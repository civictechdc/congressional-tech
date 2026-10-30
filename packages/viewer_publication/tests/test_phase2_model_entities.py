"""Phase-2 entity resolution, spicy-regs projections, and generation pinning."""
from datetime import date
import gzip
import hashlib
import json
import os
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from congress_api.lake import filenames, readings
from congress_api.lake.captures import stage_captures
from congress_api.retention.provenance import parquet_output, run_job
from docspec_client.client import NativeDatasets


def _stage_raw_fixture(tmp_path, engine, capture_specs):
    raw = tmp_path / 'raw'
    raw.mkdir()
    rows = []
    for spec in capture_specs:
        data = spec['data']
        fmt = spec.get('format', 'html')
        compress = spec.get('compress', fmt in ('html', 'xml', 'json', 'vtt', 'm3u8'))
        stored = gzip.compress(data, mtime=0) if compress else data
        digest = hashlib.sha256(data).hexdigest()
        suffix = '.gz' if compress else spec.get('suffix', '')
        key = f'bodies/sha256/{digest[:2]}/{digest}{suffix}'
        path = raw / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(stored)
        url = spec['url']
        rows.append(dict(
            writer=dict(job='fixture', commit='a' * 40),
            run_id='fixture',
            mode='fetch',
            family=spec.get('family', 'documents'),
            outcome='stored',
            requested_url=spec.get('requested_url', url),
            url=url,
            response_headers=spec.get('headers', {}),
            http_status=200,
            complete=True,
            retrieved_at=spec.get('retrieved_at', '2026-10-27T12:00:00Z'),
            captures=[dict(
                sha256=digest,
                bytes=len(data),
                media_type=spec.get('media_type', 'text/html' if fmt == 'html' else 'application/pdf'),
                fidelity='exact-bytes',
                sniffed_format=fmt,
                sniff_version=readings.current_version('sniff'),
                intact=True if fmt == 'pdf' else None,
                stored_suffix=suffix,
                stored_bytes=len(stored),
                stored_md5=hashlib.md5(stored).hexdigest(),
            )],
        ))
    receipt = raw / 'receipts/documents/2026-10-27/slice.jsonl.gz'
    receipt.parent.mkdir(parents=True, exist_ok=True)
    encoded = gzip.compress((''.join(json.dumps(r) + '\n' for r in rows)).encode(), mtime=0)
    receipt.write_bytes(encoded)
    qualification = tmp_path / 'receipt-pin.json'
    qualification.write_text(json.dumps(dict(
        path=str(receipt),
        size=len(encoded),
        sha256=hashlib.sha256(encoded).hexdigest(),
        producer='fixture creation',
    )))
    captures = stage_captures(
        [dict(key=receipt.relative_to(raw).as_posix(), path=str(receipt), qualification=str(qualification))],
        engine=engine,
        work=tmp_path / 'capture-stage',
    ) / 'captures.parquet'
    inventory = tmp_path / 'inventory'
    inventory.mkdir()
    run_job(
        inventory,
        engine,
        inputs=[dict(name='captures', kind='parquet', path=str(captures))],
        steps=[],
        outputs=[parquet_output(
            inventory,
            'bodies',
            """SELECT DISTINCT sha256 AS body_sha,
            'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex')||stored_suffix AS physical_key,
            'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex')||stored_suffix AS relative_path,
            stored_bytes,stored_suffix='.gz' AS stored_gzip FROM captures WHERE sha256 IS NOT NULL""",
            ['body_sha'],
        )],
    )
    pages = readings.stage(
        captures=captures,
        body_inventory=inventory / 'bodies.parquet',
        local_root=raw,
        engine=engine,
        work=tmp_path / 'reading-stage',
        decided_at='2026-10-27T12:00:00Z',
        parser='html',
    )
    names = filenames.stage(
        captures=captures,
        recovery_files=(),
        engine=engine,
        work=tmp_path / 'filename-stage',
        decided_at='2026-10-27T12:00:00Z',
    )
    return dict(
        captures=captures,
        readings=pages['readings'],
        filename_readings=names['readings'],
        parser_versions={p: readings.current_version(p) for p in ['sniff', 'html', 'xml', 'json']},
        catalog_version=names['catalog_version'],
    )


def test_phase2_entities_meetings_witnesses_recordings_and_spicy_projections(tmp_path):
    from viewer_publication.archive_model import build_release

    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    hearing_html = (
        b'<html><head><title>Hearing on H.R. 1234 and PN123</title></head><body><p>'
        + b'Substantive committee hearing record for H.R. 1234 and PN 123. ' * 60
        + b'</p>'
        + b'<a href="https://docs.house.gov/meetings/AG/AG00/20230510/115538/HHRG-118-AG00-Wstate-SmithJ-20230510.pdf">Witness Statement</a>'
        + b'<a href="https://www.youtube.com/watch?v=dQw4w9WgXcQ">Hearing Video</a>'
        + b'</body></html>'
    )
    pdf_bytes = b'%PDF-1.7\nwitness statement bytes\n%%EOF\n'
    chrg_pdf_bytes = b'%PDF-1.7\nprinted hearing transcript bytes\n%%EOF\n'
    vtt_old = b'WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nOld caption track\n'
    vtt_new = b'WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nNew caption track\n'
    vtt_asr = b'WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nAuto caption track\n'
    m3u8_bytes = b'#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:10\n'

    staged = _stage_raw_fixture(tmp_path, engine, [
        dict(
            url='https://www.congress.gov/118/meeting/house/115538/overview.html',
            data=hearing_html,
            format='html',
            family='congress/meetings',
            retrieved_at='2023-05-20T12:00:00Z',
        ),
        dict(
            url='https://docs.house.gov/meetings/AG/AG00/20230510/115538/HHRG-118-AG00-Wstate-SmithJ-20230510.pdf',
            data=pdf_bytes,
            format='pdf',
            compress=False,
            family='documents',
            retrieved_at='2023-05-20T12:00:00Z',
        ),
        dict(
            url='https://www.govinfo.gov/content/pkg/CHRG-118hhrg55555/pdf/CHRG-118hhrg55555.pdf',
            data=chrg_pdf_bytes,
            format='pdf',
            compress=False,
            family='documents',
            retrieved_at='2023-05-20T12:00:00Z',
        ),
        dict(
            url='https://www.youtube.com/api/timedtext?v=dQw4w9WgXcQ&lang=en&fmt=vtt',
            data=vtt_old,
            format='vtt',
            media_type='text/vtt',
            family='youtube/captions',
            retrieved_at='2023-05-20T12:00:00Z',
        ),
        dict(
            url='https://www.youtube.com/api/timedtext?v=dQw4w9WgXcQ&lang=en&fmt=vtt',
            data=vtt_new,
            format='vtt',
            media_type='text/vtt',
            family='youtube/captions',
            retrieved_at='2023-05-21T12:00:00Z',
        ),
        dict(
            url='https://www.youtube.com/api/timedtext?v=dQw4w9WgXcQ&lang=en&kind=asr&fmt=vtt',
            data=vtt_asr,
            format='vtt',
            media_type='text/vtt',
            family='youtube/captions',
            retrieved_at='2023-05-21T12:00:00Z',
        ),
        dict(
            url='https://www-senate-gov-media-srs.akamaized.net/hls/live/2034567/ag/ag051023/master.m3u8',
            data=m3u8_bytes,
            format='m3u8',
            media_type='application/vnd.apple.mpegurl',
            family='senate/captions',
            retrieved_at='2023-05-21T12:00:00Z',
        ),
    ])

    meeting_records = [
        # congress_gov older record for 115538 (should lose to newer congress_gov and house_xml)
        dict(
            record_sha='22' * 32,
            source='congress_gov',
            meetings=[dict(
                event_id='115538',
                chamber='house',
                congress=118,
                session=1,
                updated='2023-05-09T10:00:00Z',
                title='Stale Congress.gov Title',
                meeting_date='2023-05-09',
                meeting_type='Hearing',
                status='Scheduled',
                sittings=[],
                committees=[dict(system_code='HSAG00', role='host')],
                subject_keys=['118-hr-9999'],
                transcript_jackets=['99999'],
                videos=[],
            )],
        ),
        # congress_gov newer record for 115538 (provides transcript_jackets and videos where house_xml is empty)
        dict(
            record_sha='11' * 32,
            source='congress_gov',
            meetings=[dict(
                event_id='115538',
                chamber='house',
                congress=118,
                session=1,
                updated='2023-05-11T10:00:00Z',
                title='Congress.gov Title',
                meeting_date='2023-05-11',
                meeting_type='Markup',
                status='Completed',
                sittings=[],
                committees=[dict(system_code='HSAG00', role='host')],
                subject_keys=['118-hr-1234'],
                transcript_jackets=['55555'],
                videos=[
                    dict(title='YouTube Stream', url='https://youtu.be/dQw4w9WgXcQ', video_key=None),
                    dict(title='Senate ISVP', url='https://www.senate.gov/isvp/?comm=ag&filename=ag051023', video_key=None),
                ],
            )],
        ),
        # house_xml record for 115538 (priority 1: wins scalar fields & non-empty arrays)
        dict(
            record_sha='33' * 32,
            source='house_xml',
            meetings=[dict(
                event_id='115538',
                chamber='House',
                congress=118,
                session=1,
                updated='2023-05-10T14:00:00Z',
                title='House XML Official Title',
                meeting_date='2023-05-10',
                meeting_type='Hearing',
                status='Published',
                sittings=[dict(start='2023-05-10T14:00:00Z', end='2023-05-10T16:00:00Z', room='1300', building='LHOB', address='Washington, DC')],
                committees=[dict(system_code='HSAG00', role='primary')],
                subject_keys=['118-HR-1234', '118-pn-123'],
                transcript_jackets=[],
                videos=[],
            )],
        ),
    ]

    appearance_records = [
        # house_xml appearance for meeting 115538 (priority 1: wins over congress_gov and mods on meeting:115538)
        dict(
            record_sha='aa' * 32,
            source='house_xml',
            appearances=[
                dict(
                    event_id='115538',
                    name_key='smith_jane',
                    name='Dr. Jane Smith',
                    position='Director',
                    organization='Policy Institute',
                    panel='Panel I',
                    panel_order=1,
                    display_order=1,
                    witness_type='non-government',
                    testified=True,
                    document_urls=['https://docs.house.gov/meetings/AG/AG00/20230510/115538/HHRG-118-AG00-Wstate-SmithJ-20230510.pdf'],
                ),
                # Duplicate name_key in same record & occasion: second row must be dropped
                dict(
                    event_id='115538',
                    name_key='smith_jane',
                    name='Dr. Jane Smith Duplicate',
                    position='Duplicate',
                    organization='Duplicate Org',
                    panel='Panel I',
                    panel_order=1,
                    display_order=2,
                    witness_type='non-government',
                    testified=True,
                    document_urls=[],
                ),
            ],
        ),
        # congress_gov appearance for meeting 115538 (priority 2: loses entire occasion to house_xml)
        dict(
            record_sha='bb' * 32,
            source='congress_gov',
            appearances=[
                dict(
                    event_id='115538',
                    name_key='other_person',
                    name='Other Person',
                    position='Other',
                    organization='Other Org',
                    document_urls=[],
                ),
            ],
        ),
        # mods appearance for CHRG-118hhrg55555 (maps to meeting:115538, so loses to house_xml)
        # and mods appearance for unlinked CHRG-118shrg77777 (stays package:CHRG-118shrg77777)
        dict(
            record_sha='cc' * 32,
            source='mods',
            appearances=[
                dict(
                    package_id='CHRG-118hhrg55555',
                    name_key='mods_loser',
                    name='MODS Witness For Linked Package',
                    document_urls=['https://www.govinfo.gov/content/pkg/CHRG-118hhrg55555/pdf/CHRG-118hhrg55555.pdf'],
                ),
                dict(
                    package_id='CHRG-118shrg77777',
                    name_key='roe_richard',
                    name='Hon. Richard Roe',
                    bioguide_id='R000001',
                    testified=True,
                    document_urls=[],
                ),
            ],
        ),
        # senate_page appearance
        dict(
            record_sha='dd' * 32,
            source='senate_page',
            appearances=[
                dict(
                    page_url='https://www.congress.gov/118/meeting/house/115538/overview.html',
                    name_key='doe_john',
                    name='John Doe',
                    organization='Senate Witness Org',
                    display_order=1,
                    document_urls=[],
                ),
            ],
        ),
    ]

    spicy_regs = dict(
        generations={
            'committee-rosters': '1' * 64,
            'members': '2' * 64,
            'bill-family': '3' * 64,
            'nominations': '4' * 64,
            'roll-call-votes': '5' * 64,
        },
        spicy_committees=[
            dict(
                system_code='HSAG00',
                name='Committee on Agriculture',
                chamber='House',
                committee_type='Standing',
                parent_system_code=None,
                website_url='https://agriculture.house.gov/',
                is_current=True,
                history=[
                    dict(
                        officialName='Committee on Agriculture',
                        startDate='2021-01-03T05:00:00Z',
                        endDate='2023-01-03T04:59:59Z',
                    ),
                ],
            ),
        ],
        spicy_members=[
            dict(
                bioguide_id='A000001',
                name_first='Alma',
                name_last='Adams',
                lis_id='S001',
                opensecrets_id='N00000001',
                govtrack_id='400001',
                icpsr_id='20001',
                wikidata_id='Q1',
                fec_ids=['H0NC01001'],
            ),
        ],
        spicy_member_terms=[
            dict(
                bioguide_id='A000001',
                term_type='rep',
                term_state='NC',
                term_district=12,
                term_party='Democrat',
                term_start='2021-01-03',
                term_end='2023-01-03',
            ),
            dict(
                bioguide_id='A000001',
                term_type='sen',
                term_state='NC',
                term_district=None,
                term_party='Democrat',
                term_start='2023-01-03',
                term_end='2025-01-03',
            ),
        ],
        spicy_committee_assignments=[
            dict(
                congress=118,
                system_code='HSAG00',
                bioguide_id='A000001',
                position='Chair',
                rank=1,
                party='Democrat',
            ),
        ],
        spicy_congress_bills=[
            dict(
                bill_id='118-hr-1234',
                title='An Act to support agricultural research.',
                short_title='Ag Research Act',
                sponsor_bioguide_id='A000001',
                introduced_date='2023-03-01',
                latest_action_date='2023-05-15',
                latest_action_text='Ordered to be Reported.',
                stage='committee',
                policy_area='Agriculture and Food',
            ),
            dict(
                bill_id='118-hr-9999',
                title='Unreferenced Bill that must be excluded',
                short_title='Excluded Act',
                sponsor_bioguide_id='A000001',
                introduced_date='2023-01-10',
                latest_action_date='2023-01-10',
                latest_action_text='Introduced',
                stage='introduced',
                policy_area='Other',
            ),
        ],
        spicy_bill_committees=[
            dict(bill_id='118-hr-1234', system_code='HSAG00'),
        ],
        spicy_bill_committee_activities=[
            dict(bill_id='118-hr-1234', system_code='HSAG00', activity_name='Markup by', activity_date='2023-05-10T14:00:00Z', occurrence=2),
            dict(bill_id='118-hr-1234', system_code='HSAG00', activity_name='Referred to', activity_date='2023-03-01T05:00:00Z', occurrence=1),
        ],
        spicy_cbo_cost_estimates=[
            dict(bill_id='118-hr-1234', publication_id='cbo-1', pub_date='2023-05-12T12:00:00Z', description='CBO estimate for H.R. 1234'),
        ],
        spicy_amendments=[
            dict(
                amendment_id='118-hamdt-10',
                purpose='First-degree amendment to bill',
                sponsor_bioguide_id='A000001',
                latest_action_date='2023-05-13',
                latest_action_text='Offered',
                amended_bill_id='118-hr-1234',
                amended_amendment_id=None,
            ),
            dict(
                amendment_id='118-hamdt-11',
                purpose='Second-degree amendment to hamdt 10',
                sponsor_bioguide_id='A000001',
                latest_action_date='2023-05-14',
                latest_action_text='Agreed to',
                amended_bill_id=None,
                amended_amendment_id='118-hamdt-10',
            ),
        ],
        spicy_bill_vote_references=[
            dict(bill_id='118-hr-1234', congress=118, chamber='House', session=1, roll_number=201),
            dict(bill_id='118-hr-1234', congress=118, chamber='House', session=1, roll_number=202),
        ],
        spicy_roll_call_votes=[
            # Vote 201 has BOTH direct bill_id ('vote_record') and bill_vote_reference ('bill_action'); must deduplicate to 'vote_record'
            dict(
                vote_id='118-h-1-201',
                bill_id='118-hr-1234',
                congress=118,
                chamber='h',
                session=1,
                roll_number=201,
                vote_day='2023-05-15',
                question='On Passage',
                result='Passed',
                yea=220,
                nay=210,
                documents=[],
            ),
            # Vote 202 has only bill_vote_reference ('bill_action')
            dict(
                vote_id='118-h-1-202',
                bill_id=None,
                congress=118,
                chamber='h',
                session=1,
                roll_number=202,
                vote_day='2023-05-16',
                question='On Motion to Recommit',
                result='Failed',
                yea=205,
                nay=225,
                documents=[],
            ),
            # Senate nomination vote for PN0123-00 -> 118-pn-123
            dict(
                vote_id='118-s-1-99',
                bill_id=None,
                congress=118,
                chamber='s',
                session=1,
                roll_number=99,
                vote_day='2023-05-18',
                question='On the Nomination',
                result='Confirmed',
                yea=55,
                nay=44,
                documents=[dict(congress=118, type='PN', number='PN0123-00')],
            ),
        ],
        spicy_nominations=[
            dict(
                congress=118,
                number=123,
                part_number='00',
                description=' Jane Roe, to be Under Secretary of Agriculture',
                organization='Department of Agriculture',
                received_date='2023-02-01',
                latest_action_date='2023-05-18',
                latest_action_text='Confirmed by the Senate.',
                committees_json='[{"system_code":"ssaf00","name":"Agriculture"}]',
                hearings_json='[{"package_id":"CHRG-118shrg12345"},{"chamber":"Senate","jacket_number":"67890"}]',
            ),
        ],
    )

    release_dir = tmp_path / 'release'
    manifest = build_release(
        **staged,
        meeting_records=meeting_records,
        appearance_records=appearance_records,
        spicy_regs=spicy_regs,
        engine=engine,
        output=release_dir,
        scratch=tmp_path / 'model',
    )

    files_by_name = {f['name']: f for f in manifest['files']}
    expected_parquet = {
        'list.parquet', 'detail.parquet', 'links.parquet', 'urls.parquet',
        'sources.parquet', 'recoveries.parquet', 'meetings.parquet',
        'witnesses.parquet', 'recordings.parquet', 'committees.parquet',
        'members.parquet', 'rosters.parquet', 'bills.parquet',
        'nominations.parquet', 'url_state.parquet', 'url_variants.parquet',
    }
    assert expected_parquet <= set(files_by_name)

    # Check producer & generations metadata on spicy-regs files
    assert files_by_name['committees.parquet']['producer'] == 'spicy-regs'
    assert files_by_name['committees.parquet']['generations'] == {'committee-rosters': '1' * 64}
    assert files_by_name['rosters.parquet']['coverage']['gaps'] == ['Current-Congress seats only; spicy-regs keeps no roster history']
    assert files_by_name['bills.parquet']['generations'] == {'bill-family': '3' * 64, 'roll-call-votes': '5' * 64}
    assert files_by_name['bills.parquet']['coverage']['gaps'] == ['Amendments cover the 119th Congress only until spicy-regs backfills']
    assert files_by_name['nominations.parquet']['generations'] == {'nominations': '4' * 64, 'roll-call-votes': '5' * 64}
    assert files_by_name['meetings.parquet']['producer'] == 'archive'
    assert 'generations' not in files_by_name['meetings.parquet']

    # 1. Verify meetings.parquet
    meetings = pq.read_table(release_dir / 'meetings.parquet').to_pylist()
    assert len(meetings) == 1
    m = meetings[0]
    assert m['event_id'] == 115538
    assert m['chamber'] == 'house'
    assert m['title'] == 'House XML Official Title'
    assert m['meeting_date'] == date(2023, 5, 10)
    assert m['meeting_type'] == 'Hearing'
    assert m['status'] == 'Published'
    assert m['sittings'][0]['place'] == '1300, LHOB, Washington, DC'
    assert m['committees'] == [{'system_code': 'hsag00', 'role': 'primary'}]
    assert m['subject_keys'] == ['118-hr-1234', '118-pn-123']
    assert len(m['transcripts']) == 1
    assert m['transcripts'][0]['package_id'] == 'CHRG-118hhrg55555'
    assert [v['video_key'] for v in m['videos']] == ['youtube:dQw4w9WgXcQ', 'senate:ag051023']

    # Verify CHRG document linked to meeting 115538 and inherited meeting_date, without individual witness_keys
    listed = pq.read_table(release_dir / 'list.parquet').to_pylist()
    chrg_doc = next(r for r in listed if r['filename'] == 'CHRG-118hhrg55555.pdf')
    stmt_doc = next(r for r in listed if 'Wstate-SmithJ' in r['filename'])
    assert chrg_doc['meeting_keys'] == ['115538']
    assert chrg_doc['document_date'] == date(2023, 5, 10)
    assert chrg_doc['witness_keys'] == []
    assert len(stmt_doc['witness_keys']) == 1

    # 2. Verify witnesses.parquet
    witnesses = pq.read_table(release_dir / 'witnesses.parquet').to_pylist()
    by_occasion = {w['occasion']: w for w in witnesses}
    assert len(witnesses) == 3
    assert 'meeting:115538' in by_occasion
    assert by_occasion['meeting:115538']['name'] == 'Dr. Jane Smith'
    assert by_occasion['meeting:115538']['witness_key'] == stmt_doc['witness_keys'][0]
    assert 'package:CHRG-118shrg77777' in by_occasion
    assert by_occasion['package:CHRG-118shrg77777']['bioguide_id'] == 'R000001'
    page_occasions = [k for k in by_occasion if k.startswith('page:')]
    assert len(page_occasions) == 1
    assert by_occasion[page_occasions[0]]['name'] == 'John Doe'

    # 3. Verify recordings.parquet
    recordings = {r['video_key']: r for r in pq.read_table(release_dir / 'recordings.parquet').to_pylist()}
    assert {'youtube:dQw4w9WgXcQ', 'senate:ag051023'} <= set(recordings)
    yt = recordings['youtube:dQw4w9WgXcQ']
    assert yt['event_ids'] == [115538]
    tracks = {(t['format'], t['language'], t['production']): t for t in yt['tracks']}
    assert set(tracks) == {('vtt', 'en', 'asr'), ('vtt', 'en', 'caption')}
    assert tracks[('vtt', 'en', 'caption')]['body'] == hashlib.sha256(vtt_new).digest()
    assert tracks[('vtt', 'en', 'asr')]['body'] == hashlib.sha256(vtt_asr).digest()
    assert recordings['senate:ag051023']['tracks'][0]['format'] == 'm3u8'
    assert recordings['senate:ag051023']['tracks'][0]['body'] == hashlib.sha256(m3u8_bytes).digest()

    # 4. Verify committees.parquet (including Eastern date conversion)
    committees = pq.read_table(release_dir / 'committees.parquet').to_pylist()
    assert committees == [dict(
        system_code='hsag00',
        name='Committee on Agriculture',
        chamber='house',
        committee_type='standing',
        parent_system_code=None,
        names=[dict(name='Committee on Agriculture', start=date(2021, 1, 3), end=date(2023, 1, 3))],
        website='https://agriculture.house.gov/',
        is_current=True,
    )]

    # 5. Verify members.parquet and rosters.parquet
    members = pq.read_table(release_dir / 'members.parquet').to_pylist()
    assert len(members) == 1
    assert members[0]['bioguide_id'] == 'A000001'
    assert members[0]['name'] == 'Alma Adams'
    assert [t['chamber'] for t in members[0]['terms']] == ['senate', 'house']
    assert members[0]['cross_ids']['fec'] == ['H0NC01001']

    rosters = pq.read_table(release_dir / 'rosters.parquet').to_pylist()
    assert rosters == [dict(
        congress=118,
        system_code='hsag00',
        bioguide_id='A000001',
        title='Chair',
        rank=1,
        party='Democrat',
    )]

    # 6. Verify bills.parquet (referenced only, chained amendments, deduplicated votes, ordered activities)
    bills = pq.read_table(release_dir / 'bills.parquet').to_pylist()
    assert [b['bill_id'] for b in bills] == ['118-hr-1234']
    bill = bills[0]
    assert [a['amendment_id'] for a in bill['amendments']] == ['118-hamdt-10', '118-hamdt-11']
    assert [(v['vote_id'], v['basis']) for v in bill['floor_votes']] == [
        ('118-h-1-201', 'vote_record'),
        ('118-h-1-202', 'bill_action'),
    ]
    assert [act['activity'] for act in bill['committee_activities']] == ['Referred to', 'Markup by']

    # 7. Verify nominations.parquet (referenced only, parsed committees/hearings, matched PN vote)
    nominations = pq.read_table(release_dir / 'nominations.parquet').to_pylist()
    assert len(nominations) == 1
    nom = nominations[0]
    assert nom['nomination_id'] == '118-pn-123'
    assert nom['committees'] == ['ssaf00']
    assert nom['transcripts'] == ['CHRG-118shrg12345', 'CHRG-118shrg67890']
    assert len(nom['floor_votes']) == 1
    assert nom['floor_votes'][0]['vote_id'] == '118-s-1-99'


def test_spicy_generations_pinned_by_publish_and_maintenance():
    from viewer_publication.archive_maintenance import maintain_releases
    from viewer_publication.archive_publish import SPICY_PINS, input_digest
    from viewer_publication.receipt_pins import PREFIX, write_input_receipts
    from test_archive_maintenance import LIVE, NOW, OLD, PINNED, PREVIOUS, Store, add_input
    from datetime import timedelta

    d1 = input_digest(
        receipt_keys=['receipts/documents/a.jsonl.gz'],
        provenance=[],
        profile={'v': 1},
        entity_digests={'members': '1' * 64, 'bill-family': '2' * 64},
    )
    d2 = input_digest(
        receipt_keys=['receipts/documents/a.jsonl.gz'],
        provenance=[],
        profile={'v': 1},
        entity_digests={'members': '9' * 64, 'bill-family': '2' * 64},
    )
    assert d1 != d2
    with pytest.raises(ValueError, match='phase one'):
        input_digest(
            receipt_keys=['receipts/documents/a.jsonl.gz'],
            provenance=[],
            profile={'v': 1},
            entity_digests={'members': 'not-a-sha'},
        )

    store = Store()
    for idx, (rel, ident) in enumerate([(LIVE, 'one'), (LIVE, 'two'), (PREVIOUS, 'previous'), (PINNED, 'external')]):
        rec = add_input(store, rel, ident)
        for k in list(store.objects):
            if k.startswith(PREFIX + rel + '/inputs/'):
                del store.objects[k]
        rec['entity_digests'] = {'members': str((idx % 2) + 1) * 64, 'nominations': 'a' * 64}
        rec['snapshots']['meeting_records'] = dict(
            kind='parquet', path='/not-opened/meeting_records.parquet', sha256='b' * 64, size=19
        )
        keys = ['receipts/documents/' + ident + '.jsonl.gz']
        rec['input_digest'] = input_digest(
            receipt_keys=keys,
            provenance=rec['provenance'],
            profile=rec['profile'],
            entity_digests=rec['entity_digests'],
        )
        write_input_receipts(store, rel, rec['input_digest'], rec, keys)
    store.create(PREFIX + OLD + '/manifest.json', b'{}')
    store.times[PREFIX + OLD + '/manifest.json'] = NOW - timedelta(days=2)

    result = maintain_releases(store, now=NOW, external_pins=[PINNED], execute=True)
    expected_generations = [
        {'family': 'members', 'digest': '1' * 64},
        {'family': 'members', 'digest': '2' * 64},
        {'family': 'nominations', 'digest': 'a' * 64},
    ]
    assert result['spicy_generations'] == expected_generations
    pinned_doc = json.loads(store.objects[SPICY_PINS])
    assert pinned_doc == {
        'version': 1,
        'generations': expected_generations,
    }
