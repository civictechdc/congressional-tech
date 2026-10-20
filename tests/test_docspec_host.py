"""Transport lifetimes and refusals, including real maintained native execution."""
from copy import deepcopy
import os
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import httpx
import pyarrow as pa
import pytest

from congress_api.retention.docspec import DocSpecFailure, NativeDatasets
from congress_api.retention.docspec_host import ArrowResponse, Host
from native_test_helpers import native_test_client


@pytest.fixture
def native(tmp_path):
    binary = os.environ.get('DOCSPEC_BINARY') or shutil.which('docspec')
    if not binary:
        pytest.skip('Set DOCSPEC_BINARY to the maintained native binary')
    with native_test_client(binary, tmp_path / 'native') as client:
        yield client


def candidate(native):
    table = pa.table({'row': [0, 1, 2], 'values': [['same', None, 'same'], None, []]})
    return native.run_table(table, dataset='host-test', operation='initial', definition='nested-v1')


def test_real_host_shared_settings_conflicts_and_last_owner_cleanup(native):
    pin = candidate(native)
    host = native._execution_host()
    other = NativeDatasets(native.binary, native.workspace, limits=native.limits)
    conflict = NativeDatasets(native.binary, native.workspace, limits=native.limits, timeout=1)
    try:
        assert other.release('host-test', 'initial') == pin
        assert other._host is host
        with pytest.raises(ValueError, match='different settings'):
            conflict.latest('host-test')
        native.close()
        assert host.process.poll() is None
        assert other.latest('host-test') == pin
    finally:
        other.close()
        conflict.close()
    assert host.process.poll() == 0
    assert host.client.is_closed
    with pytest.raises(RuntimeError, match='closed'):
        native.latest('host-test')
    # A new explicit client can reacquire the released workspace.
    with NativeDatasets(native.binary, native.workspace, limits=native.limits) as fresh:
        assert fresh.latest('host-test') == pin


def test_same_config_path_with_changed_contents_refuses_live_host_reuse(native):
    candidate(native)
    native.limits.write_text(native.limits.read_text() + '\n')
    with NativeDatasets(native.binary, native.workspace, limits=native.limits) as other:
        with pytest.raises(ValueError, match='different settings'):
            other.latest('host-test')
    assert native._host.process.poll() is None


def test_real_read_cancellation_releases_http_body_and_host_stays_usable(native):
    pin = candidate(native)
    host = native._host
    with pytest.raises(KeyboardInterrupt):
        with native.source_batches(pin) as reader:
            response, = host.responses
            assert reader.read_next_batch().num_rows > 0
            raise KeyboardInterrupt()
    assert response.is_closed
    assert not host.responses
    with native.source_batches(pin) as reader:
        assert reader.read_all().num_rows == 3
    assert not list(native.workspace.glob('request-*'))
    assert not list(native.workspace.rglob('*.arrow'))


def test_real_close_cancels_outstanding_response_and_stops_host(native):
    pin = candidate(native)
    with native.source_batches(pin):
        host = native._host
        response, = host.responses
        native.close()
        assert response.is_closed
        assert host.process.poll() == 0


def test_closing_one_shared_client_cancels_only_its_read(native):
    pin = candidate(native)
    with NativeDatasets(native.binary, native.workspace, limits=native.limits) as other:
        assert other.latest('host-test') == pin
        with native.source_batches(pin), other.source_batches(pin) as reader:
            closed_response, = native._responses
            other_response, = other._responses
            native.close()
            assert closed_response.is_closed
            assert not other_response.is_closed
            assert reader.read_all().num_rows == 3
            assert other._host.process.poll() is None


def test_real_wrong_pin_refuses_before_body_and_schema_refuses(native, monkeypatch):
    pin = candidate(native)
    host = native._host
    wrong = deepcopy(pin)
    wrong['manifest']['digest'] = '0' * 64
    with monkeypatch.context() as scoped:
        scoped.setattr(host.client, 'stream', lambda *a, **kw: pytest.fail('wrong pin must not read'))
        with pytest.raises(ValueError, match='exact pin'):
            with native.source_batches(wrong):
                pytest.fail('wrong pin accepted')
    with pytest.raises(ValueError, match='storage schema'):
        with native.source_batches(pin, schema=pa.schema([('row', pa.string())])):
            pytest.fail('wrong schema accepted')
    assert not host.responses


def test_real_host_exit_preserves_failure_without_restart(native):
    candidate(native)
    process = native._host.process
    process.terminate()
    process.wait(timeout=5)
    with pytest.raises(DocSpecFailure) as error:
        native.latest('host-test')
    assert error.value.returncode == process.returncode
    assert native._host.process is process


def test_real_native_refusal_retains_code_message_and_http_status(native, tmp_path):
    with pytest.raises(DocSpecFailure) as error:
        native.run(dict(dataset='absent', operation='initial', definition='v1',
                        sql='SELECT * FROM input', input=str(tmp_path / 'absent.parquet'),
                        expected_digest='0' * 64))
    assert error.value.returncode == 422
    assert 'code' in error.value.stderr and 'message' in error.value.stderr
    assert native._host.process.poll() is None


def test_real_startup_refusal_preserves_native_diagnostic(native, tmp_path):
    with NativeDatasets(native.binary, tmp_path / 'invalid', limits=tmp_path / 'missing.json') as client:
        with pytest.raises(DocSpecFailure, match='No such file'):
            client.latest('unused')
        assert client._host is None


def test_startup_timeout_reaps_child(tmp_path):
    executable = tmp_path / 'sleep-host'
    executable.write_text('#!/usr/bin/env python3\nimport time\ntime.sleep(60)\n')
    executable.chmod(0o700)
    # The test executable never opens a listener. Real Popen plus timeout exercises cleanup.
    with NativeDatasets(executable, tmp_path / 'workspace', timeout=0.1) as client:
        with pytest.raises(TimeoutError, match='startup timed out'):
            client.latest('unused')
        assert client._host is None


@pytest.mark.parametrize('bad', ['docspec-dataset', 'docspec-version', 'docspec-manifest-blake3', 'content-type'])
def test_stream_header_identity_refuses_before_arrow_decode(tmp_path, monkeypatch, bad):
    pin = dict(dataset=dict(dataset='fixture'), id='initial', manifest=dict(digest='digest'))
    headers = {'docspec-dataset': 'fixture', 'docspec-version': 'initial',
               'docspec-manifest-blake3': 'digest', 'content-type': 'application/vnd.apache.arrow.stream'}
    headers[bad] = 'wrong'
    with NativeDatasets('unused', tmp_path) as native, httpx.Client(
            base_url='http://fixture', transport=httpx.MockTransport(
                lambda request: httpx.Response(200, headers=headers, content=b'not Arrow'))) as client:
        host = SimpleNamespace(client=client, responses=set(), check_response=Host.check_response,
                               request=lambda *args: pin)
        monkeypatch.setattr(native, '_execution_host', lambda: host)
        with pytest.raises(ValueError, match='exact pin'):
            with native.source_batches(pin):
                pytest.fail('bad stream accepted')
        assert not host.responses


@pytest.mark.parametrize('failure', ['missing-arrow-end', 'http-abort'])
def test_premature_stream_never_becomes_success(tmp_path, monkeypatch, failure):
    pin = dict(dataset=dict(dataset='fixture'), id='initial', manifest=dict(digest='digest'))
    output = pa.BufferOutputStream()
    table = pa.table({'row': [1, 1, None]})
    with pa.ipc.new_stream(output, table.schema) as writer:
        writer.write_table(table)
    body = output.getvalue().to_pybytes()

    class Body(httpx.SyncByteStream):
        def __iter__(self):
            yield body[:-8] if failure == 'missing-arrow-end' else body
            if failure == 'http-abort':
                raise httpx.RemoteProtocolError('injected premature HTTP close')

    headers = {'docspec-dataset': 'fixture', 'docspec-version': 'initial',
               'docspec-manifest-blake3': 'digest', 'content-type': 'application/vnd.apache.arrow.stream'}
    with NativeDatasets('unused', tmp_path) as native, httpx.Client(
            base_url='http://fixture', transport=httpx.MockTransport(
                lambda request: httpx.Response(200, headers=headers, stream=Body()))) as client:
        host = SimpleNamespace(client=client, responses=set(), check_response=Host.check_response,
                               request=lambda *args: pin)
        monkeypatch.setattr(native, '_execution_host', lambda: host)
        with pytest.raises((OSError, httpx.RemoteProtocolError)):
            with native.source_batches(pin) as reader:
                reader.read_all()
        assert not host.responses


def test_read_only_native_routes_use_maintained_requests(tmp_path, monkeypatch):
    requests = []
    def request(method, path, **kwargs):
        requests.append((method, path, kwargs))
        return {'native': True}
    with NativeDatasets('unused', tmp_path) as native:
        monkeypatch.setattr(native, '_execution_host', lambda: SimpleNamespace(request=request))
        assert native.inspect('fixture') == {'native': True}
        assert native.inspect_retention([]) == {'native': True}
        assert native.plan_removal({'dataset': 'fixture'}) == {'native': True}
    assert [(method, path) for method, path, _ in requests] == [
        ('GET', '/datasets/fixture'), ('POST', '/retention/inspect'),
        ('POST', '/retention/removal/plan')]


@pytest.mark.parametrize('kind', ['stalled', 'periodic'])
def test_public_http_timeouts_close_stalled_and_slow_periodic_responses(kind):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Length', '20')
            self.end_headers()
            try:
                for _ in range(20):
                    time.sleep(0.3 if kind == 'stalled' else 0.03)
                    self.wfile.write(b'x')
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    response = None
    started = time.monotonic()
    try:
        with httpx.Client(timeout=0.1, trust_env=False) as client:
            with pytest.raises(httpx.ReadTimeout if kind == 'stalled' else TimeoutError):
                with client.stream('GET', f'http://127.0.0.1:{server.server_port}/') as response:
                    with ArrowResponse(response, deadline=time.monotonic() + 0.15) as stream:
                        stream.read()
        assert response.is_closed
        # Periodic chunks arrive under the idle limit but still exceed the wall deadline.
        assert time.monotonic() - started < 0.5
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
