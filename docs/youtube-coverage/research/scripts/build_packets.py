"""
Rebuild the research agents' evidence packets (their input batches), offline.

    python docs/youtube-coverage/research/scripts/build_packets.py --out-dir /tmp/packets [--channels-csv PATH]

For each hearing in data/swarm_input_hearings.csv it writes:
- the GPO metadata;
- the committee's tracked channels;
- every tracked video from 2 days before to 7 days after the hearing;
- Congress.gov meeting records for that committee within 2 days.

Hearings are split into 8 "possible" batches (a tracked channel posted something that week) and 8
"novideo" batches (nothing posted, or no usable committee code), grouped by committee then date.

To reproduce the September 2026 packets exactly, pass the channel list as it stood then:
    git show 7f71208:packages/congress_shared/src/congress_shared/youtube/youtube-accounts.csv > /tmp/channels.csv
"""
import argparse, collections, csv, datetime as dt, gzip, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
REPO = os.path.abspath(os.path.join(RESEARCH, "..", "..", ".."))
## YouTube TinyDBs and GPO CSV as they were when the research ran (commit 8247617);
##  override with --data-dir, e.g. a `git worktree add /tmp/r 8247617` checkout
YT_DIR = f"{REPO}/apps/committee_youtube/data"
## meeting records filed under select subcommittees whose videos live on the parent's channels
ALIAS = {"jjec00": "jsec00", "hlvc00": "hsgo00", "hlfd00": "hsju00", "hlqj00": "hsju00"}


def main(out_dir, channels_csv, data_dir=None):
    global YT_DIR
    if data_dir:
        YT_DIR = data_dir
    chan = list(csv.DictReader(open(channels_csv)))
    handles = {r["systemCode"]: [r["handle"]] + [h for h in r["secondary"].split(";") if h.strip()] for r in chan}
    names = {r["systemCode"]: r["committee"] for r in chan}

    vids = collections.defaultdict(list)
    for i, row in enumerate(chan):
        path = f"{YT_DIR}/youtube_{i:02d}.json"
        if not os.path.exists(path):
            continue
        for t, rows in json.load(open(path)).items():
            if t.startswith("youtube_videos_"):
                for v in rows.values():
                    vids[row["systemCode"]].append({"videoId": v["videoId"], "channel": t[15:], "publishedAt": v["publishedAt"][:10],
                                                    "title": v["title"], "description": v["description"][:300]})

    meets = collections.defaultdict(list)
    for line in gzip.open(f"{RESEARCH}/data/congress_gov_meetings_112-119.jsonl.gz", "rt"):
        m = json.loads(line)
        for c in {ALIAS.get(x["systemCode"][:4] + "00", x["systemCode"][:4] + "00") for x in m.get("committees", [])}:
            meets[c].append({"eventId": m["eventId"], "date": m["date"][:10], "type": m.get("type"), "status": m.get("meetingStatus"),
                             "title": (m.get("title") or "")[:200], "committees": [x.get("name", "") for x in m.get("committees", [])],
                             "video_urls": [v.get("url") for v in (m.get("videos") or []) if "congress.gov" not in (v.get("url") or "")],
                             "docs_house_gov": f"https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID={m['eventId']}"})

    gpo = {r["package_id"]: r for r in csv.DictReader(open(f"{YT_DIR}/gpo_hearings.csv"))}
    ## for rows with a blank or bad committee code, the code GPO most often uses for that committee name
    name_code = collections.Counter((r["committee_name"], r["committee_code"]) for r in gpo.values() if r["committee_code"] in names)
    best = {}
    for (n, c), _ in name_code.most_common():
        best.setdefault(n, c)
    url2pkg = {r["html_url"]: p for p, r in gpo.items()}

    packets = []
    for r in csv.DictReader(open(f"{RESEARCH}/data/swarm_input_hearings.csv")):
        p = url2pkg[r["transcript_url"]]
        g = gpo[p]
        code = g["committee_code"] if g["committee_code"] in names else best.get(g["committee_name"], "")
        held = dt.date.fromisoformat(g["held_date"])
        in_window = lambda d: -2 <= (dt.date.fromisoformat(d) - held).days <= 7
        packets.append({
            "package_id": p, "status_so_far": r["youtube_status"], "held_date": g["held_date"], "congress": int(g["congress"]),
            "chamber": g["chamber"], "gpo_committee_code": g["committee_code"], "committee_code_used": code,
            "committee_name": g["committee_name"], "subcommittees": g["subcommittees"], "title": g["title"],
            "event_id": g["event_id"], "serial": g["serial"], "witness_count": g["witness_count"],
            "transcript_html": g["html_url"], "tracked_channels": handles.get(code, []),
            "candidate_videos": sorted([v for v in vids.get(code, []) if in_window(v["publishedAt"])], key=lambda v: v["publishedAt"]),
            "congress_gov_meetings_same_committee_near_date": [m for m in meets.get(code, []) if -2 <= (dt.date.fromisoformat(m["date"]) - held).days <= 2],
        })

    possible = sorted([p for p in packets if p["status_so_far"].startswith("possible")], key=lambda p: (p["committee_code_used"], p["held_date"]))
    rest = sorted([p for p in packets if not p["status_so_far"].startswith("possible")], key=lambda p: (p["committee_code_used"], p["held_date"]))

    def split(lst, n):
        k = -(-len(lst) // n)
        return [lst[i * k:(i + 1) * k] for i in range(n)]

    os.makedirs(out_dir, exist_ok=True)
    for kind, lst in (("possible", possible), ("novideo", rest)):
        for i, batch in enumerate(split(lst, 8)):
            json.dump(batch, open(f"{out_dir}/{kind}_{i + 1:02d}.json", "w"), indent=1)
    print(f"wrote {len(packets)} hearings in 16 batches to {out_dir}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--channels-csv", default=f"{REPO}/packages/congress_shared/src/congress_shared/youtube/youtube-accounts.csv")
    ap.add_argument("--data-dir", help="Folder with gpo_hearings.csv and youtube_NN.json as of commit 8247617.")
    a = ap.parse_args()
    main(a.out_dir, a.channels_csv, a.data_dir)
