"""
Find Senate hearing recordings on the Senate's own player by probing its archive.

The Senate Recording Studio names each recording <comm><MMDDYY> (a second hearing that day
gets <comm>A<MMDDYY>, then B...). The player at senate.gov/isvp/?comm=...&filename=... loads
https://www-senate-gov-msl3archive.akamaized.net/<stream>/<filename>_1/master.m3u8, where
<stream> is the committee's archive name from the player's own stream table. A HEAD on that
manifest says whether the recording exists.

    python senate_isvp_probe.py <out.csv>     # resumable: rows already in out.csv are skipped

Probes every Senate GPO hearing since the 113th Congress whose status isn't a full recording.
Writes one row per hearing: package_id, held_date, committee_code, comm, urls (player links,
space-separated; empty when nothing was found).
"""
import csv, datetime as dt, sys, time, os
import requests

## GPO committee code -> the player's `comm` value (learned from Congress.gov's senate.gov links)
COMM = {"ssaf00": "ag", "ssap00": "approps", "ssas00": "armed", "ssbk00": "banking", "ssbu00": "budget", "sscm00": "commerce",
        "sseg00": "energy", "ssev00": "epw", "ssfi00": "finance", "ssfr00": "foreign", "ssga00": "govtaff", "sshr00": "help",
        "ssju00": "judiciary", "ssra00": "rules", "sssb00": "smbiz", "ssva00": "vetaff", "slia00": "indian", "slin00": "intel",
        "spag00": "aging", "slet00": "ethics", "jcse00": "csce", "jsec00": "jec", "jjec00": "jec"}
## `comm` -> archive stream name, from the player page's streamInfo table (September 2026)
STREAM = {"ag": "agriculture", "aging": "aging", "approps": "appropriations", "armed": "armedservices", "banking": "banking",
          "budget": "budget", "commerce": "commerce", "csce": "srs_srs", "energy": "energy", "epw": "environment", "ethics": "ethics",
          "finance": "finance_finance", "foreign": "foreignrelations", "govtaff": "hsgac", "help": "help", "indian": "indianaffairs",
          "intel": "intelligence", "jec": "jointeconomic", "judiciary": "judiciary", "rules": "rules", "smbiz": "smallbusiness",
          "vetaff": "veteransaffairs"}
ARCHIVE = "https://www-senate-gov-msl3archive.akamaized.net/{stream}/{fn}_1/master.m3u8"
PLAYER = "https://www.senate.gov/isvp/?comm={comm}&filename={fn}"
VARIANTS = ["", "A", "B"]
sess = requests.Session()


def exists(stream, fn):
    for attempt in range(3):
        try:
            r = sess.head(ARCHIVE.format(stream=stream, fn=fn), timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code in (200, 404):
                return r.status_code == 200
        except requests.RequestException:
            pass
        time.sleep(5 * (attempt + 1))
    return None  # unknown; row is skipped so a rerun retries it


def main(out_path):
    videos = {r["package_id"]: r for r in csv.DictReader(open("apps/committee_youtube/data/gpo_hearing_videos.csv"))}
    targets = [r for r in csv.DictReader(open("apps/committee_youtube/data/gpo_hearings.csv"))
               if r["chamber"] == "senate" and int(r["congress"]) >= 113 and r["held_date"]
               and videos.get(r["package_id"], {}).get("status") not in ("full_recording", "full_recording_offsite")]
    done = {r["package_id"] for r in csv.DictReader(open(out_path))} if os.path.exists(out_path) else set()
    new = not done
    seen = {}  # (comm, fn) -> bool, so same-day hearings share one probe
    with open(out_path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["package_id", "held_date", "committee_code", "comm", "urls"])
        found = 0
        for i, r in enumerate(t for t in targets if t["package_id"] not in done):
            comm = COMM.get(r["committee_code"])
            if not comm or comm not in STREAM:
                w.writerow([r["package_id"], r["held_date"], r["committee_code"], comm or "", ""]); continue
            d = dt.date.fromisoformat(r["held_date"])
            urls, unknown = [], False
            for v in VARIANTS:
                fn = f"{comm}{v}{d:%m%d%y}"
                if (comm, fn) not in seen:
                    seen[(comm, fn)] = exists(STREAM[comm], fn)
                    time.sleep(0.15)
                if seen[(comm, fn)] is None:
                    unknown = True
                elif seen[(comm, fn)]:
                    urls.append(PLAYER.format(comm=comm, fn=fn))
                elif v == "" and not urls:
                    pass  # no plain file; still try A (some days only have the lettered one)
            if unknown and not urls:
                continue
            found += bool(urls)
            w.writerow([r["package_id"], r["held_date"], r["committee_code"], comm, " ".join(urls)]); f.flush()
            if i % 100 == 0:
                print(i, len(targets), "found", found, flush=True)
        print("DONE", len(targets), "targets;", found, "with a recording", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
