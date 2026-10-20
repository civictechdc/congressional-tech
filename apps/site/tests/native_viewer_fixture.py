"""Exercise both browser representations from the same complete typed fixture."""
import importlib.util
import json
from pathlib import Path
import runpy
import os
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'packages/congress_api/src'), str(ROOT / 'tests'), str(ROOT / 'apps/site/scripts')]
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
runpy.run_path(str(ROOT / 'apps/site/scripts/filename-test-fixture.py'), run_name='native_legacy_fixture')
spec = importlib.util.spec_from_file_location('stable_fixture_builder', ROOT / 'apps/site/scripts/publish-filename-viewer.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
legacy = json.loads((folder / 'indexes/catalog.json').read_bytes())
sources = pq.read_table(folder / legacy['files']['filenames']['key'])
documents = pq.read_table(folder / legacy['files']['documents']['key'])
store, native = LocalStore(folder / 'native-store'), Native()
orders = lambda table: table.append_column(pa.field('_catalog_order', pa.int64(), nullable=False), pa.array(range(len(table)), type=pa.int64()))
prepared = prepare_native_catalog_components(store, native, candidate='browser-fixture',
    source_chunks=[orders(sources)], document_chunks=[orders(documents)], source_schema=sources.schema,
    document_schema=documents.schema, max_chunk_rows=1024, max_chunk_bytes=1 << 24)
components = CatalogComponents(store).apply(None, retired=[], prepared=iterator_prepared_components(store, prepared))
owner = CatalogDependencyStorage(native=native, store=store, namespace='browser-fixture', source_schema=sources.schema,
                                 max_rows=64, max_bytes=1 << 24)
dependency = owner.prepare(None, replacements=sources.to_pylist(), deletions=(),
                           source_orders={row['source_id']:i for i,row in enumerate(sources.to_pylist())})
import base64
selected = MetadataObjects(store, 'catalog-selections-v2').put(dict(version=2, components=components,
    dependency=dependency, schemas={name:base64.b64encode(table.schema.serialize()).decode() for name,table in
                                  [('filenames',sources),('documents',documents)]},
    counts=dict(source_rows=len(sources),document_rows=len(documents)),requirements=catalog_reference_requirements(),scope=None))
store.put_catalog_manifest(encoded(dict(version=2, selection=selected)), expected_version=None)
snapshot = read_catalog(store, native=native)
builder.publish_selected(snapshot, folder / 'native-public', review_identities=None)
