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


def test_body_qualifications_route_unqualified_http_200_and_survive_304_or_validator_unchanged(tmp_path):
    """ct-zohj: HTTP-200 failed-qualification PDFs remain eligible (body_not_qualified) across 304 and
    validator_unchanged receipts, while healthy historical_only PDFs satisfy (qualified_direct_body)
    and refresh_live PDFs keep their live schedule."""
    import io
    from pypdf import PdfWriter
    from congress_api.retention.qualification_facts import model_qualification_input
    from congress_shared.custody import verify_local_file
    from corpus_recovery.qualification import qualify

    policy = 'recovery-identity-v1'
    corrupt_path = tmp_path / 'corrupt.pdf'
    corrupt_path.write_bytes(b'%PDF-1.7\ntruncated-without-eof')
    corrupt_rec = qualify(verify_local_file(corrupt_path), tmp_path / 'qcache')
    assert corrupt_rec['status'] == 'unresolved'

    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    good_path = tmp_path / 'good.pdf'
    good_path.write_bytes(buf.getvalue())
    good_rec = qualify(verify_local_file(good_path), tmp_path / 'qcache')
    assert good_rec['status'] == 'qualified'

    html_path = tmp_path / 'soft404.html'
    html_path.write_text('<html><title>Testimony</title><div class="field-name-body">' + 'substantive text ' * 70 + '</div></html>')
    html_rec = qualify(verify_local_file(html_path), tmp_path / 'qcache')
    assert html_rec['status'] == 'qualified' and html_rec['media_type'] == 'text/html'

    u_corrupt_304 = 'https://example.test/corrupt-304.pdf'
    u_corrupt_200_unchanged = 'https://example.test/corrupt-unchanged.pdf'
    u_fixed = 'https://example.test/fixed-later.pdf'
    u_healthy_hist = 'https://example.test/healthy-hist.pdf'
    u_healthy_live = 'https://example.test/healthy-live.pdf'
    u_pdf_got_html = 'https://example.test/html-at-pdf.pdf'
    all_urls = [u_corrupt_304, u_corrupt_200_unchanged, u_fixed, u_healthy_hist, u_healthy_live, u_pdf_got_html]

    requirements = [
        dict(original_url=u, target_requirement='historical_exact', acceptance_policy=policy,
             refresh_policy='refresh_live' if u == u_healthy_live else 'historical_only')
        for u in all_urls
    ]
    qual_inp, qual_step = model_qualification_input([corrupt_rec, good_rec, html_rec], tmp_path / 'quals')

    capture_rows = [
        # 1. Corrupt HTTP-200 at t1 followed by 304 Not Modified at t2 (no body sha)
        dict(receipt_key='r1', receipt_line=1, capture_index=0, mode='fetch', complete=True, attempt=0,
             member_path=None, requested_url=u_corrupt_304, original_url=None, body_hex=corrupt_rec['body_sha256'],
             retrieved_at='2026-10-01T00:00:00Z', http_status=200, outcome='stored', fetch_http_status=200, fetch_outcome='stored'),
        dict(receipt_key='r2', receipt_line=1, capture_index=0, mode='fetch', complete=True, attempt=0,
             member_path=None, requested_url=u_corrupt_304, original_url=None, body_hex=None,
             retrieved_at='2026-10-10T00:00:00Z', http_status=304, outcome='unchanged', fetch_http_status=304, fetch_outcome='unchanged'),
        # 2. Corrupt HTTP-200 at t1 followed by 200 validator_unchanged (no body sha) at t2
        dict(receipt_key='r3', receipt_line=1, capture_index=0, mode='fetch', complete=True, attempt=0,
             member_path=None, requested_url=u_corrupt_200_unchanged, original_url=None, body_hex=corrupt_rec['body_sha256'],
             retrieved_at='2026-10-01T00:00:00Z', http_status=200, outcome='stored', fetch_http_status=200, fetch_outcome='stored'),
        dict(receipt_key='r4', receipt_line=1, capture_index=0, mode='fetch', complete=True, attempt=0,
             member_path=None, requested_url=u_corrupt_200_unchanged, original_url=None, body_hex=None,
             retrieved_at='2026-10-10T00:00:00Z', http_status=200, outcome='unchanged', fetch_http_status=200, fetch_outcome='unchanged'),
        # 3. Corrupt HTTP-200 at t1 later replaced by a valid PDF at t2
        dict(receipt_key='r5', receipt_line=1, capture_index=0, mode='fetch', complete=True, attempt=0,
             member_path=None, requested_url=u_fixed, original_url=None, body_hex=corrupt_rec['body_sha256'],
             retrieved_at='2026-10-01T00:00:00Z', http_status=200, outcome='stored', fetch_http_status=200, fetch_outcome='stored'),
        dict(receipt_key='r6', receipt_line=1, capture_index=0, mode='fetch', complete=True, attempt=0,
             member_path=None, requested_url=u_fixed, original_url=None, body_hex=good_rec['body_sha256'],
             retrieved_at='2026-10-10T00:00:00Z', http_status=200, outcome='stored', fetch_http_status=200, fetch_outcome='stored'),
        # 4. Healthy historical_only PDF
        dict(receipt_key='r7', receipt_line=1, capture_index=0, mode='fetch', complete=True, attempt=0,
             member_path=None, requested_url=u_healthy_hist, original_url=None, body_hex=good_rec['body_sha256'],
             retrieved_at='2026-10-01T00:00:00Z', http_status=200, outcome='stored', fetch_http_status=200, fetch_outcome='stored'),
        # 5. Healthy refresh_live PDF (remains eligible for ordinary refresh)
        dict(receipt_key='r8', receipt_line=1, capture_index=0, mode='fetch', complete=True, attempt=0,
             member_path=None, requested_url=u_healthy_live, original_url=None, body_hex=good_rec['body_sha256'],
             retrieved_at='2026-10-01T00:00:00Z', http_status=200, outcome='stored', fetch_http_status=200, fetch_outcome='stored'),
        # 6. .pdf URL served HTML 200 (even though HTML body qualified as text/html, .pdf expects application/pdf)
        dict(receipt_key='r9', receipt_line=1, capture_index=0, mode='fetch', complete=True, attempt=0,
             member_path=None, requested_url=u_pdf_got_html, original_url=None, body_hex=html_rec['body_sha256'],
             retrieved_at='2026-10-01T00:00:00Z', http_status=200, outcome='stored', fetch_http_status=200, fetch_outcome='stored'),
    ]

    def inp(name, rows, **fields):
        return json_input(tmp_path, name, rows, **fields)

    inputs = [
        qual_inp,
        inp('recovery_requirements', requirements, original_url='Utf8', target_requirement='Utf8', acceptance_policy='Utf8', refresh_policy='Utf8'),
        inp('recovery_decisions', [], **{**{k: 'Utf8' for k in ('id', 'original_url', 'body_sha256', 'kind', 'target_requirement', 'acceptance_policy', 'acceptance_status', 'evidence_sha256', 'qualification_sha256', 'supersedes')}, 'recovery_record_version': 'Int32'}),
        inp('raw_captures', capture_rows, receipt_key='Utf8', receipt_line='Int32', capture_index='Int32', mode='Utf8',
            complete='Boolean', attempt='Int32', member_path='Utf8', requested_url='Utf8', original_url='Utf8',
            body_hex='Utf8', retrieved_at='Utf8', http_status='Int32', outcome='Utf8', fetch_http_status='Int32', fetch_outcome='Utf8'),
        inp('url_state_history', [dict(requested_url=u, attempts=2 if 'corrupt' in u or u == u_fixed else 1, last_status=304 if u == u_corrupt_304 else 200) for u in all_urls],
            requested_url='Utf8', attempts='Int32', last_status='Int32'),
        inp('url_state_latest', [dict(requested_url=u, family='documents') for u in all_urls], requested_url='Utf8', family='Utf8'),
        inp('url_state_scope_exclusions', [], family='Utf8', pattern='Utf8'),
    ]
    selected_steps = [
        s for s in url_state_steps(recovery_policy=dict(acceptance_policy=policy), include_qualifications=True)
        if s['name'] in {'url_state_qualified_urls', 'url_state_latest_qualification', 'url_state'}
    ]
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as eng:
        res = run_job(
            tmp_path / 'job',
            eng,
            inputs=inputs,
            steps=[
                qual_step,
                dict(
                    name='captures',
                    sql="""SELECT * EXCLUDE(body_hex,retrieved_at),
                        CASE WHEN body_hex IS NOT NULL THEN arrow_cast(decode(body_hex,'hex'),'FixedSizeBinary(32)')
                             ELSE arrow_cast(NULL,'FixedSizeBinary(32)') END AS sha256,
                        arrow_cast(cast(retrieved_at AS TIMESTAMP WITH TIME ZONE),'Timestamp(Microsecond, Some("UTC"))') AS retrieved_at
                        FROM raw_captures""",
                ),
                *selected_steps,
            ],
            outputs=[],
            queries=[dict(name='rows', sql='SELECT requested_url,capture_disposition,capture_reason,capture_decision_id FROM url_state ORDER BY requested_url')],
        )
    got = {r['requested_url']: (r['capture_disposition'], r['capture_reason'], r['capture_decision_id']) for r in res['rows']}
    assert got[u_corrupt_304] == ('eligible', 'body_not_qualified', None)
    assert got[u_corrupt_200_unchanged] == ('eligible', 'body_not_qualified', None)
    assert got[u_fixed] == ('satisfied', 'qualified_direct_body', None)
    assert got[u_healthy_hist] == ('satisfied', 'qualified_direct_body', None)
    assert got[u_healthy_live] == ('eligible', 'no_satisfying_recovery', None)
    assert got[u_pdf_got_html] == ('eligible', 'body_not_qualified', None)


def test_real_model_spec_supports_pinned_body_qualifications(tmp_path):
    import json
    import pyarrow as pa
    import pyarrow.parquet as pq
    from archive_job_fixture import real_model_spec
    from congress_api.retention.provenance import file_pin
    from congress_shared.custody import verify_local_file
    from corpus_recovery.qualification import qualify
    from viewer_publication.archive_model_job import execute, validate_spec

    spec, _, _ = real_model_spec(tmp_path)
    bad = tmp_path / 'bad.pdf'
    bad.write_bytes(b'%PDF-1.7\ntruncated')
    rec = qualify(verify_local_file(bad), tmp_path / 'qcache')
    quals_path = tmp_path / 'qualifications.jsonl'
    quals_path.write_text(json.dumps(dict(rec)) + '\n')

    requirements = tmp_path / 'requirements.parquet'
    pq.write_table(
        pa.table({
            'original_url': ['https://fixture.test/report.html'],
            'target_requirement': ['historical_exact'],
            'acceptance_policy': ['recovery-identity-v1'],
            'refresh_policy': ['historical_only'],
        }),
        requirements,
    )
    spec['recovery_requirements'] = dict(path=str(requirements), **file_pin(requirements), acceptance_policy='recovery-identity-v1')
    spec['body_qualifications'] = dict(path=str(quals_path), **file_pin(quals_path))
    validated = validate_spec(spec, base=tmp_path)
    execute(validated)
    profile = json.loads((tmp_path / 'model/profile.json').read_text())
    assert profile['profile']['body_qualifications'] == {
        'sha256': file_pin(quals_path)['sha256'],
        'size': file_pin(quals_path)['size'],
    }

