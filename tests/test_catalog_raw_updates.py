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
    from historical_raw_catalog import rebuild_catalog
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


@pytest.mark.parametrize('actual_native', [False, True])
def test_nullable_witness_fields_keep_old_component_pin_and_fill_only_missing_values(tmp_path, native, monkeypatch, actual_native):
    selected_native = native if actual_native else MemoryNative()
    store = SelectorStore()
    raw = seed(store, selected_native)
    count = raw.snapshot().manifest['captures']['rows']
    retain(store, dict(eventId=8, congress=119, chamber='House', meetingDocuments=[dict(
        url='https://example.gov/other.pdf', documentType='Statement', name='Other paper')]),
        family='congress/meetings', source_file='other.json')
    raw.publish(raw.prepare(raw.snapshot(), operation='other', captures=decode_table(store.read(CAPTURES_KEY)).slice(count)))
    monkeypatch.setattr(RawSnapshot, 'body_readings', lambda self, keys: iter(()), raising=False)
    update_from_raw(store, raw_storage=raw, directory=tmp_path / 'initial', candidate='initial')
    old = read_catalog(store, native=selected_native)
    old_rows = pa.Table.from_batches(list(old.table('filenames', max_ordered_bytes=16 << 20).iter_batches())).to_pylist()
    unrelated = next(row for row in old_rows if row['source_url'].endswith('other.pdf'))
    old_ref = old.component_ref(unrelated['document_id'])
    assert 'source_witness_name' not in old.schemas['filenames'].names
    count = raw.snapshot().manifest['captures']['rows']
    retain(store, {}, family='house/witness-xml', source_file='witness.xml', url='https://docs.house.gov/7.xml',
        body=b'<witness-list meeting-id="HMKP7"><panel><witness><firstname>Jane</firstname><lastname>Doe</lastname><witness-documents><witness-document type="WS"><files><file doc-url="https://example.gov/paper.pdf" doc-type="PDF"/></files></witness-document></witness-documents></witness></panel></witness-list>')
    raw.publish(raw.prepare(raw.snapshot(), operation='witness', captures=decode_table(store.read(CAPTURES_KEY)).slice(count)))
    update_from_raw(store, raw_storage=raw, directory=tmp_path / 'witness', candidate='witness')
    current = read_catalog(store, native=selected_native)
    values = pa.Table.from_batches(list(current.table('filenames', max_ordered_bytes=16 << 20).iter_batches())).to_pylist()
    assert current.component_ref(unrelated['document_id']) == old_ref
    assert next(row for row in values if row['source_url'].endswith('paper.pdf'))['source_witness_name'] == ['Jane Doe']
    actual_unrelated = next(row for row in values if row['source_id'] == unrelated['source_id'])
    assert actual_unrelated['source_witness_name'] is None
    assert all(actual_unrelated[name] == value for name, value in unrelated.items())
    assert old.schemas['filenames'].get_field_index('source_witness_name') == -1


@pytest.mark.parametrize('actual_native', [False, True])
def test_package_state_correction_replays_retained_api_receipt_and_complete_sibling_formats(tmp_path, monkeypatch, native, actual_native, record_property):
    import json
    from congress_api.retention.catalog_availability import annotate_availability
    from congress_api.retention.raw_archive import STATE_SCHEMA
    from test_catalog_availability import saved
    store, native = SelectorStore(), native if actual_native else MemoryNative()
    raw = RawStorage(store, native)
    package = 'CHRG-116shrg40895'
    api = 'https://api.congress.gov/v3/hearing/116/joint/40895?format=json'
    publisher = f'https://congress.gov/116/chrg/{package}/{package}.pdf'
    record = dict(requested_url=api, http_status=200,
                  hearing={'formats': [{'type': 'PDF', 'url': publisher},
                                       {'type': 'HTML', 'url': publisher[:-3] + 'htm'}]})
    receipt = retain(store, record, family='congress/hearings', source_file='api.json', url=api,
                    body=json.dumps(record).encode(), pointer=['content', 'body'])
    captures = decode_table(store.read(CAPTURES_KEY))
    pdf, html = saved(package), saved(package, 'html')
    api_state = dict(url=api, outcome='retained', body_key='api-body', http_status=200)
    raw.publish(raw.prepare(raw.snapshot(), operation='initial', captures=captures,
        states=pa.Table.from_pylist([api_state, pdf, html], schema=STATE_SCHEMA)))
    monkeypatch.setattr(RawSnapshot, 'body_readings', lambda self, keys: iter(()))
    calls, run_table = [], native.run_table
    def counted_run(table, **options):
        calls.append(options['dataset'])
        return run_table(table, **options)
    monkeypatch.setattr(native, 'run_table', counted_run)
    update_from_raw(store, raw_storage=raw, directory=tmp_path / 'first', candidate='first')
    record_property('initial_catalog_run_table_calls', len(calls))
    first = read_catalog(store, native=native)
    old = pa.Table.from_batches(list(first.table('filenames', max_ordered_bytes=16 << 20).iter_batches())).to_pylist()
    old_api = next(row for row in old if row['source_url'] == api)
    assert old_api['hearing_package_id'] == [package]  # Actual publisher differs from endpoint guess.
    assert {item['format'] for item in old_api['hearing_resources']} == {'pdf', 'html'}
    assert all(item['api_response_body_key'] == captures['body_key'][0].as_py()
               for item in old_api['hearing_resources'])
    changed_pdf = dict(pdf, outcome='http_error', http_status=404)
    raw.publish(raw.prepare(raw.snapshot(), operation='pdf-failed',
        states=pa.Table.from_pylist([changed_pdf], schema=STATE_SCHEMA)))
    calls.clear()  # Raw preparation is outside the catalog correction measurement.
    monkeypatch.setattr(RawSnapshot, 'captures', lambda *a: (_ for _ in ()).throw(AssertionError('Full captures')))
    monkeypatch.setattr(RawSnapshot, 'states', lambda *a: (_ for _ in ()).throw(AssertionError('Full states')))
    read = store.read
    reads = []
    def counted(key):
        reads.append(key)
        return read(key)
    monkeypatch.setattr(store, 'read', counted)
    update_from_raw(store, raw_storage=raw, directory=tmp_path / 'changed', candidate='changed')
    record_property('correction_catalog_run_table_calls_including_completed_replays', len(calls))
    current = read_catalog(store, native=native)
    actual = pa.Table.from_batches(list(current.table('filenames', max_ordered_bytes=16 << 20).iter_batches())).to_pylist()
    api_row = next(row for row in actual if row['source_url'] == api)
    expected = list(annotate_availability(old, pa.Table.from_pylist(
        [api_state, changed_pdf, html], schema=STATE_SCHEMA), hearing_records=[(record, captures.to_pylist())]))
    expected = pa.Table.from_pylist(expected, schema=current.schemas['filenames']).to_pylist()
    assert sorted(actual, key=lambda row: row['source_id']) == sorted(expected, key=lambda row: row['source_id'])
    assert api_row['source_id'] == old_api['source_id']
    assert api_row['document_id'] == old_api['document_id']
    assert [item['format'] for item in api_row['hearing_resources']] == ['html']
    assert receipt in reads


def file_adopted_catalog(tmp_path, store, native):
    from congress_api.retention.catalog_publication import publish_catalog
    from congress_api.retention.catalog_adoption import adopt_native_catalog
    from congress_api.retention.catalog_dependency_storage import CatalogDependencyStorage
    selected = read_catalog(store, native=native)
    directory = tmp_path / 'exact-files'
    directory.mkdir()
    for label in ('filenames', 'documents'):
        table = pa.Table.from_batches(list(selected.table(label, max_ordered_bytes=16 << 20).iter_batches()))
        pq.write_table(table, directory / (label + '.parquet'))
    # Explicit fixture transport: re-adopt these exact selected tables as files.
    store.objects.pop(MANIFEST_KEY)
    with read_catalog(store) as empty:
        publish_catalog(store, directory / 'filenames.parquet', directory / 'documents.parquet', previous=empty)
    with read_catalog(store) as files, pq.ParquetFile(files.filenames_path) as sources:
        dependencies = CatalogDependencyStorage(native=native, store=store, namespace='file-adopted-sources',
            source_schema=sources.schema_arrow, max_rows=8192, max_bytes=16 << 20)
        adopt_native_catalog(store, native=native, previous=files, dependencies=dependencies,
            candidate='file-adoption', directory=tmp_path / 'storage-adoption', max_chunk_rows=8192,
            max_chunk_bytes=16 << 20, rules=dict(interpretations='preserved'))
    return read_catalog(store, native=native)


@pytest.mark.parametrize('actual_native', [False, True])
def test_full_contribution_qualification_preserves_adopted_values_and_enables_recurring_replay(tmp_path, monkeypatch, native, actual_native):
    from congress_api.retention.raw_catalog import qualify_source_contributions
    store, native = SelectorStore(), native if actual_native else MemoryNative()
    raw = seed(store, native)
    monkeypatch.setattr(RawSnapshot, 'body_readings', lambda self, keys: iter(()))
    update_from_raw(store, raw_storage=raw, directory=tmp_path / 'normal', candidate='normal')
    selected = file_adopted_catalog(tmp_path, store, native)
    assert selected.selection['interpretation'] is None
    expected = {label: pa.Table.from_batches(list(selected.table(label, max_ordered_bytes=16 << 20).iter_batches())).to_pylist()
                for label in ('filenames', 'documents')}
    options = dict(raw_storage=raw, directory=tmp_path / 'qualification', candidate='qualification')
    result = qualify_source_contributions(store, **options)
    qualified = read_catalog(store, native=native)
    assert qualified.selection['interpretation']['raw_identity'] == raw.snapshot().identity
    for label, rows in expected.items():
        actual = pa.Table.from_batches(list(qualified.table(label, max_ordered_bytes=16 << 20).iter_batches())).to_pylist()
        key = 'source_id' if label == 'filenames' else 'document_id'
        assert sorted(actual, key=lambda row: row[key]) == sorted(rows, key=lambda row: row[key])
    with monkeypatch.context() as retry:
        retry.setattr(native, 'run_table', lambda *a, **k: (_ for _ in ()).throw(AssertionError('Completed native work repeated')))
        retry.setattr(RawSnapshot, 'capture_batch', lambda *a, **k: (_ for _ in ()).throw(AssertionError('Completed receipt input reread')))
        assert qualify_source_contributions(store, **options)['unchanged']
    count = raw.snapshot().manifest['captures']['rows']
    retain(store, dict(eventId=7, congress=119, chamber='House', meetingDocuments=[dict(
        url='https://example.gov/paper.pdf', documentType='Statement', name='Later label')]),
        family='congress/meetings', source_file='later.json')
    raw.publish(raw.prepare(raw.snapshot(), operation='later', captures=decode_table(store.read(CAPTURES_KEY)).slice(count)))
    update_from_raw(store, raw_storage=raw, directory=tmp_path / 'later', candidate='later')
    latest = read_catalog(store, native=native)
    row, = pa.Table.from_batches(list(latest.table('filenames', max_ordered_bytes=16 << 20).iter_batches())).to_pylist()
    assert row['source_document_label'] == ['Later label', 'Literal paper']


def test_contribution_qualification_refuses_unreplayed_source_fact_before_publication(tmp_path, monkeypatch):
    from congress_api.retention.raw_catalog import qualify_source_contributions
    from congress_api.retention.catalog_updates import update_native_catalog
    from congress_api.retention.catalog_dependency_storage import CatalogDependencyStorage
    store, native = SelectorStore(), MemoryNative()
    raw = seed(store, native)
    monkeypatch.setattr(RawSnapshot, 'body_readings', lambda self, keys: iter(()))
    update_from_raw(store, raw_storage=raw, directory=tmp_path / 'normal', candidate='normal')
    selected = read_catalog(store, native=native)
    row, = pa.Table.from_batches(list(selected.table('filenames', max_ordered_bytes=16 << 20).iter_batches())).to_pylist()
    row['source_document_label'] = ['Historical fact without matching retained receipt']
    update_native_catalog(store, native=native, previous=selected,
        dependencies=CatalogDependencyStorage.for_snapshot(selected), replacements=[row], candidate='historical',
        directory=tmp_path / 'historical', max_chunk_rows=8192, max_chunk_bytes=16 << 20, rules=dict(explicit='replacement'))
    before = store.read(MANIFEST_KEY)
    with pytest.raises(ValueError, match='qualification changes selected filenames values'):
        qualify_source_contributions(store, raw_storage=raw, directory=tmp_path / 'refused', candidate='refused')
    assert store.read(MANIFEST_KEY) == before


@pytest.mark.parametrize('actual_native', [False, True])
def test_explicit_rule_upgrade_replays_all_sources_and_preserves_untouched_ids(tmp_path, monkeypatch, native, actual_native):
    from congress_api.retention.raw_catalog import upgrade_source_rules
    from congress_api.retention.source_update_proof import read_source_update
    from congress_api.retention.catalog_scope import read_catalog_scope
    store, native = SelectorStore(), native if actual_native else MemoryNative()
    raw = seed(store, native)
    monkeypatch.setattr(RawSnapshot, 'body_readings', lambda self, keys: iter(()))
    old_seeds = [dict(url='https://example.gov/original.pdf')]
    new_seeds = [dict(url='https://example.gov/revised.pdf')]
    update_from_raw(store, raw_storage=raw, directory=tmp_path / 'old', candidate='old', seeds=old_seeds)
    previous = read_catalog(store, native=native)
    old = pa.Table.from_batches(list(previous.table('filenames', max_ordered_bytes=16 << 20).iter_batches())).to_pylist()
    paper = next(row for row in old if row['source_url'].endswith('paper.pdf'))
    before = store.read(MANIFEST_KEY)
    with pytest.raises(ValueError, match='rules or seeds changed'):
        update_from_raw(store, raw_storage=raw, directory=tmp_path / 'refuse', candidate='refuse', seeds=new_seeds)
    assert store.read(MANIFEST_KEY) == before
    options = dict(raw_storage=raw, directory=tmp_path / 'upgrade', candidate='upgrade',
                   rule_version='source-rules-20261020', seeds=new_seeds)
    result = upgrade_source_rules(store, **options)
    selected = read_catalog(store, native=native)
    values = pa.Table.from_batches(list(selected.table('filenames', max_ordered_bytes=16 << 20).iter_batches())).to_pylist()
    assert {row['source_url'] for row in values} == {'https://example.gov/paper.pdf', 'https://example.gov/revised.pdf'}
    preserved = next(row for row in values if row['source_url'].endswith('paper.pdf'))
    assert all(preserved[name] == value for name, value in paper.items())
    assert all(value is None for name, value in preserved.items() if name not in paper)
    proof = read_catalog_scope(store, result['scope_reference'])
    source_proof = read_source_update(store, proof['source_update'])
    assert source_proof['purpose'] == 'rule-upgrade'
    assert source_proof['rule_version'] == 'source-rules-20261020'
    assert selected.selection['interpretation']['rule_version'] == 'source-rules-20261020'
    with monkeypatch.context() as retry:
        retry.setattr(native, 'run_table', lambda *a, **k: (_ for _ in ()).throw(AssertionError('Completed native work repeated')))
        retry.setattr(RawSnapshot, 'capture_batch', lambda *a, **k: (_ for _ in ()).throw(AssertionError('Completed receipt input reread')))
        assert upgrade_source_rules(store, **options)['unchanged']


def test_changed_maintained_filename_rules_require_explicit_global_upgrade(tmp_path, monkeypatch):
    from congress_api.retention.raw_catalog import upgrade_source_rules
    store, native = SelectorStore(), MemoryNative()
    raw = seed(store, native)
    monkeypatch.setattr(RawSnapshot, 'body_readings', lambda self, keys: iter(()))
    update_from_raw(store, raw_storage=raw, directory=tmp_path / 'initial', candidate='initial')
    selected = read_catalog(store, native=native)
    before = store.read(MANIFEST_KEY)
    original = selected.selection['interpretation']['requirements']['filename_rules_sha256']
    monkeypatch.setattr(index, 'parser_fingerprint', lambda: original + '-changed')
    with pytest.raises(ValueError, match='rules or seeds changed'):
        update_from_raw(store, raw_storage=raw, directory=tmp_path / 'refuse', candidate='refuse')
    assert store.read(MANIFEST_KEY) == before
    upgrade_source_rules(store, raw_storage=raw, directory=tmp_path / 'upgrade', candidate='upgrade',
                         rule_version='changed-filename-rules')
    current = read_catalog(store, native=native)
    assert current.selection['interpretation']['requirements']['filename_rules_sha256'] == original + '-changed'


def test_dispatch_spills_receipt_rows_and_replays_retained_output_as_a_stream(tmp_path, monkeypatch):
    from congress_api.retention import catalog_raw_updates as dispatch
    store, native = SelectorStore(), MemoryNative()
    raw = seed(store, native)
    monkeypatch.setattr(RawSnapshot, 'body_readings', lambda self, keys: iter(()))
    observed = []
    for name in ('recover_sources', 'annotate_availability'):
        original = getattr(dispatch, name)
        def check(rows, *args, _original=original, _name=name, **kwargs):
            assert not isinstance(rows, (list, tuple)), f'{_name} retained the complete affected payload'
            assert kwargs.get('working') is not None
            observed.append(_name)
            return _original(rows, *args, **kwargs)
        monkeypatch.setattr(dispatch, name, check)
    original = dispatch.update_native_catalog
    def update(*args, **kwargs):
        rows = kwargs.get('replacements', ())
        assert not isinstance(rows, list), 'Dispatch decoded every retained interpreted row on retry'
        if rows:
            # The downstream owner hashes, groups and verifies the same input.
            assert list(rows) == list(rows)
        return original(*args, **kwargs)
    monkeypatch.setattr(dispatch, 'update_native_catalog', update)
    options = dict(raw_storage=raw, directory=tmp_path / 'candidate', candidate='streamed')
    first = update_from_raw(store, **options)
    assert observed == ['recover_sources', 'annotate_availability']
    assert first['counts'] == dict(source_rows=1, document_rows=1)
    assert update_from_raw(store, **options)['unchanged']


def test_retained_interpretation_groups_respect_bytes_and_restore_nullable_fields(tmp_path, monkeypatch):
    from congress_api.retention import catalog_raw_updates as dispatch
    schema = pa.schema([pa.field('source_url', pa.string()), pa.field('new_values', pa.list_(pa.string()))],
                       metadata={b'literal': b'preserved'})
    rows = [dict(source_url='https://example.gov/' + str(i), new_values=['literal', None, 'literal']) for i in range(9)]
    monkeypatch.setattr(dispatch, 'MAX_BYTES', 125)
    retained = dispatch._retain_rows(tmp_path / 'rows.parquet', iter(rows), schema)
    assert len(retained) == len(rows)
    assert list(retained) == rows == list(retained)
    assert retained.schema.equals(schema, check_metadata=True)
    with pq.ParquetFile(retained.path) as file:
        assert file.num_row_groups > 1
        for group in range(file.num_row_groups):
            assert file.read_row_group(group).nbytes <= 125
    with pytest.raises(ValueError, match='source row exceeds'):
        dispatch._retain_rows(retained.path, [dict(source_url='x' * 200)], schema)
    assert list(retained) == rows  # Incomplete retry did not replace the retained input.


def test_interrupted_source_interpretation_resumes_retained_replay_without_raw_payload(tmp_path, monkeypatch):
    store, native = SelectorStore(), MemoryNative()
    raw = seed(store, native)
    monkeypatch.setattr(RawSnapshot, 'body_readings', lambda self, keys: iter(()))
    write = index.write_filename_metadata
    monkeypatch.setattr(index, 'write_filename_metadata', lambda *a, **k: (_ for _ in ()).throw(OSError('interpreter stopped')))
    options = dict(raw_storage=raw, directory=tmp_path / 'retained', candidate='first')
    with pytest.raises(OSError, match='interpreter stopped'):
        update_from_raw(store, **options)
    assert store.read(MANIFEST_KEY) is None
    assert (options['directory'] / 'source-replay/replay-complete.json').is_file()
    monkeypatch.setattr(index, 'write_filename_metadata', write)
    monkeypatch.setattr(RawSnapshot, 'capture_batch', lambda *a: (_ for _ in ()).throw(AssertionError('Completed source payload repeated')))
    monkeypatch.setattr(RawSnapshot, 'states_for', lambda *a: (_ for _ in ()).throw(AssertionError('All state values collected')))
    result = update_from_raw(store, **options)
    assert result['counts'] == dict(source_rows=1, document_rows=1)


def test_empty_raw_inventory_keeps_explicit_seed_sources(tmp_path, monkeypatch):
    store, native = SelectorStore(), MemoryNative()
    raw = RawStorage(store, native)
    monkeypatch.setattr(RawSnapshot, 'body_readings', lambda self, keys: iter(()))
    result = update_from_raw(store, raw_storage=raw, directory=tmp_path / 'seeded', candidate='seeded',
        seeds=iter([dict(url='https://example.gov/seed.pdf')]))
    assert result['counts'] == dict(source_rows=1, document_rows=1)
    with read_catalog(store, native=native) as selected:
        row, = pa.Table.from_batches(list(selected.table('filenames', max_ordered_bytes=16 << 20).iter_batches())).to_pylist()
        assert row['source_url'] == 'https://example.gov/seed.pdf'


@pytest.mark.parametrize('actual_native', [False, True])
def test_schema_addition_retry_uses_the_retained_interpretation_schema(tmp_path, monkeypatch, native, actual_native):
    from congress_api.retention import catalog_updates
    store, native = SelectorStore(), native if actual_native else MemoryNative()
    raw = seed(store, native)
    monkeypatch.setattr(RawSnapshot, 'body_readings', lambda self, keys: iter(()))
    update_from_raw(store, raw_storage=raw, directory=tmp_path / 'initial', candidate='initial')
    count = raw.snapshot().manifest['captures']['rows']
    retain(store, {}, family='house/witness-xml', source_file='witness.xml', url='https://docs.house.gov/7.xml',
        body=b'<witness-list meeting-id="HMKP7"><panel><witness><firstname>Jane</firstname><lastname>Doe</lastname><witness-documents><witness-document type="WS"><files><file doc-url="https://example.gov/paper.pdf" doc-type="PDF"/></files></witness-document></witness-documents></witness></panel></witness-list>')
    raw.publish(raw.prepare(raw.snapshot(), operation='witness', captures=decode_table(store.read(CAPTURES_KEY)).slice(count)))
    publish = catalog_updates.publish_native_catalog
    monkeypatch.setattr(catalog_updates, 'publish_native_catalog', lambda *a, **k: (_ for _ in ()).throw(OSError('worker stopped')))
    options = dict(raw_storage=raw, directory=tmp_path / 'witness', candidate='witness')
    with pytest.raises(OSError, match='worker stopped'):
        update_from_raw(store, **options)
    monkeypatch.setattr(catalog_updates, 'publish_native_catalog', publish)
    monkeypatch.setattr(native, 'run_table', lambda *a, **k: (_ for _ in ()).throw(AssertionError('Completed schema update repeated')))
    update_from_raw(store, **options)
    with read_catalog(store, native=native) as selected:
        rows = pa.Table.from_batches(list(selected.table('filenames', max_ordered_bytes=16 << 20).iter_batches())).to_pylist()
        row = next(row for row in rows if row['source_url'] == 'https://example.gov/paper.pdf')
        assert row['source_witness_name'] == ['Jane Doe']
