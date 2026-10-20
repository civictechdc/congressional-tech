"""Existing catalog byte/value/identity mappings qualify before native selection."""
from copy import deepcopy
import pyarrow as pa
import pytest

from congress_api.retention import document_index as index
from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.catalog_dependency_storage import CatalogDependencyStorage
from congress_api.retention.catalog_publication import read_catalog, publish_catalog, MANIFEST_KEY
from congress_api.retention.catalog_adoption import adopt_native_catalog
from test_catalog_dependencies import source, identity
from test_catalog_coalesced_batches import Native


def existing(tmp_path, store):
    rows = [source('a.pdf', 'A'), source('b.pdf', 'B'), source('a.pdf', 'B'), source('other.pdf', 'O')]
    schema = pa.schema([*index.SOURCE_SCHEMA, ('capture_outcome', index.STRINGS)])
    root = tmp_path / 'old'
    root.mkdir()
    index.write_document_indexes(root / 'document-filenames.parquet', rows, schema, catalog_id='original')
    with read_catalog(store) as previous:
        publish_catalog(store, root / 'document-filenames.parquet', root / 'documents.parquet', previous=previous)
    return rows


def test_explicit_adoption_preserves_all_fields_and_original_row_document_links(tmp_path):
    import pyarrow.parquet as pq
    store, native = LocalStore(tmp_path / 'store'), Native()
    existing(tmp_path, store)
    previous = read_catalog(store)
    sources, documents = pq.read_table(previous.filenames_path), pq.read_table(previous.documents_path)
    owner = CatalogDependencyStorage(native=native, store=store, namespace='adopt',
        source_schema=sources.schema, max_rows=64, max_bytes=1 << 20)
    result = adopt_native_catalog(store, native=native, previous=previous, dependencies=owner,
        candidate='adoption', directory=tmp_path / 'work', max_chunk_rows=64, max_chunk_bytes=1 << 20,
        rules=dict(interpretation='preserved'))
    selected = read_catalog(store, native=native)
    actual_sources = pa.Table.from_batches(list(selected.table('filenames', max_ordered_bytes=1 << 20).iter_batches()))
    actual_documents = pa.Table.from_batches(list(selected.table('documents', max_ordered_bytes=1 << 20).iter_batches()))
    assert actual_sources.equals(sources, check_metadata=True)
    assert actual_documents.equals(documents, check_metadata=True)
    for old_offset in range(len(sources)):
        # Old saved table position retains the exact source/document link at
        # adoption; later durable links use stable IDs rather than offsets.
        assert actual_sources['source_id'][old_offset].as_py() == sources['source_id'][old_offset].as_py()
        assert actual_sources['document_id'][old_offset].as_py() == sources['document_id'][old_offset].as_py()
    assert selected.selection['adoption'] == result['adoption_reference']
    assert owner.selected(selected.selection['dependency']).order(identity(sources.to_pylist()[2])) == 2
    assert len(native.tables) == 5  # Source/group/URL dependencies and two mixed output batches.


@pytest.mark.parametrize('corrupt', ['field', 'order', 'mapping', 'omission'])
def test_adoption_refuses_changed_native_values_and_preserves_v1_selector(tmp_path, corrupt):
    class ChangedNative(Native):
        def run_table(self, table, **request):
            if request['dataset'].startswith('catalog-filenames-'):
                records = table.to_pylist()
                if corrupt == 'field':
                    records[0]['filename'] = 'wrong.pdf'
                elif corrupt == 'order':
                    records[0]['_catalog_order'] = -1
                elif corrupt == 'mapping':
                    records[0]['document_id'] = 'wrong-document'
                elif corrupt == 'omission':
                    records.pop()
                table = pa.Table.from_pylist(records, schema=table.schema)
            return super().run_table(table, **request)
    import pyarrow.parquet as pq
    store, native = LocalStore(tmp_path / 'store'), ChangedNative()
    existing(tmp_path, store)
    previous = read_catalog(store)
    before = store.read(MANIFEST_KEY)
    with pq.ParquetFile(previous.filenames_path) as source_file:
        owner = CatalogDependencyStorage(native=native, store=store, namespace='adopt',
            source_schema=source_file.schema_arrow, max_rows=64, max_bytes=1 << 20)
    with pytest.raises(ValueError, match='changed selected values|row count|rows differ|count'):
        adopt_native_catalog(store, native=native, previous=previous, dependencies=owner,
            candidate='adoption', directory=tmp_path / 'work', max_chunk_rows=64, max_chunk_bytes=1 << 20,
            rules=dict(interpretation='preserved'))
    assert store.read(MANIFEST_KEY) == before


from test_docspec_boundary import native


def test_actual_native_adoption_keeps_exact_old_pair_and_retained_proof_on_retry(tmp_path, native, monkeypatch):
    import pyarrow.parquet as pq
    store = LocalStore(tmp_path / 'store')
    existing(tmp_path, store)
    previous = read_catalog(store)
    expected = {label: pq.read_table(previous.filenames_path if label == 'filenames' else previous.documents_path)
                for label in ('filenames', 'documents')}
    owner = CatalogDependencyStorage(native=native, store=store, namespace='actual-adoption',
        source_schema=expected['filenames'].schema, max_rows=64, max_bytes=1 << 20)
    options = dict(native=native, dependencies=owner, candidate='actual-adoption', directory=tmp_path / 'work',
                   max_chunk_rows=64, max_chunk_bytes=1 << 20, rules=dict(interpretation='preserved'))
    result = adopt_native_catalog(store, previous=previous, **options)
    selected = read_catalog(LocalStore(store.root), native=native)
    for label in expected:
        actual = pa.Table.from_batches(list(selected.table(label, max_ordered_bytes=1 << 20).iter_batches()))
        assert actual.equals(expected[label], check_metadata=True)
    monkeypatch.setattr(native, 'run_table', lambda *a, **k: (_ for _ in ()).throw(AssertionError('Completed adoption repeated')))
    assert adopt_native_catalog(store, previous=selected, **options)['unchanged']
    assert selected.selection['adoption'] == result['adoption_reference']
