"""Prefetch hints populate only the maintained hash-validated metadata cache."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import sys
import threading
import time
from types import SimpleNamespace

from botocore.hooks import HierarchicalEmitter
import pytest
from congress_api.retention.immutable_metadata import MetadataObjects
from congress_api.retention.r2 import R2Store

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts/publication'))
import prefetch_local_metadata as prefetcher
from prepare_local_release import ReadOnlyClient


def item(value, namespace=prefetcher.ROUTES):
    raw = json.dumps(value, sort_keys=True).encode()
    digest = hashlib.sha256(raw).hexdigest()
    return prefetcher.Hint(f'indexes/native-manifests/{namespace}/{digest}.json', digest, len(raw)), raw


class Remote:
    def __init__(self, objects):
        self.objects, self.calls, self.active, self.maximum = objects, [], 0, 0
        self.lock = threading.Lock()
        self.meta = SimpleNamespace(events=HierarchicalEmitter(), config=SimpleNamespace(retries={'total_max_attempts': 3}))

    def get_object(self, *, Bucket, Key, **conditions):
        with self.lock:
            self.calls.append((Key, conditions))
            self.active += 1
            self.maximum = max(self.maximum, self.active)
        try:
            time.sleep(0.002)
            raw = self.objects[Key]
            return dict(Body=io.BytesIO(raw), ContentLength=len(raw), ETag='original-etag')
        finally:
            with self.lock:
                self.active -= 1


def test_prefetch_populates_maintained_cache_and_rechecks_resume_without_gets(tmp_path):
    pairs = [item({'version': 1, 'prefix': str(i), 'value': {}}) for i in range(12)]
    remote = Remote({hint.key: raw for hint, raw in pairs})
    client = ReadOnlyClient(remote)
    events = []
    result = prefetcher.prefetch(client, [hint for hint, raw in pairs], tmp_path, workers=2, progress=events.append)
    assert result['completed'] == result['downloaded'] == 12 and result['failures'] == 0
    assert remote.maximum <= 2
    assert len(remote.calls) == 12
    # The ordinary maintained owner validates these exact bytes. It does not
    # need the hint database or a new cache reader at preparation time.
    objects = MetadataObjects(R2Store(client, 'fixture', cache_dir=tmp_path), prefetcher.ROUTES)
    for hint, raw in pairs:
        assert objects.read(dict(key=hint.key, sha256=hint.sha256, bytes=len(raw))) == json.loads(raw)
    assert len(remote.calls) == 12
    again = prefetcher.prefetch(client, [hint for hint, raw in pairs], tmp_path, workers=2)
    assert again['cached'] == 12 and again['downloaded'] == 0 and len(remote.calls) == 12
    assert events[-1]['completed'] == 12


def test_corrupt_local_cache_is_refetched_and_remote_corruption_is_not_cached(tmp_path):
    hint, raw = item({'version': 1}, prefetcher.PROOFS)
    path = tmp_path / 'r2-native-manifests' / prefetcher.PROOFS / (hint.sha256 + '.json')
    path.parent.mkdir(parents=True)
    path.write_bytes(b'corrupt')
    remote = Remote({hint.key: raw})
    result = prefetcher.prefetch(ReadOnlyClient(remote), [hint], tmp_path, workers=1)
    assert result['downloaded'] == 1 and path.read_bytes() == raw
    path.unlink()
    remote.objects[hint.key] = b'corrupt'
    events = []
    with pytest.raises(ValueError, match='identity mismatch'):
        prefetcher.prefetch(ReadOnlyClient(remote), [hint], tmp_path, workers=1, progress=events.append)
    assert not path.exists() and events[-1]['failures'] == 1


@pytest.mark.parametrize('key', ['indexes/catalog.json', 'viewer-publications/manifest.json',
    'bodies/sha256/' + 'a' * 64, 'indexes/native-manifests/catalog-schemas-v1/' + 'a' * 64 + '.json',
    'indexes/native-manifests/catalog-component-pages-v1/../../outside'])
def test_mutable_and_unlisted_keys_refused_before_remote_access(key):
    with pytest.raises(ValueError, match='allowlist'):
        prefetcher.Hint(key, 'a' * 64)


def test_stopped_database_is_read_only_and_duplicate_hints_are_deduplicated(tmp_path):
    hint, raw = item({'version': 1})
    page, page_raw = item({'version': 1, 'components': {}}, prefetcher.PROOFS)
    path = tmp_path / 'stages.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE plans(body TEXT)')
        db.execute('CREATE TABLE components(page TEXT)')
        db.executemany('INSERT INTO plans VALUES (?)', [(json.dumps({'native_sha256': hint.sha256}),)] * 2)
        db.executemany('INSERT INTO components VALUES (?)', [(json.dumps(dict(
            key=page.key, sha256=page.sha256, bytes=len(page_raw))),)] * 2)
    before = hashlib.sha256(path.read_bytes()).digest()
    hints = prefetcher.read_hints(path)
    assert set(hints) == {prefetcher.Hint(hint.key, hint.sha256), page}
    assert hashlib.sha256(path.read_bytes()).digest() == before


def test_selectors_and_conditional_reads_stay_remote(tmp_path):
    hint, raw = item({'version': 1})
    remote = Remote({hint.key: raw, 'indexes/catalog.json': b'live'})
    client = ReadOnlyClient(remote)
    prefetcher.prefetch(client, [hint], tmp_path, workers=1)
    store = R2Store(client, 'fixture', cache_dir=tmp_path)
    assert store.read('indexes/catalog.json') == b'live'
    remote.objects['indexes/catalog.json'] = b'changed'
    assert store.read('indexes/catalog.json') == b'changed'
    client.get_object(Bucket='fixture', Key=hint.key, IfMatch='original-etag')['Body'].close()
    assert remote.calls[-1] == (hint.key, {'IfMatch': 'original-etag'})
