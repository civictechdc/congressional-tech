"""Generate only bounded synthetic browser-search data; never acquire sources."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'apps/site/scripts'))
spec = importlib.util.spec_from_file_location('publisher', ROOT / 'apps/site/scripts/publish-filename-viewer.py')
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)
root = Path(sys.argv[1])
count = int(sys.argv[2]) if len(sys.argv) > 2 else 8192
root.mkdir(parents=True, exist_ok=True)
folder = root / 'catalog-generations' / ('a' * 32)
folder.mkdir(parents=True)
(root / 'indexes').mkdir()
columns = list(publisher.viewer.LIST_COLUMNS) + ['source_occurrences', 'content_document_kind']
scalar = {'filename', 'source_url', 'body_key', 'source_id', 'document_id'}
observation = pa.list_(pa.struct([(key, pa.list_(pa.string())) for key in ['source_page_url', 'source_page_title', 'source_link_label', 'source_occurrence_scope']]))
schema = pa.schema([(key, observation if key == 'source_occurrences' else pa.string() if key in scalar else pa.list_(pa.string())) for key in columns], metadata={b'catalog_id': b'b' * 32, b'house_naming_version': b'fixture'})
rows = []
for i in range(count):
    row = dict.fromkeys(columns)
    row.update(filename=f'{i:06d} Witness.pdf', source_url=f'https://committee.test/{i}/' + 'path-' * 180,
               source_id=hashlib.sha256(str(i).encode()).hexdigest(), document_id=str(i // 2),
               record_role=['document'], format=['pdf'], congress=['117'] if i % 2 else ['118'],
               content_document_kind=['José 🏛️ ' + 'wide-' * 210 + (' marker' if i % 101 == 0 else '')])
    if i % 5 == 0:
        row['content_document_kind'] = None
    row['source_occurrences'] = None if i % 7 == 0 else [dict(source_page_title=['José 🏛️', str(i % 113)], source_link_label=['Witness'], source_page_url=None, source_occurrence_scope=[])]
    rows.append(row)
files = {}
for name in ['filenames', 'documents']:
    path = folder / ('document-filenames.parquet' if name == 'filenames' else 'documents.parquet')
    subset = rows if name == 'filenames' else rows[::2]
    pq.write_table(pa.Table.from_pylist(subset, schema=schema), path, row_group_size=256, compression='zstd')
    files[name] = dict(key=str(path.relative_to(root)), bytes=path.stat().st_size, rows=len(subset), sha256=publisher.digest(path))
(root / 'indexes/catalog.json').write_text(json.dumps(dict(version=1, generation='a' * 32, catalog_id='b' * 32, files=files)))
publisher.publish(root, root / 'public', review_identities=None)
# The publisher chooses its own physical layout. Fix the consumed synthetic
# fixture's row-group shape explicitly while preserving all Arrow values.
manifest_path = root / 'public/manifest.json'
manifest = json.loads(manifest_path.read_text())
part = manifest['files']['filenames']
path = root / 'public' / part['path']
table = pq.read_table(path)
pq.write_table(table, path, row_group_size=256, compression='zstd')
assert pq.read_table(path).equals(table, check_metadata=True)
part.update(bytes=path.stat().st_size, sha256=publisher.digest(path))
manifest_path.write_text(json.dumps(manifest))
(root / 'fixture.json').write_text(json.dumps({'rows': count, 'row_group_size': 256, 'seed': 'deterministic-row-number', 'source_url_chars': len(rows[0]['source_url']), 'wide_chars': len(rows[1]['content_document_kind'][0])}, indent=2))
