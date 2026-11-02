"""Phase-2 entity resolution, spicy-regs projections, and generation pinning."""
from datetime import date
import gzip
import hashlib
import json
import os
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from congress_api.lake import appearance_records as ar_lake, filenames, meeting_records as mr_lake, readings
from congress_api.lake.capture_staging import stage_captures
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
        parser_versions={
            **{p: readings.current_version(p) for p in ['sniff', 'html', 'xml', 'json']},
            'meeting_records': mr_lake.current_versions(),
            'appearance_records': ar_lake.current_versions(),
        },
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
    segment_bytes = b'G@\x00\x10' + bytes(184)

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
        # The same package's HTML, listed apart from its PDF: still one transcript entry.
        dict(
            url='https://www.govinfo.gov/content/pkg/CHRG-118hhrg55555/html/CHRG-118hhrg55555.htm',
            data=b'<html><head><title>Printed hearing</title></head><body><pre>' + b'Printed hearing transcript text. ' * 60 + b'</pre></body></html>',
            format='html',
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
        # A stream segment is media, never a track or a document (annex §2), even when fetched.
        dict(
            url='https://www-senate-gov-media-srs.akamaized.net/hls/live/2034567/ag/ag051023/master0.ts',
            data=segment_bytes,
            format='other',
            media_type='video/MP2T',
            compress=False,
            family='senate/players',
            retrieved_at='2023-05-22T12:00:00Z',
        ),
        # Legacy segment rows carry no media type (green-e1: three 206 MP2T samples); the segment
        # registry's extension classifies them as media.
        dict(
            url='https://www-senate-gov-msl3archive.akamaized.net/ag/ag051023_1/master0.ts',
            data=segment_bytes + b'legacy',
            format='other',
            media_type=None,
            compress=False,
            family='senate/players',
            retrieved_at='2023-05-22T12:00:00Z',
        ),
        # A newer empty caption body is a failed attempt, not a track (ct-fh62).
        dict(
            url='https://www.youtube.com/api/timedtext?v=dQw4w9WgXcQ&lang=en&fmt=vtt',
            data=b'',
            format='empty',
            media_type='text/vtt',
            family='youtube/captions',
            retrieved_at='2023-05-22T12:00:00Z',
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
                # Repeated name_key in same record & occasion with distinct display_order / locator:
                # ct-30fp AC 4 & 6: both occurrences are preserved with distinct source_locators and witness_keys
                dict(
                    event_id='115538',
                    name_key='smith_jane',
                    name='Dr. Jane Smith Second Panel',
                    position='Senior Advisor',
                    organization='Advisory Board',
                    panel='Panel II',
                    panel_order=2,
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
        dict(
            record_sha='cc' * 32,
            source='mods',
            package_id='CHRG-118hhrg55555',
            appearances=[
                dict(
                    name_key='mods_loser',
                    name='MODS Witness For Linked Package',
                    document_urls=['https://www.govinfo.gov/content/pkg/CHRG-118hhrg55555/pdf/CHRG-118hhrg55555.pdf'],
                ),
            ],
        ),
        # mods appearance for unlinked CHRG-118shrg77777 (stays package:CHRG-118shrg77777)
        dict(
            record_sha='ce' * 32,
            source='mods',
            package_id='CHRG-118shrg77777',
            appearances=[
                dict(
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

    # Check producer, generations, coverage, and gaps metadata on Phase-2 files
    assert files_by_name['committees.parquet']['producer'] == 'spicy-regs'
    assert files_by_name['committees.parquet']['generations'] == {'committee-rosters': '1' * 64}
    assert files_by_name['committees.parquet']['coverage']['date_start'] == '2021-01-03'
    assert files_by_name['committees.parquet']['coverage']['date_end'] == '2023-01-03'
    assert files_by_name['members.parquet']['coverage']['date_start'] == '2021-01-03'
    assert files_by_name['members.parquet']['coverage']['date_end'] == '2025-01-03'
    assert files_by_name['rosters.parquet']['coverage']['congress_start'] == 118
    assert files_by_name['rosters.parquet']['coverage']['congress_end'] == 118
    assert files_by_name['rosters.parquet']['coverage']['gaps'] == ['Current-Congress seats only; spicy-regs keeps no roster history']
    assert files_by_name['bills.parquet']['generations'] == {'bill-family': '3' * 64, 'roll-call-votes': '5' * 64}
    assert files_by_name['bills.parquet']['coverage']['gaps'] == ['Amendments cover the 119th Congress only until spicy-regs backfills']
    assert files_by_name['nominations.parquet']['generations'] == {'nominations': '4' * 64, 'roll-call-votes': '5' * 64}
    assert files_by_name['nominations.parquet']['coverage']['gaps'] == ['Nominations cover the 119th Congress only until spicy-regs backfills']
    assert files_by_name['meetings.parquet']['producer'] == 'archive'
    assert files_by_name['meetings.parquet']['coverage']['congress_start'] == 118
    assert files_by_name['meetings.parquet']['coverage']['congress_end'] == 118
    assert files_by_name['meetings.parquet']['coverage']['date_start'] == '2023-05-10'
    assert files_by_name['meetings.parquet']['coverage']['date_end'] == '2023-05-10'
    assert files_by_name['witnesses.parquet']['coverage']['congress_start'] == 118
    assert files_by_name['witnesses.parquet']['coverage']['congress_end'] == 118
    assert files_by_name['witnesses.parquet']['coverage']['date_start'] == '2023-05-10'
    assert files_by_name['witnesses.parquet']['coverage']['date_end'] == '2023-05-10'
    assert 'generations' not in files_by_name['meetings.parquet']

    # Check lake_versions pins and job settings for sort order, Invariant 15, and Annex §2 diagnostics
    profile_doc = json.loads((tmp_path / 'model/profile.json').read_text())
    assert {'captures', 'readings', 'filename_readings', 'meeting_records', 'appearance_records'} <= set(
        profile_doc['profile']['lake_versions']
    )
    job_doc = json.loads((tmp_path / 'model/job.json').read_text())
    outputs_by_name = {o['name']: o for o in job_doc['outputs']}
    assert [f['field'] for f in outputs_by_name['witnesses.parquet']['settings']['order_by']] == [
        'occasion', 'panel_order', 'display_order', 'witness_key',
    ]
    assert [f['field'] for f in outputs_by_name['rosters.parquet']['settings']['order_by']] == [
        'congress', 'system_code', 'rank', 'bioguide_id',
    ]
    assert [f['field'] for f in outputs_by_name['url_variants.parquet']['settings']['order_by']] == [
        'variant_url', 'canonical_url',
    ]
    result_doc = json.loads((tmp_path / 'model/result.json').read_text())
    queries_by_name = {q['name']: q['data'] for q in result_doc['queries']}
    inv = queries_by_name['model_invariants'][0]
    for key in (
        'multi_chamber_events',
        'missing_meeting_keys',
        'invalid_transcript_rows',
        'invalid_url_rows',
        'single_doc_version_keys',
        'missing_witness_keys',
        'missing_committee_keys',
    ):
        assert inv[key] == 0
    ent_comp = queries_by_name['entity_profile_completeness'][0]
    assert all(v == 0 for v in ent_comp.values())
    assert len(queries_by_name['senate_cards_without_links']) == 1
    assert queries_by_name['senate_cards_without_links'][0]['name_key'] == 'doe_john'

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
    assert m['transcripts'][0]['formats'] == ['pdf', 'html']
    assert [v['video_key'] for v in m['videos']] == ['youtube:dQw4w9WgXcQ', 'senate:ag051023']

    # Verify CHRG document linked to meeting 115538 and inherited meeting_date, without individual witness_keys
    listed = pq.read_table(release_dir / 'list.parquet').to_pylist()
    chrg_doc = next(r for r in listed if r['filename'] == 'CHRG-118hhrg55555.pdf')
    assert [r['format'] for r in listed if r['filename'].startswith('CHRG-118hhrg55555.')] == ['html', 'pdf']
    assert m['transcripts'][0]['list_row'] == listed.index(chrg_doc)  # The PDF, though the HTML lists first.
    stmt_doc = next(r for r in listed if 'Wstate-SmithJ' in r['filename'])
    assert not any(r['filename'].endswith('.ts') for r in listed)
    assert chrg_doc['meeting_keys'] == ['115538']
    assert chrg_doc['document_date'] == date(2023, 5, 10)
    assert chrg_doc['witness_keys'] == []
    assert len(stmt_doc['witness_keys']) == 1

    # 2. Verify witnesses.parquet
    witnesses = pq.read_table(release_dir / 'witnesses.parquet').to_pylist()
    assert len(witnesses) == 4
    meeting_witnesses = [w for w in witnesses if w['occasion'] == 'meeting:115538']
    assert len(meeting_witnesses) == 2
    assert [w['name'] for w in meeting_witnesses] == ['Dr. Jane Smith', 'Dr. Jane Smith Second Panel']
    assert meeting_witnesses[0]['witness_key'] != meeting_witnesses[1]['witness_key']
    assert meeting_witnesses[0]['witness_key'] == stmt_doc['witness_keys'][0]
    by_occasion = {w['occasion']: w for w in witnesses if w['occasion'] != 'meeting:115538'}
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
    assert hashlib.sha256(segment_bytes).digest() not in {t['body'] for t in recordings['senate:ag051023']['tracks']}

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


    # A digest the input never stated must not become an upstream URL.
    released_schema = json.loads((release_dir / 'schema.json').read_text())
    assert not any('path' in relation for relation in released_schema['upstream_relations'] if relation['family'] not in (spicy_regs.get('generations') or {}))

    # Explorer tables need their own version pins, and only pinned copies count.
    explorer_versions = dict(staged['parser_versions'], video_records={'youtube_cache': 'pv', 'youtube_api': 'pa'}, committee_records={'house_xml': 'pc'})
    staged = dict(staged, parser_versions=explorer_versions)
    # The same inputs with the Explorer tables: all five appear, and old-shaped outputs do not move.
    from congress_api.lake import committee_records as cr_lake, video_records as vr_lake
    video_path, committee_path, decisions = tmp_path / 'video.parquet', tmp_path / 'committee.parquet', tmp_path / 'decisions.jsonl'
    pq.write_table(vr_lake.table([]), video_path)
    pq.write_table(cr_lake.table([]), committee_path)
    decisions.write_text(json.dumps(dict(id='a' * 64, subject_kind='event', subject_id='115538', verdict='found',
        video_refs=['https://example.test/watch'], note=None, disputed_by=None, decided_at=None, supersedes=None)) + '\n')
    explorer = build_release(**staged, meeting_records=meeting_records, appearance_records=appearance_records, spicy_regs=spicy_regs,
        video_records=video_path, committee_records=committee_path,
        recording_decision_files=[dict(key='provenance/recording_decisions/a.jsonl', path=str(decisions))],
        engine=engine, output=tmp_path / 'release-explorer', scratch=tmp_path / 'model-explorer')
    with_tables = {f['name']: f for f in explorer['files']}
    assert {'videos.parquet', 'channels.parquet', 'recording_matches.parquet', 'committee_records.parquet', 'meeting_coverage.parquet'} <= with_tables.keys()
    assert not {'videos.parquet', 'meeting_coverage.parquet'} & files_by_name.keys()
    for name in ('list.parquet', 'detail.parquet', 'meetings.parquet', 'witnesses.parquet'):
        assert with_tables[name]['sha256'] == files_by_name[name]['sha256'], name
    assert with_tables['channels.parquet']['rows'] == 119 and with_tables['videos.parquet']['rows'] == 0
    assert with_tables['meeting_coverage.parquet']['rows'] == 5 * with_tables['meetings.parquet']['rows']
    curated = pq.read_table(tmp_path / 'release-explorer/recording_matches.parquet').to_pylist()
    assert [(r['event_id'], r['url'], r['status']) for r in curated if r['basis'] == 'curated'] == [(115538, 'https://example.test/watch', 'decided')]


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


def test_phase2_invariant15_diagnostics_and_entity_completeness_guards(tmp_path):
    from viewer_publication.archive_model import build_release

    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    staged = _stage_raw_fixture(tmp_path, engine, [
        dict(
            url='https://docs.house.gov/meetings/AG/AG00/20230510/115538/HHRG-118-AG00-Wstate-SmithJ-20230510.pdf',
            data=b'%PDF-1.7\nwitness statement bytes\n%%EOF\n',
            format='pdf',
            compress=False,
            family='documents',
            retrieved_at='2023-05-20T12:00:00Z',
        ),
    ])
    min_spicy = dict(
        spicy_committees=[
            dict(
                system_code='HSAG00',
                name='Committee on Agriculture',
                chamber='House',
                committee_type='Standing',
                parent_system_code=None,
                website_url='https://agriculture.house.gov/',
                is_current=True,
                history=[],
            ),
            dict(
                system_code='HSIF00',
                name='Committee on Energy and Commerce',
                chamber='House',
                committee_type='Standing',
                parent_system_code=None,
                website_url='https://energycommerce.house.gov/',
                is_current=True,
                history=[],
            ),
        ],
    )

    # 1. Verify non-fatal appearance_name_key_variants report detects multi-title and multi-initial variants within one occasion
    valid_meetings = [
        dict(
            record_sha='11' * 32,
            source='house_xml',
            meetings=[dict(
                event_id='115538',
                chamber='house',
                congress=118,
                session=1,
                updated='2023-05-10T14:00:00Z',
                title='House Hearing',
                meeting_date='2023-05-10',
                meeting_type='Hearing',
                status='Published',
                sittings=[],
                committees=[dict(system_code='hsif00', role='host')],
                subject_keys=[],
                transcript_jackets=[],
                videos=[],
            )],
        ),
    ]
    variant_appearances = [
        dict(
            record_sha='aa' * 32,
            source='house_xml',
            appearances=[
                dict(
                    event_id='115538',
                    name_key='the honorable dr jane smith',
                    name='The Honorable Dr. Jane Smith',
                    panel_order=1,
                    display_order=1,
                    document_urls=['https://docs.house.gov/meetings/AG/AG00/20230510/115538/HHRG-118-AG00-Wstate-SmithJ-20230510.pdf'],
                ),
                dict(
                    event_id='115538',
                    name_key='jane smith',
                    name='Jane Smith',
                    panel_order=1,
                    display_order=2,
                    document_urls=[],
                ),
                dict(
                    event_id='115538',
                    name_key='john q p public',
                    name='John Q. P. Public',
                    panel_order=1,
                    display_order=3,
                    document_urls=[],
                ),
                dict(
                    event_id='115538',
                    name_key='john public',
                    name='John Public',
                    panel_order=1,
                    display_order=4,
                    document_urls=[],
                ),
            ],
        ),
    ]
    build_release(
        **staged,
        meeting_records=valid_meetings,
        appearance_records=variant_appearances,
        spicy_regs=min_spicy,
        engine=engine,
        output=tmp_path / 'release-variants',
        scratch=tmp_path / 'model-variants',
    )
    res_variants = json.loads((tmp_path / 'model-variants/result.json').read_text())
    q_variants = {q['name']: q['data'] for q in res_variants['queries']}
    assert q_variants['appearance_name_key_variants'] == [
        dict(
            occasion='meeting:115538',
            base_key='jane smith',
            first_name_key='jane smith',
            second_name_key='the honorable dr jane smith',
            variant_count=2,
        ),
        dict(
            occasion='meeting:115538',
            base_key='john public',
            first_name_key='john public',
            second_name_key='john q p public',
            variant_count=2,
        ),
    ]

    # 1b. Verify Invariant 15 missing_committee_keys refuses when committees_export is empty (0 rows) and committee_keys exist
    with pytest.raises(ValueError, match='Release key invariant failed'):
        build_release(
            **staged,
            meeting_records=valid_meetings,
            appearance_records=variant_appearances,
            spicy_regs=None,
            engine=engine,
            output=tmp_path / 'release-empty-committees',
            scratch=tmp_path / 'model-empty-committees',
        )
    res_empty_comm = json.loads((tmp_path / 'model-empty-committees/result.json').read_text())
    inv_empty_comm = next(q['data'][0] for q in res_empty_comm['queries'] if q['name'] == 'model_invariants')
    assert inv_empty_comm['missing_committee_keys'] > 0

    # 2. Verify Invariant 15 multi_chamber_events refuses a release when one event_id names two chambers
    conflicting_meetings = valid_meetings + [
        dict(
            record_sha='22' * 32,
            source='congress_gov',
            meetings=[dict(
                event_id='115538',
                chamber='senate',
                congress=118,
                session=1,
                updated='2023-05-10T14:00:00Z',
                title='Conflicting Chamber Meeting',
                meeting_date='2023-05-10',
                meeting_type='Hearing',
                status='Published',
                sittings=[],
                committees=[],
                subject_keys=[],
                transcript_jackets=[],
                videos=[],
            )],
        ),
    ]
    with pytest.raises(ValueError, match='Release key invariant failed'):
        build_release(
            **staged,
            meeting_records=conflicting_meetings,
            appearance_records=variant_appearances,
            spicy_regs=min_spicy,
            engine=engine,
            output=tmp_path / 'release-conflict',
            scratch=tmp_path / 'model-conflict',
        )

    # 3. Verify entity_profile_completeness refuses duplicate (record_sha, parser_version) rows
    with pytest.raises(ValueError, match='Release key invariant failed'):
        build_release(
            **staged,
            meeting_records=valid_meetings + valid_meetings,
            appearance_records=variant_appearances,
            spicy_regs=min_spicy,
            engine=engine,
            output=tmp_path / 'release-dup',
            scratch=tmp_path / 'model-dup',
        )


def test_senate_coldfusion_download_query_stripped_in_witness_document_matching(tmp_path):
    """ct-v51p: aging, appropriations, banking, budget, finance, and veterans strip ?download=1 / &download=1 in url_key."""
    from viewer_publication.archive_model import build_release

    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    hosts = ('aging', 'appropriations', 'banking', 'budget', 'finance', 'veterans')
    pdf_bytes = b'%PDF-1.7\nsenate testimony pdf bytes\n%%EOF\n'
    capture_specs = []
    appearances = []
    for idx, host in enumerate(hosts, start=1):
        # Exercise all 4 combinations required by ct-v51p AC 4 across the 6 Senate ColdFusion hosts:
        # 1 (testimony-a): capture ?download=1 vs card bare
        # 2 (testimony-b): capture bare vs card ?download=1
        # 3 (testimony-c): capture ?download=1 vs card &download=1
        # 4 (testimony-d): capture bare vs card &download=1
        combo = (idx - 1) % 4
        if combo == 0:
            base = f'https://www.{host}.senate.gov/download/testimony-a' if idx == 1 else f'https://www.{host}.senate.gov/download/witness-{host}-statement'
            capture_url = f'{base}?download=1'
            card_url = base
        elif combo == 1:
            base = f'https://www.{host}.senate.gov/download/testimony-b' if idx == 2 else f'https://www.{host}.senate.gov/download/witness-{host}-statement'
            capture_url = base
            card_url = f'{base}?download=1'
        elif combo == 2:
            base = f'https://www.{host}.senate.gov/download/testimony-c'
            capture_url = f'{base}?download=1'
            card_url = f'{base}&download=1'
        else:
            base = f'https://www.{host}.senate.gov/download/testimony-d'
            capture_url = base
            card_url = f'{base}&download=1'
        capture_specs.append(dict(
            url=capture_url,
            data=pdf_bytes + f'\n% {host}\n'.encode(),
            format='pdf',
            compress=False,
            family='documents',
            retrieved_at='2023-05-20T12:00:00Z',
        ))
        appearances.append(dict(
            event_id='335001',
            page_url='https://www.finance.senate.gov/hearings/senate-coldfusion-hearing',
            name_key=f'witness {host}',
            name=f'Witness {host.title()}',
            panel_order=1,
            display_order=idx,
            document_urls=[card_url],
        ))

    staged = _stage_raw_fixture(tmp_path, engine, capture_specs)
    meetings = [dict(
        record_sha='33' * 32,
        source='congress_gov',
        meetings=[dict(
            event_id='335001',
            chamber='senate',
            congress=118,
            session=1,
            updated='2023-05-10T14:00:00Z',
            title='Senate Hearing',
            meeting_date='2023-05-10',
            meeting_type='Hearing',
            status='Scheduled',
            sittings=[],
            committees=[],
            subject_keys=[],
            transcript_jackets=[],
            videos=[],
        )],
    )]
    appearance_rows = [dict(
        record_sha='44' * 32,
        source='senate_page',
        appearances=appearances,
    )]
    build_release(
        **staged,
        meeting_records=meetings,
        appearance_records=appearance_rows,
        engine=engine,
        output=tmp_path / 'release-senate-dl',
        scratch=tmp_path / 'model-senate-dl',
    )
    list_rows = pq.read_table(tmp_path / 'release-senate-dl/list.parquet').to_pylist()
    assert len(list_rows) == 6
    assert all(row['witness_keys'] and len(row['witness_keys']) == 1 for row in list_rows)
    # urls.parquet lookup_url remains untouched (only #fragment stripped, query preserved)
    url_rows = pq.read_table(tmp_path / 'release-senate-dl/urls.parquet').to_pylist()
    assert len(url_rows) == 6


def test_context_free_a_then_b_capture_binding_and_collection_states(tmp_path):
    """ct-30fp AC 1, 2, 3 & Note:
    - Context-free senate_page bytes captured first at URL A and later at URL B resolve to both contexts,
      and capturing at B does NOT refresh A's older observation over a newer distinct body at A.
    - Explicit empty ('empty') replaces lower-priority sources without falling back.
    - 'absent' falls back to lower-priority sources.
    - 'unrecognized' blocks fallback to lower-priority sources.
    """
    from viewer_publication.archive_model import build_release

    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    shared_html = (
        b'<html><head><title>Senate Hearing Shared</title></head><body>'
        + b'<p>Substantive Senate hearing page content for shared body. ' * 50 + b'</p>'
        + b'<div class="paragraph--witness"><div class="witness__field-name">Shared Body Witness</div></div>'
        + b'</body></html>'
    )
    updated_a_html = (
        b'<html><head><title>Senate Hearing A Updated</title></head><body>'
        + b'<p>Updated substantive Senate hearing page content for URL A. ' * 50 + b'</p>'
        + b'<div class="paragraph--witness"><div class="witness__field-name">Updated A Witness</div></div>'
        + b'</body></html>'
    )
    sha_shared = hashlib.sha256(shared_html).hexdigest()
    sha_updated_a = hashlib.sha256(updated_a_html).hexdigest()
    url_a = 'https://www.banking.senate.gov/hearings/hearing-a'
    url_b = 'https://www.banking.senate.gov/hearings/hearing-b'
    pdf_bytes = b'%PDF-1.7\nstatement\n%%EOF\n'
    wlist_old = b'<?xml version="1.0"?><witness-list meeting-id="HHRG2004"><panel sort-order="1"><witness display-order="1"><witness-name><firstname>Stale</firstname><lastname>Witness</lastname></witness-name></witness></panel></witness-list>'
    wlist_empty = b'<?xml version="1.0"?><witness-list meeting-id="HHRG2004"></witness-list>'
    wlist_dup1 = b'<?xml version="1.0"?><witness-list meeting-id="HHRG2005"><panel sort-order="1"><witness display-order="1"><witness-name><firstname>Earlier</firstname><lastname>Witness</lastname></witness-name></witness></panel></witness-list>'
    wlist_dup2 = b'<?xml version="1.0"?><witness-list meeting-id="HHRG2005"><panel sort-order="1"><witness display-order="1"><witness-name><firstname>Fresher</firstname><lastname>Witness</lastname></witness-name></witness></panel></witness-list>'
    sha_wlist_old = hashlib.sha256(wlist_old).hexdigest()
    sha_wlist_empty = hashlib.sha256(wlist_empty).hexdigest()
    sha_wlist_dup1 = hashlib.sha256(wlist_dup1).hexdigest()
    sha_wlist_dup2 = hashlib.sha256(wlist_dup2).hexdigest()

    staged = _stage_raw_fixture(tmp_path, engine, [
        dict(url=url_a, data=shared_html, format='html', family='senate/pages', retrieved_at='2023-05-10T12:00:00Z'),
        dict(url=url_a, data=updated_a_html, format='html', family='senate/pages', retrieved_at='2023-05-20T12:00:00Z'),
        dict(url=url_b, data=shared_html, format='html', family='senate/pages', retrieved_at='2023-05-25T12:00:00Z'),
        dict(url='https://docs.house.gov/meetings/AG/AG00/20230510/2001/HHRG-118-AG00-Wstate-Test-20230510.pdf',
             data=pdf_bytes, format='pdf', compress=False, family='documents', retrieved_at='2023-05-20T12:00:00Z'),
        # 2004: older URL 1 has 'present' witness list, newer URL 2 has revised 'empty' witness list
        dict(url='https://docs.house.gov/meetings/AG/AG00/20230510/2004/HHRG-118-AG00-WList-20230510-v1.xml',
             data=wlist_old, format='xml', media_type='text/xml', family='house/witness-xml', retrieved_at='2023-05-10T12:00:00Z'),
        dict(url='https://docs.house.gov/meetings/AG/AG00/20230510/2004/HHRG-118-AG00-WList-20230510-v2.xml',
             data=wlist_empty, format='xml', media_type='text/xml', family='house/witness-xml', retrieved_at='2023-05-11T12:00:00Z'),
        # 2005: two 'present' captures at different URLs for the same (occasion, source) -> only fresher one wins without duplication
        dict(url='https://docs.house.gov/meetings/AG/AG00/20230510/2005/HHRG-118-AG00-WList-20230510-a.xml',
             data=wlist_dup1, format='xml', media_type='text/xml', family='house/witness-xml', retrieved_at='2023-05-10T12:00:00Z'),
        dict(url='https://docs.house.gov/meetings/AG/AG00/20230510/2005/HHRG-118-AG00-WList-20230510-b.xml',
             data=wlist_dup2, format='xml', media_type='text/xml', family='house/witness-xml', retrieved_at='2023-05-12T12:00:00Z'),
    ])
    import pyarrow as pa
    xml_pages = readings.stage(
        captures=staged['captures'],
        body_inventory=tmp_path / 'inventory/bodies.parquet',
        local_root=tmp_path / 'raw',
        engine=engine,
        work=tmp_path / 'reading-xml-ctx-stage',
        decided_at='2026-10-27T12:00:00Z',
        parser='xml',
        existing=staged['readings'],
    )
    combined_readings = tmp_path / 'combined-ctx-readings.parquet'
    pq.write_table(
        pa.concat_tables([pq.read_table(staged['readings']), pq.read_table(xml_pages['readings'])]),
        combined_readings,
    )
    staged['readings'] = combined_readings

    meetings = [
        dict(
            record_sha='11' * 32,
            source='house_xml',
            meetings=[
                dict(event_id=str(eid), chamber='house', congress=118, session=1, updated='2023-05-10T14:00:00Z',
                     title=f'Hearing {eid}', meeting_date='2023-05-10', meeting_type='Hearing', status='Published',
                     sittings=[], committees=[], subject_keys=[], transcript_jackets=[], videos=[])
                for eid in (2001, 2002, 2003, 2004, 2005)
            ],
        ),
    ]
    appearances = [
        # Context-free senate_page observations (no context_url stored in the observation rows!)
        ar_lake.build_appearance_record_row(sha_shared, 'senate_page', shared_html,
                                            parser_version=ar_lake.current_version('senate_page')),
        ar_lake.build_appearance_record_row(sha_updated_a, 'senate_page', updated_a_html,
                                            parser_version=ar_lake.current_version('senate_page')),
        # 2001: house_xml 'empty' replaces congress_gov 'present' -> 0 witnesses on meeting:2001
        dict(record_sha='a1' * 32, source='house_xml', event_id=2001, collection_state='empty', appearances=[]),
        dict(record_sha='b1' * 32, source='congress_gov', event_id=2001, collection_state='present',
             appearances=[dict(source_locator='congress_gov:witness[1]', name_key='cg fallback 2001', name='CG Fallback 2001', document_links=[])]),
        # 2002: house_xml 'absent' falls back to congress_gov 'present' -> 'CG Fallback 2002'
        dict(record_sha='a2' * 32, source='house_xml', event_id=2002, collection_state='absent', appearances=[]),
        dict(record_sha='b2' * 32, source='congress_gov', event_id=2002, collection_state='present',
             appearances=[dict(source_locator='congress_gov:witness[1]', name_key='cg fallback 2002', name='CG Fallback 2002', document_links=[])]),
        # 2003: house_xml 'unrecognized' blocks fallback to congress_gov 'present' -> 0 witnesses on meeting:2003
        dict(record_sha='a3' * 32, source='house_xml', event_id=2003, collection_state='unrecognized', appearances=[]),
        dict(record_sha='b3' * 32, source='congress_gov', event_id=2003, collection_state='present',
             appearances=[dict(source_locator='congress_gov:witness[1]', name_key='cg blocked 2003', name='CG Blocked 2003', document_links=[])]),
        # 2004: multi-context supersession where newer 'empty' at URL v2 supersedes older 'present' at URL v1
        ar_lake.build_appearance_record_row(sha_wlist_old, 'house_xml', wlist_old,
                                            parser_version=ar_lake.current_version('house_xml')),
        ar_lake.build_appearance_record_row(sha_wlist_empty, 'house_xml', wlist_empty,
                                            parser_version=ar_lake.current_version('house_xml')),
        # 2005: multi-context supersession where newer 'present' at URL b supersedes older 'present' at URL a without duplicating witnesses
        ar_lake.build_appearance_record_row(sha_wlist_dup1, 'house_xml', wlist_dup1,
                                            parser_version=ar_lake.current_version('house_xml')),
        ar_lake.build_appearance_record_row(sha_wlist_dup2, 'house_xml', wlist_dup2,
                                            parser_version=ar_lake.current_version('house_xml')),
    ]

    spicy_regs = dict(
        spicy_committees=[
            dict(
                system_code='HSAG00',
                name='Committee on Agriculture',
                chamber='House',
                committee_type='Standing',
                parent_system_code=None,
                website_url='https://agriculture.house.gov/',
                is_current=True,
                history=[],
            ),
        ],
    )
    build_release(
        **staged,
        spicy_regs=spicy_regs,
        meeting_records=meetings,
        appearance_records=appearances,
        engine=engine,
        output=tmp_path / 'release-ctx',
        scratch=tmp_path / 'model-ctx',
    )
    witnesses = pq.read_table(tmp_path / 'release-ctx/witnesses.parquet').to_pylist()
    by_occ = {}
    for w in witnesses:
        by_occ.setdefault(w['occasion'], []).append(w['name'])

    # Both page occasions resolve, and URL A has Updated A Witness (not overwritten by URL B's later capture of shared_html)
    page_witnesses = {occ: names for occ, names in by_occ.items() if occ.startswith('page:')}
    assert len(page_witnesses) == 2
    assert sorted(names[0] for names in page_witnesses.values()) == ['Shared Body Witness', 'Updated A Witness']

    # Collection state replacement rules on 2001, 2002, 2003, 2004, 2005
    assert 'meeting:2001' not in by_occ  # 'empty' replaced congress_gov with []
    assert by_occ.get('meeting:2002') == ['CG Fallback 2002']  # 'absent' fell back to congress_gov
    assert 'meeting:2003' not in by_occ  # 'unrecognized' blocked fallback to congress_gov
    assert 'meeting:2004' not in by_occ  # newer 'empty' at v2 superseded older 'present' at v1
    assert by_occ.get('meeting:2005') == ['Fresher Witness']  # only fresher context selected without duplication


def test_entity_record_version_selection_and_completeness_admission(tmp_path):
    """ct-kw9b AC 1-6 & ct-vpo2:
    - Multiple parser_version rows for the same (record_sha, source) select only the pinned current version.
    - Expected candidates in captures + readings must be settled in meeting_records / appearance_records or active_unreadable.
    """
    from viewer_publication.archive_model import build_release

    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    house_cm_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<committee-meeting congress-num="118" session-num="1" meeting-id="HHRG118888" meeting-type="HHRG">
  <meeting-details>
    <meeting-title>Current Version Title</meeting-title>
    <meeting-date><calendar-date>2023-06-01</calendar-date></meeting-date>
    <committees><committee-name id="AG00">Committee on Agriculture</committee-name></committees>
  </meeting-details>
</committee-meeting>"""
    house_wl_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<witness-list meeting-id="HHRG118888">
  <panel sort-order="1">
    <witness display-order="1">
      <witness-name><firstname>Current</firstname><lastname>Witness</lastname></witness-name>
    </witness>
  </panel>
</witness-list>"""
    pdf_bytes = b'%PDF-1.7\nstatement\n%%EOF\n'
    sha_cm = hashlib.sha256(house_cm_xml).hexdigest()
    sha_wl = hashlib.sha256(house_wl_xml).hexdigest()

    staged = _stage_raw_fixture(tmp_path, engine, [
        dict(url='https://docs.house.gov/meetings/AG/AG00/20230601/118888/HHRG-118-AG00-20230601.xml',
             data=house_cm_xml, format='xml', media_type='text/xml', family='house/meeting-xml', retrieved_at='2023-06-01T12:00:00Z'),
        dict(url='https://docs.house.gov/meetings/AG/AG00/20230601/118888/HHRG-118-AG00-WList-20230601.xml',
             data=house_wl_xml, format='xml', media_type='text/xml', family='house/witness-xml', retrieved_at='2023-06-01T12:00:00Z'),
        dict(url='https://docs.house.gov/meetings/AG/AG00/20230601/118888/HHRG-118-AG00-Wstate-W-20230601.pdf',
             data=pdf_bytes, format='pdf', compress=False, family='documents', retrieved_at='2023-06-01T12:00:00Z'),
    ])
    # Also stage XML readings so readings table has xml_root='committee-meeting' and 'witness-list'
    raw = tmp_path / 'raw'
    xml_pages = readings.stage(
        captures=staged['captures'],
        body_inventory=tmp_path / 'inventory/bodies.parquet',
        local_root=raw,
        engine=engine,
        work=tmp_path / 'reading-xml-stage',
        decided_at='2026-10-27T12:00:00Z',
        parser='xml',
        existing=staged['readings'],
    )
    import pyarrow as pa
    combined_readings = tmp_path / 'combined-readings.parquet'
    pq.write_table(
        pa.concat_tables([pq.read_table(staged['readings']), pq.read_table(xml_pages['readings'])]),
        combined_readings,
    )
    staged['readings'] = combined_readings

    cur_mr_ver = mr_lake.current_version('house_xml')
    cur_ar_ver = ar_lake.current_version('house_xml')
    cur_mr_row = mr_lake.build_meeting_record_row(sha_cm, 'house_xml', house_cm_xml, parser_version=cur_mr_ver)
    old_mr_row = dict(cur_mr_row, parser_version='old-mr-v0',
                      meetings=[dict(cur_mr_row['meetings'][0], title='Stale Old Version Title')])
    cur_ar_row = ar_lake.build_appearance_record_row(sha_wl, 'house_xml', house_wl_xml, parser_version=cur_ar_ver)
    old_ar_row = dict(cur_ar_row, parser_version='old-ar-v0',
                      appearances=[dict(cur_ar_row['appearances'][0], name='Stale Old Version Witness')])

    spicy_regs = dict(
        spicy_committees=[
            dict(
                system_code='HSAG00',
                name='Committee on Agriculture',
                chamber='House',
                committee_type='Standing',
                parent_system_code=None,
                website_url='https://agriculture.house.gov/',
                is_current=True,
                history=[],
            ),
        ],
    )

    # 1. Both old and current versions present: SQL selects only current version and completeness succeeds
    build_release(
        **staged,
        spicy_regs=spicy_regs,
        meeting_records=[old_mr_row, cur_mr_row],
        appearance_records=[old_ar_row, cur_ar_row],
        engine=engine,
        output=tmp_path / 'release-ok',
        scratch=tmp_path / 'model-ok',
    )
    m_out = pq.read_table(tmp_path / 'release-ok/meetings.parquet').to_pylist()
    assert len(m_out) == 1 and m_out[0]['title'] == 'Current Version Title'
    w_out = pq.read_table(tmp_path / 'release-ok/witnesses.parquet').to_pylist()
    assert len(w_out) == 1 and w_out[0]['name'] == 'Current Witness'

    # 2. Only old version present (missing current reading): refused by entity_profile_completeness
    with pytest.raises(ValueError, match='Release key invariant failed'):
        build_release(
            **staged,
            spicy_regs=spicy_regs,
            meeting_records=[old_mr_row],
            appearance_records=[cur_ar_row],
            engine=engine,
            output=tmp_path / 'release-old-mr',
            scratch=tmp_path / 'model-old-mr',
        )

    # 3. Missing current reading settled via active_unreadable for meeting_records.house_xml at cur_mr_ver: succeeds!
    unreadable_file = tmp_path / 'unreadable-mr.jsonl'
    unreadable_file.write_text(json.dumps(dict(
        id='u1',
        body_sha256=None,
        record_sha=sha_cm,
        parser='meeting_records.house_xml',
        parser_version=cur_mr_ver,
        supersedes=None,
    )) + '\n')
    build_release(
        **staged,
        spicy_regs=spicy_regs,
        unreadable_files=[dict(key='unreadable/mr.jsonl', path=str(unreadable_file))],
        meeting_records=[old_mr_row],
        appearance_records=[cur_ar_row],
        engine=engine,
        output=tmp_path / 'release-unreadable-settled',
        scratch=tmp_path / 'model-unreadable-settled',
    )


def _resolved_meetings(tmp_path, records, pins=()):
    """Run only the maintained meeting SQL over stated records, with no capture history."""
    from congress_api.retention.provenance import json_input, run_job
    from docspec_client.client import NativeDatasets
    from viewer_publication.archive_model import MEETING_RECORD_FIELDS, _normalize_meeting_rows, meeting_steps, selected_record_step
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    inputs = [json_input(tmp_path, 'meeting_records_input', _normalize_meeting_rows(records, 'v'), **MEETING_RECORD_FIELDS),
        json_input(tmp_path, 'parser_versions', list(pins), parser='Utf8', version='Utf8'),
        json_input(tmp_path, 'meeting_sources', [dict(kind='meeting', source='house_xml', priority=1), dict(kind='meeting', source='congress_gov', priority=2)], kind='Utf8', source='Utf8', priority='Int64'),
        json_input(tmp_path, 'recording_sources', [], kind='Utf8', pattern='Utf8', key_template='Utf8')]
    captures = """SELECT arrow_cast(NULL,'FixedSizeBinary(32)') AS sha256,cast(NULL AS VARCHAR) AS retrieved_at,cast(NULL AS VARCHAR) AS mode,
        cast(NULL AS BOOLEAN) AS complete,cast(NULL AS VARCHAR) AS outcome,cast(NULL AS INT) AS http_status WHERE false"""
    result = run_job(tmp_path, engine, inputs=inputs, outputs=[],
        steps=[dict(name='captures', sql=captures), selected_record_step('meeting_records', 'meeting_records_input'), *meeting_steps()],
        queries=[dict(name='rows', sql=f"""SELECT event_id,congress,congress_gov_updated,house_xml_updated,congress_gov_meeting_type,
            sittings[1]['start'] AS s_start,sittings[1]['end'] AS s_end,sittings[1]['place'] AS place,sittings[1]['room'] AS room,
            coalesce(array_length(sittings),0) AS sitting_count FROM meetings_resolved ORDER BY event_id""")])
    return result['rows']


def _record(sha, source, *, states=None, sittings=(), **fields):
    return dict(record_sha=sha * 32, source=source, meetings=[dict(dict(event_id='100', chamber='house', congress=118,
        sittings=list(sittings), collection_states=states or {}), **fields)])


CONGRESS_SITTING = dict(start='2019-11-13T19:00:00Z', room='1300', building='Longworth House Office Building')
HOUSE_SITTING = dict(start='2019-11-13T14:00:00-05:00', end='2019-11-13T16:30:00-05:00', room='9', building='LHOB', address='DC 20515')


def test_congress_gov_leads_and_house_fills_only_what_it_lacks(tmp_path):
    rows = _resolved_meetings(tmp_path, [
        _record('11', 'house_xml', updated='2019-11-10T08:00:00', meeting_type='HHRG', sittings=[HOUSE_SITTING]),
        _record('22', 'congress_gov', updated='2019-11-11T00:00:00Z', meeting_type='Hearing', sittings=[CONGRESS_SITTING])])
    assert str(rows[0]['s_start']).startswith('2019-11-13T19:00:00') and rows[0]['room'] == '1300'
    assert str(rows[0]['s_end']).startswith('2019-11-13T21:30:00')  # Only House states the end.
    assert rows[0]['place'] == '1300, Longworth House Office Building, DC 20515'  # Only House states the address.
    assert rows[0]['house_xml_updated'] == '2019-11-10T08:00:00' and rows[0]['congress_gov_meeting_type'] == 'Hearing'
    assert str(rows[0]['congress_gov_updated']).startswith('2019-11-11T00:00:00')


def test_field_hearing_place_comes_from_the_house_record(tmp_path):
    field = dict(start='2019-11-13T14:00:00-05:00', building='City Hall', address='1 Main St, Richmond, MI, 48062')
    rows = _resolved_meetings(tmp_path, [_record('11', 'house_xml', sittings=[field]),
        _record('22', 'congress_gov', sittings=[dict(start='2019-11-13T19:00:00Z')])])
    assert rows[0]['place'] == 'City Hall, 1 Main St, Richmond, MI, 48062'


def test_house_only_sitting_keeps_its_stated_instant(tmp_path):
    rows = _resolved_meetings(tmp_path, [_record('11', 'house_xml', sittings=[HOUSE_SITTING])])
    assert str(rows[0]['s_start']).startswith('2019-11-13T19:00:00') and rows[0]['congress_gov_updated'] is None


@pytest.mark.parametrize('state', ['empty', 'unrecognized'])
def test_explicit_empty_house_sittings_never_fall_back(tmp_path, state):
    rows = _resolved_meetings(tmp_path, [_record('11', 'house_xml', states=dict(sittings=state)),
        _record('22', 'congress_gov', sittings=[CONGRESS_SITTING])])
    assert rows[0]['sitting_count'] == 0


def test_congress_is_only_what_a_record_states(tmp_path):
    rows = _resolved_meetings(tmp_path, [_record('11', 'congress_gov', congress=None, sittings=[CONGRESS_SITTING])])
    assert rows[0]['congress'] is None


def _versioned(sha, event, version):
    record = _record(sha, 'house_xml', event_id=event)
    return dict(record, parser_version=version)


def test_pinned_versions_select_by_equality_and_an_unpinned_job_takes_all(tmp_path):
    records = [_versioned('11', '100', 'pinned'), _versioned('22', '200', 'other'), _versioned('33', '300', 'pinned')]
    selected = lambda work, pins: [row['event_id'] for row in _resolved_meetings(tmp_path / work, records, pins)]
    for work in ('all', 'one', 'absent', 'repeat'):
        (tmp_path / work).mkdir()
    assert selected('all', []) == [100, 200, 300]
    pin = dict(parser='meeting_records.house_xml', version='pinned')
    assert selected('one', [pin]) == [100, 300]  # An extra version in the input is refused.
    assert selected('repeat', [pin, pin]) == [100, 300]  # A repeated pin cannot duplicate records.
    # A pin no record has selects nothing rather than falling back to every record.
    assert selected('absent', [dict(pin, version='missing')]) == []


def test_another_chambers_pin_does_not_select_this_source(tmp_path):
    rows = _resolved_meetings(tmp_path, [_versioned('11', '100', 'pinned')], [dict(parser='meeting_records.congress_gov', version='pinned')])
    assert rows == []


def test_zip_contents_are_the_documents_from_receipts_to_release(tmp_path):
    """Real receipt lines through captures, readings and the model, not model-only rows."""
    from viewer_publication.archive_model import build_release
    import io, zipfile
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    pdf = b'%PDF-1.7\nzip member transcript bytes\n%%EOF\n'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('CHRG-1/pdf/CHRG-1.pdf', pdf)
    zip_bytes = buffer.getvalue()
    lone_zip = b'PK\x05\x06' + bytes(18)
    direct = b'%PDF-1.7\ndirect document bytes\n%%EOF\n'
    bad = b'%PDF-1.7\nmember of a failed container\n%%EOF\n'
    raw = tmp_path / 'raw'
    def body(data, gz=False):
        digest = hashlib.sha256(data).hexdigest()
        path = raw / f'bodies/sha256/{digest[:2]}/{digest}'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return dict(sha256=digest, bytes=len(data), media_type='application/octet-stream', fidelity='exact-bytes', stored_suffix='', stored_bytes=len(data),
            stored_md5=hashlib.md5(data).hexdigest(), sniff_version=readings.current_version('sniff'))
    def line(url, entries, **extra):
        return dict(writer=dict(job='fixture', commit='a' * 40), run_id='fixture', mode='fetch', family='documents', outcome='stored', requested_url=url, url=url,
            response_headers={}, http_status=200, complete=True, retrieved_at='2026-10-27T12:00:00Z', captures=entries, **extra)
    good_url, failed_url = 'https://fixture.test/CHRG-1.zip', 'https://fixture.test/failed.zip'
    lines = [
        line(good_url, [dict(body(zip_bytes), sniffed_format='zip', expansion='expanded'),
            dict(body(pdf), sniffed_format='pdf', intact=True, member_path='CHRG-1/pdf/CHRG-1.pdf')]),
        # A repeated container row on another attempt must not fan the member out.
        line(good_url, [dict(body(zip_bytes), sniffed_format='zip', expansion='expanded'),
            dict(body(pdf), sniffed_format='pdf', intact=True, member_path='CHRG-1/pdf/CHRG-1.pdf')]),
        line(failed_url, [dict(body(bad), sniffed_format='pdf', intact=True, member_path='x/bad.pdf')], complete=False) if False else
        dict(line(failed_url, [dict(body(bad), sniffed_format='pdf', intact=True, member_path='x/bad.pdf')]), complete=False),
        line('https://fixture.test/lone.zip', [dict(body(lone_zip), sniffed_format='zip')]),
        line('https://fixture.test/direct.pdf', [dict(body(direct), sniffed_format='pdf', intact=True)]),
    ]
    receipt = raw / 'receipts/documents/2026-10-27/slice.jsonl.gz'
    receipt.parent.mkdir(parents=True, exist_ok=True)
    encoded = gzip.compress(''.join(json.dumps(r) + '\n' for r in lines).encode(), mtime=0)
    receipt.write_bytes(encoded)
    pin = tmp_path / 'pin.json'
    pin.write_text(json.dumps(dict(path=str(receipt), size=len(encoded), sha256=hashlib.sha256(encoded).hexdigest(), producer='fixture creation')))
    captures = stage_captures([dict(key=receipt.relative_to(raw).as_posix(), path=str(receipt), qualification=str(pin))], engine=engine, work=tmp_path / 'stage') / 'captures.parquet'
    inventory = tmp_path / 'inventory'
    inventory.mkdir()
    run_job(inventory, engine, inputs=[dict(name='captures', kind='parquet', path=str(captures))], steps=[], outputs=[parquet_output(inventory, 'bodies',
        """SELECT DISTINCT sha256 AS body_sha,'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex') AS physical_key,
        'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex') AS relative_path,stored_bytes,false AS stored_gzip FROM captures WHERE sha256 IS NOT NULL""", ['body_sha'])])
    pages = readings.stage(captures=captures, body_inventory=inventory / 'bodies.parquet', local_root=raw, engine=engine, work=tmp_path / 'read', decided_at='2026-10-27T12:00:00Z', parser='html')
    names = filenames.stage(captures=captures, recovery_files=(), engine=engine, work=tmp_path / 'names', decided_at='2026-10-27T12:00:00Z')
    build_release(captures=captures, readings=pages['readings'], filename_readings=names['readings'],
        parser_versions={p: readings.current_version(p) for p in ['sniff', 'html', 'xml', 'json']}, catalog_version=names['catalog_version'],
        engine=engine, output=tmp_path / 'release', scratch=tmp_path / 'model')
    release = tmp_path / 'release'
    rows = pq.read_table(release / 'list.parquet').to_pylist()
    formats = sorted(row['format'] for row in rows)
    assert formats == ['pdf', 'pdf', 'zip'], rows  # Member and direct PDFs, and the ZIP with no contents.
    key = lambda data: hashlib.sha256(data).digest()[:8]
    details = pq.read_table(release / 'detail.parquet').to_pylist()
    member = next(d for d in details if d['saved_body'] == hashlib.sha256(pdf).digest())
    assert not member['alternates']
    links = {row['link_key']: row['list_row'] for row in pq.read_table(release / 'links.parquet').to_pylist()}
    row_of_member = details.index(member)
    assert links[key(zip_bytes)] == links[key(pdf)] == row_of_member  # The ZIP's public key finds its document.
    assert key(bad) not in links  # A failed container's member stays out.
    sources = pq.read_table(release / 'sources.parquet').to_pylist()
    mine = [s for s in sources if s['list_row'] == row_of_member]
    assert {(s['url'], s['member_path']) for s in mine} == {(good_url, 'CHRG-1/pdf/CHRG-1.pdf')}
    assert all(s['url'] for s in sources)


def test_imported_zip_identical_to_a_good_download_keeps_its_members(tmp_path):
    """The Senate Finance shape, as raw lines: a direct good fetch with no expansion, and a retained
    import of the same bytes that expanded it. Its members have no other good row."""
    from viewer_publication.archive_model import build_release
    import io, zipfile
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    pdf = b'%PDF-1.7\nimported member only\n%%EOF\n'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('A/one.pdf', pdf)
    data = buffer.getvalue()
    other = b'PK\x03\x04 an import with no good download'
    orphan = b'%PDF-1.7\nmember of an unverified import\n%%EOF\n'
    raw = tmp_path / 'raw'
    url = 'https://fixture.test/download/appendix&download=1'
    def body(content):
        digest = hashlib.sha256(content).hexdigest()
        path = raw / f'bodies/sha256/{digest[:2]}/{digest}'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return dict(sha256=digest, bytes=len(content), fidelity='exact-bytes', stored_suffix='', stored_bytes=len(content),
            stored_md5=hashlib.md5(content).hexdigest(), sniff_version=readings.current_version('sniff'))
    def entry(content, fmt, **extra):
        return dict(body(content), media_type='application/octet-stream', sniffed_format=fmt, **extra)
    direct = dict(writer=dict(job='fixture', commit='a' * 40), run_id='fixture', mode='fetch', family='documents', outcome='stored', requested_url=url, url=url,
        response_headers={}, http_status=200, complete=True, retrieved_at='2026-09-29T00:00:00Z', captures=[entry(data, 'zip')])
    def imported(page, zipped, member, name):
        return dict(direct, mode='retained_import', requested_url=page, url=page, retrieved_at='2026-10-16T00:00:00Z',
            source_associations=[dict(original_url=page + '-original', basis='explicit_retained_download_wrapper')],
            captures=[entry(zipped, 'zip', expansion='expanded'), entry(member, 'pdf', intact=True, member_path=name)])
    lines = [direct, imported(url, data, pdf, 'A/one.pdf'), imported('https://fixture.test/unverified', other, orphan, 'B/two.pdf')]
    receipt = raw / 'receipts/documents/2026-10-16/slice.jsonl.gz'
    receipt.parent.mkdir(parents=True, exist_ok=True)
    encoded = gzip.compress(''.join(json.dumps(r) + '\n' for r in lines).encode(), mtime=0)
    receipt.write_bytes(encoded)
    pin = tmp_path / 'pin.json'
    pin.write_text(json.dumps(dict(path=str(receipt), size=len(encoded), sha256=hashlib.sha256(encoded).hexdigest(), producer='fixture creation')))
    decisions = tmp_path / 'recoveries.jsonl'
    decisions.write_text(''.join(json.dumps(dict(id=name, body_sha256=hashlib.sha256(content).hexdigest(), original_url=page + '-original', recovered_filename=None,
        recovered_url=page, kind='recovered_document', identity_note=None, decided_at='2026-10-16T00:00:00Z', supersedes=None, recovery_record_version=2)) + '\n'
        for name, content, page in (('one', data, url), ('two', other, 'https://fixture.test/unverified'))))
    recovery_files = [dict(key='provenance/recoveries/fixture.jsonl', path=str(decisions))]
    captures = stage_captures([dict(key=receipt.relative_to(raw).as_posix(), path=str(receipt), qualification=str(pin))], engine=engine, work=tmp_path / 'stage') / 'captures.parquet'
    modes = {(r['mode'], r['member_path']) for r in pq.read_table(captures, columns=['mode', 'member_path']).to_pylist()}
    assert ('retained_import', 'A/one.pdf') in modes, modes
    inventory = tmp_path / 'inventory'
    inventory.mkdir()
    run_job(inventory, engine, inputs=[dict(name='captures', kind='parquet', path=str(captures))], steps=[], outputs=[parquet_output(inventory, 'bodies',
        """SELECT DISTINCT sha256 AS body_sha,'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex') AS physical_key,
        'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex') AS relative_path,stored_bytes,false AS stored_gzip FROM captures WHERE sha256 IS NOT NULL""", ['body_sha'])])
    pages = readings.stage(captures=captures, body_inventory=inventory / 'bodies.parquet', local_root=raw, engine=engine, work=tmp_path / 'read', decided_at='2026-10-27T12:00:00Z', parser='html')
    names = filenames.stage(captures=captures, recovery_files=recovery_files, engine=engine, work=tmp_path / 'names', decided_at='2026-10-27T12:00:00Z')
    build_release(captures=captures, readings=pages['readings'], filename_readings=names['readings'], recovery_files=recovery_files,
        parser_versions={p: readings.current_version(p) for p in ['sniff', 'html', 'xml', 'json']}, catalog_version=names['catalog_version'],
        engine=engine, output=tmp_path / 'release', scratch=tmp_path / 'model')
    release = tmp_path / 'release'
    details = pq.read_table(release / 'detail.parquet').to_pylist()
    bodies = {d['saved_body'] for d in details}
    assert hashlib.sha256(pdf).digest() in bodies
    assert hashlib.sha256(orphan).digest() not in bodies  # No good download proves that import's bytes.
    member = next(i for i, d in enumerate(details) if d['saved_body'] == hashlib.sha256(pdf).digest())
    links = {row['link_key']: row['list_row'] for row in pq.read_table(release / 'links.parquet').to_pylist()}
    assert links[hashlib.sha256(data).digest()[:8]] == member
    assert hashlib.sha256(data).digest() not in bodies  # The ZIP is a source record, not a document.
    assert {(s['url'], s['member_path']) for s in pq.read_table(release / 'sources.parquet').to_pylist() if s['list_row'] == member} == {(url, 'A/one.pdf')}
    lookup = hashlib.sha256(b'lookup:fixture.test/download/appendix&download=1').digest()[:8]
    assert [r['list_row'] for r in pq.read_table(release / 'urls.parquet').to_pylist() if r['lookup_key'] == lookup] == [member]


def _govinfo_release(tmp_path, packages):
    """Receipt lines for GovInfo packages through captures, html readings and the model.

    Each package: a details page linking the PDF, the HTML and the ZIP each in its own
    `li`; direct HTML bodies; a ZIP holding P/html/P.htm and P/pdf/P.pdf; the direct PDF
    with the member PDF's bytes.
    """
    from viewer_publication.archive_model import build_release
    import io, zipfile
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    raw = tmp_path / 'raw'
    def body(data, fmt, **extra):
        digest = hashlib.sha256(data).hexdigest()
        path = raw / f'bodies/sha256/{digest[:2]}/{digest}'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return dict(sha256=digest, bytes=len(data), media_type='application/octet-stream', fidelity='exact-bytes', stored_suffix='',
            stored_bytes=len(data), stored_md5=hashlib.md5(data).hexdigest(), sniff_version=readings.current_version('sniff'),
            sniffed_format=fmt, **({'intact': True} if fmt == 'pdf' else {}), **extra)
    def line(url, entries, context=None):
        return dict(writer=dict(job='fixture', commit='a' * 40), run_id='fixture', mode='fetch', family='documents', outcome='stored',
            requested_url=url, url=url, response_headers={}, http_status=200, complete=True, retrieved_at='2026-10-27T12:00:00Z',
            captures=entries)
    lines, bodies = [], {}
    for package, (direct_htmls, member_html) in packages.items():
        base = f'https://www.govinfo.gov/content/pkg/{package}'
        pdf = f'%PDF-1.7\n{package} transcript\n%%EOF\n'.encode()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr(f'{package}/html/{package}.htm', member_html)
            archive.writestr(f'{package}/pdf/{package}.pdf', pdf)
        zip_bytes = buffer.getvalue()
        details = (f'<html><head><title>{package} details</title></head><body><ul>'
                   f'<li><a href="{base}/pdf/{package}.pdf">PDF</a></li><li><a href="{base}/html/{package}.htm">Text</a></li>'
                   f'<li><a href="{base}.zip">ZIP</a></li></ul></body></html>').encode()
        bodies[package] = dict(pdf=pdf, zip=zip_bytes, member=member_html, direct=direct_htmls)
        lines.append(line(f'https://www.govinfo.gov/app/details/{package}', [body(details, 'html')]))
        lines.extend(line(f'{base}/html/{package}.htm', [body(data, 'html')]) for data in direct_htmls)
        lines.append(line(f'{base}/pdf/{package}.pdf', [body(pdf, 'pdf')]))
        lines.append(line(f'{base}.zip', [body(zip_bytes, 'zip', expansion='expanded'),
            body(member_html, 'html', member_path=f'{package}/html/{package}.htm'),
            body(pdf, 'pdf', member_path=f'{package}/pdf/{package}.pdf')]))
    receipt = raw / 'receipts/documents/2026-10-27/slice.jsonl.gz'
    receipt.parent.mkdir(parents=True, exist_ok=True)
    encoded = gzip.compress(''.join(json.dumps(r) + '\n' for r in lines).encode(), mtime=0)
    receipt.write_bytes(encoded)
    pin = tmp_path / 'pin.json'
    pin.write_text(json.dumps(dict(path=str(receipt), size=len(encoded), sha256=hashlib.sha256(encoded).hexdigest(), producer='fixture creation')))
    captures = stage_captures([dict(key=receipt.relative_to(raw).as_posix(), path=str(receipt), qualification=str(pin))], engine=engine, work=tmp_path / 'stage') / 'captures.parquet'
    inventory = tmp_path / 'inventory'
    inventory.mkdir()
    run_job(inventory, engine, inputs=[dict(name='captures', kind='parquet', path=str(captures))], steps=[], outputs=[parquet_output(inventory, 'bodies',
        """SELECT DISTINCT sha256 AS body_sha,'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex') AS physical_key,
        'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex') AS relative_path,stored_bytes,false AS stored_gzip FROM captures WHERE sha256 IS NOT NULL""", ['body_sha'])])
    pages = readings.stage(captures=captures, body_inventory=inventory / 'bodies.parquet', local_root=raw, engine=engine, work=tmp_path / 'read', decided_at='2026-10-27T12:00:00Z', parser='html')
    names = filenames.stage(captures=captures, recovery_files=(), engine=engine, work=tmp_path / 'names', decided_at='2026-10-27T12:00:00Z')
    build_release(captures=captures, readings=pages['readings'], filename_readings=names['readings'],
        parser_versions={p: readings.current_version(p) for p in ['sniff', 'html', 'xml', 'json']}, catalog_version=names['catalog_version'],
        engine=engine, output=tmp_path / 'release', scratch=tmp_path / 'model')
    release = tmp_path / 'release'
    return bodies, {name: pq.read_table(release / f'{name}.parquet').to_pylist() for name in ('list', 'detail', 'links', 'sources')}


def _transcript_html(package, address, tail=''):
    paragraph = f'    The committee received testimony on {package}, rural transportation and public lands. \n' * 40
    return (f'<html><head><title>Hearing {package}</title></head><body><pre>{paragraph}'
            f'    Please also email it to {address}.\n{tail}</pre></body></html>').encode()


def _cloudflare(address, key):
    token = bytes([key]) + bytes(b ^ key for b in address.encode())
    return f'<a href="/cdn-cgi/l/email-protection" class="__cf_email__" data-cfemail="{token.hex()}">[email&#160;protected]</a>'


def test_govinfo_member_and_its_direct_copy_are_one_document(tmp_path):
    """The direct HTML (Cloudflare-obfuscated per fetch, once with a \\x1a) and the ZIP member HTML
    sit at one published address, so equal text is one document; really different text is two
    versions of it."""
    address = 'DocumentsTI@mail.house.gov'
    bodies, release = _govinfo_release(tmp_path, {
        'CHRG-119hhrg1': ([_transcript_html(1, _cloudflare(address, 0x4d)), _transcript_html(1, _cloudflare(address, 0x21), '\x1a\n')],
                          _transcript_html(1, address)),
        'CHRG-119hhrg2': ([_transcript_html(2, _cloudflare(address, 0x4d))],
                          _transcript_html(2, address).replace(b'public lands', b'tribal lands'))})
    key = lambda data: hashlib.sha256(data).digest()[:8]
    links = {row['link_key']: row['list_row'] for row in release['links']}
    details, rows = release['detail'], release['list']
    one = bodies['CHRG-119hhrg1']
    row = links[key(one['pdf'])]
    assert all(links[key(data)] == row for data in [one['zip'], one['member'], *one['direct']])
    assert [r for r, d in enumerate(details) if d['package_id'] == 'CHRG-119hhrg1'] == [row]
    assert rows[row]['format'] == 'pdf' and not rows[row]['version_keys']
    assert [a['format'] for a in details[row]['alternates']] == ['html']
    assert rows[row]['title'] == 'Hearing 1'  # The HTML rendition's title, never the link word "PDF".
    mine = {(s['url'], s['member_path']) for s in release['sources'] if s['list_row'] == row}
    assert ('https://www.govinfo.gov/content/pkg/CHRG-119hhrg1.zip', 'CHRG-119hhrg1/html/CHRG-119hhrg1.htm') in mine
    two = bodies['CHRG-119hhrg2']
    versions = {links[key(two['member'])], links[key(two['direct'][0])]}
    assert len(versions) == 2
    shared = [set(rows[r]['version_keys']) for r in versions]
    assert shared[0] and shared[0] == shared[1]


def test_a_page_never_groups_itself_through_its_own_navigation_links(tmp_path):
    """green-g: alert_act_title_ii_ans_section_by_section.pdf took a press release's <title> because the
    release page's share ('#') and skip ('#main') links sit in the PDF link's row and resolve to the page."""
    from viewer_publication.archive_model import build_release
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    page_url = 'https://armedservices.house.gov/news/documentsingle.aspx?DocumentID=6459'
    pdf_url = 'https://armedservices.house.gov/uploadedfiles/alert_act_title_ii_ans_section_by_section.pdf'
    words = 'The committee passed the air safety bill with bipartisan support. ' * 30
    page = (f'<html><head><title>Chairman Praises Committee Passage of Air Safety Bill</title></head><body>'
            f'<a href="#main">Skip to Content</a><main id="main"><p>{words}</p><table><tr><td>'
            f'<a href="#">Share on Facebook</a><a href="#">Print this Page</a> Read the section by section '
            f'<a href="{pdf_url}">here</a></td></tr></table></main><a href="#wrapper">Back to top</a></body></html>').encode()
    pdf = b'%PDF-1.7\nALERT Act Title II section by section\n%%EOF\n'
    staged = _stage_raw_fixture(tmp_path, engine, [dict(url=page_url, data=page, format='html'),
                                                   dict(url=pdf_url, data=pdf, format='pdf', compress=False)])
    build_release(captures=staged['captures'], readings=staged['readings'], filename_readings=staged['filename_readings'],
        parser_versions={p: staged['parser_versions'][p] for p in ['sniff', 'html', 'xml', 'json']},
        catalog_version=staged['catalog_version'], engine=engine, output=tmp_path / 'release', scratch=tmp_path / 'model')
    rows = pq.read_table(tmp_path / 'release/detail.parquet').to_pylist()
    saved = next(r for r in rows if r['filename'] == 'alert_act_title_ii_ans_section_by_section.pdf')
    assert not saved['alternates'] and saved['title'] is None  # 'here' is a link word; the page is not a rendition.
    assert len(rows) == 2


def test_a_listing_label_outranks_another_formats_page_title(tmp_path):
    """red-g F1: a rendition's <title> fills a title only when no listing label names the document."""
    from viewer_publication.archive_model import build_release
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    base = 'https://appropriations.house.gov/files'
    words = 'The subcommittee received the appendix tables for fiscal year spending. ' * 30
    listing = (f'<html><head><title>Hearing documents</title></head><body><p>{words}</p><ul>'
               f'<li><a href="{base}/appendix-d.pdf">Appendix D</a> <a href="https://appropriations.house.gov/news/appendix-d-text">HTML</a></li>'
               f'</ul></body></html>').encode()
    html = ('<html><head><title>Press release headline</title></head><body><main><article><h1>Appendix D</h1><p>'
            + 'Table D-1 lists obligations by account and fiscal year for the subcommittee. ' * 40 + '</p></article></main></body></html>').encode()
    pdf = b'%PDF-1.7\nAppendix D tables\n%%EOF\n'
    staged = _stage_raw_fixture(tmp_path, engine, [dict(url='https://appropriations.house.gov/hearing', data=listing, format='html'),
        dict(url=f'https://appropriations.house.gov/news/appendix-d-text', data=html, format='html'), dict(url=f'{base}/appendix-d.pdf', data=pdf, format='pdf', compress=False)])
    build_release(captures=staged['captures'], readings=staged['readings'], filename_readings=staged['filename_readings'],
        parser_versions={p: staged['parser_versions'][p] for p in ['sniff', 'html', 'xml', 'json']},
        catalog_version=staged['catalog_version'], engine=engine, output=tmp_path / 'release', scratch=tmp_path / 'model')
    rows = pq.read_table(tmp_path / 'release/detail.parquet').to_pylist()
    saved = next(r for r in rows if r['filename'] == 'appendix-d.pdf')
    assert [a['format'] for a in saved['alternates']] == ['html'] and saved['title'] == 'Appendix D', [(r['filename'], r['format'], r['title'], r['alternates']) for r in rows]
