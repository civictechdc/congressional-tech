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
        dict(name='known_meetings', sql="SELECT event_id,meeting_type,title,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') AS subject_keys FROM meetings_export", materialize=True),
        dict(name='video_key_aliases', sql='SELECT cast(NULL AS VARCHAR) AS alias_key,cast(NULL AS VARCHAR) AS canonical_key WHERE false', materialize=True),
        dict(name='recording_page_video_events', sql="SELECT cast(NULL AS VARCHAR) AS video_key,cast(NULL AS BIGINT) AS event_id,cast(NULL AS VARCHAR) AS source_ref,cast(NULL AS VARCHAR) AS link_rule,cast(NULL AS VARCHAR) AS match_note WHERE false", materialize=True),
        *__import__('viewer_publication.archive_model', fromlist=['recording_match_prep_steps']).recording_match_prep_steps(videos_relation='videos_export', include_stopwords=True),
        dict(name='recording_matches_export', sql=sql('entity-recording-matches'), materialize=True),
        dict(name='ordered', sql="SELECT arrow_cast(make_array('1001'),'List(Utf8)') AS meeting_keys", materialize=True),
        # 1001 shows Jane once: the print's Jane is superseded by the meeting's own row, and a letter for the
        # record is a statement, not a witness. 1012 lists only a sitting Member, 1013 a Member and an outside
        # witness, 1014 only the Member introducing a nominee it leaves out, 1015 a Member and record material (ct-kw85).
        # A linked print's rows tied to no meeting: 1016's names only a Senator (as Bennet's for 337704), 1017's two
        # Representatives (as Smith's and Walz's for 104324), 1018's a Member and an outside witness, and 1019's only the
        # Senator introducing a nominee.
        dict(name='witnesses_export', sql="""SELECT *,'listed' AS listing_status FROM (SELECT cast(1001 AS BIGINT) AS event_id,'Jane' AS name,cast(NULL AS VARCHAR) AS package_id,
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
            UNION ALL SELECT cast(NULL AS BIGINT) AS event_id,'Senator Kay Introducer' AS name,'CHRG-introducer-only' AS package_id,'member_appearance' AS witness_type,cast(NULL AS VARCHAR) AS superseded_by)""", materialize=True),
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
        dict(name='known_meetings', sql="SELECT event_id,cast('Hearing' AS VARCHAR) AS meeting_type,cast('Hearing' AS VARCHAR) AS title,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') AS subject_keys FROM meetings_resolved", materialize=True),
        dict(name='video_key_aliases', sql="SELECT cast(NULL AS VARCHAR) AS alias_key,cast(NULL AS VARCHAR) AS canonical_key WHERE false", materialize=True),
        dict(name='meeting_transcript_links', sql="SELECT 'CHRG-pkg' AS package_id,cast(1004 AS BIGINT) AS event_id", materialize=True),
        dict(name='package_meeting_links', sql="SELECT 'CHRG-pkg' AS package_id,cast(1004 AS BIGINT) AS event_id", materialize=True),
        dict(name='recording_video_links', sql="""SELECT 'aa' AS page_body,'youtube:0YtytQuMCT8' AS extracted_key
            UNION ALL SELECT 'bb','youtube:pageVid0004'
            UNION ALL SELECT 'cc','youtube:unmatched99'""", materialize=True),
        dict(name='recording_page_meetings', sql="SELECT 'bb' AS page_body,cast(1004 AS BIGINT) AS event_id,cast(0 AS INT) AS route_priority,cast('page_named_meeting' AS VARCHAR) AS link_rule,cast('page_named_meeting' AS VARCHAR) AS match_note", materialize=True),
        dict(name='recording_tracks', sql="""SELECT cast(NULL AS VARCHAR) AS video_key,
            array_slice(make_array(named_struct('body',arrow_cast(NULL,'FixedSizeBinary(32)'),'suffix',cast(NULL AS VARCHAR),
             'format',cast(NULL AS VARCHAR),'language',cast(NULL AS VARCHAR),'production',cast(NULL AS VARCHAR))),1,0) AS tracks WHERE false""", materialize=True),
        dict(name='recordings_entity', sql=sql('entity-recordings'), materialize=True),
        dict(name='recording_page_video_events', sql=archive_model.RECORDING_PAGE_VIDEO_EVENTS_SQL, materialize=True),
        dict(name='videos_export', sql="""SELECT 'youtube:0YtytQuMCT8' AS video_key,
            arrow_cast(decode(repeat('ab',32),'hex'),'FixedSizeBinary(32)') AS record_sha,
            arrow_cast(make_array(cast(119546 AS BIGINT)),'List(Int64)') AS stated_event_ids,false AS has_caption,
            cast(5400 AS INT) AS duration_seconds,cast('Hearing' AS VARCHAR) AS title""", materialize=True),
        *archive_model.recording_match_prep_steps(videos_relation='videos_export', include_stopwords=True),
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
              array_slice(make_array(named_struct('name',cast(NULL AS VARCHAR),'url',cast(NULL AS VARCHAR),'video_key',cast(NULL AS VARCHAR))),1,0)
            -- ct-mwod: two generically titled markups, matched only by "one page on that date".
            UNION ALL SELECT 117471,'house',cast('2024-07-10' AS DATE),'Markup','Markup',false,
              make_array(named_struct('system_code','hssy00','role','host')),arrow_cast(make_array('118-hr-8958'),'List(Utf8)'),
              array_slice(make_array(named_struct('name',cast(NULL AS VARCHAR),'url',cast(NULL AS VARCHAR),'video_key',cast(NULL AS VARCHAR))),1,0)
            UNION ALL SELECT 117999,'house',cast('2024-08-01' AS DATE),'Markup','Markup',false,
              make_array(named_struct('system_code','hssy00','role','host')),arrow_cast(make_array('118-hr-9999'),'List(Utf8)'),
              array_slice(make_array(named_struct('name',cast(NULL AS VARCHAR),'url',cast(NULL AS VARCHAR),'video_key',cast(NULL AS VARCHAR))),1,0)
            UNION ALL SELECT 118111,'house',cast('2024-09-05' AS DATE),'Markup','Markup',false,
              make_array(named_struct('system_code','hssy00','role','host')),arrow_cast(make_array('118-hr-7777'),'List(Utf8)'),
              array_slice(make_array(named_struct('name',cast(NULL AS VARCHAR),'url',cast(NULL AS VARCHAR),'video_key',cast(NULL AS VARCHAR))),1,0))""", materialize=True),
        dict(name='meetings_export', sql="""SELECT event_id,chamber,meeting_type,title,
            array_slice(make_array(named_struct('source',cast(NULL AS VARCHAR),'package_id',cast(NULL AS VARCHAR),'list_row',cast(NULL AS INT),
             'video_key',cast(NULL AS VARCHAR),'language',cast(NULL AS VARCHAR),'production',cast(NULL AS VARCHAR))),1,0) AS transcripts
            FROM meetings_resolved""", materialize=True),
        dict(name='known_meetings', sql="SELECT event_id,meeting_type,title,subject_keys FROM meetings_resolved", materialize=True),
        dict(name='video_key_aliases', sql="SELECT cast(NULL AS VARCHAR) AS alias_key,cast(NULL AS VARCHAR) AS canonical_key WHERE false", materialize=True),
        dict(name='recording_video_links', sql="""SELECT repeat('11',32) AS page_body,'youtube:-Ii51ySKWUc' AS extracted_key
            UNION ALL SELECT repeat('22',32),'youtube:xv-3QApZs7o'
            UNION ALL SELECT repeat('33',32),'youtube:ezLNq2qeJxU'
            UNION ALL SELECT repeat('44',32),'youtube:e8tGWFo6s2c'
            UNION ALL SELECT repeat('55',32),'youtube:29FzR1Hadpk'
            UNION ALL SELECT repeat('66',32),'youtube:SBp0UXikw8w'
            UNION ALL SELECT repeat('77',32),'youtube:SBp0UXikw8w'
            UNION ALL SELECT repeat('88',32),'youtube:markupAAAAA'
            UNION ALL SELECT repeat('99',32),'youtube:statementBB'
            UNION ALL SELECT repeat('aa',32),'youtube:majorityCCC'
            UNION ALL SELECT repeat('bb',32),'youtube:minorityCCC'""", materialize=True),
        dict(name='recording_video_pages', sql="SELECT DISTINCT page_body,arrow_cast(decode(page_body,'hex'),'FixedSizeBinary(32)') AS body_sha FROM recording_video_links", materialize=True),
        dict(name='capture_source_contexts', sql="""SELECT 's1' AS source_id,repeat('11',32) AS body_sha
            UNION ALL SELECT 's2',repeat('22',32)
            UNION ALL SELECT 's3',repeat('33',32)
            UNION ALL SELECT 's4',repeat('44',32)
            UNION ALL SELECT 's5',repeat('55',32)
            UNION ALL SELECT 's6',repeat('66',32)
            UNION ALL SELECT 's7',repeat('77',32)
            UNION ALL SELECT 's8',repeat('88',32)
            UNION ALL SELECT 's9',repeat('99',32)
            UNION ALL SELECT 'sa',repeat('aa',32)
            UNION ALL SELECT 'sb',repeat('bb',32)""", materialize=True),
        dict(name='source_addresses', sql="""SELECT 's1' AS source_id,'https://agriculture.house.gov/calendar/eventsingle.aspx?EventID=7972' AS url
            UNION ALL SELECT 's2','https://republicans-science.house.gov/markups?ID=409C'
            UNION ALL SELECT 's3','https://agriculture.house.gov/calendar/eventsingle.aspx?EventID=3123'
            UNION ALL SELECT 's4','https://edworkforce.house.gov/calendar/eventsingle.aspx?EventID=407227'
            UNION ALL SELECT 's5','https://democrats-veterans.house.gov/events/hearings/econ-06252026'
            -- One page saved from its party host and again from the committee's bare host, with new bytes.
            UNION ALL SELECT 's6','https://republicans-science.house.gov/markups?ID=F6543C82'
            UNION ALL SELECT 's7','https://science.house.gov/markups?ID=F6543C82'
            -- Two different pages on one date: neither is provably the proceeding.
            UNION ALL SELECT 's8','https://republicans-science.house.gov/markups?ID=AAAA'
            UNION ALL SELECT 's9','https://republicans-science.house.gov/opening-statements?ID=BBBB'
            -- The two party sites are different publishers, even with one path and query.
            UNION ALL SELECT 'sa','https://republicans-science.house.gov/markups?ID=CCCC'
            UNION ALL SELECT 'sb','https://democrats-science.house.gov/markups?ID=CCCC'""", materialize=True),
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
              cast(NULL AS VARCHAR),'Date: 06.25.26',arrow_cast(NULL,'List(Int64)')
            UNION ALL SELECT arrow_cast(decode(repeat('66',32),'hex'),'FixedSizeBinary(32)'),'completed',
              'Full Committee Markup of the NASA Reauthorization Act of 2024','Full Committee Markup of the NASA Reauthorization Act of 2024',
              '2024-07-10','July 10, 2024',arrow_cast(NULL,'List(Int64)')
            UNION ALL SELECT arrow_cast(decode(repeat('77',32),'hex'),'FixedSizeBinary(32)'),'completed',
              'Full Committee Markup of the NASA Reauthorization Act of 2024','Full Committee Markup of the NASA Reauthorization Act of 2024',
              '2024-07-10','July 10, 2024',arrow_cast(NULL,'List(Int64)')
            UNION ALL SELECT arrow_cast(decode(repeat('88',32),'hex'),'FixedSizeBinary(32)'),'completed',
              'Full Committee Markup of the Weather Act','Full Committee Markup of the Weather Act',
              '2024-08-01','August 1, 2024',arrow_cast(NULL,'List(Int64)')
            UNION ALL SELECT arrow_cast(decode(repeat('99',32),'hex'),'FixedSizeBinary(32)'),'completed',
              'Opening Statement at the Markup of the Weather Act','Opening Statement at the Markup of the Weather Act',
              '2024-08-01','August 1, 2024',arrow_cast(NULL,'List(Int64)')
            UNION ALL SELECT arrow_cast(decode(repeat('aa',32),'hex'),'FixedSizeBinary(32)'),'completed',
              'Full Committee Markup of the Fusion Act','Full Committee Markup of the Fusion Act',
              '2024-09-05','September 5, 2024',arrow_cast(NULL,'List(Int64)')
            UNION ALL SELECT arrow_cast(decode(repeat('bb',32),'hex'),'FixedSizeBinary(32)'),'completed',
              'Full Committee Markup of the Fusion Act','Full Committee Markup of the Fusion Act',
              '2024-09-05','September 5, 2024',arrow_cast(NULL,'List(Int64)')""", materialize=True),
        dict(name='publisher_links', sql="SELECT cast(NULL AS VARCHAR) AS page_body,cast(NULL AS VARCHAR) AS source_id WHERE false", materialize=True),
        dict(name='document_members', sql="SELECT cast(NULL AS VARCHAR) AS source_id,cast(NULL AS BIGINT) AS component,cast(NULL AS VARCHAR) AS filename,cast(NULL AS VARCHAR) AS source_url WHERE false", materialize=True),
        dict(name='component_meeting_links', sql="SELECT cast(NULL AS BIGINT) AS component,arrow_cast(NULL,'List(Utf8)') AS meeting_keys WHERE false", materialize=True),
        dict(name='source_annotation_addresses', sql="SELECT cast(NULL AS VARCHAR) AS source_id,cast(NULL AS VARCHAR) AS meeting_key WHERE false", materialize=True),
        dict(name='senate_page_meeting_links', sql="SELECT cast(NULL AS VARCHAR) AS record_sha_hex,cast(NULL AS BIGINT) AS event_id,cast(NULL AS VARCHAR) AS banking_hearing_url WHERE false", materialize=True),
        dict(name='recording_match_stopwords', sql=archive_model.RECORDING_MATCH_STOPWORDS_SQL, materialize=True),
        dict(name='recording_page_event_links', sql=archive_model.EMPTY_RECORDING_PAGE_EVENT_LINKS_SQL, materialize=True),
        dict(name='house_page_meeting_links', sql=sql('house-page-meeting-links'), materialize=True),
        dict(name='recording_page_meetings', sql=archive_model.RECORDING_PAGE_MEETINGS_SQL, materialize=True),
        dict(name='recording_tracks', sql="""SELECT cast(NULL AS VARCHAR) AS video_key,
            array_slice(make_array(named_struct('body',arrow_cast(NULL,'FixedSizeBinary(32)'),'suffix',cast(NULL AS VARCHAR),
             'format',cast(NULL AS VARCHAR),'language',cast(NULL AS VARCHAR),'production',cast(NULL AS VARCHAR))),1,0) AS tracks WHERE false""", materialize=True),
        dict(name='recordings_entity', sql=sql('entity-recordings'), materialize=True),
        dict(name='recording_page_video_events', sql=archive_model.RECORDING_PAGE_VIDEO_EVENTS_SQL, materialize=True),
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
              arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)'),false,cast(0 AS INT),'Subcommittee Hearing 6.25.2026'
            UNION ALL SELECT 'youtube:SBp0UXikw8w',arrow_cast(decode(repeat('a6',32),'hex'),'FixedSizeBinary(32)'),
              arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)'),false,cast(9000 AS INT),'Full Committee Markup of the NASA Reauthorization Act'
            UNION ALL SELECT 'youtube:markupAAAAA',arrow_cast(decode(repeat('a8',32),'hex'),'FixedSizeBinary(32)'),
              arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)'),false,cast(7000 AS INT),'Full Committee Markup of the Weather Act'
            UNION ALL SELECT 'youtube:statementBB',arrow_cast(decode(repeat('a9',32),'hex'),'FixedSizeBinary(32)'),
              arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)'),false,cast(300 AS INT),'Opening Statement'
            UNION ALL SELECT 'youtube:majorityCCC',arrow_cast(decode(repeat('b1',32),'hex'),'FixedSizeBinary(32)'),
              arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)'),false,cast(7000 AS INT),'Full Committee Markup of the Fusion Act'
            UNION ALL SELECT 'youtube:minorityCCC',arrow_cast(decode(repeat('b2',32),'hex'),'FixedSizeBinary(32)'),
              arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)'),false,cast(7000 AS INT),'Full Committee Markup of the Fusion Act'""", materialize=True),
        dict(name='meeting_transcript_links', sql="SELECT cast(NULL AS VARCHAR) AS package_id,cast(NULL AS BIGINT) AS event_id WHERE false", materialize=True),
        dict(name='package_meeting_links', sql="SELECT cast(NULL AS VARCHAR) AS package_id,cast(NULL AS BIGINT) AS event_id WHERE false", materialize=True),
        dict(name='package_mods_facts', sql="SELECT cast(NULL AS VARCHAR) AS package_id,arrow_cast(NULL,'List(Int64)') AS named_meetings WHERE false", materialize=True),
        dict(name='meeting_document_urls', sql="SELECT cast(NULL AS BIGINT) AS event_id,cast(NULL AS VARCHAR) AS url WHERE false", materialize=True),
        dict(name='ordered', sql="SELECT arrow_cast(NULL,'List(Utf8)') AS meeting_keys WHERE false", materialize=True),
        dict(name='witnesses_export', sql="SELECT cast(NULL AS BIGINT) AS event_id,cast(NULL AS VARCHAR) AS name,cast(NULL AS VARCHAR) AS package_id,cast(NULL AS VARCHAR) AS witness_type,cast(NULL AS VARCHAR) AS superseded_by,cast(NULL AS VARCHAR) AS listing_status WHERE false", materialize=True),
        dict(name='selected_appearance_records', sql="SELECT cast(NULL AS BIGINT) AS event_id,cast(NULL AS VARCHAR) AS status,cast(NULL AS VARCHAR) AS collection_state,arrow_cast(NULL,'List(Utf8)') AS appearances WHERE false", materialize=True),
        *archive_model.recording_match_prep_steps(videos_relation='videos_export'),
        dict(name='recording_matches_export', sql=sql('entity-recording-matches'), materialize=True),
        dict(name='recordings_export', sql=archive_model.recordings_export_sql(root=ROOT, explorer_inputs=True), materialize=True),
        dict(name='meeting_coverage_export', sql=sql('entity-meeting-coverage'), materialize=True),
    ]
    run_job(tmp_path / 'job', engine, inputs=inputs, steps=steps, outputs=[
        parquet_output(tmp_path, 'recordings', 'SELECT * FROM recordings_export', ['video_key']),
        parquet_output(tmp_path, 'meeting_coverage', 'SELECT * FROM meeting_coverage_export', ['event_id', 'aspect']),
        parquet_output(tmp_path, 'recording_matches', 'SELECT * FROM recording_matches_export', ['match_id']),
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
    # ct-mwod: one page under two host aliases is still one page on its date; two pages are not.
    assert rec['youtube:SBp0UXikw8w']['event_ids'] == [117471]
    assert rec['youtube:markupAAAAA']['event_ids'] == [] and rec['youtube:statementBB']['event_ids'] == []
    assert rec['youtube:majorityCCC']['event_ids'] == [] and rec['youtube:minorityCCC']['event_ids'] == []
    # Both saved copies win the meeting; they are one match, cited to the lower body with rule provenance.
    assert [(m['event_id'], m['basis'], m['source_ref'], m['note']) for m in rows(tmp_path, 'recording_matches')
            if m['video_key'] == 'youtube:SBp0UXikw8w'] == [(117471, 'committee_page', 'committee_page:' + '66' * 32, 'house_single_day_generic')]
    assert [(m['event_id'], m['basis'], m['note']) for m in rows(tmp_path, 'recording_matches')
            if m['video_key'] == 'youtube:-Ii51ySKWUc'] == [(118500, 'committee_page', 'house_title_words: exploring, options, snap, state')]

    cov = {(r['event_id'], r['aspect']): (r['state'], r['reason']) for r in rows(tmp_path, 'meeting_coverage')}
    assert cov[118500, 'recording'] == ('partial', 'excerpts_only')
    assert cov[117410, 'recording'] == ('present', None)
    assert cov[104357, 'recording'] == ('unknown', None)
    assert cov[115900, 'recording'] == ('unknown', None)


def test_meetings_transcripts_and_video_aliases_follow_recordings_export_and_ignore_crpt_docs(tmp_path):
    """P1-1 & P2-5b (ct-yizl, ct-ywz2):
    1. Vetoed markup video on a non-markup hearing page with a VTT track is excluded from meetings.transcripts.
    2. video_states_event_id / curated video with a VTT track is included in meetings.transcripts.
    3. video_key_aliases canonicalizes recording_video_links and publisher_rows so alias keys never split rows.
    4. A CRPT-... committee report link on a House hearing page does not override dated_winners."""
    from viewer_publication import archive_model
    from viewer_publication.meeting_detail_observations import EMPTY_OBSERVATIONS

    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    vtt_body = "arrow_cast(decode('" + ('11' * 32) + "','hex'),'FixedSizeBinary(32)')"
    inputs = [
        json_input(tmp_path, 'active_recording_decisions', [
            decision('c' * 64, 'event', '2002', 'found', ['curatedCapt']),
        ], id='Utf8', subject_kind='Utf8', subject_id='Utf8', verdict='Utf8', video_refs=_list(),
           note='Utf8', disputed_by='Utf8', decided_at='Utf8', supersedes='Utf8'),
        json_input(tmp_path, 'recording_sources',
                   json.loads((ROOT / 'model/registries/recording-sources.json').read_text()),
                   id='Utf8', kind='Utf8', pattern='Utf8', key_template='Utf8',
                   format='Utf8', default_language='Utf8', default_production='Utf8'),
        json_input(tmp_path, 'spicy_committees', [
            dict(system_code='hsag00', parent_system_code=None, website_url='https://agriculture.house.gov/'),
        ], system_code='Utf8', parent_system_code='Utf8', website_url='Utf8'),
    ]
    steps = [
        dict(name='recording_url_sources', sql="SELECT id,pattern,key_template,format,default_language,default_production FROM recording_sources WHERE kind='video_url'", materialize=True),
        # 2001: non-markup hearing whose page embeds a markup video (vetoed)
        # 2002: hearing with curatedCapt VTT track
        # 2003: hearing claimed via stated_event_ids on statedCapt VTT track
        # 2004: defines canonical explicit key 'senate:commerce:canon' for youtube.com/watch?v=aliasVid001
        # 2005: references youtube.com/watch?v=aliasVid001 without explicit_key, plus page link to same URL
        # 2006 & 2007: same-day House Agriculture hearings; page links to CRPT-119hrpt1.pdf on 2007 (must NOT win over title match to 2006)
        dict(name='meetings_resolved', sql="""SELECT cast(event_id AS BIGINT) AS event_id,chamber,cast(119 AS INT) AS congress,cast(1 AS INT) AS session,
              cast(title AS VARCHAR) AS title,cast(day AS DATE) AS meeting_date,'Hearing' AS meeting_type,'Scheduled' AS status,
              false AS not_held,title_key,false AS reschedule_candidate,committee_key,
              make_array(named_struct('system_code',committee_key,'role','host')) AS committees,
              array_slice(make_array(named_struct('start',arrow_cast(NULL,'Timestamp(Microsecond, Some("UTC"))'),'end',arrow_cast(NULL,'Timestamp(Microsecond, Some("UTC"))'),'place',cast(NULL AS VARCHAR),'room',cast(NULL AS VARCHAR),'building',cast(NULL AS VARCHAR),'address',cast(NULL AS VARCHAR))),1,0) AS sittings,
              arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') AS subject_keys,
              arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)') AS transcript_jackets,
              CASE WHEN vid_url IS NOT NULL THEN make_array(named_struct('name','Stream','url',vid_url,'video_key',vid_key))
                   ELSE array_slice(make_array(named_struct('name',cast(NULL AS VARCHAR),'url',cast(NULL AS VARCHAR),'video_key',cast(NULL AS VARCHAR))),1,0) END AS videos,
              arrow_cast(NULL,'Timestamp(Microsecond, Some("UTC"))') AS congress_gov_updated,cast(NULL AS VARCHAR) AS house_xml_updated,
              'Hearing' AS congress_gov_meeting_type,'open' AS access,'inferred_open' AS access_basis,
              array_slice(make_array(named_struct('url',cast(NULL AS VARCHAR))),1,0) AS document_references,
              array_slice(make_array(named_struct('subject_key',cast(NULL AS VARCHAR),'last_listed_on',cast(NULL AS DATE),'unlisted_since',cast(NULL AS DATE),'unlisted_by_record_sha',cast(NULL AS VARCHAR))),1,0) AS unlisted_subjects
            FROM (VALUES
              (2001,'house','Oversight of Farm Credit','2025-05-10','oversight farm credit','hsag00',cast(NULL AS VARCHAR),cast(NULL AS VARCHAR)),
              (2002,'house','Clean Water Hearing','2025-05-11','clean water','hsag00',NULL,NULL),
              (2003,'house','Rural Broadband Hearing','2025-05-12','rural broadband','hsag00',NULL,NULL),
              (2004,'senate','Commerce Hearing A','2025-05-13','commerce a','sscm00','https://www.youtube.com/watch?v=aliasVid001','senate:commerce:canon'),
              (2005,'senate','Commerce Hearing B','2025-05-14','commerce b','sscm00','https://www.youtube.com/watch?v=aliasVid001','youtube:aliasVid001'),
              (2006,'house','Crop Insurance Modernization','2025-05-15','crop insurance','hsag00',NULL,NULL),
              (2007,'house','Forestry Management Review','2025-05-15','forestry management','hsag00',NULL,NULL)
            ) AS t(event_id,chamber,title,day,title_key,committee_key,vid_url,vid_key)""", materialize=True),
        dict(name='ordered', sql="SELECT arrow_cast(NULL,'List(Utf8)') AS meeting_keys,arrow_cast(NULL,'List(Utf8)') AS measure_keys,cast(NULL AS VARCHAR) AS filename,cast(NULL AS VARCHAR) AS format,cast(NULL AS INT) AS list_row,arrow_cast(NULL,'List(Utf8)') AS chambers,arrow_cast(NULL,'List(Utf8)') AS committee_keys,cast(NULL AS SMALLINT) AS congress,cast(NULL AS DATE) AS document_date,cast(NULL AS VARCHAR) AS document_date_status,false AS hidden WHERE false", materialize=True),
        dict(name='known_meetings', sql="SELECT event_id,meeting_type,title,subject_keys FROM meetings_resolved", materialize=True),
        dict(name='video_key_aliases', sql="""WITH raw_meeting_videos AS (
            SELECT m.event_id,m.video_url AS url,m.explicit_key,
                min(regexp_replace((regexp_match(m.video_url,rs.pattern))[1],'^(.+)$',rs.key_template)) AS extracted_key
            FROM (SELECT event_id,v['url'] AS video_url,nullif(trim(v['video_key']),'') AS explicit_key
                  FROM (SELECT event_id,unnest(videos) AS v FROM meetings_resolved WHERE videos IS NOT NULL)) m
            LEFT JOIN recording_url_sources rs ON m.video_url IS NOT NULL AND regexp_like(m.video_url,rs.pattern)
            GROUP BY m.event_id,m.video_url,m.explicit_key
        )
        SELECT extracted_key AS alias_key,min(explicit_key) AS canonical_key
        FROM raw_meeting_videos
        WHERE extracted_key IS NOT NULL AND explicit_key IS NOT NULL AND extracted_key<>explicit_key
        GROUP BY extracted_key""", materialize=True),
        dict(name='recording_link_candidates', sql="""SELECT repeat('aa',32) AS page_body,'https://www.youtube.com/watch?v=vetoMarkup1' AS target_url
            UNION ALL SELECT repeat('bb',32),'https://www.youtube.com/watch?v=aliasVid001'
            UNION ALL SELECT repeat('cc',32),'https://www.youtube.com/watch?v=cropVid0006'""", materialize=True),
        dict(name='recording_video_links', sql="""SELECT DISTINCT raw.page_body,coalesce(a.canonical_key,raw.extracted_key) AS extracted_key
            FROM video_key_aliases a RIGHT JOIN (
                SELECT l.page_body,regexp_replace((regexp_match(l.target_url,rs.pattern))[1],'^(.+)$',rs.key_template) AS extracted_key
                FROM recording_url_sources rs JOIN recording_link_candidates l ON regexp_like(l.target_url,rs.pattern)
            ) raw ON a.alias_key=raw.extracted_key""", materialize=True),
        dict(name='recording_video_pages', sql="""SELECT DISTINCT page_body,arrow_cast(decode(page_body,'hex'),'FixedSizeBinary(32)') AS body_sha FROM recording_video_links""", materialize=True),
        dict(name='recording_page_sources', sql=f"SELECT 'src_cc' AS source_id,repeat('cc',32) AS page_body", materialize=True),
        dict(name='source_addresses', sql="SELECT 'src_cc' AS source_id,'https://agriculture.house.gov/calendar/eventsingle.aspx?EventID=99' AS url", materialize=True),
        dict(name='page_facts', sql="""SELECT arrow_cast(decode(repeat('cc',32),'hex'),'FixedSizeBinary(32)') AS body_sha,'completed' AS status,
            'Crop Insurance Modernization' AS title,'Crop Insurance Modernization' AS heading,'2025-05-15' AS content_date,'May 15, 2025' AS text_head,arrow_cast(NULL,'List(Int64)') AS named_meetings""", materialize=True),
        # Page cc links to CRPT-119hrpt1.pdf attached to 2007: must NOT hijack page cc from 2006 to 2007!
        dict(name='publisher_links', sql="SELECT repeat('cc',32) AS page_body,'doc_crpt' AS source_id", materialize=True),
        dict(name='document_members', sql="SELECT 'doc_crpt' AS source_id,cast(77 AS BIGINT) AS component,'CRPT-119hrpt1.pdf' AS filename,'https://www.govinfo.gov/content/pkg/CRPT-119hrpt1/pdf/CRPT-119hrpt1.pdf' AS source_url", materialize=True),
        dict(name='component_meeting_links', sql="SELECT cast(77 AS BIGINT) AS component,make_array('2007') AS meeting_keys", materialize=True),
        dict(name='recording_match_stopwords', sql=archive_model.RECORDING_MATCH_STOPWORDS_SQL, materialize=True),
        dict(name='recording_page_event_links', sql=archive_model.EMPTY_RECORDING_PAGE_EVENT_LINKS_SQL, materialize=True),
        dict(name='house_page_meeting_links', sql=sql('house-page-meeting-links'), materialize=True),
        dict(name='recording_page_meetings', sql="""SELECT repeat('aa',32) AS page_body,cast(2001 AS BIGINT) AS event_id,cast(0 AS INT) AS route_priority,cast('page_named_meeting' AS VARCHAR) AS link_rule,cast('page_named_meeting' AS VARCHAR) AS match_note
            UNION ALL SELECT repeat('bb',32),2005,cast(0 AS INT),cast('page_named_meeting' AS VARCHAR),cast('page_named_meeting' AS VARCHAR)
            UNION ALL SELECT page_body,event_id,cast(4 AS INT),link_rule,match_note FROM house_page_meeting_links""", materialize=True),
        dict(name='recording_tracks', sql=f"""SELECT 'youtube:vetoMarkup1' AS video_key,make_array(named_struct('body',{vtt_body},'suffix','.gz','format','vtt','language','en','production','asr')) AS tracks
            UNION ALL SELECT 'youtube:curatedCapt',make_array(named_struct('body',{vtt_body},'suffix','.gz','format','vtt','language','en','production','asr'))
            UNION ALL SELECT 'youtube:statedCapt1',make_array(named_struct('body',{vtt_body},'suffix','.gz','format','vtt','language','en','production','asr'))
            UNION ALL SELECT 'senate:commerce:canon',make_array(named_struct('body',{vtt_body},'suffix','.gz','format','vtt','language','en','production','asr'))""", materialize=True),
        dict(name='recordings_entity', sql=sql('entity-recordings'), materialize=True),
        dict(name='recording_page_video_events', sql=archive_model.RECORDING_PAGE_VIDEO_EVENTS_SQL, materialize=True),
        dict(name='videos_export', sql="""SELECT 'youtube:vetoMarkup1' AS video_key,arrow_cast(decode(repeat('b1',32),'hex'),'FixedSizeBinary(32)') AS record_sha,
              arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)') AS stated_event_ids,true AS has_caption,cast(3600 AS INT) AS duration_seconds,'Full Committee Markup of H.R. 1' AS title
            UNION ALL SELECT 'youtube:curatedCapt',arrow_cast(decode(repeat('b2',32),'hex'),'FixedSizeBinary(32)'),arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)'),true,3600,'Clean Water Hearing'
            UNION ALL SELECT 'youtube:statedCapt1',arrow_cast(decode(repeat('b3',32),'hex'),'FixedSizeBinary(32)'),arrow_cast(make_array(cast(2003 AS BIGINT)),'List(Int64)'),true,3600,'Rural Broadband Hearing'
            UNION ALL SELECT 'youtube:cropVid0006',arrow_cast(decode(repeat('b4',32),'hex'),'FixedSizeBinary(32)'),arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)'),false,3600,'Crop Insurance Modernization'""", materialize=True),
        dict(name='meeting_transcript_links', sql="SELECT cast(NULL AS VARCHAR) AS package_id,cast(NULL AS BIGINT) AS event_id WHERE false", materialize=True),
        dict(name='package_meeting_links', sql="SELECT cast(NULL AS VARCHAR) AS package_id,cast(NULL AS BIGINT) AS event_id WHERE false", materialize=True),
        dict(name='package_mods_facts', sql="SELECT cast(NULL AS VARCHAR) AS package_id WHERE false", materialize=True),
        dict(name='details', sql="SELECT cast(NULL AS VARCHAR) AS package_id,cast(NULL AS INT) AS list_row,cast(NULL AS VARCHAR) AS format,array_slice(make_array(named_struct('format',cast(NULL AS VARCHAR))),1,0) AS alternates,arrow_cast(NULL,'FixedSizeBinary(8)') AS link_key WHERE false", materialize=True),
        dict(name='formats', sql="SELECT 'preference' AS kind,'pdf' AS value,cast(1 AS INT) AS rank", materialize=True),
        dict(name='meeting_document_urls', sql="SELECT cast(NULL AS BIGINT) AS event_id,cast(NULL AS VARCHAR) AS url WHERE false", materialize=True),
        dict(name='appearance_records_resolved', sql="SELECT cast(NULL AS BIGINT) AS event_id,cast(NULL AS VARCHAR) AS name,cast(NULL AS VARCHAR) AS source,cast(NULL AS VARCHAR) AS listing_status WHERE false", materialize=True),
        dict(name='spicy_nominations', sql="SELECT cast(NULL AS INT) AS congress,cast(NULL AS VARCHAR) AS number,cast(NULL AS VARCHAR) AS part_number,cast(NULL AS VARCHAR) AS hearings_json WHERE false", materialize=True),
        dict(name='meeting_detail_observations', sql=EMPTY_OBSERVATIONS, materialize=True),
        dict(name='meeting_records_observed', sql="SELECT cast(NULL AS BIGINT) AS event_id,cast(NULL AS VARCHAR) AS source,cast(NULL AS VARCHAR) AS status,cast(NULL AS DATE) AS meeting_date,cast(NULL AS VARCHAR) AS record_sha_hex,arrow_cast(NULL,'Timestamp(Microsecond, Some(\"UTC\"))') AS retrieved_at WHERE false", materialize=True),
        dict(name='meeting_records_current', sql="SELECT *,cast(1 AS INT) AS priority,cast(NULL AS VARCHAR) AS title FROM meeting_records_observed WHERE false", materialize=True),
        dict(name='meeting_status_conflicts', sql="SELECT cast(NULL AS BIGINT) AS event_id,cast(NULL AS VARCHAR) AS held_date,cast(NULL AS VARCHAR) AS evidence WHERE false", materialize=True),
        *archive_model.recording_match_prep_steps(videos_relation='videos_export'),
        dict(name='recording_matches_export', sql=sql('entity-recording-matches'), materialize=True),
        dict(name='recordings_export', sql=archive_model.recordings_export_sql(root=ROOT, explorer_inputs=True), materialize=True),
        dict(name='retained_caption_tracks', sql="SELECT cast(NULL AS VARCHAR) AS video_key,arrow_cast(NULL,'FixedSizeBinary(32)') AS track_body WHERE false", materialize=True),
        dict(name='meetings_final', sql=sql('entity-meetings'), materialize=True),
    ]
    run_job(tmp_path / 'job', engine, inputs=inputs, steps=steps, outputs=[
        parquet_output(tmp_path, 'recordings', 'SELECT * FROM recordings_export', ['video_key']),
        parquet_output(tmp_path, 'recording_matches', 'SELECT * FROM recording_matches_export', ['match_id']),
        parquet_output(tmp_path, 'meetings', 'SELECT * FROM meetings_final', ['event_id']),
    ], queries=[])
    rec = {r['video_key']: r for r in rows(tmp_path, 'recordings')}
    mtgs = {r['event_id']: r for r in rows(tmp_path, 'meetings')}

    # 1. Vetoed markup video on 2001 excluded from both recordings.event_ids and meetings.transcripts:
    assert rec['youtube:vetoMarkup1']['event_ids'] == []
    assert mtgs[2001]['transcripts'] == []
    # 2. Curated (2002) and video_states_event_id (2003) captions included in meetings.transcripts:
    assert [t['video_key'] for t in mtgs[2002]['transcripts']] == ['youtube:curatedCapt']
    assert [t['video_key'] for t in mtgs[2003]['transcripts']] == ['youtube:statedCapt1']
    # 3. Alias canonicalized everywhere (no split youtube:aliasVid001 row):
    assert 'youtube:aliasVid001' not in rec
    assert rec['senate:commerce:canon']['event_ids'] == [2004, 2005]
    assert [t['video_key'] for t in mtgs[2005]['transcripts']] == ['senate:commerce:canon']
    # 4. CRPT-119hrpt1.pdf did not steal cropVid0006 from 2006 to 2007:
    assert rec['youtube:cropVid0006']['event_ids'] == [2006]


def test_ct_414r_house_page_date_vetoes_and_rule_provenance(tmp_path):
    """ct-414r: House page-date vetoes (roundtable kind + variants, outbound <a href> / ordinal congress.gov /
    zero-padded EventID conflicts, weak text_head & non-generic topical subcommittee titles) and deterministic
    recording_matches.note provenance (including opposite hash-vs-priority winning body) keeping source_ref unchanged."""
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
    empty_vids = "array_slice(make_array(named_struct('name',cast(NULL AS VARCHAR),'url',cast(NULL AS VARCHAR),'video_key',cast(NULL AS VARCHAR))),1,0)"
    empty_subj = "arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')"
    empty_stated = "arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)')"
    steps = [
        dict(name='recording_url_sources', sql="SELECT id,pattern,key_template,format,default_language,default_production FROM recording_sources WHERE kind='video_url'", materialize=True),
        dict(name='meetings_resolved', sql=f"""SELECT *,arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)') AS transcript_jackets FROM (
            -- 117496: Hearing on CARB locomotive regulation (ct-414r trigger date)
            SELECT cast(117496 AS BIGINT) AS event_id,'house' AS chamber,cast('2024-07-09' AS DATE) AS meeting_date,
              'Hearing' AS meeting_type,'An Examination of the California Air Resources Board In Use Locomotive Regulation' AS title,false AS not_held,
              make_array(named_struct('system_code','hspw00','role','host')) AS committees,{empty_subj} AS subject_keys,{empty_vids} AS videos
            -- 118619: Non-roundtable task force hearing sharing 2 title words with a same-day Democratic roundtable
            UNION ALL SELECT 118619,'house',cast('2025-09-17' AS DATE),'Hearing',
              'Task Force on Monetary Policy: Federal Reserve Independence',false,
              make_array(named_struct('system_code','hsba00','role','host')),{empty_subj},{empty_vids}
            -- 110744: Genuine roundtable meeting (must keep both roundtable video and non-hearing pool clip)
            UNION ALL SELECT 110744,'house',cast('2019-05-03' AS DATE),'HMTG',
              'Roundtable "The Cost of Doing Nothing: The Gateway Project."',false,
              make_array(named_struct('system_code','hspw00','role','host')),{empty_subj},{empty_vids}
            -- 115115, 115134, & 115135: Science hearings for conflicting stated_event_ids & Previous-hearing nav tests
            UNION ALL SELECT 115115,'house',cast('2022-09-15' AS DATE),'Hearing',
              'The Fountain of Youth? The Quest for Aging Therapies',false,
              make_array(named_struct('system_code','hssy00','role','host')),{empty_subj},{empty_vids}
            UNION ALL SELECT 115134,'house',cast('2022-09-21' AS DATE),'Hearing',
              'Looking Back to Predict the Future: The Next Generation of Weather Satellites',false,
              make_array(named_struct('system_code','hssy00','role','host')),{empty_subj},{empty_vids}
            UNION ALL SELECT 115135,'house',cast('2022-09-21' AS DATE),'Hearing',
              'Advancing Commercial Space Launch Safety and Orbital Debris Mitigation',false,
              make_array(named_struct('system_code','hssy00','role','host')),{empty_subj},{empty_vids}
            -- 116134 & 115975: Generic subcommittee video with stale EventID=115975 whose title contains the subcommittee name (must STAY on House date route!)
            UNION ALL SELECT 115975,'house',cast('2023-06-14' AS DATE),'Hearing',
              'Energy and Mineral Resources Subcommittee legislative hearing on three bills',false,
              make_array(named_struct('system_code','hsii06','role','host')),{empty_subj},{empty_vids}
            UNION ALL SELECT 116134,'house',cast('2023-07-12' AS DATE),'Hearing',
              'Oversight Hearing titled Examining the Biden Administration Record on Federal Coal Leasing',false,
              make_array(named_struct('system_code','hsii06','role','host')),{empty_subj},{empty_vids}
            -- 115381 & 115070: Stale EventID on markup video whose bill numbers match 115381 subject_keys (must stay!)
            UNION ALL SELECT 115070,'house',cast('2022-07-27' AS DATE),'HMKP','Markup on Various Measures',false,
              make_array(named_struct('system_code','hsba00','role','host')),arrow_cast(make_array('117-hr-1728'),'List(Utf8)'),{empty_vids}
            UNION ALL SELECT 115381,'house',cast('2023-02-28' AS DATE),'HMKP','Markup of Various Measures',false,
              make_array(named_struct('system_code','hsba00','role','host')),arrow_cast(make_array('118-hr-1076','118-hr-1109'),'List(Utf8)'),{empty_vids}
            -- 108476: Weak nav-bar text_head false-positive vs generic video acceptance (also has subject_keys to verify strong text_head ignores subject_keys)
            UNION ALL SELECT 108476,'house',cast('2018-06-20' AS DATE),'Hearing',
              'Illicit Use of Virtual Currency and the Law Enforcement Response',false,
              make_array(named_struct('system_code','hsba00','role','host')),arrow_cast(make_array('115-hr-5036','115-hr-5037','115-hr-5038'),'List(Utf8)'),{empty_vids}
            -- 108580: Strong text_head press-release quote (4/4 meeting words -> must stay!)
            UNION ALL SELECT 108580,'house',cast('2018-07-18' AS DATE),'Hearing',
              'Monetary Policy and the State of the Economy',false,
              make_array(named_struct('system_code','hsba00','role','host')),{empty_subj},{empty_vids}
            -- 109100: Single-day 1-word text_head-only rejection test
            UNION ALL SELECT 109100,'house',cast('2024-11-12' AS DATE),'Hearing',
              'Protecting Domestic Semiconductor Supply Chains and Workforce Training',false,
              make_array(named_struct('system_code','hsed00','role','host')),{empty_subj},{empty_vids}
        )""", materialize=True),
        dict(name='meetings_export', sql="""SELECT event_id,chamber,meeting_type,title,
            array_slice(make_array(named_struct('source',cast(NULL AS VARCHAR),'package_id',cast(NULL AS VARCHAR),'list_row',cast(NULL AS INT),
             'video_key',cast(NULL AS VARCHAR),'language',cast(NULL AS VARCHAR),'production',cast(NULL AS VARCHAR))),1,0) AS transcripts
            FROM meetings_resolved""", materialize=True),
        dict(name='known_meetings', sql="SELECT event_id,meeting_type,title,subject_keys FROM meetings_resolved", materialize=True),
        dict(name='video_key_aliases', sql="SELECT cast(NULL AS VARCHAR) AS alias_key,cast(NULL AS VARCHAR) AS canonical_key WHERE false", materialize=True),
        dict(name='recording_video_links', sql="""
            -- 01: Shipbuilding roundtable page on 117496 date with NON-roundtable video title -> isolates page-level roundtable veto
            SELECT repeat('01',32) AS page_body,'youtube:rtPageOnly1' AS extracted_key
            -- 02: CARB hearing page holding BOTH true CARB video AND misplaced roundtable video (isolates video-level veto)
            UNION ALL SELECT repeat('02',32),'youtube:carbHearing'
            UNION ALL SELECT repeat('02',32),'youtube:rtMisplaced'
            -- 03: Round-Table variant page sharing 2 title words with 118619, non-roundtable video -> must NOT link to 118619
            UNION ALL SELECT repeat('03',32),'youtube:rtFedIndep1'
            -- 04: True roundtable page for 110744 holding roundtable video + Gateway Pool Video 4 clip
            UNION ALL SELECT repeat('04',32),'youtube:gwRoundtabl'
            UNION ALL SELECT repeat('04',32),'youtube:gwPoolClip4'
            -- 05: Weak/generic page on 2022-09-21 with ONLY labelled anchor text ('Repository') and outbound docs.house.gov EventID=115115 link -> must veto 115134
            UNION ALL SELECT repeat('05',32),'youtube:hrefDocsVet'
            -- 06: Weather Satellites page (matches 115134) holding BOTH true weather video AND swapped 115115 video
            UNION ALL SELECT repeat('06',32),'youtube:weatherTrue'
            UNION ALL SELECT repeat('06',32),'youtube:agingSwap15'
            -- 07: Markup page for 115381 with stale EventID=115070 video whose bills match 115381 -> must STAY
            UNION ALL SELECT repeat('07',32),'youtube:staleMarkup'
            -- 08: Weak nav-bar text_head page on 108476 date holding: unrelated topical video, topical 'Subcommittee on Energy Hearing on Pipeline Leaks', AND generic 'Full Committee Hearing'
            UNION ALL SELECT repeat('08',32),'youtube:taxScamTop1'
            UNION ALL SELECT repeat('08',32),'youtube:pipeLeaksSub'
            UNION ALL SELECT repeat('08',32),'youtube:genericHear'
            -- 09: Strong text_head press release quoting all 4 words of 108580 -> must STAY
            UNION ALL SELECT repeat('09',32),'youtube:watersFedCh'
            -- 0a: Single-day 1-word text_head-only page on 109100 date -> must NOT link
            UNION ALL SELECT repeat('0a',32),'youtube:oneWordHead'
            -- 0b: Page with named_meetings=[115115] on 115134 date -> links 115115 via page_named_meeting, vetoes 115134
            UNION ALL SELECT repeat('0b',32),'youtube:namedMt115A'
            -- 0c: Two outbound <a href> links (congress.gov ordinal slug for 115115 + docs.house.gov for 115134) -> must NOT falsely veto 115134
            UNION ALL SELECT repeat('0c',32),'youtube:multiHref34'
            -- 0d: Outbound <a href> to SAME-DATE ordinal zero-padded congress.gov/event/119th-congress/house-event/0115135 -> must veto 115134
            UNION ALL SELECT repeat('0d',32),'youtube:hrefOrdZero'
            -- 0e: Zero-padded EventID=0115115 in visible text -> must veto 115134
            UNION ALL SELECT repeat('0e',32),'youtube:textZeroPad'
            -- 0f (smaller hash) + f0 (larger hash): OPPOSITE hash vs priority order for (108476, youtube:oppOrderVid)
            UNION ALL SELECT repeat('0f',32),'youtube:oppOrderVid'
            UNION ALL SELECT repeat('f0',32),'youtube:oppOrderVid'
            -- 11: Current Weather Satellites hearing page with a DIFFERENT-DATE 'Previous hearing' nav link to 115115 -> must PRESERVE 115134!
            UNION ALL SELECT repeat('11',32),'youtube:prevNavKeep'
            -- 12: 116134 Federal Coal Leasing hearing page holding generic subcommittee video with stale stated_event_ids=[115975] -> must PRESERVE 116134!
            UNION ALL SELECT repeat('12',32),'youtube:237P3FQXQRg'
            -- 13: Multi-event page naming BOTH 115115 and 115134 with one video per hearing -> each topical video links ONLY to its matching meeting!
            UNION ALL SELECT repeat('13',32),'youtube:multiEvYth1'
            UNION ALL SELECT repeat('13',32),'youtube:multiEvSat1'""", materialize=True),
        dict(name='recording_video_pages', sql="SELECT DISTINCT page_body,arrow_cast(decode(page_body,'hex'),'FixedSizeBinary(32)') AS body_sha FROM recording_video_links", materialize=True),
        dict(name='resolved_link_targets', sql="""
            SELECT repeat('05',32) AS page_body,'https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=115115' AS target_url
            UNION ALL SELECT repeat('0c',32),'https://www.congress.gov/event/117th-congress/house-event/115115'
            UNION ALL SELECT repeat('0c',32),'https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=115134'
            UNION ALL SELECT repeat('0d',32),'https://www.congress.gov/event/119th-congress/house-event/0115135'
            UNION ALL SELECT repeat('11',32),'https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=115115'""", materialize=True),
        dict(name='capture_source_contexts', sql="""SELECT 's01' AS source_id,repeat('01',32) AS body_sha
            UNION ALL SELECT 's02',repeat('02',32)
            UNION ALL SELECT 's03',repeat('03',32)
            UNION ALL SELECT 's04',repeat('04',32)
            UNION ALL SELECT 's05',repeat('05',32)
            UNION ALL SELECT 's06',repeat('06',32)
            UNION ALL SELECT 's07',repeat('07',32)
            UNION ALL SELECT 's08',repeat('08',32)
            UNION ALL SELECT 's09',repeat('09',32)
            UNION ALL SELECT 's0a',repeat('0a',32)
            UNION ALL SELECT 's0b',repeat('0b',32)
            UNION ALL SELECT 's0c',repeat('0c',32)
            UNION ALL SELECT 's0d',repeat('0d',32)
            UNION ALL SELECT 's0e',repeat('0e',32)
            UNION ALL SELECT 's0f',repeat('0f',32)
            UNION ALL SELECT 'sf0',repeat('f0',32)
            UNION ALL SELECT 's11',repeat('11',32)
            UNION ALL SELECT 's12',repeat('12',32)
            UNION ALL SELECT 's13',repeat('13',32)""", materialize=True),
        dict(name='source_addresses', sql="""SELECT 's01' AS source_id,'https://transportation.house.gov/calendar/eventsingle.aspx?EventID=407638' AS url
            UNION ALL SELECT 's02','https://transportation.house.gov/calendar/eventsingle.aspx?EventID=407699'
            UNION ALL SELECT 's03','https://democrats-financialservices.house.gov/events/eventsingle.aspx?EventID=414001'
            UNION ALL SELECT 's04','https://transportation.house.gov/calendar/eventsingle.aspx?EventID=403200'
            UNION ALL SELECT 's05','https://science.house.gov/hearings?ID=HREF-DOCS-115115'
            UNION ALL SELECT 's06','https://science.house.gov/hearings?ID=WEATHER-115134'
            UNION ALL SELECT 's07','https://democrats-financialservices.house.gov/events/eventsingle.aspx?EventID=410157'
            UNION ALL SELECT 's08','https://democrats-financialservices.house.gov/news/documentsingle.aspx?DocumentID=401460'
            UNION ALL SELECT 's09','https://democrats-financialservices.house.gov/news/documentsingle.aspx?DocumentID=401535'
            UNION ALL SELECT 's0a','https://edworkforce.house.gov/calendar/eventsingle.aspx?EventID=409999'
            UNION ALL SELECT 's0b','https://science.house.gov/hearings?ID=NAMED-115115'
            UNION ALL SELECT 's0c','https://science.house.gov/hearings?ID=MULTI-HREF-115134'
            UNION ALL SELECT 's0d','https://science.house.gov/hearings?ID=ORDINAL-ZERO-115135'
            UNION ALL SELECT 's0e','https://science.house.gov/hearings?ID=TEXT-ZERO-115115'
            UNION ALL SELECT 's0f','https://democrats-financialservices.house.gov/news/documentsingle.aspx?DocumentID=401461'
            UNION ALL SELECT 'sf0','https://democrats-financialservices.house.gov/news/documentsingle.aspx?DocumentID=401462'
            UNION ALL SELECT 's11','https://science.house.gov/hearings?ID=PREV-NAV-115134'
            UNION ALL SELECT 's12','https://naturalresources.house.gov/calendar/eventsingle.aspx?EventID=414222'
            UNION ALL SELECT 's13','https://science.house.gov/hearings?ID=MULTI-EVENT-INDEX'""", materialize=True),
        dict(name='recording_page_sources', sql="SELECT DISTINCT c.source_id,c.body_sha AS page_body FROM recording_video_pages vp JOIN capture_source_contexts c ON c.body_sha=vp.page_body", materialize=True),
        dict(name='page_facts', sql="""
            SELECT arrow_cast(decode(repeat('01',32),'hex'),'FixedSizeBinary(32)') AS body_sha,'completed' AS status,
              'Roundtable on Reinvigorating the U.S.-Flag Fleet and Shipbuilding Industry | Transportation Committee' AS title,
              'Roundtable on Reinvigorating the U.S.-Flag Fleet' AS heading,
              cast('2024-07-09' AS VARCHAR) AS content_date,'July 9, 2024 board use resources' AS text_head,arrow_cast(NULL,'List(Int64)') AS named_meetings
            UNION ALL SELECT arrow_cast(decode(repeat('02',32),'hex'),'FixedSizeBinary(32)'),'completed',
              'An Examination of the California Air Resources Board In Use Locomotive Regulation | Transportation Committee',
              'California Air Resources Board Locomotive Regulation','2024-07-09','July 9, 2024',arrow_cast(NULL,'List(Int64)')
            UNION ALL SELECT arrow_cast(decode(repeat('03',32),'hex'),'FixedSizeBinary(32)'),'completed',
              'Democratic Round-Table: Examining Threats to the Federal Reserve Independence | Financial Services Democrats',
              'Democratic Round Table on Federal Reserve Independence','2025-09-17','September 17, 2025',arrow_cast(NULL,'List(Int64)')
            UNION ALL SELECT arrow_cast(decode(repeat('04',32),'hex'),'FixedSizeBinary(32)'),'completed',
              'Roundtable: The Cost of Doing Nothing: The Gateway Project | Transportation Committee',
              'Gateway Project Roundtable','2019-05-03','May 3, 2019',arrow_cast(NULL,'List(Int64)')
            -- 05: Labelled anchor text ONLY ('Repository') on a weak/generic-titled page; docs.house.gov EventID=115115 is in resolved_link_targets
            UNION ALL SELECT arrow_cast(decode(repeat('05',32),'hex'),'FixedSizeBinary(32)'),'completed',
              'Full Committee Hearing | Science Committee','Full Committee Hearing',
              '2022-09-21','Repository weather satellites September 21, 2022',arrow_cast(NULL,'List(Int64)')
            UNION ALL SELECT arrow_cast(decode(repeat('06',32),'hex'),'FixedSizeBinary(32)'),'completed',
              'Looking Back to Predict the Future: The Next Generation of Weather Satellites | Science Committee',
              'The Next Generation of Weather Satellites','2022-09-21','September 21, 2022',arrow_cast(NULL,'List(Int64)')
            UNION ALL SELECT arrow_cast(decode(repeat('07',32),'hex'),'FixedSizeBinary(32)'),'completed',
              'Markup of H.R. 1076 and H.R. 1109 | U.S. House Committee on Financial Services Democrats',
              'Markup of H.R. 1076 and H.R. 1109','2023-02-28','February 28, 2023',arrow_cast(NULL,'List(Int64)')
            -- 08: Even with 3 extra subject_keys tokens (5036, 5037, 5038) + 2 title tokens (illicit, law) in nav, only 2 title_only_words overlap so it stays house_text_head_weak (NOT strong!)
            UNION ALL SELECT arrow_cast(decode(repeat('08',32),'hex'),'FixedSizeBinary(32)'),'completed',
              'Waters: GOP Tax Scam is a Giveaway to Wall Street | U.S. House Committee on Financial Services Democrats',
              'Press Releases','2018-06-20','Menu National Security Illicit Finance tax law 5036 5037 5038 June 20, 2018',arrow_cast(NULL,'List(Int64)')
            UNION ALL SELECT arrow_cast(decode(repeat('09',32),'hex'),'FixedSizeBinary(32)'),'completed',
              'Waters to Fed Chair: Trump Policies Threaten Economic Gains | U.S. House Committee on Financial Services Democrats',
              'Press Releases','2018-07-18','Hearing on Monetary Policy and the State of the Economy July 18, 2018',arrow_cast(NULL,'List(Int64)')
            UNION ALL SELECT arrow_cast(decode(repeat('0a',32),'hex'),'FixedSizeBinary(32)'),'completed',
              'Early Childhood Nutrition Forum | Committee on Education and the Workforce',
              'Early Childhood Nutrition','2024-11-12','November 12, 2024 workforce memo',arrow_cast(NULL,'List(Int64)')
            UNION ALL SELECT arrow_cast(decode(repeat('0b',32),'hex'),'FixedSizeBinary(32)'),'completed',
              'Looking Back to Predict the Future: Weather Satellites','Weather Satellites',
              '2022-09-21','September 21, 2022',arrow_cast(make_array(cast(115115 AS BIGINT)),'List(Int64)')
            UNION ALL SELECT arrow_cast(decode(repeat('0c',32),'hex'),'FixedSizeBinary(32)'),'completed',
              'Oversight Hearing | Weather Satellites Next Generation','Weather Satellites',
              '2022-09-21','Repository links September 21, 2022',arrow_cast(NULL,'List(Int64)')
            UNION ALL SELECT arrow_cast(decode(repeat('0d',32),'hex'),'FixedSizeBinary(32)'),'completed',
              'Looking Back to Predict the Future: Weather Satellites','Weather Satellites',
              '2022-09-21','Congress.gov link September 21, 2022',arrow_cast(NULL,'List(Int64)')
            UNION ALL SELECT arrow_cast(decode(repeat('0e',32),'hex'),'FixedSizeBinary(32)'),'completed',
              'Looking Back to Predict the Future: Weather Satellites','Weather Satellites',
              '2022-09-21','EventID=0115115 September 21, 2022',arrow_cast(NULL,'List(Int64)')
            UNION ALL SELECT arrow_cast(decode(repeat('0f',32),'hex'),'FixedSizeBinary(32)'),'completed',
              'Press Release on Financial Markets | U.S. House Committee on Financial Services Democrats',
              'Press Releases','2018-06-20','Menu Illicit Finance Law June 20, 2018',arrow_cast(NULL,'List(Int64)')
            UNION ALL SELECT arrow_cast(decode(repeat('f0',32),'hex'),'FixedSizeBinary(32)'),'completed',
              'Illicit Use of Virtual Currency','Virtual Currency',
              '2018-06-20','June 20, 2018',arrow_cast(make_array(cast(108476 AS BIGINT)),'List(Int64)')
            UNION ALL SELECT arrow_cast(decode(repeat('11',32),'hex'),'FixedSizeBinary(32)'),'completed',
              'Looking Back to Predict the Future: The Next Generation of Weather Satellites | Science Committee',
              'The Next Generation of Weather Satellites','2022-09-21','Previous hearing September 21, 2022',arrow_cast(NULL,'List(Int64)')
            UNION ALL SELECT arrow_cast(decode(repeat('12',32),'hex'),'FixedSizeBinary(32)'),'completed',
              'Examining the Biden Administration Record on Federal Coal Leasing | House Natural Resources Committee',
              'Examining the Biden Administration Record on Federal Coal Leasing','2023-07-12','July 12, 2023',arrow_cast(NULL,'List(Int64)')
            UNION ALL SELECT arrow_cast(decode(repeat('13',32),'hex'),'FixedSizeBinary(32)'),'completed',
              'Science Committee Hearings Archive','Hearings Archive',NULL,'Archive index',
              arrow_cast(make_array(cast(115115 AS BIGINT),cast(115134 AS BIGINT)),'List(Int64)')""", materialize=True),
        dict(name='publisher_links', sql="SELECT cast(NULL AS VARCHAR) AS page_body,cast(NULL AS VARCHAR) AS source_id WHERE false", materialize=True),
        dict(name='document_members', sql="SELECT cast(NULL AS VARCHAR) AS source_id,cast(NULL AS BIGINT) AS component,cast(NULL AS VARCHAR) AS filename,cast(NULL AS VARCHAR) AS source_url WHERE false", materialize=True),
        dict(name='component_meeting_links', sql="SELECT cast(NULL AS BIGINT) AS component,arrow_cast(NULL,'List(Utf8)') AS meeting_keys WHERE false", materialize=True),
        dict(name='source_annotation_addresses', sql="SELECT cast(NULL AS VARCHAR) AS source_id,cast(NULL AS VARCHAR) AS meeting_key WHERE false", materialize=True),
        dict(name='senate_page_meeting_links', sql="SELECT cast(NULL AS VARCHAR) AS record_sha_hex,cast(NULL AS BIGINT) AS event_id,cast(NULL AS VARCHAR) AS banking_hearing_url WHERE false", materialize=True),
        dict(name='recording_match_stopwords', sql=archive_model.RECORDING_MATCH_STOPWORDS_SQL, materialize=True),
        dict(name='recording_page_event_links', sql=archive_model.RECORDING_PAGE_EVENT_LINKS_SQL, materialize=True),
        dict(name='house_page_meeting_links', sql=sql('house-page-meeting-links'), materialize=True),
        dict(name='recording_page_meetings', sql=archive_model.RECORDING_PAGE_MEETINGS_SQL, materialize=True),
        dict(name='recording_tracks', sql="""SELECT cast(NULL AS VARCHAR) AS video_key,
            array_slice(make_array(named_struct('body',arrow_cast(NULL,'FixedSizeBinary(32)'),'suffix',cast(NULL AS VARCHAR),
             'format',cast(NULL AS VARCHAR),'language',cast(NULL AS VARCHAR),'production',cast(NULL AS VARCHAR))),1,0) AS tracks WHERE false""", materialize=True),
        dict(name='recordings_entity', sql=sql('entity-recordings'), materialize=True),
        dict(name='recording_page_video_events', sql=archive_model.RECORDING_PAGE_VIDEO_EVENTS_SQL, materialize=True),
        dict(name='videos_export', sql=f"""
            -- Non-roundtable video title on roundtable page 01 -> proves page-level roundtable veto independently!
            SELECT 'youtube:rtPageOnly1' AS video_key,arrow_cast(decode(repeat('c1',32),'hex'),'FixedSizeBinary(32)') AS record_sha,{empty_stated} AS stated_event_ids,false AS has_caption,cast(3600 AS INT) AS duration_seconds,'Reinvigorating the U.S.-Flag Fleet and Shipbuilding Industry' AS title
            UNION ALL SELECT 'youtube:carbHearing',arrow_cast(decode(repeat('c2',32),'hex'),'FixedSizeBinary(32)'),{empty_stated},false,3600,'An Examination of the California Air Resources Board In Use Locomotive Regulation'
            UNION ALL SELECT 'youtube:rtMisplaced',arrow_cast(decode(repeat('c3',32),'hex'),'FixedSizeBinary(32)'),{empty_stated},false,3600,'Republican Round Table on the Energy Crisis'
            -- Non-roundtable video title on Round-Table variant page 03 -> proves page-level round-table variant veto independently!
            UNION ALL SELECT 'youtube:rtFedIndep1',arrow_cast(decode(repeat('c4',32),'hex'),'FixedSizeBinary(32)'),{empty_stated},false,3600,'Examining Threats to the Federal Reserve Independence'
            UNION ALL SELECT 'youtube:gwRoundtabl',arrow_cast(decode(repeat('c5',32),'hex'),'FixedSizeBinary(32)'),{empty_stated},false,3600,'Gateway Program Field Roundtable'
            UNION ALL SELECT 'youtube:gwPoolClip4',arrow_cast(decode(repeat('c6',32),'hex'),'FixedSizeBinary(32)'),{empty_stated},false,600,'Gateway Pool Video 4'
            UNION ALL SELECT 'youtube:hrefDocsVet',arrow_cast(decode(repeat('c7',32),'hex'),'FixedSizeBinary(32)'),{empty_stated},false,3600,'Looking Back to Predict the Future: Weather Satellites'
            UNION ALL SELECT 'youtube:weatherTrue',arrow_cast(decode(repeat('c8',32),'hex'),'FixedSizeBinary(32)'),arrow_cast(make_array(cast(115134 AS BIGINT)),'List(Int64)'),false,3600,'Looking Back to Predict the Future: The Next Generation of Weather Satellites (EventID=115134)'
            UNION ALL SELECT 'youtube:agingSwap15',arrow_cast(decode(repeat('c9',32),'hex'),'FixedSizeBinary(32)'),arrow_cast(make_array(cast(115115 AS BIGINT)),'List(Int64)'),false,3600,'The Fountain of Youth? The Quest for Aging Therapies (EventID=115115)'
            UNION ALL SELECT 'youtube:staleMarkup',arrow_cast(decode(repeat('ca',32),'hex'),'FixedSizeBinary(32)'),arrow_cast(make_array(cast(115070 AS BIGINT)),'List(Int64)'),false,3600,'Markup of H.R. 1076; H.R. 1109 (EventID=115070)'
            UNION ALL SELECT 'youtube:taxScamTop1',arrow_cast(decode(repeat('cb',32),'hex'),'FixedSizeBinary(32)'),{empty_stated},false,300,'Waters: GOP Tax Scam is a Giveaway to Wall Street at the Expense of Hardworking Americans'
            UNION ALL SELECT 'youtube:pipeLeaksSub',arrow_cast(decode(repeat('d1',32),'hex'),'FixedSizeBinary(32)'),{empty_stated},false,3600,'Subcommittee on Energy Hearing on Pipeline Leaks'
            UNION ALL SELECT 'youtube:genericHear',arrow_cast(decode(repeat('cc',32),'hex'),'FixedSizeBinary(32)'),{empty_stated},false,3600,'Full Committee Hearing'
            UNION ALL SELECT 'youtube:watersFedCh',arrow_cast(decode(repeat('cd',32),'hex'),'FixedSizeBinary(32)'),{empty_stated},false,300,'Waters to Fed Chair: Trump Policies Threaten Economic Gains'
            UNION ALL SELECT 'youtube:oneWordHead',arrow_cast(decode(repeat('ce',32),'hex'),'FixedSizeBinary(32)'),{empty_stated},false,3600,'Early Childhood Nutrition Forum'
            UNION ALL SELECT 'youtube:namedMt115A',arrow_cast(decode(repeat('cf',32),'hex'),'FixedSizeBinary(32)'),{empty_stated},false,3600,'Aging Therapies Hearing'
            UNION ALL SELECT 'youtube:multiHref34',arrow_cast(decode(repeat('d0',32),'hex'),'FixedSizeBinary(32)'),{empty_stated},false,3600,'Next Generation of Weather Satellites'
            UNION ALL SELECT 'youtube:hrefOrdZero',arrow_cast(decode(repeat('d2',32),'hex'),'FixedSizeBinary(32)'),{empty_stated},false,3600,'Looking Back to Predict the Future: Weather Satellites'
            UNION ALL SELECT 'youtube:textZeroPad',arrow_cast(decode(repeat('d3',32),'hex'),'FixedSizeBinary(32)'),{empty_stated},false,3600,'Looking Back to Predict the Future: Weather Satellites'
            UNION ALL SELECT 'youtube:oppOrderVid',arrow_cast(decode(repeat('d4',32),'hex'),'FixedSizeBinary(32)'),{empty_stated},false,3600,'Full Committee Hearing'
            UNION ALL SELECT 'youtube:prevNavKeep',arrow_cast(decode(repeat('d5',32),'hex'),'FixedSizeBinary(32)'),{empty_stated},false,3600,'Looking Back to Predict the Future: Weather Satellites'
            UNION ALL SELECT 'youtube:237P3FQXQRg',arrow_cast(decode(repeat('d6',32),'hex'),'FixedSizeBinary(32)'),arrow_cast(make_array(cast(115975 AS BIGINT)),'List(Int64)'),false,3600,'Oversight Hearing | Energy and Mineral Resources Subcommittee'
            UNION ALL SELECT 'youtube:multiEvYth1',arrow_cast(decode(repeat('d7',32),'hex'),'FixedSizeBinary(32)'),{empty_stated},false,3600,'The Quest for Aging Therapies'
            UNION ALL SELECT 'youtube:multiEvSat1',arrow_cast(decode(repeat('d8',32),'hex'),'FixedSizeBinary(32)'),{empty_stated},false,3600,'Next Generation of Weather Satellites'""", materialize=True),
        dict(name='meeting_transcript_links', sql="SELECT cast(NULL AS VARCHAR) AS package_id,cast(NULL AS BIGINT) AS event_id WHERE false", materialize=True),
        dict(name='package_meeting_links', sql="SELECT cast(NULL AS VARCHAR) AS package_id,cast(NULL AS BIGINT) AS event_id WHERE false", materialize=True),
        *archive_model.recording_match_prep_steps(videos_relation='videos_export'),
        dict(name='recording_matches_export', sql=sql('entity-recording-matches'), materialize=True),
        dict(name='recordings_export', sql=archive_model.recordings_export_sql(root=ROOT, explorer_inputs=True), materialize=True),
    ]
    run_job(tmp_path / 'job', engine, inputs=inputs, steps=steps, outputs=[
        parquet_output(tmp_path, 'recordings', 'SELECT * FROM recordings_export', ['video_key']),
        parquet_output(tmp_path, 'recording_matches', 'SELECT * FROM recording_matches_export', ['match_id']),
    ], queries=[])

    cp = {(m['event_id'], m['video_key']): m for m in rows(tmp_path, 'recording_matches') if m['basis'] == 'committee_page'}

    # 1. Roundtable vetoes (page-level isolated from video title, round-table/round table variants, and video-level) + positive controls:
    assert (117496, 'youtube:rtPageOnly1') not in cp
    assert (117496, 'youtube:rtMisplaced') not in cp
    assert (118619, 'youtube:rtFedIndep1') not in cp
    assert cp[(117496, 'youtube:carbHearing')]['source_ref'] == 'committee_page:' + '02' * 32
    assert cp[(117496, 'youtube:carbHearing')]['note'].startswith('house_title_words: ')
    assert (110744, 'youtube:gwRoundtabl') in cp
    assert (110744, 'youtube:gwPoolClip4') in cp

    # 2. Conflicting stated_event_id vetoes (labelled <a href> docs.house.gov, ordinal congress.gov + zero-padded ID, visible zero-padded text, named_meetings, video-level) + multi-href & stale markup preserved:
    assert (115134, 'youtube:hrefDocsVet') not in cp
    assert (115134, 'youtube:hrefOrdZero') not in cp
    assert (115134, 'youtube:textZeroPad') not in cp
    assert (115134, 'youtube:agingSwap15') not in cp
    assert (115134, 'youtube:namedMt115A') not in cp
    assert cp[(115115, 'youtube:namedMt115A')]['note'] == 'page_named_meeting'
    assert (115134, 'youtube:multiHref34') in cp
    assert cp[(115134, 'youtube:multiHref34')]['note'] == 'house_title_words: generation, next, satellites, weather'
    assert (115134, 'youtube:weatherTrue') in cp
    assert (115381, 'youtube:staleMarkup') in cp
    assert cp[(115381, 'youtube:staleMarkup')]['note'] == 'house_title_words: 1076, 1109'

    # 3. Tightened text_head fallback: 1-word, nav-bar weak match (even with subject_keys overlap), and topical 'Subcommittee on Energy Hearing on Pipeline Leaks' rejected; generic title & strong quote kept:
    assert (109100, 'youtube:oneWordHead') not in cp
    assert (108476, 'youtube:taxScamTop1') not in cp
    assert (108476, 'youtube:pipeLeaksSub') not in cp
    assert (108476, 'youtube:genericHear') in cp
    assert cp[(108476, 'youtube:genericHear')]['note'] == 'house_text_head_weak: 5036, 5037, 5038, illicit, law'
    assert (108580, 'youtube:watersFedCh') in cp
    assert cp[(108580, 'youtube:watersFedCh')]['note'] == 'house_text_head_strong: economy, monetary, policy, state'

    # 4. Opposite hash vs rule-priority order: source_ref keeps min(page_body) while note names the winning rule & winning body:
    assert cp[(108476, 'youtube:oppOrderVid')]['source_ref'] == 'committee_page:' + '0f' * 32
    assert cp[(108476, 'youtube:oppOrderVid')]['note'] == 'page_named_meeting [via committee_page:' + 'f0' * 32 + ']'

    # 5. Different-date 'Previous hearing' nav anchor does NOT veto a strong title match to the current hearing,
    #    generic subcommittee video (116134/237P3FQXQRg) with stale stated_event_ids=[115975] is preserved on a House date route,
    #    and a multi-event page disambiguates topical videos to their matching meeting instead of Cartesian-joining:
    assert (115134, 'youtube:prevNavKeep') in cp
    assert cp[(115134, 'youtube:prevNavKeep')]['note'].startswith('house_title_words: ')
    assert (116134, 'youtube:237P3FQXQRg') in cp
    assert cp[(116134, 'youtube:237P3FQXQRg')]['note'].startswith('house_title_words: ')
    assert (115115, 'youtube:multiEvYth1') in cp
    assert (115134, 'youtube:multiEvYth1') not in cp
    assert (115134, 'youtube:multiEvSat1') in cp
    assert (115115, 'youtube:multiEvSat1') not in cp

    # 6. Every accepted committee_page row carries deterministic provenance note & committee_page:<sha> source_ref:
    for m in cp.values():
        assert m['source_ref'].startswith('committee_page:')
        assert m['note'] and isinstance(m['note'], str)


def test_explorer_tables_frozen_job_dag_resolves_all_relations(tmp_path):
    """Verify scripts/measure/explorer_tables_frozen.py defines every input/step relation referenced by its
    recording/video/match pipeline (video_key_aliases, known_meetings, recording_page_video_events,
    recording_match_prep_steps, recording_matches_export) and passes retire_relations cleanly."""
    import importlib.util
    from viewer_publication.archive_model import SPICY_SCHEMAS, registry_inputs
    from viewer_publication.archive_model_lifetimes import retire_relations, sql_dependencies

    spec = importlib.util.spec_from_file_location(
        'explorer_tables_frozen', ROOT / 'scripts/measure/explorer_tables_frozen.py'
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    reg_names = {item['name'] for item in registry_inputs(tmp_path / 'regs')}
    declared_inputs = reg_names | {
        'captures', 'meeting_records', 'appearance_records_lake', 'video_records', 'committee_records',
        'released_list', 'released_meetings', 'released_detail', 'page_facts', 'recordings_entity',
        'released_caption_resources', 'recording_decision_records', 'channel_directory', 'parser_versions',
        *SPICY_SCHEMAS.keys(),
    }
    recording_steps = {
        'known_meetings', 'recording_url_sources', 'video_key_aliases', 'recordings_export',
        'retained_caption_tracks', 'videos_export', 'recording_page_video_events',
        'recording_match_stopwords', 'recording_publisher_match_rows', 'recording_page_video_facts',
        'recording_page_video_stated_overlaps', 'recording_page_match_rows', 'recording_linked_packages',
        'recording_matches_export',
    }
    for has_caption in (True, False):
        steps, outputs = mod.build_steps_and_outputs(
            output=tmp_path / f'out_{has_caption}',
            has_document_references=True,
            has_caption_resources=has_caption,
        )
        available = set(declared_inputs) if has_caption else (declared_inputs - {'released_caption_resources'})
        seen = set()
        for step in steps:
            sql_text = step['components']['sql'] if 'components' in step else step['sql']
            if step['name'] in recording_steps:
                missing = sql_dependencies(sql_text) - available
                assert not missing, f"step {step['name']} references undefined relation(s): {sorted(missing)}"
                seen.add(step['name'])
            available.add(step['name'])
        assert seen == recording_steps
        for out in outputs:
            missing = sql_dependencies(out['sql']) - available
            assert not missing, f"output {out['name']} references undefined relation(s): {sorted(missing)}"
        rec_step_list = [s for s in steps if s['name'] in recording_steps]
        rec_outputs = [o for o in outputs if o['name'] in {'videos.parquet', 'recording_matches.parquet'}]
        upstream_names = (set(declared_inputs) | {s['name'] for s in steps}) - recording_steps
        retired = retire_relations(dict(
            scratch=str(tmp_path / 'native'),
            inputs=[dict(name=n) for n in sorted(upstream_names)],
            steps=rec_step_list,
            outputs=rec_outputs,
            queries=[],
        ))
        step_names = {s['name'] for s in retired['steps']}
        assert {'known_meetings', 'recording_url_sources', 'video_key_aliases', 'videos_export',
                'recording_page_video_events', 'recording_match_stopwords', 'recording_publisher_match_rows',
                'recording_page_video_facts', 'recording_page_video_stated_overlaps',
                'recording_page_match_rows', 'recording_linked_packages', 'recording_matches_export'} <= step_names



