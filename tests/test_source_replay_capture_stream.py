"""Receipt interpretation consumes bounded selected capture batches repeatedly."""
from contextlib import closing
import weakref
import pyarrow as pa
import pyarrow.parquet as pq
from congress_api.retention import document_index as index
from congress_api.retention.catalog_staging import WorkingCatalog
from congress_api.retention.document_evidence import read_retained_body
from congress_api.retention.raw_archive import CAPTURES_KEY, decode_table
from congress_api.retention.raw_storage import RawStorage, RawSnapshot
from congress_api.retention.source_observations import SourceObservationStorage, SourceObservationTrace
from congress_api.retention.source_replay import prepare_source_replay
from native_memory_helpers import MemoryNative
from test_raw_rebuild import retain
from test_raw_storage import SelectorStore


def test_complete_receipt_replay_spools_capture_payloads_without_concatenating_all_inputs(tmp_path, monkeypatch):
    store, native = SelectorStore(), MemoryNative()
    raw = RawStorage(store, native, max_capture_rows=2)
    for event in range(12):
        retain(store, dict(eventId=event, congress=119, chamber='House', meetingDocuments=[dict(
            url=f'https://example.gov/paper-{event}.pdf', documentType='Statement', name=f'Literal {event}')]),
            family='congress/meetings', source_file=f'meeting-{event}.json')
    captures = decode_table(store.read(CAPTURES_KEY))
    empty = raw.snapshot()
    selected = raw.publish(raw.prepare(empty, operation='fixture', captures=captures))
    read_body = lambda key: read_retained_body(None, key, read_compressed=store.read)
    with closing(WorkingCatalog(tmp_path / 'reference.sqlite')) as work:
        expected = {index.source_identity(row): row for row in SourceObservationTrace(work).replay(
            captures, store.read, read_body).values()}
    capture_refs, capture_batch = [], RawSnapshot.capture_batch
    def bounded_batch(snapshot, entry):
        assert sum(reference() is not None for reference in capture_refs) <= 1
        table = capture_batch(snapshot, entry)
        capture_refs.append(weakref.ref(table))
        return table
    monkeypatch.setattr(RawSnapshot, 'capture_batch', bounded_batch)
    monkeypatch.setattr(pa, 'concat_tables', lambda *a, **k: (_ for _ in ()).throw(AssertionError('All capture payloads concatenated')))
    owner = SourceObservationStorage(native=native, store=store, namespace='streaming-receipts',
        max_rows=64, max_bytes=1 << 20)
    with prepare_source_replay(store, snapshot=selected, changes=selected.changes_since(empty.identity),
            observations=owner, root=None, directory=tmp_path / 'replay', read_body=read_body) as prepared:
        assert isinstance(prepared.captures, pq.ParquetFile)
        assert max(len(batch) for batch in index.capture_batches(prepared.captures)) <= 2
        assert {index.source_identity(row): row for row in prepared.sources()} == expected
