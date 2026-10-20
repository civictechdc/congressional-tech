"""The maintained group builder receives only a closed affected scope."""
from copy import deepcopy

import pyarrow as pa
import pyarrow.parquet as pq

from test_catalog_dependencies import source, identity, SelectedDependencies
from congress_api.retention import document_index as index
from congress_api.retention.catalog_dependencies import affected_sources
from congress_api.retention.catalog_scope import prepare_catalog_scope


def test_scoped_bridge_split_matches_every_reference_field_and_saved_source_links(tmp_path, monkeypatch):
    rows = [source('a.pdf', 'A'), source('b.pdf', 'B'), source('a.pdf', 'B'), source('unrelated.pdf', 'U')]
    schema = pa.schema([*index.SOURCE_SCHEMA, ('capture_outcome', index.STRINGS)])
    old_rows, old_schema, old_docs, _ = index.prepare_document_indexes(deepcopy(rows), schema)
    selected = SelectedDependencies(old_rows)
    scope = affected_sources(selected, deletions=[identity(rows[2])])
    orders = {identity(row): i for i, row in enumerate(old_rows)}
    monkeypatch.setattr(index, 'extract', lambda *a, **k: (_ for _ in ()).throw(AssertionError('Repeated classification')))
    prepared = prepare_catalog_scope(tmp_path / 'scope', scope, schema=old_schema,
                                     source_orders=orders, candidate='stable-candidate')
    assert prepared.source_rows == 2
    chunks = list(prepared.source_chunks(max_rows=1, max_bytes=1 << 20))
    assert len(chunks) == 2
    assert all(len(chunk) == 1 for chunk in chunks)
    assert all('_catalog_order' in chunk.column_names for chunk in chunks)
    assert len(list(prepared.document_chunks(max_rows=10, max_bytes=1 << 20))) == 1
    untouched_sources = [row for row in old_rows if identity(row) == identity(rows[3])]
    untouched_documents = [row for row in old_docs if row['document_id'] == untouched_sources[0]['document_id']]
    actual_sources = pq.read_table(prepared.filenames_path).to_pylist() + untouched_sources
    actual_documents = pq.read_table(prepared.documents_path).to_pylist() + untouched_documents
    expected_sources, _, expected_documents, _ = index.prepare_document_indexes(deepcopy([rows[0], rows[1], rows[3]]), old_schema)
    sort = lambda values: sorted(values, key=lambda row: row['source_id'])
    assert sort(pa.Table.from_pylist(actual_sources, schema=prepared.source_schema).to_pylist()) == sort(pa.Table.from_pylist(expected_sources, schema=prepared.source_schema).to_pylist())
    assert sort(pa.Table.from_pylist(actual_documents, schema=prepared.document_schema).to_pylist()) == sort(pa.Table.from_pylist(expected_documents, schema=prepared.document_schema).to_pylist())
    links = {row['source_id']: row for row in prepared.source_links()}
    assert links[identity(rows[0])]['source_order'] == 0
    assert links[identity(rows[1])]['source_order'] == 1
    assert links[identity(rows[2])]['new_document_id'] is None
    for row in actual_sources:
        if row['source_id'] in links:
            assert links[row['source_id']]['new_document_id'] == row['document_id']
    # Stable candidate identity produces the same application metadata on retry.
    again = prepare_catalog_scope(tmp_path / 'again', scope, schema=old_schema,
                                 source_orders=orders, candidate='stable-candidate')
    assert again.source_schema == prepared.source_schema
    assert again.document_schema == prepared.document_schema


def test_scoped_grouping_retains_columns_needed_by_unaffected_catalog_rows(tmp_path):
    schema = pa.schema([*index.SOURCE_SCHEMA, ('capture_outcome', index.STRINGS),
                        ('publication_code_code', index.STRINGS), ('publication_type', index.STRINGS)])
    a = source('a.pdf', 'A', publication_code_code=['report'], publication_type=['report'])
    other = source('other.pdf', 'O', publication_code_code=['verbatim'], publication_type=['normalized'])
    old_rows, old_schema, _, _ = index.prepare_document_indexes(deepcopy([a, other]), schema)
    scope = affected_sources(SelectedDependencies(old_rows), replacements=[old_rows[0]])
    class KeyedOrders:
        def __getitem__(self, key):
            assert key == identity(a)
            return 7
        def __iter__(self):
            raise AssertionError('Unrelated source order must not be enumerated')
    result = prepare_catalog_scope(tmp_path / 'scope', scope, schema=old_schema,
        source_orders=KeyedOrders(), candidate='columns-preserved')
    assert 'publication_code_code' in result.source_schema.names
    assert list(result.source_values())[0]['publication_code_code'] == ['report']
    assert list(result.source_chunks(max_rows=10, max_bytes=1 << 20))[0]['_catalog_order'].to_pylist() == [7]


def test_scoped_chunks_refuse_oversized_rows_and_missing_orders(tmp_path):
    import pytest
    from congress_api.retention.catalog_dependencies import DependencyGap
    a = source('a.pdf', 'A')
    scope = affected_sources(SelectedDependencies([]), replacements=[a])
    with pytest.raises(DependencyGap, match='source order'):
        prepare_catalog_scope(tmp_path / 'missing', scope, schema=index.SOURCE_SCHEMA,
                              source_orders={}, candidate='missing')
    result = prepare_catalog_scope(tmp_path / 'sized', scope, schema=index.SOURCE_SCHEMA,
                                  source_orders={identity(a): 0}, candidate='sized')
    with pytest.raises(ValueError, match='One catalog row'):
        list(result.source_chunks(max_rows=4, max_bytes=1))


def grouped_candidate(tmp_path, store, owner, selected, rows, *, name, deletions=()):
    from congress_api.retention.catalog_batches import prepare_native_catalog_components, iterator_prepared_components
    scope = affected_sources(owner.selected(selected), replacements=rows, deletions=deletions)
    orders = {key: owner.selected(selected).order(key) for key in scope.before}
    position = selected['next_source_order'] if selected else 0
    for key in scope.after:
        if key not in orders:
            orders[key], position = position, position + 1
    prepared = prepare_catalog_scope(tmp_path / name, scope, schema=owner.source_schema,
                                     source_orders=orders, candidate=name)
    candidate = owner.prepare(selected, replacements=prepared.source_values(), deletions=deletions,
                              source_orders=orders)
    references = prepare_native_catalog_components(store, owner.native, candidate=name,
        source_chunks=prepared.source_chunks(max_rows=64, max_bytes=1 << 20),
        document_chunks=prepared.document_chunks(max_rows=64, max_bytes=1 << 20),
        source_schema=prepared.source_schema, document_schema=prepared.document_schema,
        max_chunk_rows=64, max_chunk_bytes=1 << 20)
    return prepared, candidate, dict(iterator_prepared_components(store, references))


def test_scope_proof_binds_complete_old_new_membership_and_rejects_missing_outputs(tmp_path):
    import pytest
    from test_catalog_coalesced_batches import Native
    from test_raw_source_sync import MemoryStore
    from congress_api.retention.catalog_dependency_storage import CatalogDependencyStorage
    from congress_api.retention.catalog_scope import verify_catalog_scope, read_catalog_scope, iterator_scope_components
    from congress_api.retention.catalog_batches import CatalogComponentReader
    from congress_api.retention.catalog_dependencies import DependencyGap
    rows = [source('a.pdf', 'A'), source('b.pdf', 'B'), source('a.pdf', 'B'), source('other.pdf', 'O')]
    old_rows, schema, _, _ = index.prepare_document_indexes(deepcopy(rows),
        pa.schema([*index.SOURCE_SCHEMA, ('capture_outcome', index.STRINGS)]))
    native, store = Native(), MemoryStore()
    owner = CatalogDependencyStorage(native=native, store=store, namespace='scope',
                                     source_schema=schema, max_rows=64, max_bytes=1 << 20)
    adoption, old, old_refs = grouped_candidate(tmp_path, store, owner, None, old_rows, name='adopt')
    prepared, changed, refs = grouped_candidate(tmp_path, store, owner, old, [], name='split',
                                                deletions=[identity(rows[2])])
    lookup_calls = []
    def lookup(key):
        lookup_calls.append(key)
        return old_refs.get(key)
    arguments = dict(dependencies=owner, dependency_before=old, dependency_after=changed,
        prepared=prepared, base=dict(selector_sha256='selected', selected_ref=None),
        component_lookup=lookup, read_component=CatalogComponentReader(store).read,
        rules=dict(grouping='maintained-v1'))
    with pytest.raises(DependencyGap, match='Missing prepared component'):
        verify_catalog_scope(store, prepared_components=[], **arguments)
    # Candidate source rows alone cannot authorize an arbitrary routing root.
    # Dropping the entire reverse directory used to pass the per-row checks.
    with pytest.raises(DependencyGap, match='unaffected dependency'):
        verify_catalog_scope(store, prepared_components=refs.items(),
                             **{**arguments, 'dependency_after': {**changed, 'alias_root': None}})
    reference = verify_catalog_scope(store, prepared_components=refs.items(), **arguments)
    proof = read_catalog_scope(store, reference)
    assert proof['counts'] == dict(retired_source_rows=3, prepared_source_rows=2,
                                   retired_document_rows=1, prepared_document_rows=2)
    assert dict(iterator_scope_components(store, proof, 'prepared')) == refs
    retired = dict(iterator_scope_components(store, proof, 'retired'))
    assert len(retired) == 1
    untouched = old_rows[3]['document_id']
    assert untouched not in lookup_calls
    assert proof['dependency_before'] == old and proof['dependency_after'] == changed
    assert owner.selected(old).source(identity(rows[2])) is not None
    # The logical source/document results share just one source and one document
    # native batch, rather than one dataset pair for every new document.
    pins = {value['tables']['filenames']['chunks'][0]['release']['dataset']['dataset']
            for value in map(CatalogComponentReader(store).read, refs.values())}
    assert len(pins) == 1


def test_scope_component_pages_stream_in_order_with_constant_page_reads():
    from test_raw_source_sync import MemoryStore
    from congress_api.retention.catalog_scope import _component_pages, iterator_scope_components
    store = MemoryStore()
    baseline = len(store.objects)
    values = [(f'doc-{i:04}', {'proof': i}) for i in range(130)]
    inventory = _component_pages(store, values)
    iterator = iterator_scope_components(store, {'prepared': inventory}, 'prepared')
    # First output requires one bounded page; the chain need not be collected
    # or reversed before the consumer can proceed.
    assert next(iterator) == values[0]
    assert list(iterator) == values[1:]
    assert len(store.objects) - baseline == 3


from test_docspec_boundary import native


def test_actual_native_scope_proof_replay_calls_are_measured_separately(tmp_path, native, record_property):
    from test_raw_source_sync import MemoryStore
    from congress_api.retention.catalog_dependency_storage import CatalogDependencyStorage
    from congress_api.retention.catalog_scope import verify_catalog_scope
    from congress_api.retention.catalog_batches import CatalogComponentReader
    rows = [source('a.pdf', 'A'), source('b.pdf', 'B'), source('a.pdf', 'B'), source('other.pdf', 'O')]
    old_rows, schema, _, _ = index.prepare_document_indexes(deepcopy(rows),
        pa.schema([*index.SOURCE_SCHEMA, ('capture_outcome', index.STRINGS)]))
    store, calls = MemoryStore(), []
    original = native.run_table
    def count(table, **options):
        calls.append(options['dataset'])
        return original(table, **options)
    native.run_table = count
    owner = CatalogDependencyStorage(native=native, store=store, namespace='scope-native',
                                     source_schema=schema, max_rows=64, max_bytes=1 << 20)
    _, old, old_refs = grouped_candidate(tmp_path, store, owner, None, old_rows, name='adopt')
    adoption_calls = len(calls)
    prepared, changed, refs = grouped_candidate(tmp_path, store, owner, old, [], name='split',
                                                deletions=[identity(rows[2])])
    preparation_calls = len(calls) - adoption_calls
    position = len(calls)
    verify_catalog_scope(store, dependencies=owner, dependency_before=old, dependency_after=changed,
        prepared=prepared, base=dict(selector_sha256='selected', selected_ref=None),
        component_lookup=old_refs.get, prepared_components=refs.items(),
        read_component=CatalogComponentReader(store).read, rules=dict(grouping='maintained-v1'))
    replay_calls = len(calls) - position
    record_property('adoption_native_run_table_calls', adoption_calls)
    record_property('correction_preparation_native_run_table_calls', preparation_calls)
    record_property('scope_proof_native_completed_replay_calls', replay_calls)
    assert adoption_calls == 6
    assert preparation_calls == 6
    assert replay_calls == 4
    # Replay calls name already prepared immutable dependency datasets, not new
    # versions. Their cost is still nonzero and reported separately.
    assert calls[position:] == calls[adoption_calls:adoption_calls + 4]


def test_nullable_list_members_preserve_exact_sources_and_match_full_document_summary(tmp_path):
    rows = [source('a.pdf', 'A', source_new_literal=['new', 'new', None]),
            source('b.pdf', 'A', source_new_literal=['second', None])]
    schema = pa.schema([*index.SOURCE_SCHEMA, ('capture_outcome', index.STRINGS),
                        ('source_new_literal', index.STRINGS)])
    expected_sources, _, expected_documents, _ = index.prepare_document_indexes(deepcopy(rows), schema)
    scope = affected_sources(SelectedDependencies([]), replacements=rows)
    result = prepare_catalog_scope(tmp_path / 'nullable-list', scope, schema=schema,
        source_orders={identity(row): i for i, row in enumerate(rows)}, candidate='nullable-list')
    actual_sources = list(result.source_values())
    actual_documents = pq.read_table(result.documents_path).to_pylist()
    assert {row['source_id']: row['source_new_literal'] for row in actual_sources} == {
        identity(row): row['source_new_literal'] for row in rows}
    assert actual_documents[0]['source_new_literal'] == ['new', 'second', None]
    for actual, expected, logical in [(actual_sources, expected_sources, result.source_schema),
                                     (actual_documents, expected_documents, result.document_schema)]:
        normalize = lambda values: sorted(pa.Table.from_pylist(values, schema=logical).to_pylist(), key=lambda row: row['source_id'])
        assert normalize(actual) == normalize(expected)
