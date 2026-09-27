"""
Write the senate.gov archive probe's hits into hearing_video_overrides.csv as found_offsite rows.

    python senate_probe_overrides.py docs/youtube-coverage/research/data/senate_isvp_probe.csv

A hearing that already has a recording on YouTube (found_tracked / found_untracked) or off it
keeps that row; a research "no video" or "clips only" verdict is replaced, with the old verdict
kept in the note; hearings with no row get one. The last probe row per package wins (the probe
appends retries).
"""
import csv, sys

probe = {}
for r in csv.DictReader(open(sys.argv[1])):
    probe[r["package_id"]] = r
path = "apps/committee_youtube/data/hearing_video_overrides.csv"
rows = list(csv.DictReader(open(path))); cols = list(rows[0].keys()); ov = {r["package_id"]: r for r in rows}
added = replaced = 0
for r in sorted(probe.values(), key=lambda r: (r["held_date"], r["package_id"])):
    if not r["urls"]:
        continue
    fn = [u.split("filename=")[1] for u in r["urls"].split()]
    note = f"senate.gov archive probe (Sept 2026): recording {' and '.join(fn)} exists on the Senate Recording Studio's player for this committee and day" + (" (several hearings that day share it)" if " " in r["urls"] else "")
    prev = ov.get(r["package_id"])
    if prev:
        if prev["verdict"] in ("found_tracked", "found_untracked", "found_offsite"):
            continue
        prev.update(verdict="found_offsite", video_ids=r["urls"], channel="senate.gov", lock="", note=f"{note} (research verdict was {prev['verdict']})"); replaced += 1
    else:
        rows.append({"package_id": r["package_id"], "verdict": "found_offsite", "video_ids": r["urls"], "channel": "senate.gov", "lock": "", "note": note}); added += 1
with open(path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
print(f"added {added}, replaced {replaced}")
