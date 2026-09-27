"""
Download the captions of Senate hearing recordings from the Senate's own player, as plain text.

    senate-captions --out-dir ~/hearing-text/senate --urls "https://www.senate.gov/isvp/?comm=epw&filename=epw120623" ...
    senate-captions --out-dir ~/hearing-text/senate --urls-file links.txt

Recordings since about mid-2023 carry an English WebVTT subtitle track (the live path in
`isvp.py`); its segments are fetched concurrently and joined into <filename>.txt. Older
recordings (the archive path) have captions only inside the video stream, which this tool
doesn't decode; they are recorded as `none`. Appends to <out-dir>/captions_index.csv:
filename, comm, kind (webvtt | none), characters. Recordings already in the index are skipped.
"""
import argparse
import csv
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from congress_api.senate.isvp import STREAM, live_url, parse_player_url

INDEX = "captions_index.csv"
HDR = {"User-Agent": "Mozilla/5.0"}
sess = requests.Session()
sess.mount("https://", requests.adapters.HTTPAdapter(pool_maxsize=32))


def get(url: str, attempts: int = 3) -> str:
    for i in range(attempts):
        try:
            r = sess.get(url, headers=HDR, timeout=30)
            if r.status_code == 200:
                return r.text
            if r.status_code == 404:
                return ""
        except requests.RequestException:
            pass
    return ""


def cues(vtt: str) -> list[list[str]]:
    """Each cue's lines, tags stripped."""
    out, cur = [], []
    for raw in vtt.splitlines() + [""]:
        if raw.strip() and not raw.startswith(("WEBVTT", "X-TIMESTAMP-MAP", "NOTE")) and "-->" not in raw:
            line = re.sub(r"<[^>]+>", "", raw).strip()
            if line:
                cur.append(line)
        elif cur:
            out.append(cur); cur = []
    return out


def merge_rollup(cue_lines: list[list[str]]) -> str:
    """Senate captions roll up: a cue shows the lines on screen, and the newest line grows word by
    word across cues while the older one stays. So a line that extends one of the last few lines
    replaces it, and a shorter copy of one of them is dropped; anything else is a new line."""
    lines: list[str] = []
    for cue in cue_lines:
        for line in cue:
            for j in range(len(lines) - 1, max(-1, len(lines) - 5), -1):
                if line.startswith(lines[j]):
                    lines[j] = line  # the line grew
                    break
                if lines[j].startswith(line):
                    break  # an older, shorter copy
            else:
                lines.append(line)
    return "\n".join(lines) + "\n"


def fetch_one(url: str, out_dir: Path, nthreads: int = 16) -> tuple[str, str, str, int]:
    """(filename, comm, kind, characters) for one player URL."""
    parsed = parse_player_url(url)
    if not parsed or parsed[0] not in STREAM:
        return url, "", "none", 0
    comm, fn = parsed
    master_url = live_url(comm, fn)
    master = get(master_url)
    m = re.search(r'TYPE=SUBTITLES.*?URI="([^"]+)"', master)
    if not m:
        return fn, comm, "none", 0
    base = master_url.rsplit("/", 1)[0] + "/"
    playlist_url = base + m.group(1)
    segments = [l.strip() for l in get(playlist_url).splitlines() if l.strip() and not l.startswith("#")]
    seg_base = playlist_url.rsplit("/", 1)[0] + "/"
    with ThreadPoolExecutor(nthreads) as pool:
        parts = list(pool.map(lambda s: get(seg_base + s), segments))
    all_cues = [c for part in parts for c in cues(part)]
    (out_dir / f"{fn}.cues.txt").write_text("\n".join(" | ".join(c) for c in all_cues) + "\n", encoding="utf-8")  # raw cues, one per line, for re-merging
    text = merge_rollup(all_cues)
    (out_dir / f"{fn}.txt").write_text(text, encoding="utf-8")
    return fn, comm, "webvtt", len(text)


def main(out_dir, urls, nthreads=4):
    out_dir = Path(out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    index = out_dir / INDEX
    done = {r["filename"] for r in csv.DictReader(open(index))} if index.exists() else set()
    todo = [u for u in dict.fromkeys(urls) if (parse_player_url(u) or ("", u))[1] not in done]
    logging.info(f"{len(todo)} recordings to fetch ({len(done)} already in {index})")
    counts = {"webvtt": 0, "none": 0}
    with open(index, "a", newline="") as f:
        w = csv.writer(f)
        if not done:
            w.writerow(["filename", "comm", "kind", "characters"])
        with ThreadPoolExecutor(nthreads) as pool:
            for n, (fn, comm, kind, chars) in enumerate(pool.map(lambda u: fetch_one(u, out_dir), todo), 1):
                w.writerow([fn, comm, kind, chars]); f.flush()
                counts[kind] += 1
                if n % 50 == 0:
                    logging.info(f"{n}/{len(todo)}: {counts}")
    logging.info(f"done: {counts}")
    return counts


def parse_args_and_run():
    parser = argparse.ArgumentParser(description="Download Senate hearing captions from senate.gov as plain text.")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--urls", nargs="*", default=[], help="Player URLs (senate.gov/isvp/?comm=...&filename=...).")
    parser.add_argument("--urls-file", type=Path, help="Text file with one player URL per line.")
    parser.add_argument("--nthreads", type=int, default=4)
    args = parser.parse_args()
    urls = list(args.urls) + ([l.strip() for l in args.urls_file.read_text().splitlines() if l.strip()] if args.urls_file else [])
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(asctime)s : %(message)s")
    if not urls:
        sys.exit("No player URLs given.")
    main(args.out_dir, urls, args.nthreads)


if __name__ == "__main__":
    parse_args_and_run()
