"""
Find Senate hearing recordings on the Senate's own player by probing its archive.

The Senate Recording Studio names each recording <comm><MMDDYY> (a second hearing that day
gets <comm>A<MMDDYY>, then B...). The player at senate.gov/isvp/?comm=...&filename=... loads
https://www-senate-gov-msl3archive.akamaized.net/<stream>/<filename>_1/master.m3u8, where
<stream> is the committee's archive name from the player's own stream table, or for recordings
since about mid-2023 the live path .../hls/live/<streamID>/<comm>/<filename>/master.m3u8. A HEAD
on the manifest says whether the recording exists.

    python senate_isvp_probe.py <out.csv>     # resumable: hearings already found are skipped, misses retried

Probes every Senate and joint GPO hearing since the 113th Congress whose status isn't a full recording.
Writes one row per hearing: package_id, held_date, committee_code, comm, urls (player links,
space-separated; empty when nothing was found).
"""
import collections
import csv
import datetime as dt
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[5] / "packages/congress_api/src"))
from congress_api.parsers.senate_player import COMM, STREAM, archive_url, live_url, player_url

VARIANTS = ["", "A", "B"]  # lettered names are tried when the committee held several hearings that day, or the plain one is missing
WORKERS = 8
sess = requests.Session()


def head(url):
    for attempt in range(3):
        try:
            r = sess.head(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code in (200, 404):
                return r.status_code == 200
        except requests.RequestException:
            pass
        time.sleep(5 * (attempt + 1))
    return None  # unknown; row is skipped so a rerun retries it


def exists(comm, fn):
    """True when the recording is in the archive or on the live path; None when neither answered."""
    a = head(archive_url(comm, fn))
    if a:
        return True
    b = head(live_url(comm, fn))
    return b if b or a is not None else None


def probe_day(comm, d, several):
    """Player URLs for a committee's recordings on a day."""
    urls, unknown = [], False
    for v in VARIANTS:
        if v and not several and urls:
            break
        fn = f"{comm}{v}{d:%m%d%y}"
        ok = exists(comm, fn)
        if ok is None:
            unknown = True
        elif ok:
            urls.append(player_url(comm, fn))
    return urls, unknown


def main(out_path):
    videos = {r["package_id"]: r for r in csv.DictReader(open("apps/committee_youtube/data/gpo_hearing_videos.csv"))}
    targets = [r for r in csv.DictReader(open("apps/committee_youtube/data/gpo_hearings.csv"))
               if r["chamber"] in ("senate", "joint") and int(r["congress"]) >= 113 and r["held_date"]
               and videos.get(r["package_id"], {}).get("status") not in ("full_recording", "full_recording_offsite")]
    per_day = collections.Counter((r["committee_code"], r["held_date"]) for r in targets)
    ## rows with a recording are final; misses are probed again (a later row for the same hearing wins)
    done = {r["package_id"] for r in csv.DictReader(open(out_path)) if r["urls"]} if os.path.exists(out_path) else set()
    todo = [t for t in targets if t["package_id"] not in done]
    days = sorted({(COMM[r["committee_code"]], r["held_date"], per_day[(r["committee_code"], r["held_date"])] > 1)
                   for r in todo if COMM.get(r["committee_code"]) in STREAM})
    print(len(targets), "targets,", len(todo), "to do,", len(days), "committee-days", flush=True)
    results = {}
    with open(out_path, "a", newline="") as f:
        w = csv.writer(f)
        if not done:
            w.writerow(["package_id", "held_date", "committee_code", "comm", "urls"])
        with ThreadPoolExecutor(WORKERS) as pool:
            for n, ((comm, day, several), (urls, unknown)) in enumerate(zip(days, pool.map(lambda x: probe_day(x[0], dt.date.fromisoformat(x[1]), x[2]), days))):
                results[(comm, day)] = (urls, unknown)
                if n % 200 == 0:
                    print(n, len(days), "days probed;", sum(1 for u, _ in results.values() if u), "with a recording", flush=True)
        found = 0
        for r in todo:
            comm = COMM.get(r["committee_code"])
            if not comm or comm not in STREAM:
                w.writerow([r["package_id"], r["held_date"], r["committee_code"], comm or "", ""]); continue
            urls, unknown = results[(comm, r["held_date"])]
            if unknown and not urls:
                continue  # left out so a rerun retries it
            found += bool(urls)
            w.writerow([r["package_id"], r["held_date"], r["committee_code"], comm, " ".join(urls)])
        print("DONE", len(todo), "hearings;", found, "with a recording", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
