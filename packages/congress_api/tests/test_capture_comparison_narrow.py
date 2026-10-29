"""The pinned old index checks only fields its source actually records."""
import json
import os
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from docspec_client.client import NativeDatasets
from congress_api.lake.capture_comparison import compare_old

SHA='a'*64
BODY='bodies/sha256/aa/'+SHA


def compare(tmp_path,old_changes=None,new_changes=None,*,secondary=None):
    common=dict(receipt_key='receipts/documents/2026-10-20/r.gz',receipt_line=1,
        context_url='https://example.org/a',bytes=100,stored_bytes=42,
        media_type='application/pdf',fidelity='exact-bytes',http_status=200,
        retrieved_at='2026-10-20T00:00:00Z',pointer_json='["body"]',family='documents')
    old=dict(common,sha256=SHA,body_key=BODY+'.gz',source_file='ci/run',
        reference_kind='capture',original_path=None,resolution='saved',**{})
    new=dict(common,sha256=bytes.fromhex(SHA),capture_index=0,stored_suffix='.gz',
        run_id='ci/run',reference_kind='capture',member_path=None)
    old.update(old_changes or {});new.update(new_changes or {})
    for name,row in [('old',old),('new',new)]:
        types={k:pa.int64() if k in {'receipt_line','capture_index','bytes','stored_bytes','http_status'}
            else pa.bool_() if k=='source_context_from_final'
            else pa.binary(32) if k=='sha256' and name=='new' else pa.string() for k in row}
        rows=[row]
        if name=='old' and secondary is not None:
            rows.append(dict(row,reference_kind='file',pointer_json='["old-file"]',**secondary))
        pq.write_table(pa.Table.from_pylist(rows,schema=pa.schema(types.items())),tmp_path/(name+'.parquet'))
    report=compare_old(tmp_path/'new.parquet',tmp_path/'old.parquet',
        engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),work=tmp_path/'comparison')
    return report,pq.read_table(tmp_path/'comparison/changed-fields.parquet').to_pylist()


@pytest.mark.parametrize('old_change,new_change,field',[
    ({'family':'old-family'},{},'family'),
    ({'source_file':'old-run'},{},'run_id'),
    ({},{'stored_suffix':''},'body_key'),
    ({'body_key':'bodies/not-a-content-address'},{},'body_key'),
    ({'body_key':'bodies/sha256/bb/'+'b'*64+'.gz'},{},'body_key'),
])
def test_nonnull_oracle_facts_never_disappear_behind_normalization(tmp_path,old_change,new_change,field):
    report,rows=compare(tmp_path,old_change,new_change)
    assert report['matched']==1 and report['old_only']==report['new_only']==0
    assert report['unexplained']==1 and report['owner_gate'] is True
    [row]=rows
    assert row['old_'+field]!=row['new_'+field]


def test_missing_family_and_run_are_explicit_restorations_without_prefix_rewrite(tmp_path):
    report,rows=compare(tmp_path,{'family':None,'source_file':None})
    assert report['unexplained']==0 and report['expected_changes']==1
    [row]=rows
    assert row['new_run_id']=='ci/run' and row['new_family']=='documents'


@pytest.mark.parametrize('pointer,kind,old_path,new_path,unexplained',[
    ('["archive_members",0,"content","body"]','capture','inside/A.pdf','inside/B.pdf',1),
    ('["not_archive_members",0,"body"]','capture','local/A.pdf',None,0),
    ('["archive_members_suffix",0,"body"]','capture','local/A.pdf',None,0),
    (json.dumps(['prefix"archive_members',0,'body']),'capture','local/A.pdf',None,0),
    ('["content","body"]','capture','local/A.pdf',None,0),
    ('["body"]','file','/local/retained/A.pdf',None,0),
])
def test_member_names_require_the_proved_archive_pointer_component(
        tmp_path,pointer,kind,old_path,new_path,unexplained):
    report,_=compare(tmp_path,{'pointer_json':pointer,'reference_kind':kind,'original_path':old_path},
        {'pointer_json':pointer,'member_path':new_path})
    assert report['unexplained']==unexplained
    assert report['matched']==1


def test_only_proved_bodiless_metadata_empty_pointer_maps_to_null(tmp_path):
    report,_=compare(tmp_path,{'sha256':None,'body_key':None,'reference_kind':'metadata',
        'pointer_json':'[]','context_url':None},
        {'sha256':None,'reference_kind':'line','pointer_json':None,'context_url':'https://example.org/a',
         'source_context_from_final':True})
    assert report['matched']==1 and report['old_only']==report['new_only']==0
    assert report['unexplained']==0 and report['expected_changes']==1


@pytest.mark.parametrize('kind',['capture','file','unrecognized'])
def test_other_pointer_shapes_remain_owner_gates(tmp_path,kind):
    report,_=compare(tmp_path,{'sha256':None,'body_key':None,'reference_kind':kind,'pointer_json':'[]'},
        {'sha256':None,'reference_kind':'line','pointer_json':None})
    assert report['old_only']==report['new_only']==1 and report['owner_gate'] is True


def test_report_names_the_oracle_coverage_gaps(tmp_path):
    report,_=compare(tmp_path)
    assert report['owner_gate'] is False
    assert {'family','run_id','member_path','body_key'}<=set(report['coverage']['compared'])
    assert {'mode','complete','outcome','requested_url','url','h_content_disposition','stored_md5',
        'sniffed_format','sniff_version','intact','expansion','writer_job','writer_commit',
        'recovery_category','original_url','recovered_url','match_basis','evidence_sha256','imported_at'}<=set(report['coverage']['not_compared'])
    assert 'resolution' in report['coverage']['unqualified_old_fields']


@pytest.mark.parametrize('kind',['metadata',None])
def test_missing_bodiless_pointer_proof_cannot_hide_a_changed_context(tmp_path,kind):
    report,rows=compare(tmp_path,{'sha256':None,'body_key':None,'reference_kind':kind,
        'pointer_json':None,'context_url':None},
        {'sha256':None,'reference_kind':'line','pointer_json':None})
    assert report['matched']==1 and report['unexplained']==1 and report['owner_gate'] is True
    [row]=rows
    assert row['unexplained'] is True
    assert row['old_context_url'] is None and row['new_context_url']=='https://example.org/a'


@pytest.mark.parametrize('secondary,new_size,new_suffix,discarded',[
    ({'stored_bytes':42,'body_key':BODY+'.gz','fidelity':'retained-file'},42,'.gz',1),
    ({'stored_bytes':None,'body_key':None,'fidelity':'retained-file'},43,'',1),
    ({'stored_bytes':42},43,'.gz',0),
    ({'body_key':'bodies/not-a-content-address'},42,'.gz',0),
    ({'body_key':BODY+'.gz'},42,'',0),
    ({'stored_bytes':42},None,'.gz',0),
])
def test_secondary_storage_evidence_must_agree_with_the_retained_target(
        tmp_path,secondary,new_size,new_suffix,discarded):
    report,_=compare(tmp_path,{'stored_bytes':None,'body_key':None},
        {'stored_bytes':new_size,'stored_suffix':new_suffix},secondary=secondary)
    assert report['secondary_duplicates']==discarded
    assert report['old_only']==1-discarded and report['new_only']==0
    assert report['owner_gate'] is not bool(discarded)
    old_only=pq.read_table(tmp_path/'comparison/old-only.parquet').to_pylist()
    if not discarded:
        [row]=old_only
        assert row['reference_kind']=='file' and row['pointer_json']=='["old-file"]'
        assert all(row[name]==value for name,value in secondary.items())
