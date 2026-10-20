"""Large affected components use disposable indexes, preserving exact values."""
from collections.abc import Mapping

from congress_api.retention.catalog_dependencies import affected_sources, dependency_tables, NativeCatalogDependencies
from congress_api.retention import document_index as index
from test_catalog_dependencies import SelectedDependencies, source, identity
from test_catalog_coalesced_batches import Native
import pyarrow as pa


def test_connected_closure_spools_rows_and_frontier_without_losing_typed_values():
    rows = [source(f'{i}.pdf', 'shared', source_new_values=[str(i), None, str(i)]) for i in range(1000)]
    changed = {**rows[0], 'source_new_values': ['corrected', None, 'corrected']}
    scope = affected_sources(SelectedDependencies(rows), replacements=iter([changed]))
    assert isinstance(scope.before, Mapping) and not isinstance(scope.before, dict)
    assert isinstance(scope.after, Mapping) and not isinstance(scope.after, dict)
    assert len(scope.before) == len(scope.after) == scope.sources_read == 1000
    for row in rows:
        key = identity(row)
        assert scope.before[key] == row
        assert scope.after[key] == (changed if key == identity(changed) else row)
    assert scope.after[identity(changed)]['source_new_values'] == ['corrected', None, 'corrected']
    scope.close()


def test_native_lookup_cache_spools_many_leaves_and_alias_members(tmp_path):
    schema = pa.schema([*index.SOURCE_SCHEMA, ('capture_outcome', index.STRINGS)])
    rows = [source(f'{i}.pdf', 'shared') for i in range(100)]
    native, source_pins, alias_pins = Native(), {}, []
    for position in range(0, len(rows), 5):
        source_table, alias_table = dependency_tables(rows[position:position + 5], schema, first_order=position)
        pin = native.run_table(source_table, dataset=f'sources-{position}', operation='initial', definition='test')
        for row in rows[position:position + 5]:
            source_pins[identity(row)] = pin
        alias_pins.append(native.run_table(alias_table, dataset=f'aliases-{position}', operation='initial', definition='test'))
    selected = NativeCatalogDependencies(native=native, source_schema=schema,
        locate_source=source_pins.get, locate_alias=lambda _: iter(alias_pins), max_rows=20, max_bytes=1 << 20)
    scope = affected_sources(selected, replacements=[rows[0]])
    assert len(scope.before) == 100
    assert not isinstance(selected._sources, dict)
    reads = len(native.reads)
    assert list(selected.members(('body', 'shared'))) == sorted(identity(row) for row in rows)
    assert len(native.reads) == reads
    for order, row in enumerate(rows):
        assert selected.order(identity(row)) == order
    scope.close()
    selected.close()


def test_dependency_preparation_never_assembles_the_complete_changed_scope_as_arrow(tmp_path, monkeypatch):
    from congress_api.retention import catalog_dependency_storage as storage
    from congress_api.retention.catalog_cache import LocalStore
    rows = [source(f'{i}.pdf', 'shared') for i in range(100)]
    schema = pa.schema([*index.SOURCE_SCHEMA, ('capture_outcome', index.STRINGS)])
    owner = storage.CatalogDependencyStorage(native=Native(), store=LocalStore(tmp_path / 'store'),
        namespace='bounded-preparation', source_schema=schema, max_rows=4, max_bytes=1 << 20)
    # Limit the transient typed source-leaf assembly as well as submitted Runs.
    class Tables:
        def from_pylist(self, values, **kwargs):
            assert len(values) <= 5, 'Whole affected scope assembled before leaf splitting'
            return pa.Table.from_pylist(values, **kwargs)
        def __getattr__(self, name):
            return getattr(pa.Table, name)
    class Arrow:
        Table = Tables()
        def __getattr__(self, name):
            return getattr(pa, name)
    monkeypatch.setattr(storage, 'pa', Arrow())
    candidate = owner.prepare(None, replacements=iter(rows))
    selected = owner.selected(candidate)
    assert len(selected.members(('body', 'shared'))) == len(rows)
    for order, row in enumerate(rows):
        assert selected.order(identity(row)) == order
        assert selected.source(identity(row)) == pa.Table.from_pylist([row], schema=schema).to_pylist()[0]


def test_prepared_scope_keeps_orders_and_mappings_on_disk_and_preserves_every_field(tmp_path):
    from copy import deepcopy
    import pyarrow.parquet as pq
    from congress_api.retention.catalog_scope import prepare_catalog_scope
    rows = [source(f'{i}.pdf', 'shared') for i in range(300)]
    schema = pa.schema([*index.SOURCE_SCHEMA, ('capture_outcome', index.STRINGS)])
    old, logical, _, _ = index.prepare_document_indexes(deepcopy(rows), schema)
    scope = affected_sources(SelectedDependencies(old), deletions=[identity(old[0])])
    orders = {identity(row): position * 7 for position, row in enumerate(old)}
    prepared = prepare_catalog_scope(tmp_path / 'scope', scope, schema=logical,
        source_orders=orders, candidate='disk-mapping')
    assert not isinstance(prepared.source_orders, dict)
    assert not isinstance(prepared.source_document_ids, dict)
    assert not isinstance(prepared.document_ids, tuple)
    expected_sources, _, expected_documents, _ = index.prepare_document_indexes(deepcopy(rows[1:]), logical)
    by_id = lambda values: {row['source_id']: row for row in values}
    normalize = lambda values, schema: pa.Table.from_pylist(values, schema=schema).to_pylist()
    assert by_id(list(prepared.source_values())) == by_id(normalize(expected_sources, prepared.source_schema))
    assert pq.read_table(prepared.documents_path).to_pylist() == normalize(expected_documents, prepared.document_schema)
    assert [row['source_order'] for row in prepared.source_links()] == list(orders.values())
    assert [value for chunk in prepared.source_chunks(max_rows=4, max_bytes=1 << 20)
            for value in chunk['_catalog_order'].to_pylist()] == list(orders.values())[1:]
    assert list(prepared.document_chunks(max_rows=4, max_bytes=1 << 20))[0]['_catalog_order'].to_pylist() == [0]
    prepared.close()
    scope.close()
