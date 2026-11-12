"""Bidirectional raw check tests for ct-960v retained Congress.gov items."""
from hashlib import sha256
import json
from pathlib import Path
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import congress_gov_retained_raw_check as retained_check  # noqa: E402


def _write_receipt_lines(mirror: Path, lines: list[dict]) -> list[str]:
    receipt = mirror / 'receipts/congress/meetings/2026-11-10/meetings.jsonl'
    receipt.parent.mkdir(parents=True, exist_ok=True)
    raw_lines = [json.dumps(obj, separators=(',', ':')).encode() for obj in lines]
    receipt.write_bytes(b'\n'.join(raw_lines) + b'\n')
    return [sha256(b).hexdigest() for b in raw_lines]


def _fixture_release(tmp_path: Path):
    mirror = tmp_path / 'mirror'
    release = tmp_path / 'release'
    release.mkdir(parents=True)

    read_1 = {
        'captured_at': '2026-11-01T12:00:00Z',
        'committeeMeeting': {
            'eventId': '118999',
            'updateDate': '2026-11-01T10:00:00Z',
            'witnesses': [
                {'name': 'Dr. Alice Example', 'position': 'Director', 'organization': 'Institute Alpha'},
                {'name': 'Mr. Bob Dropped', 'position': 'Fellow', 'organization': 'Policy Lab'},
            ],
            'meetingDocuments': [
                {'url': 'https://docs.house.gov/meetings/IF/IF00/20261101/118999/keep.pdf'},
                {'url': 'https://docs.house.gov/meetings/IF/IF00/20261101/118999/dropped.pdf'},
            ],
            'relatedItems': {
                'bills': [
                    {'congress': 118, 'type': 'HR', 'number': 100},
                    {'congress': 118, 'type': 'HR', 'number': 200},
                ],
                'nominations': [
                    {'congress': 118, 'number': '450', 'part': '00'},
                    {'congress': 118, 'number': 'PN730', 'part': '02'},
                ],
            },
        },
    }
    read_2 = {
        'captured_at': '2026-11-05T12:00:00Z',
        'committeeMeeting': {
            'eventId': '118999',
            'updateDate': '2026-11-05T10:00:00Z',
            'witnesses': [
                {'name': 'Dr. Alice Example', 'position': 'Director', 'organization': 'Institute Alpha'},
            ],
            'meetingDocuments': [
                {'url': 'https://docs.house.gov/meetings/IF/IF00/20261101/118999/keep.pdf'},
            ],
            'relatedItems': {
                'bills': [{'congress': 118, 'type': 'HR', 'number': 100}],
                'nominations': [],
            },
        },
    }
    sha_1, sha_2 = _write_receipt_lines(mirror, [read_1, read_2])

    witnesses = [
        {
            'witness_key': 'aaaa1111aaaa1111',
            'occasion': 'meeting:118999',
            'event_id': 118999,
            'source': 'congress_gov',
            'record_sha': bytes.fromhex(sha_2),
            'source_locator': 'congress_gov:witness[1]',
            'name': 'Dr. Alice Example',
            'position': 'Director',
            'organization': 'Institute Alpha',
            'listing_status': 'listed',
            'last_listed_on': None,
            'unlisted_since': None,
            'unlisted_by_record_sha': None,
        },
        {
            'witness_key': 'bbbb2222bbbb2222',
            'occasion': 'meeting:118999',
            'event_id': 118999,
            'source': 'congress_gov',
            'record_sha': bytes.fromhex(sha_1),
            'source_locator': 'congress_gov:witness[2]',
            'name': 'Mr. Bob Dropped',
            'position': 'Fellow',
            'organization': 'Policy Lab',
            'listing_status': 'no_longer_listed',
            'last_listed_on': '2026-11-01',
            'unlisted_since': '2026-11-05',
            'unlisted_by_record_sha': sha_2,
        },
    ]
    meetings = [
        {
            'event_id': 118999,
            'subject_keys': ['118-hr-100', '118-hr-200', '118-pn-450', '118-pn-730-2'],
            'unlisted_subjects': [
                {
                    'subject_key': '118-hr-200',
                    'last_listed_on': '2026-11-01',
                    'unlisted_since': '2026-11-05',
                    'unlisted_by_record_sha': sha_2,
                },
                {
                    'subject_key': '118-pn-450',
                    'last_listed_on': '2026-11-01',
                    'unlisted_since': '2026-11-05',
                    'unlisted_by_record_sha': sha_2,
                },
                {
                    'subject_key': '118-pn-730-2',
                    'last_listed_on': '2026-11-01',
                    'unlisted_since': '2026-11-05',
                    'unlisted_by_record_sha': sha_2,
                },
            ],
            'document_references': [
                {
                    'url': 'https://docs.house.gov/meetings/IF/IF00/20261101/118999/keep.pdf',
                    'listing_status': 'listed',
                    'last_listed_on': None,
                    'unlisted_since': None,
                    'unlisted_by_record_sha': None,
                },
                {
                    'url': 'https://docs.house.gov/meetings/IF/IF00/20261101/118999/dropped.pdf',
                    'listing_status': 'no_longer_listed',
                    'last_listed_on': '2026-11-01',
                    'unlisted_since': '2026-11-05',
                    'unlisted_by_record_sha': sha_2,
                },
            ],
        },
    ]
    pq.write_table(pa.Table.from_pylist(witnesses), release / 'witnesses.parquet')
    pq.write_table(pa.Table.from_pylist(meetings), release / 'meetings.parquet')
    return release, mirror, witnesses, meetings, sha_1, sha_2


def test_clean_release_passes_both_directions_and_cli_plants_catch_both_mutations(tmp_path):
    release, mirror, _, _, _, _ = _fixture_release(tmp_path)
    out = tmp_path / 'report.json'
    report = retained_check.main([
        '--release', str(release),
        '--mirror', str(mirror),
        '--plant',
        '--output', str(out),
    ])
    assert report['flag_count'] == 0
    assert report['counts']['supported_unlisted_witnesses'] == 1
    assert report['counts']['supported_unlisted_docs'] == 1
    assert report['counts']['supported_unlisted_subjects'] == 3
    assert report['plants']['still_listed_marked_removed']['caught'] is True
    assert report['plants']['dropped_item_deleted']['caught'] is True


def test_flags_still_listed_items_falsely_marked_removed_and_dropped_items_deleted(tmp_path):
    _, mirror, witnesses, meetings, _, _ = _fixture_release(tmp_path)
    raw_reads, house_docs, house_subjects = retained_check.load_raw_reads(mirror)

    # Falsely mark still-listed doc and subject as removed
    bad_meetings = json.loads(json.dumps(meetings))
    bad_meetings[0]['document_references'][0]['listing_status'] = 'no_longer_listed'
    bad_meetings[0]['unlisted_subjects'].append({
        'subject_key': '118-hr-100',
        'last_listed_on': '2026-11-01',
        'unlisted_since': '2026-11-05',
        'unlisted_by_record_sha': '0' * 64,
    })
    res_false = retained_check.evaluate(witnesses, bad_meetings, raw_reads, house_docs, house_subjects)
    assert res_false['flags_by_kind'] == {
        'still_listed_doc_marked_removed': 1,
        'still_listed_subject_marked_removed': 1,
    }

    # Silently delete dropped witness, dropped doc, and dropped subject
    dropped_w = [w for w in witnesses if w['listing_status'] != 'no_longer_listed']
    dropped_m = json.loads(json.dumps(meetings))
    dropped_m[0]['document_references'] = [
        r for r in dropped_m[0]['document_references'] if r['listing_status'] != 'no_longer_listed'
    ]
    dropped_m[0]['subject_keys'] = ['118-hr-100']
    dropped_m[0]['unlisted_subjects'] = []
    res_del = retained_check.evaluate(dropped_w, dropped_m, raw_reads, house_docs, house_subjects)
    assert res_del['flags_by_kind'] == {
        'dropped_witness_missing': 1,
        'dropped_doc_missing': 1,
        'dropped_subject_missing': 3,
    }

    # Wrong unlisted_since / unlisted_by_record_sha on document_references and unlisted_subjects are flagged
    bad_dates_m = json.loads(json.dumps(meetings))
    bad_dates_m[0]['document_references'][1]['unlisted_since'] = '2026-11-09'
    bad_dates_m[0]['unlisted_subjects'][0]['unlisted_by_record_sha'] = 'f' * 64
    res_dates = retained_check.evaluate(witnesses, bad_dates_m, raw_reads, house_docs, house_subjects)
    assert res_dates['flags_by_kind'] == {
        'doc_unlisted_since_mismatch': 1,
        'subject_unlisted_record_sha_mismatch': 1,
    }


def test_unchanged_refetches_advance_last_listed_on_without_drifting_unlisted_since(tmp_path):
    mirror = tmp_path / 'mirror'
    bodies = mirror / 'bodies/sha256'
    b1 = json.dumps({
        'committeeMeeting': {
            'eventId': '119123',
            'updateDate': '2026-10-01T10:00:00Z',
            'witnesses': [{'name': 'Dr. Drop Test', 'position': 'Chair', 'organization': 'Org A'}],
            'meetingDocuments': [{'url': 'https://www.congress.gov/119/meeting/house/119123/witnesses/drop.pdf'}],
            'relatedItems': {'bills': [{'congress': 119, 'type': 'HR', 'number': 42}]},
        },
    }).encode()
    b2 = json.dumps({
        'committeeMeeting': {
            'eventId': '119123',
            'updateDate': '2026-10-31T10:00:00Z',
            'witnesses': [],
            'meetingDocuments': [],
            'relatedItems': {'bills': []},
        },
    }).encode()
    s1, s2 = sha256(b1).hexdigest(), sha256(b2).hexdigest()
    for s, b in [(s1, b1), (s2, b2)]:
        p = bodies / s[:2] / f'{s}.json'
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b)

    import gzip
    for idx, env in enumerate([
        {'outcome': 'stored', 'http_status': 200, 'retrieved_at': '2026-10-01T12:00:00Z', 'padding': 'x' * 700, 'captures': [{'sha256': s1}]},
        {'outcome': 'unchanged', 'http_status': 200, 'retrieved_at': '2026-10-15T12:00:00Z', 'padding': 'x' * 700, 'captures': [{'sha256': s1}]},
        {'outcome': 'stored', 'http_status': 200, 'retrieved_at': '2026-10-31T12:00:00Z', 'padding': 'x' * 700, 'captures': [{'sha256': s2}]},
        {'outcome': 'unchanged', 'http_status': 200, 'retrieved_at': '2026-11-08T12:00:00Z', 'padding': 'x' * 700, 'captures': [{'sha256': s2}]},
    ]):
        rp = mirror / f'receipts/congress/meetings/2026-11/single-{idx:04d}.jsonl.gz'
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_bytes(gzip.compress((json.dumps(env) + '\n').encode()))
    raw_reads, house_docs, house_subjects = retained_check.load_raw_reads(mirror)

    witnesses = [{
        'witness_key': 'cccc3333cccc3333',
        'occasion': 'meeting:119123',
        'event_id': 119123,
        'source': 'congress_gov',
        'name': 'Dr. Drop Test',
        'position': 'Chair',
        'organization': 'Org A',
        'listing_status': 'no_longer_listed',
        'last_listed_on': '2026-10-15',
        'unlisted_since': '2026-10-31',
        'unlisted_by_record_sha': s2,
    }]
    meetings = [{
        'event_id': 119123,
        'subject_keys': ['119-hr-42'],
        'unlisted_subjects': [{
            'subject_key': '119-hr-42',
            'last_listed_on': '2026-10-15',
            'unlisted_since': '2026-10-31',
            'unlisted_by_record_sha': s2,
        }],
        'document_references': [{
            'url': 'https://www.congress.gov/119/meeting/house/119123/witnesses/drop.pdf',
            'listing_status': 'no_longer_listed',
            'last_listed_on': '2026-10-15',
            'unlisted_since': '2026-10-31',
            'unlisted_by_record_sha': s2,
        }],
    }]
    res_ok = retained_check.evaluate(witnesses, meetings, raw_reads, house_docs, house_subjects)
    assert res_ok['flag_count'] == 0

    # Drifting unlisted_since to the unchanged poll date (2026-11-08) is flagged!
    drifted_m = json.loads(json.dumps(meetings))
    drifted_m[0]['document_references'][0]['unlisted_since'] = '2026-11-08'
    res_drift = retained_check.evaluate(witnesses, drifted_m, raw_reads, house_docs, house_subjects)
    assert res_drift['flags_by_kind'] == {'doc_unlisted_since_mismatch': 1}


def test_real_house_xml_meeting_tags_and_partial_duplicate_tba_slots(tmp_path):
    """WARNING 1 & WARNING 2: _parse_house_xml recognizes real <committee-meeting meeting-id="HMTG-...">,
    <meeting-details><congress>, <files><file doc-url="..."/></files>, and <legis-num>H.R. 300</legis-num>
    so items still listed by House XML are NOT expected in unlisted_subjects/no_longer_listed, while partial
    duplicate TBA witness drops (2 -> 1) pass both directions cleanly."""
    mirror = tmp_path / 'mirror'
    bodies = mirror / 'bodies/sha256'
    house_xml = b"""<committee-meeting meeting-id="HMTG-118-IF00-20261101-118555">
      <meeting-details><congress>118</congress></meeting-details>
      <meeting-documents>
        <meeting-document>
          <legis-num>H.R. 300</legis-num>
          <files>
            <file doc-url="https://docs.house.gov/meetings/IF/IF00/20261101/118555/house-kept.pdf"/>
          </files>
        </meeting-document>
      </meeting-documents>
    </committee-meeting>"""
    h_sha = sha256(house_xml).hexdigest()
    hp = bodies / h_sha[:2] / f'{h_sha}.xml'
    hp.parent.mkdir(parents=True, exist_ok=True)
    hp.write_bytes(house_xml)

    r1 = {
        'captured_at': '2026-11-01T12:00:00Z',
        'committeeMeeting': {
            'eventId': '118555',
            'updateDate': '2026-11-01T10:00:00Z',
            'witnesses': [
                {'name': 'TBA', 'organization': 'Panel 1', 'position': 'Witness'},
                {'name': 'TBA', 'organization': 'Panel 1', 'position': 'Witness'},
            ],
            'meetingDocuments': [
                {'url': 'https://docs.house.gov/meetings/IF/IF00/20261101/118555/house-kept.pdf'},
            ],
            'relatedItems': {'bills': [{'congress': 118, 'type': 'HR', 'number': 300}]},
        },
    }
    # Read 2 omits meetingDocuments and relatedItems (kept listed by House XML!) and drops 1 of 2 TBA witnesses
    r2 = {
        'captured_at': '2026-11-05T12:00:00Z',
        'committeeMeeting': {
            'eventId': '118555',
            'updateDate': '2026-11-05T10:00:00Z',
            'witnesses': [
                {'name': 'TBA', 'organization': 'Panel 1', 'position': 'Witness'},
            ],
        },
    }
    _, s2 = _write_receipt_lines(mirror, [r1, r2])
    raw_reads, house_docs, house_subjects = retained_check.load_raw_reads(mirror, house_xml_shas=[h_sha])
    assert 'https://docs.house.gov/meetings/IF/IF00/20261101/118555/house-kept.pdf' in house_docs['118555']
    assert '118-hr-300' in house_subjects['118555']

    witnesses = [
        {
            'witness_key': 'tba11111tba11111',
            'occasion': 'meeting:118555',
            'event_id': 118555,
            'source': 'congress_gov',
            'name': 'TBA',
            'organization': 'Panel 1',
            'position': 'Witness',
            'listing_status': 'listed',
            'last_listed_on': None,
            'unlisted_since': None,
            'unlisted_by_record_sha': None,
        },
        {
            'witness_key': 'tba22222tba22222',
            'occasion': 'meeting:118555',
            'event_id': 118555,
            'source': 'congress_gov',
            'name': 'TBA',
            'organization': 'Panel 1',
            'position': 'Witness',
            'listing_status': 'no_longer_listed',
            'last_listed_on': '2026-11-01',
            'unlisted_since': '2026-11-05',
            'unlisted_by_record_sha': s2,
        },
    ]
    meetings = [{
        'event_id': 118555,
        'subject_keys': ['118-hr-300'],
        'unlisted_subjects': [],
        'document_references': [],
    }]
    res = retained_check.evaluate(witnesses, meetings, raw_reads, house_docs, house_subjects)
    assert res['flag_count'] == 0, res['flags']
    plants = retained_check.run_plants(witnesses, meetings, raw_reads, house_docs, house_subjects)
    assert plants['still_listed_marked_removed']['caught'] is True
    assert plants['dropped_item_deleted']['caught'] is True

