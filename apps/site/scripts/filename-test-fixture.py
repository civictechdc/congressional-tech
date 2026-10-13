"""Small catalog covering group retention, API scope and source provenance."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pyarrow as pa
import pyarrow.parquet as pq

spec = importlib.util.spec_from_file_location('publisher', Path(__file__).with_name('publish-filename-viewer.py'))
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)
root = Path(sys.argv[1])
generation = 'a' * 32
catalog_id = 'b' * 32
folder = root / 'catalog-generations' / generation
folder.mkdir(parents=True)
(root / 'indexes').mkdir()
columns = list(publisher.viewer.LIST_COLUMNS) + ['source_occurrences', 'content_document_kind']
scalar = {'filename','source_url','body_key','source_id','document_id'}
observation = pa.list_(pa.struct([(key, pa.list_(pa.string())) for key in ['source_page_url','source_page_title','source_link_label','source_occurrence_scope']]))
schema = pa.schema([(key, observation if key == 'source_occurrences' else pa.string() if key in scalar else pa.list_(pa.string())) for key in columns], metadata={b'catalog_id': catalog_id.encode(), b'house_naming_version': b'fixture'})
rows = []
for i, (filename, url, body, group, role, kind) in enumerate([
    ('unfetched alias.pdf', 'https://committee.test/alias', None, 'A', 'document', None),
    ('Saved statement.pdf', 'https://committee.test/final', 'bodies/sha256/aa/file.gz', 'A', 'document', ['witness-statement']),
    ('Unfetched.pdf', 'https://committee.test/unfetched', None, 'B', 'document', None),
    ('1', 'https://api.congress.gov/v3/hearing/116/senate/1?format=json', None, 'C', 'document', None),
    ('Recovered', None, None, 'D', 'source-record', None),
    ('failed.pdf', 'https://committee.test/failure', 'body-failed', 'E', 'error-response', None),
]):
    row = dict.fromkeys(columns)
    row.update(filename=filename, source_url=url, body_key=body, source_id=hashlib.sha256(str(i).encode()).hexdigest(),
               document_id=group, record_role=[role], document_kind=kind, document_family=['statement'] if kind else None,
               format=['pdf'] if filename.endswith('.pdf') else None, congress=['117'] if i == 2 else None)
    if i == 2:
        row['source_occurrences'] = [dict(source_page_url=['https://committee.test/hearing'], source_page_title=['Hearing page'], source_link_label=['Witness name'], source_occurrence_scope=['anchor'])]
    if i == 4:
        row['recovered_filename'] = ['Recovered witness.pdf']
    rows.append(row)
files = {}
for name, subset in [('filenames', rows), ('documents', [rows[i] for i in [1,2,3,4,5]])]:
    path = folder / ('document-filenames.parquet' if name == 'filenames' else 'documents.parquet')
    pq.write_table(pa.Table.from_pylist(subset, schema=schema), path, row_group_size=2, compression='zstd')
    files[name] = dict(key=str(path.relative_to(root)), bytes=path.stat().st_size, rows=len(subset), sha256=publisher.digest(path))
(root / 'indexes/catalog.json').write_text(json.dumps(dict(version=1, generation=generation, catalog_id=catalog_id, files=files)))
publisher.publish(root, root / 'public')
queries = [{}, {'scope':'all'}, {'retained':'no','scope':'all'}, {'q':'alias','retained':'no'}, {'q':'alias'},
           {'q':'ALIAS','document_kind':'__null__'}, {'document_kind':'__null__'}, {'scope':'capture-records','retained':'no'},
           {'q':'Witness name','field':'source_occurrences'}, {'scope':'all','q':'Recovered witness'}, {'congress':'117'}, {'q':'unfetched','format':'pdf'}, {'scope':'all','page':'99','limit':'2'}]
catalog = publisher.viewer.Catalog(folder / 'document-filenames.parquet')
expected = [dict(query=query, result=catalog.search(query)) for query in queries]
(root / 'expected.json').write_text(json.dumps(expected))
(root / 'source-records.json').write_text(json.dumps(rows))
