"""Offline publication-boundary checks; never contact an object store."""
import hashlib
import sys
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'packages/congress_api/src')]
import pyarrow as pa
from import_corpus_recovery_batch import import_batch
from congress_api.retention.raw_archive import CAPTURE_SCHEMA, STATE_SCHEMA, CAPTURES_KEY, STATE_KEY


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
        self.assertEqual(store.writes[-2:], [(STATE_KEY, False), (CAPTURES_KEY, False)])
        self.assertEqual(store.data[CAPTURES_KEY], self.saved[CAPTURES_KEY])
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
        store = Store(fail_key=CAPTURES_KEY)
        with self.assertRaisesRegex(RuntimeError, 'Conditional conflict'):
            self.run_import(store)
        self.assertIn(STATE_KEY, store.data)
        self.assertNotIn(CAPTURES_KEY, store.data)
        self.assertNotIn('import_complete', [e for e, _ in self.events])
        self.assertIn(CAPTURES_KEY, self.saved)

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
    import import_corpus_recovery_batch as module
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
    import import_corpus_recovery_batch as module
    from test_reconcile_corpus_recovery_bodies import Client
    from reconcile_corpus_recovery_bodies import reconcile
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
    import import_corpus_recovery_batch as module
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
        cap = pa.Table.from_pylist([dict(body_key='duplicate', bytes=None)] * 2, schema=CAPTURE_SCHEMA)
        store = Store()
        result = import_batch(store, prepared=fixture.prepared, body_paths=fixture.paths,
            captures=cap, state=old, source_file='test', receipt_prefix='receipts/test',
            guard=lambda:None, journal=lambda *args:None, save_payload=lambda *args:None)
        final = decode_table(store.data[STATE_KEY])
        assert final.slice(0, len(old)).equals(old)
        assert final.schema.equals(old.schema, check_metadata=False)
        assert decode_table(store.data[CAPTURES_KEY]).slice(0, 2).equals(cap)
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
