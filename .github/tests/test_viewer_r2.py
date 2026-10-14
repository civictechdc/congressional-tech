"""Publication failures must leave the current viewer and raw catalog intact."""
from datetime import datetime, timezone
import importlib.util
import io
import json
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


Body = io.BytesIO


class Store:
    def __init__(self, manifest):
        self.data = {'indexes/catalog.json': publication.encoded(manifest['source_manifest'])}
        self.writes = []
        self.corrupt = False
        self.raw_etag = 'raw-v1'

    def get_object(self, *, Bucket, Key):
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
        self.data[Key] = Body

    def upload_file(self, path, bucket, key, ExtraArgs):
        self.put_object(Bucket=bucket, Key=key, Body=Path(path).read_bytes())

    def download_file(self, bucket, key, path):
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


def test_unchanged_catalog_does_not_download_repack_or_write(prepared):
    store = Store(prepared[1])
    store.data['viewer-publications/manifest.json'] = publication.encoded({
        'publisher_version': publication.PUBLISHER_VERSION, 'source_manifest': prepared[1]['source_manifest']})
    assert publication.run(store)['status'] == 'unchanged'
    assert store.writes == []


def test_archiving_old_review_does_not_change_latest(prepared, monkeypatch):
    store = Store(prepared[1])
    assert publish(store, prepared, monkeypatch, archive_only=True)['status'] == 'archived'
    assert 'viewer-publications/manifest.json' not in store.data


def test_public_verification_identifies_the_publisher_without_credentials():
    request = publication.public_request('https://data.test/manifest.json', {'Origin': 'https://civictechdc.github.io'})
    assert request.get_header('User-agent') == publication.USER_AGENT
    assert request.get_header('Authorization') is None


def test_legacy_bootstrap_never_downloads_a_different_catalog(prepared, tmp_path, monkeypatch):
    calls = []
    def read(request, **kwargs):
        calls.append(request.full_url)
        return Body(publication.encoded(prepared[1]))
    monkeypatch.setattr(publication.urllib.request, 'urlopen', read)
    assert publication.bootstrap_pages({'catalog_id': 'different'}, tmp_path) is None
    assert calls == [publication.PAGES_MANIFEST]


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
