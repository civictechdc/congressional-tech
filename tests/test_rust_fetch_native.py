"""Exercise the compiled Rust transport against loopback only; no publisher calls."""

from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import gzip
import os
import threading
import time

import pytest

from congress_api.models.content import RawContent
from congress_api.transport.rust_fetch import RustFetcher
from congress_api.transport.source_capture import fetch_source


BINARY = os.environ.get('SOURCE_FETCH_BINARY')
pytestmark = pytest.mark.skipif(not BINARY, reason='Set SOURCE_FETCH_BINARY to run native loopback checks')


@pytest.fixture
def server():
    starts = []
    running = 0
    peak = 0
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):
            pass

        def do_GET(self):
            nonlocal running, peak
            with lock:
                starts.append(time.monotonic())
                running += 1
                peak = max(peak, running)
            try:
                time.sleep(0.15)
                if self.path == '/redirect':
                    self.send_response(302)
                    self.send_header('Location', '/done')
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                body = b'%PDF-1.7\n' + b'x' * (8192 if self.path in {'/large', '/gzip-large'} else 10) + b'\n%%EOF'
                compressed = self.path.startswith('/gzip')
                if compressed:
                    body = gzip.compress(body, mtime=0)
                self.send_response(200)
                self.send_header('Content-Type', 'application/pdf')
                if compressed:
                    self.send_header('Content-Encoding', 'gzip')
                self.send_header('Link', 'one')
                self.send_header('Link', 'two')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                with lock:
                    running -= 1

    class Server(ThreadingHTTPServer):
        request_queue_size = 128
        daemon_threads = True

    http = Server(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{http.server_port}', starts, lambda: peak
    http.shutdown()
    http.server_close()
    thread.join()


def test_native_60_files_per_second_is_concurrent_and_bounded(server):
    url, starts, peak = server
    with RustFetcher(BINARY, files_per_second=60, workers=80) as fetcher:
        def get(i):
            with fetcher._request(f'{url}/{i}', 'direct') as response:
                assert response.status_code == 200
                assert b'%%EOF' in b''.join(response.iter_content(1024))
                assert [h['value'] for h in response.capture_metadata['response_header_items'] if h['name'] == 'link'] == ['one', 'two']
        with ThreadPoolExecutor(max_workers=80) as pool:
            list(pool.map(get, range(120)))
        assert not list(fetcher.root.glob('*.body'))
    starts.sort()
    elapsed = starts[-1] - starts[0]
    assert len(starts) == 120
    assert peak() > 1
    # Rust's virtual-clock test asserts exact slots; this checks real network throughput.
    assert 1.9 <= elapsed < 4.0
    print(f'Native starts: {119 / elapsed:.2f}/s; peak simultaneous server requests: {peak()}')


def test_native_declared_size_limit_never_becomes_a_complete_capture(server, monkeypatch):
    url, _, _ = server
    monkeypatch.setattr('congress_api.transport.source_capture.allowed_url', lambda value: value)
    with RustFetcher(BINARY, max_bytes=1024) as fetcher:
        result = fetch_source(url + '/large', transport='direct', max_bytes=1024, session=fetcher, pace=False)
        assert not result['complete'] and result['error'] == 'response_limit'
        assert RawContent.model_validate(result['content']).body_bytes() == b''
        assert result['source_metadata']['body_read_skipped'] == 'declared_size_limit'
        assert result['source_metadata']['declared_body_bytes'] > 1024
        assert not list(fetcher.root.glob('*.body'))


def test_native_redirect_continues_immediately_but_next_file_waits(server, monkeypatch):
    url, starts, _ = server
    monkeypatch.setattr('congress_api.transport.source_capture.allowed_url', lambda value: value)
    with RustFetcher(BINARY, files_per_second=1) as fetcher:
        result = fetcher.fetch(url + '/redirect', transport='direct')
        fetcher.fetch(url + '/second', transport='direct')
        assert fetcher.sequence == 3 and fetcher.file_dispatches == 2
    assert result['complete'] and result['url'].endswith('/done')
    assert len(result['redirects']) == 1
    assert len(starts) == 3
    assert starts[1] - starts[0] < 0.8
    assert starts[2] - starts[0] >= 0.95


@pytest.mark.parametrize('path,complete', [('/gzip', True), ('/gzip-large', False)])
def test_compression_preserves_original_headers_and_limits_decoded_bytes(server, monkeypatch, path, complete):
    url, _, _ = server
    monkeypatch.setattr('congress_api.transport.source_capture.allowed_url', lambda value: value)
    with RustFetcher(BINARY, max_bytes=1024) as fetcher:
        result = fetch_source(url + path, transport='direct', max_bytes=1024, session=fetcher, pace=False)
    body = RawContent.model_validate(result['content']).body_bytes()
    assert body.startswith(b'%PDF-1.7')
    assert result['response_headers']['content-encoding'] == 'gzip'
    assert 'content-length' in result['response_headers']
    assert result['complete'] == complete
    if not complete:
        assert len(body) == 1024 and result['error'] == 'response_limit'


def test_spooled_pipeline_downloads_ahead_with_default_memory_budget(server, monkeypatch):
    from functools import partial
    from congress_api.acquisition.raw_sync import run_sync
    from congress_api.retention.raw_archive import Archive
    from test_raw_source_sync import MemoryStore

    url, starts, peak = server
    # Only the fixture server is accepted; production scope checks stay intact.
    monkeypatch.setattr('congress_api.transport.source_capture.allowed_url',
                        lambda value: value if value.startswith(url + '/') else None)
    monkeypatch.setattr('congress_api.retention.raw_archive.allowed_url',
                        lambda value: value if value.startswith(url + '/') else None)
    with RustFetcher(BINARY, workers=16) as fetcher:
        store = MemoryStore()
        result = run_sync(Archive(store, 'native-spool'),
            [{'url': f'{url}/{i}'} for i in range(16)], workers=16, download_workers=16,
            fetch_spooled=partial(fetcher.fetch_spooled, transport='direct'))
        assert result['saved'] == len(starts) == 16
        assert 4 <= peak() <= 16
        assert result['peak_body_payload_reservation_bytes'] <= 512*1024**2
        assert result['peak_spool_reservation_bytes'] <= 2*1024**3
        assert not list(fetcher.root.glob('*.body'))


def test_native_body_deadline_preserves_timeout_reason_and_partial_bytes():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Length', '20')
            self.end_headers()
            self.wfile.write(b'%PDF-1.7\n')
            self.wfile.flush()
            time.sleep(0.8)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with RustFetcher(BINARY, request_timeout=0.25) as fetcher:
            with fetcher._request(f'http://127.0.0.1:{server.server_port}/slow', 'direct') as response:
                assert response.capture_error == 'timeout'
                assert not response.capture_complete
                assert b''.join(response.iter_content(1024)) == b'%PDF-1.7\n'
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_native_interrupted_body_is_not_a_timeout():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Length', '200')
            self.end_headers()
            self.wfile.write(b'%PDF truncated')
            self.wfile.flush()
            self.close_connection = True

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with RustFetcher(BINARY) as fetcher:
            with fetcher._request(f'http://127.0.0.1:{server.server_port}/cut', 'direct') as response:
                assert response.capture_error == 'body_error'
                assert not response.capture_complete
                assert b''.join(response.iter_content(1024)) == b'%PDF truncated'
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
