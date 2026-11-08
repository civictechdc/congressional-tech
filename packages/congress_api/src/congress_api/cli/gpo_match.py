"""Cli: gpo match."""

import argparse
import collections
import csv
import json
import logging
import tempfile
from pathlib import Path

from congress_shared.youtube_cache import decode_cache
from congress_shared.cli import add_global_args, configure_logging
from congress_shared.resources import DEFAULT_CHANNELS_CSV
from congress_shared.paths import (
    DEFAULT_OVERRIDES_FILE,
    DEFAULT_GPO_HEARINGS_FILE,
    DEFAULT_HEARING_VIDEOS_FILE,
)

from congress_api.matching.committees import codes_of
from congress_api.matching.gpo_decisions import COLUMNS, decide
from congress_api.matching.gpo_videos import EVENT_ID, dates_in_text, words
from congress_api.matching.meetings import scheduled_or_rescheduled
from congress_api.acquisition.public_release import PUBLIC_POINTER, release_meetings
from congress_api.parsers.media import youtube_video_id, senate_player_reference


def load_videos(tinydb_dir, channels):
    """Committee code -> list of video dicts from the weekly YouTube fetch."""
    by_code = collections.defaultdict(list)
    for i, row in enumerate(channels):
        path = Path(tinydb_dir) / f"youtube_{i:02d}.json"
        if not path.exists():
            continue
        with path.open() as stream:
            tables = json.load(stream)
        for handle, video in decode_cache(tables).videos():
            text = f"{video['title']} {video['description']}"
            by_code[row["systemCode"]].append({
                "videoId": video["videoId"], "channel": handle,
                "published": video["publishedAt"][:10], "title": video["title"], "words": words(video["title"]),
                "dates": dates_in_text(text), "event_ids": {a or b for a, b in EVENT_ID.findall(text)},
                "duration": video.get("duration"), "audio_only": "audio recording" in text.lower() or "audio only" in text.lower(),
            })
    return by_code


def load_meetings(release, *, work):
    """Parent committee code -> date -> meeting records, from an archive release.

    ``release`` is the public pointer or a local release directory. A missing,
    altered or meeting-less release raises ``ValueError``: without it every
    Congress.gov link and event-ID match silently disappears from the output.
    """
    out = collections.defaultdict(lambda: collections.defaultdict(list))
    for meeting in release_meetings(release, work=work, scope=scheduled_or_rescheduled):
        urls = [video.get("url", "") for video in (meeting.get("videos") or [])]
        record = {"eventId": meeting["eventId"], "title": meeting.get("title") or "", "words": words(meeting.get("title")),
                  "subcommittees": [c.get("name", "") for c in meeting.get("committees", []) if not c["systemCode"].endswith("00")],
                  "videos": [video for url in urls if (video := youtube_video_id(url))],
                  "offsite": [url for url in urls if senate_player_reference(url)]}
        for code in codes_of(meeting):
            out[code][meeting["date"][:10]].append(record)
    return out


def write_coverage(rows, channels, path):
    """Hearings per congress x committee x status, for dashboards and reports."""
    names = {channel["systemCode"]: channel["committee"] for channel in channels}
    counts = collections.Counter((row["congress"], row["committee_code"], row["status"]) for row in rows)
    with open(path, "w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["congress", "committee_code", "committee_name", "status", "hearings"])
        for (congress, code, status), count in sorted(counts.items(), key=lambda item: (int(item[0][0]), item[0][1], item[0][2])):
            writer.writerow([congress, code, names.get(code, ""), status, count])


def main(output_path, tinydb_dir, channels_csv_path, gpo_path, meetings, overrides_path, coverage_path, no_overrides=False):
    """``meetings`` is ``load_meetings``'s index."""
    with open(channels_csv_path) as stream:
        channels = list(csv.DictReader(stream))
    videos = load_videos(tinydb_dir, channels)
    with open(gpo_path) as stream:
        hearings = list(csv.DictReader(stream))
    overrides = {}
    if not no_overrides and Path(overrides_path).exists():
        with open(overrides_path) as stream:
            overrides = {row["package_id"]: row for row in csv.DictReader(stream)}
    rows = decide(hearings, videos, meetings, overrides, tracked_codes={channel["systemCode"] for channel in channels})
    with open(output_path, "w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    write_coverage(rows, channels, coverage_path)
    logging.info(f"Wrote {len(rows)} hearings to {output_path}: {dict(collections.Counter(row['status'] for row in rows))}")
    return rows


def parse_args_and_run():
    configure_logging()
    parser = argparse.ArgumentParser(description="Match GPO hearing transcripts to committee YouTube videos.")
    add_global_args(parser)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_HEARING_VIDEOS_FILE)
    parser.add_argument("--coverage-path", type=Path, default=None,
                        help="Per congress x committee summary (default: next to --output-path).")
    parser.add_argument("--channels-csv-path", type=Path, default=DEFAULT_CHANNELS_CSV)
    parser.add_argument("--gpo-path", type=Path, default=DEFAULT_GPO_HEARINGS_FILE)
    parser.add_argument("--release", default=PUBLIC_POINTER,
                        help="Archive release pointer URL or local release directory holding meetings.parquet.")
    parser.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES_FILE)
    parser.add_argument("--no-overrides", action="store_true", help="Automatic evidence only (for evaluating the matcher).")
    args = parser.parse_known_args()[0]
    coverage = args.coverage_path or Path(args.output_path).with_name("gpo_hearing_video_coverage.csv")
    with tempfile.TemporaryDirectory(prefix="gpo-match-release-") as work:
        try:
            meetings = load_meetings(args.release, work=Path(work) / "release")
        except ValueError as error:
            parser.exit(2, f"gpo-match: {error}\n")
    main(args.output_path, args.tinydb_dir, args.channels_csv_path, args.gpo_path, meetings,
         args.overrides, coverage, no_overrides=args.no_overrides)


if __name__ == "__main__":
    parse_args_and_run()
