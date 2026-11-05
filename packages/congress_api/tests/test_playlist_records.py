"""playlist_records reads the URIs an HLS playlist lists (ct-9s7b)."""
import hashlib

from congress_api.lake import playlist_records
from congress_api.parsers.captions import playlist_uris

MEDIA = ('#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:12\n#EXT-X-MEDIA-SEQUENCE:1\n#EXT-X-PLAYLIST-TYPE:VOD\n'
         '#EXTINF:12.00000,\ntext_1_00001.vtt\n#EXTINF:12.00000,\n#EXT-X-BYTERANGE:100@0\ntext_1_00002.vtt\n#EXT-X-ENDLIST\n')
MASTER = ('﻿#EXTM3U\n#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",LANGUAGE="en",URI="text_1.m3u8"\n'
          '#EXT-X-STREAM-INF:BANDWIDTH=1000,SUBTITLES="subs"\nvideo_1.m3u8\n'
          '#EXT-X-I-FRAME-STREAM-INF:BANDWIDTH=100,URI="iframe.m3u8"\n')


def test_media_playlist_lists_its_segments_in_order():
    assert playlist_uris(MEDIA) == dict(status='completed', error_type=None,
                                        segments=['text_1_00001.vtt', 'text_1_00002.vtt'], playlists=[])


def test_a_uri_line_without_extinf_is_a_segment():
    assert playlist_uris('#EXTM3U\n../one.vtt\nhttps://x.gov/two.vtt\n')['segments'] == ['../one.vtt', 'https://x.gov/two.vtt']


def test_master_playlist_lists_playlists_not_segments():
    assert playlist_uris(MASTER)['segments'] == []
    assert playlist_uris(MASTER)['playlists'] == ['text_1.m3u8', 'video_1.m3u8', 'iframe.m3u8']


def test_a_body_that_is_not_a_playlist_is_an_error_row():
    caption = b'WEBVTT\nX-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:183000\n\n'
    row = playlist_records.build_row(hashlib.sha256(caption).hexdigest(), 'hls', caption, parser_version='v')
    assert (row['status'], row['error_type'], row['segments']) == ('error', 'not_m3u8', [])
    assert playlist_records.build_row('ab' * 32, 'hls', b'\xff\xfe', parser_version='v')['error_type'] == 'not_utf8'


def test_rows_build_the_lake_schema():
    row = playlist_records.build_row('ab' * 32, 'hls', MEDIA.encode(), parser_version='v')
    table = playlist_records.table([row])
    assert table.schema == playlist_records.ARROW_SCHEMA
    assert table.to_pylist()[0]['segments'] == ['text_1_00001.vtt', 'text_1_00002.vtt']
