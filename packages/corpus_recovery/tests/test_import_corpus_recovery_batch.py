"""Offline publication-boundary checks; never contact an object store."""
import hashlib
import sys
from pathlib import Path
import tempfile
import unittest

import pyarrow as pa
from corpus_recovery.transfer import import_batch as native_import_batch
from congress_api.retention.raw_storage import RAW_KEY

# Shared offline transport fixture; real native coverage is in test_raw_storage.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tests"))
from native_memory_helpers import memory_raw_storage
from congress_api.retention.raw_archive import CAPTURE_SCHEMA, LEGACY_CAPTURE_SCHEMA, STATE_SCHEMA, CAPTURES_KEY, STATE_KEY


def import_batch(store, *, captures, state, **kwargs):
    """Explicitly adopt each historical test baseline, then use the real importer."""
    if not hasattr(store, 'raw_storage'):
        if pa.compute.count_distinct(state['url'], mode='all').as_py() != len(state):
            raise ValueError('Duplicate URLs in baseline download state')
        owner = memory_raw_storage(store, state_schema=state.schema.remove_metadata())
        lost, fail = store.lost_ack, store.fail_key
        store.lost_ack, store.fail_key = False, None
        owner.publish(owner.prepare(owner.snapshot(), operation='fixture-seed', captures=captures,
                                    states=state.replace_schema_metadata(None), filename_version='missing'))
        store.raw_storage = owner
        store.lost_ack, store.fail_key = lost, fail
        store.writes.clear()
        store.reads.clear()
    return native_import_batch(store, raw_storage=store.raw_storage, operation='test-delivery', **kwargs)


class Store:
    def __init__(self, lost_ack=False, fail_key=None):
        self.data = {}
        self.writes = []
        self.reads = []
        self.lost_ack = lost_ack
        self.fail_key = fail_key

    def read(self, key):
        self.reads.append(key)
        return self.data.get(key)

    def put(self, key, payload, *, immutable):
        if key == self.fail_key:
            raise RuntimeError('Conditional conflict')
        self.writes.append((key, immutable))
        self.data[key] = payload
        if self.lost_ack:
            self.lost_ack = False
            raise TimeoutError('Lost acknowledgment')


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.url = 'https://example.org/archive.zip'
        self.paths = {}
        caps = []
        members = []
        for n in range(2):
            raw = f'retained fixture {n}'.encode()
            digest = hashlib.sha256(raw).hexdigest()
            key = f'bodies/sha256/{digest[:2]}/{digest}.gz'
            path = Path(self.temp.name) / str(n)
            path.write_bytes(raw)
            self.paths[key] = path
            caps.append(dict(body_key=key, sha256=digest, bytes=len(raw), context_url=self.url,
                retrieved_at='2020-01-01T00:00:00Z', pointer=['content', 'body'] if n == 0
                else ['archive_members', 0, 'content', 'body']))
            if n:
                caps[-1]['original_path'] = 'member.pdf'
                members.append(dict(original_name='member.pdf', parent_archive_body_key=caps[0]['body_key'],
                                    content=dict(body=None, sha256=digest)))
        self.prepared = [dict(original_url=self.url, preserve_download_state=True, captures=caps,
            record=dict(url=self.url, retrieved_at='2020-01-01T00:00:00Z',
                        content=dict(body=None, sha256=caps[0]['sha256']), archive_members=members,
                        source_associations=[dict(original_url=self.url)]))]
        self.events = []
        self.saved = {}

    def run_import(self, store, guard=lambda: None):
        return import_batch(store, prepared=self.prepared, body_paths=self.paths,
            captures=pa.Table.from_pylist([], schema=CAPTURE_SCHEMA),
            state=pa.Table.from_pylist([], schema=STATE_SCHEMA), source_file='test',
            receipt_prefix='receipts/documents/test', guard=guard,
            journal=lambda event, data: self.events.append((event, data)),
            save_payload=lambda key, data: self.saved.__setitem__(key, data))

    def test_complete_zip_import_and_pair_readback(self):
        store = Store()
        result = self.run_import(store)
        self.assertTrue(result['complete'])
        self.assertEqual(result['added_capture_rows'], 2)
        self.assertEqual(result['new_pending_states'], 1)
        self.assertFalse(result['catalog_and_viewer_publication_complete'])
        self.assertEqual(store.writes[-1], (RAW_KEY, False))
        self.assertEqual(store.data[RAW_KEY], self.saved[RAW_KEY])
        self.assertNotIn(CAPTURES_KEY, store.data)
        self.assertNotIn(STATE_KEY, store.data)
        for key in self.paths:
            self.assertEqual(store.reads.count(key), 2)  # Presence check and full readback.

    def test_lost_ack_reconciled_without_duplicate_write(self):
        store = Store(lost_ack=True)
        self.run_import(store)
        self.assertEqual(len(store.writes), len({k for k, _ in store.writes}))
        self.assertIn('acknowledgment_reconciled', [e for e, _ in self.events])
        for key in self.paths:
            self.assertEqual(store.reads.count(key), 2)

    def test_guard_refusal_prevents_writes(self):
        def refuse():
            raise RuntimeError('Cloud writer active')
        store = Store()
        with self.assertRaisesRegex(RuntimeError, 'Cloud writer'):
            self.run_import(store, refuse)
        self.assertEqual(store.writes, [])

    def test_partial_index_pair_never_reports_complete(self):
        store = Store(fail_key=RAW_KEY)
        with self.assertRaisesRegex(RuntimeError, 'Conditional conflict'):
            self.run_import(store)
        self.assertEqual(len(store.raw_storage.snapshot().captures()), 0)
        self.assertEqual(len(store.raw_storage.snapshot().states()), 0)
        self.assertNotIn('import_complete', [e for e, _ in self.events])
        self.assertIn(RAW_KEY, self.saved)

    def test_changed_local_body_rejected_before_writes(self):
        next(iter(self.paths.values())).write_bytes(b'changed')
        store = Store()
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            self.run_import(store)
        self.assertEqual(store.writes, [])


if __name__ == '__main__':
    unittest.main()


def test_existing_body_skips_compression():
    from unittest.mock import patch
    import gzip
    import corpus_recovery.transfer as module
    fixture = ImportTests()
    fixture.setUp()
    try:
        store = Store()
        for key, path in fixture.paths.items():
            store.data[key] = gzip.compress(path.read_bytes(), mtime=12)
        with patch.object(module, 'body_payload', wraps=module.body_payload) as compress:
            fixture.run_import(store)
        assert compress.call_count == 0
        assert all(store.reads.count(key) == 1 for key in fixture.paths)
        assert all(key not in dict(store.writes) for key in fixture.paths)
    finally:
        fixture.doCleanups()


def test_prior_body_identity_reuses_head_without_get_or_gzip():
    from unittest.mock import patch
    import corpus_recovery.transfer as module
    from test_reconcile_corpus_recovery_bodies import Client
    from corpus_recovery.inventory import reconcile
    from types import SimpleNamespace
    fixture = ImportTests()
    fixture.setUp()
    try:
        key, path = next(iter(fixture.paths.items()))
        fixture.paths = {key: path}
        fixture.prepared[0]['captures'] = fixture.prepared[0]['captures'][:1]
        client = Client(path.read_bytes())
        report = reconcile(SimpleNamespace(client=client, bucket='test'),
                           {key: dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(), bytes=path.stat().st_size)})
        store = Store()
        store.client, store.bucket = client, 'test'
        with patch.object(module, 'body_payload', wraps=module.body_payload) as compress:
            import_batch(store, prepared=fixture.prepared, body_paths=fixture.paths,
                captures=pa.Table.from_pylist([], schema=CAPTURE_SCHEMA),
                state=pa.Table.from_pylist([], schema=STATE_SCHEMA), source_file='test',
                receipt_prefix='receipts/test', guard=lambda:None,
                journal=lambda *args:None, save_payload=lambda *args:None, body_readback=report)
        assert compress.call_count == 0
        assert key not in store.reads
        assert client.gets == 1  # The prior full-byte check only.
    finally:
        fixture.doCleanups()


def test_missing_bodies_compress_once_each_even_after_lost_ack():
    from unittest.mock import patch
    import corpus_recovery.transfer as module
    fixture = ImportTests()
    fixture.setUp()
    try:
        store = Store(lost_ack=True)
        with patch.object(module, 'body_payload', wraps=module.body_payload) as compress:
            fixture.run_import(store)
        assert compress.call_count == len(fixture.paths)
        assert all(store.reads.count(key) == 2 for key in fixture.paths)
        assert all(store.writes.count((key, True)) == 1 for key in fixture.paths)
    finally:
        fixture.doCleanups()


def test_arrow_append_preserves_types_nulls_and_capture_multiplicity():
    from congress_api.retention.raw_archive import decode_table
    fixture = ImportTests()
    fixture.setUp()
    try:
        state_schema = STATE_SCHEMA.append(pa.field('extra', pa.struct([
            pa.field('large', pa.uint64()), pa.field('nested', pa.list_(pa.binary()))])))
        old = pa.Table.from_pylist([dict(url='untouched', outcome='failed', attempts=7,
            extra=dict(large=2**64-1, nested=[None, b'exact'])), dict(url=None, outcome=None)], schema=state_schema)
        cap = pa.Table.from_pylist([dict(body_key='duplicate', bytes=None)] * 2, schema=LEGACY_CAPTURE_SCHEMA)
        store = Store()
        result = import_batch(store, prepared=fixture.prepared, body_paths=fixture.paths,
            captures=cap, state=old, source_file='test', receipt_prefix='receipts/test',
            guard=lambda:None, journal=lambda *args:None, save_payload=lambda *args:None)
        final = store.raw_storage.snapshot().states()
        assert final.slice(0, len(old)).equals(old)
        assert final.schema.equals(old.schema, check_metadata=False)
        assert store.raw_storage.snapshot().captures().slice(0, 2).equals(cap)
        assert result['existing_download_states_preserved'] == 2
        assert result['new_pending_states'] == 1

    finally:
        fixture.doCleanups()


def test_duplicate_baseline_urls_rejected_explicitly():
    import pytest
    fixture = ImportTests()
    fixture.setUp()
    try:
        for url in ('same', None):
            with pytest.raises(ValueError, match='Duplicate URLs'):
                import_batch(Store(), prepared=[], body_paths={},
                    captures=pa.Table.from_pylist([], schema=CAPTURE_SCHEMA),
                    state=pa.Table.from_pylist([dict(url=url)] * 2, schema=STATE_SCHEMA),
                    source_file='test', receipt_prefix='receipts/test',
                    guard=lambda:None, journal=lambda *args:None, save_payload=lambda *args:None)
    finally:
        fixture.doCleanups()


def test_completed_import_retry_after_unrelated_update_has_original_result_and_zero_writes():
    fixture = ImportTests()
    fixture.setUp()
    try:
        store = Store()
        first = fixture.run_import(store)
        owner = store.raw_storage
        later = owner.publish(owner.prepare(owner.snapshot(), operation='unrelated',
            captures=pa.Table.from_pylist([dict(receipt_key='receipts/other')], schema=CAPTURE_SCHEMA)))
        before = list(store.writes)
        result = fixture.run_import(store)
        assert result['already_applied']
        assert result['capture_rows'] == first['capture_rows'] == 2
        assert later.manifest['captures']['rows'] == 3
        assert store.writes == before
    finally:
        fixture.doCleanups()


def test_commit_guard_refusal_preserves_the_selected_raw_root():
    import pytest
    fixture = ImportTests()
    fixture.setUp()
    try:
        store = Store()
        def refuse():
            raise RuntimeError('Shared raw writer appeared')
        with pytest.raises(RuntimeError, match='Shared raw writer'):
            import_batch(store, prepared=fixture.prepared, body_paths=fixture.paths,
                captures=pa.Table.from_pylist([], schema=CAPTURE_SCHEMA),
                state=pa.Table.from_pylist([], schema=STATE_SCHEMA), source_file='test',
                receipt_prefix='receipts/test', guard=lambda:None, commit_guard=refuse,
                journal=lambda *args:None, save_payload=lambda *args:None)
        assert store.raw_storage.snapshot().manifest['captures']['rows'] == 0
        assert not any(key == RAW_KEY for key, _ in store.writes)
    finally:
        fixture.doCleanups()


def test_unadopted_legacy_archive_is_preserved_before_body_or_native_writes():
    import pytest
    fixture = ImportTests()
    fixture.setUp()
    try:
        store = Store()
        store.data[CAPTURES_KEY] = b'preserved legacy captures'
        store.data[STATE_KEY] = b'preserved legacy state'
        owner = memory_raw_storage(store)
        before = dict(store.data)
        with pytest.raises(RuntimeError, match='seed adoption'):
            native_import_batch(store, raw_storage=owner, operation='not-adopted',
                prepared=fixture.prepared, body_paths=fixture.paths,
                source_file='test', receipt_prefix='receipts/test', guard=lambda:None,
                journal=lambda *args:None, save_payload=lambda *args:None)
        assert store.data == before
        assert store.writes == owner.native.writes == []
    finally:
        fixture.doCleanups()


def test_empty_operation_and_stale_baseline_refuse_before_any_import_write():
    import pytest
    fixture = ImportTests()
    fixture.setUp()
    try:
        store = Store()
        owner = memory_raw_storage(store)
        first = owner.publish(owner.prepare(owner.snapshot(), operation='seed', filename_version='missing'))
        owner.publish(owner.prepare(first, operation='later', captures=pa.Table.from_pylist([{}], schema=CAPTURE_SCHEMA)))
        before, native_before = list(store.writes), list(owner.native.writes)
        for operation, base, message in [('', None, 'operation'), ('new', first, 'Stale')]:
            with pytest.raises(ValueError, match=message):
                native_import_batch(store, raw_storage=owner, base=base, operation=operation,
                    prepared=fixture.prepared, body_paths=fixture.paths, source_file='test', receipt_prefix='receipts/test',
                    guard=lambda:None, journal=lambda *args:None, save_payload=lambda *args:None)
            assert store.writes == before
            assert owner.native.writes == native_before
    finally:
        fixture.doCleanups()
