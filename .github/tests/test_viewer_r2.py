"""Publication failures must leave the current viewer and raw catalog intact."""
from datetime import datetime, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys

from botocore.exceptions import ClientError
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'apps/site/scripts/publish-viewer-r2.py'
spec = importlib.util.spec_from_file_location('viewer_r2', SCRIPT)
publication = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publication)


def test_fresh_cli_preparation_uses_shared_release_identity(tmp_path):
    # Package paths alone reproduce the workflow; pytest's scripts path must not
    # supply a missing CLI bootstrap dependency.
    code = '''
import importlib.util, json, runpy, sys
from pathlib import Path
import boto3
import viewer_publication.attempt as attempts

script = Path(sys.argv[1])
report = Path(sys.argv[2])
sys.path.insert(0, str(script.parent))  # Python adds this for a direct script.
boto3.client = lambda *args, **kwargs: object()
attempts.record_input = lambda publisher, client, key, optional=False: {
    'value': None if optional else {'version': 1}, 'etag': 'fixture',
    'modified': None, 'sha256': 'a' * 64}
original = attempts.content_identity
def check_identity(publisher):
    identity = original(publisher)
    spec = importlib.util.spec_from_file_location('expected_identity', script.parents[3] / 'scripts/viewer_release_identity.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    assert identity == {'version': 1, 'publisher_version': publisher.PUBLISHER_VERSION,
        'implementation': helper.hashlib.sha256(helper.encoded(helper.source_files(script.parents[3]))).hexdigest(),
        'dependencies': helper.installed_runtime()}
    assert Path(sys.modules['viewer_release_identity'].__file__).resolve() == Path(helper.__file__).resolve()
    print(json.dumps(identity))
    return identity
attempts.content_identity = check_identity
sys.argv = [str(script), 'prepare', '--directory', str(report.parent / 'preparation'),
    '--run-id', '123', '--run-attempt', '1', '--report', str(report)]
try:
    runpy.run_path(str(script), run_name='__main__')
except ValueError as error:
    assert str(error) == 'Viewer updates require explicitly adopted native catalog storage'
else:
    raise AssertionError('Legacy catalog must still be refused')
assert json.loads(report.read_text())['error_type'] == 'ValueError'
assert not (report.parent / 'preparation').exists()
'''
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('DOCSPEC_', 'GITHUB_', 'R2_', 'AWS_', 'CLOUDFLARE_'))}
    env['PYTHONPATH'] = os.pathsep.join(str(path) for path in sorted((ROOT / 'packages').glob('*/src')))
    env.update(CLOUDFLARE_ACCOUNT_ID='fixture', R2_ACCESS_KEY_ID='fixture', R2_SECRET_ACCESS_KEY='fixture')
    result = subprocess.run([sys.executable, '-c', code, str(SCRIPT), str(tmp_path / 'outcome.json')],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['publisher_version'] == publication.PUBLISHER_VERSION


Body = io.BytesIO


class Store:
    def __init__(self, manifest):
        self.data = {'indexes/catalog.json': publication.encoded(manifest['source_manifest'])}
        self.writes = []
        self.conditions = []
        self.reads = []
        self.downloads = []
        self.corrupt = False
        self.raw_etag = 'raw-v1'

    def get_object(self, *, Bucket, Key):
        self.reads.append(Key)
        assert Bucket == publication.BUCKET
        if Key not in self.data:
            raise ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject')
        data = self.data[Key]
        if self.corrupt and Key.endswith('browse.parquet'):
            data += b'corrupt'
        return {'Body': Body(data), 'ContentLength': len(data),
                'ETag': self.raw_etag if Key == 'indexes/catalog.json' else 'viewer-v1',
                'LastModified': datetime(2026, 10, 13, tzinfo=timezone.utc)}

    def put_object(self, *, Bucket, Key, Body, **kw):
        assert Key.startswith(publication.PREFIX), 'Attempted write outside viewer namespace'
        if (kw.get('IfNoneMatch') == '*' and Key in self.data) or (kw.get('IfMatch') and kw['IfMatch'] != 'viewer-v1'):
            raise ClientError({'Error': {'Code': 'PreconditionFailed'}}, 'PutObject')
        self.writes.append(Key)
        self.conditions.append((Key,kw.get('IfMatch'),kw.get('IfNoneMatch')))
        self.data[Key] = Body if isinstance(Body,bytes) else Body.read()

    def upload_file(self, path, bucket, key, ExtraArgs):
        self.put_object(Bucket=bucket, Key=key, Body=Path(path).read_bytes())

    def download_file(self, bucket, key, path):
        self.downloads.append(key)
        with self.get_object(Bucket=bucket, Key=key)['Body'] as stream:
            Path(path).write_bytes(stream.read())


@pytest.fixture(scope='module')
def prepared(tmp_path_factory):
    root = tmp_path_factory.mktemp('viewer-r2')
    subprocess.run([sys.executable, str(SCRIPT.with_name('filename-test-fixture.py')), str(root)], check=True, capture_output=True)
    return root / 'public', json.loads((root / 'public/manifest.json').read_text())


def publish(store, prepared, monkeypatch, **kwargs):
    monkeypatch.setattr(publication.urllib.request, 'urlopen', lambda url, **kw: Body(store.data['viewer-publications/manifest.json']))
    root, manifest = prepared
    return publication.upload(store, root, manifest, previous_etag=None, selected_etag='raw-v1', probe=lambda *a: None, **kwargs)


def test_complete_upload_selects_only_after_readback_and_keeps_catalog_identity(prepared, monkeypatch):
    store = Store(prepared[1])
    result = publish(store, prepared, monkeypatch)
    assert result['status'] == 'published'
    assert store.writes[-1] == 'viewer-publications/manifest.json'
    selected = json.loads(store.data[store.writes[-1]])
    assert selected['source_manifest'] == prepared[1]['source_manifest']
    assert selected['catalog_id'] == prepared[1]['info']['catalog_id']
    assert 'indexes/catalog.json' not in store.writes


def test_corrupt_readback_does_not_select_partial_publication(prepared, monkeypatch):
    store = Store(prepared[1]); store.corrupt = True
    with pytest.raises(ValueError, match='readback'):
        publish(store, prepared, monkeypatch)
    assert 'viewer-publications/manifest.json' not in store.data


def test_interrupted_download_does_not_select_partial_publication(prepared, monkeypatch):
    store = Store(prepared[1])
    def interrupted(bucket, key, path):
        Path(path).write_bytes(b'partial response')
        raise OSError('connection lost')
    monkeypatch.setattr(store, 'download_file', interrupted)
    with pytest.raises(OSError, match='connection lost'):
        publish(store, prepared, monkeypatch)
    assert 'viewer-publications/manifest.json' not in store.data


def test_raw_catalog_advancing_during_upload_prevents_stale_selection(prepared, monkeypatch):
    store = Store(prepared[1]); store.raw_etag = 'raw-v2'
    assert publish(store, prepared, monkeypatch)['status'] == 'superseded'
    assert 'viewer-publications/manifest.json' not in store.data


def test_other_viewer_publisher_wins_without_being_overwritten(prepared, monkeypatch):
    store = Store(prepared[1]); store.data['viewer-publications/manifest.json'] = b'{"newer":true}'
    assert publish(store, prepared, monkeypatch)['status'] == 'superseded'
    assert json.loads(store.data['viewer-publications/manifest.json']) == {'newer': True}


def public_store(monkeypatch, store):
    class Public(Body):
        headers = {'Access-Control-Allow-Origin': '*'}
    monkeypatch.setattr(publication, 'open_public', lambda request, **kw: Public(
        store.data[publication.PREFIX + request.full_url.removeprefix(publication.PUBLIC_URL)]))


def seed_recoveries(prepared, monkeypatch, accepted=None):
    store = Store(prepared[1])
    if accepted is not None:
        store.data[publication.ACCEPTED_KEY] = publication.encoded({'version': 1, 'recoveries': accepted})
    publish(store, prepared, monkeypatch)
    public_store(monkeypatch, store)
    store.reads.clear(); store.writes.clear(); store.downloads.clear()
    return store


def poll(store):
    return publication.check_selected_publication(store, json.loads(store.data[publication.PREFIX+'manifest.json']))


def mapping():
    return {'original_url': 'https://committee.test/file.pdf', 'recovered_url': 'http://committee.test/file.pdf',
            'body_key': 'bodies/sha256/aa/' + 'a' * 64 + '.gz', 'kind': 'pdf',
            'recovery_status': 'recovered', 'recovery_basis': 'user_accepted_url_variant'}


@pytest.mark.parametrize('accepted', [None, [], [mapping()]])
def test_unchanged_catalog_reads_no_tables_and_performs_no_writes(prepared, monkeypatch, accepted):
    store = seed_recoveries(prepared, monkeypatch, accepted)
    assert poll(store)['status'] == 'unchanged'
    assert store.writes == [] and store.downloads == []
    assert not any(key.endswith(('.parquet', '.bin')) for key in store.reads)


@pytest.mark.parametrize('change', ['edit', 'delete_row', 'remove_object', 'empty'])
def test_every_mapping_change_rebuilds_only_recovery_index(prepared, monkeypatch, change):
    rows = [mapping(), dict(mapping(), original_url='https://committee.test/another.pdf')]
    store = seed_recoveries(prepared, monkeypatch, rows)
    if change == 'edit':
        rows[0]['kind'] = 'doc'
    elif change == 'delete_row':
        rows.pop()
    elif change == 'empty':
        rows.clear()
    if change == 'remove_object':
        del store.data[publication.ACCEPTED_KEY]
    else:
        store.data[publication.ACCEPTED_KEY] = publication.encoded({'version': 1, 'recoveries': rows})
    assert poll(store)['status'] == 'recovery_preparation_required'
    assert store.downloads == [] and store.writes == []


def test_corrupted_selected_status_refuses_reuse_without_table_download(prepared, monkeypatch):
    store = seed_recoveries(prepared, monkeypatch, [mapping()])
    pointer = json.loads(store.data[publication.PREFIX + 'manifest.json'])
    store.data[publication.PREFIX + pointer['recovery']['path']] = b'{}'
    with pytest.raises(ValueError, match='hash mismatch|declared byte length'):
        poll(store)
    assert store.downloads == [] and store.writes == []


@pytest.mark.parametrize('key', ['indexes/catalog.json', publication.PREFIX + 'manifest.json', publication.ACCEPTED_KEY])
def test_mutable_identity_changes_during_noop_refuse_stale_status(prepared, monkeypatch, key):
    store = seed_recoveries(prepared, monkeypatch, [mapping()])
    original = publication.verify_recovery_status
    def advance(*args, **kwargs):
        result = original(*args, **kwargs)
        store.data[key] = publication.encoded({'advanced': True})
        return result
    monkeypatch.setattr(publication, 'verify_recovery_status', advance)
    with pytest.raises(ValueError, match='changed|differs'):
        poll(store)
    assert store.writes == [] and store.downloads == []


def test_invalid_accepted_mapping_refuses_before_table_reads(prepared, monkeypatch):
    store = seed_recoveries(prepared, monkeypatch, [mapping()])
    store.data[publication.ACCEPTED_KEY] = publication.encoded({'version': 99, 'recoveries': []})
    with pytest.raises(ValueError, match='Invalid accepted'):
        poll(store)
    assert store.downloads == [] and store.writes == []


def test_public_verification_identifies_the_publisher_without_credentials():
    request = publication.public_request('https://data.test/manifest.json', {'Origin': 'https://civictechdc.github.io'})
    assert request.get_header('User-agent') == publication.USER_AGENT
    assert request.get_header('Authorization') is None


def test_public_reads_retry_transient_service_failures(monkeypatch):
    attempts = []
    def read(request, **kwargs):
        attempts.append(request.full_url)
        if len(attempts) < 3:
            raise publication.urllib.error.HTTPError(request.full_url, 503, 'Unavailable', {}, None)
        return Body(b'ok')
    monkeypatch.setattr(publication.urllib.request, 'urlopen', read)
    monkeypatch.setattr(publication.time, 'sleep', lambda seconds: None)
    with publication.open_public(publication.public_request('https://data.test/manifest.json')) as response:
        assert response.read() == b'ok'
    assert len(attempts) == 3


@pytest.mark.parametrize('status', ['corrupt', 'missing', 'no_cors'])
def test_public_recovery_failure_prevents_first_selection(prepared, monkeypatch, status):
    store = Store(prepared[1])
    class Public(Body):
        headers = {'Access-Control-Allow-Origin': '*'}
    def read(request, **kwargs):
        key = publication.PREFIX + request.full_url.removeprefix(publication.PUBLIC_URL)
        if key.endswith('recovery-status.json'):
            if status == 'missing':
                raise OSError('recovery unavailable')
            result = Public(b'corrupt' if status == 'corrupt' else store.data[key])
            if status == 'no_cors':
                result.headers = {}
            return result
        return Public(store.data[key])
    monkeypatch.setattr(publication, 'open_public', read)
    with pytest.raises((ValueError, OSError), match='recovery'):
        publication.upload(store, prepared[0], prepared[1], previous_etag=None, selected_etag='raw-v1')
    assert publication.PREFIX + 'manifest.json' not in store.data


def test_plain_sdk_payloads_use_original_conditional_single_put_and_full_readback(prepared,monkeypatch):
    store=Store(prepared[1])
    monkeypatch.setattr(store,'upload_file',lambda *a,**kw:pytest.fail('managed multipart upload bypass'))
    assert publish(store,prepared,monkeypatch)['status']=='published'
    payloads=[condition for condition in store.conditions if condition[0].endswith(('.parquet','.bin'))]
    assert payloads and all(item[2]=='*' and item[1] is None for item in payloads)
    assert all(key in store.downloads for key,_,_ in payloads)


def test_sdk_retry_policy_refuses_before_any_publication_write(prepared,monkeypatch):
    from types import SimpleNamespace
    store=Store(prepared[1]);store.meta=SimpleNamespace(config=SimpleNamespace(retries={'total_max_attempts':2}))
    with pytest.raises(ValueError,match='retries must be disabled'):
        publish(store,prepared,monkeypatch)
    assert store.writes==[]
