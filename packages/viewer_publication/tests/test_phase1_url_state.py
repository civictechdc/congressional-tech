"""Phase-one scheduling reads line facts once and discovers public queue URLs."""
import os
from pathlib import Path

import pytest
from congress_api.retention.provenance import json_input,run_job
from docspec_client.client import NativeDatasets
from viewer_publication.archive_model import registry_inputs

ROOT=Path(__file__).parents[3]
BASE='https://docs.house.gov/meetings/AG/AG03/20261101/123/'


def run_state(tmp_path,change=None):
    from viewer_publication.archive_url_state import url_state_steps,url_state_diagnostics
    def row(line,requested,**extra):
        return dict(dict(receipt_key='r',receipt_line=line,capture_index=0,mode='fetch',requested_url=requested,
            url=requested,context_url=requested,member_path=None,family='documents',retrieved_at='2026-11-20T12:00:00Z',
            http_status=200,outcome='stored',complete=True,body_hex='a'*64,record_role='document'),**extra)
    url=BASE+'report.pdf'
    rows=[row(1,url,retrieved_at='2026-11-01T12:00:00Z'),
          row(1,url,capture_index=1,retrieved_at='2026-11-01T12:00:00Z'),
          row(2,url,retrieved_at='2026-11-10T12:00:00Z',outcome='size_limit',complete=False),
          row(3,url,http_status=503,outcome='request_failed',complete=False),
          row(4,BASE+'wrapper.html',body_hex='b'*64,record_role='wrapper'),
          row(5,BASE+'error.html',body_hex='c'*64,record_role='error_response'),
          row(6,BASE+'redirect',url=BASE+'redirected.pdf'),
          row(7,'https://unknown-date.test/a'),
          row(8,BASE+'undated.pdf',retrieved_at=None),
          row(9,'https://docs.house.gov/meetings/AG/AG03/20200101/456/old.pdf'),
          row(10,BASE+'retained.pdf',mode='retained_import'),
          row(11,BASE+'tie.pdf',receipt_key='a'),row(11,BASE+'tie.pdf',receipt_key='z',http_status=500,outcome='request_failed')]
    targets=[(BASE+'new.pdf?token=example&x=1',None,'b'*64),
             (BASE+'new.pdf?token=example&x=1',None,'b'*64),
             (url,None,'b'*64),(BASE+'redirected.pdf',None,'b'*64),
             ('https://outside.test/a.pdf',None,'b'*64),(BASE+'asset.css',None,'b'*64),
             (BASE+'member.pdf','folder/member.pdf','b'*64),(BASE+'error-only.pdf',None,'c'*64),
             (BASE+'caption.vtt?key=constant',None,'b'*64)]
    if change=='non_acquisition':
        rows += [row(12,url,outcome='reference',body_hex=None,http_status=None,family='record-only',retrieved_at='2026-11-21T00:00:00Z'),
                 row(13,url,outcome='saved-record',body_hex=None,http_status=None,family='record-only',retrieved_at='2026-11-22T00:00:00Z')]
    if change=='unknown_family':rows[3]['family']='not-registered'
    if change=='line_conflict':rows[1]['http_status']=503
    if change=='entry_facts':
        rows[0]['complete']=False
        rows[1]['retrieved_at']='2026-11-01T13:00:00Z'
    if change=='batched_urls':
        rows[1]['requested_url']=BASE+'second-report.pdf'
        rows[1]['url']=rows[1]['requested_url']
    if change=='collision':targets.append((url+'?api_key=example',None,'b'*64))
    links=[dict(target_url=target,target_member_path=member,page_body=body,
        context_url=BASE+('error.html' if body=='c'*64 else 'wrapper.html'),member_path=None) for target,member,body in targets]
    inputs=registry_inputs(tmp_path/'registries')
    inputs.append(json_input(tmp_path,'fixture_captures',rows,receipt_key='Utf8',receipt_line='Int32',capture_index='Int32',
        mode='Utf8',requested_url='Utf8',url='Utf8',context_url='Utf8',member_path='Utf8',family='Utf8',retrieved_at='Utf8',
        http_status='Int32',outcome='Utf8',complete='Boolean',body_hex='Utf8',record_role='Utf8'))
    inputs.append(json_input(tmp_path,'resolved_links',links,target_url='Utf8',target_member_path='Utf8',page_body='Utf8',context_url='Utf8',member_path='Utf8'))
    inputs.append(json_input(tmp_path,'url_state_meeting_dates',[dict(requested_url=url,meeting_date='2026-10-10')],requested_url='Utf8',meeting_date='Utf8'))
    inputs.append(json_input(tmp_path,'url_variants',[],canonical_url='Utf8',variant_url='Utf8'))
    steps=[dict(name='captures',sql="SELECT * EXCLUDE(body_hex,record_role,retrieved_at),decode(body_hex,'hex') AS sha256,arrow_cast(cast(retrieved_at AS TIMESTAMP WITH TIME ZONE),'Timestamp(Microsecond, Some(\"UTC\"))') AS retrieved_at FROM fixture_captures"),
        dict(name='record_roles',sql='SELECT receipt_key,receipt_line,capture_index,record_role FROM fixture_captures'),
        dict(name='capture_evidence',sql='SELECT * FROM captures'),
        dict(name='good_fetches',sql=(ROOT/'model/sql/good-fetches.sql').read_text()),
        dict(name='url_inputs',sql="SELECT DISTINCT encode(sha256(json_array(url)),'hex') AS input_id,url FROM (SELECT requested_url AS url FROM captures UNION SELECT url FROM captures UNION SELECT target_url AS url FROM resolved_links) WHERE url IS NOT NULL"),
        dict(name='url_normalized',sql=(ROOT/'model/sql/url-normalized.sql').read_text(),materialize=True),
        dict(name='model_url_keys',sql=(ROOT/'model/sql/url-keys.sql').read_text(),materialize=True)]
    return run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=steps+url_state_steps(),outputs=[],queries=[*url_state_diagnostics(),
            dict(name='state',sql='SELECT requested_url,attempts,last_status,last_outcome,cast(last_attempt AS VARCHAR) AS last_attempt,cast(last_good_at AS VARCHAR) AS last_good_at,cast(next_attempt_at AS VARCHAR) AS next_attempt_at FROM url_state ORDER BY requested_url')])


def test_url_state_line_grain_bands_and_clean_scoped_queue(tmp_path):
    result=run_state(tmp_path)
    assert not any(result['url_state_invariants'][0].values())
    states={r['requested_url']:r for r in result['state']}
    report=states[BASE+'report.pdf']
    assert report['attempts']==3 and report['last_status']==503 and report['last_outcome']=='request_failed'
    assert report['last_good_at'].startswith('2026-11-01') and report['next_attempt_at'].startswith('2026-12-18')
    assert states[BASE+'undated.pdf']['next_attempt_at'] is None
    assert states['https://unknown-date.test/a']['next_attempt_at'].startswith('2026-11-27')
    assert states['https://docs.house.gov/meetings/AG/AG03/20200101/456/old.pdf']['next_attempt_at'].startswith('2027-11-20')
    assert states[BASE+'tie.pdf']['last_status']==500 and states[BASE+'tie.pdf']['attempts']==2
    queued=[r for r in result['state'] if r['attempts']==0]
    assert [r['requested_url'] for r in queued]==[BASE+'caption.vtt?key=constant',BASE+'new.pdf?x=1']
    assert all(r['last_attempt'] is None and r['next_attempt_at'] is None for r in queued)
    assert BASE+'retained.pdf' not in states


@pytest.mark.parametrize(('change','field'),[('unknown_family','unknown_families'),('line_conflict','conflicting_lines'),('collision','sanitization_collisions')])
def test_url_state_reports_build_blocking_input_errors(tmp_path,change,field):
    result=run_state(tmp_path,change)
    assert result['url_state_invariants'][0][field]>0
    if change=='unknown_family':
        row=next(r for r in result['state'] if r['requested_url']==BASE+'report.pdf')
        assert row['next_attempt_at'] is None


@pytest.mark.parametrize('shape',['entry_facts','batched_urls'])
def test_url_state_keeps_per_entry_facts_and_each_requested_address(tmp_path,shape):
    result=run_state(tmp_path,shape)
    assert not any(result['url_state_invariants'][0].values())
    states={r['requested_url']:r for r in result['state']}
    assert states[BASE+'report.pdf']['attempts']==3
    if shape=='entry_facts':
        assert states[BASE+'report.pdf']['last_good_at'].startswith('2026-11-01T13:00:00')
    else:
        assert states[BASE+'second-report.pdf']['attempts']==1


def test_references_and_inline_records_cannot_shadow_a_real_fetch(tmp_path):
    result=run_state(tmp_path,'non_acquisition')
    assert not any(result['url_state_invariants'][0].values())
    [row]=[r for r in result['state'] if r['requested_url']==BASE+'report.pdf']
    assert row['attempts']==3 and row['last_status']==503 and row['last_outcome']=='request_failed'
