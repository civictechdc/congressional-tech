"""Reuse local work without changing source identity or durable page boundaries."""
from copy import deepcopy
import builtins
import csv
import importlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError
from tinydb import TinyDB, where
from tinydb.storages import MemoryStorage
from tinydb.table import Document, Table

from congress_shared.resources import DEFAULT_CHANNELS_CSV
from youtube_api.fetch.youtube_event_fetcher import (
    YoutubeEventFetcher, insert_videos_into_tb, parse_video_details, video_document_ids,
)
from youtube_api.tables import open_tinydb_for_committee

CID = "UCB6LGE5-_i-xxtZxk1_SeTg"
OTHER_ID = "UCY08wEbJ8fztRofQ9eZs0-g"


def playlist(video, title=None):
    return {"id": "entry-" + video, "snippet": {
        "resourceId": {"videoId": video}, "title": title or video,
        "description": "EventID=123456", "publishedAt": "2025-01-04T00:00:00Z"}}


def fetcher(db):
    obj = object.__new__(YoutubeEventFetcher)
    obj.tinydb = db
    obj.channels_tb = db.table("youtube_channels")
    obj.channels_tb.insert({"handle": "test", "uploads": "UU-fixture", "uploads_scan_complete": False})
    obj.youtube = MagicMock()
    return obj


def api():
    service = MagicMock()
    def channel(**kwargs):
        request = MagicMock()
        channel_id = kwargs["id"]
        request.execute.return_value = {"items": [{"id": channel_id, "snippet": {"title": "Fixture"},
            "contentDetails": {"relatedPlaylists": {"uploads": "UU" + channel_id[2:]}}}]}
        return request
    service.channels.return_value.list.side_effect = channel
    service.playlistItems.return_value.list.return_value.execute.return_value = {
        "items": [], "pageInfo": {"totalResults": 0}}
    return service


@pytest.mark.parametrize("name,index,channel_count", [(None, None, 119), ("Natural Resources", None, 2), (None, 11, 2)])
def test_fetch_command_reads_configuration_once(tmp_path, monkeypatch, name, index, channel_count):
    main = importlib.import_module("youtube_api.fetch.main")
    module = importlib.import_module("youtube_api.fetch.youtube_event_fetcher")
    service = api()
    monkeypatch.setattr(main, "load_youtube_api_key", lambda: "fixture")
    monkeypatch.setattr(module, "build", lambda *args, **kwargs: service)
    original = builtins.open
    opens = []
    def opened(path, *args, **kwargs):
        if Path(path).resolve() == DEFAULT_CHANNELS_CSV.resolve():
            opens.append(path)
        return original(path, *args, **kwargs)
    with patch("builtins.open", opened):
        main.main(tmp_path, name, index, DEFAULT_CHANNELS_CSV)
    assert len(opens) == 1
    assert service.channels.return_value.list.call_count == channel_count


def test_next_command_reads_changed_configuration(tmp_path, monkeypatch):
    main = importlib.import_module("youtube_api.fetch.main")
    module = importlib.import_module("youtube_api.fetch.youtube_event_fetcher")
    service = api()
    monkeypatch.setattr(main, "load_youtube_api_key", lambda: "fixture")
    monkeypatch.setattr(module, "build", lambda *args, **kwargs: service)
    config = tmp_path / "channels.csv"
    for number, channel_id in enumerate((CID, OTHER_ID)):
        with config.open("w", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(["committee", "systemCode", "handle", "secondary", "channel_ids"])
            writer.writerow(["Fixture", "hsii00", "@fixture", "", json.dumps({"@fixture": channel_id})])
        main.main(tmp_path / str(number), None, None, config)
    assert [call.kwargs["id"] for call in service.channels.return_value.list.call_args_list] == [CID, OTHER_ID]


def test_scan_indexes_once_updates_new_ids_and_keeps_duplicate_rows():
    db = TinyDB(storage=MemoryStorage)
    obj = fetcher(db)
    table = db.table("youtube_videos_test")
    table.insert_multiple([parse_video_details(playlist("a")), parse_video_details(playlist("a")),
                           parse_video_details(playlist("old"))])
    execute = obj.youtube.playlistItems.return_value.list.return_value.execute
    execute.side_effect = [
        {"items": [playlist("a", "revised-a"), playlist("b")], "pageInfo": {"totalResults": 4}, "nextPageToken": "second"},
        {"items": [playlist("b", "revised-b"), playlist("c")], "pageInfo": {"totalResults": 4}},
    ]
    original = Table.all
    scans = []
    def all_rows(self):
        result = original(self)
        if self is table:
            scans.append(len(result))
        return result
    with patch.object(Table, "all", all_rows):
        obj.get_all_channel_videos("test")
    assert scans == [3]
    rows = table.all()
    assert [row["videoId"] for row in rows] == ["a", "a", "old", "b", "c"]
    assert [row["title"] for row in rows] == ["revised-a", "revised-a", "old", "revised-b", "c"]
    assert execute.call_count == 2


def test_one_atomic_page_write_preserves_ids_fields_order_and_query_invalidation(tmp_path):
    db = open_tinydb_for_committee(0, tinydb_dir=tmp_path)
    table = db.table("youtube_videos_test")
    first = {**parse_video_details(playlist("same")), "unknown": "first", "upstream": {"video": {"keep": True}}}
    second = {**parse_video_details(playlist("same")), "unknown": "second"}
    table.insert_multiple([Document(first, doc_id=9), Document(second, doc_id=2)])
    assert len(table.search(where("title") == "same")) == 2  # Prime TinyDB's query cache.
    index = video_document_ids(table)
    with patch.object(db.storage, "write", wraps=db.storage.write) as written:
        assert insert_videos_into_tb([playlist("same", "revised"), playlist("new"), playlist("new", "last")],
                                     table, existing=index) == (True, 1)
    assert written.call_count == 1
    rows = table.all()
    assert [row.doc_id for row in rows] == [9, 2, 10]
    assert [row["videoId"] for row in rows] == ["same", "same", "new"]
    assert [row["title"] for row in rows] == ["revised", "revised", "last"]
    assert rows[0]["unknown"] == "first" and rows[1]["unknown"] == "second"
    assert rows[0]["upstream"]["video"] == {"keep": True}
    assert index == {"same": [9, 2], "new": [10]}
    assert table.search(where("title") == "same") == []
    assert len(table.search(where("title") == "revised")) == 2


@pytest.mark.parametrize("failure", ["replace", "fsync"])
def test_failed_page_leaves_disk_and_scan_index_unchanged_and_can_retry(tmp_path, failure):
    db = open_tinydb_for_committee(0, tinydb_dir=tmp_path)
    table = db.table("youtube_videos_test")
    table.insert(parse_video_details(playlist("old")))
    index = video_document_ids(table)
    original_index = deepcopy(index)
    path = tmp_path / "youtube_00.json"
    before = path.read_bytes()
    with patch.object(db.storage, "write", wraps=db.storage.write) as writes:
        target = "pathlib.Path.replace" if failure == "replace" else "congress_shared.custody.os.fsync"
        with patch(target, side_effect=OSError("interrupted page")):
            with pytest.raises(OSError, match="interrupted page"):
                insert_videos_into_tb([playlist("old", "revised"), playlist("new")], table, existing=index)
    assert writes.call_count == 1
    assert path.read_bytes() == before
    assert index == original_index
    assert sorted(p.name for p in tmp_path.iterdir()) == ["youtube_00.json"]
    assert insert_videos_into_tb([playlist("old", "revised"), playlist("new")], table, existing=index) == (True, 1)
    assert [row["title"] for row in table.all()] == ["revised", "new"]


def test_invalid_page_does_not_partially_update_existing_rows(tmp_path):
    db = open_tinydb_for_committee(0, tinydb_dir=tmp_path)
    table = db.table("youtube_videos_test")
    table.insert(parse_video_details(playlist("old")))
    path = tmp_path / "youtube_00.json"
    before = path.read_bytes()
    index = video_document_ids(table)
    with patch.object(db.storage, "write", wraps=db.storage.write) as writes:
        with pytest.raises(ValidationError):
            insert_videos_into_tb([playlist("old", "revised"), {"snippet": {}}], table, existing=index)
    assert writes.call_count == 0
    assert path.read_bytes() == before and index == {"old": [1]}


def test_page_is_durable_before_next_request_and_overlap_keeps_new_rows(tmp_path):
    db = open_tinydb_for_committee(0, tinydb_dir=tmp_path)
    obj = fetcher(db)
    table = db.table("youtube_videos_test")
    table.insert(parse_video_details(playlist("old")))
    path = tmp_path / "youtube_00.json"
    first = {"items": [playlist("old", "revised"), playlist("new")], "pageInfo": {"totalResults": 3}, "nextPageToken": "second"}
    def second():
        saved = json.loads(path.read_text())
        assert [row["title"] for row in saved["youtube_videos_test"].values()] == ["revised", "new"]
        assert saved["youtube_channels"]["1"]["uploads_scan_complete"] is False
        raise TimeoutError("later page failed")
    calls = iter((first, second))
    def execute():
        value = next(calls)
        return value() if callable(value) else value
    obj.youtube.playlistItems.return_value.list.return_value.execute.side_effect = execute
    with pytest.raises(TimeoutError, match="later page failed"):
        obj.get_all_channel_videos("test")
    assert [row["videoId"] for row in table.all()] == ["old", "new"]
    # Retry must replay its own overlap because the earlier scan is incomplete.
    obj.youtube.playlistItems.return_value.list.return_value.execute.side_effect = [first,
        {"items": [playlist("last")], "pageInfo": {"totalResults": 3}}]
    obj.get_all_channel_videos("test")
    assert [row["videoId"] for row in table.all()] == ["old", "new", "last"]
    assert obj.channels_tb.all()[0]["uploads_scan_complete"] is True
    # Once complete, an overlap page still inserts its new item before stopping.
    obj.youtube.playlistItems.return_value.list.return_value.execute.side_effect = [
        {"items": [playlist("old"), playlist("after-complete")], "pageInfo": {"totalResults": 4}, "nextPageToken": "unused"}]
    obj.get_all_channel_videos("test")
    assert [row["videoId"] for row in table.all()] == ["old", "new", "last", "after-complete"]


@pytest.mark.parametrize("force,expected", [(False, ["stale"]), (True, ["fresh", "stale"])])
def test_force_skips_discarded_search_but_refreshes_fresh_video(force, expected):
    obj = fetcher(TinyDB(storage=MemoryStorage))
    obj.force = force
    table = obj.tinydb.table("youtube_videos_test")
    table.insert_multiple([
        {"videoId": "fresh", "caption": True, "duration": 120, "metadata_version": 1,
         "details_checked_at": "2999-01-01T00:00:00+00:00", "publishedAt": "2025-01-04T00:00:00Z"},
        {"videoId": "stale", "publishedAt": "2025-01-04T00:00:00Z"},
    ])
    obj.youtube.videos.return_value.list.return_value.execute.return_value = {"items": []}
    with patch.object(table, "search", wraps=table.search) as searched:
        assert obj.update_video_details("test")
    assert searched.call_count == (0 if force else 1)
    assert obj.youtube.videos.return_value.list.call_args.kwargs["id"].split(",") == expected
