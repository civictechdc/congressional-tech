"""Normal selected raw changes publish through retained contribution replay."""
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.retention import document_index as index
from congress_api.retention.raw_archive import CAPTURES_KEY, decode_table
from congress_api.retention.raw_storage import RawStorage, RawSnapshot
from congress_api.retention.raw_catalog import update_from_raw
from congress_api.retention.catalog_publication import read_catalog, MANIFEST_KEY
from test_raw_rebuild import retain
from test_raw_storage import SelectorStore
from native_memory_helpers import MemoryNative as RawMemoryNative
from contextlib import contextmanager

class MemoryNative(RawMemoryNative):
    @contextmanager
    def source_batches(self, pin, *, schema=None):
        with super().source_batches(pin) as reader:
            yield reader


def seed(store, native):
    raw = RawStorage(store, native)
    retain(store, dict(eventId=7, congress=119, chamber='House', meetingDocuments=[dict(
        url='https://example.gov/paper.pdf', documentType='Statement', name='Literal paper')]),
        family='congress/meetings', source_file='meeting.json')
    raw.publish(raw.prepare(raw.snapshot(), operation='meeting', captures=decode_table(store.read(CAPTURES_KEY))))
    return raw


def test_normal_dispatch_creates_native_selection_and_retries_without_raw_or_native_work(tmp_path, monkeypatch):
    store, native = SelectorStore(), MemoryNative()
    raw = seed(store, native)
    # This fixture has an explicitly investigated empty capture-reading inventory.
    monkeypatch.setattr(RawSnapshot, 'body_readings', lambda self, keys: iter(()), raising=False)
    options = dict(raw_storage=raw, directory=tmp_path / 'work', candidate='first')
    result = update_from_raw(store, **options)
    selected = read_catalog(store, native=native)
    assert result['selected_identity'] == selected.identity
    assert selected.selection['interpretation']['raw_identity'] == raw.snapshot().identity
    rows = pa.Table.from_batches(list(selected.table('filenames', max_ordered_bytes=16 << 20).iter_batches())).to_pylist()
    assert len(rows) == 1 and rows[0]['source_document_label'] == ['Literal paper']
    monkeypatch.setattr(native, 'run_table', lambda *a, **k: (_ for _ in ()).throw(AssertionError('Native work repeated')))
    monkeypatch.setattr(RawSnapshot, 'capture_batch', lambda *a: (_ for _ in ()).throw(AssertionError('Raw payload repeated')))
    assert update_from_raw(store, **options)['unchanged']
    assert update_from_raw(store, raw_storage=raw, directory=tmp_path / 'unchanged', candidate='next')['unchanged']


def test_unqualified_capture_readings_refuse_before_catalog_selector(tmp_path, monkeypatch):
    store, native = SelectorStore(), MemoryNative()
    raw = seed(store, native)
    monkeypatch.setattr(RawSnapshot, 'body_readings', lambda *a: (_ for _ in ()).throw(
        ValueError('Capture reading inventory requires explicit adoption')), raising=False)
    with pytest.raises(ValueError, match='reading inventory'):
        update_from_raw(store, raw_storage=raw, directory=tmp_path / 'work', candidate='first')
    assert store.read(MANIFEST_KEY) is None


from test_docspec_boundary import native


def test_actual_native_recurring_ambiguity_matches_maintained_full_reference(tmp_path, native, monkeypatch):
    from test_raw_source_sync import MemoryStore
    from congress_api.retention.raw_catalog import rebuild_catalog
    from catalog_test_helpers import selected_path
    store = SelectorStore()
    raw = RawStorage(store, native, max_capture_rows=2)
    retain(store, dict(eventId=7, congress=119, chamber='House', committees=[dict(systemCode='hsii00')]),
           family='congress/meetings', source_file='meeting.json')
    retain(store, {}, family='house/witness-xml', source_file='witness.xml', url='https://docs.house.gov/7.xml',
        body=b'<witness-list meeting-id="HMKP7"><panel><witness><firstname>Jane</firstname><lastname>Doe</lastname><witness-documents><witness-document type="WS"><files><file doc-url="https://example.gov/paper.pdf" doc-type="PDF"/></files></witness-document></witness-documents></witness></panel></witness-list>')
    captures = decode_table(store.read(CAPTURES_KEY))
    raw.publish(raw.prepare(raw.snapshot(), operation='initial', captures=captures))
    monkeypatch.setattr(RawSnapshot, 'body_readings', lambda self, keys: iter(()), raising=False)
    initial = update_from_raw(store, raw_storage=raw, directory=tmp_path / 'initial', candidate='initial')
    retain(store, dict(eventId=7, congress=118, chamber='House', committees=[dict(systemCode='hsju00')]),
           family='congress/meetings', source_file='other-meeting.json')
    raw.publish(raw.prepare(raw.snapshot(), operation='ambiguous', captures=decode_table(store.read(CAPTURES_KEY)).slice(len(captures))))
    result = update_from_raw(store, raw_storage=raw, directory=tmp_path / 'changed', candidate='ambiguous')
    selected = read_catalog(store, native=native)
    actual = {label: pa.Table.from_batches(list(selected.table(label, max_ordered_bytes=16 << 20).iter_batches()))
              for label in ('filenames', 'documents')}
    paper = next(row for row in actual['filenames'].to_pylist() if row['source_url'] == 'https://example.gov/paper.pdf')
    assert paper['source_committee_code'] is None
    reference = MemoryStore()
    reference.objects.update({key: value for key, value in store.objects.items() if key != MANIFEST_KEY})
    rebuild_catalog(reference, decode_table(store.read(CAPTURES_KEY)), workers=1)
    for label in actual:
        from congress_api.retention.catalog_publication import read_catalog as read_reference
        with read_reference(reference) as reference_snapshot:
            expected = pq.read_table(reference_snapshot.filenames_path if label == 'filenames' else reference_snapshot.documents_path)
        # The incremental logical schema retains newly empty nullable fields.
        expected = pa.Table.from_pylist(expected.to_pylist(), schema=actual[label].schema)
        key = 'source_id' if label == 'filenames' else 'document_id'
        assert sorted(actual[label].to_pylist(), key=lambda row: row[key]) == sorted(expected.to_pylist(), key=lambda row: row[key])
    assert result['selected_identity'] != initial['selected_identity']


def test_worker_loss_before_catalog_cas_resumes_exact_retained_output(tmp_path, monkeypatch):
    from congress_api.retention import catalog_updates
    store, native = SelectorStore(), MemoryNative()
    raw = seed(store, native)
    monkeypatch.setattr(RawSnapshot, 'body_readings', lambda self, keys: iter(()), raising=False)
    publish = catalog_updates.publish_native_catalog
    monkeypatch.setattr(catalog_updates, 'publish_native_catalog', lambda *a, **k: (_ for _ in ()).throw(OSError('worker stopped')))
    options = dict(raw_storage=raw, directory=tmp_path / 'retained', candidate='first')
    with pytest.raises(OSError, match='worker stopped'):
        update_from_raw(store, **options)
    assert store.read(MANIFEST_KEY) is None
    monkeypatch.setattr(catalog_updates, 'publish_native_catalog', publish)
    monkeypatch.setattr(native, 'run_table', lambda *a, **k: (_ for _ in ()).throw(AssertionError('Completed native work repeated')))
    monkeypatch.setattr(RawSnapshot, 'capture_batch', lambda *a: (_ for _ in ()).throw(AssertionError('Raw payload repeated')))
    assert update_from_raw(store, **options)['selected_identity'] == read_catalog(store, native=native).identity
    assert update_from_raw(store, **options)['unchanged']


def test_old_file_selector_refuses_without_old_payload_reads(tmp_path, monkeypatch):
    store, native = SelectorStore(), MemoryNative()
    raw = seed(store, native)
    store.objects[MANIFEST_KEY] = b'{"version":1}'
    monkeypatch.setattr(store, 'read_derived_file', lambda *a, **k: (_ for _ in ()).throw(AssertionError('Old full file read')))
    with pytest.raises(ValueError, match='contribution adoption'):
        update_from_raw(store, raw_storage=raw, directory=tmp_path / 'retained', candidate='first')


def test_complete_interpreted_source_change_clears_unproven_receipt_cursor(tmp_path, monkeypatch):
    from congress_api.retention.catalog_updates import update_native_catalog
    from congress_api.retention.catalog_dependency_storage import CatalogDependencyStorage
    store, native = SelectorStore(), MemoryNative()
    raw = seed(store, native)
    monkeypatch.setattr(RawSnapshot, 'body_readings', lambda self, keys: iter(()), raising=False)
    update_from_raw(store, raw_storage=raw, directory=tmp_path / 'raw', candidate='raw')
    previous = read_catalog(store, native=native)
    owner = CatalogDependencyStorage.for_snapshot(previous)
    row, = pa.Table.from_batches(list(previous.table('filenames', max_ordered_bytes=16 << 20).iter_batches())).to_pylist()
    row['source_document_label'] = ['Explicit complete replacement']
    update_native_catalog(store, native=native, previous=previous, dependencies=owner, replacements=[row],
        candidate='replacement', directory=tmp_path / 'manual', max_chunk_rows=8192, max_chunk_bytes=16 << 20,
        rules=dict(interpretation='explicit replacement'))
    assert read_catalog(store, native=native).selection['interpretation'] is None
    with pytest.raises(ValueError, match='contribution adoption'):
        update_from_raw(store, raw_storage=raw, directory=tmp_path / 'next', candidate='next')


def test_source_replay_proof_refuses_an_extra_selected_source_deletion(tmp_path, monkeypatch):
    from congress_api.retention import catalog_raw_updates
    store, native = SelectorStore(), MemoryNative()
    raw = seed(store, native)
    count = raw.snapshot().manifest['captures']['rows']
    retain(store, dict(eventId=8, congress=119, chamber='House', meetingDocuments=[dict(
        url='https://example.gov/other.pdf', documentType='Statement', name='Other paper')]),
        family='congress/meetings', source_file='other.json')
    raw.publish(raw.prepare(raw.snapshot(), operation='other', captures=decode_table(store.read(CAPTURES_KEY)).slice(count)))
    monkeypatch.setattr(RawSnapshot, 'body_readings', lambda self, keys: iter(()), raising=False)
    update_from_raw(store, raw_storage=raw, directory=tmp_path / 'initial', candidate='initial')
    previous = read_catalog(store, native=native)
    rows = pa.Table.from_batches(list(previous.table('filenames', max_ordered_bytes=16 << 20).iter_batches())).to_pylist()
    unrelated = next(row['source_id'] for row in rows if row['source_url'].endswith('other.pdf'))
    count = raw.snapshot().manifest['captures']['rows']
    retain(store, dict(eventId=7, congress=119, chamber='House', meetingDocuments=[dict(
        url='https://example.gov/paper.pdf', documentType='Statement', name='Additional literal label')]),
        family='congress/meetings', source_file='changed.json')
    raw.publish(raw.prepare(raw.snapshot(), operation='changed', captures=decode_table(store.read(CAPTURES_KEY)).slice(count)))
    before = store.read(MANIFEST_KEY)
    update = catalog_raw_updates.update_native_catalog
    def extra_deletion(store, **arguments):
        return update(store, **{**arguments, 'deletions': [*arguments['deletions'], unrelated]})
    monkeypatch.setattr(catalog_raw_updates, 'update_native_catalog', extra_deletion)
    with pytest.raises(ValueError, match='basis/deletions'):
        update_from_raw(store, raw_storage=raw, directory=tmp_path / 'invalid', candidate='invalid')
    assert store.read(MANIFEST_KEY) == before
