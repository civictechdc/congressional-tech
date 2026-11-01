"""`video_records` keeps typed cache facts, null where a cache row states nothing."""
import json

import pyarrow.parquet as pq
import pytest

from congress_api.lake import video_records
from congress_api.matching.gpo_videos import EVENT_ID as MATCHER_EVENT_ID
from congress_api.parsers.youtube_video import EVENT_ID, stated_event_ids

SHA = 'ab' * 32


def cache():
    return json.dumps({
        'youtube_channels': {'1': dict(handle='@A', channelId='UCA', title='A', customUrl='@a', uploads_scan_complete=True, upstream={'big': 1})},
        'youtube_videos_@A': {
            '1': dict(videoId='v1', title='Hearing EventID=117681', description='(ID: 117681) and house-event/118000', channelId='UCA', channelTitle='A',
                publishedAt='2020-01-02T03:04:05Z', videoPublishedAt='2020-01-02T03:04:06Z', duration='60', available=True, caption=False,
                details_checked_at='2026-01-01T00:00:00+00:00', upstream={'big': 1}),
            '2': dict(videoId='v2'),
        },
        'youtube_videos_@B': {'1': dict(videoId='v1', title='Same video on another table')},
    }).encode()


def build(payload=None):
    return video_records.build_row(SHA, 'youtube_cache', cache() if payload is None else payload, parser_version='v')


def test_matcher_uses_the_one_event_id_rule():
    assert MATCHER_EVENT_ID is EVENT_ID


def test_multi_table_cache_is_typed_and_upstream_stays_in_the_body():
    row = build()
    assert [c['channel_id'] for c in row['channels']] == ['UCA'] and 'upstream' not in row['channels'][0]
    assert [(v['handle'], v['video_id']) for v in row['videos']] == [('@A', 'v1'), ('@A', 'v2'), ('@B', 'v1')]
    first = row['videos'][0]
    assert first['duration_seconds'] == 60 and first['available'] is True and first['has_caption'] is False
    assert first['stated_event_ids'] == [117681, 118000] and 'upstream' not in first


def test_missing_channel_fields_stay_null():
    missing = build()['videos'][1]
    assert missing['channel_id'] is None and missing['duration_seconds'] is None
    assert missing['available'] is None and missing['has_caption'] is None and missing['stated_event_ids'] == []


def test_empty_cache_is_a_completed_empty_row():
    row = build(b'{}')
    assert row['status'] == 'completed' and row['channels'] == [] and row['videos'] == []


@pytest.mark.parametrize('payload', [b'{not json', json.dumps({'youtube_videos_@A': ['x']}).encode(), json.dumps({'youtube_videos_@A': {'1': {}}}).encode()])
def test_malformed_cache_raises_the_errors_staging_records_as_unreadable(payload):
    with pytest.raises((ValueError, KeyError)):
        build(payload)


def test_repeated_event_ids_are_stated_once():
    assert stated_event_ids('EventID=117681 EventID=117681', 'ID: 117681') == [117681]


def test_same_bytes_give_same_rows_and_table_matches_declared_schema(tmp_path):
    assert build() == build()
    table = video_records.table([build()])
    assert table.schema.equals(video_records.ARROW_SCHEMA)
    pq.write_table(table, tmp_path / 'one.parquet')
    assert pq.read_table(tmp_path / 'one.parquet').to_pylist()[0]['videos'][0]['video_id'] == 'v1'


def test_versions_and_candidate_sql_are_stated():
    assert set(video_records.current_versions()) == {'youtube_cache'}
    assert "family='pipeline-data'" in video_records.candidate_sql()
