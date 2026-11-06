"""Exact receipt/route/response qualification, using the maintained pinned readers."""
from datetime import datetime
from hashlib import sha256
import json
import os

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.lake import appearance_records as ar, meeting_records as mr
from congress_api.retention.provenance import json_input, parquet_output, run_job
from docspec_client.client import NativeDatasets
from viewer_publication.archive_model import (
    APPEARANCE_RECORD_FIELDS, MEETING_RECORD_FIELDS, _normalize_appearance_rows,
    _normalize_meeting_rows, meeting_detail_steps,
)
from viewer_publication.meeting_detail_observations import UNKNOWN_OBSERVATION

PROOF_VERSION = '6d9460f5ec203c24c508846092505a875710f565e1ff026479b542c7555e7d48'
BASE = 'https://api.congress.gov/v3/committee-meeting/118/house'


@pytest.fixture(scope='module')
def observations(tmp_path_factory):
    assert ar.current_versions()['congress_gov']==PROOF_VERSION
    work = tmp_path_factory.mktemp('meeting-detail-observations')
    meetings, appearances, captures = [], [], []

    def response(event, *, listing=False, congress=118, chamber='House', proof=PROOF_VERSION):
        record = dict(eventId=str(event), congress=congress, chamber=chamber,
                      title='Retained event', updateDate='2024-06-01T10:00:00Z')
        payload = {'committeeMeetings': [record]} if listing else {'committeeMeeting': record}
        body = json.dumps(payload).encode()
        digest = sha256(body).hexdigest()
        meetings.append(mr.build_meeting_record_row(digest, 'congress_gov', body,
                        parser_version=mr.current_versions()['congress_gov']))
        appearances.append(ar.build_appearance_record_row(digest, 'congress_gov', body,
                           parser_version=proof))
        return bytes.fromhex(digest)

    def capture(event, digest=None, *, when='2026-11-01T12:00:00Z', outcome='stored', status=200,
                url=None, final=None, complete=True):
        url = url or f'{BASE}/{event}?format=json'
        captures.append(dict(receipt_key=f'receipts/observation-{len(captures):02}.jsonl.gz',
            receipt_line=1,capture_index=0,sha256=digest,
            retrieved_at=datetime.fromisoformat(when.replace('Z','+00:00')) if when else None,
            mode='fetch',requested_url=url,url=final or url,http_status=status,outcome=outcome,complete=complete))

    good = response(1)
    capture(1,good)
    capture(1,outcome='failed',status=503,when='2026-11-03T12:00:00Z')
    # A later retrieval of identical bytes at another route cannot move event 1's read time.
    capture(2,good,when='2026-11-05T12:00:00Z')
    capture(None,response(3,listing=True),url=BASE+'?offset=0&limit=250')
    capture(4,outcome='failed',status=404)
    capture(5,response(5),when=None)
    # A list response served on a detail route must not be stamped successful.
    capture(6,response(6,listing=True))
    # Complete identity, recognized proof version and final route all matter.
    capture(7,response(7,congress=119))
    capture(8,response(8,chamber='Senate'))
    capture(9,response(9,proof='unqualified-older-reader'))
    capture(10,response(10),final=f'{BASE}/99?format=json')
    # Unknown candidates outrank a failure or listing-only claim.
    capture(6,outcome='failed',status=500,when='2026-11-06T12:00:00Z')
    capture(None,response(6,listing=True),url=BASE)
    capture(11,response(11),when='2026-11-01T07:00:00-05:00')
    capture(11,bytes.fromhex(meetings[-1]['record_sha']),when=None)
    # Joint uses the API's nochamber spelling, while the model states joint.
    capture(12,response(12,chamber='Joint'),url=BASE.replace('/house','/nochamber')+'/12')
    # Existing parser deliberately leaves NoChamber unknown; a route cannot fill that source fact.
    capture(14,response(14,chamber='NoChamber'),url=BASE.replace('/house','/nochamber')+'/14')
    # A legacy saved record supplies no fetch receipt or observation clock.
    response(13)

    schema=pa.schema([('receipt_key',pa.string()),('receipt_line',pa.int32()),('capture_index',pa.int32()),
        ('sha256',pa.binary(32)),('retrieved_at',pa.timestamp('us',tz='UTC')),('mode',pa.string()),
        ('requested_url',pa.string()),('url',pa.string()),('http_status',pa.int32()),
        ('outcome',pa.string()),('complete',pa.bool_())])
    pq.write_table(pa.Table.from_pylist(captures,schema=schema),work/'captures.parquet')
    inputs=[dict(name='captures',kind='parquet',path=str(work/'captures.parquet')),
        json_input(work,'selected_meeting_records',_normalize_meeting_rows(meetings,None),**MEETING_RECORD_FIELDS),
        json_input(work,'selected_appearance_records',_normalize_appearance_rows(appearances,None),**APPEARANCE_RECORD_FIELDS)]
    result=run_job(work,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=meeting_detail_steps(),outputs=[parquet_output(work,'observations',
            'SELECT * FROM meeting_detail_observations',['congress','chamber','event_id'])],
        queries=[dict(name='unknown',sql=f'SELECT {UNKNOWN_OBSERVATION} AS observation')])
    assert result['unknown'][0]['observation']==dict(state='unknown',coverage='unknown',
        successful_read=None,latest_attempt=None,listing=None,has_undated_attempt=False)
    return {row['event_id']:row for row in pq.read_table(work/'observations.parquet').to_pylist()},captures


def test_success_keeps_its_receipt_and_clock_after_failure(observations):
    rows,captures=observations
    row=rows[1]
    assert row['state']=='successful'
    assert row['successful_read']['receipt_key']==captures[0]['receipt_key']
    assert row['successful_read']['retrieved_at']==captures[0]['retrieved_at']
    assert row['latest_attempt']['evidence']['receipt_key']==captures[1]['receipt_key']
    assert row['latest_attempt']['state']=='failed'
    assert row['latest_attempt']['http_status']==503


def test_scoped_listing_failure_undated_and_missing_evidence(observations):
    rows,_=observations
    assert rows[3]['state']=='listing_only_in_scope' and rows[3]['listing']
    assert rows[3]['latest_attempt'] is None
    assert rows[4]['state']=='failed' and rows[4]['successful_read'] is None
    assert rows[5]['state']=='successful' and rows[5]['has_undated_attempt']
    assert rows[5]['successful_read']['retrieved_at'] is None
    assert 13 not in rows  # Public join supplies typed unknown, never a fabricated attempt.
    assert {row['coverage'] for row in rows.values()}=={'selected_release_inputs'}


def test_planted_list_wrong_identity_unqualified_reader_and_redirect_are_unknown(observations):
    rows,_=observations
    for event in (2,6,7,8,9,10,14):
        assert rows[event]['state']=='unknown',event
        assert rows[event]['successful_read'] is None,event
    assert rows[6]['latest_attempt']['state']=='failed'  # Uncertain earlier response remains visible in summary.


def test_chronological_order_and_joint_identity(observations):
    rows,_=observations
    assert rows[11]['has_undated_attempt']
    assert rows[11]['successful_read']['retrieved_at'].isoformat()=='2026-11-01T12:00:00+00:00'
    assert rows[12]['chamber']=='joint' and rows[12]['state']=='successful'


def test_detail_observation_reaches_public_meeting_and_legacy_stays_unknown(tmp_path):
    from archive_job_fixture import spicy_input
    from test_phase2_model_entities import _stage_raw_fixture
    from viewer_publication.archive_model import build_release

    assert ar.current_versions()['congress_gov']==PROOF_VERSION
    payload=json.dumps(dict(committeeMeeting=dict(eventId='115538',congress=118,chamber='House',
        title='Detail read integration',date='2023-05-10T10:00:00Z',updateDate='2024-06-01T10:00:00Z'))).encode()
    digest=sha256(payload).hexdigest()
    engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    staged=_stage_raw_fixture(tmp_path,engine,[
        dict(url=f'{BASE}/115538?format=json',data=payload,format='json',media_type='application/json',
            family='congress/meetings',retrieved_at='2026-11-01T12:00:00Z'),
        dict(url='https://fixture.test/report.pdf',data=b'%PDF-1.7\nfixture\n%%EOF\n',
            format='pdf',compress=False,family='documents')])
    legacy=json.dumps(dict(committeeMeeting=dict(eventId='115539',congress=118,chamber='House',
        title='Legacy record with no fetch',updateDate='2024-06-02T10:00:00Z'))).encode()
    build_release(**staged,engine=engine,output=tmp_path/'release',scratch=tmp_path/'model',spicy_regs=spicy_input(),
        meeting_records=[mr.build_meeting_record_row(digest,'congress_gov',payload,
            parser_version=mr.current_versions()['congress_gov']),
            mr.build_meeting_record_row(sha256(legacy).hexdigest(),'congress_gov',legacy,
            parser_version=mr.current_versions()['congress_gov'])],
        appearance_records=[ar.build_appearance_record_row(digest,'congress_gov',payload,parser_version=PROOF_VERSION)])
    rows={r['event_id']:r for r in pq.read_table(tmp_path/'release/meetings.parquet').to_pylist()}
    observed=rows[115538]['congress_gov_detail_observation']
    assert observed['state']=='successful'
    assert observed['successful_read']['body_sha256']==digest
    assert observed['successful_read']['retrieved_at'].isoformat()=='2026-11-01T12:00:00+00:00'
    assert rows[115538]['congress_gov_updated'].isoformat()=='2024-06-01T10:00:00+00:00'
    assert rows[115539]['congress_gov_detail_observation']==dict(state='unknown',coverage='unknown',
        successful_read=None,latest_attempt=None,listing=None,has_undated_attempt=False)
