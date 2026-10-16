"""Package receipt admission writes candidates without altering retained indexes."""
from copy import deepcopy
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from pypdf import PdfWriter
import pytest

from congress_api.retention.document_review_catalog import write_candidates, selected_groups
from congress_api.retention.document_review_receipts import file_digest, row_digest, load_reviews


def fixture(tmp_path, unsupported=False):
    pdf=tmp_path/'body.pdf';writer=PdfWriter()
    writer.add_blank_page(width=100,height=100);writer.write(pdf)
    digest=file_digest(pdf);body=f'bodies/sha256/{digest[:2]}/{digest}.gz'
    source=dict(document_id='d',source_id='s',filename='amendment.pdf',body_key=body,record_role=['document'],
        media_type=['application/pdf'],http_status=['200'],body_format=['pdf'],document_kind=['amendment'])
    doc=dict(source,body_keys=[body],source_occurrences=[dict(literal=['é',None,'é'])])
    original=dict(document_id='d',filename='amendment.pdf',after_kind=['amendment'],members=[deepcopy(source)])
    ledger=tmp_path/'ledger.jsonl';ledger.write_text(json.dumps(original)+'\n')
    render=tmp_path/'page-1.png';render.write_bytes(b'fixture-render')
    fetched=dict(document_id='d',filename='amendment.pdf',body_key=body,sha256=digest,path=str(pdf),pages=1)
    fetch=tmp_path/'fetch.json';fetch.write_text(json.dumps(dict(results=[fetched])))
    forms=['letter']+(['tax-return'] if unsupported else [])
    record=dict(fetched,reviewer='assistant',all_pages_visually_reviewed=True,observed_document_forms=forms,
        rendered_pages={str(render):file_digest(render)},independent_reference=False,release_approved=False)
    receipt=tmp_path/'receipt.json'
    receipt.write_text(json.dumps(dict(input_ledger=str(ledger),input_ledger_sha256=file_digest(ledger),
        fetch_results_path=str(fetch),fetch_results_sha256=file_digest(fetch),records=[record],
        independent_reference=False,release_approved=False)))
    proposal=dict(document_id='d',source_row_sha256=row_digest(original),status='assistant_proposal',
        proposed_primary_forms=['letter'],proposed_component_forms=forms[1:],independent_reference=False,
        release_approved=False,evidence=dict(receipt=str(receipt),receipt_sha256=file_digest(receipt),
            body_key=body,sha256=digest,pages=1))
    proposals=tmp_path/'proposals.json';proposals.write_text(json.dumps(dict(records=[proposal])))
    paths=[]
    for name,row in [('sources.parquet',source),('documents.parquet',doc)]:
        path=tmp_path/name;pq.write_table(pa.Table.from_pylist([row]).replace_schema_metadata({b'catalog_id':b'pair'}),path);paths.append(path)
    return dict(sources=paths[0],documents=paths[1],proposals=proposals,proposals_sha256=file_digest(proposals),
        receipt=receipt,receipt_sha256=file_digest(receipt),output=tmp_path/'output')


@pytest.mark.parametrize('unsupported',[False,True])
def test_package_bundle_preserves_inputs_nested_values_and_full_packet(tmp_path,unsupported):
    args=fixture(tmp_path,unsupported)
    before={p:p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    result=write_candidates(**args)
    assert result['reviewed_groups']==result['source_rows']==result['reviewed_pages']==1
    assert result['baseline_files_unchanged'] and result['withdrawal_restores_baseline']
    candidate=json.loads((args['output']/'candidates.jsonl').read_text())
    assert candidate['status']==('annotation_only_unsupported_forms' if unsupported else 'candidate_applied')
    assert candidate['document']['source_occurrences']==[{'literal':['é',None,'é']}]
    assert candidate['document']['document_kind']==(['amendment'] if unsupported else ['letter'])
    assert all(p.read_bytes()==data for p,data in before.items())
    assert not result['production_selected'] and not result['independent_reference']
    with pytest.raises(FileExistsError):write_candidates(**args)


@pytest.mark.parametrize('change',['body_bytes','receipt_hash','proposal_hash','missing_render','missing_group',
    'membership','role','body_union','selected_kind','ineligible_body','forms','approval'])
def test_admission_refuses_changed_or_incomplete_evidence_before_output(tmp_path,change):
    args=fixture(tmp_path)
    if change=='body_bytes':(tmp_path/'body.pdf').write_bytes(b'changed')
    elif change in {'receipt_hash','proposal_hash'}:args[change.replace('_hash','_sha256').replace('proposal_','proposals_')]='0'*64
    elif change=='missing_render':(tmp_path/'page-1.png').unlink()
    elif change in {'forms','approval'}:
        spec=json.loads(args['proposals'].read_text())
        if change=='forms':spec['records'][0]['proposed_primary_forms']=['biography']
        else:spec['records'][0]['release_approved']=True
        args['proposals'].write_text(json.dumps(spec));args['proposals_sha256']=file_digest(args['proposals'])
    else:
        path=args['sources'] if change in {'membership','ineligible_body'} else args['documents']
        table=pq.read_table(path);rows=table.to_pylist()
        if change=='missing_group':rows=[]
        elif change=='membership':rows.append(dict(rows[0],source_id='extra'))
        elif change=='role':rows[0]['record_role']=['error-response']
        elif change=='body_union':rows[0]['body_keys']=[]
        elif change=='selected_kind':rows[0]['document_kind']=['biography']
        else:rows[0]['http_status']=['404']
        pq.write_table(pa.Table.from_pylist(rows,schema=table.schema),path)
    with pytest.raises((ValueError,FileNotFoundError)):write_candidates(**args)
    assert not args['output'].exists()


def test_receipt_page_coverage_is_revalidated(tmp_path):
    args=fixture(tmp_path);path=args['receipt'];record=json.loads(path.read_text())
    record['records'][0]['rendered_pages']={};path.write_text(json.dumps(record))
    with pytest.raises(ValueError,match='coverage'):load_reviews(path,file_digest(path),{})


def test_selected_reads_keep_full_values_and_reject_duplicate_ids(tmp_path):
    path=tmp_path/'rows.parquet'
    wanted=dict(document_id='d',source_id='s',nested=[{'a':'literal','b':None}])
    table=pa.Table.from_pylist([dict(wanted,document_id='other',source_id='x'),wanted])
    pq.write_table(table,path,row_group_size=1)
    assert selected_groups(path,{'d'},'source_id')=={'s':wanted}
    pq.write_table(pa.Table.from_pylist([wanted,wanted]),path,row_group_size=1)
    with pytest.raises(ValueError,match='duplicate'):selected_groups(path,{'d'},'source_id')


@pytest.mark.parametrize('change',['partial_review','reference','approval','digest','duplicate_forms',
    'unknown_component','page_count','duplicate_record','duplicate_fetch','duplicate_ledger','parent_digest'])
def test_package_receipt_validation_rejects_invalid_coverage_and_lineage(tmp_path,change):
    args=fixture(tmp_path);path=args['receipt'];receipt=json.loads(path.read_text());record=receipt['records'][0]
    if change=='partial_review':record['all_pages_visually_reviewed']=False
    elif change=='reference':record['independent_reference']=True
    elif change=='approval':record['release_approved']=True
    elif change=='digest':record['sha256']='not-a-digest'
    elif change=='duplicate_forms':record['observed_document_forms']*=2
    elif change=='unknown_component':record['page_sections']=[dict(first_page=1,last_page=1,observed_form='tax-return')]
    elif change=='page_count':
        record['pages']=2
        fetch=Path(receipt['fetch_results_path']);rows=json.loads(fetch.read_text());rows['results'][0]['pages']=2
        fetch.write_text(json.dumps(rows));receipt['fetch_results_sha256']=file_digest(fetch)
    elif change=='duplicate_record':receipt['records'].append(deepcopy(record))
    elif change=='duplicate_fetch':
        fetch=Path(receipt['fetch_results_path']);rows=json.loads(fetch.read_text());rows['results']*=2
        fetch.write_text(json.dumps(rows));receipt['fetch_results_sha256']=file_digest(fetch)
    elif change=='duplicate_ledger':
        ledger=Path(receipt['input_ledger']);ledger.write_text(ledger.read_text()*2);receipt['input_ledger_sha256']=file_digest(ledger)
    else:receipt.update(previous_review=str(path),previous_review_sha256='0'*64)
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError):load_reviews(path,file_digest(path),{})


@pytest.mark.parametrize('change',['input','implementation'])
def test_admission_rechecks_snapshot_before_output(tmp_path,monkeypatch,change):
    from congress_api.retention import document_review_catalog as catalog
    args=fixture(tmp_path)
    if change=='input':
        original=catalog.selected_groups
        def changed(path,*rest):
            rows=original(path,*rest)
            if path==args['documents']:
                with Path(path).open('ab') as stream:stream.write(b'changed after reading')
            return rows
        monkeypatch.setattr(catalog,'selected_groups',changed)
    else:
        calls=iter([{'version':'before'},{'version':'after'}])
        monkeypatch.setattr(catalog,'implementation',lambda:next(calls))
    with pytest.raises(ValueError):write_candidates(**args)
    assert not args['output'].exists()
