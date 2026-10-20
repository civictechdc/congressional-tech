"""Bounded adoption batches preserve scalar dependency values and refusals."""
from copy import deepcopy

import pyarrow as pa
import pytest

from congress_api.retention import catalog_dependency_storage as storage
from congress_api.retention import catalog_adoption as adoption
from congress_api.retention import document_index as index
from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.catalog_dependencies import DependencyGap
from congress_api.retention.catalog_publication import read_catalog
from congress_api.retention.catalog_rows import core_table
from test_catalog_adoption import existing
from test_catalog_dependencies import source
from test_catalog_rows import Native, OCC
from test_raw_source_sync import MemoryStore

SCHEMA = pa.schema([*index.SOURCE_SCHEMA,
    pa.field('source_id', pa.string()), pa.field('document_id', pa.string()),
    pa.field('source_occurrences', OCC, metadata={b'origin': b'exact'}),
    pa.field('unsigned', pa.uint64()), pa.field('binary', pa.binary())],
    metadata={b'catalog_id': b'preserved', b'custom': b'original'})


def table_values():
    occurrence = dict(label=['é', 'é'], url=[None, '', 'https://example.gov/x'])
    values = [None, [], [None], [occurrence, occurrence],
              [dict(label=[], url=None)], [occurrence, None],
              [dict(label=['x' * 180, 'x' * 180], url=['u'])] * 64]
    rows = [source(f'{i}.pdf', f'body-{i}', document_id=f'doc-{i // 2}',
                   source_occurrences=value, unsigned=2**64 - 1 if i % 2 else None,
                   binary=b'\x00\xff' if i % 2 else None)
            for i, value in enumerate(values)]
    for row in rows:
        row['source_id'] = index.source_identity(row)
    return pa.Table.from_pylist(rows, schema=SCHEMA)


def owner(native, store):
    return storage.CatalogDependencyStorage(native=native, store=store, namespace='batch-equivalence',
        source_schema=SCHEMA, max_rows=8, max_bytes=4096)


@pytest.mark.parametrize('sparse_orders', [False, True])
def test_batched_native_outputs_and_selection_equal_scalar_reference(sparse_orders):
    table = table_values()
    orders = dict(zip(table['source_id'].to_pylist(), [40, 2, 19, 100, 0, 73, 8])) if sparse_orders else None
    outputs = []
    for scalar in [True, False]:
        native, store = Native(), MemoryStore()
        dependencies = owner(native, store)
        chunks = [table.slice(0, 0), *([table.slice(i, 1) for i in range(len(table))]
                  if scalar else [table.slice(0, 3), table.slice(3)])]
        selection = dependencies.adopt(chunks, source_orders=orders, first_unused_order=150 if sparse_orders else 0)
        selected = dependencies.selected(selection)
        actual = [selected.source(identity) for identity in table['source_id'].to_pylist()]
        assert pa.Table.from_pylist(actual, schema=SCHEMA).equals(table, check_metadata=True)
        assert [selected.order(identity) for identity in table['source_id'].to_pylist()] == (
            [40, 2, 19, 100, 0, 73, 8] if sparse_orders else list(range(len(table))))
        assert selection['next_source_order'] == (150 if sparse_orders else len(table))
        assert all(len(part) <= 8 and part.nbytes <= 4096 for part in native.tables.values())
        assert any('-occ-' in name for name in native.tables)  # Large logical list uses bounded native parts.
        outputs.append((selection, store.objects, native.tables))
    assert outputs[0][:2] == outputs[1][:2]
    assert outputs[0][2].keys() == outputs[1][2].keys()
    for name, expected in outputs[0][2].items():
        assert outputs[1][2][name].equals(expected, check_metadata=True)


@pytest.mark.parametrize('damage', ['identity', 'negative', 'bool', 'float', 'overflow',
    'missing-order', 'duplicate-order', 'duplicate-source', 'duplicate-across-chunks', 'schema'])
def test_batch_refusals_match_scalar_reference(damage):
    table = table_values().slice(0, 3)
    rows = table.to_pylist()
    orders = {row['source_id']: i for i, row in enumerate(rows)}
    if damage == 'identity':
        rows[1]['source_id'] = 'wrong-saved-id'
    elif damage in {'negative', 'bool', 'float', 'overflow'}:
        orders[rows[1]['source_id']] = {'negative': -1, 'bool': True, 'float': 1.5, 'overflow': 2**70}[damage]
    elif damage == 'missing-order':
        del orders[rows[1]['source_id']]
    elif damage == 'duplicate-order':
        orders[rows[1]['source_id']] = 0
    elif damage in {'duplicate-source', 'duplicate-across-chunks'}:
        rows.append(deepcopy(rows[0]))
    table = pa.Table.from_pylist(rows, schema=SCHEMA)
    if damage == 'schema':
        table = table.replace_schema_metadata({b'catalog_id': b'changed'})
    errors = []
    for scalar in [True, False]:
        native, store = Native(), MemoryStore()
        dependencies = owner(native, store)
        chunks = [table.slice(i, 1) for i in range(len(table))] if scalar else (
            [table.slice(0, 2), table.slice(2)] if damage == 'duplicate-across-chunks' else [table])
        with pytest.raises((DependencyGap, KeyError, OverflowError)) as error:
            dependencies.adopt(chunks, source_orders=orders)
        errors.append((type(error.value), str(error.value)))
        assert native.tables == {}  # Staging refusals precede native preparation.
    assert errors[0] == errors[1]


def test_adoption_batches_the_existing_dependency_helper(monkeypatch):
    table = table_values().slice(0, 6)
    helper = storage.dependency_tables
    calls = []
    def counted(rows, *args, **kwargs):
        calls.append(len(rows))
        return helper(rows, *args, **kwargs)
    monkeypatch.setattr(storage, 'dependency_tables', counted)
    owner(Native(), MemoryStore()).adopt([table.slice(0, 3), table.slice(3)])
    assert calls == [3, 3]


def test_catalog_adoption_feeds_bounded_grouped_original_schema(tmp_path, monkeypatch):
    store, native = LocalStore(tmp_path / 'store'), Native()
    existing(tmp_path, store)
    with read_catalog(store) as previous:
        import pyarrow.parquet as pq
        with pq.ParquetFile(previous.filenames_path) as file:
            schema = file.schema_arrow
        dependencies = storage.CatalogDependencyStorage(native=native, store=store, namespace='bounded-adopt',
            source_schema=schema, max_rows=64, max_bytes=1 << 20)
        original = dependencies.adopt
        sizes = []
        def checked(chunks):
            def observed():
                for chunk in chunks:
                    assert chunk.schema.equals(schema, check_metadata=True)
                    assert len(chunk) <= 64 and core_table(chunk).nbytes <= 1 << 20
                    assert chunk.nbytes <= 1 << 20 or len(chunk) == 1
                    sizes.append(len(chunk))
                    yield chunk
            return original(observed())
        monkeypatch.setattr(dependencies, 'adopt', checked)
        adoption.adopt_native_catalog(store, native=native, previous=previous, dependencies=dependencies,
            candidate='bounded-input', directory=tmp_path / 'adopt', max_chunk_rows=64,
            max_chunk_bytes=1 << 20, rules=dict(interpretation='preserved'))
    assert sum(sizes) == 4 and max(sizes) > 1
