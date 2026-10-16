from copy import deepcopy
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from catalog_content_review import load_reviews
from catalog_review_evidence import row_digest
from current_review_candidates import select_candidates
from normalized_review_candidates import validate_transition, run
from pilot_reconcile import file_digest
from test_catalog_content_review import fixture


def transition():
    sources=[dict(source_id='a',document_id='d',document_kind=['amendment'],document_kind_source=['filename']),
             dict(source_id='b',document_id='d',document_kind=['letter'],document_kind_source=['content'])]
    docs=[dict(document_id='d',document_kind=['amendment'],document_kind_source=['filename'])]
    current=deepcopy(sources);current[0]['filename_document_kind']=['amendment']
    return sources,docs,current,[dict(docs[0],filename_document_kind=['amendment'])]


def test_only_restored_filename_claims_change_and_inputs_survive():
    args=transition();before=deepcopy(args)
    result=validate_transition(*args)
    assert args==before
    assert set(result['source_changes']['fields'])=={'a'}
    assert set(result['document_changes']['fields'])=={'d'}


@pytest.mark.parametrize('change',['body','membership','text','kind','provenance','claim','content_claim','group_union'])
def test_other_changes_refuse_normalization(change):
    a,b,s,d=transition()
    if change=='membership':s.pop()
    elif change=='group_union':d[0]['filename_document_kind']=['letter']
    elif change=='content_claim':s[1]['filename_document_kind']=['letter']
    else:
        field={'body':'body_key','text':'source_occurrences','kind':'document_kind',
               'provenance':'document_kind_source','claim':'filename_document_kind'}[change]
        s[0][field]=['changed']
    with pytest.raises(ValueError,match='restoration'):validate_transition(a,b,s,d)


def write_pair(directory,sources,documents):
    directory.mkdir(parents=True)
    for name,rows in [('document-filenames.parquet',sources),('documents.parquet',documents)]:
        pq.write_table(pa.Table.from_pylist(rows).replace_schema_metadata({b'catalog_id':b'fixture'}),directory/name)


def checkpoint(directory,bindings):
    summary=directory/'summary.json'
    summary.write_text(json.dumps(dict(bindings=bindings,outputs={str(p.relative_to(directory)):file_digest(p)
        for p in directory.rglob('*') if p.is_file()})))
    cp=directory/'checkpoint.json';cp.write_text(json.dumps(dict(summary_path=str(summary),summary_sha256=file_digest(summary))))
    return cp


@pytest.mark.parametrize('tamper',[None,'pdf','normalized','outside_receipt','unbound_input'])
def test_real_receipt_and_parquet_rebinding_preserve_review_content(tmp_path,tamper):
    original,receipt,receipt_path,save,ledger=fixture(tmp_path)
    review=load_reviews(receipt_path,save(),{})
    p=dict(document_id='d',source_row_sha256=row_digest(original),proposed_primary_forms=['testimony-disclosure'],
        proposed_component_forms=['biography'],status='assistant_proposal',handling='body_form',
        independent_reference=False,release_approved=False,evidence=dict(receipt=str(receipt_path),
        receipt_sha256=file_digest(receipt_path),**{k:receipt['records'][0][k] for k in ['body_key','sha256','pages']}))
    source=dict(original['members'][0],filename_document_kind=None,document_kind=['testimony-disclosure'],
        document_kind_source=['filename'],record_role=['document'])
    doc=dict(source,document_kind=original['after_kind'],body_keys=[source['body_key']])
    old=select_candidates({'d':p},{'d':original},{'d':doc},{'s':source},review)['d']
    current=tmp_path/'current';write_pair(current,[source],[doc])
    (current/'candidates.jsonl').write_text(json.dumps(old)+'\n')
    (current/'proposals.json').write_text(json.dumps(dict(records=[p])))
    receipt_cp=tmp_path/'receipt-checkpoint.json'
    receipt_cp.write_text(json.dumps(dict(receipt_path=str(receipt_path),receipt_sha256=file_digest(receipt_path))))
    current_cp=checkpoint(current,{str(receipt_cp):file_digest(receipt_cp)})
    replay=tmp_path/'replay'
    ns=dict(source,filename_document_kind=['testimony-disclosure'])
    nd=dict(doc,filename_document_kind=['testimony-disclosure'])
    write_pair(replay/'disk',[ns],[nd])
    if tamper=='normalized':
        ns['source_occurrences']=[{'literal':['new']}]
        pq.write_table(pa.Table.from_pylist([ns]).replace_schema_metadata({b'catalog_id':b'fixture'}),replay/'disk/document-filenames.parquet')
    replay_cp=checkpoint(replay,{str(current_cp):file_digest(current_cp)})
    if tamper=='pdf':(tmp_path/'saved.pdf').write_bytes(b'changed')
    if tamper=='outside_receipt':
        receipt_cp=tmp_path/'other-checkpoint.json';receipt_cp.write_text('{}')
    if tamper=='unbound_input':
        summary=replay/'summary.json';r=json.loads(summary.read_text());r['outputs'].pop('disk/documents.parquet')
        summary.write_text(json.dumps(r));replay_cp.write_text(json.dumps(dict(summary_path=str(summary),summary_sha256=file_digest(summary))))
    output=tmp_path/'output'
    if tamper:
        with pytest.raises(ValueError):run(current_cp,replay_cp,receipt_cp,output)
        assert not output.exists()
    else:
        result=run(current_cp,replay_cp,receipt_cp,output)
        assert result['changed_bindings']==1 and result['case_status']=={'candidate_applied':1}
        fresh=json.loads((output/'candidates.jsonl').read_text())
        assert fresh['review']['receipt_sha256']==old['review']['receipt_sha256']
        assert fresh['document']['document_kind']==old['document']['document_kind']
        assert fresh['document']['filename_document_kind']==['testimony-disclosure']
        assert fresh['review']['group_sha256']!=old['review']['group_sha256']
        assert (output/'documents.parquet').read_bytes()==(replay/'disk/documents.parquet').read_bytes()
        assert json.loads((current/'candidates.jsonl').read_text())==old
        with pytest.raises(FileExistsError):run(current_cp,replay_cp,receipt_cp,output)
