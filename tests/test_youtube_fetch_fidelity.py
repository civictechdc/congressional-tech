"""The cache keeps complete returned API records, including unknown fields."""
from unittest.mock import MagicMock

from tinydb import TinyDB
from tinydb.storages import MemoryStorage

from youtube_api.fetch.youtube_event_fetcher import (
    YoutubeEventFetcher, insert_videos_into_tb, parse_channel_details,
)


def playlist(video='video', title='Playlist title'):
    return {'id': 'playlist-item-' + video, 'etag': 'original', 'futureField': [1, 2],
            'snippet': {'resourceId': {'videoId': video}, 'title': title,
                        'description': 'Description', 'publishedAt': '2025-01-01T01:00:00Z'}}


def fetcher(items):
    obj = object.__new__(YoutubeEventFetcher)
    obj.tinydb = TinyDB(storage=MemoryStorage)
    obj.youtube = MagicMock()
    obj.youtube.videos.return_value.list.return_value.execute.return_value = {'items': items}
    return obj


def test_existing_playlist_item_does_not_drop_other_items_on_returned_page():
    obj = fetcher([])
    table = obj.tinydb.table('youtube_videos_test')
    insert_videos_into_tb([playlist()], table)
    stopped, added = insert_videos_into_tb([playlist(title='Revised'), playlist('new')], table)
    assert stopped and added == 1
    assert len(table) == 2
    assert table.all()[0]['upstream']['playlist_item']['item'] == playlist(title='Revised')


def test_complete_video_and_channel_records_survive_normalization():
    item = {'id': 'video', 'snippet': {'title': 'Video title', 'channelId': 'UC-example',
            'publishedAt': '2024-12-31T13:00:00Z'}, 'contentDetails': {'duration': 'PT1M2S',
            'caption': 'true', 'regionRestriction': {'blocked': ['XX']}},
            'status': {'embeddable': False}, 'liveStreamingDetails': {'actualStartTime': '2024-12-31T13:00:00Z'}}
    obj = fetcher([item]); table = obj.tinydb.table('youtube_videos_test')
    table.insert({'videoId': 'video', 'caption': False, 'duration': 1, 'publishedAt': '2025-01-01T01:00:00Z'})
    assert obj.update_video_details('test')
    saved = table.all()[0]
    assert saved['upstream']['video']['item'] == item
    assert saved['caption'] is True and saved['duration'] == 62
    assert saved['publishedAt'] != saved['videoPublishedAt']
    assert saved['channelId'] == 'UC-example'
    assert saved['available'] is True
    channel = {'id': 'UC-example', 'snippet': {'title': 'Committee'},
               'contentDetails': {'relatedPlaylists': {'uploads': 'UU-example'}}, 'unknown': {'keep': True}}
    assert parse_channel_details(channel)['upstream']['item'] == channel


def test_unavailable_video_keeps_last_returned_item_but_clears_current_claims():
    item = {'id': 'video', 'contentDetails': {'duration': 'PT5M', 'caption': 'true'}}
    obj = fetcher([]); table = obj.tinydb.table('youtube_videos_test')
    table.insert({'videoId': 'video', 'caption': True, 'duration': 300,
                  'upstream': {'video': {'retrieved_at': '2025-01-01', 'item': item}}})
    assert obj.update_video_details('test')
    saved = table.all()[0]
    assert saved['upstream']['video']['item'] == item
    assert saved['available'] is False
    assert saved['duration'] is None and saved['caption'] is None
    assert saved['details_checked_at']


def test_missing_caption_field_is_unknown_not_false():
    obj = fetcher([{'id': 'video', 'contentDetails': {'duration': 'PT5M'}}])
    table = obj.tinydb.table('youtube_videos_test'); table.insert({'videoId': 'video'})
    assert obj.update_video_details('test')
    assert table.all()[0]['caption'] is None


def test_interrupted_playlist_scan_replays_beyond_its_own_partial_writes():
    import pytest
    obj = fetcher([]); obj.videos_tbs = {}; obj.channels_tb = obj.tinydb.table('youtube_channels')
    obj.channels_tb.insert({'handle': 'test', 'uploads': 'UU-test', 'uploads_scan_complete': True})
    first = {'items': [playlist('first')], 'pageInfo': {'totalResults': 2}, 'nextPageToken': 'second-page'}
    second = {'items': [playlist('second')], 'pageInfo': {'totalResults': 2}}
    execute = obj.youtube.playlistItems.return_value.list.return_value.execute
    execute.side_effect = [first, RuntimeError('temporary failure')]
    with pytest.raises(RuntimeError): obj.get_all_channel_videos('test')
    assert obj.channels_tb.all()[0]['uploads_scan_complete'] is False
    execute.side_effect = [first, second]
    obj.get_all_channel_videos('test')
    assert {r['videoId'] for r in obj.tinydb.table('youtube_videos_test')} == {'first', 'second'}
    assert obj.channels_tb.all()[0]['uploads_scan_complete'] is True


def test_forced_scan_preserves_prior_capture_on_failure_and_refreshes_video_details():
    import pytest
    obj = fetcher([]); obj.force = True; obj.videos_tbs = {}
    obj.channels_tb = obj.tinydb.table('youtube_channels')
    obj.channels_tb.insert({'handle': 'test', 'uploads': 'UU-test', 'uploads_scan_complete': True})
    table = obj.tinydb.table('youtube_videos_test')
    old = {'videoId': 'old', 'title': 'Retained title', 'caption': True, 'duration': 300,
           'metadata_version': 1, 'details_checked_at': '2999-01-01T00:00:00+00:00',
           'upstream': {'video': {'item': {'id': 'old', 'unknown': 'preserve'}}}}
    table.insert(old)
    execute = obj.youtube.playlistItems.return_value.list.return_value.execute
    execute.side_effect = RuntimeError('interrupted refresh')
    with pytest.raises(RuntimeError): obj.get_all_channel_videos('test')
    assert table.all() == [old]
    assert not obj.channels_tb.all()[0]['uploads_scan_complete']
    assert obj.update_video_details('test')
    assert table.all()[0]['available'] is False
    assert table.all()[0]['upstream'] == old['upstream']


def test_forced_channel_refresh_failure_does_not_clear_other_channels():
    obj = fetcher([]); obj.force = True
    obj.channels_tb = obj.tinydb.table('youtube_channels')
    original = [{'handle': 'test', 'uploads': 'one'}, {'handle': 'test', 'uploads': 'two'},
                {'handle': 'another', 'uploads': 'three'}]
    obj.channels_tb.insert_multiple(original)
    obj.youtube.channels.return_value.list.return_value.execute.return_value = {'items': []}
    assert obj.get_channel('test') is None
    assert obj.channels_tb.all() == original


def test_completed_detail_batch_survives_later_transport_failure():
    import pytest
    obj = fetcher([]); table = obj.tinydb.table('youtube_videos_test')
    table.insert_multiple([{'videoId': str(i)} for i in range(51)])
    returned = [{'id': str(i), 'contentDetails': {'caption': 'true'}} for i in range(50)]
    obj.youtube.videos.return_value.list.return_value.execute.side_effect = [
        {'items': returned}, TimeoutError('connection timed out')]
    with pytest.raises(TimeoutError): obj.update_video_details('test')
    for row, item in zip(table.all()[:50], returned):
        assert row['upstream']['video']['item'] == item
        assert row['details_checked_at'] and row['caption'] is True
    assert table.all()[50] == {'videoId': '50'}


def test_interrupted_tinydb_write_leaves_previous_capture_readable(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    import pytest
    from youtube_api.tables import open_tinydb_for_committee
    db = open_tinydb_for_committee(0, tinydb_dir=tmp_path)
    db.table('videos').insert({'videoId': 'first', 'title': 'Retained'})
    path = tmp_path / 'youtube_00.json'
    original = path.read_bytes()
    def interrupted(*args):
        raise OSError('replacement interrupted')
    monkeypatch.setattr(Path, 'replace', interrupted)
    with pytest.raises(OSError): db.table('videos').insert({'videoId': 'second'})
    assert path.read_bytes() == original
    assert json.loads(original)['videos']['1']['title'] == 'Retained'
    assert sorted(p.name for p in tmp_path.iterdir()) == ['youtube_00.json']
