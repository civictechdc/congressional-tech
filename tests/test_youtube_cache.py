"""Retained cache decoding preserves data, order and consumer boundaries."""

from copy import deepcopy
import json
import os
import subprocess
import sys

import pytest

from congress_api.cli.gpo_match import load_videos
from congress_api.retention.tables import read_youtube_videos
from congress_shared.youtube_cache import decode_cache


def video(**changes):
    return {"videoId": "abcdefghijk", "title": "Competition", "description": "EventID=123456; Jan 2, 2026 audio only",
            "publishedAt": "2026-01-03T12:00:00Z", "channelId": "ROW_CHANNEL", "caption": False,
            "duration": 3600, "future": {"native": [None, 0]}, **changes}


@pytest.fixture
def tables():
    return {"_default": {"1": {"ignored": True}},
            "youtube_videos_@second": {"9": video(), "2": video(title="Second upload")},
            "youtube_channels": {"5": {"handle": "@first", "channelId": "UC-native", "future": None},
                                 "1": {"handle": "@second", "title": "Comité"}},
            "youtube_videos_@empty": {},
            "youtube_videos_@first": {"4": video(videoId="zzzzzzzzzzz")},
            "youtube_videos": {"1": {"ignored": True}}}


@pytest.mark.parametrize("source", ["data", "text", "bytes"])
def test_decoder_keeps_literal_handles_rows_metadata_duplicates_and_order(tables, source):
    original = deepcopy(tables)
    data = tables if source == "data" else json.dumps(tables, ensure_ascii=False)
    if source == "bytes":
        data = data.encode()
    cache = decode_cache(data)
    expected = [("@second", tables["youtube_videos_@second"]["9"]),
                ("@second", tables["youtube_videos_@second"]["2"]),
                ("@first", tables["youtube_videos_@first"]["4"])]
    assert list(cache.videos()) == expected
    assert list(cache.channels()) == list(tables["youtube_channels"].values())
    if source == "data":
        assert list(cache.videos())[0][1] is expected[0][1]
        assert list(cache.channels())[0] is tables["youtube_channels"]["5"]
    assert tables == original


@pytest.mark.parametrize("data", [{}, {"youtube_videos_@empty": {}, "youtube_channels": {}}, {"other": None}])
def test_empty_or_unrelated_tables_produce_no_rows(data):
    cache = decode_cache(data)
    assert list(cache.videos()) == list(cache.channels()) == []


@pytest.mark.parametrize("data", [b"", b"{not json}", "{not json}"])
def test_invalid_json_still_fails(data):
    with pytest.raises(json.JSONDecodeError):
        decode_cache(data)


def test_bad_table_fails_when_reached_and_channel_errors_stay_separate():
    row = video()
    cache = decode_cache({"youtube_videos_@valid": {"1": row}, "youtube_videos_@bad": [], "youtube_channels": None})
    rows = cache.videos()
    assert next(rows) == ("@valid", row)
    with pytest.raises(AttributeError):
        next(rows)
    with pytest.raises(AttributeError):
        list(cache.channels())
    # Structural decoding does not reinterpret or discard malformed video rows.
    assert list(decode_cache({"youtube_videos_": {"1": None}}).videos()) == [("", None)]
    with pytest.raises(AttributeError):
        list(decode_cache(b"[]").videos())


def test_inventory_and_gpo_preserve_file_indexes_and_candidate_policy(tmp_path, tables):
    path = tmp_path / "youtube_01.json"
    body = json.dumps(tables, ensure_ascii=False, indent=2).encode()
    path.write_bytes(body)
    # Channel metadata is irrelevant to these video-only readers, even if invalid.
    (tmp_path / "youtube_02.json").write_text(json.dumps({"youtube_channels": None}))
    channels = [{"systemCode": "missing"}, {"systemCode": "hsju00"}, {"systemCode": "empty"}]
    rows = list(read_youtube_videos(tmp_path, channels))
    assert rows == [("hsju00", row) for _, row in decode_cache(tables).videos()]
    candidates = load_videos(tmp_path, channels)
    assert list(candidates) == ["hsju00"]
    assert candidates["hsju00"][0] == {
        "videoId": "abcdefghijk", "channel": "@second", "published": "2026-01-03", "title": "Competition",
        "words": {"competition"}, "dates": {"2026-01-02"}, "event_ids": {"123456"}, "duration": 3600, "audio_only": True,
    }
    assert [row["channel"] for row in candidates["hsju00"]] == ["@second", "@second", "@first"]
    assert [row["videoId"] for row in candidates["hsju00"]] == [row["videoId"] for _, row in rows]
    assert path.read_bytes() == body
    assert sorted(p.name for p in tmp_path.iterdir()) == ["youtube_01.json", "youtube_02.json"]


@pytest.mark.parametrize("reader", [read_youtube_videos, load_videos])
@pytest.mark.parametrize("body,error", [(b"", json.JSONDecodeError), (b"{not json}", json.JSONDecodeError),
                                       (b"[]", AttributeError), (b'{"youtube_videos_x": []}', AttributeError)])
def test_consumers_keep_malformed_file_errors(tmp_path, reader, body, error):
    path = tmp_path / "youtube_00.json"
    path.write_bytes(body)
    with pytest.raises(error):
        list(reader(tmp_path, [{"systemCode": "hsju00"}]))
    assert path.read_bytes() == body


def test_decoder_imports_only_standard_library_and_does_no_io():
    program = '''
import importlib.abc
import sys
class NoProviders(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'youtube_api', 'congress_api', 'committee_meeting', 'tinydb', 'googleapiclient', 'yt_dlp'} or fullname == 'congress_shared.globals':
            raise AssertionError('decoder imported ' + fullname)
sys.meta_path.insert(0, NoProviders())
from congress_shared.youtube_cache import decode_cache
def forbidden(*args, **kwargs):
    raise AssertionError('decoder attempted file or network access')
import builtins
import socket
builtins.open = forbidden
socket.socket.connect = forbidden
assert list(decode_cache(b'{"youtube_videos_@x": {"1": {"videoId": "retained"}}}').videos()) == [('@x', {'videoId': 'retained'})]
'''
    result = subprocess.run([sys.executable, "-c", program], env=os.environ.copy(), text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
