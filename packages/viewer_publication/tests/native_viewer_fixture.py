"""Exercise both browser representations from the same complete typed fixture."""
import importlib.util
import json
from pathlib import Path
import runpy
import os
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'packages/congress_shared/src'), str(ROOT / 'packages/congress_api/src'), str(ROOT / 'tests'), str(ROOT / 'apps/site/scripts')]
import pyarrow as pa
import pyarrow.parquet as pq
from congress_api.retention.catalog_batches import prepare_native_catalog_components, iterator_prepared_components
from congress_api.retention.catalog_dependency_storage import CatalogDependencyStorage
from congress_api.retention.catalog_selection import CatalogComponents
from congress_api.retention.catalog_validation import catalog_reference_requirements
from congress_api.retention.catalog_publication import read_catalog
from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.immutable_metadata import MetadataObjects, encoded
from test_catalog_coalesced_batches import Native

folder = Path(sys.argv[1])
os.environ['FILENAME_FIXTURE_NATIVE_IDENTITIES'] = '1'
runpy.run_path(str(ROOT / 'scripts/publication/filename-test-fixture.py'), run_name='native_legacy_fixture')
spec = importlib.util.spec_from_file_location('stable_fixture_builder', ROOT / 'scripts/publication/publish-filename-viewer.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
legacy = json.loads((folder / 'indexes/catalog.json').read_bytes())
sources = pq.read_table(folder / legacy['files']['filenames']['key'])
documents = pq.read_table(folder / legacy['files']['documents']['key'])
if os.environ.get('FILENAME_FIXTURE_SCHEMA_ADDITION'):
    # This update scenario starts from current maintained grouping metadata;
    # the ordinary historical differential fixture intentionally has older metadata.
    from congress_api.retention import document_index as index
    seed_path=folder/'current-grouping/document-filenames.parquet'
    seed_path.parent.mkdir()
    index.write_document_indexes(seed_path,sources.to_pylist(),sources.schema,
        catalog_id='b'*32,preserve_columns=True)
    sources=pq.read_table(seed_path);documents=pq.read_table(seed_path.with_name('documents.parquet'))
if os.environ.get('FILENAME_FIXTURE_OCCURRENCE_ADDITION'):
    occurrence_kind = sources.schema.field('source_occurrences').type
    sources = sources.drop(['source_occurrences'])
    documents = documents.drop(['source_occurrences'])
if os.environ.get('FILENAME_FIXTURE_GIANT_DOCUMENT'):
    # Document observations are saved document values, distinct from every
    # source's occurrence sequence. No grouping or canonicalization is replayed.
    values = documents['source_occurrences'].to_pylist()
    occurrence = {'source_page_title': ['document-only José 🏛️' + 'é' * 1100, '', None],
                  'source_page_url': []}
    values[0] = [None, occurrence, occurrence] * 6000
    documents = documents.set_column(documents.schema.get_field_index('source_occurrences'),
        documents.schema.field('source_occurrences'), pa.array(values, type=documents.schema.field('source_occurrences').type))
    assert documents.slice(0, 1).nbytes > 16 * 1024 * 1024
store, native = LocalStore(folder / 'native-store'), Native()
orders = lambda table: table.append_column(pa.field('_catalog_order', pa.int64(), nullable=False), pa.array(range(len(table)), type=pa.int64()))
document_chunks = [orders(documents)]
if os.environ.get('FILENAME_FIXTURE_GIANT_DOCUMENT'):
    from congress_api.retention.catalog_adoption import ordered_chunks
    path = folder / 'native-document-input.parquet'
    pq.write_table(documents, path)
    with pq.ParquetFile(path) as file:
        document_chunks = list(ordered_chunks(file, max_rows=1024, max_bytes=1 << 24))
prepared = prepare_native_catalog_components(store, native, candidate='browser-fixture',
    source_chunks=[orders(sources)], document_chunks=document_chunks, source_schema=sources.schema,
    document_schema=documents.schema, max_chunk_rows=1024, max_chunk_bytes=1 << 24)
components = CatalogComponents(store).apply(None, retired=[], prepared=iterator_prepared_components(store, prepared))
owner = CatalogDependencyStorage(native=native, store=store, namespace='browser-fixture', source_schema=sources.schema,
                                 max_rows=1 if os.environ.get('FILENAME_FIXTURE_SCHEMA_ADDITION') else 64, max_bytes=1 << 24)
dependency = owner.prepare(None, replacements=sources.to_pylist(), deletions=(),
                           source_orders={row['source_id']:i for i,row in enumerate(sources.to_pylist())})
import base64
selected = MetadataObjects(store, 'catalog-selections-v2').put(dict(version=2, components=components,
    dependency=dependency, schemas={name:base64.b64encode(table.schema.serialize()).decode() for name,table in
                                  [('filenames',sources),('documents',documents)]},
    counts=dict(source_rows=len(sources),document_rows=len(documents)),requirements=catalog_reference_requirements(),scope=None))
store.put_catalog_manifest(encoded(dict(version=2, selection=selected)), expected_version=None)
snapshot = read_catalog(store, native=native)
viewer_metrics = {}
builder.publish_selected(snapshot, folder / 'native-public', review_identities=None, memory_metrics=viewer_metrics)
(folder / 'native-viewer-metrics.json').write_text(json.dumps(viewer_metrics, indent=2))
if os.environ.get('FILENAME_FIXTURE_GIANT_DOCUMENT'):
    (folder / 'giant-document-metrics.json').write_text(json.dumps(dict(
        document_id=documents['document_id'][0].as_py(), logical_arrow_bytes=documents.slice(0,1).nbytes,
        observations=len(documents['source_occurrences'][0].values), fixture_native='in-memory test double'), indent=2))

(folder / "document-records.json").write_text(json.dumps(documents.to_pylist(), default=str))

if os.environ.get('FILENAME_FIXTURE_SCHEMA_ADDITION'):
    from congress_api.retention.catalog_updates import update_native_catalog
    expanded=sources.schema
    # The historical serving fixture predates the grouping engine's two optional
    # claim columns; declare them with the new optional field for real updates.
    for name in ('document_kind_source','filename_document_kind','source_new_literal'):
        if name not in expanded.names:expanded=expanded.append(pa.field(name,pa.list_(pa.string())))
    if os.environ.get('FILENAME_FIXTURE_OCCURRENCE_ADDITION'):
        expanded=expanded.append(pa.field('source_occurrences',occurrence_kind))
    current=CatalogDependencyStorage(native=native,store=store,namespace='browser-fixture',source_schema=expanded,
        max_rows=1,max_bytes=1<<24)
    row=current.selected(snapshot.selection['dependency']).source(sources['source_id'][0].as_py())
    row['source_new_literal']=['new','new',None]
    if os.environ.get('FILENAME_FIXTURE_OCCURRENCE_ADDITION'):
        row['source_occurrences']=[{'source_page_title':['added occurrence']}]
    update_native_catalog(store,native=native,previous=snapshot,dependencies=current,replacements=[row],
        candidate='schema-addition',directory=folder/'schema-update',max_chunk_rows=1024,max_chunk_bytes=1<<24,rules={'grouping':'maintained-v1'})
    after=read_catalog(store,native=native)
    before=json.loads((folder/'native-public/manifest.json').read_bytes())
    metrics={}
    builder.publish_selected(after,folder/'native-expanded',previous=before,
        read_asset=lambda name:(folder/'native-public'/name).read_bytes(),review_identities=None,memory_metrics=metrics)
    (folder/'nullable-metrics.json').write_text(json.dumps(metrics))
    source_records=[row for batch in after.table('filenames',max_ordered_bytes=1<<24).iter_batches() for row in batch.to_pylist()]
    document_records=[row for batch in after.table('documents',max_ordered_bytes=1<<24).iter_batches() for row in batch.to_pylist()]
    (folder/'expanded-source-records.json').write_text(json.dumps(source_records,default=str))
    (folder/'expanded-document-records.json').write_text(json.dumps(document_records,default=str))
    # Explicit analysis is query work, measured separately from viewer building.
    with builder.viewer.Catalog.from_snapshot(after,max_ordered_bytes=1<<24) as analysis:
        for record in source_records:
            position=analysis.resolve(record['source_id'])
            assert analysis.record(position)==record
            assert analysis.document(position)==next(doc for doc in document_records if doc['document_id']==record['document_id'])
        assert analysis.search({'q':'new','field':'source_new_literal','scope':'all'})['total']==1
