"""The local adapter retries reads without changing preparation admission."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from botocore.awsrequest import AWSResponse
from botocore.exceptions import ConnectionClosedError

from congress_api.retention.r2 import R2Store, _stream_read_attempts
from congress_shared.storage import connect_r2
from viewer_publication import attempt
from viewer_publication.release_identity import source_files

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('prepare_local_release',
    ROOT / 'scripts/publication/prepare_local_release.py')
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


class Transport:
    def __init__(self, failures):
        self.failures, self.calls = failures, 0

    def send(self, request):
        self.calls += 1
        if self.calls <= self.failures:
            raise ConnectionClosedError(endpoint_url=request.url)
        return AWSResponse(request.url, 200, {'content-length': '2', 'etag': 'fixture'}, io.BytesIO(b'{}'))


def sdk_client():
    return connect_r2(endpoint_url='https://unused.invalid', access_key_id='fixture',
        secret_access_key='fixture', retries=dict(adapter.RETRIES))


@pytest.mark.parametrize('failures,expected_calls', [(1, 2), (99, 3)])
def test_real_sdk_bounds_connection_closed_retries(failures, expected_calls):
    # Stubber bypasses the retry machinery; replace only its HTTP transport so
    # the real SDK standard retry handler decides whether to send again.
    sdk = sdk_client()
    transport = Transport(failures)
    sdk._endpoint.http_session = transport
    client = adapter.ReadOnlyClient(sdk)
    R2Store(client, 'fixture')  # Maintained retry hooks can use wrapped metadata.
    assert _stream_read_attempts(client) == 3
    if failures == 1:
        response = client.get_object(Bucket='fixture', Key='catalog.json')
        with response['Body'] as body:
            assert body.read() == b'{}'
        assert response['ResponseMetadata']['RetryAttempts'] == 1
    else:
        with pytest.raises(ConnectionClosedError):
            client.get_object(Bucket='fixture', Key='catalog.json')
    assert transport.calls == expected_calls


def test_every_other_sdk_operation_is_refused_before_transport():
    sdk = sdk_client()
    transport = Transport(0)
    sdk._endpoint.http_session = transport
    client = adapter.ReadOnlyClient(sdk)
    for name in set(sdk.meta.method_to_api_mapping) - set(adapter.READ_OPERATIONS):
        with pytest.raises(PermissionError, match='refuses SDK operation'):
            getattr(client, name)(Bucket='fixture')
    for name in ('_make_api_call', 'get_paginator', 'upload_file', 'download_file', 'delete_objects'):
        with pytest.raises(PermissionError):
            getattr(client, name)
    assert transport.calls == 0


def flags(tmp_path, *, resume=True):
    return ['--directory', str(tmp_path / 'prepared'), '--native-config', str(tmp_path / 'runtime.json'),
        '--run-id', 'original', '--run-attempt', '1', '--public-url', 'https://fixture.invalid/',
        '--renderer-upgrade', *(['--resume-preparation'] if resume else []),
        '--report', str(tmp_path / 'result.json')]


def test_adapter_forwards_original_resume_and_emits_separate_operation_receipt(tmp_path, monkeypatch, capsys):
    native, client = object(), object()
    monkeypatch.setattr(adapter.NativeDatasets, 'from_config', lambda path: native)
    monkeypatch.setattr(adapter, 'make_client', lambda: client)
    result = {'status': 'prepared', 'preparation_sha256': 'a' * 64}
    def prepare(publisher, actual_client, directory, **options):
        assert publisher is adapter.publisher and actual_client is client
        assert directory == tmp_path / 'prepared'
        assert options.pop('native') is native
        callback = options.pop('stage_event')
        assert options == dict(run_id='original', run_attempt='1', public_url='https://fixture.invalid/',
            renderer_upgrade=True, resume_preparation=True)
        callback(dict(event='stage_completed', stage='component_scope'))
        return result
    monkeypatch.setattr(adapter.attempt, 'prepare', prepare)
    assert adapter.main(flags(tmp_path)) == 0
    assert json.loads((tmp_path / 'result.json').read_bytes()) == result
    receipt = json.loads((tmp_path / 'prepared.local-prepare-operation.json').read_bytes())
    assert receipt['kind'] == 'local_preparation_operation'
    assert receipt['status'] == 'prepared'
    assert receipt['adapter_sha256'] == hashlib.sha256(Path(adapter.__file__).read_bytes()).hexdigest()
    assert receipt['retries'] == dict(mode='standard', total_max_attempts=3)
    assert receipt['allowed_operations'] == ['get_object', 'head_object']
    assert not (tmp_path / 'prepared').exists()  # Operational receipt cannot occupy a fresh target.
    assert 'artifact_id' not in receipt and 'binding' not in receipt
    assert 'component_scope' in capsys.readouterr().out


def test_failure_replaces_success_report_and_keeps_original_error(tmp_path, monkeypatch):
    root = tmp_path / 'prepared'
    root.mkdir()
    (tmp_path / 'result.json').write_text('{"status":"prepared"}')
    original = ValueError('native configuration changed')
    def refuse(path):
        raise original
    monkeypatch.setattr(adapter.NativeDatasets, 'from_config', refuse)
    monkeypatch.setattr(adapter, 'make_client', lambda: pytest.fail('client before native admission'))
    with pytest.raises(ValueError) as caught:
        adapter.main(flags(tmp_path))
    assert caught.value is original
    assert json.loads((tmp_path / 'result.json').read_bytes())['status'] == 'failed'
    assert json.loads((root / 'command-outcome.json').read_bytes())['error_type'] == 'ValueError'
    assert json.loads((tmp_path / 'prepared.local-prepare-operation.json').read_bytes())['status'] == 'failed'


def test_adapter_and_its_tests_are_outside_frozen_release_source_files():
    files = source_files(ROOT)
    assert 'scripts/publication/prepare_local_release.py' not in files
    assert 'scripts/publication/tests/test_prepare_local_release.py' not in files


@pytest.mark.parametrize('guard', ['selector', 'runtime'])
def test_maintained_prepare_still_refuses_changed_inputs_before_builder(tmp_path, monkeypatch, guard):
    import congress_api.retention.catalog_publication as catalog
    selected = {'version': 2}
    pub = SimpleNamespace(PREFIX='viewer/', ACCEPTED_KEY='accepted', BUCKET='fixture', PUBLISHER_VERSION=6,
        validated_accepted=lambda value: None, full_release_identity=lambda: {'runtime': 'current'})
    pub.read_identity = lambda client, key, optional=False: (
        selected if key == 'indexes/catalog.json' else None,
        'selected' if key == 'indexes/catalog.json' else None, None,
        'a' * 64 if key == 'indexes/catalog.json' else None)
    snapshot = SimpleNamespace(manifest=selected, identity={'selector_sha256': 'a' * 64}, version='selected')
    if guard == 'selector':
        snapshot.version = 'changed'
    monkeypatch.setattr(catalog, 'read_catalog', lambda *a, **k: snapshot)
    native = SimpleNamespace(execution_files=lambda: [])
    root = tmp_path / 'prepared'
    if guard == 'runtime':
        root.mkdir()
        # A real, valid continuation with a prior runtime cannot be resumed by
        # current preparation. Core compares the entire newly read binding.
        from viewer_publication.continuation import Continuation
        prior = {'run_id': 'original', 'run_attempt': '1', 'code_runtime': {'runtime': 'old'}}
        root.rmdir()
        Continuation(root, prior)
    client = adapter.ReadOnlyClient(sdk_client())
    with pytest.raises(ValueError, match='Catalog changed|continuation inputs changed'):
        attempt.prepare(pub, client, root, run_id='original', run_attempt='1',
            public_url='https://fixture.invalid/', native=native, renderer_upgrade=True,
            resume_preparation=guard == 'runtime')
    assert not (root / 'publication').exists()


def test_production_client_constructor_uses_standard_three_attempt_budget(monkeypatch):
    monkeypatch.setenv('R2_ENDPOINT_URL', 'https://unused.invalid')
    monkeypatch.setenv('R2_ACCESS_KEY_ID', 'fixture')
    monkeypatch.setenv('R2_SECRET_ACCESS_KEY', 'fixture')
    client = adapter.make_client()
    assert client.meta.config.retries == dict(mode='standard', total_max_attempts=3)
    assert client.meta.config.connect_timeout == 15
    assert client.meta.config.read_timeout == 180


def test_adapter_forwards_explicit_metadata_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter.NativeDatasets, 'from_config', lambda path: object())
    monkeypatch.setattr(adapter, 'make_client', lambda: object())
    seen = {}
    def prepare(*args, **options):
        seen.update(options)
        return {'status': 'prepared'}
    monkeypatch.setattr(adapter.attempt, 'prepare', prepare)
    cache = tmp_path / 'cache'
    assert adapter.main([*flags(tmp_path), '--metadata-cache', str(cache)]) == 0
    assert seen['metadata_cache_dir'] == cache


def test_maintained_prepare_receives_cache_without_caching_selected_control(tmp_path, monkeypatch):
    import congress_api.retention.catalog_publication as catalog
    pub = SimpleNamespace(PREFIX='viewer/', ACCEPTED_KEY='accepted', BUCKET='fixture', PUBLISHER_VERSION=6,
        validated_accepted=lambda value: None, full_release_identity=lambda: {'runtime': 'current'})
    reads = []
    def read_identity(client, key, optional=False):
        reads.append(key)
        return ({'version': 2} if key == 'indexes/catalog.json' else None, 'etag', None, 'a' * 64)
    pub.read_identity = read_identity
    cache = tmp_path / 'cache'
    original = ValueError('stop after constructing maintained cached store')
    def read_catalog(store, **options):
        assert store.cache_dir == cache
        raise original
    monkeypatch.setattr(catalog, 'read_catalog', read_catalog)
    with pytest.raises(ValueError) as caught:
        attempt.prepare(pub, adapter.ReadOnlyClient(sdk_client()), tmp_path / 'fresh',
            run_id='new', run_attempt='1', public_url='https://fixture.invalid',
            native=object(), metadata_cache_dir=cache)
    assert caught.value is original
    assert reads == ['indexes/catalog.json', 'viewer/manifest.json', 'accepted']
