"""Owner acceptance covers exact comparison groups without altering the report."""
import copy
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

FIELDS=('context_url','bytes','stored_bytes','media_type','fidelity','http_status','family','run_id','member_path','body_key','retrieved_at')
LABELS=('changed_fields','old_family','new_family','old_fidelity','new_fidelity','old_reference_kind','new_reference_kind','retrieved_at_reason','http_change_kind')
MAPPING='52120d49aa771c10105d87af6440b3d2a0b0c297aca08a0dac1c654205464d4b'
CAPTURE=dict(metadata_location='/fixture/captures/metadata/1.json',table_uuid='00000000-0000-4000-8000-000000000001',snapshot=42,schema_id=0)


def pin(path):
    from congress_api.retention.provenance import file_pin
    return dict(path=str(path.resolve()),**file_pin(path))


def write(path,value):
    path.write_text(json.dumps(value));return path


def fixture(tmp_path,group_count=97):
    evidence=tmp_path/'evidence.txt';evidence.write_text('Retained fixture witness; never an actual owner decision.')
    groups=[];rows=[]
    for i in range(group_count):
        labels=dict(changed_fields='bytes' if i==0 else 'bytes,family',old_family=None if i==0 else "f'"+str(i),new_family=None,
                    old_fidelity='saved-record',new_fidelity=None,old_reference_kind='metadata',new_reference_kind=None,retrieved_at_reason='unchanged',http_change_kind='unchanged')
        groups.append(dict(id='fixture-'+str(i),**labels,count=1,decision='accept_new',classification='old_pipeline_error',
                           reason='Explicit fixture-only decision',evidence=[pin(evidence)]))
        row={side+'_'+name:None for name in FIELDS for side in ('old','new')}
        row.update({k:v for k,v in labels.items() if k not in ('changed_fields','http_change_kind')})
        # These labels describe an unchanged fidelity, so bytes and family enter the signature.
        row.update(old_fidelity='saved-record',new_fidelity='saved-record',old_bytes=1,new_bytes=2,unexplained=True)
        groups[-1]['new_fidelity']='saved-record'
        rows.append(row)
    fields=[(side+'_'+name,pa.int64() if name in ('bytes','stored_bytes','http_status') else pa.string())
            for name in FIELDS for side in ('old','new')]
    fields += [(k,pa.string()) for k in ('old_reference_kind','new_reference_kind','retrieved_at_reason','http_change_kind')]+[('unexplained',pa.bool_())]
    changed=tmp_path/'changed-fields.parquet';pq.write_table(pa.Table.from_pylist(rows,schema=pa.schema(fields)),changed)
    report=tmp_path/'comparison-report.json';terminal=tmp_path/'comparison-status.json'
    write(report,dict(status='compared_owner_gate',mapping_digest=MAPPING,capture_pin=dict(CAPTURE),
        counts=dict(owner_gate=True,old_only=0,unexplained_new_only=0,unexplained=group_count),
        changed_fields=str(changed),outputs=[dict(name='changed-fields',sha256=pin(changed)['sha256'],size=pin(changed)['size'],rows=group_count)]))
    write(terminal,dict(status='compared_owner_gate',report=str(report),measurement=dict(returncode=0,failure=None)))
    owner=dict(version=1,mapping_digest=MAPPING,capture_pin=dict(CAPTURE),comparison_report=pin(report),
        comparison_terminal=pin(terminal),changed_fields=pin(changed),groups=groups)
    return report,terminal,changed,owner,evidence


def validate(owner,report,terminal,changed):
    from viewer_publication.archive_comparison_acceptance import validate_owner_record
    return validate_owner_record(owner,mapping_digest=MAPPING,capture_pin=CAPTURE,
        comparison_report=pin(report),comparison_terminal=pin(terminal),changed_fields=pin(changed),unexplained=97)


def test_owner_record_is_complete_exact_and_normalizes_ordered_field_array(tmp_path):
    report,terminal,changed,owner,_=fixture(tmp_path)
    owner['groups'][0]['changed_fields']=['bytes']
    result=validate(owner,report,terminal,changed)
    assert result['groups'][0]['changed_fields']=='bytes'
    assert owner['groups'][0]['changed_fields']==['bytes']


@pytest.mark.parametrize('case',[
    'missing_group','overlap','duplicate_id','wrong_count','bad_mapping','bad_capture','bad_report_pin',
    'bad_terminal_pin','bad_changed_pin','bad_evidence','blocked','bad_decision','bad_classification',
    'missing_null','missing_reason','empty_evidence','wrong_order','unknown_field','boolean_count','missing_http_kind','invalid_http_kind','false_defect_tag','wrong_defect_mapping'])
def test_owner_record_refuses_incomplete_or_unbound_decisions(tmp_path,case):
    report,terminal,changed,owner,_=fixture(tmp_path);g=owner['groups'][0]
    if case=='missing_group':owner['groups'].pop()
    elif case=='overlap':owner['groups'][1].update({k:g[k] for k in LABELS})
    elif case=='duplicate_id':owner['groups'][1]['id']=g['id']
    elif case=='wrong_count':g['count']=2
    elif case=='bad_mapping':owner['mapping_digest']='b'*64
    elif case=='bad_capture':owner['capture_pin']['snapshot']=43
    elif case=='bad_report_pin':owner['comparison_report']['sha256']='b'*64
    elif case=='bad_terminal_pin':owner['comparison_terminal']['sha256']='b'*64
    elif case=='bad_changed_pin':owner['changed_fields']['sha256']='b'*64
    elif case=='bad_evidence':g['evidence'][0]['sha256']='b'*64
    elif case=='blocked':g['decision']='blocked'
    elif case=='bad_decision':g['decision']='accept_all'
    elif case=='bad_classification':g['classification']='renamed_outcome'
    elif case=='missing_null':del g['new_reference_kind']
    elif case=='missing_reason':g['reason']=' '
    elif case=='empty_evidence':g['evidence']=[]
    elif case=='wrong_order':g['changed_fields']=['retrieved_at','bytes']
    elif case=='unknown_field':g['predicate']='TRUE'
    elif case=='boolean_count':g['count']=True
    elif case=='missing_http_kind':
        for group in owner['groups']:del group['http_change_kind']
    elif case=='invalid_http_kind':g['http_change_kind']='loss_or_change'
    elif case=='false_defect_tag':g['classification']='known_defect_mapping_52120d49_http_alias'
    elif case=='wrong_defect_mapping':
        g['classification']='known_defect_mapping_52120d49_http_alias';g['http_change_kind']='value_to_null';owner['mapping_digest']='b'*64
    with pytest.raises(ValueError):validate(owner,report,terminal,changed)


@pytest.mark.parametrize('case',['mapping','capture','terminal','changed','old_only','new_only','owner_required'])
def test_comparison_binding_refuses_before_native_or_work_allocation(tmp_path,case):
    from viewer_publication.archive_comparison_acceptance import accept_comparison
    report,terminal,changed,owner,_=fixture(tmp_path);r=json.loads(report.read_text())
    kwargs=dict(expected_mapping_digest=MAPPING,capture_pin=CAPTURE,work=tmp_path/'work',engine=None)
    if case=='mapping':kwargs['expected_mapping_digest']='b'*64
    elif case=='capture':kwargs['capture_pin']=dict(CAPTURE,snapshot=43)
    elif case=='terminal':write(terminal,dict(status='running',report=str(report)))
    elif case=='changed':changed.write_bytes(b'stale')
    elif case=='old_only':r['counts']['old_only']=1;write(report,r)
    elif case=='new_only':r['counts']['unexplained_new_only']=1;write(report,r)
    with pytest.raises(ValueError):accept_comparison(report,**kwargs)
    assert not (tmp_path/'work').exists()


def test_no_owner_gate_needs_no_native_and_retains_original_report(tmp_path):
    from viewer_publication.archive_comparison_acceptance import accept_comparison,validate_receipt
    report,terminal,changed,_,_=fixture(tmp_path);r=json.loads(report.read_text())
    r['status']='compared';r['counts'].update(owner_gate=False,unexplained=0)
    pq.write_table(pq.read_table(changed).slice(0,0),changed)
    r['outputs'][0].update(sha256=pin(changed)['sha256'],size=pin(changed)['size'],rows=0);write(report,r)
    write(terminal,dict(status='compared',report=str(report),measurement=dict(returncode=0,failure=None)))
    receipt=accept_comparison(report,expected_mapping_digest=MAPPING,capture_pin=CAPTURE,work=tmp_path/'work',engine=None)
    assert receipt['status']=='accepted_without_owner_dispositions'
    assert json.loads(report.read_text())['counts']['owner_gate'] is False
    assert validate_receipt(pin(tmp_path/'work/acceptance.json'),expected_mapping_digest=MAPPING,capture_pin=CAPTURE)==receipt
    changed.write_bytes(b'replaced after receipt')
    with pytest.raises(ValueError):validate_receipt(pin(tmp_path/'work/acceptance.json'),expected_mapping_digest=MAPPING,capture_pin=CAPTURE)



def http_fixture(tmp_path):
    report,terminal,changed,owner,evidence=fixture(tmp_path,group_count=2)
    rows=pq.read_table(changed).to_pylist()
    shared={name:owner['groups'][0][name] for name in LABELS if name!='http_change_kind'}
    shared['changed_fields']='http_status'
    for i,(group,row) in enumerate(zip(owner['groups'],rows)):
        group.update(shared,http_change_kind='value_to_null' if i==0 else 'value_changed')
        if i==0:group['classification']='known_defect_mapping_52120d49_http_alias'
        for side in ('old','new'):
            for name in FIELDS:row[side+'_'+name]=None
        row.update(old_fidelity='saved-record',new_fidelity='saved-record',old_http_status=200,new_http_status=None if i==0 else 403,http_change_kind='unchanged')
    pq.write_table(pa.Table.from_pylist(rows,schema=pq.read_schema(changed)),changed)
    r=json.loads(report.read_text());r['outputs'][0].update(sha256=pin(changed)['sha256'],size=pin(changed)['size']);write(report,r)
    owner['changed_fields']=pin(changed);owner['comparison_report']=pin(report)
    assert all(owner['groups'][0][key]==owner['groups'][1][key] for key in LABELS if key!='http_change_kind')
    return report,terminal,changed,owner,evidence


def test_legacy_eight_key_combined_http_bucket_refuses_before_native(tmp_path):
    from viewer_publication.archive_comparison_acceptance import validate_owner_record
    report,terminal,changed,owner,_=http_fixture(tmp_path)
    owner['groups']=[dict(owner['groups'][0],count=2)]
    del owner['groups'][0]['http_change_kind']
    owner['groups'][0]['classification']='old_pipeline_error'
    with pytest.raises(ValueError):
        validate_owner_record(owner,mapping_digest=MAPPING,capture_pin=CAPTURE,comparison_report=pin(report),
            comparison_terminal=pin(terminal),changed_fields=pin(changed),unexplained=2)
    assert not (tmp_path/'never-created').exists()


def test_native_exact_null_safe_coverage_and_receipt_rechecks_evidence(tmp_path):
    from docspec_client.client import NativeDatasets
    from viewer_publication.archive_comparison_acceptance import accept_comparison,validate_receipt
    report,terminal,changed,owner,evidence=http_fixture(tmp_path)
    owner_path=write(tmp_path/'owner.json',owner)
    before=changed.stat()
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        receipt=accept_comparison(report,expected_mapping_digest=MAPPING,capture_pin=CAPTURE,work=tmp_path/'work',
            engine=engine,owner_record=pin(owner_path))
    after=changed.stat()
    assert (before.st_ino,before.st_nlink,before.st_ctime_ns)==(after.st_ino,after.st_nlink,after.st_ctime_ns)
    assert receipt['status']=='accepted_with_owner_dispositions'
    assert receipt['counts']==dict(actual_groups=2,owner_groups=2,unexplained=2,mismatches=0)
    assert json.loads(report.read_text())['counts']['owner_gate'] is True
    selected=pin(tmp_path/'work/acceptance.json')
    assert validate_receipt(selected,expected_mapping_digest=MAPPING,capture_pin=CAPTURE)==receipt
    staged=Path(receipt['owner_groups_input']['path']);original=staged.read_bytes();staged.write_bytes(b'changed staged owner predicates')
    with pytest.raises(ValueError):validate_receipt(selected,expected_mapping_digest=MAPPING,capture_pin=CAPTURE)
    staged.write_bytes(original)
    evidence.write_text('changed witness')
    with pytest.raises(ValueError):validate_receipt(selected,expected_mapping_digest=MAPPING,capture_pin=CAPTURE)


def test_coverage_summary_refuses_missing_extra_or_incorrect_native_groups():
    from viewer_publication.archive_comparison_acceptance import validate_coverage
    for bad in [dict(actual_groups=96,owner_groups=97,unexplained=97,mismatches=1),
                dict(actual_groups=98,owner_groups=97,unexplained=98,mismatches=1),
                dict(actual_groups=97,owner_groups=97,unexplained=97,mismatches=2),
                dict(actual_groups=97,owner_groups=97,unexplained=98,mismatches=0)]:
        with pytest.raises(ValueError):validate_coverage(bad,unexplained=97)


@pytest.mark.parametrize('classification',[
    'known_defect_mapping_52120d49_http_alias',
    'known_defect_mapping_52120d49_inline_payload_outcome'])
def test_known_defect_classifications_remain_explicit_mapping_bound_decisions(tmp_path,classification):
    from viewer_publication.archive_comparison_acceptance import validate_owner_record
    report,terminal,changed,owner,_=fixture(tmp_path)
    group=owner['groups'][0];group['classification']=classification
    if classification.endswith('http_alias'):group['http_change_kind']='value_to_null'
    assert validate(owner,report,terminal,changed)['groups'][0]['classification']==classification
    owner['mapping_digest']='b'*64
    with pytest.raises(ValueError):
        validate_owner_record(owner,mapping_digest='b'*64,capture_pin=CAPTURE,comparison_report=pin(report),
            comparison_terminal=pin(terminal),changed_fields=pin(changed),unexplained=97)


def test_known_defect_wildcard_is_not_an_approval_classification(tmp_path):
    report,terminal,changed,owner,_=fixture(tmp_path)
    owner['groups'][0]['classification']='known_defect_mapping_52120d49_anything'
    with pytest.raises(ValueError):validate(owner,report,terminal,changed)
