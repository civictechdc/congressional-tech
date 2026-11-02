"""Meeting status, reschedule and witness attachment, run from the maintained SQL over hand rows.

The parser's own stated_facts and title_key build the meeting rows, so the parser feeds the SQL.
"""
import hashlib
import os
from pathlib import Path

import duckdb
import pytest

from congress_api.parsers.meeting_facts import stated_facts
from congress_api.retention.provenance import json_input, list_of, parquet_output, run_job, struct
from docspec_client.client import NativeDatasets

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


def meeting(event_id, date, title, status=None, video=False):
    facts = stated_facts('Hearing', title, status)
    return (f"SELECT cast({event_id} AS BIGINT) AS event_id,'house' AS chamber,{text(title)} AS title,"
            f"cast('{date}' AS DATE) AS meeting_date,'Hearing' AS meeting_type,cast(NULL AS SMALLINT) AS session,"
            f"cast({text(status)} AS VARCHAR) AS status,{EMPTY_SITTINGS} AS sittings,"
            "array_slice(make_array(named_struct('system_code',cast(NULL AS VARCHAR),'role',cast(NULL AS VARCHAR))),1,0) AS committees,"
            "arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') AS subject_keys,"
            f"{VIDEO.format(event_id) if video else NO_VIDEOS} AS videos,cast(118 AS INT) AS congress,"
            f"{UTC} AS congress_gov_updated,cast(NULL AS VARCHAR) AS house_xml_updated,'Hearing' AS congress_gov_meeting_type,"
            f"{text(facts['access'])} AS access,cast(NULL AS VARCHAR) AS access_basis,{str(facts['not_held']).lower()} AS not_held,"
            f"cast({text(facts['title_key'])} AS VARCHAR) AS title_key,{str(facts['reschedule_candidate']).lower()} AS reschedule_candidate,"
            "'hsif00' AS committee_key")


UTC = "arrow_cast(NULL,'Timestamp(Microsecond, Some(\"UTC\"))')"
POWER = 'Powering America: Defining Reliability in a Transforming Electricity Industry'
INSURRECTION = 'The Capitol Insurrection: Unexplained Delays and Unanswered Questions'
FTC = 'The FTC at 100: Where Do We Go From Here regulatory'
POSTPONED = 'Challenges to Democracy in the Western Hemisphere'
NEVER = 'Wildfire funding and forest management practices review'
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
]


@pytest.fixture(scope='module')
def meetings(tmp_path_factory):
    work = tmp_path_factory.mktemp('meeting-semantics')
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    steps = [
        dict(name='meetings_resolved', sql=' UNION ALL '.join(MEETINGS), materialize=True),
        dict(name='ordered', sql="SELECT arrow_cast(array_slice(make_array('1'),1,0),'List(Utf8)') AS meeting_keys", materialize=True),
        dict(name='meeting_transcript_links', sql="SELECT cast(NULL AS VARCHAR) AS package_id,cast(NULL AS BIGINT) AS event_id WHERE false", materialize=True),
        dict(name='details', sql="SELECT cast(NULL AS VARCHAR) AS package_id,cast(NULL AS INT) AS list_row WHERE false", materialize=True),
        dict(name='meetings_export', sql=sql('entity-meetings'), materialize=True),
    ]
    run_job(work, engine, inputs=[], steps=steps,
            outputs=[parquet_output(work, 'meetings', 'SELECT * FROM meetings_export', ['event_id'])])
    with duckdb.connect() as db:
        found = db.execute(f"SELECT event_id,rescheduled_to,rescheduled_basis,not_held FROM read_parquet('{work / 'meetings.parquet'}')").fetchall()
    return {row[0]: row[1:] for row in found}


def test_rescheduled_with_its_own_recording_sat(meetings):
    assert meetings[1][0] is None


def test_a_later_part_is_not_the_same_meeting(meetings):
    assert meetings[3][0] is None


def test_rescheduled_without_a_recording_moves_by_publisher_status(meetings):
    assert meetings[5][:2] == (6, 'publisher_status')


def test_postponed_moves_even_with_a_recording_of_its_own(meetings):
    assert meetings[7][:3] == (8, 'publisher_status', True)


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


def witness(name, links=()):
    return {**{k: None for k in APPEARANCE}, 'source_locator': f'w:{name}', 'name': name, 'document_links': list(links)}


def record(tag, source, appearances, event_id=None, package_id=None):
    return dict(record_sha_hex=hashlib.sha256(tag.encode()).hexdigest(), parser_version='v', status='completed', error_type=None,
                source=source, event_id=event_id, package_id=package_id, declared_base=None, collection_state='present',
                context_url=None, appearances=appearances)


LIST = 'https://docs.house.gov/meetings/HM/HM00/20130718/{}/HHRG-113-HM00-Wstate-X-20130718.pdf'


def resolve(tmp_path, records, links, named):
    """Witness rows per name, from the maintained package-link and appearance SQL."""
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    inputs = [
        json_input(tmp_path, 'appearance_records_input', records, record_sha_hex='Utf8', parser_version='Utf8', status='Utf8',
                   error_type='Utf8', source='Utf8', event_id='Int64', package_id='Utf8', declared_base='Utf8',
                   collection_state='Utf8', context_url='Utf8', appearances=list_of(struct(**APPEARANCE))),
        json_input(tmp_path, 'meeting_transcript_links', [dict(package_id=p, event_id=e) for p, e in links], package_id='Utf8', event_id='Int64'),
        json_input(tmp_path, 'package_mods_facts', [dict(package_id=p, named_meetings=n) for p, n in named.items()],
                   package_id='Utf8', named_meetings=list_of('Int64')),
        json_input(tmp_path, 'meeting_sources', [dict(kind='appearance', source=s, priority=i) for i, s in enumerate(('house_xml', 'congress_gov', 'mods'), 1)],
                   kind='Utf8', source='Utf8', priority='Int32'),
        json_input(tmp_path, 'appearance_url_keys', [], url='Utf8', url_key='Utf8', error='Utf8'),
        json_input(tmp_path, 'selected_meeting_records', [], record_sha_hex='Utf8', status='Utf8', meetings=list_of(struct(updated='Utf8'))),
    ]
    steps = [dict(name='selected_appearance_records', sql='SELECT * FROM appearance_records_input', materialize=True),
             dict(name='captures', sql=CAPTURES, materialize=True),
             dict(name='package_meeting_links', sql=sql('package-meeting-links'), materialize=True),
             dict(name='appearance_records_resolved', sql=sql('appearance-records-resolved'), materialize=True)]
    found = run_job(tmp_path, engine, inputs=inputs, steps=steps, outputs=[], queries=[
        dict(name='rows', sql='SELECT name,occasion,event_id FROM appearance_records_resolved ORDER BY name')])['rows']
    return {r['name']: (r['occasion'], r['event_id']) for r in found}


def test_an_event_with_two_packages_attaches_neither(tmp_path):
    got = resolve(tmp_path, [record('a', 'mods', [witness('A')], package_id='CHRG-a'), record('b', 'mods', [witness('B')], package_id='CHRG-b')],
                  [('CHRG-a', 9001), ('CHRG-b', 9001)], {})
    assert got == {'A': ('package:CHRG-a', None), 'B': ('package:CHRG-b', None)}


def test_the_package_whose_mods_names_the_event_attaches(tmp_path):
    got = resolve(tmp_path, [record('a', 'mods', [witness('A')], package_id='CHRG-a'), record('b', 'mods', [witness('B')], package_id='CHRG-b')],
                  [('CHRG-a', 9001), ('CHRG-b', 9001)], {'CHRG-a': [9001]})
    assert got == {'A': ('meeting:9001', 9001), 'B': ('package:CHRG-b', None)}


def test_a_print_and_its_errata_whose_mods_both_name_the_event_both_attach(tmp_path):
    # CHRG-117shrg45636 and its errata CHRG-117shrg49900 both state <eventId>321961</eventId>.
    got = resolve(tmp_path, [record('a', 'mods', [witness('A')], package_id='CHRG-a'), record('b', 'mods', [witness('B')], package_id='CHRG-b')],
                  [('CHRG-a', 9001), ('CHRG-b', 9001)], {'CHRG-a': [9001], 'CHRG-b': [9001]})
    assert {occasion for occasion, _ in got.values()} == {'meeting:9001'}


def test_an_exclusive_link_whose_mods_names_another_event_stays_a_package(tmp_path):
    got = resolve(tmp_path, [record('a', 'mods', [witness('A')], package_id='CHRG-a')], [('CHRG-a', 9001)], {'CHRG-a': [9002]})
    assert got == {'A': ('package:CHRG-a', None)}


def test_a_house_list_without_meeting_id_takes_the_event_its_links_state(tmp_path):
    got = resolve(tmp_path, [record('h', 'house_xml', [witness('H', [LIST.format(101160)])]),
                             record('two', 'house_xml', [witness('T1', [LIST.format(101160)]), witness('T2', [LIST.format(101161)])])], [], {})
    assert got == {'H': ('meeting:101160', 101160)}  # Links naming two events give no occasion.


def test_a_package_mods_names_its_meeting_as_a_link(tmp_path):
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    inputs = [json_input(tmp_path, 'package_mods_facts', [dict(package_id='CHRG-m', named_meetings=[5, 404])],
                         package_id='Utf8', named_meetings=list_of('Int64'))]
    steps = [dict(name='meetings_resolved', sql=' UNION ALL '.join(MEETINGS), materialize=True),
             dict(name='meeting_mods_links', sql=sql('meeting-mods-links'), materialize=True)]
    found = run_job(tmp_path, engine, inputs=inputs, steps=steps, outputs=[], queries=[
        dict(name='links', sql='SELECT package_id,event_id FROM meeting_mods_links')])['links']
    assert found == [dict(package_id='CHRG-m', event_id=5)]  # 404 is no meeting held here.
