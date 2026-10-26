"""Stable channel lookup must keep the literal handle used by retained tables."""
from copy import deepcopy
from unittest.mock import MagicMock

import pytest
from tinydb import TinyDB
from tinydb.storages import MemoryStorage

from congress_shared.resources import DEFAULT_CHANNELS_CSV
from youtube_api.fetch.youtube_event_fetcher import YoutubeEventFetcher
from youtube_api.tables import get_channel_id_overrides, map_system_code_committee_handles

HANDLE = "@NRDems"
CHANNEL_ID = "UCB6LGE5-_i-xxtZxk1_SeTg"
UPLOADS = "UUB6LGE5-_i-xxtZxk1_SeTg"


def configured_fetcher():
    obj = object.__new__(YoutubeEventFetcher)
    obj.tinydb = TinyDB(storage=MemoryStorage)
    obj.channels_tb = obj.tinydb.table("youtube_channels")
    obj.channel_ids = get_channel_id_overrides(DEFAULT_CHANNELS_CSV)
    obj.youtube = MagicMock()
    return obj


def channel_item(channel_id=CHANNEL_ID):
    return {"id": channel_id, "snippet": {"title": "House Natural Resources Committee Democrats"},
            "contentDetails": {"relatedPlaylists": {"uploads": UPLOADS}}}


def test_natural_resources_pin_preserves_configured_handles_and_row_order():
    committees = map_system_code_committee_handles()
    assert list(committees).index("hsii00") == 11
    assert committees["hsii00"]["handles"] == ["@NaturalResourcesGOP", HANDLE]
    assert get_channel_id_overrides() == {HANDLE: CHANNEL_ID}


def test_id_lookup_refreshes_existing_channel_and_keeps_video_history():
    obj = configured_fetcher()
    obj.channels_tb.insert({"handle": HANDLE, "uploads": UPLOADS, "uploads_scan_complete": True})
    videos = obj.tinydb.table(f"youtube_videos_{HANDLE}")
    old_video = {"videoId": "retained", "title": "Historical hearing", "upstream": {"keep": True}}
    videos.insert(old_video)
    obj.youtube.channels.return_value.list.return_value.execute.return_value = {"items": [channel_item()]}

    assert obj.get_channel(HANDLE) == channel_item()
    obj.youtube.channels.return_value.list.assert_called_once_with(
        part=["snippet", "contentDetails"], id=CHANNEL_ID)
    assert len(obj.channels_tb) == 1
    assert obj.channels_tb.all()[0]["handle"] == HANDLE
    assert obj.channels_tb.all()[0]["channelId"] == CHANNEL_ID
    assert obj.channels_tb.all()[0]["uploads_scan_complete"] is True
    assert videos.all() == [old_video]
    assert f"youtube_videos_{CHANNEL_ID}" not in obj.tinydb.tables()


@pytest.mark.parametrize("response", [{"items": []}, {"items": [channel_item("UC-unexpected")]}])
def test_failed_pinned_lookup_preserves_cache_without_handle_fallback(response):
    obj = configured_fetcher()
    obj.channels_tb.insert({"handle": HANDLE, "uploads": UPLOADS})
    obj.tinydb.table(f"youtube_videos_{HANDLE}").insert({"videoId": "retained"})
    before = deepcopy(obj.tinydb.storage.read())
    obj.youtube.channels.return_value.list.return_value.execute.return_value = response
    if response["items"]:
        with pytest.raises(ValueError, match="does not match configured channel ID"):
            obj.get_channel(HANDLE)
    else:
        assert obj.get_channel(HANDLE) is None
    assert obj.tinydb.storage.read() == before
    obj.youtube.channels.return_value.list.assert_called_once_with(
        part=["snippet", "contentDetails"], id=CHANNEL_ID)


def test_unpinned_channel_uses_existing_handle_lookup():
    obj = configured_fetcher()
    obj.youtube.channels.return_value.list.return_value.execute.return_value = {"items": []}
    assert obj.get_channel("@NaturalResourcesGOP") is None
    obj.youtube.channels.return_value.list.assert_called_once_with(
        part=["snippet", "contentDetails"], forHandle="@NaturalResourcesGOP")


def test_custom_csv_without_id_column_keeps_handle_lookup_configuration(tmp_path):
    path = tmp_path / "channels.csv"
    path.write_text("committee,systemCode,handle,secondary,member_channels\nNatural Resources,hsii00,@NaturalResourcesGOP,@NRDems,\n")
    assert get_channel_id_overrides(path) == {}


def test_selected_committee_fetch_loads_pin_and_uses_only_its_two_channels(tmp_path, monkeypatch):
    import importlib
    import json

    main_module = importlib.import_module("youtube_api.fetch.main")
    fetch_module = importlib.import_module("youtube_api.fetch.youtube_event_fetcher")
    api = MagicMock()
    gop = channel_item("UCY08wEbJ8fztRofQ9eZs0-g")
    gop["contentDetails"]["relatedPlaylists"]["uploads"] = "UUY08wEbJ8fztRofQ9eZs0-g"
    api.channels.return_value.list.return_value.execute.side_effect = [
        {"items": [gop]}, {"items": [channel_item()]}]
    api.playlistItems.return_value.list.return_value.execute.return_value = {
        "items": [], "pageInfo": {"totalResults": 0}}
    monkeypatch.setattr(main_module, "load_youtube_api_key", lambda: "test-only")
    monkeypatch.setattr(fetch_module, "build", lambda *args, **kwargs: api)

    main_module.main(tmp_path, "Natural Resources", None, DEFAULT_CHANNELS_CSV)

    assert [call.kwargs for call in api.channels.return_value.list.call_args_list] == [
        {"part": ["snippet", "contentDetails"], "forHandle": "@NaturalResourcesGOP"},
        {"part": ["snippet", "contentDetails"], "id": CHANNEL_ID}]
    assert api.playlistItems.return_value.list.call_count == 2
    assert sorted(path.name for path in tmp_path.iterdir()) == ["youtube_11.json"]
    saved = json.loads((tmp_path / "youtube_11.json").read_text())
    assert [row["handle"] for row in saved["youtube_channels"].values()] == ["@NaturalResourcesGOP", HANDLE]
