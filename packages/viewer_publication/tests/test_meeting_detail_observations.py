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
    # Conditional revalidation supplies no new detail body and is not a failed read.
    capture(15,outcome='unchanged',status=304)
    capture(16,response(16))
    capture(16,outcome='unchanged',status=304,when='2026-11-03T12:00:00Z')
    capture(None,response(17,listing=True),url=BASE)
    capture(17,outcome='unchanged',status=304)

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


def test_not_modified_preserves_unknown_proof_and_prior_success(observations):
    rows,_=observations
    for event in (15,17):
        assert rows[event]['state']=='unknown',event
        assert rows[event]['successful_read'] is None
    assert rows[17]['listing'] is not None
    assert rows[16]['state']=='successful'
    assert rows[16]['successful_read']['retrieved_at'].isoformat()=='2026-11-01T12:00:00+00:00'
    for event in (15,16,17):
        attempt=rows[event]['latest_attempt']
        assert attempt['state']=='unknown',event
        assert attempt['outcome']=='unchanged' and attempt['http_status']==304
        assert attempt['evidence']['source_url']==f'{BASE}/{event}?format=json'
        assert attempt['evidence']['receipt_key'] is not None


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


def _stage_receipts_fixture(work_root, engine, receipt_specs):
    import gzip
    from congress_api.lake import filenames, readings
    from congress_api.lake.capture_staging import stage_captures
    raw = work_root / 'raw'
    raw.mkdir(parents=True)
    receipt_inputs = []
    blobs = {}
    all_specs = []
    for rel_key, specs in receipt_specs.items():
        all_specs.extend(specs)
        rows = []
        for spec in specs:
            data = spec['data']
            fmt = spec.get('format', 'html')
            compress = spec.get('compress', fmt in ('html', 'xml', 'json', 'vtt', 'm3u8'))
            stored = gzip.compress(data, mtime=0) if compress else data
            digest = sha256(data).hexdigest()
            suffix = '.gz' if compress else spec.get('suffix', '')
            body_path = raw / f'bodies/sha256/{digest[:2]}/{digest}{suffix}'
            body_path.parent.mkdir(parents=True, exist_ok=True)
            body_path.write_bytes(stored)
            url = spec['url']
            rows.append(dict(
                writer=dict(job='fixture', commit='a' * 40), run_id='fixture', mode='fetch',
                family=spec.get('family', 'documents'), outcome=spec.get('outcome', 'stored'),
                requested_url=spec.get('requested_url', url), url=url, response_headers={},
                http_status=200, complete=True, retrieved_at=spec['retrieved_at'],
                captures=[dict(
                    sha256=digest, bytes=len(data),
                    media_type=spec.get('media_type', 'application/pdf'),
                    fidelity='exact-bytes', sniffed_format=fmt,
                    sniff_version=readings.current_version('sniff'),
                    intact=True if fmt == 'pdf' else None, stored_suffix=suffix,
                    stored_bytes=len(stored),
                    stored_md5=__import__('hashlib').md5(stored).hexdigest(),
                    context_url=spec.get('context_url'))]))
        encoded = gzip.compress((''.join(json.dumps(r) + '\n' for r in rows)).encode(), mtime=0)
        blobs[rel_key] = encoded
        rpath = raw / rel_key
        rpath.parent.mkdir(parents=True, exist_ok=True)
        rpath.write_bytes(encoded)
        qpath = work_root / f'pin-{len(receipt_inputs)}.json'
        qpath.write_text(json.dumps(dict(path=str(rpath), size=len(encoded),
                                         sha256=sha256(encoded).hexdigest(), producer='fixture')))
        receipt_inputs.append(dict(key=rel_key, path=str(rpath), qualification=str(qpath)))
    captures = stage_captures(receipt_inputs, engine=engine, work=work_root / 'capture-stage') / 'captures.parquet'
    inv = work_root / 'inventory'
    inv.mkdir()
    run_job(inv, engine, inputs=[dict(name='captures', kind='parquet', path=str(captures))], steps=[],
            outputs=[parquet_output(inv, 'bodies', """SELECT DISTINCT sha256 AS body_sha,
                'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex')||stored_suffix AS physical_key,
                'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex')||stored_suffix AS relative_path,
                stored_bytes FROM captures WHERE sha256 IS NOT NULL""", ['body_sha'])])
    page_formats = ['html'] + sorted({s.get('format', 'html') for s in all_specs} & {'xml', 'json'})
    staged_pages = [readings.stage(captures=captures, body_inventory=inv / 'bodies.parquet', local_root=raw,
                                   engine=engine, work=work_root / f'reading-{p}',
                                   decided_at='2026-11-08T12:00:00Z', parser=p)['readings'] for p in page_formats]
    page_readings = staged_pages[0]
    if len(staged_pages) > 1:
        page_readings = work_root / 'page-readings.parquet'
        pq.write_table(pa.concat_tables([pq.read_table(p) for p in staged_pages]), page_readings)
    names = filenames.stage(captures=captures, recovery_files=(), engine=engine,
                            work=work_root / 'filename-stage', decided_at='2026-11-08T12:00:00Z')
    return dict(
        staged=dict(captures=captures, readings=page_readings, filename_readings=names['readings'],
                    parser_versions={**{p: readings.current_version(p) for p in ['sniff', 'html', 'xml', 'json']},
                                     'meeting_records': mr.current_versions(),
                                     'appearance_records': ar.current_versions(),
                                     'video_records': {'youtube_cache': 'pv', 'youtube_api': 'pa'},
                                     'committee_records': {'house_xml': 'pc'}},
                    catalog_version=names['catalog_version']),
        blobs=blobs, captures=captures)


def test_end_to_end_build_release_congress_gov_meeting_update_passes_unattended(tmp_path):
    """End-to-end integration: build two real releases via `archive_model.build_release` where a new
    Congress.gov receipt updates an existing meeting (rescheduling its date past another document with
    the same filename so `list_row` permutes, renaming a witness, adding a witness and publisher video)
    and states a new meeting for the first time; verify `require_release_gates` passes unattended."""
    from archive_job_fixture import spicy_input
    from viewer_publication.archive_model import build_release
    from viewer_publication.release_gate import automatic_causes, require_release_gates

    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    live_key = 'receipts/congress/2026-10-27/base.jsonl.gz'
    new_key = 'receipts/congress/2026-11-08/relist.jsonl.gz'

    m1_v1 = json.dumps(dict(committeeMeeting=dict(
        eventId='115538', congress=118, chamber='House', title='Oversight Hearing',
        type='Hearing', meetingStatus='Scheduled', date='2023-05-10T10:00:00Z',
        updateDate='2024-06-01T10:00:00Z',
        committees=[dict(systemCode='hsag00', name='Committee on Agriculture')],
        witnesses=[dict(name='Ms. Ann Lee', organization='GAO'),
                   dict(name='Mr. Bo Park', organization='CBO')]))).encode()
    m2_fixed = json.dumps(dict(committeeMeeting=dict(
        eventId='115539', congress=118, chamber='House', title='Fixed Hearing',
        type='Hearing', meetingStatus='Scheduled', date='2023-05-12T10:00:00Z',
        updateDate='2024-06-01T10:00:00Z',
        committees=[dict(systemCode='hsag00', name='Committee on Agriculture')]))).encode()
    m1_v2 = json.dumps(dict(committeeMeeting=dict(
        eventId='115538', congress=118, chamber='House', title='Oversight Hearing, Rescheduled',
        type='Hearing', meetingStatus='Postponed', date='2023-05-17T14:00:00Z',
        updateDate='2024-06-08T10:00:00Z',
        committees=[dict(systemCode='hsag00', name='Committee on Agriculture')],
        videos=[dict(name='Hearing Video', url='https://www.youtube.com/watch?v=dQw4w9WgXcQ')],
        witnesses=[dict(name='Ms. Anna Lee', organization='GAO'),
                   dict(name='Mr. Bo Park', organization='CBO'),
                   dict(name='Dr. Cy Diaz', organization='EPA')]))).encode()
    m3_new = json.dumps(dict(committeeMeeting=dict(
        eventId='115540', congress=118, chamber='House', title='Newly Stated Hearing',
        type='Hearing', meetingStatus='Scheduled', date='2023-05-20T10:00:00Z',
        updateDate='2024-06-08T11:00:00Z',
        committees=[dict(systemCode='hsag00', name='Committee on Agriculture')],
        witnesses=[dict(name='Ms. Pat Roe', organization='USDA')]))).encode()

    doc_a = dict(url='https://docs.house.gov/meetings/AG/AG00/20230510/115538/testimony.pdf',
                 data=b'%PDF-1.7\nwitness A testimony\n%%EOF\n', format='pdf', compress=False,
                 family='documents', retrieved_at='2026-10-27T11:00:00Z')
    doc_b = dict(url='https://docs.house.gov/meetings/AG/AG00/20230512/115539/testimony.pdf',
                 data=b'%PDF-1.7\nwitness B testimony\n%%EOF\n', format='pdf', compress=False,
                 family='documents', retrieved_at='2026-10-27T11:05:00Z')
    live_specs = [
        doc_a, doc_b,
        dict(url=f'{BASE}/115538?format=json', data=m1_v1, format='json', media_type='application/json',
             family='congress/meetings', retrieved_at='2026-10-27T12:00:00Z'),
        dict(url=f'{BASE}/115539?format=json', data=m2_fixed, format='json', media_type='application/json',
             family='congress/meetings', retrieved_at='2026-10-27T12:01:00Z'),
    ]
    new_specs = [
        dict(url=f'{BASE}/115538?format=json', data=m1_v2, format='json', media_type='application/json',
             family='congress/meetings', retrieved_at='2026-11-08T12:00:00Z'),
        dict(url=f'{BASE}/115540?format=json', data=m3_new, format='json', media_type='application/json',
             family='congress/meetings', retrieved_at='2026-11-08T12:01:00Z'),
    ]
    spicy = spicy_input(spicy_committees=[dict(
        system_code='HSAG00', name='Committee on Agriculture', chamber='House',
        committee_type='Standing', parent_system_code=None,
        website_url='https://agriculture.house.gov/', is_current=True,
        history=[dict(officialName='Committee on Agriculture',
                      startDate='2021-01-03T05:00:00Z', endDate='2025-01-03T04:59:59Z')])])

    def parse_pair(payload):
        d = sha256(payload).hexdigest()
        return (mr.build_meeting_record_row(d, 'congress_gov', payload, parser_version=mr.current_versions()['congress_gov']),
                ar.build_appearance_record_row(d, 'congress_gov', payload, parser_version=PROOF_VERSION))

    mr_1v1, ar_1v1 = parse_pair(m1_v1)
    mr_2, ar_2 = parse_pair(m2_fixed)
    mr_1v2, ar_1v2 = parse_pair(m1_v2)
    mr_3, ar_3 = parse_pair(m3_new)

    from congress_api.lake import committee_records as cr_lake, video_records as vr_lake
    video_path, committee_path, decisions = tmp_path / 'video.parquet', tmp_path / 'committee.parquet', tmp_path / 'decisions.jsonl'
    pq.write_table(vr_lake.table([]), video_path)
    pq.write_table(cr_lake.table([]), committee_path)
    decisions.write_text('')
    explorer_kw = dict(video_records=video_path, committee_records=committee_path,
                       recording_decision_files=[dict(key='provenance/recording_decisions/a.jsonl', path=str(decisions))])

    base_env = _stage_receipts_fixture(tmp_path / 'base-stage', engine, {live_key: live_specs})
    base_dir = tmp_path / 'base-release'
    build_release(**base_env['staged'], engine=engine, output=base_dir, scratch=tmp_path / 'base-model',
                  spicy_regs=spicy, meeting_records=[mr_1v1, mr_2], appearance_records=[ar_1v1, ar_2],
                  **explorer_kw)

    cand_env = _stage_receipts_fixture(tmp_path / 'cand-stage', engine, {live_key: live_specs, new_key: new_specs})
    cand_dir = tmp_path / 'cand-release'
    build_release(**cand_env['staged'], engine=engine, output=cand_dir, scratch=tmp_path / 'cand-model',
                  spicy_regs=spicy, meeting_records=[mr_1v1, mr_2, mr_1v2, mr_3],
                  appearance_records=[ar_1v1, ar_2, ar_1v2, ar_3], **explorer_kw)

    # Confirm doc_a and doc_b swapped list_row when 115538 rescheduled from 2023-05-10 past 2023-05-12 to 2023-05-17.
    base_dates = [str(d) for d in pq.read_table(base_dir / 'list.parquet', columns=['document_date'])['document_date'].to_pylist()]
    cand_dates = [str(d) for d in pq.read_table(cand_dir / 'list.parquet', columns=['document_date'])['document_date'].to_pylist()]
    assert base_dates == ['2023-05-10', '2023-05-12']
    assert cand_dates == ['2023-05-12', '2023-05-17']

    def automatic(report):
        return automatic_causes(
            report, base_dir, cand_dir, engine=engine,
            captures=dict(kind='parquet', path=str(cand_env['captures'])),
            live_receipt_keys={live_key}, read_receipt=cand_env['blobs'].__getitem__,
            work=tmp_path / 'auto', candidate_receipt_keys={live_key, new_key})

    report = require_release_gates(base_dir, cand_dir, None, report_path=tmp_path / 'gate-report.json', automatic=automatic)
    assert report['reasons'] == [] and report.get('automatic_reasons', []) == []
