"""Expected oracle changes require specific receipt-derived scalar witnesses."""
import os
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from docspec_client.client import NativeDatasets
from congress_api.lake.capture_comparison import compare_old

WITNESSES=dict(source_context_from_final=pa.bool_(),source_retained_record=pa.bool_(),
    source_entry_status=pa.int64(),source_final_status=pa.int64(),
    source_creating_size_absent=pa.bool_(),source_family_basis=pa.string())


def pair(tmp_path,old_change,new_change,proof):
    old=dict(receipt_key='receipts/documents/2026-10-02/run.jsonl.gz',receipt_line=1,
        reference_kind='capture',pointer_json='["prior_attempts",0,"body"]',sha256='a'*64,
        context_url='https://example.org/final',bytes=10,stored_bytes=8,media_type='text/plain',
        fidelity='exact-bytes',http_status=200,retrieved_at=None,family='documents',source_file='run',resolution=None)
    old.update(old_change)
    new={k:v for k,v in old.items() if k not in {'source_file','resolution'}}
    new.update(sha256=bytes.fromhex(old['sha256']) if old['sha256'] is not None else None,
        capture_index=0,run_id=old['source_file'])
    new.update(new_change)
    new.update({name:None for name in WITNESSES});new.update(proof)
    ints={'receipt_line','capture_index','bytes','stored_bytes','http_status'}
    def schema(row,body):
        return pa.schema([(name,WITNESSES[name] if name in WITNESSES else
            pa.binary(32) if name=='sha256' and body else pa.int64() if name in ints else pa.string()) for name in row])
    op=tmp_path/'old.parquet';np=tmp_path/'new.parquet'
    pq.write_table(pa.Table.from_pylist([old],schema=schema(old,False)),op)
    pq.write_table(pa.Table.from_pylist([new],schema=schema(new,True)),np)
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as native:
        result=compare_old(np,op,engine=native,work=tmp_path/'compare')
    return result,pq.read_table(tmp_path/'compare/changed-fields.parquet').to_pylist()


CASES=[
    ('retained-fidelity',dict(reference_kind='metadata',sha256=None,pointer_json='[]',bytes=None,stored_bytes=None,
        media_type=None,fidelity='saved-record'),dict(reference_kind='line',pointer_json=None,fidelity=None),
        dict(source_retained_record=True),'source_retained_record',False),
    ('final-context',dict(context_url=None),dict(context_url='https://example.org/final'),
        dict(source_context_from_final=True),'source_context_from_final',False),
    ('final-status',dict(http_status=403),dict(http_status=404),
        dict(source_entry_status=403,source_final_status=404),'source_entry_status',402),
    ('resolver-size',dict(stored_bytes=273,resolution='digest_verified'),dict(stored_bytes=None),
        dict(source_creating_size_absent=True),'source_creating_size_absent',False),
    ('mods-receipt-family',dict(receipt_key='receipts/govinfo/transcript-html/undated/run.gz',family='govinfo/mods'),
        dict(family='govinfo/transcript-html'),dict(source_family_basis='receipt'),'source_family_basis','record'),
    ('transcript-receipt-family',dict(receipt_key='receipts/govinfo/mods/undated/run.gz',family='govinfo/transcript-html'),
        dict(family='govinfo/mods'),dict(source_family_basis='receipt'),'source_family_basis','entry'),
    ('witness-receipt-family',dict(receipt_key='receipts/house/meeting-xml/undated/run.gz',family='house/witness-xml'),
        dict(family='house/meeting-xml'),dict(source_family_basis='receipt'),'source_family_basis',None),
    ('players-receipt-family',dict(receipt_key='receipts/senate/captions/undated/run.gz',family='senate/players'),
        dict(family='senate/captions'),dict(source_family_basis='receipt'),'source_family_basis','line'),
    ('report-record-family',dict(family='documents'),dict(family='committee-reports'),
        dict(source_family_basis='record'),'source_family_basis','receipt'),
]


@pytest.mark.parametrize('name,old,new,proof,field,bad',CASES,ids=[c[0] for c in CASES])
@pytest.mark.parametrize('valid',[True,False],ids=['source-proof','negative-control'])
def test_expected_difference_requires_its_own_receipt_witness(tmp_path,name,old,new,proof,field,bad,valid):
    if not valid:proof={**proof,field:bad}
    report,changed=pair(tmp_path,old,new,proof)
    assert report['matched']==1 and report['old_only']==report['new_only']==0
    assert report['expected_changes']==int(valid)
    assert report['unexplained']==int(not valid) and report['owner_gate'] is (not valid)
    assert len(changed)==1


@pytest.mark.parametrize('old,new,proof',[
    (dict(fidelity='saved-text'),dict(fidelity=None),dict(source_retained_record=True)),
    (dict(stored_bytes=273,resolution='unverified'),dict(stored_bytes=None),dict(source_creating_size_absent=True)),
    (dict(http_status=403),dict(http_status=404),dict(source_entry_status=403,source_final_status=500)),
    (dict(family='other'),dict(family='committee-reports'),dict(source_family_basis='record')),
    (dict(receipt_key='receipts/documents/undated/run.gz',family='govinfo/mods'),
        dict(family='govinfo/transcript-html'),dict(source_family_basis='receipt')),
])
def test_receipt_witness_never_generalizes_the_approved_transformation(tmp_path,old,new,proof):
    report,_=pair(tmp_path,old,new,proof)
    assert report['unexplained']==1 and report['owner_gate'] is True and report['expected_changes']==0
