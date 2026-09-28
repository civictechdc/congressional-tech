"""
Keep a local copy of every House, Senate and joint committee meeting record on Congress.gov.

    congress-meetings --output-path congress_meetings.jsonl.gz

Each line is one meeting's detail record (event ID, date, committees, title, type,
status, witnesses, and the official `videos` links, usually to YouTube). The
first run lists every meeting from the 112th Congress on (about 13,600 detail
calls). Later runs fetch meetings Congress.gov updated since the newest
`updateDate` on file, plus any previously failed detail URLs retained in the
adjacent ``.pending.json`` file. Listing still covers every Congress.
"""
import argparse
import gzip
import json
import logging
import sys
import threading

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import requests

from congress_api.http import get_with_retry
from congress_shared.auth import load_congress_api_key
from congress_shared.globals import CONGRESS_METADATA, DEFAULT_MEETINGS_FILE

API = "https://api.congress.gov/v3"
FIRST_CONGRESS = 112  # Congress.gov's committee meeting records start here
CHAMBERS = ("house", "nochamber", "senate")  # nochamber = joint committees and commissions
RELIST_OVERLAP = timedelta(days=2)


def main(output_path: Path = DEFAULT_MEETINGS_FILE, nthreads: int = 5) -> None:
    if nthreads < 1:
        raise ValueError("nthreads must be positive")
    output_path = Path(output_path)
    api_key = load_congress_api_key()
    session = requests.Session()

    records = read(output_path)
    since = None
    if records:
        newest = max(r.get("updateDate", "") for r in records.values())
        since = (datetime.strptime(newest[:19], "%Y-%m-%dT%H:%M:%S") - RELIST_OVERLAP).strftime("%Y-%m-%dT%H:%M:%SZ")
    logging.info(f"{len(records)} meetings on file; listing {'changes since ' + since if since else 'everything'}")

    # Historical records can also be corrected; use the update window for every
    # Congress instead of silently ignoring changes more than two Congresses old.
    current = max(int(c) for c in CONGRESS_METADATA)
    have = {(r.get("chamber") or "").lower() for r in records.values()}  # "house", "nochamber", "senate"
    pending_path = output_path.with_suffix(output_path.suffix + ".pending.json")
    pending = json.loads(pending_path.read_text()) if pending_path.exists() else {"urls": []}
    urls = list(pending["urls"])
    for chamber in CHAMBERS:
        new_chamber = since is None or chamber not in have
        congresses = range(FIRST_CONGRESS, current + 1)
        for congress in congresses:
            params = {"limit": 250, "offset": 0}
            listed = set()
            if since and not new_chamber:
                params.update(fromDateTime=since, toDateTime="2100-01-01T00:00:00Z")
            while True:
                page = get(session, f"{API}/committee-meeting/{congress}/{chamber}", api_key, params)
                meetings = page["committeeMeetings"]
                page_urls = [m["url"].split("?")[0] for m in meetings]
                if page_urls and not set(page_urls) - listed:
                    raise ValueError(f"Meeting pagination repeated a page: {congress}/{chamber}")
                listed.update(page_urls)
                urls += page_urls
                if not page.get("pagination", {}).get("next") and len(meetings) < params["limit"]:
                    break
                if not meetings:
                    raise ValueError(f"Meeting pagination did not advance: {congress}/{chamber}")
                params["offset"] += len(meetings)
    urls = list(dict.fromkeys(urls))
    logging.info(f"Fetching {len(urls)} new or updated meeting records")
    # Save work before beginning detail requests. A crash may repeat completed
    # requests, but a later global updateDate can never skip unfinished URLs.
    write_pending(pending_path, urls)

    failures, failed_urls, lock = [], [], threading.Lock()

    def fetch(url):
        try:
            if not url.startswith(f"{API}/committee-meeting/"):
                raise ValueError("Meeting detail URL is not on the Congress.gov API")
            record = dict(get(session, url, api_key)["committeeMeeting"])
            if any(record.get(field) in (None, "") for field in ("eventId", "congress", "chamber")):
                raise ValueError("Meeting detail lacks eventId, congress or chamber")
            record["_url"] = url
            record["_retrieved_at"] = datetime.now(UTC).isoformat()
            with lock:
                records[url] = record
        except Exception as ex:
            with lock:
                failures.append(f"{url}: {type(ex).__name__}")
                failed_urls.append(url)

    with ThreadPoolExecutor(nthreads) as pool:
        list(pool.map(fetch, urls))

    write(records, output_path)
    write_pending(pending_path, failed_urls)
    logging.info(f"Wrote {len(records)} meetings to {output_path}")
    if failures:
        logging.error(f"{len(failures)} meeting(s) failed:\n  " + "\n  ".join(failures[:50]))
        sys.exit(1)


def get(session, url, api_key, params=None, attempts=5):
    return get_with_retry(session, url, params={**(params or {}), "api_key": api_key, "format": "json"}, attempts=attempts).json()


def read(path: Path) -> dict[str, dict]:
    if not Path(path).exists():
        return {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return {r["_url"]: r for r in map(json.loads, f)}


def write(records: dict[str, dict], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    ## sorted, and mtime=0 so identical content gives identical bytes
    try:
        with open(temporary, "wb") as raw, gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as f:
            for url in sorted(records):
                f.write((json.dumps(records[url], sort_keys=True) + "\n").encode("utf-8"))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_pending(path, urls):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(json.dumps({"urls": sorted(set(urls))}, indent=2) + "\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def parse_args_and_run():
    parser = argparse.ArgumentParser(description="Keep a local copy of House and joint committee meeting records.")
    parser.add_argument("--output-path", type=Path, default=DEFAULT_MEETINGS_FILE)
    parser.add_argument("--nthreads", type=int, default=5)
    args = parser.parse_known_args()[0]
    main(**vars(args))


if __name__ == "__main__":
    parse_args_and_run()
