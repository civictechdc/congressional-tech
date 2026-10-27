"""B5: indexed metadata never proves that a raw object exists."""
import gzip
import hashlib
import json

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.acquisition.raw_sync import run_sync
from congress_api.retention.raw_archive import _Acquisition
from congress_api.retention.raw_values import _to_legacy_capture_table
from historical_raw_archive import LegacyArchiveSeed
from testing_fakes import MemoryStore, response

DATA = b'%PDF-1.7\nretained source\n%%EOF'
SHA = hashlib.sha256(DATA).hexdigest()
KEY = f'bodies/sha256/{SHA[:2]}/{SHA}.gz'


class IndexedInfo(dict):
    def __contains__(self, key):
        raise AssertionError('Index membership cannot establish body existence')


class Acquisition(_Acquisition):
    def __init__(self, store):
        self.store = store
        self.body_info = IndexedInfo({SHA: dict(body_key=KEY, sha256=SHA, bytes=len(DATA),
                                               stored_sha256='0' * 64, stored_bytes=1)})


def test_sync_indexed_missing_body_is_written_and_same_run_repeat_is_deduplicated():
    store = MemoryStore()
    archive = Acquisition(store)
    assert archive.put_body(DATA) == KEY
    assert gzip.decompress(store.objects[KEY]) == DATA
    assert archive.body_info[SHA]['stored_sha256'] == hashlib.sha256(store.objects[KEY]).hexdigest()
    assert archive.body_info[SHA]['stored_bytes'] == len(store.objects[KEY])
    writes = list(store.writes)
    assert archive.put_body(DATA) == KEY
    assert store.writes == writes


def test_failed_write_does_not_confirm_a_body_in_the_run():
    class InterruptedStore(MemoryStore):
        def put(self, key, data, *, immutable=False):
            if key.startswith('bodies/') and not hasattr(self, 'interrupted'):
                self.interrupted = True
                raise OSError('interrupted create')
            return super().put(key, data, immutable=immutable)

    store = InterruptedStore()
    archive = Acquisition(store)
    try:
        archive.put_body(DATA)
    except OSError:
        pass
    else:
        raise AssertionError('The first write must fail')
    assert KEY not in store.objects
    assert archive.put_body(DATA) == KEY
    assert gzip.decompress(store.objects[KEY]) == DATA


def test_async_capture_recreates_indexed_missing_body_and_records_actual_stored_digest():
    store = MemoryStore()
    previous_url = 'https://example.gov/previous.pdf'
    seed = LegacyArchiveSeed(store, 'previous')
    seed.record(response(previous_url, DATA), outcome='saved', links=[])
    seed.save()
    del store.objects[KEY]
    store.writes.clear()
    url = 'https://example.gov/new-address.pdf'
    run_sync(LegacyArchiveSeed(store, 'new'), [{'url': url}],
             fetch=lambda value: response(value, DATA), limit=1, workers=1)
    assert gzip.decompress(store.objects[KEY]) == DATA
    assert store.writes.count(KEY) == 1
    receipts = [json.loads(line) for key, payload in store.objects.items()
                if key.startswith('receipts/') and '/download-new-' in key
                for line in gzip.decompress(payload).splitlines()]
    [receipt] = receipts
    [capture] = receipt['captures']
    actual = hashlib.sha256(store.objects[KEY]).hexdigest()
    assert actual != SHA
    assert capture['stored_sha256'] == actual
    assert capture['stored_bytes'] == len(store.objects[KEY])
    rows = _to_legacy_capture_table(pq.read_table(pa.BufferReader(
        store.objects['indexes/captures.parquet']))).to_pylist()
    [row] = [row for row in rows if row['context_url'] == url]
    assert row['stored_sha256'] == actual
    assert row['stored_bytes'] == len(store.objects[KEY])


def test_sync_and_async_capture_share_only_confirmed_run_deduplication():
    store = MemoryStore()
    archive = LegacyArchiveSeed(store, 'one-run')
    archive.put_body(DATA)
    run_sync(archive, [{'url': 'https://example.gov/alias.pdf'}],
             fetch=lambda value: response(value, DATA), limit=1, workers=1)
    assert store.writes.count(KEY) == 1
    assert gzip.decompress(store.objects[KEY]) == DATA
