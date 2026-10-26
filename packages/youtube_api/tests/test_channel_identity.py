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
    assert get_channel_id_overrides()[HANDLE] == CHANNEL_ID


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
        with pytest.raises(ValueError, match="does not match expected channel ID"):
            obj.get_channel(HANDLE)
    else:
        assert obj.get_channel(HANDLE) is None
    assert obj.tinydb.storage.read() == before
    obj.youtube.channels.return_value.list.assert_called_once_with(
        part=["snippet", "contentDetails"], id=CHANNEL_ID)


def test_unpinned_channel_uses_existing_handle_lookup():
    obj = configured_fetcher()
    obj.youtube.channels.return_value.list.return_value.execute.return_value = {"items": []}
    assert obj.get_channel("@new-channel") is None
    obj.youtube.channels.return_value.list.assert_called_once_with(
        part=["snippet", "contentDetails"], forHandle="@new-channel")


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
        {"part": ["snippet", "contentDetails"], "id": "UCY08wEbJ8fztRofQ9eZs0-g"},
        {"part": ["snippet", "contentDetails"], "id": CHANNEL_ID}]
    assert api.playlistItems.return_value.list.call_count == 2
    assert sorted(path.name for path in tmp_path.iterdir()) == ["youtube_11.json"]
    saved = json.loads((tmp_path / "youtube_11.json").read_text())
    assert [row["handle"] for row in saved["youtube_channels"].values()] == ["@NaturalResourcesGOP", HANDLE]


def test_new_channel_discovers_once_then_refreshes_by_retained_id():
    obj = configured_fetcher()
    obj.youtube.channels.return_value.list.return_value.execute.return_value = {"items": [channel_item()]}
    assert obj.get_channel("@new-channel") == channel_item()
    assert obj.get_channel("@new-channel") == channel_item()
    assert [call.kwargs for call in obj.youtube.channels.return_value.list.call_args_list] == [
        {"part": ["snippet", "contentDetails"], "forHandle": "@new-channel"},
        {"part": ["snippet", "contentDetails"], "id": CHANNEL_ID}]
    assert len(obj.channels_tb) == 1
    assert obj.channels_tb.all()[0]["handle"] == "@new-channel"


@pytest.mark.parametrize("row", [
    {"channelId": CHANNEL_ID},
    {"upstream": {"item": {"id": CHANNEL_ID}}},
])
def test_retained_id_is_used_without_configuration_and_preserved_on_absence(row):
    obj = configured_fetcher()
    obj.channels_tb.insert({"handle": "@old-handle", "uploads": UPLOADS, **row})
    before = deepcopy(obj.tinydb.storage.read())
    obj.youtube.channels.return_value.list.return_value.execute.return_value = {"items": []}
    assert obj.get_channel("@old-handle") is None
    obj.youtube.channels.return_value.list.assert_called_once_with(
        part=["snippet", "contentDetails"], id=CHANNEL_ID)
    assert obj.tinydb.storage.read() == before


@pytest.mark.parametrize("row", [
    {"channelId": "UCY08wEbJ8fztRofQ9eZs0-g"},
    {"channelId": CHANNEL_ID, "upstream": {"item": {"id": "UCY08wEbJ8fztRofQ9eZs0-g"}}},
])
def test_conflicting_retained_identity_blocks_lookup_without_changing_history(row):
    obj = configured_fetcher()
    obj.channels_tb.insert({"handle": HANDLE, "uploads": UPLOADS, **row})
    before = deepcopy(obj.tinydb.storage.read())
    with pytest.raises(ValueError, match="Conflicting retained/configured"):
        obj.get_channel(HANDLE)
    obj.youtube.channels.assert_not_called()
    assert obj.tinydb.storage.read() == before


@pytest.mark.parametrize("mapping", [
    [], {"@other-row": CHANNEL_ID}, {HANDLE: "not-a-channel-id"}, {HANDLE: None},
])
def test_invalid_configured_identity_fails_before_fetch(tmp_path, mapping):
    import csv
    import json
    path = tmp_path / "channels.csv"
    with path.open("w", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(["committee", "systemCode", "handle", "secondary", "channel_ids"])
        writer.writerow(["Natural Resources", "hsii00", "@NaturalResourcesGOP", HANDLE, json.dumps(mapping)])
    with pytest.raises(ValueError):
        get_channel_id_overrides(path)


def test_all_configured_channels_fetch_by_verified_id_and_keep_literal_handles(tmp_path, monkeypatch):
    import importlib
    import json
    from pathlib import Path
    from youtube_api.tables import get_all_committee_handles

    main_module = importlib.import_module("youtube_api.fetch.main")
    fetch_module = importlib.import_module("youtube_api.fetch.youtube_event_fetcher")
    evidence = json.loads((Path(__file__).resolve().parents[3] / "docs/experiments/youtube-channel-ids-20261026.json").read_text())
    recorded = {entry["handle"]: entry["channel_id"] for entry in evidence["entries"]}
    handles = get_all_committee_handles(include_member_channels=True)
    configured = get_channel_id_overrides()
    assert len(recorded) == len(configured) == 119
    assert recorded == configured
    assert set(configured) == {handle for committee in handles for handle in committee}

    api = MagicMock()
    def lookup(**kwargs):
        assert "forHandle" not in kwargs
        request = MagicMock()
        request.execute.return_value = {"items": [channel_item(kwargs["id"])]}
        return request
    api.channels.return_value.list.side_effect = lookup
    api.playlistItems.return_value.list.return_value.execute.return_value = {
        "items": [], "pageInfo": {"totalResults": 0}}
    monkeypatch.setattr(main_module, "load_youtube_api_key", lambda: "test-only")
    monkeypatch.setattr(fetch_module, "build", lambda *args, **kwargs: api)
    main_module.main(tmp_path, None, None, DEFAULT_CHANNELS_CSV)

    assert api.channels.return_value.list.call_count == 119
    assert len(list(tmp_path.iterdir())) == 52
    for index, expected in enumerate(handles):
        saved = json.loads((tmp_path / f"youtube_{index:02d}.json").read_text())
        channels = list(saved["youtube_channels"].values())
        assert [row["handle"] for row in channels] == expected
        assert [row["channelId"] for row in channels] == [configured[handle] for handle in expected]
        assert all(name in {"youtube_channels", "_default"} or name.removeprefix("youtube_videos_") in expected for name in saved)
