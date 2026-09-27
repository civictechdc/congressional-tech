"""
Download YouTube caption tracks as plain text, for hearings with no printed transcript.

    youtube-captions --out-dir ~/hearing-text/youtube --video-ids dQw4w9WgXcQ ...
    youtube-captions --out-dir ~/hearing-text/youtube --ids-file videos.txt

Writes one <videoId>.txt per video (the uploader's English captions when there are any,
otherwise YouTube's automatic ones) and appends to <out-dir>/captions_index.csv:
video_id, kind (manual | auto | none), characters. Videos already in the index are
skipped, so the command can be re-run to top up. Automatic captions are unpunctuated
speech recognition: good enough for search and for finding who said what when, not a
transcript of record.

Uses yt-dlp, which fetches the caption track without downloading the video.
"""
import argparse
import csv
import logging
import re
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yt_dlp

INDEX = "captions_index.csv"


def vtt_to_text(vtt: str) -> str:
    """Plain text from a WebVTT file. YouTube's automatic captions repeat each line as it
    scrolls (with per-word timing tags), so consecutive duplicates are dropped."""
    lines, last = [], None
    for raw in vtt.splitlines():
        if not raw.strip() or raw.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")) or "-->" in raw or raw.strip().isdigit():
            continue
        line = re.sub(r"<[^>]+>", "", raw).replace("&nbsp;", " ").strip()
        if line and line != last:
            lines.append(line)
            last = line
    return "\n".join(lines) + "\n"


YDL_OPTS: dict = {}  # extra yt-dlp options from the command line (proxy, sleep)


def fetch_one(video_id: str, out_dir: Path) -> tuple[str, str, int]:
    """Download the English caption track for one video. Returns (video_id, kind, characters);
    kind is manual, auto, none (no English track) or error (blocked or failed; retry later)."""
    with tempfile.TemporaryDirectory() as tmp:
        opts = {"skip_download": True, "writesubtitles": True, "writeautomaticsub": True, "subtitleslangs": ["en", "en-US", "en-orig"],
                "subtitlesformat": "vtt", "outtmpl": f"{tmp}/%(id)s", "quiet": True, "no_warnings": True, "logger": logging.getLogger("yt_dlp"), **YDL_OPTS}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
        except yt_dlp.utils.DownloadError as e:
            msg = str(e).splitlines()[-1]
            kind = "error" if ("not a bot" in msg or "429" in msg or "HTTP Error 5" in msg) else "none"
            logging.warning(f"{video_id}: {msg[:120]}")
            return video_id, kind, 0  # errors are not written to the index, so a rerun retries them
        files = sorted(Path(tmp).glob(f"{video_id}*.vtt"))
        if not files:
            return video_id, "none", 0
        manual = {k for k in (info.get("subtitles") or {}) if k.startswith("en")}
        kind = "manual" if manual else "auto"
        text = vtt_to_text(files[0].read_text(encoding="utf-8", errors="replace"))
        (out_dir / f"{video_id}.txt").write_text(text, encoding="utf-8")
        return video_id, kind, len(text)


def main(out_dir, video_ids, nthreads=3):
    out_dir = Path(out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    index = out_dir / INDEX
    done = {r["video_id"] for r in csv.DictReader(open(index))} if index.exists() else set()
    todo = [v for v in dict.fromkeys(video_ids) if v not in done]
    logging.info(f"{len(todo)} videos to fetch ({len(done)} already in {index})")
    counts = {"manual": 0, "auto": 0, "none": 0, "error": 0}
    with open(index, "a", newline="") as f:
        w = csv.writer(f)
        if not done:
            w.writerow(["video_id", "kind", "characters"])
        with ThreadPoolExecutor(nthreads) as pool:
            for n, (vid, kind, chars) in enumerate(pool.map(lambda v: fetch_one(v, out_dir), todo), 1):
                if kind != "error":
                    w.writerow([vid, kind, chars]); f.flush()
                counts[kind] += 1
                if n % 50 == 0:
                    logging.info(f"{n}/{len(todo)}: {counts}")
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
