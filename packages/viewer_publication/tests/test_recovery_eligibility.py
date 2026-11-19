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
    """ct-zohj: HTTP-200 failed-qualification bodies stay eligible (body_not_qualified) across 304 and
    validator_unchanged receipts. A readable body never settles identity, so healthy targets keep their
    ordinary reason under both refresh policies (review 7). A PDF is expected from either spelling or
    the captured media type, as at capture time; with no qualification facts the output is unchanged."""
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
    u_typed_pdf_got_html = 'https://example.test/download?id=7'
    u_html_statement = 'https://example.test/statement?id=8'
    all_urls = [u_corrupt_304, u_corrupt_200_unchanged, u_fixed, u_healthy_hist, u_healthy_live, u_pdf_got_html,
                u_typed_pdf_got_html, u_html_statement]

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
        # 7. Extensionless URL answered with Content-Type application/pdf but an HTML body
        dict(receipt_key='r10', receipt_line=1, capture_index=0, mode='fetch', complete=True, attempt=0,
             member_path=None, requested_url=u_typed_pdf_got_html, original_url=None, body_hex=html_rec['body_sha256'],
             retrieved_at='2026-10-01T00:00:00Z', http_status=200, outcome='stored', fetch_http_status=200, fetch_outcome='stored',
             media_type='application/pdf'),
        # 8. Extensionless HTML statement page answered as text/html
        dict(receipt_key='r11', receipt_line=1, capture_index=0, mode='fetch', complete=True, attempt=0,
             member_path=None, requested_url=u_html_statement, original_url=None, body_hex=html_rec['body_sha256'],
             retrieved_at='2026-10-01T00:00:00Z', http_status=200, outcome='stored', fetch_http_status=200, fetch_outcome='stored',
             media_type='text/html'),
    ]
    for row in capture_rows:
        row.setdefault('url', row['requested_url'])
        row.setdefault('media_type', 'text/html' if row['body_hex'] == html_rec['body_sha256'] else 'application/pdf')

    def inp(name, rows, **fields):
        return json_input(tmp_path, name, rows, **fields)

    inputs = [
        qual_inp,
        inp('recovery_requirements', requirements, original_url='Utf8', target_requirement='Utf8', acceptance_policy='Utf8', refresh_policy='Utf8'),
        inp('recovery_decisions', [], **{**{k: 'Utf8' for k in ('id', 'original_url', 'body_sha256', 'kind', 'target_requirement', 'acceptance_policy', 'acceptance_status', 'evidence_sha256', 'qualification_sha256', 'supersedes')}, 'recovery_record_version': 'Int32'}),
        inp('raw_captures', capture_rows, receipt_key='Utf8', receipt_line='Int32', capture_index='Int32', mode='Utf8',
            complete='Boolean', attempt='Int32', member_path='Utf8', requested_url='Utf8', original_url='Utf8',
            body_hex='Utf8', retrieved_at='Utf8', http_status='Int32', outcome='Utf8', fetch_http_status='Int32', fetch_outcome='Utf8',
            url='Utf8', media_type='Utf8'),
        inp('url_state_history', [dict(requested_url=u, attempts=2 if 'corrupt' in u or u == u_fixed else 1, last_status=304 if u == u_corrupt_304 else 200) for u in all_urls],
            requested_url='Utf8', attempts='Int32', last_status='Int32'),
        inp('url_state_latest', [dict(requested_url=u, family='documents') for u in all_urls], requested_url='Utf8', family='Utf8'),
        inp('url_state_scope_exclusions', [], family='Utf8', pattern='Utf8'),
    ]
    captures_step = dict(
        name='captures',
        sql="""SELECT * EXCLUDE(body_hex,retrieved_at),
            CASE WHEN body_hex IS NOT NULL THEN arrow_cast(decode(body_hex,'hex'),'FixedSizeBinary(32)')
                 ELSE arrow_cast(NULL,'FixedSizeBinary(32)') END AS sha256,
            arrow_cast(cast(retrieved_at AS TIMESTAMP WITH TIME ZONE),'Timestamp(Microsecond, Some("UTC"))') AS retrieved_at
            FROM raw_captures""",
    )
    rows_query = [dict(name='rows', sql='SELECT * FROM url_state ORDER BY requested_url')]

    def state_rows(name, quals, include):
        q_inp, q_step = model_qualification_input(quals, tmp_path / f'quals-{name}')
        selected = [
            s for s in url_state_steps(recovery_policy=dict(acceptance_policy=policy), include_qualifications=include)
            if s['name'] in {'url_state_qualified_urls', 'url_state_latest_qualification', 'url_state'}
        ]
        with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as eng:
            return run_job(tmp_path / name, eng, inputs=[q_inp, *inputs[1:]],
                           steps=[q_step, captures_step, *selected], outputs=[], queries=rows_query)['rows']

    got = {r['requested_url']: (r['capture_disposition'], r['capture_reason'], r['capture_decision_id'])
           for r in state_rows('job', [corrupt_rec, good_rec, html_rec], True)}
    assert got[u_corrupt_304] == ('eligible', 'body_not_qualified', None)
    assert got[u_corrupt_200_unchanged] == ('eligible', 'body_not_qualified', None)
    assert got[u_fixed] == ('eligible', 'no_satisfying_recovery', None)
    assert got[u_healthy_hist] == ('eligible', 'no_satisfying_recovery', None)
    assert got[u_healthy_live] == ('eligible', 'no_satisfying_recovery', None)
    assert got[u_pdf_got_html] == ('eligible', 'body_not_qualified', None)
    assert got[u_typed_pdf_got_html] == ('eligible', 'body_not_qualified', None)
    assert got[u_html_statement] == ('eligible', 'no_satisfying_recovery', None)
    # Empty-input parity: with no qualification facts the model output equals the old step's.
    assert state_rows('empty', [], True) == state_rows('without', [], False)


def test_body_less_unchanged_recheck_is_not_a_good_fetch(tmp_path):
    """Review 7: the shared good-fetch predicate (url_state last_good_at and the release gate's
    url_state_proof both read it) counts a stored body, not a body-less 200/304 'unchanged' recheck.
    Legacy 'unchanged' rows that carry a body keep counting."""
    from congress_api.lake.model_sql import model_steps

    rows = [
        dict(key='stored', status=200, outcome='stored', body='a' * 64),
        dict(key='legacy-unchanged-with-body', status=200, outcome='unchanged', body='b' * 64),
        dict(key='bodyless-200-unchanged', status=200, outcome='unchanged', body=None),
        dict(key='bodyless-304-unchanged', status=304, outcome='unchanged', body=None),
    ]
    inputs = [json_input(tmp_path, 'raw', rows, key='Utf8', status='Int32', outcome='Utf8', body='Utf8')]
    evidence = dict(name='capture_evidence', sql="""SELECT key AS receipt_key,1 AS receipt_line,0 AS capture_index,
        'fetch' AS mode,true AS complete,outcome,status AS http_status,cast(NULL AS VARCHAR) AS member_path,
        cast(NULL AS VARCHAR) AS expansion,cast(NULL AS VARCHAR) AS context_url,
        CASE WHEN body IS NULL THEN arrow_cast(NULL,'FixedSizeBinary(32)')
             ELSE arrow_cast(decode(body,'hex'),'FixedSizeBinary(32)') END AS sha256 FROM raw""")
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as eng:
        result = run_job(tmp_path / 'job', eng, inputs=inputs,
                         steps=[evidence, *model_steps(['good-fetches'], provided=['capture_evidence'])], outputs=[],
                         queries=[dict(name='good', sql='SELECT receipt_key FROM good_fetches ORDER BY receipt_key')])
    assert [r['receipt_key'] for r in result['good']] == ['legacy-unchanged-with-body', 'stored']


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
    # Physical qualification input selectors stay in snapshots, outside semantic profile_sha256.
    assert 'body_qualifications' not in profile['profile']
    assert profile['snapshots']['body_qualifications'] == {
        'sha256': file_pin(quals_path)['sha256'],
        'size': file_pin(quals_path)['size'],
    }


def test_release_gate_url_state_proof_admits_verified_qualification_reason_and_refuses_unproven(tmp_path):
    """url_state_proof admits qualification-driven capture_reason changes only with verified facts."""
    import gzip
    import hashlib
    import io
    import json
    from datetime import datetime, timedelta, timezone
    import pyarrow as pa
    from pypdf import PdfWriter
    from congress_api.retention.qualification_facts import build_qualification_fact
    from congress_shared.custody import verify_local_file
    from corpus_recovery.qualification import qualify
    from viewer_publication.release_gate import automatic_causes, require_release_gates
    from test_release_gate import DAY, FETCHED, LIVE, LIVE_RECEIPTS, NEW_RECEIPT, T0, URL_STATE, release_dir, state, write_captures

    bad_pdf = b'%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\ntruncated'
    pdf_writer = PdfWriter()
    pdf_writer.add_blank_page(width=72, height=72)
    pdf_buf = io.BytesIO()
    pdf_writer.write(pdf_buf)
    good_pdf = pdf_buf.getvalue()
    bad_file = tmp_path / 'bad.pdf'
    good_file = tmp_path / 'good.pdf'
    bad_file.write_bytes(bad_pdf)
    good_file.write_bytes(good_pdf)
    q_cache = tmp_path / 'qcache'
    bad_rec = qualify(verify_local_file(bad_file), q_cache)
    good_rec = qualify(verify_local_file(good_file), q_cache)
    bad_sha = bytes.fromhex(hashlib.sha256(bad_pdf).hexdigest())
    good_sha = bytes.fromhex(hashlib.sha256(good_pdf).hexdigest())

    u_newly_bad = 'https://docs.house.gov/meetings/FA/FA00/20261001/119001/HHRG-newly-bad.pdf'
    u_fixed = 'https://docs.house.gov/meetings/FA/FA00/20261001/119001/HHRG-fixed.pdf'
    u_unchanged = 'https://docs.house.gov/meetings/FA/FA00/20261001/119001/HHRG-unchanged.pdf'
    meeting = datetime(2026, 10, 20).date()

    def build_table(rows, reasons):
        tbl = pa.Table.from_pylist(sorted(rows.values(), key=lambda r: r['requested_url']), schema=URL_STATE)
        urls = tbl['requested_url'].to_pylist()
        tbl = tbl.append_column('capture_disposition', pa.array(['eligible'] * len(urls), pa.string()))
        tbl = tbl.append_column('capture_reason', pa.array([reasons[u] for u in urls], pa.string()))
        tbl = tbl.append_column('capture_decision_id', pa.array([None] * len(urls), pa.string()))
        return tbl

    base_rows = {
        u_newly_bad: state(u_newly_bad, 1, T0, 500, 'failed', None, 7 * DAY, meeting),
        u_fixed: state(u_fixed, 1, T0, 200, 'stored', T0, 7 * DAY, meeting),
        u_unchanged: state(u_unchanged, 1, T0, 200, 'stored', T0, 7 * DAY, meeting),
    }
    base_reasons = {
        u_newly_bad: 'no_satisfying_recovery',
        u_fixed: 'body_not_qualified',
        u_unchanged: 'body_not_qualified',
    }
    cand_rows = {
        u_newly_bad: state(u_newly_bad, 2, FETCHED, 200, 'stored', FETCHED, 7 * DAY, meeting),
        u_fixed: state(u_fixed, 2, FETCHED, 200, 'stored', FETCHED, 7 * DAY, meeting),
        # Body-less 200/unchanged recheck advances schedule/attempt, NOT last_good_at (remains T0)!
        u_unchanged: state(u_unchanged, 2, FETCHED, 200, 'unchanged', T0, 7 * DAY, meeting),
    }
    cand_reasons = {
        u_newly_bad: 'body_not_qualified',
        u_fixed: 'no_satisfying_recovery',
        u_unchanged: 'body_not_qualified',
    }
    release_dir(tmp_path / 'base', ['A'], url_state=build_table(base_rows, base_reasons))
    release_dir(tmp_path / 'cand', ['A'], url_state=build_table(cand_rows, cand_reasons))

    bad_pdf_fixed = b'%PDF-1.7\n11 0 obj\n<< /Type /Catalog >>\ntruncated-fixed'
    bad_pdf_unchanged = b'%PDF-1.7\n12 0 obj\n<< /Type /Catalog >>\ntruncated-unchanged'
    bad_file_fixed = tmp_path / 'bad-fixed.pdf'
    bad_file_unchanged = tmp_path / 'bad-unchanged.pdf'
    bad_file_fixed.write_bytes(bad_pdf_fixed)
    bad_file_unchanged.write_bytes(bad_pdf_unchanged)
    bad_rec_fixed = qualify(verify_local_file(bad_file_fixed), q_cache)
    bad_rec_unchanged = qualify(verify_local_file(bad_file_unchanged), q_cache)
    bad_sha_fixed = bytes.fromhex(hashlib.sha256(bad_pdf_fixed).hexdigest())
    bad_sha_unchanged = bytes.fromhex(hashlib.sha256(bad_pdf_unchanged).hexdigest())

    cap_rows = [
        dict(mode='fetch', complete=True, attempt=0, http_status=500, receipt_key=LIVE, receipt_line=1,
             requested_url=u_newly_bad, sha256=None, retrieved_at=T0, outcome='failed'),
        dict(mode='fetch', complete=True, attempt=0, http_status=200, receipt_key=LIVE, receipt_line=2,
             requested_url=u_fixed, sha256=bad_sha_fixed, retrieved_at=T0, outcome='stored'),
        dict(mode='fetch', complete=True, attempt=0, http_status=200, receipt_key=LIVE, receipt_line=3,
             requested_url=u_unchanged, sha256=bad_sha_unchanged, retrieved_at=T0, outcome='stored'),
        dict(mode='fetch', complete=True, attempt=0, http_status=200, receipt_key=NEW_RECEIPT, receipt_line=1,
             requested_url=u_newly_bad, sha256=bad_sha, retrieved_at=FETCHED, outcome='stored'),
        dict(mode='fetch', complete=True, attempt=0, http_status=200, receipt_key=NEW_RECEIPT, receipt_line=2,
             requested_url=u_fixed, sha256=good_sha, retrieved_at=FETCHED, outcome='stored'),
        dict(mode='fetch', complete=True, attempt=0, http_status=200, receipt_key=NEW_RECEIPT, receipt_line=3,
             requested_url=u_unchanged, sha256=None, retrieved_at=FETCHED, outcome='unchanged'),
    ]
    write_captures(cap_rows, tmp_path / 'captures.parquet')
    text = {}
    for row in cap_rows:
        body = [dict(sha256=row['sha256'].hex())] if row.get('sha256') else []
        text.setdefault(row['receipt_key'], {})[row['receipt_line']] = json.dumps(dict(
            record=dict(mode='fetch', requested_url=row['requested_url'], outcome=row['outcome']), captures=body))
    blobs = {k: gzip.compress(('\n'.join(v[i] for i in sorted(v)) + '\n').encode(), mtime=0) for k, v in text.items()}

    q_file = tmp_path / 'provenance-quals.jsonl'
    q_file.write_text(
        json.dumps(build_qualification_fact(bad_rec, requested_url=u_newly_bad, url=u_newly_bad,
                                            receipt_key=NEW_RECEIPT, retrieved_at=FETCHED.isoformat(),
                                            http_status=200, headers={'Content-Type': 'application/pdf'})) + '\n'
        + json.dumps(build_qualification_fact(bad_rec_fixed, requested_url=u_fixed, url=u_fixed,
                                              receipt_key=LIVE, retrieved_at=T0.isoformat(),
                                              http_status=200, headers={'Content-Type': 'application/pdf'})) + '\n'
        + json.dumps(build_qualification_fact(bad_rec_unchanged, requested_url=u_unchanged, url=u_unchanged,
                                              receipt_key=LIVE, retrieved_at=T0.isoformat(),
                                              http_status=200, headers={'Content-Type': 'application/pdf'})) + '\n'
        + json.dumps(build_qualification_fact(good_rec, requested_url=u_fixed, url=u_fixed,
                                              receipt_key=NEW_RECEIPT, retrieved_at=FETCHED.isoformat(),
                                              http_status=200, headers={'Content-Type': 'application/pdf'})) + '\n'
    )

    import os
    from docspec_client.client import NativeDatasets

    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as eng:
        # 1. With verified qualification facts, capture_reason transitions + body-less 200 unchanged PASS.
        passed = require_release_gates(
            tmp_path / 'base', tmp_path / 'cand', None, report_path=tmp_path / 'pass.json',
            automatic=lambda rep: automatic_causes(
                rep, tmp_path / 'base', tmp_path / 'cand', engine=eng,
                captures=dict(kind='parquet', path=str(tmp_path / 'captures.parquet')),
                live_receipt_keys=LIVE_RECEIPTS, read_receipt=blobs.__getitem__,
                work=tmp_path / 'auto-pass', candidate_receipt_keys=LIVE_RECEIPTS | {NEW_RECEIPT},
                qualification_files=[dict(key='provenance/qualifications/test.jsonl', path=str(q_file))],
            ),
        )
        assert passed['reasons'] == [] and passed['automatic_reasons'] == []

        # 2. Without qualification facts, changed capture_reason MUST refuse.
        with pytest.raises(ValueError, match='capture_reason is not implied by verified body qualifications'):
            require_release_gates(
                tmp_path / 'base', tmp_path / 'cand', None, report_path=tmp_path / 'fail-no-q.json',
                automatic=lambda rep: automatic_causes(
                    rep, tmp_path / 'base', tmp_path / 'cand', engine=eng,
                    captures=dict(kind='parquet', path=str(tmp_path / 'captures.parquet')),
                    live_receipt_keys=LIVE_RECEIPTS, read_receipt=blobs.__getitem__,
                    work=tmp_path / 'auto-fail-no-q', candidate_receipt_keys=LIVE_RECEIPTS | {NEW_RECEIPT},
                ),
            )

        # 3. Planted fault: moving capture_reason to 'qualified_recovery' refuses even with qualification files.
        bad_cand_reasons = dict(cand_reasons, **{u_fixed: 'qualified_recovery'})
        release_dir(tmp_path / 'cand-forged', ['A'], url_state=build_table(cand_rows, bad_cand_reasons))
        with pytest.raises(ValueError, match='capture_reason is not implied by verified body qualifications'):
            require_release_gates(
                tmp_path / 'base', tmp_path / 'cand-forged', None, report_path=tmp_path / 'fail-forged.json',
                automatic=lambda rep: automatic_causes(
                    rep, tmp_path / 'base', tmp_path / 'cand-forged', engine=eng,
                    captures=dict(kind='parquet', path=str(tmp_path / 'captures.parquet')),
                    live_receipt_keys=LIVE_RECEIPTS, read_receipt=blobs.__getitem__,
                    work=tmp_path / 'auto-fail-forged', candidate_receipt_keys=LIVE_RECEIPTS | {NEW_RECEIPT},
                    qualification_files=[dict(key='provenance/qualifications/test.jsonl', path=str(q_file))],
                ),
            )

        # 4. Review 7b: supplying a qualification file that lacks a row for u_unchanged MUST refuse
        # clearing body_not_qualified -> no_satisfying_recovery on its body-less unchanged recheck.
        q_partial = tmp_path / 'provenance-quals-partial.jsonl'
        q_partial.write_text(
            json.dumps(build_qualification_fact(bad_rec, requested_url=u_newly_bad, url=u_newly_bad,
                                                receipt_key=NEW_RECEIPT, retrieved_at=FETCHED.isoformat(),
                                                http_status=200, headers={'Content-Type': 'application/pdf'})) + '\n'
            + json.dumps(build_qualification_fact(good_rec, requested_url=u_fixed, url=u_fixed,
                                                  receipt_key=NEW_RECEIPT, retrieved_at=FETCHED.isoformat(),
                                                  http_status=200, headers={'Content-Type': 'application/pdf'})) + '\n'
        )
        unproven_clear_reasons = dict(cand_reasons, **{u_unchanged: 'no_satisfying_recovery'})
        release_dir(tmp_path / 'cand-unproven-clear', ['A'], url_state=build_table(cand_rows, unproven_clear_reasons))
        with pytest.raises(ValueError, match='capture_reason is not implied by verified body qualifications'):
            require_release_gates(
                tmp_path / 'base', tmp_path / 'cand-unproven-clear', None, report_path=tmp_path / 'fail-missing-row.json',
                automatic=lambda rep: automatic_causes(
                    rep, tmp_path / 'base', tmp_path / 'cand-unproven-clear', engine=eng,
                    captures=dict(kind='parquet', path=str(tmp_path / 'captures.parquet')),
                    live_receipt_keys=LIVE_RECEIPTS, read_receipt=blobs.__getitem__,
                    work=tmp_path / 'auto-fail-missing-row', candidate_receipt_keys=LIVE_RECEIPTS | {NEW_RECEIPT},
                    qualification_files=[dict(key='provenance/qualifications/partial.jsonl', path=str(q_partial))],
                ),
            )

        # 5. Review 7b: added URLs also enforce capture_reason against verified qualifications.
        u_added = 'https://fixture.test/added-bad.pdf'
        bad_pdf_added = b'%PDF-1.7\n2 0 obj\n<< /Type /Catalog >>\ntruncated-added'
        bad_file_added = tmp_path / 'bad-added.pdf'
        bad_file_added.write_bytes(bad_pdf_added)
        bad_rec_added = qualify(verify_local_file(bad_file_added), q_cache)
        bad_sha_added = bytes.fromhex(hashlib.sha256(bad_pdf_added).hexdigest())
        added_cap_rows = [*cap_rows, dict(mode='fetch', complete=True, attempt=0, http_status=200,
                                          receipt_key=NEW_RECEIPT, receipt_line=4, requested_url=u_added,
                                          sha256=bad_sha_added, retrieved_at=FETCHED, outcome='stored')]
        write_captures(added_cap_rows, tmp_path / 'captures-added.parquet')
        added_text = {}
        for row in added_cap_rows:
            body = [dict(sha256=row['sha256'].hex())] if row.get('sha256') else []
            added_text.setdefault(row['receipt_key'], {})[row['receipt_line']] = json.dumps(dict(
                record=dict(mode='fetch', requested_url=row['requested_url'], outcome=row['outcome']), captures=body))
        added_blobs = {k: gzip.compress(('\n'.join(v[i] for i in sorted(v)) + '\n').encode(), mtime=0) for k, v in added_text.items()}
        added_cand_rows = dict(cand_rows, **{u_added: state(u_added, 1, FETCHED, 200, 'stored', FETCHED, 7 * DAY, meeting)})
        added_cand_reasons = dict(cand_reasons, **{u_added: 'body_not_qualified'})
        release_dir(tmp_path / 'cand-added-bad', ['A'], url_state=build_table(added_cand_rows, added_cand_reasons))
        # Without a failed qualification record for bad_sha_added (q_file only covers bad_sha and good_sha), added body_not_qualified refuses:
        with pytest.raises(ValueError, match='capture_reason is not implied by verified body qualifications'):
            require_release_gates(
                tmp_path / 'base', tmp_path / 'cand-added-bad', None, report_path=tmp_path / 'fail-added.json',
                automatic=lambda rep: automatic_causes(
                    rep, tmp_path / 'base', tmp_path / 'cand-added-bad', engine=eng,
                    captures=dict(kind='parquet', path=str(tmp_path / 'captures-added.parquet')),
                    live_receipt_keys=LIVE_RECEIPTS, read_receipt=added_blobs.__getitem__,
                    work=tmp_path / 'auto-fail-added', candidate_receipt_keys=LIVE_RECEIPTS | {NEW_RECEIPT},
                    qualification_files=[dict(key='provenance/qualifications/test.jsonl', path=str(q_file))],
                ),
            )
        # With verified failed qualification for u_added included, added body_not_qualified passes:
        q_with_added = tmp_path / 'quals-with-added.jsonl'
        q_with_added.write_text(
            q_file.read_text()
            + json.dumps(build_qualification_fact(bad_rec_added, requested_url=u_added, url=u_added,
                                                  receipt_key=NEW_RECEIPT, retrieved_at=FETCHED.isoformat(),
                                                  http_status=200, headers={'Content-Type': 'application/pdf'})) + '\n'
        )
        passed_added = require_release_gates(
            tmp_path / 'base', tmp_path / 'cand-added-bad', None, report_path=tmp_path / 'pass-added.json',
            automatic=lambda rep: automatic_causes(
                rep, tmp_path / 'base', tmp_path / 'cand-added-bad', engine=eng,
                captures=dict(kind='parquet', path=str(tmp_path / 'captures-added.parquet')),
                live_receipt_keys=LIVE_RECEIPTS, read_receipt=added_blobs.__getitem__,
                work=tmp_path / 'auto-pass-added', candidate_receipt_keys=LIVE_RECEIPTS | {NEW_RECEIPT},
                qualification_files=[dict(key='provenance/qualifications/with-added.jsonl', path=str(q_with_added))],
            ),
        )
        assert passed_added['reasons'] == [] and passed_added['automatic_reasons'] == []

        # 5b. Review 7c: reverse check on added URL — labeling a failed added PDF as 'no_satisfying_recovery' refuses!
        hidden_added_reasons = dict(cand_reasons, **{u_added: 'no_satisfying_recovery'})
        release_dir(tmp_path / 'cand-added-hidden', ['A'], url_state=build_table(added_cand_rows, hidden_added_reasons))
        with pytest.raises(ValueError, match='capture_reason is not implied by verified body qualifications'):
            require_release_gates(
                tmp_path / 'base', tmp_path / 'cand-added-hidden', None, report_path=tmp_path / 'fail-added-hidden.json',
                automatic=lambda rep: automatic_causes(
                    rep, tmp_path / 'base', tmp_path / 'cand-added-hidden', engine=eng,
                    captures=dict(kind='parquet', path=str(tmp_path / 'captures-added.parquet')),
                    live_receipt_keys=LIVE_RECEIPTS, read_receipt=added_blobs.__getitem__,
                    work=tmp_path / 'auto-fail-added-hidden', candidate_receipt_keys=LIVE_RECEIPTS | {NEW_RECEIPT},
                    qualification_files=[dict(key='provenance/qualifications/with-added.jsonl', path=str(q_with_added))],
                ),
            )

        # 5c. Review 7c: a body-less 304 CANNOT clear body_not_qualified by crediting an older held qualified body!
        held_good_caps = [
            row if not (row['receipt_key'] == LIVE and row['requested_url'] == u_unchanged)
            else dict(row, sha256=good_sha)
            for row in cap_rows
        ]
        write_captures(held_good_caps, tmp_path / 'captures-held-good.parquet')
        held_good_text = {}
        for row in held_good_caps:
            body = [dict(sha256=row['sha256'].hex())] if row.get('sha256') else []
            held_good_text.setdefault(row['receipt_key'], {})[row['receipt_line']] = json.dumps(dict(
                record=dict(mode='fetch', requested_url=row['requested_url'], outcome=row['outcome']), captures=body))
        held_good_blobs = {k: gzip.compress(('\n'.join(v[i] for i in sorted(v)) + '\n').encode(), mtime=0) for k, v in held_good_text.items()}
        with pytest.raises(ValueError, match='capture_reason is not implied by verified body qualifications'):
            require_release_gates(
                tmp_path / 'base', tmp_path / 'cand-unproven-clear', None, report_path=tmp_path / 'fail-held-good-304.json',
                automatic=lambda rep: automatic_causes(
                    rep, tmp_path / 'base', tmp_path / 'cand-unproven-clear', engine=eng,
                    captures=dict(kind='parquet', path=str(tmp_path / 'captures-held-good.parquet')),
                    live_receipt_keys=LIVE_RECEIPTS, read_receipt=held_good_blobs.__getitem__,
                    work=tmp_path / 'auto-fail-held-good-304', candidate_receipt_keys=LIVE_RECEIPTS | {NEW_RECEIPT},
                    qualification_files=[dict(key='provenance/qualifications/test.jsonl', path=str(q_file))],
                ),
            )

    # 6. Review 7b: missing explicit qualification path and tampered selector pin raise, and
    # standalone body_qualifications pin participates in input_digest.
    from congress_api.retention.qualification_facts import load_qualification_facts
    from viewer_publication.archive_publish import input_digest

    with pytest.raises(FileNotFoundError):
        load_qualification_facts(tmp_path / 'absent-qualifications.jsonl')
    with pytest.raises(ValueError):
        load_qualification_facts({'path': str(q_file), 'sha256': '0' * 64, 'size': q_file.stat().st_size})

    base_digest = input_digest(receipt_keys=[LIVE], provenance=[], profile={'v': 1}, entity_digests={})
    d_pin_a = input_digest(receipt_keys=[LIVE], provenance=[], profile={'v': 1}, entity_digests={},
                           extra_pins={'body_qualifications': {'sha256': 'a' * 64, 'size': 10}})
    d_pin_b = input_digest(receipt_keys=[LIVE], provenance=[], profile={'v': 1}, entity_digests={},
                           extra_pins={'body_qualifications': {'sha256': 'b' * 64, 'size': 10}})
    assert d_pin_a != base_digest and d_pin_a != d_pin_b
    assert input_digest(receipt_keys=[LIVE], provenance=[], profile={'v': 1}, entity_digests={}, extra_pins=None) == base_digest

