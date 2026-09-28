"""
Download YouTube caption tracks as plain text, for hearings with no printed transcript.

    youtube-captions --out-dir ~/hearing-text/youtube --video-ids dQw4w9WgXcQ ...
    youtube-captions --out-dir ~/hearing-text/youtube --ids-file videos.txt

Retains downloaded WebVTT tracks in tracks/ and writes <videoId>.txt per video (the uploader's English captions when there are any,
otherwise YouTube's automatic ones) and appends to <out-dir>/captions_index.csv:
video_id, kind (manual | auto | none), characters. A current capture receipt and
retained timing track allow a recording to be skipped. Legacy entries are rechecked
when requested; an old negative row does not prove a successful caption check. Automatic captions are unpunctuated
speech recognition: good enough for search and for finding who said what when, not a
transcript of record.

Uses yt-dlp, which fetches the caption track without downloading the video.
"""
import argparse
import csv
from datetime import datetime, timezone
import json
import logging
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yt_dlp

from congress_shared.webvtt import cue_lines

INDEX = "captions_index.csv"
CAPTURE_VERSION = "2"
RECEIPTS = "caption_receipts"


def vtt_to_text(vtt: str) -> str:
    """Plain text from a WebVTT file. YouTube's automatic captions repeat each line as it
    scrolls (with per-word timing tags), so consecutive duplicates are dropped."""
    lines, last = [], None
    for cue in cue_lines(vtt):
        for line in cue:
            if line != last:
                lines.append(line)
                last = line
    return "\n".join(lines) + "\n"


YDL_OPTS: dict = {}  # extra yt-dlp options from the command line (proxy, sleep)


def fetch_one(video_id: str, out_dir: Path) -> tuple[str, str, int]:
    """Download the English caption track for one video. Returns (video_id, kind, characters);
    kind is manual, auto, none (no English track) or error (blocked or failed; retry later)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    def result(kind, characters=0, *, selected=None, tracks=(), error=None):
        receipt = {'capture_version': CAPTURE_VERSION, 'video_id': video_id, 'kind': kind,
                   'characters': characters, 'observed_at': datetime.now(timezone.utc).isoformat(),
                   'selected_track': selected, 'track_files': list(tracks),
                   'scope': {'kind': 'youtube_english_webvtt',
                             'video_url': f'https://www.youtube.com/watch?v={video_id}',
                             'includes_manual': True, 'includes_automatic': True}}
        if error:
            receipt['error'] = error
        directory = out_dir / RECEIPTS
        directory.mkdir(exist_ok=True)
        path = directory / f'{video_id}.json'
        if kind == 'error' and path.exists():
            previous = json.loads(path.read_text())
            successful = previous.get('last_successful') if previous.get('kind') == 'error' else previous
            if successful and successful.get('kind') in ('manual', 'auto', 'none'):
                receipt['last_successful'] = {k: v for k, v in successful.items() if k != 'last_successful'}
        temporary = path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
        temporary.replace(path)
        return video_id, kind, characters
    with tempfile.TemporaryDirectory() as tmp:
        opts = {"skip_download": True, "writesubtitles": True, "writeautomaticsub": True, "subtitleslangs": ["en.*"],
                "subtitlesformat": "vtt", "outtmpl": f"{tmp}/%(id)s", "quiet": True, "no_warnings": True, "logger": logging.getLogger("yt_dlp"), **YDL_OPTS}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
        except yt_dlp.utils.DownloadError as e:
            msg = str(e).splitlines()[-1]
            kind = "error"  # A failed request never establishes absence of captions.
            logging.warning(f"{video_id}: {msg[:120]}")
            return result(kind, error=msg[:500])  # failures never establish a negative index row
        files = sorted(Path(tmp).glob(f"{video_id}*.vtt"))
        manual = {k for k in (info.get("subtitles") or {}) if k == 'en' or k.startswith('en-')}
        automatic = {k for k in (info.get("automatic_captions") or {}) if k == 'en' or k.startswith('en-')}
        if not files:
            return result("error" if manual or automatic else "none",
                          error="Declared English track was not downloaded" if manual or automatic else None)
        language = lambda path: path.name[len(video_id) + 1:-4]
        chosen = min(files, key=lambda path: (language(path) not in manual, language(path) != 'en', path.name))
        kind = "manual" if language(chosen) in manual else "auto"
        out_dir = Path(out_dir)
        tracks = out_dir / 'tracks'
        tracks.mkdir(parents=True, exist_ok=True)
        try:
            text = vtt_to_text(chosen.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError) as error:
            logging.warning(f"{video_id}: invalid caption track: {error}")
            return result("error", error=str(error))
        # A failed normalization must not replace the last successful timing track.
        for path in files:
            (tracks / path.name).write_bytes(path.read_bytes())
        (out_dir / f"{video_id}.txt").write_text(text, encoding="utf-8")
        return result(kind, len(text), selected=chosen.name, tracks=[p.name for p in files])


def current_capture(out_dir, video_id):
    path = Path(out_dir) / RECEIPTS / f'{video_id}.json'
    if not path.exists():
        return None
    receipt = json.loads(path.read_text())
    if receipt.get('capture_version') != CAPTURE_VERSION or receipt.get('kind') not in ('manual', 'auto', 'none'):
        return None
    if receipt['kind'] != 'none' and (not receipt.get('selected_track')
        or not (Path(out_dir) / 'tracks' / receipt['selected_track']).exists()
        or not (Path(out_dir) / f'{video_id}.txt').exists()
        or not all((Path(out_dir) / 'tracks' / name).exists() for name in receipt.get('track_files') or [])):
        return None
    return receipt


def main(out_dir, video_ids, nthreads=3):
    out_dir = Path(out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    index = out_dir / INDEX
    saved = {r['video_id']: r for r in csv.DictReader(index.open())} if index.exists() else {}
    todo = []
    for video_id in dict.fromkeys(video_ids):
        receipt = current_capture(out_dir, video_id)
        if receipt:
            saved[video_id] = {'video_id': video_id, 'kind': receipt['kind'], 'characters': receipt['characters']}
        else:
            todo.append(video_id)
    logging.info(f"{len(todo)} videos need caption capture, including legacy rows without retained timing")
    counts = {"manual": 0, "auto": 0, "none": 0, "error": 0}
    try:
        with ThreadPoolExecutor(nthreads) as pool:
            for n, (vid, kind, chars) in enumerate(pool.map(lambda v: fetch_one(v, out_dir), todo), 1):
                if kind != "error":
                    saved[vid] = {'video_id': vid, 'kind': kind, 'characters': chars}
                counts[kind] += 1
                if n % 50 == 0:
                    logging.info(f"{n}/{len(todo)}: {counts}")
    finally:
        temporary = index.with_suffix('.csv.tmp')
        with temporary.open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=['video_id', 'kind', 'characters'])
            writer.writeheader()
            writer.writerows(saved.values())
        temporary.replace(index)
    logging.info(f"done: {counts}" + (" (errors are retried on the next run)" if counts["error"] else ""))
    return counts


def parse_args_and_run():
    parser = argparse.ArgumentParser(description="Download YouTube caption tracks as plain text.")
    parser.add_argument("--out-dir", required=True, help="Folder for <videoId>.txt files and the index.")
    parser.add_argument("--video-ids", nargs="*", default=[])
    parser.add_argument("--ids-file", type=Path, help="Text file with one video ID per line.")
    parser.add_argument("--nthreads", type=int, default=3)
    parser.add_argument("--proxy", help="Proxy URL for yt-dlp, e.g. Zyte's proxy mode when YouTube asks for a sign-in.")
    parser.add_argument("--sleep", type=float, default=0, help="Seconds to pause between requests (yt-dlp sleep_interval).")
    args = parser.parse_args()
    if args.proxy:
        YDL_OPTS.update(proxy=args.proxy, nocheckcertificate=True)
    if args.sleep:
        YDL_OPTS.update(sleep_interval_requests=args.sleep)
    ids = list(args.video_ids) + ([l.strip() for l in args.ids_file.read_text().splitlines() if l.strip()] if args.ids_file else [])
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(asctime)s : %(message)s")
    logging.getLogger("yt_dlp").setLevel(logging.ERROR)
    if not ids:
        sys.exit("No video IDs given.")
    main(args.out_dir, ids, args.nthreads)


if __name__ == "__main__":
    parse_args_and_run()
