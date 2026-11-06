"""Pinned metadata planning and evidence-bound imports through existing owners.

No body-store scan or network call is part of planning. Native SQL joins and
exports the campaign universe; Python handles bounded control artifacts only.
"""
import argparse
import fcntl
from hashlib import sha256
import json
from pathlib import Path

import pyarrow.parquet as pq

from congress_shared.campaign import load_campaign
from congress_shared.custody import canonical_json_bytes, verify_local_file, write_atomic_bytes, bounded_control_read
from congress_api.retention.provenance import (file_pin, instant, parquet_output, run_job,
    timestamp_key, validate_provenance, write_records)
from corpus_recovery.acceptance import VERSION, decide, identity_source, read_pin, pin_path, receipt_binding
from corpus_recovery.qualification import qualify, QualificationConfig
from corpus_recovery.reconcile import import_retained


def _q(value):
    return "'" + str(value).replace("'", "''") + "'"


def _input(campaign,name,alias):
    return dict(name=alias,kind='parquet',path=str(campaign.table_path(name)))


def _write(path,value):
    write_atomic_bytes(path,canonical_json_bytes(value)+b'\n')


def plan(descriptor, *, output, engine):
    campaign=load_campaign(descriptor)
    root=Path(output); root.mkdir(parents=True,exist_ok=True)
    if (root/'input-manifest.json').exists():
        prior=json.loads((root/'input-manifest.json').read_text())
        if prior['descriptor_sha256']!=campaign.descriptor_sha256:
            raise ValueError('Planning output belongs to different campaign inputs')
        for item in prior['outputs']:
            verify_local_file(root/item['path'],item['sha256'],item['size'])
        return prior
    targets=campaign.table_path(campaign.target_table)
    candidates=campaign.table_path(campaign.candidate_table)
    names=set(pq.read_schema(targets).names)
    if 'target_url' not in names or not {'target_url','candidate_url'}.issubset(pq.read_schema(candidates).names):
        raise ValueError('Campaign tables need literal target/candidate URLs')
    # Optional target facts must come from explicitly pinned release/inventory inputs.
    def col(name,kind,default='NULL'):
        return name if name in names else f'cast({default} AS {kind}) AS {name}'
    raw='SELECT target_url,'+','.join([col('subtype','VARCHAR'),col('evidence_id','VARCHAR'),
        col('usable_direct','BOOLEAN','false'),col('acquisition_excluded','BOOLEAN','false'),
        col('unresolved_reason','VARCHAR'),col('refresh_policy','VARCHAR',"'refresh_live'"),col('normalized_url','VARCHAR'),
        col('url_key','VARCHAR'),col('membership_origin','VARCHAR',"'unknown'")])+' FROM targets_input'
    inputs=[_input(campaign,campaign.target_table,'targets_input'),
            _input(campaign,campaign.candidate_table,'candidates_input')]
    # State is already produced by the native qualified-decision owner. A planner
    # does not elevate arbitrary accepted mapping rows into recovery evidence.
    state="SELECT cast(NULL AS VARCHAR) AS url,cast(NULL AS VARCHAR) AS capture_disposition,cast(NULL AS VARCHAR) AS capture_decision_id WHERE false"
    if 'state' in campaign.tables:
        # url_state.parquet (model/sql/url-state.sql) names the literal 'requested_url';
        # older state tables name it 'url'. Either is the same literal address.
        state_names=set(pq.read_schema(campaign.table_path('state')).names)
        state_url='url' if 'url' in state_names else 'requested_url' if 'requested_url' in state_names else None
        if state_url is None or not {'capture_disposition','capture_decision_id'}.issubset(state_names):
            raise ValueError('State table lacks versioned capture eligibility')
        if not {'state_profile','state_requirements'}.issubset(campaign.tables):
            raise ValueError('State requires its pinned capture profile and requirements')
        from congress_api.models.archive_profile import validate_capture_profile
        with campaign.table_path('state_profile').open('rb') as stream:
            profile=json.loads(bounded_control_read(stream))
        validate_capture_profile(profile,engine_revision=profile['engine_revision'])
        policy=profile.get('recovery_policy')
        if policy!={'acceptance_policy':VERSION,'requirements_sha256':campaign.tables['state_requirements'].sha256}:
            raise ValueError('State requirements or acceptance policy do not match its profile')
        inputs.extend([_input(campaign,'state','state_input'),_input(campaign,'state_requirements','state_requirements')])
        state=f"""SELECT s.{state_url} AS url,CASE WHEN s.capture_disposition='satisfied' AND
            NOT coalesce(r.target_requirement={_q(campaign.requirement)} AND r.acceptance_policy={_q(VERSION)},false)
            THEN 'eligible' ELSE s.capture_disposition END AS capture_disposition,s.capture_decision_id
            FROM state_input s LEFT JOIN state_requirements r ON s.{state_url}=r.original_url"""
    steps=[dict(name='targets',sql=raw),dict(name='state',sql=state),
        dict(name='candidate_counts',sql='SELECT target_url,count(*) AS candidates FROM candidates_input GROUP BY target_url'),
        dict(name='ledger',sql=f'''SELECT t.target_url,t.normalized_url,t.url_key,t.membership_origin,
        regexp_replace(t.target_url,'^https?://([^/]+).*$', '\\1') AS host,t.subtype,
        CASE WHEN coalesce(t.unresolved_reason,'')<>'' OR
                  (coalesce(t.usable_direct,false) AND coalesce(t.acquisition_excluded,false)) THEN 'unresolved'
             WHEN coalesce(t.usable_direct,false) THEN 'usable_direct'
             WHEN s.capture_disposition='satisfied' AND s.capture_decision_id IS NOT NULL THEN 'accepted_recovery'
             WHEN coalesce(t.acquisition_excluded,false) OR s.capture_disposition='excluded' THEN 'acquisition_excluded'
             WHEN c.candidates>0 THEN 'retained_candidate_pending' ELSE 'needs_acquisition' END AS disposition,
        coalesce(t.unresolved_reason,s.capture_disposition,'metadata_policy') AS reason,
        coalesce(s.capture_decision_id,t.evidence_id,{_q(campaign.descriptor_sha256)}) AS evidence_id,
        {_q(campaign.requirement)} AS target_requirement,{_q(VERSION)} AS acceptance_policy,t.refresh_policy,
        coalesce(c.candidates,0) AS candidates
        FROM targets t LEFT JOIN state s ON t.target_url=s.url
        LEFT JOIN candidate_counts c ON t.target_url=c.target_url''')]
    queries=[dict(name='invariants',sql='''SELECT
        (SELECT count(*) FROM targets) AS targets,
        (SELECT count(DISTINCT target_url) FROM targets) AS distinct_targets,
        (SELECT count(*) FROM ledger) AS ledger,
        (SELECT count(*) FROM targets WHERE target_url IS NULL OR NOT regexp_like(target_url,'^https?://[^/]+') OR refresh_policy IS NULL OR refresh_policy NOT IN ('historical_only','refresh_live') OR membership_origin IS NULL OR membership_origin NOT IN ('baseline','later_batch','unknown')) AS invalid_urls,
        (SELECT count(*) FROM targets WHERE (usable_direct OR acquisition_excluded) AND coalesce(evidence_id,'')='') AS evidence_free,
        (SELECT count(*) FROM (SELECT url FROM state GROUP BY url HAVING count(*)>1)) AS duplicate_state,
        (SELECT count(*) FROM candidates_input c LEFT JOIN targets t ON c.target_url=t.target_url WHERE t.target_url IS NULL) AS outside_candidates'''),
        dict(name='memberships',sql='SELECT membership_origin,count(*) AS targets FROM ledger GROUP BY membership_origin ORDER BY membership_origin'),
        dict(name='dispositions',sql='SELECT disposition,count(*) AS targets FROM ledger GROUP BY disposition ORDER BY disposition'),
        dict(name='hosts',sql='SELECT host,disposition,count(*) AS targets FROM ledger GROUP BY host,disposition ORDER BY host,disposition'),
        dict(name='subtypes',sql='SELECT subtype,disposition,count(*) AS targets FROM ledger GROUP BY subtype,disposition ORDER BY subtype,disposition')]
    outputs=[parquet_output(root,'url-dispositions','SELECT DISTINCT * FROM ledger',['target_url']),
             parquet_output(root,'recovery-requirements','SELECT DISTINCT target_url AS original_url,target_requirement,acceptance_policy,refresh_policy FROM ledger',['original_url'])]
    reports=run_job(root/'native-plan',engine,inputs=inputs,steps=steps,outputs=outputs,queries=queries)
    checks=reports['invariants'][0]
    if (checks['targets']!=checks['distinct_targets'] or checks['ledger']!=checks['targets']
            or any(checks[k] for k in ('invalid_urls','evidence_free','duplicate_state','outside_candidates'))):
        raise ValueError('Campaign membership or evidence invariants failed; native report retained')
    campaign.require_custody()
    _write(root/'counts.json',reports)
    manifest=dict(version=1,campaign_id=campaign.campaign_id,descriptor_sha256=campaign.descriptor_sha256,
        requirement=campaign.requirement,acceptance_policy=VERSION,
        inputs={name:dict(path=str(v.path),sha256=v.sha256,size=v.size_bytes) for name,v in campaign.tables.items()},
        outputs=[dict(path=Path(o['path']).name,**file_pin(o['path'])) for o in outputs]+[
            dict(path='counts.json',**file_pin(root/'counts.json'))],acquisition_requests=0)
    _write(root/'input-manifest.json',manifest)
    return manifest


def _member(campaign,target,candidate,engine,work):
    reports=run_job(work,engine,inputs=[_input(campaign,campaign.target_table,'targets'),
        _input(campaign,campaign.candidate_table,'candidates')],steps=[],outputs=[],queries=[dict(name='membership',sql=f'''SELECT
        (SELECT count(*) FROM targets WHERE target_url={_q(target)}) AS targets,
        (SELECT count(*) FROM candidates WHERE target_url={_q(target)} AND candidate_url={_q(candidate)}) AS candidates''')])
    if reports['membership'][0] != {'targets':1,'candidates':1}:
        raise ValueError('Candidate is not an unambiguous pinned campaign member')


def _acknowledged_import(root,campaign,binding,request,match_basis):
    """Replay a completed acknowledgement without reauthoring immutable decisions."""
    path=root/'result.json'
    if not path.exists():return None
    with path.open('rb') as stream:result=json.loads(bounded_control_read(stream))
    if result.get('status') not in {'accepted','rejected','review_required'}:
        raise ValueError('Unknown retained import result status')
    if result.get('status')!='accepted':return None
    record=result.get('decision',{})
    validate_provenance('recoveries',record)
    operation=sha256(canonical_json_bytes(binding)).hexdigest()
    if (record['id']!=operation or record.get('recovery_record_version')!=2
            or record.get('acceptance_status')!='accepted' or record.get('acceptance_policy')!=VERSION
            or record.get('target_requirement')!=campaign.requirement
            or record.get('match_basis')!=match_basis
            or record.get('body_sha256')!=request['body']['sha256']
            or record.get('evidence_sha256')!=result.get('evidence_sha256')
            or not all(isinstance(result.get(k),str) and result[k] for k in ('receipt_key','provenance_key'))):
        raise ValueError('Acknowledged import differs from its original operation bindings')
    evidence,_=read_pin(dict(path=str((root/'identity-evidence.json').resolve()),
                             sha256=result['evidence_sha256']),root)
    if (evidence.get('version')!=VERSION or evidence.get('requirement')!=campaign.requirement
            or evidence['target']['url']!=record['original_url'] or evidence['candidate']['url']!=record['recovered_url']
            or evidence['body_sha256']!=record['body_sha256']
            or evidence['qualification_sha256']!=record['qualification_sha256']):
        raise ValueError('Acknowledged import differs from its retained identity evidence')
    campaign.require_custody()
    return result


def import_candidate(descriptor, request_path, *, output, engine, writer, store,
                     qualification_config=QualificationConfig()):
    """Qualify actual bytes, compare pinned source records, then use common writers.

    The request names body/receipt pins, target/candidate identity sources,
    relationship, decision timestamp and actor. It is bounded control data for
    one candidate, not an in-memory corpus manifest. Restart preserves the exact
    request and stable receipt/provenance identities.
    """
    campaign=load_campaign(descriptor)
    request_path=Path(request_path)
    pin=file_pin(request_path)
    request,_=read_pin(dict(path=str(request_path.resolve()),sha256=pin['sha256']),request_path.parent)
    match_basis=request.get('match_basis','official_document_identifier')
    if not isinstance(match_basis,str) or match_basis not in {'official_document_identifier','source_catalog_document_identifier'}:
        raise ValueError('Unsupported campaign match basis')
    root=Path(output);root.mkdir(parents=True,exist_ok=True)
    binding=dict(descriptor_sha256=campaign.descriptor_sha256,request_sha256=pin['sha256'],policy=VERSION)
    with (root/'operation.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        saved=root/'binding.json'
        if saved.exists() and json.loads(saved.read_text())!=binding:
            raise ValueError('Recovery operation inputs changed; use a new operation')
        if not saved.exists():_write(saved,binding)
        acknowledged=_acknowledged_import(root,campaign,binding,request,match_basis)
        if acknowledged is not None:return acknowledged
        target=identity_source(request['target'],request_path.parent)
        candidate=identity_source(request['candidate'],request_path.parent)
        _member(campaign,target['url'],candidate['url'],engine,root/'membership')
        receipt,_=read_pin(request['receipt'],request_path.parent)
        body_path=pin_path(request['body'],request_path.parent)
        body=verify_local_file(body_path,expected_sha256=request['body']['sha256'])
        receipt_binding(receipt,url=candidate['url'],digest=body.sha256,size=body.size_bytes)
        qualification=qualify(body,root.parent/'qualification-cache',config=qualification_config)
        if qualification['status']!='qualified':
            result=dict(status='review_required',reason='body_not_qualified',qualification=dict(qualification))
            _write(root/'result.json',result);return result
        from urllib.parse import urlsplit
        if urlsplit(candidate['url']).path.lower().endswith('.pdf') and qualification['media_type']!='application/pdf':
            result=dict(status='review_required',reason='candidate_format_mismatch')
            _write(root/'result.json',result);return result
        decision=decide(target,candidate,requirement=campaign.requirement,relationship=request['relationship'],
            body=body,qualification=qualification,receipt=receipt,receipt_sha256=request['receipt']['sha256'])
        write_atomic_bytes(root/'identity-evidence.json',canonical_json_bytes(decision['evidence']))
        if decision['status']!='accepted':
            _write(root/'result.json',decision);return decision
        instant(request['decided_at'])
        if not isinstance(request.get('decided_by'),str) or not request['decided_by'].strip():
            raise ValueError('Recovery decision needs a named process or reviewer')
        operation=sha256(canonical_json_bytes(binding)).hexdigest()
        campaign.require_custody()
        source=dict(original_url=target['url'],recovered_url=candidate['url'],body_path=str(body.path),
            body_sha256=body.sha256,retrieved_at=decision['evidence']['retrieved_at'],
            media_type=qualification['media_type'],category=request['relationship'],
            match_basis=match_basis,imported_at=request['decided_at'],
            evidence_sha256=decision['evidence_sha256'])
        receipt_key,_=import_retained(writer,source,operation_id=operation,freeze_dir=root/'receipts',verified_body=body)
        record=dict(id=operation,original_url=target['url'],recovered_url=candidate['url'],
            recovered_filename=None,body_sha256=body.sha256,kind=request['relationship'],
            match_basis=source['match_basis'],evidence_sha256=decision['evidence_sha256'],
            identity_note=decision['reason'],decided_by=request['decided_by'],decided_at=request['decided_at'],
            supersedes=request.get('supersedes'),recovery_record_version=2,target_requirement=campaign.requirement,
            acceptance_status='accepted',acceptance_policy=VERSION,qualification_sha256=qualification['qualification_sha256'])
        validate_provenance('recoveries',record)
        provenance_key,_=write_records(store,'recoveries',[record],timestamp=timestamp_key(request['decided_at'])+'-'+operation)
        result=dict(status='accepted',receipt_key=receipt_key,decision=record,provenance_key=provenance_key,
                    evidence_sha256=decision['evidence_sha256'])
        _write(root/'result.json',result)
        return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    for name in ('plan','import'):
        command=sub.add_parser(name);command.add_argument('--campaign',required=True)
        command.add_argument('--output',required=True);command.add_argument('--runtime',required=True)
    sub.choices['import'].add_argument('--request',required=True)
    sub.choices['import'].add_argument('--local-store',required=True)
    sub.choices['import'].add_argument('--writer-identity',required=True,help='JSON with job, commit, lockfile_digest')
    args=parser.parse_args(argv)
    from docspec_client.client import NativeDatasets
    engine=NativeDatasets.from_config(args.runtime)
    if args.command=='plan':result=plan(args.campaign,output=args.output,engine=engine)
    else:
        from congress_api.retention.body_store import BodyStore,LocalAdapter
        from congress_api.retention.receipt_writer import ReceiptWriter
        store=BodyStore(LocalAdapter(Path(args.local_store)))
        request,_=read_pin(dict(path=str(Path(args.request).resolve()),sha256=file_pin(args.request)['sha256']),Path(args.request).parent)
        writer=ReceiptWriter(store,identity=json.loads(Path(args.writer_identity).read_text()),
            run_id='recovery-campaign',write_date=instant(request['decided_at']).date().isoformat(),archive_limits=None)
        result=import_candidate(args.campaign,args.request,output=args.output,engine=engine,writer=writer,store=store)
    print(json.dumps(result,sort_keys=True,indent=2))


if __name__=='__main__':main()
