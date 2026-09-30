"""Rehearse adding 30 days of meetings with retained source responses, no network.

Run with .venv/bin/python tests/replay_meeting_inventory.py --seed-cache PATH
--state-dir PATH --meetings PATH --gpo-path PATH --output-dir PATH. The supplied
state is copied. Request counts exercise the production refresh decisions;
elapsed time measures local replay, not internet latency. House responses use
the cached event's XML (or its confirmed .none), so address retries are excluded
from this estimate. Live bounded checks qualify addressing separately.
"""
import argparse
import collections
import datetime as dt
import gzip
import json
import re
import shutil
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import requests
from congress_api.acquisition import house as house
from congress_api.acquisition import senate as senate
from congress_api.models.senate import workflow_record
from congress_api.retention.senate import seed_fetch as senate_seed_fetch
from congress_api.retention.tables import read_meetings, read_state, write_state
from congress_api.transport import http


def main(args):
    start = time.monotonic()
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    state_dir = output / "state"
    shutil.copytree(args.state_dir, state_dir, dirs_exist_ok=True)
    meetings = read_meetings(args.meetings)
    cutoff = args.as_of - dt.timedelta(days=30)
    recent = {m["eventId"] for m in meetings if m["date"][:10] >= cutoff.isoformat()}
    older = [m for m in meetings if m["eventId"] not in recent]
    old_path = output / "older.jsonl.gz"
    old_path.write_bytes(gzip.compress("".join(json.dumps(m) + "\n" for m in older).encode(), mtime=0))
    hs = read_state(state_dir / "house.json.gz")
    for event in recent:
        hs.pop(event, None)
    write_state(state_dir / "house.json.gz", hs)
    ss = read_state(state_dir / "senate.json.gz")
    removed_pages = 0
    for saved in ss.values():
        for event in recent:
            saved["versions"].pop(event, None)
        for url, page in list(saved["pages"].items()):
            if set(workflow_record(saved, url, page).get("events") or []) & recent:
                del saved["pages"][url]
                (saved.get("workflow") or {}).pop(url, None)
                del saved["listings"][url]
                removed_pages += 1
    write_state(state_dir / "senate.json.gz", ss)
    common = dict(state_dir=state_dir, output_dir=output, as_of=args.as_of)
    house.main(old_path, args.gpo_path, **common, offline=True)
    senate.main(old_path, **common, offline=True)
    counts = collections.Counter()
    def replay(session, url, **kwargs):
        host = urlsplit(url).hostname
        counts[host] += 1
        response = requests.Response()
        response.status_code, response._content, response.url = 200, b"", url
        if host == "docs.house.gov":
            event = re.search(r"/(\d{6})/", url)
            if event:
                folder = "wlist" if "-WList-" in url else "meeting"
                path = args.seed_cache / "docs_house_xml" / folder / f"{event[1]}.xml"
                if path.exists():
                    response._content = path.read_bytes()
                elif path.with_suffix(".none").exists():
                    response.status_code = 404
                else:
                    raise RuntimeError(f"Replay missing {path}")
            else:
                event = parse_qs(urlsplit(url).query)["EventID"][0]
                response._content = (args.seed_cache / "docs_house" / f"{event}.html").read_bytes()
        else:
            page = senate_seed_fetch(args.seed_cache, url)
            response._content = page.encode()
            if not page:
                response.status_code = 404
        return response
    http.get_with_retry = replay
    phase = time.monotonic()
    house.main(args.meetings, args.gpo_path, **common)
    senate.main(args.meetings, **common)
    result = {"older_meetings": len(older), "added_meetings": len(recent), "removed_senate_pages": removed_pages,
              "requests_replayed": dict(counts), "http_total": sum(counts.values()), "external_requests": 0,
              "incremental_seconds": round(time.monotonic() - phase, 2), "total_seconds": round(time.monotonic() - start, 2)}
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(result)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for option in ("seed-cache", "state-dir", "meetings", "gpo-path", "output-dir"):
        p.add_argument(f"--{option}", type=Path, required=True)
    p.add_argument("--as-of", type=dt.date.fromisoformat, default=dt.date(2026, 9, 27))
    main(p.parse_args())
