"""
Download the captions of Senate hearing recordings from the Senate's own player, as plain text.

    senate-captions --out-dir ~/hearing-text/senate --urls "https://www.senate.gov/isvp/?comm=epw&filename=epw120623" ...
    senate-captions --out-dir ~/hearing-text/senate --urls-file links.txt

Recordings since about mid-2023 commonly carry an English WebVTT subtitle track;
both live and archive paths can provide one. Its segments are fetched concurrently
and joined into <filename>.txt. Older recordings may carry captions only inside
the video stream, which this tool doesn't decode. Absence from both WebVTT paths is recorded as
`none`; failed or incomplete checks are not indexed. Appends to <out-dir>/captions_index.csv:
filename, comm, kind (webvtt | none), characters. Current complete captures are skipped;
legacy entries without retained timing are rechecked when requested. Playlist and
segment text is retained in <filename>.captions.json.gz.
New checks also write caption_receipts/<record-key>.json with their observation
time and exact scope. Legacy index rows without receipts retain unknown check times.
"""

import csv
import gzip
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin

import requests

from congress_api.models.media import CaptionReceipt, MediaTextSource, SenateCaptionSources
from congress_api.parsers.captions import (
    IncompleteCaptionsError,
    _require_playlist,
    _subtitle_uri,
    cues,
    merge_rollup,
    parsed_cues,
)
from congress_api.parsers.senate_player import LIVE_ID, STREAM, archive_url, live_url, parse_player_url
from congress_api.retention.captions import RECEIPTS, _write_receipt, _write_text, receipt_path
from congress_api.transport.senate import get_source

INDEX = "captions_index.csv"


CAPTURE_VERSION = "3"


def _segment_source(url: str, sources: list[MediaTextSource] | None = None) -> MediaTextSource:
    source = get_source(url, sources=sources)
    parsed_cues(source.text if source.status_code == 200 else "", url)
    return source


def _segment(url: str) -> str:
    return _segment_source(url).text


def fetch_one(url: str, out_dir: Path, nthreads: int = 16) -> tuple[str, str, str, int]:
    """Return an index row only after a complete, scoped acquisition check."""
    out_dir = Path(out_dir)
    parsed = parse_player_url(url)
    comm, fn = parsed or ("", "")
    receipt = {
        "schema_version": "1.0", "capture_version": CAPTURE_VERSION, "filename": fn, "comm": comm, "player_url": url,
        "scope": {"kind": "senate_live_and_archive_webvtt", "master_url": None, "playlist_url": None,
                  "segment_urls": [], "includes_embedded_archive_captions": False},
    }
    sources = []
    try:
        if not parsed or comm not in STREAM:
            raise ValueError("Unsupported Senate player URL or committee")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", fn):
            raise ValueError("Unsupported recording filename")
        master_checks = []
        candidate_errors = []
        selected = None
        master_urls = ([live_url(comm, fn)] if comm in LIVE_ID else []) + [archive_url(comm, fn)]
        for master_url in master_urls:
            receipt["scope"]["master_url"] = master_url
            try:
                master_source = get_source(master_url, sources=sources)
                master_checks.append(master_source)
                if master_source.status_code != 200:
                    continue
                _require_playlist(master_source.text, master_url)
                subtitle_uri = _subtitle_uri(master_source.text)
                if subtitle_uri is None:
                    continue
                playlist_url = urljoin(master_url, subtitle_uri)
                receipt["scope"]["playlist_url"] = playlist_url
                playlist_source = get_source(playlist_url, sources=sources)
                playlist = playlist_source.text if playlist_source.status_code == 200 else ""
                _require_playlist(playlist, playlist_url)
                segments = [urljoin(playlist_url, line.strip()) for line in playlist.splitlines()
                            if line.strip() and not line.strip().startswith("#")]
                receipt["scope"]["segment_urls"] = segments
                if not segments:
                    raise IncompleteCaptionsError("Subtitle playlist contains no segments")
                with ThreadPoolExecutor(nthreads) as pool:
                    segment_sources = list(pool.map(lambda segment: _segment_source(segment, sources), segments))
                selected = (master_source, playlist_source, segment_sources)
                break
            except (requests.RequestException, IncompleteCaptionsError) as exc:
                # An archived copy can remain complete when a live playlist or
                # segment disappears. An unsuccessful fallback stays an error.
                candidate_errors.append(exc)
        if selected is None:
            if candidate_errors:
                raise candidate_errors[-1]
            raw = SenateCaptionSources(master=master_source, master_checks=master_checks)
            receipt.update(outcome="not_found", kind="none", characters=0,
                           reason="No checked master declares a subtitle track; embedded video captions were not checked.")
            result = (fn, comm, "none", 0)
        else:
            master_source, playlist_source, segment_sources = selected
            selected_responses = {id(source) for source in [*master_checks, playlist_source, *segment_sources]}
            prior_responses = [source for source in sources if id(source) not in selected_responses]
            # Keep failed-path responses too, so an archive fallback can be
            # checked without repeating requests or discarding captured bytes.
            raw = SenateCaptionSources(master=master_source, master_checks=master_checks,
                                       playlist=playlist_source, segments=segment_sources,
                                       prior_responses=prior_responses)
            all_cues = [cue for source in segment_sources for cue in cues(source.text)]
            text = merge_rollup(all_cues) if all_cues else ""
            receipt.update(outcome="available", kind="webvtt", characters=len(text))
            zero_duration = sum(cue.start == cue.end for source in segment_sources for cue in parsed_cues(source.text))
            if zero_duration:
                receipt['zero_duration_cues'] = zero_duration
            result = (fn, comm, "webvtt", len(text))
        # Retain complete source responses for positive and negative checks.
        out_dir.mkdir(parents=True, exist_ok=True)
        raw_path = out_dir / f"{fn}.captions.json.gz"
        temporary = raw_path.with_suffix(raw_path.suffix + '.tmp')
        temporary.write_bytes(gzip.compress(json.dumps(raw.source_dict(), ensure_ascii=False).encode('utf-8'), mtime=0))
        temporary.replace(raw_path)
        receipt['source_file'] = raw_path.name
        if result[2] == "webvtt":
            _write_text(out_dir / f"{fn}.cues.txt", "\n".join(" | ".join(cue) for cue in all_cues) + "\n")
            _write_text(out_dir / f"{fn}.txt", text)
    except Exception as exc:
        if sources:
            receipt["source_responses"] = sources
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
        receipt = CaptionReceipt.model_validate_json(path.read_text()).source_dict() if path.exists() else {}
        current = (receipt.get('capture_version') == CAPTURE_VERSION
                   or receipt.get('capture_version') == '2' and receipt.get('outcome') == 'available')
        current = current and receipt.get('outcome') in ('available', 'not_found')
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
