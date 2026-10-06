"""Header admission uses real HTTP responses and the existing capture writer."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import gzip
import os
import threading

import pytest

from congress_api.models.content import content_bytes
from congress_api.transport.rust_fetch import RustFetcher
from congress_api.retention.raw_archive import Archive, metadata_body_keys, prepare_capture
from test_raw_source_sync import MemoryStore

BINARY = os.environ.get('SOURCE_FETCH_BINARY')
pytestmark = pytest.mark.skipif(not BINARY, reason='Set SOURCE_FETCH_BINARY for native loopback checks')


@pytest.fixture
def server():
    release = threading.Event()
    body = b'abcdefgh'
    compressed = gzip.compress(body, mtime=0)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):
            pass

        def do_GET(self):
            payload = compressed if self.path == '/compressed' else body
            self.send_response({'/notfound': 404, '/range': 206}.get(self.path, 200))
            if self.path == '/compressed':
                self.send_header('Content-Encoding', 'gzip')
            if self.path == '/identity':
                self.send_header('Content-Encoding', 'identity')
            if self.path == '/range':
                self.send_header('Content-Range', 'bytes 0-7/16')
            if self.path != '/unknown':
                self.send_header('Content-Length', str(64 * 1024**2 + 1 if self.path == '/oversized' else len(payload)))
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.flush()
            if self.path == '/oversized':
                release.wait(3)  # No body is sent before the caller finishes.
                return
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass
            self.close_connection = True

    http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    http.daemon_threads = True
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{http.server_port}', release
    release.set()
    http.shutdown()
    http.server_close()
    thread.join()


def test_oversized_header_defers_before_body_without_fallback_and_retains_receipt(server):
    local, release = server
    requested = 'https://example.gov/oversized.pdf'
    calls = []

    class LoopbackFetcher(RustFetcher):
        def _request(self, url, transport, **options):
            assert url == requested and transport == 'direct'
            calls.append(transport)
            return super()._request(local + '/oversized', transport, **options)

    with LoopbackFetcher(BINARY, request_timeout=0.3) as fetcher:
        result, (outcome, links) = fetcher._fetch(requested, transport='auto')
        assert not list(fetcher.root.glob('*.body'))
    release.set()
    assert calls == ['direct']
    assert outcome == 'size_limit'
    assert result['error'] == 'response_limit' and not result['complete']
    assert content_bytes(result['content']) == b''
    assert result['source_metadata']['body_read_skipped'] == 'declared_size_limit'
    assert result['source_metadata']['declared_body_bytes'] == 64 * 1024**2 + 1
    assert result['response_headers']['content-length'] == str(64 * 1024**2 + 1)
    record, captures, _, _ = prepare_capture(result, outcome=outcome, links=links)
    assert metadata_body_keys(record, captures) == []
    store = MemoryStore()
    archive = Archive(store, 'header-limit')
    archive.record(result, outcome=outcome, links=links)
    archive.save()
    restored = Archive(store, 'check').state[requested]
    assert restored['outcome'] == 'size_limit' and restored['next_attempt_at']


@pytest.mark.parametrize('path,limit,complete,size', [
    ('/plain', 8, True, 8),       # Exactly at the cap is accepted.
    ('/unknown', 4, False, 4),    # Unknown length still streams with a byte cap.
    ('/compressed', 8, True, 8), # Encoded length exceeds the decoded byte limit.
    ('/compressed', 4, False, 4), # Decoded output still cannot exceed the cap.
    ('/notfound', 4, False, 4),   # Retain bounded error evidence.
    ('/range', 4, False, 4),      # A partial response is not a whole-file size claim.
])
def test_streaming_boundaries_are_preserved(server, path, limit, complete, size):
    local, _ = server
    with RustFetcher(BINARY, max_bytes=limit) as fetcher:
        with fetcher._request(local + path, 'direct') as response:
            assert response.capture_complete is complete
            assert len(b''.join(response.iter_content(1024))) == size
            assert 'body_read_skipped' not in response.capture_metadata
            if not complete:
                assert response.capture_error == 'response_limit'


def test_explicit_identity_encoding_uses_header_admission(server):
    local, _ = server
    with RustFetcher(BINARY, max_bytes=4) as fetcher:
        with fetcher._request(local + '/identity', 'direct') as response:
            assert not response.capture_complete
            assert b''.join(response.iter_content(1024)) == b''
            assert response.capture_metadata['declared_body_bytes'] == 8
