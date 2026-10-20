"""Native physical batches and proof PUTs grow by bounded batches, not documents."""
from contextlib import contextmanager
import os
import shutil

import pyarrow as pa
import pytest

from congress_api.retention.catalog_batches import (
    CatalogComponentReader, iterator_prepared_components, prepare_native_catalog_components,
)
from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.catalog_partitions import CatalogTable
from native_test_helpers import native_test_client


SCHEMA = pa.schema([('source_id', pa.string()), ('document_id', pa.string()), ('aliases', pa.list_(pa.string()))],
                   metadata={b'catalog_id': b'candidate'})


class Store(LocalStore):
    def __init__(self, root):
        super().__init__(root)
        self.puts = []
        self.reads = []

    def put(self, key, data, **options):
        self.puts.append((key, len(data)))
        return super().put(key, data, **options)

    def read(self, key):
        self.reads.append(key)
        return super().read(key)


class Native:
    def __init__(self):
        self.tables, self.reads = {}, []

    def run_table(self, table, **request):
        self.tables[request['dataset']] = table
        return dict(id='initial', verified=True, dataset=dict(dataset=request['dataset'], computed={}, related=None,
                    groups=dict(source=dict(rows=len(table)))))

    @contextmanager
    def source_batches(self, release, *, schema=None):
        key = release['dataset']['dataset']
        self.reads.append(key)
        table = self.tables[key]
        yield pa.RecordBatchReader.from_batches(table.schema, table.to_batches())


def prepare(store, native, count, *, schema=SCHEMA):
    physical = schema.append(pa.field('_catalog_order', pa.int64(), nullable=False))
    records = [dict(source_id=f'source-{index}', document_id=f'doc-{index:04}',
                    aliases=['same', 'same'], _catalog_order=index) for index in range(count)]
    table = pa.Table.from_pylist(records, schema=physical)
    return prepare_native_catalog_components(store, native, candidate=f'coalesced-{count}',
        source_chunks=[table], document_chunks=[table], source_schema=schema, document_schema=schema,
        max_chunk_rows=256, max_chunk_bytes=1 << 20)


@pytest.mark.parametrize('count,proof_pages', [(2, 1), (130, 3)])
def test_coalesced_documents_share_native_pins_and_bounded_proof_pages(tmp_path, count, proof_pages):
    store, native = Store(tmp_path), Native()
    prepared = prepare(store, native, count)
    references = list(iterator_prepared_components(store, prepared))
    assert len(references) == count
    assert len(native.tables) == 2
    assert len(store.puts) == 2 + 1 + proof_pages  # Physical pins, shared schema, component pages.
    assert all(size <= 1 << 20 for _, size in store.puts)
    reader = CatalogComponentReader(Store(tmp_path))
    first = reader.read(references[0][1])
    last = reader.read(references[-1][1])
    assert first['tables']['filenames']['chunks'][0]['release'] == last['tables']['filenames']['chunks'][0]['release']
    assert first['validation']['counts'] == dict(source_rows=1, document_rows=1)
    assert not native.reads
    chunk = first['tables']['filenames']['chunks'][0]
    table = CatalogTable(SCHEMA, [(chunk['name'], chunk['release'])], native=native,
        order_column='_catalog_order', max_ordered_bytes=1 << 20,
        views={chunk['name']: dict(components=chunk['components'], rows=chunk['rows'])})
    rows = pa.Table.from_batches(list(table.iter_batches())).to_pylist()
    assert [row['document_id'] for row in rows] == [references[0][0]]
    assert len(native.reads) == 1


def test_actual_native_mixed_components_replay_and_filter_shared_pin(tmp_path):
    binary = os.environ.get('DOCSPEC_BINARY') or shutil.which('docspec')
    if not binary:
        pytest.skip('Set DOCSPEC_BINARY to the qualified maintained CLI')
    native = native_test_client(binary, tmp_path / 'native')
    store = Store(tmp_path / 'archive')
    prepared = prepare(store, native, 2)
    assert prepare(store, native, 2) == prepared
    reference = next(iterator_prepared_components(store, prepared))[1]
    component = CatalogComponentReader(store).read(reference)
    chunk = component['tables']['filenames']['chunks'][0]
    assert chunk['release']['dataset']['groups']['source']['rows'] == 2
    table = CatalogTable(SCHEMA, [(chunk['name'], chunk['release'])], native=native,
        order_column='_catalog_order', max_ordered_bytes=1 << 20,
        views={chunk['name']: dict(components=chunk['components'], rows=chunk['rows'])})
    actual = pa.Table.from_batches(list(table.iter_batches()))
    assert actual.schema.equals(SCHEMA, check_metadata=True)
    assert actual.to_pylist() == [dict(source_id='source-0', document_id='doc-0000', aliases=['same', 'same'])]


def test_selected_table_reads_shared_pin_once_and_excludes_retired_member(tmp_path):
    from congress_api.retention.catalog_batches import SelectedCatalogTable
    store, native = Store(tmp_path), Native()
    original = list(iterator_prepared_components(store, prepare(store, native, 130)))
    old_physical = {key: table.to_pylist() for key, table in native.tables.items()}
    # Keep all original members except doc-0000 and select its changed candidate.
    new_schema = SCHEMA.with_metadata({b'catalog_id': b'next-logical-catalog'})
    replacement = list(iterator_prepared_components(store, prepare(store, native, 1, schema=new_schema)))
    selected = original[1:] + replacement
    consumer = Store(tmp_path)
    table = SelectedCatalogTable(new_schema, lambda: iter(selected), store=consumer, native=native,
                                 label='filenames', rows=130, max_ordered_bytes=1 << 20)
    batches = list(table.iter_batches(columns=['source_id', 'document_id'], batch_size=7))
    assert all(batch.num_rows <= 7 for batch in batches)
    rows = pa.Table.from_batches(batches).to_pylist()
    assert len(rows) == 130
    assert len({row['document_id'] for row in rows}) == 130
    assert len(native.reads) == 2
    assert len(consumer.reads) == len(set(consumer.reads))
    assert batches[0].schema.metadata == new_schema.metadata
    assert {key: native.tables[key].to_pylist() for key in old_physical} == old_physical
    historical = CatalogComponentReader(consumer).read(original[0][1])
    assert historical['tables']['filenames']['schema'] != CatalogComponentReader(consumer).read(replacement[0][1])['tables']['filenames']['schema']


def test_selected_table_rejects_duplicate_component_before_reading_native(tmp_path):
    from congress_api.retention.catalog_batches import SelectedCatalogTable
    store, native = Store(tmp_path), Native()
    reference = next(iterator_prepared_components(store, prepare(store, native, 2)))
    table = SelectedCatalogTable(SCHEMA, lambda: iter([reference, reference]), store=store, native=native,
                                 label='filenames', rows=2, max_ordered_bytes=1 << 20)
    with pytest.raises(ValueError, match='Duplicate selected catalog component'):
        list(table.iter_batches())
    assert not native.reads


def test_selected_table_adds_nullable_fields_without_rewriting_or_coercing_old_pins(tmp_path):
    from congress_api.retention.catalog_batches import SelectedCatalogTable
    class ExactNative(Native):
        @contextmanager
        def source_batches(self, release, *, schema=None):
            physical = self.tables[release['dataset']['dataset']].schema
            assert schema.equals(physical, check_metadata=True)
            with super().source_batches(release, schema=schema) as reader:
                yield reader
    store, native = Store(tmp_path), ExactNative()
    old = list(iterator_prepared_components(store, prepare(store, native, 2)))
    frozen = dict(native.tables)
    added = pa.field('reading', pa.struct([('size', pa.uint64()), ('bytes', pa.binary())]),
                     metadata={b'meaning': b'retained exact reading'})
    schema = pa.schema([SCHEMA.field(0), added, *list(SCHEMA)[1:]],
                       metadata={b'catalog_id': b'new'})
    physical = schema.append(pa.field('_catalog_order', pa.int64(), nullable=False))
    values = [dict(source_id='source-new', document_id='doc-new', aliases=['kept', 'kept'],
                   reading=dict(size=2**64-1, bytes=b'exact'), _catalog_order=2)]
    table = pa.Table.from_pylist(values, schema=physical)
    new = list(iterator_prepared_components(store, prepare_native_catalog_components(
        store, native, candidate='added-column', source_chunks=[table], document_chunks=[table],
        source_schema=schema, document_schema=schema, max_chunk_rows=256, max_chunk_bytes=1 << 20)))
    selected = old + new
    reader = SelectedCatalogTable(schema, lambda: iter(selected), store=store, native=native,
        label='filenames', rows=3, max_ordered_bytes=1 << 20)
    actual = pa.Table.from_batches(list(reader.iter_batches(batch_size=1)))
    assert actual.schema.equals(schema, check_metadata=True)
    rows = actual.to_pylist()
    assert [row['reading'] for row in rows] == [None, None, values[0]['reading']]
    assert rows[0]['aliases'] == ['same', 'same']
    assert len(native.reads) == 2
    assert all(native.tables[key].equals(value, check_metadata=True) for key, value in frozen.items())
    only_new = pa.Table.from_batches(list(reader.iter_batches(columns=['reading'])))
    assert only_new.to_pylist() == [dict(reading=row['reading']) for row in rows]
    assert only_new.schema.field(0).equals(added, check_metadata=True)


@pytest.mark.parametrize('damage', ['required', 'type', 'removed', 'reordered', 'field_metadata', 'metadata'])
def test_selected_nullable_adaptation_refuses_other_schema_changes_before_payloads(tmp_path, damage):
    from congress_api.retention.catalog_batches import SelectedCatalogTable
    store, native = Store(tmp_path), Native()
    selected = list(iterator_prepared_components(store, prepare(store, native, 2)))
    fields, metadata = list(SCHEMA), SCHEMA.metadata
    if damage == 'required':
        fields.append(pa.field('new', pa.string(), nullable=False))
    elif damage == 'type':
        fields[0] = pa.field('source_id', pa.int64())
    elif damage == 'removed':
        fields.pop()
    elif damage == 'reordered':
        fields.reverse()
    elif damage == 'field_metadata':
        fields[0] = fields[0].with_metadata({b'changed': b'meaning'})
    else:
        metadata = dict(metadata, policy=b'changed')
    reader = SelectedCatalogTable(pa.schema(fields, metadata=metadata), lambda: iter(selected),
        store=store, native=native, label='filenames', rows=2, max_ordered_bytes=1 << 20)
    with pytest.raises(ValueError, match='application schemas differ'):
        list(reader.iter_batches())
    assert not native.reads
