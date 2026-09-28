"""
Download the captions of Senate hearing recordings from the Senate's own player, as plain text.

    senate-captions --out-dir ~/hearing-text/senate --urls "https://www.senate.gov/isvp/?comm=epw&filename=epw120623" ...
    senate-captions --out-dir ~/hearing-text/senate --urls-file links.txt

Recordings since about mid-2023 carry an English WebVTT subtitle track (the live path in
`isvp.py`); its segments are fetched concurrently and joined into <filename>.txt. Older
recordings (the archive path) have captions only inside the video stream, which this tool
doesn't decode. A confirmed absence from the live WebVTT path is recorded as
`none`; failed or incomplete checks are not indexed. Appends to <out-dir>/captions_index.csv:
filename, comm, kind (webvtt | none), characters. Current complete captures are skipped;
legacy entries without retained timing are rechecked when requested. Playlist and
segment text is retained in <filename>.captions.json.gz.
New checks also write caption_receipts/<record-key>.json with their observation
time and exact scope. Legacy index rows without receipts retain unknown check times.
"""
import argparse
import csv
import gzip
from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin

import requests

from congress_api.senate.isvp import STREAM, live_url, parse_player_url
from congress_shared.webvtt import cue_lines

INDEX = "captions_index.csv"
CAPTURE_VERSION = "2"
RECEIPTS = "caption_receipts"
HDR = {"User-Agent": "Mozilla/5.0"}
sess = requests.Session()
sess.mount("https://", requests.adapters.HTTPAdapter(pool_maxsize=32))


def get(url: str, attempts: int = 3) -> str:
    """Return a successful body, or empty only for a confirmed HTTP 404.

    Exhausted errors must remain errors: converting them to empty text turns a
    temporary outage into a permanent negative row in the incremental index.
    """
    if attempts < 1:
        raise ValueError("attempts must be positive")
    error = None
    for i in range(attempts):
        try:
            r = sess.get(url, headers=HDR, timeout=30)
            if r.status_code == 200:
                if r.text.strip():
                    return r.text
                error = requests.RequestException(f"Empty HTTP 200 response for {url}")
            if r.status_code == 404:
                return ""
            elif r.status_code != 200:
                error = requests.HTTPError(f"HTTP {r.status_code} for {url}", response=r)
        except requests.RequestException as exc:
            error = exc
    raise error


class IncompleteCaptionsError(RuntimeError):
    """A declared caption playlist or segment could not be completely read."""


def receipt_path(out_dir: Path, url: str) -> Path:
    """Stable per-record path, including harmless player URL query variations."""
    parsed = parse_player_url(url)
    key = "|".join(parsed) if parsed else url
    return Path(out_dir) / RECEIPTS / (sha256(key.encode()).hexdigest() + ".json")


def _write_text(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_receipt(out_dir: Path, url: str, receipt: dict) -> None:
    path = receipt_path(out_dir, url)
    path.parent.mkdir(parents=True, exist_ok=True)
    receipt["observed_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if receipt.get('outcome') == 'error' and path.exists():
        previous = json.loads(path.read_text())
        successful = previous.get('last_successful') if previous.get('outcome') == 'error' else previous
        if successful and successful.get('outcome') in ('available', 'not_found'):
            receipt['last_successful'] = {k: v for k, v in successful.items() if k != 'last_successful'}
    _write_text(path, json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")


def _require_playlist(body: str, url: str) -> None:
    lines = body.lstrip("\ufeff \t\r\n").splitlines()
    if not lines or lines[0].strip() != "#EXTM3U":
        raise IncompleteCaptionsError(f"Missing or invalid HLS playlist: {url}")


def _subtitle_uri(master: str) -> str | None:
    for line in master.splitlines():
        if line.strip().startswith("#EXT-X-MEDIA:"):
            attrs = dict((name, value.strip('"')) for name, value in re.findall(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)', line))
            if attrs.get("TYPE") == "SUBTITLES":
                if not attrs.get("URI"):
                    raise IncompleteCaptionsError("Declared subtitle track has no playlist URI")
                return attrs["URI"]
    return None


def _segment(url: str) -> str:
    body = get(url)
    if not re.match(r"\A\ufeff?WEBVTT(?:[ \t\r\n]|$)", body):
        raise IncompleteCaptionsError(f"Missing or invalid WebVTT segment: {url}")
    blocks = re.split(r"\n[ \t]*\n", body.replace("\r\n", "\n").replace("\r", "\n"))
    if "-->" in blocks[0]:
        raise IncompleteCaptionsError(f"WebVTT header is not separated from its cues: {url}")
    for block in blocks[1:]:
        lines = block.strip().splitlines()
        if not lines or re.match(r"^(?:NOTE|STYLE|REGION)(?:\s|$)", lines[0]):
            continue
        timing = lines[0] if "-->" in lines[0] else lines[1] if len(lines) > 1 else ""
        match = re.fullmatch(r"((?:\d{2,}:)?[0-5]\d:[0-5]\d\.\d{3})[ \t]+-->[ \t]+((?:\d{2,}:)?[0-5]\d:[0-5]\d\.\d{3})(?:[ \t]+.*)?", timing)
        if not match:
            raise IncompleteCaptionsError(f"Invalid WebVTT cue timing: {url}")
        times = [sum(float(part) * 60 ** index for index, part in enumerate(reversed(value.split(":"))))
                 for value in match.groups()]
        if times[1] <= times[0]:
            raise IncompleteCaptionsError(f"WebVTT cue ends before it starts: {url}")
    return body


def cues(vtt: str) -> list[list[str]]:
    """Each cue's text lines, retaining numeric speech and excluding cue IDs."""
    return cue_lines(vtt)


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
    """Return an index row only after a complete, scoped acquisition check."""
    out_dir = Path(out_dir)
    parsed = parse_player_url(url)
    comm, fn = parsed or ("", "")
    receipt = {
        "schema_version": "1.0", "capture_version": CAPTURE_VERSION, "filename": fn, "comm": comm, "player_url": url,
        "scope": {"kind": "senate_live_webvtt", "master_url": None, "playlist_url": None,
                  "segment_urls": [], "includes_embedded_archive_captions": False},
    }
    try:
        if not parsed or comm not in STREAM:
            raise ValueError("Unsupported Senate player URL or committee")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", fn):
            raise ValueError("Unsupported recording filename")
        master_url = live_url(comm, fn)
        receipt["scope"]["master_url"] = master_url
        master = get(master_url)
        if not master:
            receipt.update(outcome="not_found", kind="none", characters=0, reason="The live WebVTT master returned HTTP 404.")
            result = (fn, comm, "none", 0)
        else:
            _require_playlist(master, master_url)
            subtitle_uri = _subtitle_uri(master)
            if subtitle_uri is None:
                receipt.update(outcome="not_found", kind="none", characters=0, reason="The live master has no declared subtitle track.")
                result = (fn, comm, "none", 0)
            else:
                playlist_url = urljoin(master_url, subtitle_uri)
                receipt["scope"]["playlist_url"] = playlist_url
                playlist = get(playlist_url)
                _require_playlist(playlist, playlist_url)
                segments = [urljoin(playlist_url, line.strip()) for line in playlist.splitlines()
                            if line.strip() and not line.strip().startswith("#")]
                receipt["scope"]["segment_urls"] = segments
                if not segments:
                    raise IncompleteCaptionsError("Subtitle playlist contains no segments")
                with ThreadPoolExecutor(nthreads) as pool:
                    parts = list(pool.map(_segment, segments))
                # One retained source file keeps timestamps, segment boundaries
                # and X-TIMESTAMP-MAP values that the text views cannot preserve.
                raw = {'master': {'url': master_url, 'text': master},
                       'playlist': {'url': playlist_url, 'text': playlist},
                       'segments': [{'url': url, 'text': part} for url, part in zip(segments, parts)]}
                out_dir.mkdir(parents=True, exist_ok=True)
                raw_path = out_dir / f"{fn}.captions.json.gz"
                temporary = raw_path.with_suffix(raw_path.suffix + '.tmp')
                temporary.write_bytes(gzip.compress(json.dumps(raw, ensure_ascii=False).encode('utf-8'), mtime=0))
                temporary.replace(raw_path)
                receipt['source_file'] = raw_path.name
                all_cues = [cue for part in parts for cue in cues(part)]
                text = merge_rollup(all_cues) if all_cues else ""
                out_dir.mkdir(parents=True, exist_ok=True)
                _write_text(out_dir / f"{fn}.cues.txt", "\n".join(" | ".join(cue) for cue in all_cues) + "\n")
                _write_text(out_dir / f"{fn}.txt", text)
                receipt.update(outcome="available", kind="webvtt", characters=len(text))
                result = (fn, comm, "webvtt", len(text))
    except Exception as exc:
        receipt.update(outcome="error", error={"type": type(exc).__name__, "message": str(exc)})
        _write_receipt(out_dir, url, receipt)
        raise
    _write_receipt(out_dir, url, receipt)
    return result


def main(out_dir, urls, nthreads=4):
    out_dir = Path(out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    index = out_dir / INDEX
    saved = {(r['comm'], r['filename']): r for r in csv.DictReader(index.open())} if index.exists() else {}
    unique = {}
    for url in urls:
        key = parse_player_url(url) or ('', url)
        path = receipt_path(out_dir, url)
        receipt = json.loads(path.read_text()) if path.exists() else {}
        current = receipt.get('capture_version') == CAPTURE_VERSION and receipt.get('outcome') in ('available', 'not_found')
        if current and receipt.get('kind') == 'webvtt':
            current = bool(receipt.get('source_file') and (out_dir / receipt['source_file']).exists()
                           and (out_dir / f"{key[1]}.txt").exists())
        if current:
            saved[key] = dict(filename=key[1], comm=key[0], kind=receipt['kind'], characters=receipt['characters'])
        else:
            unique.setdefault(key, url)
    todo = list(unique.values())
    logging.info(f"{len(todo)} recordings need caption capture, including legacy rows without retained timing")
    counts = {"webvtt": 0, "none": 0}
    failures = []
    try:
        with ThreadPoolExecutor(nthreads) as pool:
            futures = [pool.submit(fetch_one, url, out_dir) for url in todo]
            for n, (url, future) in enumerate(zip(todo, futures), 1):
                try:
                    fn, comm, kind, chars = future.result()
                except Exception as exc:
                    failures.append((url, exc))
                    logging.error(f"Caption acquisition failed for {url}: {exc}")
                    continue
                saved[(comm, fn)] = dict(filename=fn, comm=comm, kind=kind, characters=chars)
                counts[kind] += 1
                if n % 50 == 0:
                    logging.info(f"{n}/{len(todo)}: {counts}")
    finally:
        temporary = index.with_suffix('.csv.tmp')
        with temporary.open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=['filename', 'comm', 'kind', 'characters'])
            writer.writeheader()
            writer.writerows(saved.values())
        temporary.replace(index)
    logging.info(f"done: {counts}")
    if failures:
        raise RuntimeError(f"{len(failures)} Senate caption acquisition(s) failed; see {out_dir / RECEIPTS}") from failures[0][1]
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
