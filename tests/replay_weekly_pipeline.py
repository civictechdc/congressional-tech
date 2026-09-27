"""Run the workflow's eight commands, in order, against a copied snapshot.

Upstream Data API responses replay a no-change week from the supplied caches;
no metered calls occur. The three new commands run normally against their saved
state, with networking forbidden. Separate bounded live checks qualify the
transports. Publication scripts are deliberately not executed.
"""
import argparse
import importlib.metadata
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from congress_api.inventory.common import read_csv


def main(root):
    pipeline, out = root / "pipeline-data", root / "outputs"
    channels = Path("packages/congress_shared/src/congress_shared/youtube/youtube-accounts.csv")
    playlists, videos = {}, {}
    for path in (pipeline / "youtube").glob("*.json"):
        tables = json.loads(path.read_text())
        for channel in tables.get("youtube_channels", {}).values():
            rows = list(tables.get("youtube_videos_" + channel["handle"], {}).values())
            playlists[channel["uploads"]] = sorted(rows, key=lambda v: v["publishedAt"], reverse=True)
            videos.update({v["videoId"]: v for v in rows})
    calls = []
    def api_list(kind, **kwargs):
        calls.append(kind)
        if kind == "playlistItems":
            rows = playlists[kwargs["playlistId"]]
            data = {"pageInfo": {"totalResults": len(rows)}, "items": [{"snippet": {**v, "resourceId": {"videoId": v["videoId"]}}} for v in rows[:1]]}
        elif kind == "videos":
            data = {"items": [{"id": key, "contentDetails": {"caption": str(videos[key]["caption"]).lower(), "duration": f"PT{int(videos[key]['duration'] or 0)}S"}}
                              for key in kwargs["id"].split(",") if key in videos and videos[key].get("caption") is not None]}
        else:
            raise AssertionError("The copied snapshot lacks channel metadata")
        return SimpleNamespace(execute=lambda: data)
    youtube = SimpleNamespace(**{kind: (lambda k=kind: SimpleNamespace(list=lambda **kw: api_list(k, **kw))) for kind in ("playlistItems", "videos", "channels")})
    def no_network(*args, **kwargs):
        raise AssertionError("Unexpected live request in workflow replay")
    entries = {e.name: e for e in importlib.metadata.entry_points(group="console_scripts")}
    steps = [
        ("youtube-fetch", ["--tinydb_dir", pipeline / "youtube", "--channels-csv-path", channels]),
        ("youtube-analyze", ["--tinydb_dir", pipeline / "youtube", "--channels-csv-path", channels, "--output-path", out / "youtube_event_id_report.csv", "--nthreads", "1"]),
        ("gpo-fetch", ["--output-path", out / "gpo_hearings.csv"]),
        ("congress-meetings", ["--output-path", pipeline / "congress_meetings.jsonl.gz"]),
        ("gpo-match", ["--tinydb_dir", pipeline / "youtube", "--channels-csv-path", channels, "--gpo-path", out / "gpo_hearings.csv", "--meetings", pipeline / "congress_meetings.jsonl.gz", "--overrides", out / "hearing_video_overrides.csv", "--output-path", out / "gpo_hearing_videos.csv"]),
    ]
    common = ["--meetings", pipeline / "congress_meetings.jsonl.gz", "--state-dir", pipeline / "meeting-inventory", "--output-dir", out]
    steps += [("house-meeting-records", common + ["--gpo-path", out / "gpo_hearings.csv"]),
              ("senate-meeting-records", common),
              ("meeting-inventory", common + ["--gpo-path", out / "gpo_hearings.csv", "--videos-path", out / "gpo_hearing_videos.csv", "--tinydb_dir", pipeline / "youtube", "--channels-csv-path", channels, "--recordings", "apps/committee_youtube/data/meeting_recordings_found.csv"])]
    timings = {}
    with patch("youtube_api.fetch.youtube_event_fetcher.build", return_value=youtube), \
         patch("youtube_api.fetch.main.load_youtube_api_key", return_value="offline"), \
         patch("congress_api.gpo.fetch.load_congress_api_key", return_value="offline"), \
         patch("congress_api.gpo.fetch.list_collection", return_value=[]), \
         patch("congress_api.meetings.load_congress_api_key", return_value="offline"), \
         patch("congress_api.meetings.get", return_value={"committeeMeetings": []}), \
         patch("requests.sessions.Session.request", side_effect=no_network):
        for command, args in steps:
            started = time.monotonic()
            with patch.object(sys, "argv", [command, *map(str, args)]):
                entries[command].load()()
            timings[command] = round(time.monotonic() - started, 2)
    result = {"step_seconds": timings, "youtube_api_responses_replayed": len(calls), "external_requests": 0,
              "snapshot_bytes": sum(p.stat().st_size for p in pipeline.rglob("*") if p.is_file())}
    (root / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(result)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path)
    main(p.parse_args().root)
