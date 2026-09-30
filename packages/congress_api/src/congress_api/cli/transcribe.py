"""
Transcribe a committee proceeding into the shared transcript schema, with members and
witnesses named.

    hearing-transcribe --event-id 116xxx --out-dir ~/hearing-text/transcripts          # picks the meeting's recording
    hearing-transcribe --video-id 8V3OGbZOLB0 --event-id 116xxx --out-dir ...          # a specific YouTube recording
    hearing-transcribe --senate-url "https://www.senate.gov/isvp/?comm=epw&filename=epw120623" --event-id ...
    hearing-transcribe --gpo-package CHRG-118hhrg54254 --out-dir ...                    # the print, parsed into the same schema

Gemini 3.8 Flash transcribes the recording in 25-minute windows into named speaker turns: the
YouTube video itself (it reads the name plates and hears the chair's recognitions), or
uploaded audio chunks for senate.gov and local recordings. Measured on a 2023 Judiciary
hearing against its print: word error rate 8.7%, speakers right on 85% of words. See
gemini.py for why the windows are 25 minutes and why the dedicated transcription model
was dropped.

Writes <id>.json (the schema) and <id>.gpo.txt (the print's layout). Needs GEMINI_API_KEY;
YOUTUBE_API_KEY lets the video's length come from the Data API instead of yt-dlp, and --proxy
is passed to yt-dlp when YouTube asks for a sign-in.
New GovInfo HTML and Gemini responses are retained under source/ before parsing.
"""

import argparse
import csv
import logging
import re
import sys
from pathlib import Path

from congress_shared.globals import DEFAULT_GPO_HEARINGS_FILE, DEFAULT_MEETINGS_FILE

from congress_api.transcripts import context as metadata
from congress_api.transcripts.context import context_for_event
from congress_api.transcripts.generate import from_gpo, transcribe
from congress_api.transcripts.render import render_gpo


def parse_args_and_run():
    p = argparse.ArgumentParser(description="Transcribe a committee proceeding into the shared transcript schema.")
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--event-id", help="Congress.gov meeting event ID (gives the participants and, by default, the recording).")
    p.add_argument("--gpo-package", help="Parse this GPO print instead of transcribing (or, with a recording, use its metadata too).")
    p.add_argument("--video-id"); p.add_argument("--senate-url"); p.add_argument("--audio", help="A local audio or video file.")
    p.add_argument("--proxy", help="Proxy for yt-dlp when YouTube asks for a sign-in.")
    p.add_argument("--gpo-path", type=Path, default=DEFAULT_GPO_HEARINGS_FILE, help="gpo_hearings.csv (see gpo-fetch).")
    p.add_argument("--meetings", type=Path, default=DEFAULT_MEETINGS_FILE, help="congress_meetings.jsonl.gz (see congress-meetings).")
    a = p.parse_args()
    metadata.set_paths(str(a.gpo_path), str(a.meetings))
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(asctime)s : %(message)s")
    logging.getLogger("google_genai").setLevel(logging.WARNING); logging.getLogger("httpx").setLevel(logging.WARNING)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    if a.gpo_package and not (a.video_id or a.senate_url or a.audio or a.event_id):
        t = from_gpo(a.gpo_package, a.gpo_path, source_dir=a.out_dir / 'source'); stem = a.gpo_package
    else:
        if not (a.event_id or a.gpo_package):
            sys.exit("give --event-id or --gpo-package so the participants are known")
        row = {r["package_id"]: r for r in csv.DictReader(open(a.gpo_path))}.get(a.gpo_package or "", {})
        ctx = context_for_event(a.event_id or row.get("event_id", ""), package_id=a.gpo_package or "")
        video_id = a.video_id or (ctx.youtube_ids[0] if ctx.youtube_ids and not a.senate_url and not a.audio else "")
        senate_url = a.senate_url or ("" if video_id or a.audio else (ctx.senate_urls[0] if ctx.senate_urls else ""))
        if not (video_id or senate_url or a.audio):
            sys.exit("no recording known for this meeting; pass --video-id, --senate-url or --audio")
        t = transcribe(ctx, a.out_dir, video_id=video_id, senate_url=senate_url, local=a.audio or "", proxy=a.proxy)
        stem = video_id or (re.search(r"filename=([^&]+)", senate_url).group(1) if senate_url else Path(a.audio).stem)
    (a.out_dir / f"{stem}.json").write_text(t.to_json(), encoding="utf-8")
    (a.out_dir / f"{stem}.gpo.txt").write_text(render_gpo(t), encoding="utf-8")
    named = sum(1 for p in t.participants.values() if p.role != "unknown" and p.name != "Unknown")
    logging.info(f"wrote {a.out_dir / stem}.json: {len(t.turns)} turns, {named} named participants")


if __name__ == "__main__":
    parse_args_and_run()
