"""Phase-one scheduling reads line facts once and discovers public queue URLs."""
import os
from pathlib import Path

import pytest
from congress_api.retention.provenance import json_input,run_job
from docspec_client.client import NativeDatasets
from viewer_publication.archive_model import registry_inputs

ROOT=Path(__file__).parents[3]
BASE='https://docs.house.gov/meetings/AG/AG03/20261101/123/'


def run_state(tmp_path,change=None,queries=()):
    from viewer_publication.archive_url_state import url_state_steps,url_state_diagnostics
    def row(line,requested,**extra):
        base=dict(receipt_key='r',receipt_line=line,capture_index=0,attempt=0,mode='fetch',requested_url=requested,
            url=requested,context_url=requested,member_path=None,family='documents',retrieved_at='2026-11-20T12:00:00Z',
            http_status=200,outcome='stored',complete=True,fetch_http_status=200,fetch_outcome='stored',
            body_hex='a'*64,record_role='document')
        base.update(extra)
        if 'http_status' in extra and 'fetch_http_status' not in extra:
            base['fetch_http_status']=extra['http_status']
        if 'outcome' in extra and 'fetch_outcome' not in extra:
            base['fetch_outcome']=extra['outcome']
        if base['outcome'] in ('reference','saved-record') and 'attempt' not in extra:
            base['attempt']=None
            base['fetch_http_status']=None
            base['fetch_outcome']=None
        return base
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
    if change in ('mention_reference','mention_saved-record','mention_failed'):
        outcome=change.removeprefix('mention_')
        rows.append(row(12,BASE+'mentioned.pdf',url=BASE+'mentioned-final.pdf',outcome=outcome,
            body_hex=None,http_status=404 if outcome=='failed' else None))
        targets.extend((target,None,'b'*64) for target in (BASE+'mentioned.pdf',BASE+'mentioned-final.pdf'))
    if change=='unknown_family':rows[3]['family']='not-registered'
    if change=='line_conflict':
        rows[1]['http_status']=503
        rows[1]['fetch_http_status']=503
    if change=='prior_good_final_failure':
        split_fail_url='https://www.govinfo.gov/metadata/pkg/CHRG-119shrg99999/mods.xml'
        rows.extend([
            row(15,BASE+'retry-after-good.pdf',capture_index=0,attempt=1,retrieved_at='2026-11-15T12:00:00Z',
                http_status=200,outcome='stored',complete=True,fetch_http_status=503,fetch_outcome='retry_later'),
            row(15,BASE+'retry-after-good.pdf',capture_index=1,attempt=0,retrieved_at='2026-11-15T12:00:00Z',
                http_status=503,outcome='retry_later',complete=False,fetch_http_status=503,fetch_outcome='retry_later',body_hex=None),
            row(16,BASE+'transport-after-403.pdf',capture_index=0,attempt=1,retrieved_at='2026-11-16T12:00:00Z',
                http_status=403,outcome='failed',complete=True,fetch_http_status=None,fetch_outcome='request_failed'),
            row(16,BASE+'transport-after-403.pdf',capture_index=1,attempt=0,retrieved_at='2026-11-16T12:00:00Z',
                http_status=None,outcome='request_failed',complete=False,fetch_http_status=None,fetch_outcome='request_failed',body_hex=None),
            row(17,None,url=None,context_url=split_fail_url,family='govinfo/mods',
                retrieved_at='2026-11-16T10:00:00Z',http_status=None,outcome='stored',complete=True,body_hex='f'*64),
            row(18,split_fail_url,url=split_fail_url,context_url=None,family='govinfo/mods',capture_index=0,attempt=1,
                retrieved_at='2026-11-16T12:00:00Z',http_status=403,outcome='failed',complete=True,
                fetch_http_status=200,fetch_outcome='failed',body_hex=None),
            row(18,split_fail_url,url=split_fail_url,context_url=None,family='govinfo/mods',capture_index=1,attempt=0,
                retrieved_at='2026-11-16T12:00:00Z',http_status=200,outcome='failed',complete=False,
                fetch_http_status=200,fetch_outcome='failed',body_hex=None),
        ])
    if change in ('context_202','context_200'):
        # A failed line rescued only by a stored companion context body (ct-c6b0).
        status=int(change[-3:]);ctx_url='https://www.govinfo.gov/metadata/pkg/CHRG-119shrg77777/mods.xml'
        rows.extend([
            row(19,None,url=None,context_url=ctx_url,family='govinfo/mods',
                retrieved_at='2026-11-17T10:00:00Z',http_status=None,outcome='stored',complete=True,body_hex='9'*64),
            row(20,ctx_url,url=ctx_url,context_url=None,family='govinfo/mods',retrieved_at='2026-11-17T12:00:00Z',
                http_status=status,outcome='failed',complete=True,fetch_http_status=status,fetch_outcome='failed',
                body_hex='8'*64)])
    if change=='entry_facts':
        rows[0]['complete']=False
        rows[1]['retrieved_at']='2026-11-01T13:00:00Z'
    if change=='batched_urls':
        rows[1].update(requested_url=BASE+'second-report.pdf',url=BASE+'second-report.pdf',context_url=BASE+'second-report.pdf',
            http_status=404,fetch_http_status=404,outcome='failed',fetch_outcome='failed',complete=False,body_hex=None)
    if change=='collision':targets.append((url+'?api_key=example',None,'b'*64))
    if change=='second_page':
        # A listing page links the same queued address, twice.
        rows.append(row(21,BASE+'listing.html',body_hex='a1'*32,record_role='wrapper'))
        targets += [(BASE+'new.pdf?token=example&x=1',None,'a1'*32)]*2
    if change=='split_and_migrated':
        mods_url='https://www.govinfo.gov/metadata/pkg/CHRG-119shrg62381/mods.xml'
        rows.extend([
            row(12,None,url=None,context_url=mods_url,family='govinfo/mods',
                retrieved_at='2026-09-28T10:00:00Z',http_status=None,outcome='stored',complete=True,body_hex='d'*64),
            row(13,mods_url,url=mods_url,context_url=None,family='govinfo/mods',
                retrieved_at='2026-09-28T10:00:00Z',http_status=200,outcome='failed',complete=True,body_hex=None),
            row(14,BASE+'migrated.pdf',retrieved_at='2026-09-28T11:00:00Z',
                http_status=None,outcome='stored',complete=True,body_hex='e'*64),
        ])
    pages={'c'*64:'error.html','a1'*32:'listing.html'}
    links=[dict(target_url=target,target_member_path=member,page_body=body,
        context_url=BASE+pages.get(body,'wrapper.html'),member_path=None) for target,member,body in targets]
    inputs=registry_inputs(tmp_path/'registries')
    inputs.append(json_input(tmp_path,'fixture_captures',rows,receipt_key='Utf8',receipt_line='Int32',capture_index='Int32',
        attempt='Int32',mode='Utf8',requested_url='Utf8',url='Utf8',context_url='Utf8',member_path='Utf8',family='Utf8',retrieved_at='Utf8',
        http_status='Int32',outcome='Utf8',complete='Boolean',fetch_http_status='Int32',fetch_outcome='Utf8',body_hex='Utf8',record_role='Utf8'))
    inputs.append(json_input(tmp_path,'resolved_links',links,target_url='Utf8',target_member_path='Utf8',page_body='Utf8',context_url='Utf8',member_path='Utf8'))
    inputs.append(json_input(tmp_path,'url_state_meeting_dates',[dict(requested_url=url,meeting_date='2026-10-10')],requested_url='Utf8',meeting_date='Utf8'))
    inputs.append(json_input(tmp_path,'url_variants',[],canonical_url='Utf8',variant_url='Utf8'))
    steps=[dict(name='captures',sql="SELECT * EXCLUDE(body_hex,record_role,retrieved_at),cast(NULL AS VARCHAR) AS expansion,decode(body_hex,'hex') AS sha256,arrow_cast(cast(retrieved_at AS TIMESTAMP WITH TIME ZONE),'Timestamp(Microsecond, Some(\"UTC\"))') AS retrieved_at FROM fixture_captures"),
        dict(name='record_roles',sql='SELECT receipt_key,receipt_line,capture_index,record_role FROM fixture_captures'),
        dict(name='capture_evidence',sql='SELECT * FROM captures'),
        dict(name='good_archive_containers',sql=(ROOT/'model/sql/good-archive-containers.sql').read_text()),
        dict(name='good_fetches',sql=(ROOT/'model/sql/good-fetches.sql').read_text()),
        dict(name='good_fetch_contexts',sql="SELECT receipt_key,receipt_line,capture_index,sha256,context_url,member_path FROM good_fetches"),
        dict(name='resolved_link_targets',sql="SELECT DISTINCT page_body,context_url,member_path,target_url,cast(NULL AS VARCHAR) AS target_member_path FROM resolved_links WHERE target_member_path IS NULL"),
        dict(name='url_inputs',sql="SELECT DISTINCT encode(sha256(json_array(url)),'hex') AS input_id,url FROM (SELECT requested_url AS url FROM captures UNION SELECT url FROM captures UNION SELECT target_url AS url FROM resolved_links) WHERE url IS NOT NULL"),
        dict(name='url_normalized',sql=(ROOT/'model/sql/url-normalized.sql').read_text(),materialize=True),
        dict(name='model_url_keys',sql=(ROOT/'model/sql/url-keys.sql').read_text(),materialize=True)]
    return run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=steps+url_state_steps(),outputs=[],queries=[*url_state_diagnostics(),
            dict(name='state',sql='SELECT requested_url,attempts,last_status,last_outcome,cast(last_attempt AS VARCHAR) AS last_attempt,cast(last_good_at AS VARCHAR) AS last_good_at,cast(next_attempt_at AS VARCHAR) AS next_attempt_at FROM url_state ORDER BY requested_url'),
            *queries])


def test_interval_choice_is_one_grouping_without_a_join_or_window(tmp_path):
    """A grouped count joined back is a hash-join build charged once per emitted slice.

    At 1.17M URLs that charged 5.3 GB for 118 MB and exhausted the 14 GiB model pool.
    An undated address matches every band of its family and keeps the shortest one.
    """
    from viewer_publication.archive_url_state import url_state_steps
    intervals=next(step['sql'] for step in url_state_steps() if step['name']=='url_state_intervals')
    result=run_state(tmp_path,queries=[
        dict(name='plan',sql='EXPLAIN '+intervals),
        dict(name='bands',sql="""SELECT a.requested_url,count(*) AS n,min(i.interval_seconds) AS shortest
            FROM recheck_intervals i JOIN url_state_ages a ON a.family=i.family
            WHERE a.age_days IS NULL GROUP BY a.requested_url"""),
        dict(name='chosen',sql='SELECT requested_url,interval_seconds,matches FROM url_state_intervals')])
    plan=next(row['plan'] for row in result['plan'] if row['plan_type']=='physical_plan')
    assert 'HashJoinExec' not in plan and 'WindowAggExec' not in plan, plan
    chosen={row['requested_url']:row for row in result['chosen']}
    undated=[row for row in result['bands'] if row['n']>1]
    assert undated
    for row in undated:
        assert chosen[row['requested_url']]['interval_seconds']==row['shortest']
        assert chosen[row['requested_url']]['matches']==row['n']


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


FACTS=dict(name='facts',sql="""SELECT requested_url,cast(recheck_meeting_date AS VARCHAR) AS meeting_date,linked_from,
    arrow_typeof(recheck_meeting_date) AS date_type,arrow_typeof(linked_from) AS pages_type FROM url_state ORDER BY requested_url""")


@pytest.mark.parametrize('change',[None,'second_page'])
def test_url_state_publishes_the_meeting_date_its_band_used_and_the_pages_behind_a_queued_link(tmp_path,change):
    """ct-9j3z: the release gate checks next_attempt_at and queued rows against these two facts."""
    result=run_state(tmp_path,change,queries=[FACTS])
    assert not any(result['url_state_invariants'][0].values())
    facts={r['requested_url']:r for r in result['facts']}
    assert all(r['date_type']=='Date32' and r['pages_type'].startswith('List(') and 'FixedSizeBinary(8)' in r['pages_type']
               for r in result['facts'])
    # The band's date: a meeting date the model joined, else the docs.house.gov path date, else none.
    assert facts[BASE+'report.pdf']['meeting_date']=='2026-10-10'
    assert facts['https://docs.house.gov/meetings/AG/AG03/20200101/456/old.pdf']['meeting_date']=='2020-01-01'
    assert facts[BASE+'tie.pdf']['meeting_date']=='2026-11-01'
    assert facts['https://unknown-date.test/a']['meeting_date'] is None
    attempted=[r for r in result['facts'] if r['requested_url'] not in (BASE+'caption.vtt?key=constant',BASE+'new.pdf?x=1')]
    assert attempted and all(r['linked_from']==[] for r in attempted)
    # A queued row has no schedule, so no band date; it names every read page linking any spelling
    # of its key, once each, in key order. An address linked only from an error page is not queued.
    wrapper,listing='b'*16,'a1'*8  # the job returns binary values as hex
    assert facts[BASE+'caption.vtt?key=constant']=={**facts[BASE+'caption.vtt?key=constant'],'meeting_date':None,'linked_from':[wrapper]}
    assert facts[BASE+'new.pdf?x=1']['meeting_date'] is None
    assert facts[BASE+'new.pdf?x=1']['linked_from']==([listing,wrapper] if change else [wrapper])
    assert BASE+'error-only.pdf' not in facts


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
        assert states[BASE+'second-report.pdf']['last_good_at'] is None
        assert states[BASE+'report.pdf']['last_good_at'].startswith('2026-11-01')


def test_references_and_inline_records_cannot_shadow_a_real_fetch(tmp_path):
    result=run_state(tmp_path,'non_acquisition')
    assert not any(result['url_state_invariants'][0].values())
    [row]=[r for r in result['state'] if r['requested_url']==BASE+'report.pdf']
    assert row['attempts']==3 and row['last_status']==503 and row['last_outcome']=='request_failed'


@pytest.mark.parametrize('outcome',['reference','saved-record','failed'])
def test_only_metadata_mentions_leave_linked_addresses_unfetched(tmp_path,outcome):
    result=run_state(tmp_path,'mention_'+outcome)
    assert not any(result['url_state_invariants'][0].values())
    states={r['requested_url']:r for r in result['state']}
    if outcome=='failed':
        assert states[BASE+'mentioned.pdf']['attempts']==1
        assert states[BASE+'mentioned.pdf']['last_outcome']=='failed'
        assert BASE+'mentioned-final.pdf' not in states
    else:
        for url in (BASE+'mentioned.pdf',BASE+'mentioned-final.pdf'):
            assert states[url]['attempts']==0
            assert states[url]['last_status'] is None and states[url]['last_attempt'] is None


def test_split_context_stored_captures_and_statusless_migrated_good_fetches(tmp_path):
    result=run_state(tmp_path,'split_and_migrated')
    assert not any(result['url_state_invariants'][0].values())
    states={r['requested_url']:r for r in result['state']}
    mods=states['https://www.govinfo.gov/metadata/pkg/CHRG-119shrg62381/mods.xml']
    assert mods['attempts']==1
    assert mods['last_outcome']=='stored'
    assert mods['last_good_at'].startswith('2026-09-28T10:00:00')
    assert mods['next_attempt_at'] is not None
    migrated=states[BASE+'migrated.pdf']
    assert migrated['attempts']==1
    assert migrated['last_outcome']=='stored'
    assert migrated['last_good_at'].startswith('2026-09-28T11:00:00')
    assert migrated['next_attempt_at'] is not None


def test_prior_good_attempt_feeds_last_good_while_final_fetch_drives_line_schedule(tmp_path):
    result=run_state(tmp_path,'prior_good_final_failure')
    assert not any(result['url_state_invariants'][0].values())
    states={r['requested_url']:r for r in result['state']}
    retry=states[BASE+'retry-after-good.pdf']
    assert retry['attempts']==1
    assert retry['last_status']==503 and retry['last_outcome']=='retry_later'
    assert retry['last_good_at'].startswith('2026-11-15T12:00:00')
    assert retry['next_attempt_at'] is not None
    transport=states[BASE+'transport-after-403.pdf']
    assert transport['attempts']==1
    assert transport['last_status'] is None and transport['last_outcome']=='request_failed'
    split_fail=states['https://www.govinfo.gov/metadata/pkg/CHRG-119shrg99999/mods.xml']
    assert split_fail['attempts']==1
    assert split_fail['last_status']==200 and split_fail['last_outcome']=='failed'
    assert split_fail['last_good_at'] is None



@pytest.mark.parametrize(('change','good'),[('context_202',False),('context_200',True)])
def test_a_202_line_is_never_rescued_by_a_stored_context(tmp_path,change,good):
    """The control proves the rescue branch runs; a non-empty 202 still is not a document."""
    result=run_state(tmp_path,change)
    assert not any(result['url_state_invariants'][0].values())
    state={r['requested_url']:r for r in result['state']}['https://www.govinfo.gov/metadata/pkg/CHRG-119shrg77777/mods.xml']
    assert state['last_outcome']==('stored' if good else 'failed')
    assert (state['last_good_at'] is not None)==good
