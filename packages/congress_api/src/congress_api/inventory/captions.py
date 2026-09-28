"""Caption availability and one-time Senate committee/day probes, without media.

September 2026 measurement: 67,244 cached YouTube videos; 3,146 caption=true,
64,092 false, six unknown. Of 4,376 manual caption probes, 2,433 false-flag
videos had automatic captions and 1,649 had none. Duration does not separate
them (2,112 auto and 1,462 none are 20 minutes to six hours). Preserve positive
AND negative observations, then use caption=true for unprobed videos; false is
unknown, never evidence that automatic captions cannot exist. The historical
video_no_captions label means no confirmed text. Caption downloading stays manual.

The Senate index has 719 WebVTT and 667 absent entries. Among 2023 filenames,
all 39 September-December entries have WebVTT, all 83 January-July entries do
not. Use August 2023 as the unobserved-file boundary for recognized studio
committees; saved observations override it, including older files served on the
newer player. Live master playlists confirmed subtitles for all 29 additional
meetings this rule identifies; three comm=xxxx placeholders were excluded.
This is an availability estimate, not a claim to have downloaded captions.

The research archive cache has 3,268 committee-days. Import its positive and
negative answers. New days probe four studio names, archive then live (at most
eight HEADs), and are saved only after every response succeeds or is 404. Wait
seven days after a new meeting before a once-only probe, so a scheduled future
meeting cannot acquire a permanent negative answer. Transient failures raise.
"""
import datetime as dt
import json
import re
from pathlib import Path

from congress_api import http
from congress_api.inventory.common import read_csv
from congress_api.senate.isvp import LIVE_ID, archive_url, live_url, parse_player_url, player_url


def import_observations(state, seed_cache=None, youtube_index=None, senate_index=None):
    for source, index, key in (("youtube", youtube_index, "video_id"), ("senate", senate_index, "filename")):
        path = index or (seed_cache / source / "captions_index.csv" if seed_cache else None)
        if path:
            path = Path(path)
            if path.exists():
                state.setdefault(source, {}).update({r[key]: r["kind"] for r in read_csv(path)})
            # Receipts contain scope/time and file pointers, never caption bytes.
            # Include failed-only checks even when they have no successful CSV row.
            for receipt_path in sorted((path.parent / 'caption_receipts').glob('*.json')):
                receipt = json.loads(receipt_path.read_text())
                native_id = receipt.get(key)
                if not isinstance(native_id, str) or not native_id:
                    continue
                state.setdefault('caption_observations', {}).setdefault(source, {})[native_id] = receipt
    if seed_cache and not state.get("probes"):
        path = seed_cache / "senate/probe_cache.json"
        if path.exists():
            state["probes"] = {key: {"urls": urls, "checked": dt.datetime.fromtimestamp(path.stat().st_mtime, dt.UTC).date().isoformat(),
                                     "source": "research HEAD cache"} for key, urls in json.loads(path.read_text()).items()}


def senate_caption(url, observations):
    player = parse_player_url(url)
    if not player:
        return False
    filename = player[1]
    if filename in observations:
        return observations[filename] == "webvtt"
    if player[0] not in LIVE_ID:
        return False
    match = re.search(r"(\d{6})p?$", filename)
    try:
        day = dt.datetime.strptime(match[1], "%m%d%y").date() if match else None
    except ValueError:
        return False
    return day is not None and dt.date(2023, 8, 1) <= day <= dt.datetime.now(dt.UTC).date()


def text_source(row, youtube, senate, flags):
    if row["gpo_packages"]:
        return "gpo"
    if row["committee_transcripts"]:
        return "committee_transcript"
    if any(youtube[v] in ("manual", "auto") if v in youtube else flags.get(v) is True for v in row["youtube_ids"]):
        return "youtube_captions"
    if any(senate_caption(url, senate) for url in row["senate_urls"]):
        return "senate_captions"
    return "video_no_captions" if row["youtube_ids"] or row["senate_urls"] or row["other_recordings"] else "no_video"


def probe_day(comm, day):
    date = dt.date.fromisoformat(day)
    found = []
    for filename in (f"{comm}{date:%m%d%y}", f"{comm}A{date:%m%d%y}", f"{comm}B{date:%m%d%y}", f"{comm}{date:%m%d%y}p"):
        for url in (archive_url(comm, filename), live_url(comm, filename)):
            response = http.get_with_retry(None, url, method="HEAD", allowed=(200, 404))
            if response.status_code == 200:
                found.append(player_url(comm, filename))
                break
    return found
