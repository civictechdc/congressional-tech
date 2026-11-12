"""The five Explorer tables, run from their maintained SQL over hand-derived rows."""
import json
import os
from pathlib import Path

import duckdb
import pytest

from congress_api.retention.provenance import json_input, parquet_output, run_job
from docspec_client.client import NativeDatasets
from viewer_publication.archive_schema import build_schema

ROOT = Path(__file__).parents[3]
UTC = "arrow_cast(NULL,'Timestamp(Microsecond, Some(\"UTC\"))')"
LINKED, CONFLICT_PKG, SHARED_PKG, SOLO_PKG = 1001, 'CHRG-conflict', 'CHRG-shared', 'CHRG-solo'


def sql(name):
    return (ROOT / 'model/sql' / (name + '.sql')).read_text()


def decision(id, kind, subject, verdict, refs=(), note=None, disputed_by=None):
    return dict(id=id, subject_kind=kind, subject_id=subject, verdict=verdict, video_refs=list(refs), note=note, disputed_by=disputed_by, decided_at=None, supersedes=None)


@pytest.fixture(scope='module')
def tables(tmp_path_factory):
    """Meetings 1001 (publisher link), 1002, 1003, 1004; three packages; three videos."""
    work = tmp_path_factory.mktemp('explorer')
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    inputs = [
        json_input(work, 'active_recording_decisions', [
            decision('a' * 64, 'package', CONFLICT_PKG, 'no_video_found', note='not on the channel'),
            decision('b' * 64, 'package', SHARED_PKG, 'no_video_found'),
            decision('c' * 64, 'package', SOLO_PKG, 'no_video_found'),
            decision('e' * 64, 'package', 'CHRG-alone', 'no_video_found'),
            decision('9' * 64, 'package', 'CHRG-sibling', 'no_video_found'),
            # Its own MODS names another meeting, so its verdict cannot settle 1010 (ct-dx22).
            decision('8' * 64, 'package', 'CHRG-unattached', 'no_video_found'),
            decision('f' * 64, 'package', 'CHRG-disputed', 'no_video_found', disputed_by='old matcher says full_recording'),
            decision('d' * 64, 'event', '1002', 'found', ['https://example.test/watch']),
            decision('1' * 64, 'event', '1011', 'no_video_found'),
            decision('2' * 64, 'package', 'CHRG-qualified', 'found', ['https://example.test/watch']),
        ], id='Utf8', subject_kind='Utf8', subject_id='Utf8', verdict='Utf8', video_refs=_list(),
           note='Utf8', disputed_by='Utf8', decided_at='Utf8', supersedes='Utf8'),
    ]
    steps = [
        dict(name='meetings_resolved', sql=f"""SELECT cast(1001 AS BIGINT) AS event_id,make_array(named_struct('name','Stream','url','https://youtu.be/pub','video_key','youtube:pub')) AS videos,arrow_cast(make_array(cast(9 AS BIGINT)),'List(Int64)') AS transcript_jackets
            UNION ALL SELECT 1002,array_slice(make_array(named_struct('name',cast(NULL AS VARCHAR),'url',cast(NULL AS VARCHAR),'video_key',cast(NULL AS VARCHAR))),1,0),arrow_cast(make_array(cast(9 AS BIGINT)),'List(Int64)')""", materialize=True),
        # 1008 is a Senate meeting with nothing linked; 1009 lists documents not held; 1010 has a linked
        # package whose witnesses are unattached; 1011 is named only by a package's MODS.
        # 1009 holds a caption track and its committee's transcript file (ct-1i4q).
        dict(name='meetings_export', sql="""SELECT cast(event_id AS BIGINT) AS event_id,chamber,cast('Hearing' AS VARCHAR) AS meeting_type,CASE WHEN event_id=1009 THEN make_array(
              named_struct('source','captions','package_id',cast(NULL AS VARCHAR),'list_row',cast(NULL AS INT),'video_key','youtube:v','language','en','production','asr'),
              named_struct('source','committee_transcript','package_id',cast(NULL AS VARCHAR),'list_row',cast(3 AS INT),'video_key',cast(NULL AS VARCHAR),'language',cast(NULL AS VARCHAR),'production',cast(NULL AS VARCHAR)))
             ELSE array_slice(make_array(named_struct('source',cast(NULL AS VARCHAR),'package_id',cast(NULL AS VARCHAR),'list_row',cast(NULL AS INT),
              'video_key',cast(NULL AS VARCHAR),'language',cast(NULL AS VARCHAR),'production',cast(NULL AS VARCHAR))),1,0) END AS transcripts,
             CASE WHEN event_id IN (1014,1019) THEN 'Nomination of Pat Nominee to be Judge' ELSE 'Hearing' END AS title
            FROM (SELECT 1001 AS event_id,'house' AS chamber UNION ALL SELECT 1002,'house' UNION ALL SELECT 1003,'house' UNION ALL SELECT 1004,'house' UNION ALL SELECT 1005,'house'
             UNION ALL SELECT 1006,'house' UNION ALL SELECT 1007,'house' UNION ALL SELECT 1008,'senate' UNION ALL SELECT 1009,'house' UNION ALL SELECT 1010,'house' UNION ALL SELECT 1011,'house'
             UNION ALL SELECT 1012,'house' UNION ALL SELECT 1013,'house' UNION ALL SELECT 1014,'senate' UNION ALL SELECT 1015,'house'
             UNION ALL SELECT 1016,'senate' UNION ALL SELECT 1017,'house' UNION ALL SELECT 1018,'house' UNION ALL SELECT 1019,'senate')""", materialize=True),
        dict(name='meeting_transcript_links', sql=f"""SELECT '{CONFLICT_PKG}' AS package_id,cast(1001 AS BIGINT) AS event_id UNION ALL SELECT '{SHARED_PKG}',1003 UNION ALL SELECT '{SHARED_PKG}',1004 UNION ALL SELECT '{SOLO_PKG}',1002 UNION ALL SELECT 'CHRG-alone',1005 UNION ALL SELECT 'CHRG-disputed',1006 UNION ALL SELECT 'CHRG-sibling',1007 UNION ALL SELECT 'CHRG-no-verdict',1007 UNION ALL SELECT 'CHRG-unattached',1010 UNION ALL SELECT 'CHRG-qualified',1002 UNION ALL SELECT 'CHRG-qualified',1004
            UNION ALL SELECT 'CHRG-senator-only',1016 UNION ALL SELECT 'CHRG-reps-only',1017 UNION ALL SELECT 'CHRG-member-and-outside',1018 UNION ALL SELECT 'CHRG-introducer-only',1019""", materialize=True),
        dict(name='package_mods_facts', sql="""SELECT 'CHRG-unattached' AS package_id,arrow_cast(make_array(cast(9999 AS BIGINT)),'List(Int64)') AS named_meetings
            UNION ALL SELECT 'CHRG-unlinked',arrow_cast(make_array(cast(1011 AS BIGINT)),'List(Int64)')""", materialize=True),
        # The packages whose own print stands for their meeting (rule tested in test_meeting_semantics);
        # CHRG-unattached's print names another meeting, and 1003, 1004 and 1007 have no such print.
        dict(name='package_meeting_links', sql=f"""SELECT '{CONFLICT_PKG}' AS package_id,cast(1001 AS BIGINT) AS event_id
            UNION ALL SELECT '{SOLO_PKG}',1002 UNION ALL SELECT 'CHRG-alone',1005 UNION ALL SELECT 'CHRG-disputed',1006 UNION ALL SELECT 'CHRG-qualified',1002 UNION ALL SELECT 'CHRG-qualified',1004""", materialize=True),
        dict(name='meeting_document_urls', sql="SELECT cast(1009 AS BIGINT) AS event_id,'https://docs.house.gov/x.pdf' AS url", materialize=True),
        dict(name='videos_export', sql="""SELECT 'youtube:pub' AS video_key,arrow_cast(decode(repeat('ab',32),'hex'),'FixedSizeBinary(32)') AS record_sha,arrow_cast(make_array(cast(777777 AS BIGINT)),'List(Int64)') AS stated_event_ids,true AS has_caption,cast(3600 AS INT) AS duration_seconds,cast('Hearing' AS VARCHAR) AS title
            UNION ALL SELECT 'youtube:nocaption',arrow_cast(decode(repeat('ac',32),'hex'),'FixedSizeBinary(32)'),
              arrow_cast(make_array(cast(1003 AS BIGINT)),'List(Int64)'),false,cast(3600 AS INT) AS duration_seconds,cast('Hearing' AS VARCHAR) AS title
            UNION ALL SELECT 'youtube:unmatched',arrow_cast(decode(repeat('ab',32),'hex'),'FixedSizeBinary(32)'),arrow_cast(array_slice(make_array(cast(1 AS BIGINT)),1,0),'List(Int64)'),false,cast(NULL AS INT) AS duration_seconds,cast(NULL AS VARCHAR) AS title""", materialize=True),
        dict(name='selected_appearance_records', sql='SELECT * FROM appearance_records_input', materialize=True),
        dict(name='recording_page_video_events', sql="SELECT cast(NULL AS VARCHAR) AS video_key,cast(NULL AS BIGINT) AS event_id,cast(NULL AS VARCHAR) AS source_ref WHERE false", materialize=True),
        dict(name='recording_matches_export', sql=sql('entity-recording-matches'), materialize=True),
        dict(name='ordered', sql="SELECT arrow_cast(make_array('1001'),'List(Utf8)') AS meeting_keys", materialize=True),
        # 1001 shows Jane once: the print's Jane is superseded by the meeting's own row, and a letter for the
        # record is a statement, not a witness. 1012 lists only a sitting Member, 1013 a Member and an outside
        # witness, 1014 only the Member introducing a nominee it leaves out, 1015 a Member and record material (ct-kw85).
        # A linked print's rows tied to no meeting: 1016's names only a Senator (as Bennet's for 337704), 1017's two
        # Representatives (as Smith's and Walz's for 104324), 1018's a Member and an outside witness, and 1019's only the
        # Senator introducing a nominee.
        dict(name='witnesses_export', sql="""SELECT cast(1001 AS BIGINT) AS event_id,'Jane' AS name,cast(NULL AS VARCHAR) AS package_id,
            cast(NULL AS VARCHAR) AS witness_type,cast(NULL AS VARCHAR) AS superseded_by
            UNION ALL SELECT 1001 AS event_id,'Jane' AS name,'CHRG-x' AS package_id,cast(NULL AS VARCHAR) AS witness_type,'abc' AS superseded_by
            UNION ALL SELECT 1001 AS event_id,'Letter of support' AS name,'CHRG-x' AS package_id,'statement_for_record' AS witness_type,cast(NULL AS VARCHAR) AS superseded_by
            UNION ALL SELECT cast(NULL AS BIGINT) AS event_id,'Joe' AS name,'CHRG-unattached' AS package_id,cast(NULL AS VARCHAR) AS witness_type,cast(NULL AS VARCHAR) AS superseded_by
            UNION ALL SELECT 1012 AS event_id,'The Honorable Ann Member' AS name,cast(NULL AS VARCHAR) AS package_id,'member_appearance' AS witness_type,cast(NULL AS VARCHAR) AS superseded_by
            UNION ALL SELECT 1013 AS event_id,'The Honorable Ben Member' AS name,cast(NULL AS VARCHAR) AS package_id,'member_appearance' AS witness_type,cast(NULL AS VARCHAR) AS superseded_by
            UNION ALL SELECT 1013 AS event_id,'Cal Outside' AS name,cast(NULL AS VARCHAR) AS package_id,cast(NULL AS VARCHAR) AS witness_type,cast(NULL AS VARCHAR) AS superseded_by
            UNION ALL SELECT 1014 AS event_id,'Senator Dee Introducer' AS name,cast(NULL AS VARCHAR) AS package_id,'member_appearance' AS witness_type,cast(NULL AS VARCHAR) AS superseded_by
            UNION ALL SELECT 1015 AS event_id,'The Honorable Eve Member' AS name,cast(NULL AS VARCHAR) AS package_id,'member_appearance' AS witness_type,cast(NULL AS VARCHAR) AS superseded_by
            UNION ALL SELECT 1015 AS event_id,'Letter of support' AS name,cast(NULL AS VARCHAR) AS package_id,'record_material' AS witness_type,cast(NULL AS VARCHAR) AS superseded_by
            UNION ALL SELECT cast(NULL AS BIGINT) AS event_id,'Hon. Fay Senator' AS name,'CHRG-senator-only' AS package_id,'member_appearance' AS witness_type,cast(NULL AS VARCHAR) AS superseded_by
            UNION ALL SELECT cast(NULL AS BIGINT) AS event_id,'Hon. Gil Rep' AS name,'CHRG-reps-only' AS package_id,'member_appearance' AS witness_type,cast(NULL AS VARCHAR) AS superseded_by
            UNION ALL SELECT cast(NULL AS BIGINT) AS event_id,'Hon. Hal Rep' AS name,'CHRG-reps-only' AS package_id,'member_appearance' AS witness_type,cast(NULL AS VARCHAR) AS superseded_by
            UNION ALL SELECT cast(NULL AS BIGINT) AS event_id,'Hon. Ivy Member' AS name,'CHRG-member-and-outside' AS package_id,'member_appearance' AS witness_type,cast(NULL AS VARCHAR) AS superseded_by
            UNION ALL SELECT cast(NULL AS BIGINT) AS event_id,'Jon Outside' AS name,'CHRG-member-and-outside' AS package_id,cast(NULL AS VARCHAR) AS witness_type,cast(NULL AS VARCHAR) AS superseded_by
            UNION ALL SELECT cast(NULL AS BIGINT) AS event_id,'Senator Kay Introducer' AS name,'CHRG-introducer-only' AS package_id,'member_appearance' AS witness_type,cast(NULL AS VARCHAR) AS superseded_by""", materialize=True),
        dict(name='recordings_export', sql="SELECT 'youtube:unmatched' AS video_key,make_array(1) AS tracks,'unknown' AS recording_scope", materialize=True),
        dict(name='meeting_coverage_export', sql=sql('entity-meeting-coverage'), materialize=True),
    ]
    inputs += [json_input(work, 'appearance_records_input', [
            dict(event_id=1002, source='house_xml', parser_version='v', status='completed', collection_state='empty', appearances=[]),
            dict(event_id=1003, source='house_xml', parser_version='v', status='completed', collection_state='failed', appearances=[]),
            dict(event_id=1016, source='senate_page', parser_version='v', status='completed', collection_state='present', appearances=[])],
            event_id='Int64', source='Utf8', parser_version='Utf8', status='Utf8', collection_state='Utf8', appearances=_list()),
        json_input(work, 'parser_versions', [], parser='Utf8', version='Utf8')]
    outputs = [parquet_output(work, name, 'SELECT * FROM ' + name + '_export', keys)
               for name, keys in (('recording_matches', ['match_id']), ('meeting_coverage', ['event_id', 'aspect']))]
    run_job(work, engine, inputs=inputs, steps=steps, outputs=outputs, queries=[])
    return work


def _list():
    from congress_api.retention.provenance import list_of
    return list_of('Utf8')


def rows(work, table):
    with duckdb.connect() as db:
        cursor = db.execute(f"SELECT * FROM read_parquet('{work / (table + '.parquet')}')")
        names = [item[0] for item in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]


def state(work, event, aspect):
    return next(r['state'] for r in rows(work, 'meeting_coverage') if r['event_id'] == event and r['aspect'] == aspect)


def test_unmatched_video_has_no_match_row_and_stays_out_of_coverage(tables):
    assert not [r for r in rows(tables, 'recording_matches') if r['video_key'] == 'youtube:unmatched']


def test_conflict_keeps_both_rows(tables):
    found = rows(tables, 'recording_matches')
    assert [r['status'] for r in found if r['event_id'] == LINKED and r['basis'] == 'publisher_link'] == ['asserted']
    negative = [r for r in found if r['package_id'] == CONFLICT_PKG]
    assert [(r['decision'], r['status'], r['score']) for r in negative] == [('no_video_found', 'conflicting', None)]


def test_stale_event_id_stays_claimed_and_an_unknown_number_stays_visible(tables):
    stated = [r for r in rows(tables, 'recording_matches') if r['basis'] == 'video_states_event_id']
    known = next(r for r in stated if r['event_id'] == 1003)
    assert known['status'] == 'claimed' and known['score'] == 95
    unknown = next(r for r in stated if r['event_id'] is None)
    assert unknown['status'] == 'claimed' and '777777' in unknown['note'] and unknown['score'] is None


def test_match_ids_are_unique(tables):
    found = rows(tables, 'recording_matches')
    assert len({r['match_id'] for r in found}) == len(found) and all(len(r['match_id']) == 64 for r in found)


def test_print_agreement_attaches_package_context_without_proving_coverage(tables):
    found = rows(tables, 'recording_matches')
    matches = [r for r in found if r['url'] == 'https://example.test/watch']
    assert len({r['match_id'] for r in matches}) == 2
    assert {r['subject_id']: r['meeting_links'] for r in matches} == {
        '1002': [dict(event_id=1002, basis='direct_event', scope='event')],
        'CHRG-qualified': [dict(event_id=1002, basis='print_agreement', scope='package_context'),
                           dict(event_id=1004, basis='print_agreement', scope='package_context')],
    }
    assert all(not r['meeting_links'] for r in found if r['package_id'] in {SHARED_PKG, 'CHRG-unattached', 'CHRG-sibling'})
    assert state(tables, 1004, 'recording') == 'unresolved'
    assert reason(tables, 1004, 'recording') == 'package_context_only'


def test_direct_negative_can_confirm_absence(tables):
    # 1002 also has a curated positive, which wins; 1001 has a publisher link.
    assert state(tables, 1002, 'recording') == 'present'
    assert state(tables, 1001, 'recording') == 'present'
    assert state(tables, 1005, 'recording') == 'unresolved'
    assert state(tables, 1011, 'recording') == 'confirmed_absent'


def test_recording_states_keep_excerpts_claims_and_access_apart(tables):
    assert state(tables, 1002, 'recording') == 'present'
    assert state(tables, 1003, 'recording') == 'claimed'  # Only the video's own text names it.


def test_a_sibling_package_without_a_verdict_blocks_absence(tables):
    assert state(tables, 1007, 'recording') == 'unknown'


def test_disputed_negative_verdict_is_unresolved_with_its_evidence(tables):
    assert state(tables, 1006, 'recording') == 'unresolved'
    row = next(r for r in rows(tables, 'recording_matches') if r['package_id'] == 'CHRG-disputed')
    assert row['status'] == 'unresolved' and 'old matcher says full_recording' in row['note']


def test_coverage_is_meetings_times_aspects_and_states_stay_distinct(tables):
    found = rows(tables, 'meeting_coverage')
    assert len(found) == 19 * 5
    assert state(tables, 1001, 'witnesses') == 'present'
    assert next(r['count'] for r in found if r['event_id'] == 1001 and r['aspect'] == 'witnesses') == 1
    assert state(tables, 1002, 'witnesses') == 'empty'
    assert state(tables, 1003, 'witnesses') == 'unresolved'
    assert state(tables, 1004, 'witnesses') == 'not_stated'
    assert state(tables, 1001, 'transcript') == 'unresolved'
    assert state(tables, 1003, 'transcript') == 'not_stated'
    assert state(tables, 1001, 'captions') == 'present'
    assert state(tables, 1004, 'captions') == 'unknown'  # The recording itself is not settled.
    assert state(tables, 1011, 'captions') == 'not_stated'  # confirmed_absent
    assert 'empty' not in {r['state'] for r in found if r['aspect'] == 'captions'}


def reason(work, event, aspect):
    return next(r['reason'] for r in rows(work, 'meeting_coverage') if r['event_id'] == event and r['aspect'] == aspect)


@pytest.mark.parametrize('event,aspect,expected,why', [
    (1008, 'documents', 'unknown', 'senate_page_links_pending'),
    (1008, 'witnesses', 'unknown', 'senate_page_links_pending'),
    (1009, 'documents', 'unresolved', 'stated_documents_not_held'),
    (1004, 'documents', 'not_stated', None),
    (1010, 'witnesses', 'unknown', 'package_witnesses_unattached'),
    (1011, 'transcript', 'unknown', 'package_names_meeting_unlinked'),
    (1003, 'captions', 'unknown', None),
    (1004, 'captions', 'unknown', 'recording_link_pending'),
    (1009, 'transcript', 'present', 'captions,committee_transcript'),
    (1001, 'documents', 'present', None),
    (1012, 'witnesses', 'empty', 'member_appearances_only'),
    (1013, 'witnesses', 'present', None),
    (1014, 'witnesses', 'unknown', 'nominee_not_listed'),
    (1015, 'witnesses', 'empty', 'member_appearances_only'),
    # Before the fix (2026-11-11 review) 1016 and 1017 ended not_stated: the print's Members were no longer unattached
    # witnesses, and nothing else counted them as the meeting's list.
    (1016, 'witnesses', 'empty', 'member_appearances_only'),
    (1017, 'witnesses', 'empty', 'member_appearances_only'),
    (1018, 'witnesses', 'unknown', 'package_witnesses_unattached'),
    (1019, 'witnesses', 'unknown', 'nominee_not_listed'),
])
def test_held_but_unlinked_evidence_is_unknown_never_not_stated(tables, event, aspect, expected, why):
    assert (state(tables, event, aspect), reason(tables, event, aspect)) == (expected, why)


def test_members_of_congress_are_not_counted_as_witnesses(tables):
    # A meeting whose list names only sitting Members has no outside witness: empty, never not_stated (ct-kw85).
    counts = {r['event_id']: r['count'] for r in rows(tables, 'meeting_coverage') if r['aspect'] == 'witnesses'}
    assert counts[1012] == 0 and counts[1013] == 1


def test_a_package_whose_mods_names_another_meeting_settles_nothing_here(tables):
    assert state(tables, 1010, 'recording') == 'unknown'


def test_old_release_omits_the_tables_and_says_so():
    schema = build_schema(['list.parquet', 'detail.parquet', 'meetings.parquet'])
    tables = {t['name']: t for t in schema['files']}
    assert not tables['videos.parquet']['available']
    recipe = next(r for r in schema['recipes'] if r['id'] == 'coverage_counts')
    assert recipe['missing_tables'] == ['meeting_coverage'] and not recipe['available']


def test_recipes_run_under_duckdb(tables):
    schema = build_schema()
    with duckdb.connect() as db:
        db.execute(f"CREATE VIEW recording_matches AS SELECT * FROM read_parquet('{tables / 'recording_matches.parquet'}')")
        db.execute(f"CREATE VIEW meeting_coverage AS SELECT * FROM read_parquet('{tables / 'meeting_coverage.parquet'}')")
        db.execute("CREATE TABLE videos(video_key VARCHAR,handle VARCHAR,title VARCHAR,published_at TIMESTAMP)")
        db.execute("INSERT INTO videos VALUES ('youtube:unmatched','@A','t',NULL),('youtube:pub','@A','p',NULL)")
        recipes = {r['id']: r for r in schema['recipes']}
        assert db.execute(recipes['channel_unmatched_videos']['sql'], ['@A']).fetchall()[0][0] == 'youtube:unmatched'
        assert db.execute(recipes['meeting_recordings']['sql'], [LINKED]).fetchall()
        # 1002 (its record says none) and the Members-only 1012, 1015, 1016 and 1017.
        assert dict(db.execute(recipes['coverage_counts']['sql'], ['witnesses']).fetchall())['empty'] == 5


def test_videos_channels_and_committee_records_from_lake_rows(tmp_path):
    import pyarrow.parquet as pq
    from congress_api.lake import committee_records, video_records
    from congress_api.parsers.youtube_video import cache_rows
    from viewer_publication.archive_model import channel_directory_rows, selected_record_step
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    cache = json.dumps({'youtube_channels': {'1': dict(handle='@AgRepublicans', channelId='UCX', title='Ag', uploads_scan_complete=True)},
        'youtube_videos_@AgRepublicans': {'1': dict(videoId='v1', title='EventID=117681', publishedAt='2020-01-02T03:04:05Z', channelId='UCX', duration='9', available=True),
                                         '2': dict(videoId='v2')},
        'youtube_videos_@HouseAgDems': {'1': dict(videoId='v1', title='second copy')}}).encode()
    sha_new, sha_old, sha_api = 'ab' * 32, 'cd' * 32, 'ef' * 32
    directory = channel_directory_rows()
    ag = next(row['channel_id'] for row in directory if row['handle'] == '@AgRepublicans')
    # API videos fill only IDs no cache lists, and only for directory channels.
    item = lambda vid, channel, title: dict(kind='youtube#video', id=vid, snippet=dict(channelId=channel, title=title, publishedAt='2025-09-17T14:00:00Z'),
        contentDetails=dict(duration='P1DT10H30M28S'), status=dict(privacyStatus='unlisted'))
    api = json.dumps(dict(kind='youtube#videoListResponse', items=[item('v1', ag, 'API copy'), item('v3', ag, 'Unlisted EventID=118000'),
        item('v4', 'UCnot-in-directory', 'Elsewhere')])).encode()
    # An old-version copy of the same body must lose before ranking, whatever its order.
    pq.write_table(video_records.table([video_records.build_row(sha_new, 'youtube_cache', b'{"youtube_videos_@AgRepublicans":{"1":{"videoId":"old-version"}}}', parser_version='older'),
        video_records.build_row(sha_new, 'youtube_cache', cache, parser_version='p'),
        video_records.build_row(sha_old, 'youtube_cache', b'{"youtube_videos_@AgRepublicans":{"1":{"videoId":"stale"}}}', parser_version='p'),
        video_records.build_row(sha_api, 'youtube_api', api, parser_version='a')]), tmp_path / 'videos.parquet')
    amendment = dict(kind='amendment', bill='H.R. 1', number='1', sponsor_bioguide='A000001', amendment_type=None, enbloc=None, description='d', url='https://a')
    records = lambda sha, updated, count: dict(record_sha=sha, parser_version='p', status='completed', source='house_xml', event_id='100', updated=updated,
        records=[dict(amendment, ordinal=i) for i in range(count)])
    pq.write_table(committee_records.table([records(sha_old, '2020-01-01T00:00:00', 1), records(sha_new, '2021-01-01T00:00:00', 2)]), tmp_path / 'committee.parquet')
    inputs = [dict(name='video_records', kind='parquet', path=str(tmp_path / 'videos.parquet')),
        dict(name='committee_records', kind='parquet', path=str(tmp_path / 'committee.parquet')),
        json_input(tmp_path, 'parser_versions', [dict(parser='video_records.youtube_cache', version='p'), dict(parser='video_records.youtube_api', version='a'),
            dict(parser='committee_records.house_xml', version='p')], parser='Utf8', version='Utf8'),
        json_input(tmp_path, 'channel_directory', directory, handle='Utf8', channel_id='Utf8', system_code='Utf8', committee_label='Utf8', role='Utf8')]
    steps = [dict(name='youtube_cache_bodies', sql=f"SELECT 'youtube/youtube_00.json' AS cache_path,'{sha_new}' AS record_sha,'' AS stored_suffix"),
        dict(name='youtube_api_bodies', sql=f"SELECT '{sha_api}' AS record_sha,'' AS stored_suffix"),
        selected_record_step('video_records', 'video_records'), selected_record_step('committee_records', 'committee_records')]
    outputs = [parquet_output(tmp_path, 'v', sql('entity-videos'), ['video_key']), parquet_output(tmp_path, 'c', sql('entity-channels'), ['handle']),
        parquet_output(tmp_path, 'r', sql('entity-committee-records'), ['record_key'])]
    run_job(tmp_path / 'job', engine, inputs=inputs, steps=steps, outputs=outputs, queries=[])
    videos = {row['video_key']: row for row in pq.read_table(tmp_path / 'v.parquet').to_pylist()}
    assert set(videos) == {'youtube:v1', 'youtube:v2', 'youtube:v3'}  # The unmatched stays; a stale body and a repeat do not add rows.
    assert videos['youtube:v1']['title'] == 'EventID=117681'  # The cache row, not the API copy.
    assert videos['youtube:v3']['handle'] == '@AgRepublicans' and videos['youtube:v3']['system_code'] == 'hsag00'
    assert videos['youtube:v3']['duration_seconds'] == 124228 and videos['youtube:v3']['stated_event_ids'] == [118000]
    assert videos['youtube:v1']['handle'] == '@AgRepublicans' and videos['youtube:v1']['duration_seconds'] == 9
    assert videos['youtube:v1']['stated_event_ids'] == [117681] and videos['youtube:v1']['system_code'] == 'hsag00'
    assert videos['youtube:v2']['available'] is None and videos['youtube:v1']['published_at'] is not None
    channels = pq.read_table(tmp_path / 'c.parquet').to_pylist()
    assert len(channels) == len(directory) == 119 and {row['mapping_basis'] for row in channels} == {'curated_directory'}
    assert next(row for row in channels if row['handle'] == '@AgRepublicans')['uploads_scan_complete'] is True
    kept = pq.read_table(tmp_path / 'r.parquet').to_pylist()
    assert [row['ordinal'] for row in sorted(kept, key=lambda row: row['ordinal'])] == [0, 1]  # Latest record; duplicates keep two keys.
    assert len({row['record_key'] for row in kept}) == 2 and kept[0]['record_sha'] == bytes.fromhex(sha_new)


def test_only_a_pinned_version_failure_settles_an_explorer_record():
    from viewer_publication.archive_model import explorer_settled_sql
    from congress_api.retention.provenance import run_job as run
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        work = Path(folder)
        inputs = [json_input(work, 'active_unreadable', [
                dict(record_sha='old', body_sha256=None, parser='video_records', parser_version='v1'),
                dict(record_sha='new', body_sha256=None, parser='video_records', parser_version='v2')],
                record_sha='Utf8', body_sha256='Utf8', parser='Utf8', parser_version='Utf8'),
            json_input(work, 'parser_versions', [dict(parser='video_records.youtube_cache', version='v2')], parser='Utf8', version='Utf8')]
        steps = [dict(name='selected_video_records', sql="SELECT arrow_cast(decode(repeat('ab',32),'hex'),'FixedSizeBinary(32)') AS record_sha,'completed' AS status")]
        result = run(work / 'job', engine, inputs=inputs, steps=steps, outputs=[], queries=[dict(name='s', sql=explorer_settled_sql('video_records') + ' ORDER BY sha')])
    assert [row['sha'] for row in result['s']] == ['ab' * 32, 'new']  # The old version's failure settles nothing.


def test_entity_videos_trims_surrounding_whitespace_and_nulls_blank_text(tmp_path):
    """ct-p5m8: surrounding whitespace is trimmed and whitespace-only title/source_description become NULL."""
    import pyarrow.parquet as pq
    from congress_api.lake import video_records
    from congress_api.retention.provenance import parquet_output, run_job as run
    from viewer_publication.archive_model import channel_directory_rows, selected_record_step

    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    directory = channel_directory_rows()
    ag = next(row['channel_id'] for row in directory if row['handle'] == '@AgRepublicans')
    cache = json.dumps({
        'youtube_videos_@AgRepublicans': {
            '1': dict(videoId='v_trail', title='  Hearing Title \n', description='  Body text  \t', channelId=ag),
            '2': dict(videoId='v_blank_one', title='   ', description=' ', channelId=ag),
            '3': dict(videoId='v_blank_two', title='\u00a0\t\n', description='  \u00a0 ', channelId=ag),
        }
    }).encode()
    sha = 'ab' * 32
    pq.write_table(video_records.table([video_records.build_row(sha, 'youtube_cache', cache, parser_version='p')]),
                   tmp_path / 'videos.parquet')
    inputs = [
        dict(name='video_records', kind='parquet', path=str(tmp_path / 'videos.parquet')),
        json_input(tmp_path, 'parser_versions', [
            dict(parser='video_records.youtube_cache', version='p'),
            dict(parser='video_records.youtube_api', version='a'),
        ], parser='Utf8', version='Utf8'),
        json_input(tmp_path, 'channel_directory', directory,
                   handle='Utf8', channel_id='Utf8', system_code='Utf8', committee_label='Utf8', role='Utf8'),
    ]
    steps = [
        dict(name='youtube_cache_bodies', sql=f"SELECT 'youtube/youtube_00.json' AS cache_path,'{sha}' AS record_sha,'' AS stored_suffix"),
        dict(name='youtube_api_bodies', sql="SELECT '' AS record_sha,'' AS stored_suffix WHERE false"),
        selected_record_step('video_records', 'video_records'),
    ]
    run(tmp_path / 'job', engine, inputs=inputs, steps=steps,
        outputs=[parquet_output(tmp_path, 'v', sql('entity-videos'), ['video_key'])], queries=[])
    rows = {r['video_key']: r for r in pq.read_table(tmp_path / 'v.parquet').to_pylist()}
    assert rows['youtube:v_trail']['title'] == 'Hearing Title'
    assert rows['youtube:v_trail']['source_description'] == 'Body text'
    assert rows['youtube:v_blank_one']['title'] is None
    assert rows['youtube:v_blank_one']['source_description'] is None
    assert rows['youtube:v_blank_two']['title'] is None
    assert rows['youtube:v_blank_two']['source_description'] is None


def test_recording_matches_is_single_owner_of_video_to_meeting_links(tmp_path):
    """ct-yizl: recording_matches owns video-to-meeting links; recordings.event_ids derives from it with 0 disagreement."""
    import pyarrow.parquet as pq
    from viewer_publication import archive_model

    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    inputs = [
        json_input(tmp_path, 'active_recording_decisions', [
            decision('1' * 64, 'event', '1002', 'found', ['curatedVid01']),
            decision('2' * 64, 'event', '1005', 'no_video_found'),
            decision('3' * 64, 'package', 'CHRG-pkg', 'found_tracked', ['pkgOnlyVid1']),
        ], id='Utf8', subject_kind='Utf8', subject_id='Utf8', verdict='Utf8', video_refs=_list(),
           note='Utf8', disputed_by='Utf8', decided_at='Utf8', supersedes='Utf8'),
        json_input(tmp_path, 'recording_sources',
                   json.loads((ROOT / 'model/registries/recording-sources.json').read_text()),
                   id='Utf8', kind='Utf8', pattern='Utf8', key_template='Utf8',
                   format='Utf8', default_language='Utf8', default_production='Utf8'),
    ]
    recordings_sql = getattr(archive_model, 'recordings_export_sql', lambda **_kw: sql('entity-recordings'))(
        root=ROOT, explorer_inputs=True
    )
    steps = [
        dict(name='recording_url_sources', sql="SELECT id,pattern,key_template,format,default_language,default_production FROM recording_sources WHERE kind='video_url'", materialize=True),
        dict(name='meetings_resolved', sql="""SELECT cast(1001 AS BIGINT) AS event_id,
            make_array(named_struct('name','Stream','url','https://youtu.be/pubVid00001','video_key','youtube:pubVid00001')) AS videos
            UNION ALL SELECT 1002,array_slice(make_array(named_struct('name',cast(NULL AS VARCHAR),'url',cast(NULL AS VARCHAR),'video_key',cast(NULL AS VARCHAR))),1,0)
            UNION ALL SELECT 1004,array_slice(make_array(named_struct('name',cast(NULL AS VARCHAR),'url',cast(NULL AS VARCHAR),'video_key',cast(NULL AS VARCHAR))),1,0)
            UNION ALL SELECT 1005,array_slice(make_array(named_struct('name',cast(NULL AS VARCHAR),'url',cast(NULL AS VARCHAR),'video_key',cast(NULL AS VARCHAR))),1,0)
            UNION ALL SELECT 119546,array_slice(make_array(named_struct('name',cast(NULL AS VARCHAR),'url',cast(NULL AS VARCHAR),'video_key',cast(NULL AS VARCHAR))),1,0)""", materialize=True),
        dict(name='meetings_export', sql="SELECT event_id,cast('Hearing' AS VARCHAR) AS meeting_type,cast('Hearing' AS VARCHAR) AS title FROM meetings_resolved", materialize=True),
        dict(name='meeting_transcript_links', sql="SELECT 'CHRG-pkg' AS package_id,cast(1004 AS BIGINT) AS event_id", materialize=True),
        dict(name='package_meeting_links', sql="SELECT 'CHRG-pkg' AS package_id,cast(1004 AS BIGINT) AS event_id", materialize=True),
        dict(name='recording_video_links', sql="""SELECT 'aa' AS page_body,'youtube:0YtytQuMCT8' AS extracted_key
            UNION ALL SELECT 'bb','youtube:pageVid0004'
            UNION ALL SELECT 'cc','youtube:unmatched99'""", materialize=True),
        dict(name='recording_page_meetings', sql="SELECT 'bb' AS page_body,cast(1004 AS BIGINT) AS event_id", materialize=True),
        dict(name='recording_tracks', sql="""SELECT cast(NULL AS VARCHAR) AS video_key,
            array_slice(make_array(named_struct('body',arrow_cast(NULL,'FixedSizeBinary(32)'),'suffix',cast(NULL AS VARCHAR),
             'format',cast(NULL AS VARCHAR),'language',cast(NULL AS VARCHAR),'production',cast(NULL AS VARCHAR))),1,0) AS tracks WHERE false""", materialize=True),
        dict(name='recordings_entity', sql=sql('entity-recordings'), materialize=True),
        dict(name='recording_page_video_events', sql="""SELECT video_key,event_id,'committee_page:'||min(page_body) AS source_ref
            FROM (SELECT pvl.page_body,pvl.extracted_key AS video_key,pm.event_id
                  FROM recording_video_links pvl JOIN recording_page_meetings pm ON pvl.page_body=pm.page_body
                  WHERE pvl.extracted_key IS NOT NULL AND pm.event_id IS NOT NULL)
            GROUP BY video_key,event_id""", materialize=True),
        dict(name='videos_export', sql="""SELECT 'youtube:0YtytQuMCT8' AS video_key,
            arrow_cast(decode(repeat('ab',32),'hex'),'FixedSizeBinary(32)') AS record_sha,
            arrow_cast(make_array(cast(119546 AS BIGINT)),'List(Int64)') AS stated_event_ids,false AS has_caption,
            cast(5400 AS INT) AS duration_seconds,cast('Hearing' AS VARCHAR) AS title""", materialize=True),
        dict(name='recording_matches_export', sql=sql('entity-recording-matches'), materialize=True),
        dict(name='recordings_export', sql=recordings_sql, materialize=True),
    ]
    run_job(tmp_path / 'job', engine, inputs=inputs, steps=steps, outputs=[
        parquet_output(tmp_path, 'recording_matches', 'SELECT * FROM recording_matches_export', ['match_id']),
        parquet_output(tmp_path, 'recordings', 'SELECT * FROM recordings_export', ['video_key']),
    ], queries=[])
    rec = {r['video_key']: r['event_ids'] for r in rows(tmp_path, 'recordings')}
    matches = rows(tmp_path, 'recording_matches')

    assert rec['youtube:pubVid00001'] == [1001]
    assert rec['youtube:0YtytQuMCT8'] == [119546]
    assert rec['youtube:curatedVid01'] == [1002]
    assert rec['youtube:pageVid0004'] == [1004]
    assert rec['youtube:unmatched99'] == []
    assert 'youtube:pkgOnlyVid1' not in rec

    rec_pairs = {(vk, ev) for vk, evs in rec.items() for ev in evs}
    match_pairs = {
        (m['video_key'], link['event_id'])
        for m in matches
        if m['video_key'] is not None
        and m['status'] in ('asserted', 'claimed', 'decided')
        and m['decision'] not in ('no_video_found', 'not_public')
        for link in m['meeting_links']
        if link['scope'] == 'event' and link['event_id'] is not None
    }
    assert rec_pairs == match_pairs


def test_committee_page_recording_links_and_recording_scope(tmp_path):
    """ct-ywz2: committee pages link provable proceedings to meetings; recordings mark full vs excerpt vs unknown."""
    from viewer_publication import archive_model

    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    inputs = [
        json_input(tmp_path, 'active_recording_decisions', [],
                   id='Utf8', subject_kind='Utf8', subject_id='Utf8', verdict='Utf8', video_refs=_list(),
                   note='Utf8', disputed_by='Utf8', decided_at='Utf8', supersedes='Utf8'),
        json_input(tmp_path, 'recording_sources',
                   json.loads((ROOT / 'model/registries/recording-sources.json').read_text()),
                   id='Utf8', kind='Utf8', pattern='Utf8', key_template='Utf8',
                   format='Utf8', default_language='Utf8', default_production='Utf8'),
    ]
    steps = [
        dict(name='recording_url_sources', sql="SELECT id,pattern,key_template,format,default_language,default_production FROM recording_sources WHERE kind='video_url'", materialize=True),
        dict(name='meetings_resolved', sql="""SELECT *,arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)') AS transcript_jackets FROM (
            SELECT cast(118500 AS BIGINT) AS event_id,'house' AS chamber,cast('2025-09-15' AS DATE) AS meeting_date,
              'Hearing' AS meeting_type,'Exploring State Options in SNAP' AS title,false AS not_held,
              make_array(named_struct('system_code','hsag00','role','host')) AS committees,
              arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') AS subject_keys,
              array_slice(make_array(named_struct('name',cast(NULL AS VARCHAR),'url',cast(NULL AS VARCHAR),'video_key',cast(NULL AS VARCHAR))),1,0) AS videos
            UNION ALL SELECT 117410,'house',cast('2024-06-13' AS DATE),'Markup' AS meeting_type,'Markup' AS title,false,
              make_array(named_struct('system_code','hssy00','role','host')),
              arrow_cast(make_array('118-hr-8613','118-hr-8665'),'List(Utf8)'),
              array_slice(make_array(named_struct('name',cast(NULL AS VARCHAR),'url',cast(NULL AS VARCHAR),'video_key',cast(NULL AS VARCHAR))),1,0)
            UNION ALL SELECT 104357,'house',cast('2016-02-11' AS DATE),'Hearing','To consider the impacts of EPA actions on the rural economy',false,
              make_array(named_struct('system_code','hsag00','role','host')),
              arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'),
              array_slice(make_array(named_struct('name',cast(NULL AS VARCHAR),'url',cast(NULL AS VARCHAR),'video_key',cast(NULL AS VARCHAR))),1,0)
            UNION ALL SELECT 115900,'house',cast('2023-03-08' AS DATE),'Hearing','Clearing the Air: Science-Based Strategies to Protect Workers from COVID-19 Infections',false,
              make_array(named_struct('system_code','hsed00','role','host')),
              arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'),
              array_slice(make_array(named_struct('name',cast(NULL AS VARCHAR),'url',cast(NULL AS VARCHAR),'video_key',cast(NULL AS VARCHAR))),1,0))""", materialize=True),
        dict(name='meetings_export', sql="""SELECT event_id,chamber,meeting_type,title,
            array_slice(make_array(named_struct('source',cast(NULL AS VARCHAR),'package_id',cast(NULL AS VARCHAR),'list_row',cast(NULL AS INT),
             'video_key',cast(NULL AS VARCHAR),'language',cast(NULL AS VARCHAR),'production',cast(NULL AS VARCHAR))),1,0) AS transcripts
            FROM meetings_resolved""", materialize=True),
        dict(name='recording_video_links', sql="""SELECT repeat('11',32) AS page_body,'youtube:-Ii51ySKWUc' AS extracted_key
            UNION ALL SELECT repeat('22',32),'youtube:xv-3QApZs7o'
            UNION ALL SELECT repeat('33',32),'youtube:ezLNq2qeJxU'
            UNION ALL SELECT repeat('44',32),'youtube:e8tGWFo6s2c'
            UNION ALL SELECT repeat('55',32),'youtube:29FzR1Hadpk'""", materialize=True),
        dict(name='recording_video_pages', sql="SELECT DISTINCT page_body,arrow_cast(decode(page_body,'hex'),'FixedSizeBinary(32)') AS body_sha FROM recording_video_links", materialize=True),
        dict(name='capture_source_contexts', sql="""SELECT 's1' AS source_id,repeat('11',32) AS body_sha
            UNION ALL SELECT 's2',repeat('22',32)
            UNION ALL SELECT 's3',repeat('33',32)
            UNION ALL SELECT 's4',repeat('44',32)
            UNION ALL SELECT 's5',repeat('55',32)""", materialize=True),
        dict(name='source_addresses', sql="""SELECT 's1' AS source_id,'https://agriculture.house.gov/calendar/eventsingle.aspx?EventID=7972' AS url
            UNION ALL SELECT 's2','https://republicans-science.house.gov/markups?ID=409C'
            UNION ALL SELECT 's3','https://agriculture.house.gov/calendar/eventsingle.aspx?EventID=3123'
            UNION ALL SELECT 's4','https://edworkforce.house.gov/calendar/eventsingle.aspx?EventID=407227'
            UNION ALL SELECT 's5','https://democrats-veterans.house.gov/events/hearings/econ-06252026'""", materialize=True),
        dict(name='recording_page_sources', sql="SELECT DISTINCT c.source_id,c.body_sha AS page_body FROM recording_video_pages vp JOIN capture_source_contexts c ON c.body_sha=vp.page_body", materialize=True),
        dict(name='page_facts', sql="""SELECT arrow_cast(decode(repeat('11',32),'hex'),'FixedSizeBinary(32)') AS body_sha,'completed' AS status,
              'Exploring State Options in SNAP | House Agriculture Committee' AS title,'Exploring State Options in SNAP' AS heading,
              cast('2025-09-15' AS VARCHAR) AS content_date,'September 15, 2025' AS text_head,arrow_cast(NULL,'List(Int64)') AS named_meetings
            UNION ALL SELECT arrow_cast(decode(repeat('22',32),'hex'),'FixedSizeBinary(32)'),'completed',
              'Full Committee Markup of H.R. 8613 & H.R. 8665' AS title,'Full Committee Markup of H.R. 8613 & H.R. 8665' AS heading,
              '2024-06-13','June 13, 2024',arrow_cast(NULL,'List(Int64)')
            UNION ALL SELECT arrow_cast(decode(repeat('33',32),'hex'),'FixedSizeBinary(32)'),'completed',
              'Subcommittee on Livestock and Foreign Agriculture: Foot and Mouth Disease','Foot and Mouth Disease',
              '2016-02-11','February 11, 2016',arrow_cast(NULL,'List(Int64)')
            UNION ALL SELECT arrow_cast(decode(repeat('44',32),'hex'),'FixedSizeBinary(32)'),'completed',
              'Clearing the Air: Science-Based Strategies to Protect Workers from COVID-19 Infections','Clearing the Air',
              '2023-03-08','March 8, 2023',arrow_cast(NULL,'List(Int64)')
            UNION ALL SELECT arrow_cast(decode(repeat('55',32),'hex'),'FixedSizeBinary(32)'),'completed',
              'The House Committee on Veterans Affairs','Economic Opportunity Hearing',
              cast(NULL AS VARCHAR),'Date: 06.25.26',arrow_cast(NULL,'List(Int64)')""", materialize=True),
        dict(name='publisher_links', sql="SELECT cast(NULL AS VARCHAR) AS page_body,cast(NULL AS VARCHAR) AS source_id WHERE false", materialize=True),
        dict(name='document_members', sql="SELECT cast(NULL AS VARCHAR) AS source_id,cast(NULL AS BIGINT) AS component,cast(NULL AS VARCHAR) AS filename,cast(NULL AS VARCHAR) AS source_url WHERE false", materialize=True),
        dict(name='component_meeting_links', sql="SELECT cast(NULL AS BIGINT) AS component,arrow_cast(NULL,'List(Utf8)') AS meeting_keys WHERE false", materialize=True),
        dict(name='source_annotation_addresses', sql="SELECT cast(NULL AS VARCHAR) AS source_id,cast(NULL AS VARCHAR) AS meeting_key WHERE false", materialize=True),
        dict(name='senate_page_meeting_links', sql="SELECT cast(NULL AS VARCHAR) AS record_sha_hex,cast(NULL AS BIGINT) AS event_id,cast(NULL AS VARCHAR) AS banking_hearing_url WHERE false", materialize=True),
        dict(name='house_page_meeting_links', sql=sql('house-page-meeting-links'), materialize=True),
        dict(name='recording_page_meetings', sql="""SELECT page_body,event_id FROM house_page_meeting_links
            UNION SELECT vp.page_body,s.event_id FROM recording_video_pages vp JOIN senate_page_meeting_links s ON s.record_sha_hex=vp.page_body""", materialize=True),
        dict(name='recording_tracks', sql="""SELECT cast(NULL AS VARCHAR) AS video_key,
            array_slice(make_array(named_struct('body',arrow_cast(NULL,'FixedSizeBinary(32)'),'suffix',cast(NULL AS VARCHAR),
             'format',cast(NULL AS VARCHAR),'language',cast(NULL AS VARCHAR),'production',cast(NULL AS VARCHAR))),1,0) AS tracks WHERE false""", materialize=True),
        dict(name='recordings_entity', sql=sql('entity-recordings'), materialize=True),
        dict(name='recording_page_video_events', sql="""SELECT video_key,event_id,'committee_page:'||min(page_body) AS source_ref
            FROM (SELECT pvl.page_body,pvl.extracted_key AS video_key,pm.event_id
                  FROM recording_page_meetings pm JOIN recording_video_links pvl ON pvl.page_body=pm.page_body
                  WHERE pvl.extracted_key IS NOT NULL AND pm.event_id IS NOT NULL)
            GROUP BY video_key,event_id""", materialize=True),
        dict(name='videos_export', sql="""SELECT 'youtube:-Ii51ySKWUc' AS video_key,arrow_cast(decode(repeat('a1',32),'hex'),'FixedSizeBinary(32)') AS record_sha,
              arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)') AS stated_event_ids,false AS has_caption,
              cast(461 AS INT) AS duration_seconds,'Hearing Highlights | Exploring State Options in SNAP' AS title
            UNION ALL SELECT 'youtube:xv-3QApZs7o',arrow_cast(decode(repeat('a2',32),'hex'),'FixedSizeBinary(32)'),
              arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)'),false,cast(5911 AS INT),'Full Committee Markup of H.R. 8613'
            UNION ALL SELECT 'youtube:ezLNq2qeJxU',arrow_cast(decode(repeat('a3',32),'hex'),'FixedSizeBinary(32)'),
              arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)'),false,cast(6275 AS INT),'Foot and Mouth Disease'
            UNION ALL SELECT 'youtube:e8tGWFo6s2c',arrow_cast(decode(repeat('a4',32),'hex'),'FixedSizeBinary(32)'),
              arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)'),false,cast(241 AS INT),'Meeting to Approve New Subcommittee Assignments'
            UNION ALL SELECT 'youtube:29FzR1Hadpk',arrow_cast(decode(repeat('a5',32),'hex'),'FixedSizeBinary(32)'),
              arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)'),false,cast(0 AS INT),'Subcommittee Hearing 6.25.2026'""", materialize=True),
        dict(name='meeting_transcript_links', sql="SELECT cast(NULL AS VARCHAR) AS package_id,cast(NULL AS BIGINT) AS event_id WHERE false", materialize=True),
        dict(name='package_meeting_links', sql="SELECT cast(NULL AS VARCHAR) AS package_id,cast(NULL AS BIGINT) AS event_id WHERE false", materialize=True),
        dict(name='package_mods_facts', sql="SELECT cast(NULL AS VARCHAR) AS package_id,arrow_cast(NULL,'List(Int64)') AS named_meetings WHERE false", materialize=True),
        dict(name='meeting_document_urls', sql="SELECT cast(NULL AS BIGINT) AS event_id,cast(NULL AS VARCHAR) AS url WHERE false", materialize=True),
        dict(name='ordered', sql="SELECT arrow_cast(NULL,'List(Utf8)') AS meeting_keys WHERE false", materialize=True),
        dict(name='witnesses_export', sql="SELECT cast(NULL AS BIGINT) AS event_id,cast(NULL AS VARCHAR) AS name,cast(NULL AS VARCHAR) AS package_id,cast(NULL AS VARCHAR) AS witness_type,cast(NULL AS VARCHAR) AS superseded_by WHERE false", materialize=True),
        dict(name='selected_appearance_records', sql="SELECT cast(NULL AS BIGINT) AS event_id,cast(NULL AS VARCHAR) AS status,cast(NULL AS VARCHAR) AS collection_state,arrow_cast(NULL,'List(Utf8)') AS appearances WHERE false", materialize=True),
        dict(name='recording_matches_export', sql=sql('entity-recording-matches'), materialize=True),
        dict(name='recordings_export', sql=archive_model.recordings_export_sql(root=ROOT, explorer_inputs=True), materialize=True),
        dict(name='meeting_coverage_export', sql=sql('entity-meeting-coverage'), materialize=True),
    ]
    run_job(tmp_path / 'job', engine, inputs=inputs, steps=steps, outputs=[
        parquet_output(tmp_path, 'recordings', 'SELECT * FROM recordings_export', ['video_key']),
        parquet_output(tmp_path, 'meeting_coverage', 'SELECT * FROM meeting_coverage_export', ['event_id', 'aspect']),
    ], queries=[])
    rec = {r['video_key']: r for r in rows(tmp_path, 'recordings')}
    assert rec['youtube:-Ii51ySKWUc']['event_ids'] == [118500]
    assert rec['youtube:-Ii51ySKWUc']['recording_scope'] == 'excerpt'
    assert rec['youtube:xv-3QApZs7o']['event_ids'] == [117410]
    assert rec['youtube:xv-3QApZs7o']['recording_scope'] == 'full'
    assert rec['youtube:ezLNq2qeJxU']['event_ids'] == []
    assert rec['youtube:ezLNq2qeJxU']['recording_scope'] == 'full'
    assert rec['youtube:e8tGWFo6s2c']['event_ids'] == []
    assert rec['youtube:e8tGWFo6s2c']['recording_scope'] == 'full'
    assert rec['youtube:29FzR1Hadpk']['recording_scope'] == 'unknown'

    cov = {(r['event_id'], r['aspect']): (r['state'], r['reason']) for r in rows(tmp_path, 'meeting_coverage')}
    assert cov[118500, 'recording'] == ('partial', 'excerpts_only')
    assert cov[117410, 'recording'] == ('present', None)
    assert cov[104357, 'recording'] == ('unknown', None)
    assert cov[115900, 'recording'] == ('unknown', None)


