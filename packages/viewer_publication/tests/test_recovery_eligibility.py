"""Native eligibility retains fetch history and requires pinned qualified decisions."""
import os
from pathlib import Path

import pytest

from congress_api.retention.provenance import json_input,run_job
from docspec_client.client import NativeDatasets
from viewer_publication.archive_url_state import url_state_steps


def test_pinned_recovery_eligibility(tmp_path):
    policy='recovery-identity-v1'
    urls=['https://example.test/'+name for name in ('valid.pdf','wrong.pdf','withdrawn.pdf','live.pdf','stream.mp4')]
    requirements=[dict(original_url=url,target_requirement='historical_exact',acceptance_policy=policy,refresh_policy='historical_only') for url in urls[:3]]
    decisions=[dict(id='valid',original_url=urls[0],body_sha256='a'*64,kind='recovered_document',
        target_requirement='historical_exact',acceptance_policy=policy,acceptance_status='accepted',
        evidence_sha256='b'*64,qualification_sha256='c'*64,recovery_record_version=2,supersedes=None),
        dict(id='wrong',original_url=urls[1],body_sha256='a'*64,kind='official_updated_revision_available',
        target_requirement='historical_exact',acceptance_policy=policy,acceptance_status='accepted',
        evidence_sha256='b'*64,qualification_sha256='c'*64,recovery_record_version=2,supersedes=None),
        dict(id='old',original_url=urls[2],body_sha256='a'*64,kind='recovered_document',
        target_requirement='historical_exact',acceptance_policy=policy,acceptance_status='accepted',
        evidence_sha256='b'*64,qualification_sha256='c'*64,recovery_record_version=2,supersedes=None),
        dict(id='withdrawal',original_url=urls[2],body_sha256='a'*64,kind='rejected',
        target_requirement='historical_exact',acceptance_policy=policy,acceptance_status='rejected',
        evidence_sha256='b'*64,qualification_sha256='c'*64,recovery_record_version=2,supersedes='old')]
    def inp(name,rows,**fields):return json_input(tmp_path,name,rows,**fields)
    inputs=[inp('recovery_requirements',requirements,original_url='Utf8',target_requirement='Utf8',acceptance_policy='Utf8',refresh_policy='Utf8'),
        inp('recovery_decisions',decisions,**{**{k:'Utf8' for k in ('id','original_url','body_sha256','kind','target_requirement','acceptance_policy','acceptance_status','evidence_sha256','qualification_sha256','supersedes')},'recovery_record_version':'Int32'}),
        inp('retained', [dict(original_url=url,body='a'*64) for url in urls],original_url='Utf8',body='Utf8'),
        inp('url_state_history',[dict(requested_url=url,attempts=1,last_status=404) for url in urls],requested_url='Utf8',attempts='Int32',last_status='Int32'),
        inp('url_state_latest',[dict(requested_url=url,family='documents') for url in urls],requested_url='Utf8',family='Utf8'),
        inp('url_state_scope_exclusions',[dict(family='documents',pattern='[.]mp4$')],family='Utf8',pattern='Utf8')]
    step=next(s for s in url_state_steps(recovery_policy=dict(acceptance_policy=policy)) if s['name']=='url_state')
    result=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=[dict(name='captures',sql="SELECT original_url,decode(body,'hex') AS sha256,'retained_import' AS mode,true AS complete FROM retained"),step],outputs=[],
        queries=[dict(name='rows',sql='SELECT * FROM url_state ORDER BY requested_url')])
    rows={r['requested_url']:r for r in result['rows']}
    assert [rows[url]['capture_disposition'] for url in urls]==['satisfied','eligible','eligible','eligible','excluded']
    assert rows[urls[0]]['capture_decision_id']=='valid'
    assert all(rows[url]['last_status']==404 and rows[url]['attempts']==1 for url in urls)


def test_govinfo_details_rows_are_excluded_by_the_scope_they_were_captured_under(tmp_path):
    """ct-egoo (owner, 2026-11-11: stop fetching). url_state carries 34,831 GovInfo Content Details pages,
    captured as family documents by the 2026-10-05 download and published as eligible and due weekly. The
    real registry's documents exclusion marks them excluded, so the scheduler counts them done; the
    package's PDF in that family stays eligible."""
    import json
    policy='recovery-identity-v1'
    registry=json.loads((Path(__file__).resolve().parents[3]/'model/registries/capture-scope.json').read_text())
    exclusions=[dict(family=entry['family'],pattern=pattern) for entry in registry['entries'] for pattern in entry['exclusions']]
    details='https://www.govinfo.gov/app/details/CHRG-119hhrg12345'
    urls=[details,details+'/CHRG-119hhrg12345-pt1','https://www.govinfo.gov/content/pkg/CHRG-119hhrg12345/pdf/CHRG-119hhrg12345.pdf']
    def inp(name,rows,**fields):return json_input(tmp_path,name,rows,**fields)
    text=lambda *names:{name:'Utf8' for name in names}
    inputs=[inp('recovery_requirements',[],**text('original_url','target_requirement','acceptance_policy','refresh_policy')),
        inp('recovery_decisions',[],**text('id','original_url','body_sha256','kind','target_requirement','acceptance_policy','acceptance_status',
            'evidence_sha256','qualification_sha256','supersedes'),recovery_record_version='Int32'),
        inp('retained',[],**text('original_url','body')),
        inp('url_state_history',[dict(requested_url=url,attempts=1,last_status=200) for url in urls],requested_url='Utf8',attempts='Int32',last_status='Int32'),
        inp('url_state_latest',[dict(requested_url=url,family='documents') for url in urls],**text('requested_url','family')),
        inp('url_state_scope_exclusions',exclusions,**text('family','pattern'))]
    step=next(s for s in url_state_steps(recovery_policy=dict(acceptance_policy=policy)) if s['name']=='url_state')
    result=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=[dict(name='captures',sql="SELECT original_url,decode(body,'hex') AS sha256,'retained_import' AS mode,true AS complete FROM retained"),step],outputs=[],
        queries=[dict(name='rows',sql='SELECT requested_url,capture_disposition,capture_reason FROM url_state ORDER BY requested_url')])
    rows={r['requested_url']:(r['capture_disposition'],r['capture_reason']) for r in result['rows']}
    assert [rows[url] for url in urls]==[('excluded','scope_exclusion')]*2+[('eligible','no_satisfying_recovery')]


def test_real_model_exports_versioned_eligibility(tmp_path):
    import json
    import pyarrow as pa
    import pyarrow.parquet as pq
    from archive_job_fixture import real_model_spec
    from congress_api.retention.provenance import file_pin
    from viewer_publication.archive_model_job import validate_spec,execute
    spec,_,_=real_model_spec(tmp_path)
    requirements=tmp_path/'requirements.parquet'
    pq.write_table(pa.table({'original_url':['https://fixture.test/report.html'],
        'target_requirement':['historical_exact'],'acceptance_policy':['recovery-identity-v1'],'refresh_policy':['historical_only']}),requirements)
    spec['recovery_requirements']=dict(path=str(requirements),**file_pin(requirements),acceptance_policy='recovery-identity-v1')
    spec=validate_spec(spec,base=tmp_path)
    execute(spec)
    profile=json.loads((tmp_path/'release/capture_profile.json').read_text())
    assert profile['version']==2 and profile['recovery_policy']['requirements_sha256']==file_pin(requirements)['sha256']
    rows=pq.read_table(tmp_path/'release/url_state.parquet').to_pylist()
    assert rows[0]['capture_disposition']=='eligible' and rows[0]['last_status']==200
    schema=json.loads((tmp_path/'release/schema.json').read_text())
    assert 'capture_disposition' in [x['name'] for x in next(x for x in schema['files'] if x['name']=='url_state.parquet')['columns']]


def test_native_requirement_relationship_and_literal_identity_matrix(tmp_path):
    """Hashes here prove syntax only; the accepted producer owns their bindings."""
    policy='recovery-identity-v1'
    cases=[
        ('exact','historical_exact','recovered_document','satisfied',{}),
        ('requested','requested_content','requested_content_in_official_hearing','satisfied',{}),
        ('current','current_official_counterpart','official_updated_revision_available','satisfied',{}),
        ('article','requested_content','same_article_publisher_text_available','satisfied',{}),
        ('final-report','current_official_counterpart','related_final_report_available','satisfied',{}),
        ('historical-wrong','historical_exact','official_updated_revision_available','eligible',{}),
        ('requested-wrong','requested_content','official_updated_revision_available','eligible',{}),
        ('policy-mismatch','historical_exact','recovered_document','eligible',{'acceptance_policy':'other'}),
        ('requirement-mismatch','historical_exact','recovered_document','eligible',{'target_requirement':'requested_content'}),
        ('body-mismatch','historical_exact','recovered_document','eligible',{'body_sha256':'d'*64}),
        ('missing-qualification','historical_exact','recovered_document','eligible',{'qualification_sha256':None}),
        ('uppercase-qualification','historical_exact','recovered_document','eligible',{'qualification_sha256':'C'*64}),
        ('malformed-evidence','historical_exact','recovered_document','eligible',{'evidence_sha256':'unbound'}),
        ('legacy','historical_exact','recovered_document','eligible',{'recovery_record_version':None}),
        ('ambiguous','historical_exact','recovered_document','eligible',{}),
        ('successor','historical_exact','recovered_document','satisfied',{'supersedes':'successor-old'}),
        ('literal?Case=A','historical_exact','recovered_document','eligible',{'original_url':'https://example.test/literal?case=a'}),
    ]
    requirements=[];decisions=[];urls=[];expected=[]
    for name,requirement,kind,disposition,changes in cases:
        url='https://example.test/'+name;urls.append(url);expected.append(disposition)
        requirements.append(dict(original_url=url,target_requirement=requirement,acceptance_policy=policy,refresh_policy='historical_only'))
        decisions.append(dict(dict(id=name,original_url=url,body_sha256='a'*64,kind=kind,
            target_requirement=requirement,acceptance_policy=policy,acceptance_status='accepted',
            evidence_sha256='b'*64,qualification_sha256='c'*64,recovery_record_version=2,supersedes=None),**changes))
    ambiguous=next(row for row in decisions if row['id']=='ambiguous')
    decisions.append(dict(ambiguous,id='ambiguous-other'))
    successor=next(row for row in decisions if row['id']=='successor')
    decisions.append(dict(successor,id='successor-old',supersedes=None))
    # A non-campaign live page and in-scope captions remain refreshable.
    live='https://example.test/live';caption='https://www-senate-gov-media-srs.akamaized.net/hls/event.vtt'
    stream='https://example.test/video.mp4'
    requirements.append(dict(original_url=live,target_requirement='historical_exact',acceptance_policy=policy,refresh_policy='refresh_live'))
    decisions.append(dict(decisions[0],id='accepted-live',original_url=live))
    urls.extend([live,caption,stream]);expected.extend(['eligible','eligible','excluded'])
    def inp(name,rows,**fields):return json_input(tmp_path,name,rows,**fields)
    inputs=[inp('recovery_requirements',requirements,original_url='Utf8',target_requirement='Utf8',acceptance_policy='Utf8',refresh_policy='Utf8'),
        inp('recovery_decisions',decisions,**{**{k:'Utf8' for k in ('id','original_url','body_sha256','kind','target_requirement','acceptance_policy','acceptance_status','evidence_sha256','qualification_sha256','supersedes')},'recovery_record_version':'Int32'}),
        inp('retained',[dict(original_url=url,body='a'*64) for url in urls],original_url='Utf8',body='Utf8'),
        inp('url_state_history',[dict(requested_url=url,attempts=2,last_status=404) for url in urls],requested_url='Utf8',attempts='Int32',last_status='Int32'),
        inp('url_state_latest',[dict(requested_url=url,family='senate/captions' if url==caption else 'documents') for url in urls],requested_url='Utf8',family='Utf8'),
        inp('url_state_scope_exclusions',[dict(family='documents',pattern='[.]mp4$')],family='Utf8',pattern='Utf8')]
    step=next(s for s in url_state_steps(recovery_policy=dict(acceptance_policy=policy)) if s['name']=='url_state')
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        result=run_job(tmp_path,engine,inputs=inputs,
            steps=[dict(name='captures',sql="SELECT original_url,decode(body,'hex') AS sha256,'retained_import' AS mode,true AS complete FROM retained"),step],outputs=[],
            queries=[dict(name='rows',sql='SELECT * FROM url_state ORDER BY requested_url')])
    rows={r['requested_url']:r for r in result['rows']}
    assert [rows[url]['capture_disposition'] for url in urls]==expected
    assert all(row['last_status']==404 and row['attempts']==2 for row in rows.values())


@pytest.mark.parametrize('refresh_policy',[None,'unrecognized'])
def test_full_model_refuses_invalid_refresh_policy(tmp_path,refresh_policy):
    import pyarrow as pa
    import pyarrow.parquet as pq
    from archive_job_fixture import real_model_spec
    from congress_api.retention.provenance import file_pin
    from viewer_publication.archive_model_job import validate_spec,execute
    spec,_,_=real_model_spec(tmp_path)
    path=tmp_path/'requirements.parquet'
    pq.write_table(pa.table(dict(original_url=['https://fixture.test/report.html'],target_requirement=['historical_exact'],
        acceptance_policy=['recovery-identity-v1'],refresh_policy=pa.array([refresh_policy],type=pa.string()))),path)
    spec['recovery_requirements']=dict(path=str(path),**file_pin(path),acceptance_policy='recovery-identity-v1')
    with pytest.raises(ValueError,match='invariant'):
        execute(validate_spec(spec,base=tmp_path))


def test_legacy_requirements_conservatively_keep_live_refresh(tmp_path):
    import pyarrow.parquet as pq
    from test_recovery_publication_journey import retained_model
    from congress_api.retention.provenance import file_pin
    from viewer_publication.archive_model_job import validate_spec,execute
    spec,_,_,_,urls=retained_model(tmp_path)
    path=Path(spec['recovery_requirements']['path'])
    table=pq.read_table(path).drop(['refresh_policy']);pq.write_table(table,path)
    spec['recovery_requirements'].update(file_pin(path))
    execute(validate_spec(spec,base=tmp_path))
    states={row['requested_url']:row for row in pq.read_table(Path(spec['output'])/'url_state.parquet').to_pylist()}
    assert states[urls['exact']]['capture_disposition']=='eligible'
    assert states[urls['live']]['capture_disposition']=='eligible'
