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
