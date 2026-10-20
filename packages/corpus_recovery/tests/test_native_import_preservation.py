"""Preservation reads exact new captures and affected typed state, not old corpus rows."""
import json
from pathlib import Path
import sys

import pyarrow as pa
import pytest

from corpus_recovery.preservation import verify
from corpus_recovery.transfer import import_batch
from congress_api.retention.raw_archive import CAPTURE_SCHEMA, STATE_SCHEMA
from congress_api.retention.raw_storage import RAW_KEY
from congress_api.retention.immutable_metadata import encoded
from test_import_corpus_recovery_batch import ImportTests, Store
from native_memory_helpers import memory_raw_storage


@pytest.fixture
def retained(tmp_path):
    inputs = ImportTests()
    inputs.setUp()
    try:
        schema = STATE_SCHEMA.append(pa.field('extra', pa.struct([
            pa.field('large', pa.uint64()), pa.field('binary', pa.list_(pa.binary()))])))
        original = pa.Table.from_pylist([
            dict(url='https://example.org/old', outcome='failed', attempts=7,
                 extra=dict(large=2**64-1, binary=[None, b'exact'])),
            dict(url=None, outcome=None)], schema=schema)
        store = Store()
        owner = memory_raw_storage(store, state_schema=schema)
        owner.publish(owner.prepare(owner.snapshot(), operation='seed', states=original,
            captures=pa.Table.from_pylist([dict(body_key='legacy')] * 2, schema=CAPTURE_SCHEMA)))
        def execute(destination):
            payloads = destination / 'payloads'
            (payloads / 'baseline/indexes').mkdir(parents=True)
            (payloads / 'baseline' / RAW_KEY).write_bytes(store.read(RAW_KEY))
            events = []
            def save(key, value):
                path = payloads / key
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(value)
            result = import_batch(store, raw_storage=owner, operation='retained-delivery',
                prepared=inputs.prepared, body_paths=inputs.paths, source_file='fixture',
                receipt_prefix='receipts/fixture', guard=lambda:None,
                journal=lambda event, value: events.append(dict(event=event, value=value)), save_payload=save)
            save('import-complete.json', encoded(result))
            (destination / 'events.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in events))
            return result
        folder = tmp_path / 'first'
        result = execute(folder)
        yield owner, store, folder, result, execute
    finally:
        inputs.doCleanups()


def test_native_preservation_reuses_old_capture_pins_and_preserves_richer_state(retained):
    owner, store, folder, result, _ = retained
    before = json.loads((folder / 'payloads/baseline' / RAW_KEY).read_bytes())
    old = {entry['release']['dataset']['dataset'] for entry in owner.capture_pages.entries(before['captures']['head'])}
    owner.native.reads.clear()
    writes, native_writes = list(store.writes), list(owner.native.writes)
    report = verify(folder, raw_storage=owner)
    assert report['local_preservation_verified']
    assert report['previous_capture_rows'] == 2 and report['added_capture_rows'] == 2
    assert report['existing_states_preserved'] == 2 and report['new_pending_states'] == 1
    assert not old.intersection(owner.native.reads)
    assert store.writes == writes and owner.native.writes == native_writes
    assert not (folder / 'payloads/indexes/captures.parquet').exists()
    assert not (folder / 'payloads/indexes/download-state.parquet').exists()


def test_native_preservation_detects_changed_existing_state(retained):
    owner, _, folder, _, _ = retained
    _, reference = owner.state_routes.lookup(owner.snapshot().manifest['state']['root'], 'url:https://example.org/old')
    dataset = reference['release']['dataset']['dataset']
    table = owner.native.tables[dataset]
    rows = table.to_pylist()
    rows[0]['outcome'] = 'other!'
    owner.native.tables[dataset] = pa.Table.from_pylist(rows, schema=table.schema)
    with pytest.raises(ValueError, match='Existing download state changed'):
        verify(folder, raw_storage=owner)


def test_native_preservation_detects_selector_tampering(retained):
    owner, _, folder, _, _ = retained
    path = folder / 'payloads' / RAW_KEY
    path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(ValueError, match='payload|identity'):
        verify(folder, raw_storage=owner)


def test_completed_delivery_reuse_preserves_original_counts_after_unrelated_change(retained, tmp_path):
    owner, _, _, original, execute = retained
    owner.publish(owner.prepare(owner.snapshot(), operation='unrelated',
        captures=pa.Table.from_pylist([{}], schema=CAPTURE_SCHEMA)))
    folder = tmp_path / 'replayed'
    replayed = execute(folder)
    assert replayed['already_applied'] and replayed['capture_rows'] == original['capture_rows'] == 4
    report = verify(folder, raw_storage=owner)
    assert report['already_applied'] and report['added_capture_rows'] == 2


def test_native_preservation_detects_missing_capture_payload(retained):
    owner, _, folder, _, _ = retained
    after = owner.snapshot()
    entry = list(after.owner.capture_pages.entries(after.manifest['captures']['head']))[-1]
    dataset = entry['release']['dataset']['dataset']
    owner.native.tables[dataset] = owner.native.tables[dataset].slice(0, 1)
    with pytest.raises(ValueError, match='row count|coverage'):
        verify(folder, raw_storage=owner)


def test_completed_delivery_reuse_after_legitimate_download_does_not_compare_historical_state(retained, tmp_path):
    owner, store, _, original, execute = retained
    url = next(url for url in owner.snapshot().states()['url'].to_pylist() if url and url != 'https://example.org/old')
    row = owner.snapshot().state(url)
    row.update(outcome='saved', body_key='bodies/later-success.gz', attempts=2)
    owner.publish(owner.prepare(owner.snapshot(), operation='later-download',
        states=pa.Table.from_pylist([row], schema=owner.state_schema)))
    writes, native_writes = list(store.writes), list(owner.native.writes)
    folder = tmp_path / 'after-download'
    replayed = execute(folder)
    assert replayed['already_applied'] and replayed['capture_rows'] == original['capture_rows']
    assert verify(folder, raw_storage=owner)['local_preservation_verified']
    assert store.writes == writes and owner.native.writes == native_writes
