from copy import deepcopy
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from current_review_candidates import extract_groups, compact_rows, select_candidates, run
from catalog_review_evidence import row_digest
from pilot_reconcile import file_digest
from test_review_catalog_reconcile import current_case
from test_catalog_content_review import fixture as review_fixture


def test_full_extraction_preserves_nested_nulls_order_duplicates_and_schema(tmp_path):
    schema = pa.schema([('document_id',pa.string()),('source_id',pa.string()),
        ('source_occurrences',pa.list_(pa.struct([('text',pa.string()),('missing',pa.string())])))],
        metadata={b'catalog_id':b'catalog',b'custom':b'keep'})
    duplicate = dict(text='Literal source text',missing=None)
    selected = dict(document_id='wanted',source_id='chosen',source_occurrences=[duplicate,duplicate])
    control = dict(document_id='control',source_id='control',source_occurrences=[dict(text='other')])
    path,target = tmp_path/'source.parquet',tmp_path/'selected.parquet'
    pq.write_table(pa.Table.from_pylist([control,selected,dict(control,source_id='second')],schema=schema),path,row_group_size=1)
    result = extract_groups(path,target,{'wanted'},'source_id',batch_size=1)
    assert result['rows']==result['selected_row_groups']==1 and result['total_row_groups']==3
    assert pq.read_table(target).to_pylist()==[selected]
    assert pq.read_schema(target).equals(pq.read_schema(path),check_metadata=True)
    assert compact_rows(target,'source_id')['chosen']['source_occurrences']==[{'text':'Literal source text'}]*2
    with pytest.raises(FileExistsError):extract_groups(path,target,{'wanted'},'source_id')


def test_extraction_duplicate_identity_is_rejected(tmp_path):
    path,target=tmp_path/'source.parquet',tmp_path/'selected.parquet'
    pq.write_table(pa.Table.from_pylist([dict(document_id='d',source_id='s')]*2),path)
    with pytest.raises(ValueError,match='duplicate'):extract_groups(path,target,{'d'},'source_id',batch_size=1)


@pytest.mark.parametrize('change',[None,'source','body','role','missing_review','union'])
def test_current_candidate_checks_complete_membership_and_preserves_baseline(change):
    p,o,d,m,s,r=current_case()
    if change=='source':m[0]['filename']='replacement.pdf'
    elif change=='body':m[0]['body_key']='replacement'
    elif change=='role':d['record_role']=['error-response']
    elif change=='union':d['body_keys']=[]
    args=({p['document_id']:p},{o['document_id']:o},{d['document_id']:d},s,
          {} if change=='missing_review' else {p['document_id']:r})
    before=deepcopy(args)
    if change:
        with pytest.raises(ValueError):select_candidates(*args)
    else:
        result=select_candidates(*args)['document']
        assert result['status']=='candidate_applied'
        assert result['document']['document_kind']==['committee-vote']
        assert result['review']['original_row_sha256']==row_digest(o)
    assert args==before


@pytest.mark.parametrize('mode',['historical','new','changed_catalog'])
def test_current_selection_bound_integration(tmp_path,mode):
    original,receipt,receipt_path,save,ledger=review_fixture(tmp_path)
    # A single-form review permits the new-case path to derive its simple proposal.
    observed=receipt['records'][0];observed['observed_document_forms']=['opening-statement']
    for section in observed['page_sections']:section['observed_form']='opening-statement'
    save()
    proposal=dict(document_id='d',source_row_sha256=row_digest(original),
        proposed_primary_forms=['opening-statement'],proposed_component_forms=[],status='assistant_proposal',
        handling='body_form',independent_reference=False,release_approved=False,
        evidence=dict(receipt=str(receipt_path),receipt_sha256=file_digest(receipt_path),
                      **{k:observed[k] for k in ['body_key','sha256','pages']}))
    spec=tmp_path/'content_disposition_proposals_v1.json'
    spec.write_text(json.dumps(dict(records=[proposal],original_ledger=str(ledger),original_ledger_sha256=file_digest(ledger))))
    root=tmp_path/'catalog';generation='a'*32;directory=root/'catalog-generations'/generation;directory.mkdir(parents=True)
    source=dict(original['members'][0],record_role=['document'],document_kind=original['after_kind'])
    document=dict(source,body_keys=[source['body_key']])
    files={};bindings={str(spec):file_digest(spec),str(ledger):file_digest(ledger)}
    for label,name,row in [('filenames','document-filenames.parquet',source),('documents','documents.parquet',document)]:
        path=directory/name
        table=pa.Table.from_pylist([row]).replace_schema_metadata({b'catalog_id':b'fresh'})
        pq.write_table(table,path);bindings[str(path)]=file_digest(path)
        files[label]=dict(key=str(path.relative_to(root)),sha256=file_digest(path),bytes=path.stat().st_size,rows=1)
    (root/'indexes').mkdir();manifest=root/'indexes/catalog.json'
    manifest.write_text(json.dumps(dict(version=1,catalog_id='fresh',generation=generation,files=files)))
    bindings[str(manifest)]=file_digest(manifest)
    reconciliation=tmp_path/'reconciliation.jsonl'
    reconciliation.write_text('' if mode=='new' else json.dumps(dict(document_id='d',matching_body_and_source_identity=True))+'\n')
    summary=tmp_path/'summary.json';summary.write_text(json.dumps(dict(bindings=bindings,outputs={'reconciliation.jsonl':file_digest(reconciliation)})))
    cp=tmp_path/'checkpoint.json';cp.write_text(json.dumps(dict(summary_path=str(summary),summary_sha256=file_digest(summary))))
    selected_receipt=receipt_path
    if mode!='new':
        empty=tmp_path/'empty.jsonl';empty.write_text('')
        fetched=tmp_path/'empty-fetch.json';fetched.write_text('{"results":[]}')
        selected_receipt=tmp_path/'latest.json'
        selected_receipt.write_text(json.dumps(dict(previous_review=str(receipt_path),previous_review_sha256=file_digest(receipt_path),
            input_ledger=str(empty),input_ledger_sha256=file_digest(empty),fetch_results_path=str(fetched),
            fetch_results_sha256=file_digest(fetched),records=[],independent_reference=False,release_approved=False)))
    palmer=tmp_path/'palmer.json';palmer.write_text(json.dumps(dict(receipt_path=str(selected_receipt),receipt_sha256=file_digest(selected_receipt))))
    output=tmp_path/'output'
    if mode=='changed_catalog':
        with (directory/'documents.parquet').open('ab') as stream:stream.write(b'changed')
        with pytest.raises(ValueError):run(cp,palmer,root,output)
        assert not output.exists()
    else:
        result=run(cp,palmer,root,output)
        assert result['current_groups']==result['source_rows']==result['changed_kind_sets']==1
        assert result['case_status']=={'candidate_applied':1}
        assert result['baseline_preserved'] and result['withdrawal_restores_baseline']
        assert not result['production_selected']
        for name,digest in result['outputs'].items():assert file_digest(output/name)==digest
