"""Meeting status, reschedule and witness attachment, run from the maintained SQL over hand rows.

The parser's own stated_facts and title_key build the meeting rows, so the parser feeds the SQL.
"""
import hashlib
import os
import random
import re
from pathlib import Path

import duckdb
import pytest

from congress_api.parsers.meeting_facts import stated_facts
from congress_api.retention.provenance import json_input, list_of, parquet_output, run_job, struct
from docspec_client.client import NativeDatasets
from viewer_publication.archive_model import witness_key_steps

ROOT = Path(__file__).parents[3]
EMPTY_SITTINGS = ("array_slice(make_array(named_struct('start',arrow_cast(NULL,'Timestamp(Microsecond, Some(\"UTC\"))'),"
                  "'end',arrow_cast(NULL,'Timestamp(Microsecond, Some(\"UTC\"))'),'place',cast(NULL AS VARCHAR),"
                  "'room',cast(NULL AS VARCHAR),'building',cast(NULL AS VARCHAR),'address',cast(NULL AS VARCHAR))),1,0)")
NO_VIDEOS = "array_slice(make_array(named_struct('name',cast(NULL AS VARCHAR),'url',cast(NULL AS VARCHAR),'video_key',cast(NULL AS VARCHAR))),1,0)"
VIDEO = "make_array(named_struct('name','Stream','url','https://youtu.be/{0}','video_key','youtube:{0}'))"


def sql(name):
    return (ROOT / 'model/sql' / (name + '.sql')).read_text()


def text(value):
    return 'NULL' if value is None else "'" + str(value).replace("'", "''") + "'"


def meeting(event_id, date, title, status=None, video=False, kind='Hearing', chamber='house'):
    facts = stated_facts(kind, title, status)
    return (f"SELECT cast({event_id} AS BIGINT) AS event_id,cast({text(chamber)} AS VARCHAR) AS chamber,{text(title)} AS title,"
            f"cast('{date}' AS DATE) AS meeting_date,'{kind}' AS meeting_type,cast(NULL AS SMALLINT) AS session,"
            f"cast({text(status)} AS VARCHAR) AS status,{EMPTY_SITTINGS} AS sittings,"
            "array_slice(make_array(named_struct('system_code',cast(NULL AS VARCHAR),'role',cast(NULL AS VARCHAR))),1,0) AS committees,"
            "arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') AS subject_keys,"
            f"{VIDEO.format(event_id) if video else NO_VIDEOS} AS videos,cast(118 AS INT) AS congress,"
            f"{UTC} AS congress_gov_updated,cast(NULL AS VARCHAR) AS house_xml_updated,'Hearing' AS congress_gov_meeting_type,"
            f"{text(facts['access'])} AS access,cast(NULL AS VARCHAR) AS access_basis,{str(facts['not_held']).lower()} AS not_held,"
            f"cast({text(facts['title_key'])} AS VARCHAR) AS title_key,{str(facts['reschedule_candidate']).lower()} AS reschedule_candidate,"
            "'hsif00' AS committee_key,arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)') AS transcript_jackets")


UTC = "arrow_cast(NULL,'Timestamp(Microsecond, Some(\"UTC\"))')"
POWER = 'Powering America: Defining Reliability in a Transforming Electricity Industry'
INSURRECTION = 'The Capitol Insurrection: Unexplained Delays and Unanswered Questions'
FTC = 'The FTC at 100: Where Do We Go From Here regulatory'
POSTPONED = 'Challenges to Democracy in the Western Hemisphere'
NEVER = 'Wildfire funding and forest management practices review'
BILLS = 'H.R. 1753 Jax Act; H.R. 3790 Justice for ALS Veterans Act of 2023; H.R. 4016 Veteran Fraud Reimbursement Act'
MEETINGS = [
    # 106383 shape: Rescheduled, its own video, a later twin: it sat.
    meeting(1, '2017-09-14', POWER, 'Rescheduled', video=True),
    meeting(2, '2017-10-03', POWER, 'Scheduled', video=True),
    # 112524 shape: Rescheduled with no video; the twin is Part II, a different meeting.
    meeting(3, '2021-05-12', INSURRECTION, 'Rescheduled'),
    meeting(4, '2021-06-15', INSURRECTION + ' (Part II)', 'Scheduled', video=True),
    # 101422 shape: Rescheduled, no video, a same-title twin.
    meeting(5, '2013-10-24', FTC, 'Rescheduled'),
    meeting(6, '2013-12-03', FTC, 'Scheduled'),
    # Postponed with a video of its own still moves.
    meeting(7, '2013-07-24', POSTPONED, 'Postponed', video=True),
    meeting(8, '2013-09-10', POSTPONED, 'Scheduled'),
    # The only later twin is itself not held.
    meeting(9, '2014-03-01', NEVER, 'Postponed'),
    meeting(10, '2014-03-20', NEVER, 'Canceled'),
    # 116450 shape: Rescheduled, no video, but its record lists its own transcript; the twin is a markup.
    meeting(11, '2023-11-08', BILLS, 'Rescheduled'),
    meeting(12, '2023-11-29', BILLS, 'Rescheduled', kind='HMKP'),
    # A hearing never moves to a markup of the same bills, whatever its status.
    meeting(13, '2023-11-08', BILLS + ' oversight', 'Postponed'),
    meeting(14, '2023-11-29', BILLS + ' oversight', 'Scheduled', kind='HMKP'),
    # Its own witness list (House XML or Congress.gov) shows it sat.
    meeting(15, '2013-10-24', FTC + ' second', 'Rescheduled'),
    meeting(16, '2013-12-03', FTC + ' second', 'Scheduled'),
    # 101422 shape: witnesses attached from another hearing's print are not its own; it still moves.
    meeting(17, '2013-10-24', FTC + ' third', 'Rescheduled'),
    meeting(18, '2013-12-03', FTC + ' third', 'Scheduled'),
    # 101498 shape: Canceled on Congress.gov, but its own print was held that day under its title.
    meeting(19, '2013-11-14', POSTPONED + ' printed', 'Canceled'),
    meeting(20, '2013-12-12', POSTPONED + ' printed', 'Scheduled'),
    # Its own transcript file alone shows a Rescheduled meeting sat (same-kind twin, nothing else).
    meeting(21, '2023-11-09', BILLS + ' transcript', 'Rescheduled'),
    meeting(22, '2023-11-30', BILLS + ' transcript', 'Scheduled'),
    # ct-1i4q transcript sources: committee file only, captions only, segment-only recording.
    meeting(23, '2023-11-08', NEVER + ' committee file', 'Scheduled'),
    meeting(24, '2023-11-15', NEVER + ' captions', 'Scheduled'),
    meeting(25, '2023-11-16', NEVER + ' segments', 'Scheduled'),
    meeting(104064, '2015-11-17', 'Examining Ongoing Challenges at the U.S. Secret Service', chamber=None),
    meeting(335901, '2024-06-12', 'Source-stated joint hearing control', chamber='joint'),
]
TRACK = "named_struct('body',{body},'suffix','.gz','format','{format}','language','en','production','{production}')"
SHA = "arrow_cast(decode(repeat('ab',32),'hex'),'FixedSizeBinary(32)')"
RECORDINGS = (f"SELECT 'youtube:abc' AS video_key,arrow_cast(make_array(cast(24 AS BIGINT)),'List(Int64)') AS event_ids,"
              f"make_array({TRACK.format(body=SHA, format='vtt', production='asr')},"
              f"{TRACK.format(body="arrow_cast(decode('e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855','hex'),'FixedSizeBinary(32)')", format='vtt', production='caption')}) AS tracks "
              # A Senate stream: its vtt is one segment of the caption playlist (ct-9s7b), and one vtt holds no body.
              f"UNION ALL SELECT 'senate:x',arrow_cast(make_array(cast(25 AS BIGINT)),'List(Int64)'),"
              f"make_array({TRACK.format(body=SHA, format='vtt', production='caption')},{TRACK.format(body=SHA, format='m3u8', production='caption')},"
              f"{TRACK.format(body="arrow_cast(NULL,'FixedSizeBinary(32)')", format='vtt', production='live')})")
ORDERED = ("SELECT arrow_cast(make_array('23'),'List(Utf8)') AS meeting_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') AS measure_keys,'HHRG-118-VR09-Transcript-20231108.pdf' AS filename,'pdf' AS format,cast(3 AS INT) AS list_row "
           "UNION ALL SELECT arrow_cast(make_array('23'),'List(Utf8)'),arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'),'HMKP-118-VR09-Transcript-20231108.pdf','pdf',cast(6 AS INT) "
           "UNION ALL SELECT arrow_cast(make_array('23'),'List(Utf8)'),arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'),'Hearing-transcript-request-letter.pdf','pdf',cast(4 AS INT) "
           "UNION ALL SELECT arrow_cast(make_array('23'),'List(Utf8)'),arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'),'HHRG-118-VR09-Transcript-20231109.pdf','pdf',cast(5 AS INT) "
           "UNION ALL SELECT arrow_cast(make_array('119583'),'List(Utf8)'),arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'),'HHRG-119-ED00-20261023-SD001.pdf','pdf',cast(8 AS INT)")


@pytest.fixture(scope='module')
def meetings(tmp_path_factory):
    work = tmp_path_factory.mktemp('meeting-semantics')
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    steps = [
        dict(name='meetings_resolved', sql="SELECT *,CASE WHEN false THEN make_array(named_struct('url',cast(NULL AS VARCHAR))) END AS document_references FROM ("+' UNION ALL '.join(MEETINGS)+")", materialize=True),
        dict(name='ordered', sql=ORDERED, materialize=True),
        dict(name='recordings_entity', sql=RECORDINGS, materialize=True),
        dict(name='meeting_transcript_links', sql="SELECT cast(NULL AS VARCHAR) AS package_id,cast(NULL AS BIGINT) AS event_id WHERE false", materialize=True),
        dict(name='details', sql="""SELECT 'CHRG-own' AS package_id,cast(7 AS INT) AS list_row,'pdf' AS format,
            array_slice(make_array(named_struct('format',cast(NULL AS VARCHAR))),1,0) AS alternates""", materialize=True),
        dict(name='formats', sql="SELECT 'preference' AS kind,'pdf' AS value,cast(1 AS INT) AS rank", materialize=True),
        dict(name='meeting_document_urls', sql="SELECT cast(11 AS BIGINT) AS event_id,'https://www.congress.gov/118/meeting/house/116450/documents/HHRG-118-VR09-Transcript-20231108.pdf' AS url UNION ALL SELECT 21,'https://www.congress.gov/118/meeting/house/9/documents/HHRG-118-XX00-Transcript-20231109.pdf' "
             # 23's record lists its transcript; the other dated file is held and linked but not listed by the record.
             "UNION ALL SELECT 23,'http://docs.house.gov/meetings/VR/VR09/20231108/23/HHRG-118-VR09-Transcript-20231108.pdf'", materialize=True),
        dict(name='appearance_records_resolved', sql="SELECT cast(15 AS BIGINT) AS event_id,'Jane Witness' AS name,'congress_gov' AS source UNION ALL SELECT 17,'PPACA Witness','mods'", materialize=True),
        dict(name='package_meeting_links', sql="SELECT 'CHRG-own' AS package_id,cast(19 AS BIGINT) AS event_id", materialize=True),
        dict(name='package_mods_facts', sql="SELECT 'CHRG-own' AS package_id", materialize=True),
        dict(name='spicy_nominations', sql="SELECT cast(NULL AS INT) AS congress,cast(NULL AS VARCHAR) AS number,cast(NULL AS VARCHAR) AS part_number,cast(NULL AS VARCHAR) AS hearings_json WHERE false", materialize=True),
        dict(name='meetings_export', sql=sql('entity-meetings'), materialize=True),
    ]
    run_job(work, engine, inputs=[], steps=steps,
            outputs=[parquet_output(work, 'meetings', 'SELECT * FROM meetings_export', ['event_id'])])
    with duckdb.connect() as db:
        found = db.execute(f"""SELECT event_id,rescheduled_to,rescheduled_basis,not_held,
            [concat(t.source,':',coalesce(t.package_id,cast(t.list_row AS VARCHAR),t.video_key||'/'||t.production)) FOR t IN transcripts]
            , chamber, chamber_basis FROM read_parquet('{work / 'meetings.parquet'}')""").fetchall()
    return {row[0]: row[1:] for row in found}


def test_chamber_basis_distinguishes_missing_detail_unknown_chamber_and_joint(meetings):
    assert meetings[119583][4:] == (None, 'meeting_detail_missing')
    assert meetings[104064][4:] == (None, 'source_chamber_unknown')
    assert meetings[335901][4:] == ('joint', 'source')


def test_a_meeting_with_only_a_print_lists_the_print(meetings):
    assert meetings[19][3] == ['printed_hearing:CHRG-own']


def test_a_meeting_with_only_its_committee_transcript_lists_it(meetings):
    # Only the file in the House transcript form dated the meeting's day; a letter that says "transcript" is not one.
    assert meetings[23][3] == ['committee_transcript:3']


def test_a_meeting_with_only_captions_lists_the_track(meetings):
    assert meetings[24][3] == ['captions:youtube:abc/asr']


def test_a_recording_with_only_segments_or_empty_tracks_gives_no_transcript(meetings):
    assert meetings[25][3] == []


def test_rescheduled_with_its_own_recording_sat(meetings):
    assert meetings[1][0] is None


def test_a_later_part_is_not_the_same_meeting(meetings):
    assert meetings[3][0] is None


def test_rescheduled_without_a_recording_moves_by_publisher_status(meetings):
    assert meetings[5][:2] == (6, 'publisher_status')


def test_postponed_moves_even_with_a_recording_of_its_own(meetings):
    assert meetings[7][:3] == (8, 'publisher_status', True)


def test_a_meeting_with_its_own_transcript_or_witnesses_sat(meetings):
    assert meetings[11][0] is None and meetings[15][0] is None


def test_its_own_transcript_file_alone_shows_it_sat(meetings):
    assert meetings[21][0] is None


def test_witnesses_attached_from_a_print_are_not_its_own(meetings):
    assert meetings[17][:2] == (18, 'publisher_status')


def test_a_canceled_meeting_whose_own_print_was_held_sat(meetings):
    assert meetings[19][0] is None and meetings[19][2] is False


def test_a_hearing_never_moves_to_a_markup(meetings):
    assert meetings[13][0] is None


def test_a_twin_that_is_itself_not_held_is_never_chosen(meetings):
    assert meetings[9][0] is None and meetings[10][2] is True


# Witness attachment (ct-dx22, ct-x78c): appearance-records-resolved over hand appearance records.
APPEARANCE = dict(source_locator='Utf8', name_key='Utf8', name='Utf8', honorific='Utf8', given='Utf8', middle='Utf8',
                  family='Utf8', suffix='Utf8', position='Utf8', organization='Utf8', on_behalf_of='Utf8', location='Utf8',
                  panel='Utf8', panel_order='Int32', display_order='Int32', witness_type='Utf8', testified='Boolean',
                  bioguide_id='Utf8', document_links=list_of('Utf8'))
CAPTURES = ("SELECT cast(NULL AS VARCHAR) AS mode,cast(NULL AS BOOLEAN) AS complete,cast(NULL AS VARCHAR) AS outcome,"
            "cast(NULL AS INT) AS http_status,arrow_cast(NULL,'FixedSizeBinary(32)') AS sha256,cast(NULL AS VARCHAR) AS family,"
            "cast(NULL AS VARCHAR) AS url,cast(NULL AS VARCHAR) AS requested_url,cast(NULL AS VARCHAR) AS context_url,"
            "cast(NULL AS VARCHAR) AS member_path,cast(NULL AS VARCHAR) AS sniffed_format,cast(NULL AS VARCHAR) AS media_type,"
            "cast(NULL AS VARCHAR) AS retrieved_at,cast(NULL AS VARCHAR) AS original_path WHERE false")


def witness(name, links=(), kind=None):
    key = ' '.join(re.sub(r'[^a-z ]+', '', name.lower()).split())
    return {**{k: None for k in APPEARANCE}, 'source_locator': f'w:{name}', 'name': name, 'name_key': key,
            'witness_type': kind, 'document_links': list(links)}


def record(tag, source, appearances, event_id=None, package_id=None, created=None, context_url=None, collection_state=None):
    return dict(record_sha_hex=hashlib.sha256(tag.encode()).hexdigest(), parser_version='v', status='completed', error_type=None,
                source=source, event_id=event_id, package_id=package_id, declared_base=None,
                collection_state=collection_state or ('present' if appearances else 'empty'),
                context_url=context_url, appearances=appearances, created=created)


LIST = 'https://docs.house.gov/meetings/HM/HM00/20130718/{}/HHRG-113-HM00-Wstate-X-20130718.pdf'


DAY, TITLE = '2021-04-28', 'Student loan debt relief and the borrower defense rule'


def facts(named=(), held=(DAY,), title=TITLE):
    return dict(named_meetings=list(named), held_dates=list(held), title=title)


def resolve(tmp_path, records, links, prints, paths=(), meetings=((9001, DAY, TITLE),), pages=(), full=False, rows=False, keys=False, print_links=False):
    """Witness rows per name, from the maintained package-link and appearance SQL; with keys, the
    published rows and witness_key_map."""
    import json
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    ms_rows = [r for r in json.loads((ROOT / 'model/registries/meeting-sources.json').read_text()) if r['kind'] == 'appearance']
    inputs = [
        json_input(tmp_path, 'appearance_records_input', records, record_sha_hex='Utf8', parser_version='Utf8', status='Utf8',
                   error_type='Utf8', source='Utf8', event_id='Int64', package_id='Utf8', declared_base='Utf8',
                   collection_state='Utf8', context_url='Utf8', appearances=list_of(struct(**APPEARANCE)), created='Utf8'),
        json_input(tmp_path, 'meeting_transcript_links', [dict(package_id=p, event_id=e) for p, e in links], package_id='Utf8', event_id='Int64'),
        json_input(tmp_path, 'package_mods_facts', [dict(package_id=p, **f) for p, f in prints.items()],
                   package_id='Utf8', named_meetings=list_of('Int64'), held_dates=list_of('Utf8'), title='Utf8'),
        json_input(tmp_path, 'meetings_input', [dict(event_id=m[0], meeting_date=m[1], title=m[2],
                                                     not_held=(m[3] if len(m) > 3 else False),
                                                     chamber=(m[4] if len(m) > 4 else 'house'),
                                                     committee_key=(m[5] if len(m) > 5 else 'hsif00'))
                                                for m in meetings],
                   event_id='Int64', meeting_date='Utf8', title='Utf8', not_held='Boolean', chamber='Utf8', committee_key='Utf8'),
        json_input(tmp_path, 'meeting_sources', ms_rows, id='Utf8', kind='Utf8', source='Utf8', priority='Int32'),
        json_input(tmp_path, 'appearance_url_keys',
                   [dict(url=r['context_url'], url_key=r['context_url'], error=None) for r in records if r.get('context_url')],
                   url='Utf8', url_key='Utf8', error='Utf8'),
        json_input(tmp_path, 'selected_meeting_records', [], record_sha_hex='Utf8', status='Utf8', meetings=list_of(struct(updated='Utf8'))),
        json_input(tmp_path, 'page_inputs', list(pages), body_hex='Utf8', status='Utf8', title='Utf8', heading='Utf8', text_head='Utf8', content_date='Utf8'),
    ]
    senate_links_path = ROOT / 'model/sql/senate-page-meeting-links.sql'
    senate_step = [dict(name='senate_page_meeting_links', sql=senate_links_path.read_text(), materialize=True)] if senate_links_path.exists() else []
    steps = [dict(name='selected_appearance_records', sql='SELECT * FROM appearance_records_input', materialize=True),
             dict(name='page_facts', sql="SELECT arrow_cast(decode(body_hex,'hex'),'FixedSizeBinary(32)') AS body_sha,status,title,heading,text_head,cast(content_date AS DATE) AS content_date FROM page_inputs", materialize=True),
             dict(name='spicy_committees', sql="SELECT 'ssbk00' AS system_code,cast(NULL AS VARCHAR) AS parent_system_code,'https://www.banking.senate.gov/' AS website_url", materialize=True),
             dict(name='meetings_resolved', sql="""SELECT event_id,chamber,cast(meeting_date AS DATE) AS meeting_date,title,not_held,committee_key,
                 make_array(named_struct('system_code',committee_key,'role','primary')) AS committees FROM meetings_input""", materialize=True),
             dict(name='appearance_people', sql=sql('appearance-people'), materialize=True),
             dict(name='captures', sql=CAPTURES + ''.join(
                 f" UNION ALL SELECT 'fetch' AS mode,cast(NULL AS BOOLEAN) AS complete,'failed' AS outcome,cast(NULL AS INT) AS http_status,"
                 f"arrow_cast(decode('{sha}','hex'),'FixedSizeBinary(32)') AS sha256,'house/witness-xml' AS family,cast(NULL AS VARCHAR) AS url,"
                 f"cast(NULL AS VARCHAR) AS requested_url,cast(NULL AS VARCHAR) AS context_url,cast(NULL AS VARCHAR) AS member_path,"
                 f"cast(NULL AS VARCHAR) AS sniffed_format,cast(NULL AS VARCHAR) AS media_type,cast(NULL AS VARCHAR) AS retrieved_at,"
                 f"'{path}' AS original_path" for sha, path in paths), materialize=True),
             dict(name='print_meeting_agreement', sql=sql('print-meeting-agreement'), materialize=True),
             dict(name='package_meeting_links', sql=sql('package-meeting-links'), materialize=True),
             *senate_step,
             dict(name='appearance_observations', sql=sql('appearance-observations'), materialize=True),
             dict(name='appearance_records_resolved', sql=sql('appearance-records-resolved'), materialize=True),
             dict(name='witness_precedence', sql=sql('witness-precedence'), materialize=True)]
    if keys:
        steps += [dict(name=name.replace('-', '_'), sql=sql(name), materialize=True)
                  for name in ('witness-key-current', 'witness-key-priors', 'witness-key-map')]
        return run_job(tmp_path, engine, inputs=inputs, steps=steps, outputs=[], queries=[
            dict(name='witnesses', sql='SELECT witness_key,name,occasion,source_locator,record_sha_hex FROM appearance_records_resolved ORDER BY witness_key'),
            dict(name='map', sql='SELECT * FROM witness_key_map ORDER BY old_key')])
    queries = [dict(name='rows', sql='''SELECT r.name,r.occasion,r.event_id,r.witness_type,r.source,r.source_locator,s.name AS superseded_by FROM appearance_records_resolved r
            LEFT JOIN witness_precedence p ON p.witness_key=r.witness_key
            LEFT JOIN appearance_records_resolved s ON s.witness_key=p.superseded_by ORDER BY r.name''')]
    if print_links:
        queries.append(dict(name='print_links', sql='SELECT * FROM package_meeting_links ORDER BY package_id,event_id'))
    result = run_job(tmp_path, engine, inputs=inputs, steps=steps, outputs=[], queries=queries)
    found = result['rows']
    if print_links:
        return found, result['print_links']
    if rows:
        return found
    if full:
        return {r['name']: (r['occasion'], r['superseded_by']) for r in found}
    return {r['name']: (r['occasion'], r['event_id']) for r in found}


def two(tmp_path, prints, links=(('CHRG-a', 9001), ('CHRG-b', 9001)), **kw):
    return resolve(tmp_path, [record('a', 'mods', [witness('A')], package_id='CHRG-a'), record('b', 'mods', [witness('B')], package_id='CHRG-b')],
                   list(links), prints, **kw)


def test_of_two_same_day_prints_only_the_one_whose_title_agrees_attaches(tmp_path):
    got = two(tmp_path, {'CHRG-a': facts(), 'CHRG-b': facts(title='Nuclear waste storage and the Yucca Mountain license')})
    assert got == {'A': ('meeting:9001', 9001), 'B': ('package:CHRG-b', None)}


def test_a_one_to_one_link_to_another_hearings_print_stays_a_package(tmp_path):
    # ct-dx22: a jacket link alone is not evidence; the print's title is another hearing's.
    got = resolve(tmp_path, [record('a', 'mods', [witness('A')], package_id='CHRG-a')], [('CHRG-a', 9001)],
                  {'CHRG-a': facts(title='Nuclear waste storage and the Yucca Mountain license')})
    assert got == {'A': ('package:CHRG-a', None)}


def test_letters_left_from_abbreviations_do_not_make_titles_agree(tmp_path):
    # 106328 "U.S. Cyber Diplomacy" and the same-day print "Assessing the U.S.-Qatar Relationship".
    got = resolve(tmp_path, [record('a', 'mods', [witness('A')], package_id='CHRG-a')], [('CHRG-a', 9001)],
                  {'CHRG-a': facts(title='ASSESSING THE U.S.-QATAR RELATIONSHIP')}, meetings=((9001, DAY, 'U.S. Cyber Diplomacy'),))
    assert got == {'A': ('package:CHRG-a', None)}


def test_an_eventid_on_a_print_held_another_day_is_not_accepted(tmp_path):
    # 330128: GPO put the meeting's eventId on another day's print.
    got = resolve(tmp_path, [record('a', 'mods', [witness('A')], package_id='CHRG-a')], [('CHRG-a', 9001)],
                  {'CHRG-a': facts(named=[9001], held=['2021-05-05'])})
    assert got == {'A': ('package:CHRG-a', None)}


def test_a_print_and_its_errata_both_keep_their_witnesses(tmp_path):
    # CHRG-117shrg45636 and its errata CHRG-117shrg49900 both state <eventId>321961</eventId>.
    got = two(tmp_path, {'CHRG-a': facts(named=[9001]), 'CHRG-b': facts(named=[9001], title='[ERRATA] ' + TITLE)})
    assert len(got) == 2 and set(got.values()) == {('meeting:9001', 9001)}


def test_a_print_naming_two_meetings_attaches_only_where_it_was_held(tmp_path):
    # A multi-meeting eventId list is accepted per meeting, by that meeting's own date and title.
    got = resolve(tmp_path, [record('a', 'mods', [witness('A')], package_id='CHRG-a')], [('CHRG-a', 9001), ('CHRG-a', 9002)],
                  {'CHRG-a': facts(named=[9001, 9002])}, meetings=((9001, DAY, TITLE), (9002, '2021-06-10', TITLE)))
    assert got == {'A': ('meeting:9001', 9001)}


@pytest.mark.parametrize('jacket_events', [(100098,), (100098, 100099)])
def test_two_day_print_links_do_not_assign_individual_witness_dates(tmp_path, jacket_events):
    # Printed contents III of CHRG-112hhrg72238 puts Pistole on June 2 and
    # Farmer and Reese on July 12. Its flat MODS list gives no individual dates.
    package = 'CHRG-112hhrg72238'
    days = ('2011-06-02', '2011-07-12')
    pistole = 'John S. Pistole'
    names = [pistole, 'Thomas L. Farmer', 'Raymond J. Reese']
    records = [
        record('two-day-print', 'mods', [witness(name) for name in names], package_id=package),
        record('june-list', 'congress_gov', [witness(pistole)], event_id=100098),
    ]
    rows, links = resolve(
        tmp_path, records, [(package, event) for event in jacket_events],
        {package: facts(held=days)},
        meetings=((100098, days[0], TITLE), (100099, days[1], TITLE)),
        print_links=True,
    )
    assert [(r['package_id'], r['event_id']) for r in links] == [(package, event) for event in jacket_events]
    assert sorted((r['name'], r['occasion'], r['event_id'], r['source_locator']) for r in rows) == sorted([
        *((name, f'package:{package}', None, f'w:{name}') for name in names),
        (pistole, 'meeting:100098', 100098, f'w:{pistole}'),
    ])


PANEL = ['Jane Doe', 'John Roe', 'Mary Major']
OWN_LIST = record('cg', 'congress_gov', [witness(n) for n in PANEL], event_id=9001)


def test_witnesses_decide_before_titles(tmp_path):
    # A boilerplate title fits the meeting, but print B's people are another hearing's; print A's generic
    # title ("PENDING LEGISLATION") does not, but its people are the meeting's own.
    got = resolve(tmp_path, [OWN_LIST, record('a', 'mods', [witness(n) for n in PANEL], package_id='CHRG-a'),
                             record('b', 'mods', [witness('Carl Other'), witness('Dana Else')], package_id='CHRG-b')],
                  [('CHRG-a', 9001), ('CHRG-b', 9001)], {'CHRG-a': facts(title='PENDING LEGISLATION'), 'CHRG-b': facts()}, full=True)
    assert got['Carl Other'] == ('package:CHRG-b', None) and got['Jane Doe'][0] == 'meeting:9001'


def test_ranks_and_surname_particles_do_not_hide_the_same_people(tmp_path):
    # 114750 lists "The Honorable Carlos Del Toro", "Admiral Michael Gilday"; its print lists "Del Toro", "Michael M. Gilday".
    own = record('cg', 'congress_gov', [witness('The Honorable Carlos Del Toro'), witness('Admiral Michael Gilday'), witness('General David Berger')], event_id=9001)
    got = resolve(tmp_path, [own, record('a', 'mods', [witness('Del Toro'), witness('Michael M. Gilday'), witness('David H. Berger')], package_id='CHRG-a')],
                  [('CHRG-a', 9001)], {'CHRG-a': facts(title='Missile defense budget request')}, full=True)
    assert got['Del Toro'] == ('meeting:9001', 'The Honorable Carlos Del Toro')


PRECEDENCE = [
    # red-f3 constructed cases: never hide a different person.
    ('nickname_one_way', ['Robert Smith', 'Mary Major', 'Carl Other'], {'Barbara Smith': None, 'Bob Smith': 'Robert Smith'}),
    ('same_initial', ['John Smith', 'Mary Major', 'Carl Other'], {'Joan Smith': None, 'John Smith': 'John Smith'}),
    ('credentials', ['Dr. Henry Walke, M.D., M.P.H.', 'Dr. Hilary Marston, M.D., M.P.H.', 'Carl Other'],
     {'Henry Walke, M.D., M.P.H.': 'Dr. Henry Walke, M.D., M.P.H.', 'Hilary Marston': 'Dr. Hilary Marston, M.D., M.P.H.'}),
    ('district', ['The Honorable Michael Cloud (TX-27)', 'Mary Major', 'Carl Other'],
     {'Michael McCaul (TX-10)': None, 'Michael Cloud': 'The Honorable Michael Cloud (TX-27)'}),
    ('van_given', ['Karl D. Jackson, Ph.D.', 'Mary Major', 'Carl Other'], {'Van Jackson': None, 'Karl D. Jackson': 'Karl D. Jackson, Ph.D.'}),
    # Real near-collisions: 106046 (Chris and Connie Stewart), 114121 (bill numbers in parentheses).
    ('stewarts', ['The Honorable Chris Stewart', 'Ms. Connie Stewart', 'Mr. Victor Iverson'],
     {'The Honorable Chris Stewart': 'The Honorable Chris Stewart', 'Ms. Connie Stewart': 'Ms. Connie Stewart'}),
    ('bills_in_parens', ['The Honorable Al Green (HR 4454)', 'The Honorable Eleanor Holmes Norton (HR 3531 and HR 4009)', 'Mr. Albert Hernandez (HR 4380)'],
     {'Al Green': 'The Honorable Al Green (HR 4454)', 'Eleanor Norton': 'The Honorable Eleanor Holmes Norton (HR 3531 and HR 4009)',
      'Albert Hernandez': 'Mr. Albert Hernandez (HR 4380)'}),
]


@pytest.mark.parametrize('case,top,expected', PRECEDENCE, ids=[c[0] for c in PRECEDENCE])
def test_precedence_matches_only_the_same_person(tmp_path, case, top, expected):
    # The print also carries the rest of the meeting's list, so it stands for the meeting.
    own = record('cg', 'congress_gov', [witness(n) for n in top + ['Pat Panel', 'Quinn Panel']], event_id=9001)
    printed = record('a', 'mods', [witness(n) for n in [*expected, 'Pat Panel', 'Quinn Panel']], package_id='CHRG-a')
    got = resolve(tmp_path, [own, printed], [('CHRG-a', 9001)], {'CHRG-a': facts()}, rows=True)
    assert {r['name']: r['superseded_by'] for r in got if r['source'] == 'mods' and r['name'] in expected} == expected


def test_a_witness_listed_twice_in_one_print_is_shown_once(tmp_path):
    # D4 gate: a print lists a witness and then their answers to submitted questions ("Answers to submitted
    # questions \\1\\ Lynn Goldman, ..."). The later line of the same person in the same record is superseded by the
    # first, on a package occasion as on a meeting; two distinct letters with one heading stay two.
    printed = record('a', 'mods', [dict(witness('Lynn Goldman'), source_locator='mods:witness[1]'),
                                   dict(witness('Lynn Goldman'), source_locator='mods:witness[2]'),
                                   dict(witness('Letter dated October 7', kind='statement_for_record'), source_locator='mods:witness[3]'),
                                   dict(witness('Letter dated October 7', kind='statement_for_record'), source_locator='mods:witness[4]')],
                     package_id='CHRG-a')
    got = resolve(tmp_path, [printed], [], {}, rows=True)
    assert sorted((r['source_locator'], r['superseded_by'] is not None) for r in got) == [
        ('mods:witness[1]', False), ('mods:witness[2]', True), ('mods:witness[3]', False), ('mods:witness[4]', False)]


# Witness key map (ct-kb4w): a re-fetched body gives every witness at its occasion a new key; the map
# carries each key the earlier body published to the current witness, or states it ambiguous or unresolved.
def listed(entries):
    return [{**witness(name), 'source_locator': f'congress_gov:witness[{i}]', **attrs} for i, (name, attrs) in enumerate(entries, 1)]


REFETCHED_BEFORE = listed([
    ('Jane Doe', dict(position='Professor')),
    ('John Roe', dict(organization='ACME')),
    ('Mr. Jennifer Manner', dict(position='Chief Executive')),
    ('Sam Lee', dict(position='Professor, MIT')),
    ('John Smith', dict(position='Director')),
    ('Pat Smith', {}),
    ('Lynn Goldman', dict(position='Dean')),
    ('Lynn Goldman', dict(position='Dean')),
    ('Lynn Goldman', dict(position='Dean')),
    ('Carl Other', dict(organization='Other Co')),
])
REFETCHED_AFTER = listed([
    ('John Roe', dict(organization='ACME')),
    ('Jane Doe', dict(position='Professor')),
    ('Ms. Jennifer Manner', dict(position='Chief Executive')),
    ('Sam Lee', dict(position='Mayor of Springfield')),
    ('Joan Smith', dict(position='Director')),
    ('Lynn Goldman', dict(position='Dean')),
    ('Lynn Goldman', dict(position='Dean')),
    ('Pat Smith', {}),
])


@pytest.fixture(scope='module')
def refetched(tmp_path_factory):
    """The keys a release published from the earlier body, and the map once a re-fetched body replaces it."""
    # With no update date or capture time, the lower record SHA is the current body.
    newer, older = sorted(['body-1', 'body-2'], key=lambda tag: hashlib.sha256(tag.encode()).hexdigest())
    before = record(older, 'congress_gov', REFETCHED_BEFORE, event_id=9001)
    base = resolve(tmp_path_factory.mktemp('base'), [before], [], {}, keys=True)['witnesses']
    found = resolve(tmp_path_factory.mktemp('candidate'), [before, record(newer, 'congress_gov', REFETCHED_AFTER, event_id=9001)],
                    [], {}, keys=True)
    current = {w['witness_key']: (w['name'], w['source_locator']) for w in found['witnesses']}
    mapped = {row['old_key']: row for row in found['map']}
    by_old = {}
    for w in base:
        row = mapped.get(w['witness_key'])
        by_old[(w['name'], w['source_locator'])] = row and dict(
            row, successor=current.get(row['witness_key']), candidates=sorted(current[k] for k in row['candidate_keys']))
    return by_old, current, found['map']


def test_a_refetched_body_publishes_none_of_the_earlier_keys(refetched):
    by_old, current, rows = refetched
    assert not set(current) & {row['old_key'] for row in rows}
    assert all(row is not None for row in by_old.values()), 'every key the earlier body published has a map row'


@pytest.mark.parametrize('old,successor,basis', [
    (('Jane Doe', 'congress_gov:witness[1]'), ('Jane Doe', 'congress_gov:witness[2]'), 'content'),
    (('John Roe', 'congress_gov:witness[2]'), ('John Roe', 'congress_gov:witness[1]'), 'content'),
    (('Lynn Goldman', 'congress_gov:witness[7]'), ('Lynn Goldman', 'congress_gov:witness[6]'), 'content'),
    (('Lynn Goldman', 'congress_gov:witness[8]'), ('Lynn Goldman', 'congress_gov:witness[7]'), 'content'),
    # An edited honorific at the same place, with the same position: one person.
    (('Mr. Jennifer Manner', 'congress_gov:witness[3]'), ('Ms. Jennifer Manner', 'congress_gov:witness[3]'), 'locator'),
])
def test_an_unambiguous_successor_maps(refetched, old, successor, basis):
    row = refetched[0][old]
    assert (row['status'], row['successor'], row['basis'], row['candidate_keys']) == ('unambiguous', successor, basis, [])


def test_a_repeat_with_no_partner_is_ambiguous_and_lists_its_candidates(refetched):
    row = refetched[0][('Lynn Goldman', 'congress_gov:witness[9]')]
    assert (row['status'], row['witness_key'], row['basis']) == ('ambiguous', None, 'content')
    assert row['candidates'] == [('Lynn Goldman', 'congress_gov:witness[6]'), ('Lynn Goldman', 'congress_gov:witness[7]')]


def test_a_repeat_with_no_partner_does_not_map_to_the_only_survivor(tmp_path):
    newer, older = sorted(['body-1', 'body-2'], key=lambda tag: hashlib.sha256(tag.encode()).hexdigest())
    entries = [('Lynn Goldman', dict(position='Dean'))]
    before = record(older, 'congress_gov', listed(entries * 2), event_id=9001)
    after = record(newer, 'congress_gov', listed(entries), event_id=9001)
    found = resolve(tmp_path, [before, after], [], {}, keys=True)
    assert len(found['witnesses']) == 1
    survivor = found['witnesses'][0]['witness_key']
    assert sorted((row['status'], row['witness_key'], row['basis'], row['candidate_keys'])
                  for row in found['map']) == [('unambiguous', survivor, 'content', []),
                                                ('unresolved', None, None, [])]


@pytest.mark.parametrize('old', [
    ('Carl Other', 'congress_gov:witness[10]'),  # no longer listed
    ('Sam Lee', 'congress_gov:witness[4]'),  # the same name with another position: another person
    ('John Smith', 'congress_gov:witness[5]'),  # Joan Smith now holds the place and the position
    ('Pat Smith', 'congress_gov:witness[6]'),  # a name alone, at another place
])
def test_a_name_alone_or_a_vanished_witness_is_unresolved(refetched, old):
    row = refetched[0][old]
    assert (row['status'], row['witness_key'], row['basis'], row['candidate_keys']) == ('unresolved', None, None, [])


def test_a_print_key_from_before_its_meeting_link_maps_to_the_linked_row(tmp_path):
    printed = record('a', 'mods', [witness('A')], package_id='CHRG-a')
    (tmp_path / 'base').mkdir(), (tmp_path / 'candidate').mkdir()
    base = resolve(tmp_path / 'base', [printed], [], {}, keys=True)['witnesses']
    found = resolve(tmp_path / 'candidate', [printed], [('CHRG-a', 9001)], {'CHRG-a': facts()}, keys=True)
    assert [w['occasion'] for w in base] == ['package:CHRG-a'] and [w['occasion'] for w in found['witnesses']] == ['meeting:9001']
    assert [(r['old_key'], r['witness_key'], r['status'], r['basis']) for r in found['map']] == [
        (base[0]['witness_key'], found['witnesses'][0]['witness_key'], 'unambiguous', 'occurrence')]


@pytest.mark.parametrize('created,shown', [('2021-04-07T11:07:59.340', True), ('2021-05-01T09:00:00', False)])
def test_an_empty_house_list_made_before_its_hearing_does_not_hide_other_lists(tmp_path, created, shown):
    # 111420: the House list was created 2021-04-07, empty, for a 2021-04-28 hearing.
    house = record('hx', 'house_xml', [], event_id=9001, created=created)
    own = record('cg', 'congress_gov', [witness('Jane Doe')], event_id=9001)
    got = resolve(tmp_path, [house, own], [], {}, rows=True)
    assert bool([r for r in got if r['name'] == 'Jane Doe']) is shown


def test_one_shared_family_name_is_chance_not_agreement(tmp_path):
    own = record('cg', 'congress_gov', [witness('Jane Doe'), witness('John Roe')], event_id=9001)
    got = resolve(tmp_path, [own, record('a', 'mods', [witness('Joan Roe'), witness('Carl Other'), witness('Dana Else')], package_id='CHRG-a')],
                  [('CHRG-a', 9001)], {'CHRG-a': facts()}, full=True)
    assert got['Carl Other'] == ('package:CHRG-a', None)


def test_of_two_agreeing_same_day_meetings_the_better_match_keeps_the_print(tmp_path):
    # 100692 and 100693 share part of a panel; the print is the one whose list matches it fully.
    lists = [OWN_LIST, record('cg2', 'congress_gov', [witness('Jane Doe'), witness('John Roe'), witness('Zed Last'), witness('Yan Next')], event_id=9002)]
    got = resolve(tmp_path, lists + [record('a', 'mods', [witness(n) for n in PANEL], package_id='CHRG-a')],
                  [('CHRG-a', 9001), ('CHRG-a', 9002)], {'CHRG-a': facts()}, meetings=((9001, DAY, TITLE), (9002, DAY, TITLE)), rows=True)
    assert {r['occasion'] for r in got if r['name'] == 'Mary Major'} == {'meeting:9001'}


def test_a_wrong_eventid_never_vetoes_the_same_witnesses(tmp_path):
    # 29369: GovInfo states another meeting's eventId on the print of this one.
    got = resolve(tmp_path, [OWN_LIST, record('a', 'mods', [witness(n) for n in PANEL], package_id='CHRG-a')],
                  [('CHRG-a', 9001)], {'CHRG-a': facts(named=[9555], title='PENDING LEGISLATION')}, full=True)
    assert {occasion for occasion, _ in got.values()} == {'meeting:9001'}


def test_a_print_yields_a_superseded_duplicate_to_the_meeting_that_sat(tmp_path):
    # 105066 (Postponed) was re-entered as 105084 the same day under a new title.
    got = resolve(tmp_path, [record('a', 'mods', [witness('A')], package_id='CHRG-a')], [('CHRG-a', 9001), ('CHRG-a', 9002)],
                  {'CHRG-a': facts()}, meetings=((9001, DAY, TITLE, True), (9002, DAY, TITLE + ' oversight')))
    assert got == {'A': ('meeting:9002', 9002)}


def test_a_print_stands_for_the_meeting_on_its_second_held_day(tmp_path):
    rows, links = resolve(
        tmp_path, [record('a', 'mods', [witness('A')], package_id='CHRG-a')],
        [('CHRG-a', 9002)], {'CHRG-a': facts(held=['2021-02-23', '2021-02-24'])},
        meetings=((9002, '2021-02-24', TITLE),), print_links=True,
    )
    assert links == [{'package_id': 'CHRG-a', 'event_id': 9002}]
    assert [(r['name'], r['occasion'], r['event_id']) for r in rows] == [('A', 'package:CHRG-a', None)]


def test_precedence_is_per_person_and_statements_stay_statements(tmp_path):
    # The meeting's own list outranks the print, person by person (nickname Bob for Robert); the print's
    # second-day witness and its letter for the record are published, the letter as a statement.
    own = record('cg', 'congress_gov', [witness('Jane Doe'), witness('Robert Guy')], event_id=9001)
    printed = record('a', 'mods', [witness('Jane Doe'), witness('Bob Guy'), witness('Chris Harrison'),
                                   witness('Florida Fish and Wildlife Commission', kind='statement_for_record')], package_id='CHRG-a')
    got = resolve(tmp_path, [own, printed], [('CHRG-a', 9001)], {'CHRG-a': facts()}, full=True)
    assert len(got) == 5  # Two Jane Does collapse in this name-keyed view; the print's row is superseded.
    assert got['Bob Guy'] == ('meeting:9001', 'Robert Guy')
    assert got['Chris Harrison'] == ('meeting:9001', None)
    assert got['Florida Fish and Wildlife Commission'] == ('meeting:9001', None)


def test_a_house_list_without_meeting_id_takes_the_event_its_links_state(tmp_path):
    got = resolve(tmp_path, [record('h', 'house_xml', [witness('H', [LIST.format(101160)])]),
                             record('two', 'house_xml', [witness('T1', [LIST.format(101160)]), witness('T2', [LIST.format(101161)])])], [], {})
    assert got == {'H': ('meeting:101160', 101160)}  # Links naming two events give no occasion.


def test_a_package_mods_names_its_meeting_as_a_transcript_link(tmp_path):
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    inputs = [json_input(tmp_path, 'package_mods_facts', [dict(package_id='CHRG-m', **facts(named=[5, 6, 404], held=['2013-10-24'], title=FTC))],
                         package_id='Utf8', named_meetings=list_of('Int64'), held_dates=list_of('Utf8'), title='Utf8')]
    empty = "SELECT cast(NULL AS VARCHAR) AS package_id WHERE false"
    steps = [dict(name='meetings_resolved', sql=' UNION ALL '.join(MEETINGS), materialize=True),
             dict(name='source_annotations', sql=empty, materialize=True),
             dict(name='document_packages', sql=empty, materialize=True),
             dict(name='selected_appearance_records', sql="SELECT cast(NULL AS VARCHAR) AS package_id,cast(NULL AS VARCHAR) AS status WHERE false", materialize=True),
             dict(name='captures', sql=CAPTURES, materialize=True),
             dict(name='appearance_people', sql="SELECT cast(NULL AS VARCHAR) AS package_id,cast(NULL AS BIGINT) AS event_id,cast(NULL AS VARCHAR) AS source,"
                  "false AS statement,cast(NULL AS VARCHAR) AS family,cast(NULL AS VARCHAR) AS given,cast(NULL AS VARCHAR) AS given_canon WHERE false", materialize=True),
             dict(name='print_meeting_agreement', sql=sql('print-meeting-agreement'), materialize=True),
             dict(name='meeting_mods_links', sql=sql('meeting-mods-links'), materialize=True),
             dict(name='meeting_transcript_links', sql=sql('meeting-transcript-links'), materialize=True)]
    found = run_job(tmp_path, engine, inputs=inputs, steps=steps, outputs=[], queries=[
        dict(name='links', sql='SELECT package_id,event_id FROM meeting_transcript_links')])['links']
    # No jacket names it. 6 was held another day under the same title and 404 is no meeting held here,
    # so the print's eventIds stand only where it was held (red-f: GPO eventIds alone are not evidence).
    assert found == [dict(package_id='CHRG-m', event_id=5)]


def test_a_retained_house_list_takes_the_event_its_file_name_states(tmp_path):
    house = record('wl', 'house_xml', [witness('W')])
    got = resolve(tmp_path, [house], [], {}, paths=[(house['record_sha_hex'], 'external-sources/hearing-text/docs_house_xml/wlist/108265.xml')])
    assert got == {'W': ('meeting:108265', 108265)}


def test_senate_page_links_to_meeting_and_outranks_mods_while_preserving_statements(tmp_path):
    # ct-j2yo & User Decision A3: senate_page (priority 3) links to Senate meeting 9001 via committee + date
    # and supersedes the matching mods witness (priority 4), while mods-only witnesses and statements stay.
    sp = record('sp1', 'senate_page', [witness('The Honorable Jane Doe')],
                context_url='https://www.banking.senate.gov/hearings/04/28/2021/student-loan-debt-relief')
    printed = record('m1', 'mods', [witness('Jane Doe'), witness('Chris Harrison'),
                                    witness('American Bankers Association', kind='statement_for_record')],
                     package_id='CHRG-s1')
    got = resolve(tmp_path, [sp, printed], [('CHRG-s1', 9001)], {'CHRG-s1': facts()},
                  meetings=((9001, DAY, TITLE, False, 'senate', 'ssbk00'),),
                  pages=[dict(body_hex=sp['record_sha_hex'], status='completed', title=TITLE, heading=TITLE, text_head='', content_date=DAY)],
                  rows=True)
    by_src_name = {(r['source'], r['name']): (r['occasion'], r['superseded_by']) for r in got}
    assert by_src_name[('senate_page', 'The Honorable Jane Doe')] == ('meeting:9001', None)
    assert by_src_name[('mods', 'Jane Doe')] == ('meeting:9001', 'The Honorable Jane Doe')
    assert by_src_name[('mods', 'Chris Harrison')] == ('meeting:9001', None)
    assert by_src_name[('mods', 'American Bankers Association')] == ('meeting:9001', None)


@pytest.mark.parametrize('second_title,expected', [
    ('Unrelated testimony concerning tax revenue', 335901),
    ('Made in America: The Boom in U.S. Manufacturing Investment', None),
])
def test_jec_page_matches_both_committee_codes_without_asserting_chamber(tmp_path, second_title, expected):
    title = 'Made in America: The Boom in U.S. Manufacturing Investment'
    day = '2024-06-12'
    sp = record('jec-page', 'senate_page', [witness('Scott Lincicome')],
                context_url='https://www.jec.senate.gov/public/index.cfm/2024/6/made-in-america')
    page = dict(body_hex=sp['record_sha_hex'], status='completed', title=title, heading=title, text_head='', content_date=day)
    got = resolve(tmp_path, [sp], [], {}, pages=[page], meetings=(
        (335901, day, title, False, None, 'jjec00'),
        (335902, day, second_title, False, 'joint', 'jsec00'),
    ))
    assert got['Scott Lincicome'][1] == expected


def test_jec_unknown_chamber_requires_title_or_witness_evidence(tmp_path):
    day = '2024-06-12'
    sp = record('jec-page', 'senate_page', [witness('Scott Lincicome')],
                context_url='https://www.jec.senate.gov/public/index.cfm/2024/6/made-in-america')
    page = dict(body_hex=sp['record_sha_hex'], status='completed', title='Manufacturing investments',
                heading=None, text_head='', content_date=day)
    got = resolve(tmp_path, [sp], [], {}, pages=[page], meetings=(
        (335901, day, 'Unrelated testimony concerning tax revenue', False, None, 'jjec00'),
    ))
    assert got['Scott Lincicome'][1] is None


def test_empty_senate_page_does_not_suppress_mods_witnesses(tmp_path):
    # ct-j2yo guard: an empty/absent senate_page container never attaches as 'empty' to suppress mods witnesses.
    empty_sp = record('sp_empty', 'senate_page', [], collection_state='empty',
                      context_url='https://www.banking.senate.gov/hearings/04/28/2021/student-loan-debt-relief')
    printed = record('m1', 'mods', [witness('Jane Doe')], package_id='CHRG-s1')
    got = resolve(tmp_path, [empty_sp, printed], [('CHRG-s1', 9001)], {'CHRG-s1': facts()},
                  meetings=((9001, DAY, TITLE, False, 'senate', 'ssbk00'),),
                  pages=[dict(body_hex=empty_sp['record_sha_hex'], status='completed', title=TITLE, heading=TITLE, text_head='', content_date=DAY)],
                  full=True)
    assert got == {'Jane Doe': ('meeting:9001', None)}


def test_same_day_senate_pages_disambiguate_by_title_and_witness_overlap(tmp_path):
    # ct-j2yo disambiguation: two same-day Senate hearings on ssbk00 disambiguate via title/heading word overlap.
    sp_a = record('spa', 'senate_page', [witness('Alice Borrower')],
                  context_url='https://www.banking.senate.gov/hearings/04/28/2021/student-loan-debt-relief')
    sp_b = record('spb', 'senate_page', [witness('Bob Reactor')],
                  context_url='https://www.banking.senate.gov/hearings/04/28/2021/nuclear-waste-storage')
    sp_ambig = record('spc', 'senate_page', [witness('Carol Unmatched')],
                      context_url='https://www.banking.senate.gov/hearings/04/28/2021/hearing')
    meetings = (
        (9001, DAY, TITLE, False, 'senate', 'ssbk00'),
        (9002, DAY, 'Nuclear waste storage and the Yucca Mountain license', False, 'senate', 'ssbk00'),
    )
    pages = [
        dict(body_hex=sp_a['record_sha_hex'], status='completed', title=TITLE, heading=TITLE, text_head='', content_date=DAY),
        dict(body_hex=sp_b['record_sha_hex'], status='completed', title='Nuclear waste storage and the Yucca Mountain license',
             heading='Nuclear waste storage', text_head='', content_date=DAY),
        dict(body_hex=sp_ambig['record_sha_hex'], status='completed', title='Hearing', heading='Hearing', text_head='', content_date=DAY),
    ]
    got = resolve(tmp_path, [sp_a, sp_b, sp_ambig], [], {}, meetings=meetings, pages=pages)
    assert got['Alice Borrower'] == ('meeting:9001', 9001)
    assert got['Bob Reactor'] == ('meeting:9002', 9002)
    assert got['Carol Unmatched'][0].startswith('page:') and got['Carol Unmatched'][1] is None


def test_senate_special_and_joint_hosts_link_to_canonical_committee_codes(tmp_path):
    # F7: aging -> spag00, ethics -> slet00, jec -> jsec00, drugcaucus -> scnc00, ag -> ssaf00.
    cases = [
        ('sp_aging', 'https://www.aging.senate.gov/hearings/senior-care', 9101, 'spag00', 'Alice Senior'),
        ('sp_ethics', 'https://www.ethics.senate.gov/hearings/ethics-review', 9102, 'slet00', 'Bob Ethics'),
        ('sp_jec', 'https://www.jec.senate.gov/hearings/economic-outlook', 9103, 'jsec00', 'Carol Econ'),
        ('sp_drug', 'https://www.drugcaucus.senate.gov/hearings/narcotics-control', 9104, 'scnc00', 'Dan Narcotics'),
        ('sp_ag', 'https://www.ag.senate.gov/hearings/farm-bill', 9105, 'ssaf00', 'Eve Farmer'),
    ]
    records = [record(rid, 'senate_page', [witness(wname)], context_url=url) for rid, url, _, _, wname in cases]
    meetings = tuple((ev, DAY, TITLE, False, 'senate', code) for _, _, ev, code, _ in cases)
    pages = [dict(body_hex=r['record_sha_hex'], status='completed', title=TITLE, heading=TITLE, text_head='', content_date=DAY)
             for r in records]
    got = resolve(tmp_path, records, [], {}, meetings=meetings, pages=pages)
    for _, _, ev, _, wname in cases:
        assert got[wname] == (f'meeting:{ev}', ev)


def test_witness_precedence_picks_highest_priority_root_and_handles_multi_source_open_given(tmp_path):
    # F4: when house_xml (priority 1), congress_gov (priority 2), and mods (priority 4) all list the same
    # person, mods.superseded_by must point directly to the house_xml root winner (not congress_gov even if
    # congress_gov has a lexicographically smaller witness_key). Also, a surname-only mods row ('Smith') is
    # superseded when 'John Smith' is listed in both house_xml and congress_gov.
    house = record('hx_root', 'house_xml', [witness('Dr. Jane Doe'), witness('Mr. John Smith')], event_id=9001)
    congress = record('cg_mid', 'congress_gov', [witness('Jane Doe'), witness('John Smith')], event_id=9001)
    printed = record('mods_leaf', 'mods', [witness('Ms. Jane Doe'), witness('Mr. Smith')], package_id='CHRG-root')
    got = resolve(tmp_path, [house, congress, printed], [('CHRG-root', 9001)], {'CHRG-root': facts()}, rows=True)
    by_src_name = {(r['source'], r['name']): r for r in got}
    # Both congress_gov and mods must point directly to house_xml's 'Dr. Jane Doe', never forming a 2-hop chain.
    assert by_src_name[('house_xml', 'Dr. Jane Doe')]['superseded_by'] is None
    assert by_src_name[('congress_gov', 'Jane Doe')]['superseded_by'] == 'Dr. Jane Doe'
    assert by_src_name[('mods', 'Ms. Jane Doe')]['superseded_by'] == 'Dr. Jane Doe'
    # Surname-only 'Mr. Smith' in mods is superseded by 'Mr. John Smith' even though both house_xml and congress_gov list John Smith.
    assert by_src_name[('mods', 'Mr. Smith')]['superseded_by'] == 'Mr. John Smith'


def test_two_way_witness_precedence_and_hmtg_sha_prefixed_slugs_in_document_witness_keys(tmp_path):
    # F4 & F9: document-witness-keys expands witness_precedence in both directions (so matching a canonical
    # house_xml witness also attaches superseded congress_gov/mods keys, while witness_name stays canonical)
    # and matches HMTG- and <sha256>.hhrg- witness filenames.
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    sha_prefix = 'a' * 64
    inputs = [
        json_input(tmp_path, 'appearance_records_resolved', [
            dict(witness_key='wk_house_smith', occasion='meeting:9001', source='house_xml',
                 record_sha_hex='11' * 32, ordinal=0, event_id=9001, name='Dr. Jane Smith', document_urls=[]),
            dict(witness_key='wk_cgov_smith', occasion='meeting:9001', source='congress_gov',
                 record_sha_hex='22' * 32, ordinal=0, event_id=9001, name='Jane Smith', document_urls=[]),
            dict(witness_key='wk_mods_smith', occasion='meeting:9001', source='mods',
                 record_sha_hex='33' * 32, ordinal=0, event_id=9001, name='Smith, Jane', document_urls=[]),
            dict(witness_key='wk_house_doe', occasion='meeting:9001', source='house_xml',
                 record_sha_hex='11' * 32, ordinal=1, event_id=9001, name='Hon. Robert Doe', document_urls=[]),
        ], witness_key='Utf8', occasion='Utf8', source='Utf8', record_sha_hex='Utf8',
           ordinal='Int64', event_id='Int64', name='Utf8', document_urls=list_of('Utf8')),
        json_input(tmp_path, 'witness_precedence', [
            dict(witness_key='wk_cgov_smith', superseded_by='wk_house_smith'),
            dict(witness_key='wk_mods_smith', superseded_by='wk_house_smith'),
        ], witness_key='Utf8', superseded_by='Utf8'),
        json_input(tmp_path, 'appearance_people', [
            dict(record_sha_hex='11' * 32, source='house_xml', ordinal=0, statement=False, family='smith', given='jane'),
            dict(record_sha_hex='22' * 32, source='congress_gov', ordinal=0, statement=False, family='smith', given='jane'),
            dict(record_sha_hex='33' * 32, source='mods', ordinal=0, statement=False, family='smith', given='jane'),
            dict(record_sha_hex='11' * 32, source='house_xml', ordinal=1, statement=False, family='doe', given='robert'),
        ], record_sha_hex='Utf8', source='Utf8', ordinal='Int64', statement='Boolean', family='Utf8', given='Utf8'),
        json_input(tmp_path, 'appearance_url_keys', [], url='Utf8', url_key='Utf8', error='Utf8'),
        json_input(tmp_path, 'document_packages', [], component='Utf8', package_id='Utf8'),
        json_input(tmp_path, 'source_annotations', [], source_id='Utf8', package_id='Utf8', meeting_keys=list_of('Utf8')),
        json_input(tmp_path, 'source_filename_readings', [], source_id='Utf8', status='Utf8', package_id='Utf8'),
        json_input(tmp_path, 'copy_url_keys', [], source_id='Utf8', url_key='Utf8'),
        json_input(tmp_path, 'saved_recoveries', [], id='Utf8', component='Utf8', original_url='Utf8'),
        json_input(tmp_path, 'recovery_original_keys', [], recovery_id='Utf8', url_key='Utf8'),
        json_input(tmp_path, 'effective_filenames', [], input_id='Utf8', filename='Utf8'),
        json_input(tmp_path, 'document_metadata', [
            dict(component='comp_hmtg', meeting_keys=['9001']),
            dict(component='comp_sha_hhrg', meeting_keys=['9001']),
        ], component='Utf8', meeting_keys=list_of('Utf8')),
        json_input(tmp_path, 'document_members', [
            dict(component='comp_hmtg', source_id='src_hmtg'),
            dict(component='comp_sha_hhrg', source_id='src_sha_hhrg'),
        ], component='Utf8', source_id='Utf8'),
        json_input(tmp_path, 'source_files', [
            dict(source_id='src_hmtg', body_sha='aa' * 32, source_url='https://docs.house.gov/1.pdf',
                 filename='HMTG-118-AG00-Wstate-SmithJ-20230510.pdf'),
            dict(source_id='src_sha_hhrg', body_sha='bb' * 32, source_url='https://docs.house.gov/2.pdf',
                 filename=f'{sha_prefix}.hhrg-118-ag00-bio-doer-20230510.pdf'),
        ], source_id='Utf8', body_sha='Utf8', source_url='Utf8', filename='Utf8'),
    ]
    steps = witness_key_steps(root=ROOT)
    res = run_job(tmp_path, engine, inputs=inputs, steps=steps, outputs=[], queries=[
        dict(name='dwk', sql='SELECT component, witness_keys, witness_name FROM document_witness_keys ORDER BY component')
    ])['dwk']
    assert res == [
        dict(component='comp_hmtg',
             witness_keys=['wk_cgov_smith', 'wk_house_smith', 'wk_mods_smith'],
             witness_name='Dr. Jane Smith'),
        dict(component='comp_sha_hhrg',
             witness_keys=['wk_house_doe'],
             witness_name='Hon. Robert Doe'),
    ]


def witness_key_inputs(directory, matches, names, precedence):
    """document_witness_keys' three inputs from (component, key), (key, name) and (key, superseded_by) pairs."""
    return [
        json_input(directory, 'document_witness_raw_matches', [dict(component=c, witness_key=k) for c, k in matches],
                   component='Utf8', witness_key='Utf8'),
        json_input(directory, 'appearance_records_resolved', [dict(witness_key=k, name=n) for k, n in names],
                   witness_key='Utf8', name='Utf8'),
        json_input(directory, 'witness_precedence', [dict(witness_key=k, superseded_by=s) for k, s in precedence],
                   witness_key='Utf8', superseded_by='Utf8'),
    ]


def test_document_witness_keys_counts_each_witness_once_per_document(tmp_path):
    # witness_name: the one current witness's name, else the one witness's name, else NULL. Name rows
    # and precedence rows fan the join out; neither may count a witness twice, and a NULL key is no witness.
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    matches = [('c_superseded', 'k_old'), ('c_two_current', 'k_a'), ('c_two_current', 'k_b'),
               ('c_name_rows', 'k_two'), ('c_precedence_rows', 'k_dup'), ('c_self', 'k_self'),
               ('c_null', None), ('c_null', 'k_named'), ('c_nameless', 'k_noname')]
    names = [('k_cur', 'Current Name'), ('k_old', 'Aardvark Old'), ('k_a', 'Bea'), ('k_b', 'Al'),
             ('k_two', 'Zed'), ('k_two', 'Abe'), ('k_dup', 'Zz Dup'), ('k_dup2', 'Dup Two'),
             ('k_self', 'Self'), ('k_named', 'Named')]
    precedence = [('k_old', 'k_cur'), ('k_dup', None), ('k_dup', 'k_dup2'), ('k_dup2', 'k_dup'), ('k_self', 'k_self')]
    inputs = witness_key_inputs(tmp_path, matches, names, precedence)
    steps = [step for step in witness_key_steps(root=ROOT) if step['name'] == 'document_witness_keys']
    res = run_job(tmp_path, engine, inputs=inputs, steps=steps, outputs=[], queries=[
        dict(name='dwk', sql='SELECT component, witness_keys, witness_name FROM document_witness_keys ORDER BY component')
    ])['dwk']
    assert res == [
        dict(component='c_name_rows', witness_keys=['k_two'], witness_name='Abe'),
        dict(component='c_nameless', witness_keys=['k_noname'], witness_name=None),
        dict(component='c_null', witness_keys=[None, 'k_named'], witness_name='Named'),
        dict(component='c_precedence_rows', witness_keys=['k_dup', 'k_dup2'], witness_name='Zz Dup'),
        dict(component='c_self', witness_keys=['k_self'], witness_name='Self'),
        dict(component='c_superseded', witness_keys=['k_cur', 'k_old'], witness_name='Current Name'),
        dict(component='c_two_current', witness_keys=['k_a', 'k_b'], witness_name=None),
    ]


# The reference oracle: document-witness-keys.sql's aggregate as it stood before 2d76d689, two
# count(DISTINCT) over the fanned-out name and precedence join. Verbatim but for reading raw matches
# from their step (document_witness_raw_matches), which was then the inline raw_matched CTE.
PRE_2D76D689_WITNESS_KEYS_SQL = """WITH canonical_expanded AS (
 SELECT component,witness_key FROM document_witness_raw_matches
 UNION
 SELECT m.component,wp.superseded_by AS witness_key
 FROM document_witness_raw_matches m
 JOIN witness_precedence wp ON wp.witness_key=m.witness_key
 WHERE wp.superseded_by IS NOT NULL
), all_matched AS (
 SELECT component,witness_key FROM canonical_expanded
 UNION
 SELECT c.component,wp.witness_key
 FROM canonical_expanded c
 JOIN witness_precedence wp ON wp.superseded_by=c.witness_key
)
SELECT
 m.component,
 array_sort(array_distinct(array_agg(m.witness_key))) AS witness_keys,
 CASE
  WHEN count(DISTINCT m.witness_key) FILTER (WHERE wp.superseded_by IS NULL)=1
   THEN min(w.name) FILTER (WHERE wp.superseded_by IS NULL)
  WHEN count(DISTINCT m.witness_key)=1
   THEN min(w.name)
 END AS witness_name
FROM all_matched m
LEFT JOIN appearance_records_resolved w ON w.witness_key=m.witness_key
LEFT JOIN witness_precedence wp ON wp.witness_key=m.witness_key
GROUP BY m.component"""

# Wrong rewrites the seeded rows must tell apart from the oracle: (base SQL, text replaced, replacement).
WITNESS_KEY_PLANTS = {
    'oracle_without_distinct': ('oracle', 'count(DISTINCT m.witness_key)', 'count(m.witness_key)'),
    'committed_count_star': ('committed', 'count(witness_key)', 'count(*)'),
    'committed_bool_and': ('committed', 'bool_or(', 'bool_and('),
}


def seeded_witness_rows(seed=20261104, components=2500, keys=400, matches=4000):
    """Raw matches, names and precedence with NULL keys and components, NULL names, duplicate rows,
    precedence chains and self-supersession, and keys with both a current and a superseded row."""
    rng = random.Random(seed)
    key = lambda: f'k{rng.randrange(keys)}'
    names, precedence = [], []
    for k in range(keys):
        for _ in range(rng.choice([0, 1, 1, 2, 3])):
            names.append((f'k{k}', None if rng.random() < 0.12 else f'n{rng.randrange(300)}'))
        for _ in range(rng.choice([0, 1, 1, 2])):
            precedence.append((f'k{k}', None if rng.random() < 0.45 else key()))
    rows = [(None if rng.random() < 0.01 else f'c{rng.randrange(components)}', None if rng.random() < 0.04 else key())
            for _ in range(matches)]
    rows += rng.sample(rows, matches // 20)
    return rows, names, precedence


@pytest.fixture(scope='module')
def witness_key_variants(tmp_path_factory):
    """Committed SQL, oracle and every plant over the seeded rows and over no matches, in one engine job each."""
    committed = next(step['sql'] for step in witness_key_steps(root=ROOT) if step['name'] == 'document_witness_keys')
    variants = dict(committed=committed, oracle=PRE_2D76D689_WITNESS_KEYS_SQL)
    variants.update({plant: variants[base].replace(old, new) for plant, (base, old, new) in WITNESS_KEY_PLANTS.items()
                     if old in variants[base]})
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    seeded = seeded_witness_rows()
    cases = dict(seeded=seeded, no_matches=([], seeded[1], seeded[2]))
    results = {}
    for case, rows in cases.items():
        directory = tmp_path_factory.mktemp(case)
        results[case] = run_job(directory, engine, inputs=witness_key_inputs(directory, *rows),
            steps=[dict(name=name, sql=sql, materialize=True) for name, sql in variants.items()], outputs=[],
            queries=[dict(name=name, sql=f'SELECT component, witness_keys, witness_name FROM {name} ORDER BY component')
                     for name in variants])
    return results


def test_document_witness_keys_with_no_matches_is_empty(witness_key_variants):
    assert witness_key_variants['no_matches']['committed'] == []
    assert witness_key_variants['no_matches']['oracle'] == []


def test_document_witness_keys_equals_the_pre_2d76d689_aggregate_on_seeded_rows(witness_key_variants):
    seeded = witness_key_variants['seeded']
    named = [row for row in seeded['oracle'] if row['witness_name'] is not None]
    # The seed reaches every branch: named and unnamed groups, several keys, a NULL key, a NULL component.
    assert len(named) > 100 and len(seeded['oracle']) - len(named) > 100
    assert any(len(row['witness_keys']) > 1 for row in named)
    assert any(None in row['witness_keys'] for row in named)
    assert any(row['component'] is None for row in seeded['oracle'])
    assert seeded['committed'] == seeded['oracle']


@pytest.mark.parametrize('plant', WITNESS_KEY_PLANTS)
def test_seeded_rows_tell_each_wrong_witness_key_rewrite_from_the_oracle(witness_key_variants, plant):
    assert plant in witness_key_variants['seeded'], f'{plant}: its replaced text is no longer in the SQL'
    assert witness_key_variants['seeded'][plant] != witness_key_variants['seeded']['oracle']


def test_senate_page_plan_is_linear_and_coverage_codes_and_generic_titles_hold(tmp_path):
    # F1, F7, F9:
    # 1. senate-page-meeting-links.sql physical plan has 1 scan of selected_appearance_records,
    #    no Decimal128 coercion, and no unbounded WindowAggExec.
    # 2. source-annotations-codes.sql maps ag/aging/ethics/jec/drugcaucus .senate.gov aliases even when
    #    spicy_committees.website_url differs or is NULL.
    # 3. document-recovery-normalized.sql prefers a non-generic annotation title over a generic reading
    #    title on a witness document, and enriches when all titles are generic.
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    sp = record('sp_plan', 'senate_page', [witness('Alice Senior')],
                context_url='https://www.aging.senate.gov/hearings/senior-care')
    inputs = [
        json_input(tmp_path, 'appearance_records_input', [sp], record_sha_hex='Utf8', parser_version='Utf8', status='Utf8',
                   error_type='Utf8', source='Utf8', event_id='Int64', package_id='Utf8', declared_base='Utf8',
                   collection_state='Utf8', context_url='Utf8', appearances=list_of(struct(**APPEARANCE)), created='Utf8'),
        json_input(tmp_path, 'meetings_input', [dict(event_id=9101, meeting_date=DAY, title=TITLE, not_held=False, chamber='senate', committee_key='spag00')],
                   event_id='Int64', meeting_date='Utf8', title='Utf8', not_held='Boolean', chamber='Utf8', committee_key='Utf8'),
        json_input(tmp_path, 'page_inputs', [dict(body_hex=sp['record_sha_hex'], status='completed', title=TITLE, heading=TITLE, text_head='', content_date=DAY)],
                   body_hex='Utf8', status='Utf8', title='Utf8', heading='Utf8', text_head='Utf8', content_date='Utf8'),
    ]
    steps = [
        dict(name='selected_appearance_records', sql='SELECT * FROM appearance_records_input', materialize=True),
        dict(name='captures', sql=CAPTURES, materialize=True),
        dict(name='meetings_resolved', sql="SELECT event_id,cast(meeting_date AS DATE) AS meeting_date,title,not_held,chamber,committee_key,"
             "make_array(named_struct('system_code',committee_key,'role','host')) AS committees FROM meetings_input", materialize=True),
        dict(name='page_facts', sql="SELECT arrow_cast(decode(body_hex,'hex'),'FixedSizeBinary(32)') AS body_sha,status,title,heading,text_head,content_date FROM page_inputs", materialize=True),
        dict(name='spicy_committees', sql="SELECT cast(NULL AS VARCHAR) AS system_code,cast(NULL AS VARCHAR) AS parent_system_code,cast(NULL AS VARCHAR) AS website_url WHERE false", materialize=True),
        dict(name='appearance_people', sql=sql('appearance-people'), materialize=True),
        dict(name='package_meeting_links', sql='SELECT cast(NULL AS VARCHAR) AS package_id,cast(NULL AS BIGINT) AS event_id WHERE false', materialize=True),
    ]
    explained = run_job(tmp_path / 'plan', engine, inputs=inputs, steps=steps, outputs=[],
                        queries=[dict(name='plan', sql='EXPLAIN ' + sql('senate-page-meeting-links'))])['plan']
    phys = next(r['plan'] for r in explained if r['plan_type'] == 'physical_plan')
    assert 'Decimal128' not in phys
    assert not any(line.lstrip().startswith('WindowAggExec:') for line in phys.splitlines())
    # Only 1 scan of selected_appearance_records (the materialized memory table) in the physical plan:
    assert phys.count('MemoryExec:') <= 6

    # Check source-annotations-codes.sql with host aliases:
    code_inputs = [
        json_input(tmp_path, 'source_filename_readings', [], source_id='Utf8', status='Utf8',
                   committee_code_status='Utf8', committee_code=list_of('Utf8')),
        json_input(tmp_path, 'capture_source_contexts', [
            dict(source_id='s_ag', context_url='https://www.ag.senate.gov/hearings/farm'),
            dict(source_id='s_aging', context_url='https://www.aging.senate.gov/hearings/care'),
            dict(source_id='s_ethics', context_url='https://www.ethics.senate.gov/hearings/ethics'),
            dict(source_id='s_jec', context_url='https://www.jec.senate.gov/hearings/econ'),
            dict(source_id='s_drug', context_url='https://www.drugcaucus.senate.gov/hearings/drug'),
        ], source_id='Utf8', context_url='Utf8'),
        json_input(tmp_path, 'spicy_committees', [
            dict(system_code='SSAF00', parent_system_code=None, website_url='https://www.agriculture.senate.gov/'),
            dict(system_code='SPAG00', parent_system_code=None, website_url=None),
            dict(system_code='SLET00', parent_system_code=None, website_url=None),
            dict(system_code='JSEC00', parent_system_code=None, website_url=None),
            dict(system_code='SCNC00', parent_system_code=None, website_url=None),
        ], system_code='Utf8', parent_system_code='Utf8', website_url='Utf8'),
    ]
    codes = run_job(tmp_path / 'codes', engine, inputs=code_inputs, steps=[], outputs=[],
                    queries=[dict(name='codes', sql=sql('source-annotations-codes') + ' ORDER BY source_id')])['codes']
    assert codes == [
        dict(source_id='s_ag', code='SSAF00'),
        dict(source_id='s_aging', code='SPAG00'),
        dict(source_id='s_drug', code='SCNC00'),
        dict(source_id='s_ethics', code='SLET00'),
        dict(source_id='s_jec', code='JSEC00'),
    ]



