"""Unknown native admission keeps producer files independently of host lifetime."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.retention.docspec import DocSpecFailure, NativeDatasets
from native_test_helpers import native_test_client


def failure(status):
    error = DocSpecFailure(['POST', '/run'], subprocess.CompletedProcess([], status or -9, stderr='fixture failure'))
    error.status_code = status
    return error


@pytest.mark.parametrize('error', [TimeoutError('deadline'), KeyboardInterrupt(),
    httpx.ReadError('lost response'), ValueError('invalid response JSON'), failure(None), failure(504)])
def test_unknown_submission_retains_exact_replay_input_and_original_failure(tmp_path, monkeypatch, error):
    native = NativeDatasets('unused', tmp_path)
    table = pa.table({'key': ['one', 'two', 'one'], 'values': [['same', None, 'same'], None, []]})
    monkeypatch.setattr(native, 'hash_input', lambda path: {'digest': 'd' * 64})
    def request(path, value, *, dispatch=None):
        dispatch['submitted'] = True
        raise error
    monkeypatch.setattr(native, '_request', request)
    with pytest.raises(type(error)) as caught:
        native.run_table(table, dataset='custody', operation='initial', definition='v1')
    assert caught.value is error
    saved = error.retained_input
    assert pq.read_table(saved['input']).equals(table)
    request = json.loads(Path(saved['request']).read_text())
    assert request == dict(dataset='custody', operation='initial', definition='v1',
        input=saved['input'], expected_digest='d' * 64, sql='SELECT * FROM input')
    assert saved['bytes'] == Path(saved['input']).stat().st_size
    native.close()
    with NativeDatasets('unused', tmp_path) as fresh:
        assert fresh.retained_producer_inputs() == [saved]
    assert any(saved['input'] in note for note in error.__notes__)


@pytest.mark.parametrize('submitted,error', [(False, TimeoutError('not sent')), (True, failure(422))])
def test_before_dispatch_and_completed_native_refusal_cleanup(submitted, error, tmp_path, monkeypatch):
    with NativeDatasets('unused', tmp_path) as native:
        monkeypatch.setattr(native, 'hash_input', lambda path: {'digest': 'd' * 64})
        def request(path, value, *, dispatch=None):
            if submitted:
                dispatch['submitted'] = True
            raise error
        monkeypatch.setattr(native, '_request', request)
        with pytest.raises(type(error)) as caught:
            native.run_table(pa.table({'key': ['one']}), dataset='custody', operation='initial', definition='v1')
        assert caught.value is error
        assert not list(tmp_path.glob('request-*'))


def test_repeated_unknown_attempts_report_actual_accumulated_bytes(tmp_path, monkeypatch):
    with NativeDatasets('unused', tmp_path) as native:
        monkeypatch.setattr(native, 'hash_input', lambda path: {'digest': 'd' * 64})
        def request(path, value, *, dispatch=None):
            dispatch['submitted'] = True
            raise TimeoutError('unknown admission')
        monkeypatch.setattr(native, '_request', request)
        for _ in range(3):
            with pytest.raises(TimeoutError):
                native.run_table(pa.table({'key': ['one']}), dataset='custody', operation='initial', definition='v1')
        saved = native.retained_producer_inputs()
        assert len(saved) == 3
        assert sum(item['bytes'] for item in saved) == sum(Path(item['input']).stat().st_size for item in saved)
        assert len({item['input'] for item in saved}) == 3
    assert all(Path(item['input']).exists() for item in saved)


def test_abrupt_client_process_loss_after_http_submission_keeps_discoverable_replay_inputs(tmp_path):
    submitted, release = threading.Event(), threading.Event()
    received = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            submitted.set()
            release.wait(timeout=15)
            try:
                self.send_response(200)
                self.end_headers()
            except (BrokenPipeError, ConnectionResetError):
                pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    workspace = tmp_path / 'native'
    script = '''import sys
import httpx
import pyarrow as pa
from congress_api.retention.docspec import NativeDatasets
from docspec_transport_helpers import host_for_client
native = NativeDatasets('unused', sys.argv[1])
native.hash_input = lambda path: {'digest': 'd' * 64}
client = httpx.Client(base_url=sys.argv[2], timeout=120, trust_env=False)
host = host_for_client(client)
native._execution_host = lambda: host
native.run_table(pa.table({'key': ['one', 'one', None]}), dataset='custody', operation='initial', definition='v1')
'''
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parent) + os.pathsep + os.environ.get('PYTHONPATH', ''))
    child = None
    try:
        with (tmp_path / 'child.stderr').open('wb') as stderr:
            child = subprocess.Popen([sys.executable, '-c', script, str(workspace),
                                      f'http://127.0.0.1:{server.server_port}'],
                                     env=environment, stdout=subprocess.DEVNULL, stderr=stderr)
            assert submitted.wait(timeout=10), 'child must submit the actual HTTP request'
            child.kill()
            assert child.wait(timeout=5) != 0
        with NativeDatasets('unused', workspace) as fresh:
            saved, = fresh.retained_producer_inputs()
        assert json.loads(Path(saved['request']).read_text()) == received[0]
        assert saved['bytes'] == Path(saved['input']).stat().st_size
        assert pq.read_table(saved['input']).to_pylist() == [{'key': 'one'}, {'key': 'one'}, {'key': None}]
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


@pytest.mark.parametrize('phase', ['admission', 'processing'])
def test_real_timeout_retains_unadmitted_input_and_recovers_admitted_input_without_producer(tmp_path, monkeypatch, phase):
    binary = os.environ.get('DOCSPEC_BINARY') or shutil.which('docspec')
    if not binary:
        pytest.skip('Set DOCSPEC_BINARY to the protocol1 test-util candidate')
    marker, resume = tmp_path / 'paused', tmp_path / 'resume'
    monkeypatch.setenv('DOCSPEC_TEST_PAUSE_BEFORE', phase)
    monkeypatch.setenv('DOCSPEC_TEST_PAUSE_MARKER', str(marker))
    monkeypatch.setenv('DOCSPEC_TEST_RESUME_MARKER', str(resume))
    native = native_test_client(binary, tmp_path / 'native')
    native._execution_host()
    native.timeout = 1
    table = pa.table({'key': ['one', 'two', 'one'], 'values': [['same', None, 'same'], None, []]})
    try:
        with pytest.raises((TimeoutError, httpx.TimeoutException, DocSpecFailure)) as caught:
            native.run_table(table, dataset='custody', operation='initial', definition='v1')
        assert marker.exists(), 'real native service must reach the selected admission handoff'
        saved = caught.value.retained_input
        request = json.loads(Path(saved['request']).read_text())
        host = native._host
        if phase == 'processing':
            # Native admission has finished; drain the actual owned task normally.
            resume.touch()
        else:
            # Kill while the real task is paused before input admission.
            host.timeout = 0.1
        native.close()
        assert host.process.poll() is not None
        assert Path(saved['input']).exists(), 'host exit never proves producer admission'
        if phase == 'processing':
            assert host.process.returncode == 0
            Path(saved['input']).unlink()  # Simulate producer loss only after confirmed admission/drain.
        with NativeDatasets(binary, native.workspace, limits=native.limits) as fresh:
            if phase == 'admission':
                missing = Path(saved['input']).with_suffix('.held')
                Path(saved['input']).rename(missing)
                with pytest.raises(DocSpecFailure):
                    fresh.run(request)
                missing.rename(saved['input'])
            pin = fresh.run(request)
            with fresh.source_batches(pin, schema=table.schema) as reader:
                assert sorted(reader.read_all().to_pylist(), key=repr) == sorted(table.to_pylist(), key=repr)
    finally:
        resume.touch()
        native.close()
