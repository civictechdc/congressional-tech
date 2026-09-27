"""
Keep a local copy of every House, Senate and joint committee meeting record on Congress.gov.

    congress-meetings --output-path congress_meetings.jsonl.gz

Each line is one meeting's detail record (event ID, date, committees, title, type,
status, witnesses, and the official `videos` links, usually to YouTube). The
first run lists every meeting from the 112th Congress on (about 13,600 detail
calls). Later runs only fetch meetings Congress.gov updated since the newest
`updateDate` on file.
"""
import argparse
import gzip
import json
import logging
import sys
import threading
import time

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import requests

from congress_shared.auth import load_congress_api_key
from congress_shared.globals import CONGRESS_METADATA, DEFAULT_MEETINGS_FILE

API = "https://api.congress.gov/v3"
FIRST_CONGRESS = 112  # Congress.gov's committee meeting records start here
CHAMBERS = ("house", "nochamber", "senate")  # nochamber = joint committees and commissions
RELIST_OVERLAP = timedelta(days=2)


def main(output_path: Path = DEFAULT_MEETINGS_FILE, nthreads: int = 5) -> None:
    api_key = load_congress_api_key()
    session = requests.Session()

    records = read(output_path)
    since = None
    if records:
        newest = max(r.get("updateDate", "") for r in records.values())
        since = (datetime.strptime(newest[:19], "%Y-%m-%dT%H:%M:%S") - RELIST_OVERLAP).strftime("%Y-%m-%dT%H:%M:%SZ")
    logging.info(f"{len(records)} meetings on file; listing {'changes since ' + since if since else 'everything'}")

    ## only list congresses whose records can still change: all of them for a
    ##  chamber we have nothing for yet, otherwise the current one and the one before
    current = max(int(c) for c in CONGRESS_METADATA)
    have = {(r.get("chamber") or "").lower() for r in records.values()}  # "house", "nochamber", "senate"
    urls = []
    for chamber in CHAMBERS:
        new_chamber = since is None or chamber not in have
        congresses = range(FIRST_CONGRESS, current + 1) if new_chamber else range(current - 1, current + 1)
        for congress in congresses:
            params = {"limit": 250, "offset": 0}
            if since and not new_chamber:
                params.update(fromDateTime=since, toDateTime="2100-01-01T00:00:00Z")
            while True:
                page = get(session, f"{API}/committee-meeting/{congress}/{chamber}", api_key, params)
                meetings = page.get("committeeMeetings", [])
                urls += [m["url"].split("?")[0] for m in meetings]
                if len(meetings) < params["limit"]:
                    break
                params["offset"] += params["limit"]
    urls = list(dict.fromkeys(urls))
    logging.info(f"Fetching {len(urls)} new or updated meeting records")

    failures, lock = [], threading.Lock()

    def fetch(url):
        try:
            record = get(session, url, api_key)["committeeMeeting"]
            record["_url"] = url
            with lock:
                records[url] = record
        except Exception as ex:
            failures.append(f"{url}: {ex!r}")

    with ThreadPoolExecutor(nthreads) as pool:
        list(pool.map(fetch, urls))

    write(records, output_path)
    logging.info(f"Wrote {len(records)} meetings to {output_path}")
    if failures:
        logging.error(f"{len(failures)} meeting(s) failed:\n  " + "\n  ".join(failures[:50]))
        sys.exit(1)


def get(session, url, api_key, params=None, attempts=5):
    for attempt in range(attempts):
        r = session.get(url, params={**(params or {}), "api_key": api_key, "format": "json"}, timeout=60)
        if r.status_code in (429, 500, 502, 503, 504) and attempt < attempts - 1:
            time.sleep(3 * 2 ** attempt)
            continue
        r.raise_for_status()
        return r.json()


def read(path: Path) -> dict[str, dict]:
    if not Path(path).exists():
        return {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return {r["_url"]: r for r in map(json.loads, f)}


def write(records: dict[str, dict], path: Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    ## sorted, and mtime=0 so identical content gives identical bytes
    with open(path, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as f:
        for url in sorted(records):
            f.write((json.dumps(records[url], sort_keys=True) + "\n").encode("utf-8"))


def parse_args_and_run():
    parser = argparse.ArgumentParser(description="Keep a local copy of House and joint committee meeting records.")
    parser.add_argument("--output-path", type=Path, default=DEFAULT_MEETINGS_FILE)
    parser.add_argument("--nthreads", type=int, default=5)
    args = parser.parse_known_args()[0]
    main(**vars(args))


if __name__ == "__main__":
    parse_args_and_run()
