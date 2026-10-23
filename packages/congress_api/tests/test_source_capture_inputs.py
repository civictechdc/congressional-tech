"""Receipt replay uses exact retained raw batches after a fresh owner restart."""
from contextlib import closing

import pyarrow as pa
import pytest

from congress_api.retention.catalog_staging import WorkingCatalog
from congress_api.retention.raw_values import NATIVE_CAPTURE_SCHEMA
from congress_api.retention.source_capture_inputs import SourceCaptureInputs
from congress_api.retention.source_observations import SourceObservationTrace, SourceObservationStorage, observation_id
from testing_fakes import MemoryNative, MemoryStore, SelectorStore


class Snapshot:
    def __init__(self, tables):
        self.tables, self.reads = tables, []
    def capture_batch(self, entry):
        self.reads.append(entry['release']['dataset_key'])
        return self.tables[entry['release']['dataset_key']]
    def captures(self):
        raise AssertionError('Global capture read forbidden')


def batch(start, count):
    return pa.Table.from_pylist([dict(_capture_order=i, receipt_key=f'receipts/{i // 2}.gz',
        receipt_line=i % 2 + 1, context_url=f'https://example.gov/{i}', body_key=f'body-{i}')
        for i in range(start, start + count)], schema=NATIVE_CAPTURE_SCHEMA)


def test_exact_old_capture_group_restores_after_restart_without_history_scan(tmp_path):
    store, native = MemoryStore(), MemoryNative()
    owner = SourceObservationStorage(native=native, store=store, namespace='input-owners', max_rows=8192, max_bytes=1 << 20)
    inputs = SourceCaptureInputs(store)
    tables = {f'batch-{i}': batch(i * 4, 4) for i in range(100)}
    with closing(WorkingCatalog(tmp_path / 'attach.sqlite')) as work:
        trace = SourceObservationTrace(work)
        for key, table in tables.items():
            entry = dict(release=dict(dataset_key=key), rows=len(table), first_order=table['_capture_order'][0].as_py())
            inputs.attach(trace, entry, table)
        root = owner.prepare(None, trace)
    fresh = SourceCaptureInputs(store)
    snapshot = Snapshot(tables)
    recovered = list(fresh.tables(owner, root, [observation_id('receipts/3.gz', 1),
                                               observation_id('receipts/3.gz', 2)], snapshot))
    assert snapshot.reads == ['batch-1']
    assert pa.concat_tables(recovered)['_capture_order'].to_pylist() == [6, 7]
    assert len(native.tables) == 1  # Coalesced owner relationships, no per-receipt datasets.


def test_capture_association_refuses_changed_locator_and_missing_ordinal(tmp_path):
    store, native = MemoryStore(), MemoryNative()
    owner = SourceObservationStorage(native=native, store=store, namespace='input-refusal', max_rows=64, max_bytes=1 << 20)
    original = batch(0, 2)
    with closing(WorkingCatalog(tmp_path / 'trace.sqlite')) as work:
        trace = SourceObservationTrace(work)
        SourceCaptureInputs(store).attach(trace, dict(release=dict(dataset_key='original'), rows=2, first_order=0), original)
        root = owner.prepare(None, trace)
    rows = original.to_pylist()
    rows[0]['receipt_line'] = 99
    changed = pa.Table.from_pylist(rows, schema=original.schema)
    for bad in (changed, original.slice(1)):
        with pytest.raises(ValueError, match='locator differs|omits requested'):
            list(SourceCaptureInputs(store).tables(owner, root, [observation_id('receipts/0.gz', 1)],
                                                   Snapshot(dict(original=bad))))




def test_actual_native_raw_capture_reference_replays_only_selected_old_input(tmp_path, native):
    from congress_api.retention.raw_archive import CAPTURE_SCHEMA
    from congress_api.retention.raw_storage import RawStorage
    store = SelectorStore()
    raw = RawStorage(store, native, max_capture_rows=2)
    old = raw.snapshot()
    selected = raw.publish(raw.prepare(old, operation='retained-inputs', captures=batch(0, 2).drop(['_capture_order'])))
    owner = SourceObservationStorage(native=native, store=store, namespace='actual-raw-inputs', max_rows=64, max_bytes=1 << 20)
    with closing(WorkingCatalog(tmp_path / 'actual-trace.sqlite')) as work:
        trace = SourceObservationTrace(work)
        for change in selected.changes_since(old.identity):
            assert len(list(SourceCaptureInputs(store).changed(selected, change, trace))) == 1
        root = owner.prepare(None, trace)
    fresh_raw = RawStorage(store, native, max_capture_rows=2).snapshot()
    result, = SourceCaptureInputs(store).tables(owner, root, [observation_id('receipts/0.gz', 2)], fresh_raw)
    assert result.equals(batch(0, 2).slice(1), check_metadata=True)
