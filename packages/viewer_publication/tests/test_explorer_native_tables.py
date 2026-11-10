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
        dict(name='meetings_export', sql="""SELECT cast(event_id AS BIGINT) AS event_id,chamber,CASE WHEN event_id=1009 THEN make_array(
              named_struct('source','captions','package_id',cast(NULL AS VARCHAR),'list_row',cast(NULL AS INT),'video_key','youtube:v','language','en','production','asr'),
              named_struct('source','committee_transcript','package_id',cast(NULL AS VARCHAR),'list_row',cast(3 AS INT),'video_key',cast(NULL AS VARCHAR),'language',cast(NULL AS VARCHAR),'production',cast(NULL AS VARCHAR)))
             ELSE array_slice(make_array(named_struct('source',cast(NULL AS VARCHAR),'package_id',cast(NULL AS VARCHAR),'list_row',cast(NULL AS INT),
              'video_key',cast(NULL AS VARCHAR),'language',cast(NULL AS VARCHAR),'production',cast(NULL AS VARCHAR))),1,0) END AS transcripts,
             CASE WHEN event_id=1014 THEN 'Nomination of Pat Nominee to be Judge' ELSE 'Hearing' END AS title
            FROM (SELECT 1001 AS event_id,'house' AS chamber UNION ALL SELECT 1002,'house' UNION ALL SELECT 1003,'house' UNION ALL SELECT 1004,'house' UNION ALL SELECT 1005,'house'
             UNION ALL SELECT 1006,'house' UNION ALL SELECT 1007,'house' UNION ALL SELECT 1008,'senate' UNION ALL SELECT 1009,'house' UNION ALL SELECT 1010,'house' UNION ALL SELECT 1011,'house'
             UNION ALL SELECT 1012,'house' UNION ALL SELECT 1013,'house' UNION ALL SELECT 1014,'senate' UNION ALL SELECT 1015,'house')""", materialize=True),
        dict(name='meeting_transcript_links', sql=f"""SELECT '{CONFLICT_PKG}' AS package_id,cast(1001 AS BIGINT) AS event_id UNION ALL SELECT '{SHARED_PKG}',1003 UNION ALL SELECT '{SHARED_PKG}',1004 UNION ALL SELECT '{SOLO_PKG}',1002 UNION ALL SELECT 'CHRG-alone',1005 UNION ALL SELECT 'CHRG-disputed',1006 UNION ALL SELECT 'CHRG-sibling',1007 UNION ALL SELECT 'CHRG-no-verdict',1007 UNION ALL SELECT 'CHRG-unattached',1010 UNION ALL SELECT 'CHRG-qualified',1002 UNION ALL SELECT 'CHRG-qualified',1004""", materialize=True),
        dict(name='package_mods_facts', sql="""SELECT 'CHRG-unattached' AS package_id,arrow_cast(make_array(cast(9999 AS BIGINT)),'List(Int64)') AS named_meetings
            UNION ALL SELECT 'CHRG-unlinked',arrow_cast(make_array(cast(1011 AS BIGINT)),'List(Int64)')""", materialize=True),
        # The packages whose own print stands for their meeting (rule tested in test_meeting_semantics);
        # CHRG-unattached's print names another meeting, and 1003, 1004 and 1007 have no such print.
        dict(name='package_meeting_links', sql=f"""SELECT '{CONFLICT_PKG}' AS package_id,cast(1001 AS BIGINT) AS event_id
            UNION ALL SELECT '{SOLO_PKG}',1002 UNION ALL SELECT 'CHRG-alone',1005 UNION ALL SELECT 'CHRG-disputed',1006 UNION ALL SELECT 'CHRG-qualified',1002 UNION ALL SELECT 'CHRG-qualified',1004""", materialize=True),
        dict(name='meeting_document_urls', sql="SELECT cast(1009 AS BIGINT) AS event_id,'https://docs.house.gov/x.pdf' AS url", materialize=True),
        dict(name='videos_export', sql="""SELECT 'youtube:pub' AS video_key,arrow_cast(decode(repeat('ab',32),'hex'),'FixedSizeBinary(32)') AS record_sha,arrow_cast(make_array(cast(777777 AS BIGINT)),'List(Int64)') AS stated_event_ids,true AS has_caption
            UNION ALL SELECT 'youtube:nocaption',arrow_cast(decode(repeat('ac',32),'hex'),'FixedSizeBinary(32)'),
              arrow_cast(make_array(cast(1003 AS BIGINT)),'List(Int64)'),false
            UNION ALL SELECT 'youtube:unmatched',arrow_cast(decode(repeat('ab',32),'hex'),'FixedSizeBinary(32)'),arrow_cast(array_slice(make_array(cast(1 AS BIGINT)),1,0),'List(Int64)'),false""", materialize=True),
        dict(name='selected_appearance_records', sql='SELECT * FROM appearance_records_input', materialize=True),
        dict(name='recording_matches_export', sql=sql('entity-recording-matches'), materialize=True),
        dict(name='ordered', sql="SELECT arrow_cast(make_array('1001'),'List(Utf8)') AS meeting_keys", materialize=True),
        # 1001 shows Jane once: the print's Jane is superseded by the meeting's own row, and a letter for the
        # record is a statement, not a witness. 1012 lists only a sitting Member, 1013 a Member and an outside
        # witness, 1014 only the Member introducing a nominee it leaves out, 1015 a Member and record material (ct-kw85).
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
            UNION ALL SELECT 1015 AS event_id,'Letter of support' AS name,cast(NULL AS VARCHAR) AS package_id,'record_material' AS witness_type,cast(NULL AS VARCHAR) AS superseded_by""", materialize=True),
        dict(name='recordings_export', sql="SELECT 'youtube:unmatched' AS video_key,make_array(1) AS tracks", materialize=True),
        dict(name='meeting_coverage_export', sql=sql('entity-meeting-coverage'), materialize=True),
    ]
    inputs += [json_input(work, 'appearance_records_input', [
            dict(event_id=1002, source='house_xml', parser_version='v', status='completed', collection_state='empty', appearances=[]),
            dict(event_id=1003, source='house_xml', parser_version='v', status='completed', collection_state='failed', appearances=[])],
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
    assert len(found) == 15 * 5
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
        assert dict(db.execute(recipes['coverage_counts']['sql'], ['witnesses']).fetchall())['empty'] == 3


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
