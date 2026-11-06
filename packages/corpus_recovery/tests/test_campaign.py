"""Campaign proof uses native metadata joins, actual qualification and raw writers."""
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from docspec_client.client import NativeDatasets
from congress_api.models.raw_fetch import BodyFile,FetchAttempt,FetchResult
from congress_api.retention.body_store import BodyStore,LocalAdapter
from congress_api.retention.receipt_writer import ReceiptWriter
from congress_api.retention.provenance import file_pin
from corpus_recovery.campaign import plan,import_candidate

STAMP='2026-10-31T12:00:00Z'
TARGET='https://docs.house.gov/missing.html'
CANDIDATE='https://docs.house.gov/retained.html'
IDENTITY=dict(job='campaign-test',commit='a'*40,lockfile_digest='b'*64)


def pinned(path):return dict(path=str(path.resolve()),sha256=file_pin(path)['sha256'])

def engine():return NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])


def inputs(tmp_path, *, requirement='historical_exact', extra_targets=()):
    targets=tmp_path/'targets.parquet';candidates=tmp_path/'candidates.parquet'
    pq.write_table(pa.Table.from_pylist([dict(target_url=TARGET),*[dict(target_url=u) for u in extra_targets]]),targets)
    pq.write_table(pa.Table.from_pylist([dict(target_url=TARGET,candidate_url=CANDIDATE)]),candidates)
    descriptor=tmp_path/'campaign.json'
    descriptor.write_text(json.dumps(dict(version=1,campaign_id='local-proof',requirement=requirement,
        tables=dict(targets=pinned(targets),candidates=pinned(candidates)),target_table='targets',candidate_table='candidates')))
    return descriptor


def candidate_request(tmp_path, *, target_changes=None,candidate_changes=None,relationship='recovered_document'):
    raw=tmp_path/'raw';store=BodyStore(LocalAdapter(raw))
    writer=ReceiptWriter(store,identity=IDENTITY,run_id='campaign-test',write_date='2026-10-31',archive_limits=None)
    body=tmp_path/'body.html';body.write_text('<html><title>Testimony</title><div class="field-name-body">'+'substantive testimony '*70+'</div></html>')
    digest=file_pin(body)['sha256']
    attempt=FetchAttempt(CANDIDATE,CANDIDATE,'2020-01-01T00:00:00Z','direct',200,None,{},(),True,
        BodyFile(body,digest,body.stat().st_size,'text/html',None,None,None))
    key,_=writer.write(FetchResult(attempt),family='documents',mode='fetch')
    specs={}
    for side,url,changes in [('target',TARGET,target_changes),('candidate',CANDIDATE,candidate_changes)]:
        fields=dict(meeting='H-123',document='D-7',version='ih',date='2020-01-01',title='Testimony',witness='Person')
        fields.update(changes or {})
        path=tmp_path/(side+'.json');path.write_text(json.dumps(dict(url=url,**fields)))
        specs[side]=dict(source=pinned(path),source_url='https://docs.house.gov/meeting/123.json',
            record_pointer='',url_field='url',identifier_fields={k:k for k in fields},required_fields=['meeting','document','version'],
            reviewed_by='fixture-publisher-metadata-review',reviewed_at=STAMP)
    request=dict(**specs,body=pinned(body),receipt=pinned(raw/key),relationship=relationship,
                 decided_by='campaign-identity-v1',decided_at=STAMP)
    path=tmp_path/'request.json';path.write_text(json.dumps(request))
    return path,writer,store


def test_native_ledger_membership_counts_reuse_and_pin_refusal(tmp_path):
    descriptor=inputs(tmp_path,extra_targets=['https://example.gov/live.html'])
    root=tmp_path/'plan';result=plan(descriptor,output=root,engine=engine())
    rows=pq.read_table(root/'url-dispositions.parquet').to_pylist()
    assert [(r['target_url'],r['disposition']) for r in rows]==[(TARGET,'retained_candidate_pending'),('https://example.gov/live.html','needs_acquisition')]
    assert rows[0]['host']=='docs.house.gov'
    counts=json.loads((root/'counts.json').read_text())
    assert counts['invariants'][0]['targets']==2
    assert result['acquisition_requests']==0
    before=(root/'url-dispositions.parquet').stat().st_mtime_ns
    assert plan(descriptor,output=root,engine=engine())==result
    assert (root/'url-dispositions.parquet').stat().st_mtime_ns==before
    (tmp_path/'targets.parquet').write_bytes(b'changed')
    with pytest.raises(ValueError,match='SHA-256'):plan(descriptor,output=root,engine=engine())


def test_duplicate_targets_cannot_become_execution_baseline(tmp_path):
    descriptor=inputs(tmp_path,extra_targets=[TARGET])
    with pytest.raises(ValueError,match='invariants'):plan(descriptor,output=tmp_path/'plan',engine=engine())
    assert not (tmp_path/'plan/input-manifest.json').exists()


@pytest.mark.parametrize('field,value',[('meeting','H-999'),('witness','Other person'),('date','2021-01-01'),('version','enr'),('document','D-8')])
def test_readable_wrong_document_never_reaches_import(tmp_path,field,value):
    descriptor=inputs(tmp_path);request,writer,store=candidate_request(tmp_path,candidate_changes={field:value})
    result=import_candidate(descriptor,request,output=tmp_path/'operation',engine=engine(),writer=writer,store=store)
    assert result['status']=='rejected' and result['reason']=='conflicting_'+field
    assert not (tmp_path/'raw/provenance').exists()
    assert len(list((tmp_path/'raw/receipts').rglob('*.gz')))==1


def test_supported_literal_alias_import_and_fresh_process_repeat(tmp_path):
    descriptor=inputs(tmp_path);request,writer,store=candidate_request(tmp_path)
    result=import_candidate(descriptor,request,output=tmp_path/'operation',engine=engine(),writer=writer,store=store)
    assert result['status']=='accepted' and result['decision']['recovery_record_version']==2
    assert file_pin(tmp_path/'operation/identity-evidence.json')['sha256']==result['evidence_sha256']
    assert result['decision']['original_url']==TARGET and result['decision']['recovered_url']==CANDIDATE
    assert result['decision']['identity_note'] is None
    identity=tmp_path/'writer.json';identity.write_text(json.dumps(IDENTITY))
    command=[sys.executable,'-m','corpus_recovery.campaign','import','--campaign',str(descriptor),'--request',str(request),
        '--runtime',os.environ['DOCSPEC_JOB_CONFIG'],'--output',str(tmp_path/'operation'),'--local-store',str(tmp_path/'raw'),
        '--writer-identity',str(identity)]
    # Same stable identity must survive a fresh process, even with another run_id.
    again=subprocess.run(command,check=True,capture_output=True,text=True)
    assert json.loads(again.stdout)==result
    assert len(list((tmp_path/'raw/receipts').rglob('*.gz')))==2
    assert len(list((tmp_path/'raw/provenance').rglob('*.jsonl')))==1


def test_campaign_preserves_explicit_evidence_supported_explanation(tmp_path):
    descriptor=inputs(tmp_path);request,writer,store=candidate_request(tmp_path)
    value=json.loads(request.read_text())
    value['identity_note']='Committee records identify both URLs as the same meeting statement D-7, version ih.'
    request.write_text(json.dumps(value))
    result=import_candidate(descriptor,request,output=tmp_path/'operation',engine=engine(),writer=writer,store=store)
    assert result['decision']['identity_note']==value['identity_note']
    assert result['decision']['kind']==value['relationship']
    assert file_pin(tmp_path/'operation/identity-evidence.json')['sha256']==result['evidence_sha256']


def test_legacy_operation_cannot_rewrite_its_immutable_decision(tmp_path):
    from corpus_recovery.acceptance import VERSION
    from congress_shared.campaign import load_campaign

    descriptor=inputs(tmp_path);request,writer,store=candidate_request(tmp_path)
    operation=tmp_path/'operation';operation.mkdir()
    binding=dict(descriptor_sha256=load_campaign(descriptor).descriptor_sha256,
                 request_sha256=file_pin(request)['sha256'],policy=VERSION)
    path=operation/'binding.json';path.write_text(json.dumps(binding))
    before=path.read_bytes()
    with pytest.raises(ValueError,match='inputs changed'):
        import_candidate(descriptor,request,output=operation,engine=engine(),writer=writer,store=store)
    assert path.read_bytes()==before
    assert not (tmp_path/'raw/provenance').exists()


def test_counterpart_cannot_satisfy_historical_requirement(tmp_path):
    descriptor=inputs(tmp_path);request,writer,store=candidate_request(tmp_path,relationship='official_updated_revision_available')
    result=import_candidate(descriptor,request,output=tmp_path/'operation',engine=engine(),writer=writer,store=store)
    assert result['status']=='review_required' and result['reason']=='relationship_does_not_satisfy_requirement'


def test_changed_source_bytes_receipt_and_outside_membership_refused(tmp_path):
    descriptor=inputs(tmp_path);request,writer,store=candidate_request(tmp_path)
    (tmp_path/'candidate.json').write_text('{}')
    with pytest.raises(ValueError,match='SHA-256'):
        import_candidate(descriptor,request,output=tmp_path/'operation',engine=engine(),writer=writer,store=store)


def test_unqualified_fake_pdf_cannot_import(tmp_path):
    descriptor=inputs(tmp_path);request,writer,store=candidate_request(tmp_path)
    body=tmp_path/'body.html';body.write_bytes(b'%PDF-1.7\nnot a PDF object structure\n%%EOF\n')
    value=json.loads(request.read_text());value['body']=pinned(body)
    fake=FetchAttempt(CANDIDATE,CANDIDATE,'2020-01-01T00:00:00Z','direct',200,None,{},(),True,
        BodyFile(body,file_pin(body)['sha256'],body.stat().st_size,'application/pdf',None,None,None))
    key,_=writer.write(FetchResult(fake),family='documents',mode='fetch')
    value['receipt']=pinned(tmp_path/'raw'/key);request.write_text(json.dumps(value))
    result=import_candidate(descriptor,request,output=tmp_path/'operation',engine=engine(),writer=writer,store=store)
    assert result['status']=='review_required' and result['reason']=='body_not_qualified'


@pytest.mark.parametrize('bridge', ['valid','missing','wrong-target'])
def test_updated_counterpart_needs_explicit_native_relationship(tmp_path,bridge):
    descriptor=inputs(tmp_path,requirement='current_official_counterpart')
    request,writer,store=candidate_request(tmp_path,target_changes={'bill':'hr7','congress':'118'},
        candidate_changes={'bill':'hr7','congress':'118','version':'enr','date':'2021-01-01','title':'Enrolled bill'},
        relationship='official_updated_revision_available')
    value=json.loads(request.read_text())
    if bridge!='missing':
        row=json.loads((tmp_path/'candidate.json').read_text())
        target=json.loads((tmp_path/'target.json').read_text());target.pop('url')
        row['relationship']={'kind':'official_updated_revision_available',
            'target_url':TARGET if bridge=='valid' else TARGET+'/other','target_identifiers':target}
        (tmp_path/'candidate.json').write_text(json.dumps(row))
        value['candidate']['source']=pinned(tmp_path/'candidate.json')
        value['candidate']['relationship_field']='relationship'
        request.write_text(json.dumps(value))
    result=import_candidate(descriptor,request,output=tmp_path/'operation',engine=engine(),writer=writer,store=store)
    assert result['status']=={'valid':'accepted','missing':'review_required','wrong-target':'rejected'}[bridge]


@pytest.mark.parametrize('case',['matching','different-requirement','profile-mismatch','duplicate-requirements'])
def test_planner_binds_state_to_profile_and_requested_policy(tmp_path,case):
    from congress_api.models.archive_profile import build_capture_profile
    descriptor=inputs(tmp_path)
    state=tmp_path/'state.parquet';requirements=tmp_path/'state-requirements.parquet';profile=tmp_path/'profile.json'
    pq.write_table(pa.Table.from_pylist([dict(url=TARGET,capture_disposition='satisfied',capture_decision_id='decision-1')]),state)
    row=dict(original_url=TARGET,target_requirement='current_official_counterpart' if case=='different-requirement' else 'historical_exact',
             acceptance_policy='recovery-identity-v1',refresh_policy='historical_only')
    pq.write_table(pa.Table.from_pylist([row,row] if case=='duplicate-requirements' else [row]),requirements)
    value=build_capture_profile(engine_revision='a'*40,url_normalized_sql='SELECT 1',url_keys_sql='SELECT 1',
        url_rules=[dict(id='rule',kind='strip',host_pattern=None,pattern='#.*$',replacement=None,decoder=None)],
        recovery_policy=dict(acceptance_policy='recovery-identity-v1',requirements_sha256='f'*64 if case=='profile-mismatch' else file_pin(requirements)['sha256']))
    profile.write_text(json.dumps(value))
    campaign=json.loads(descriptor.read_text());campaign['tables'].update(state=pinned(state),state_requirements=pinned(requirements),state_profile=pinned(profile))
    descriptor.write_text(json.dumps(campaign))
    if case in {'profile-mismatch','duplicate-requirements'}:
        with pytest.raises(ValueError):plan(descriptor,output=tmp_path/'plan',engine=engine())
        assert not (tmp_path/'plan/input-manifest.json').exists()
    else:
        plan(descriptor,output=tmp_path/'plan',engine=engine())
        [actual]=pq.read_table(tmp_path/'plan/url-dispositions.parquet').to_pylist()
        assert actual['disposition']==('accepted_recovery' if case=='matching' else 'retained_candidate_pending')
        assert actual['refresh_policy']=='refresh_live'


def test_literal_universe_preserves_normalized_aliases_and_later_membership(tmp_path):
    descriptor=inputs(tmp_path,extra_targets=[TARGET+'?version=2'])
    rows=[dict(target_url=TARGET,normalized_url=TARGET,url_key='same-key',membership_origin='baseline'),
          dict(target_url=TARGET+'?version=2',normalized_url=TARGET,url_key='same-key',membership_origin='later_batch')]
    pq.write_table(pa.Table.from_pylist(rows),tmp_path/'targets.parquet')
    value=json.loads(descriptor.read_text());value['tables']['targets']=pinned(tmp_path/'targets.parquet');descriptor.write_text(json.dumps(value))
    plan(descriptor,output=tmp_path/'plan',engine=engine())
    ledger=pq.read_table(tmp_path/'plan/url-dispositions.parquet').to_pylist()
    assert len(ledger)==2 and {r['url_key'] for r in ledger}=={'same-key'}
    counts=json.loads((tmp_path/'plan/counts.json').read_text())
    assert counts['memberships']==[{'membership_origin':'baseline','targets':1},{'membership_origin':'later_batch','targets':1}]



@pytest.mark.parametrize('which',['body','source','receipt'])
def test_null_digest_cannot_disable_input_pinning(tmp_path,which):
    descriptor=inputs(tmp_path);request,writer,store=candidate_request(tmp_path)
    value=json.loads(request.read_text())
    pin=value['target']['source'] if which=='source' else value[which]
    pin['sha256']=None
    request.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='exact file pin'):
        import_candidate(descriptor,request,output=tmp_path/'operation',engine=engine(),writer=writer,store=store)
    assert not (tmp_path/'raw/provenance').exists()



def test_duplicate_metadata_identifier_is_ambiguous(tmp_path):
    descriptor=inputs(tmp_path);request,writer,store=candidate_request(tmp_path)
    source=tmp_path/'target.json';source.write_text(source.read_text()[:-1]+',"version":"enr"}')
    value=json.loads(request.read_text());value['target']['source']=pinned(source);request.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='Duplicate evidence field'):
        import_candidate(descriptor,request,output=tmp_path/'operation',engine=engine(),writer=writer,store=store)
