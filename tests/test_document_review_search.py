"""Compare reviewed search with an independent source/group result-set oracle."""
from copy import deepcopy
from base64 import b64decode
from itertools import product
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from house_naming.categories import document_families
from congress_api.retention.document_review_catalog import write_candidates
from congress_api.retention.document_review_portable import export_bundle
from congress_api.retention.document_review_receipts import file_digest, row_digest
from test_document_review_catalog import fixture
from test_document_filename_viewer import viewer


def search_catalog(tmp_path, unsupported=False, unclassified=False, pages=1):
    args=fixture(tmp_path,unsupported,pages=pages)
    render=tmp_path/'page-1.png'
    render.write_bytes(b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a3ioAAAAASUVORK5CYII='))
    source=pq.read_table(args['sources']).to_pylist()[0]
    source.update(source_url='https://example.test/original',congress=['118'],format=['pdf'],
                  document_kind=None if unclassified else ['amendment'])
    alias=dict(source,source_id='alias',filename='alias.pdf',source_url='https://example.test/download?download=1',
               congress=['119'],document_kind=None if unclassified else ['biography'])
    control=dict(source,source_id='control',document_id='u',filename='control.pdf',body_key=None,document_kind=['amendment'])
    unknown=dict(control,source_id='unknown',document_id='z',filename='unknown.pdf',document_kind=None)
    sources=[source,alias,control,unknown]
    for row in sources:
        row['document_family']=document_families(row['document_kind']) or None
        row['document_kind_source']=['filename'] if row['document_kind'] else None
    document=pq.read_table(args['documents']).to_pylist()[0]
    document.update(source)
    document['document_kind']=None if unclassified else ['amendment','biography']
    document['document_family']=document_families(document['document_kind']) or None
    documents=[document,dict(control,body_keys=[]),dict(unknown,body_keys=[])]
    for path,rows in [(args['sources'],sources),(args['documents'],documents)]:
        pq.write_table(pa.Table.from_pylist(rows).replace_schema_metadata({b'catalog_id':b'pair'}),path)
    original=dict(document_id='d',filename=source['filename'],after_kind=document['document_kind'] or [],members=[source,alias])
    ledger=tmp_path/'ledger.jsonl';ledger.write_text(json.dumps(original)+'\n')
    receipt=json.loads(args['receipt'].read_text());receipt['input_ledger_sha256']=file_digest(ledger)
    renders = {}
    for number in range(1, pages + 1):
        path = tmp_path / f'page-{number}.png'; path.write_bytes(render.read_bytes())
        renders[str(path)] = file_digest(path)
    receipt['records'][0]['rendered_pages']=renders
    args['receipt'].write_text(json.dumps(receipt));args['receipt_sha256']=file_digest(args['receipt'])
    proposals=json.loads(args['proposals'].read_text())
    proposals['records'][0]['source_row_sha256']=row_digest(original)
    proposals['records'][0]['evidence']['receipt_sha256']=args['receipt_sha256']
    args['proposals'].write_text(json.dumps(proposals));args['proposals_sha256']=file_digest(args['proposals'])
    write_candidates(**args);summary=args['output']/'summary.json'
    export_bundle(summary,file_digest(summary),args['sources'],args['documents'],tmp_path/'portable')
    manifest=tmp_path/'portable/manifest.json'
    return viewer.Catalog(args['sources'],review_manifest=manifest,review_sha256=file_digest(manifest)),manifest


def oracle(sources, documents, query):
    matches=set()
    for row in sources:
        text=query.get('q','').lower();field=query.get('field','filename');value=row.get(field)
        searchable=' | '.join(value) if isinstance(value,list) else value or ''
        if text not in searchable.lower():continue
        if any(value and value!='__null__' and value not in (row.get(key) or [])
               for key in viewer.FILTERS if (value:=query.get(key))):continue
        matches.add(row['document_id'])
    retained={row['document_id'] for row in sources if row['body_key']}
    if query.get('retained')=='yes':matches &= retained
    if query.get('retained')=='no':matches -= retained
    for key in ('document_kind','document_family'):
        if query.get(key)=='__null__':matches &= {row['document_id'] for row in documents if not row.get(key)}
    return matches


@pytest.mark.parametrize('unsupported',[False,True])
@pytest.mark.parametrize('unclassified',[False,True])
def test_review_mode_matches_independent_result_sets_and_preserves_original(tmp_path,unsupported,unclassified):
    catalog,manifest=search_catalog(tmp_path,unsupported,unclassified)
    assert catalog.review_error is None
    sources=catalog.table.to_pylist();documents=catalog.documents.to_pylist()
    baseline_hashes=[file_digest(path) for path in [catalog.path,catalog.document_path]]
    fields=('document_kind','document_family','document_kind_source')
    selected=catalog.review_snapshot.candidates['d']['document']
    for reviewed in [False,True]:
        expected_sources,expected_documents=deepcopy(sources),deepcopy(documents)
        if reviewed and not unsupported:
            for row in expected_sources+expected_documents:
                if row['document_id']=='d':row.update({field:selected.get(field) for field in fields})
        expected_by_id={row['document_id']:row for row in expected_documents}
        filters=catalog.info['review_facets']
        queries=[dict(document_kind=kind,document_family=family,congress=congress,retained=retained,q=text)
                 for kind,family,congress,retained,text in product(
                    ['', '__null__']+filters['document_kind'], ['', '__null__']+filters['document_family'],
                    ['', '118','119'], ['', 'yes','no'], ['', 'alias','control'])]
        queries += [dict(field=field,q=text) for field,text in product(fields+('source_url',),['letter','amendment','assistant','download'])]
        for query in queries:
            result=catalog.search(dict(query,classification='reviewed' if reviewed else '',limit=100))
            assert {row['document_id'] for row in result['rows']}==oracle(expected_sources,expected_documents,query),query
            assert result['total']==len(result['rows'])
            for row in result['rows']:
                # List rows add classification provenance in reviewed mode, but
                # ordinary original rows retain their existing display columns.
                for field in fields[:2]:assert row.get(field)==expected_by_id[row['document_id']].get(field)
                if reviewed and row['document_id']=='d':
                    assert row['_review_status']==('annotation_only_unsupported_forms' if unsupported else 'candidate_applied')
                elif not reviewed:assert '_review_status' not in row
    assert sources==catalog.table.to_pylist() and documents==catalog.documents.to_pylist()
    assert baseline_hashes==[file_digest(path) for path in [catalog.path,catalog.document_path]]
    assert 'tax-return' not in catalog.info['review_facets']['document_kind']
    if not unsupported:
        row=catalog.search(dict(classification='reviewed',document_kind='letter'))['rows'][0]
        row['document_kind'].append('changed by caller')
        assert catalog.search(dict(classification='reviewed',document_kind='letter'))['rows'][0]['document_kind']==['letter']


def test_reviewed_search_refuses_wrong_pin_changed_files_and_missing_bundle(tmp_path):
    catalog,manifest=search_catalog(tmp_path)
    with pytest.raises(viewer.SnapshotChanged,match='review snapshot'):
        catalog.search(dict(classification='reviewed',review='old'))
    with pytest.raises(ValueError,match='Unknown classification'):
        catalog.search(dict(classification='automatic'))
    manifest.write_text('{}')
    with pytest.raises(ValueError,match='snapshot changed'):catalog.search(dict(classification='reviewed'))
    assert catalog.search({})['total']==3
    ordinary=viewer.Catalog(catalog.path)
    with pytest.raises(ValueError,match='not configured'):ordinary.search(dict(classification='reviewed'))
    assert ordinary.search({})==catalog.search({})
