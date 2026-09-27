"""
Rebuild hearing_video_verdicts.csv from the saved research files, offline.

    python docs/youtube-coverage/research/scripts/aggregate.py [--out PATH]

Steps (the same ones run during the September 2026 research):
  1. Automatic matching of every GPO hearing against tracked-channel videos
     (event ID in the video text, else same committee within -1..+3 days with
     a similar title or the subcommittee's name in the title).
  2. The 2,198 hearings automatic matching couldn't place get the research
     agents' verdicts (agent_results/possible_*.jsonl, novideo_*.jsonl).
  3. Adversarial verification outcomes are applied (verify_*.jsonl).
  4. "found_untracked" claims whose videos are all on some tracked channel are
     reclassified as found_tracked (channels in data/untracked_claim_video_channels.json).
  5. Videos matched to hearings on different dates keep only the closest-dated
     hearing; other automatic matches in those groups become "unconfirmed".

Inputs come from the repo (GPO hearings, YouTube channel data, channel list)
and from this research folder. Nothing is fetched from the network.
"""
import argparse, collections, csv, datetime as dt, glob, json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
REPO = os.path.abspath(os.path.join(RESEARCH, "..", "..", ".."))
CHANNELS_CSV = f"{REPO}/packages/congress_shared/src/congress_shared/youtube/youtube-accounts.csv"
## YouTube TinyDBs and GPO CSV as they were when the research ran (commit 8247617);
##  override with --data-dir, e.g. a `git worktree add /tmp/r 8247617` checkout
YT_DIR = f"{REPO}/apps/committee_youtube/data"
GPO_CSV = f"{YT_DIR}/gpo_hearings.csv"

STOP = set("the a an of and to in on for with from at by is are be as or its it this that hearing hearings "
           "subcommittee committee house u.s. us part examining examine review oversight".split())
FOUND = ("found_tracked", "found_untracked")
AUTO_OK = ("event_id", "date+title", "date+subcommittee")
COLUMNS = ["package_id", "held_date", "congress", "chamber", "committee_code", "committee_name", "subcommittees",
           "title", "source", "verdict", "confidence", "video_ids", "channel", "evidence", "verification",
           "verdict_note", "shared_video", "prior_status", "transcript_url"]


def words(s):
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP and len(w) > 2}


def load_youtube(channels):
    """Videos per committee code, event IDs seen in video text, and videoId -> first stored copy."""
    vids, by_event, first_copy = collections.defaultdict(list), {}, {}
    for i, row in enumerate(channels):
        path = f"{YT_DIR}/youtube_{i:02d}.json"
        if not os.path.exists(path):
            continue
        for table, rows in json.load(open(path)).items():
            if not table.startswith("youtube_videos_"):
                continue
            for v in rows.values():
                v["_w"] = words(v["title"])
                vids[row["systemCode"]].append((dt.date.fromisoformat(v["publishedAt"][:10]), v))
                first_copy.setdefault(v["videoId"], v)
                for e in re.findall(r"(?<!\d)(1\d{5})(?!\d)", v["title"] + " " + v["description"]):
                    by_event.setdefault(e, v)
    return vids, by_event, first_copy


def auto_match(gpo, vids, by_event):
    """Step 1: automatic matching. Returns package_id -> (how, videoId)."""
    tracked = set(vids)
    out = {}
    for r in gpo:
        how, best, score = "", None, 0
        if r["event_id"] and r["event_id"] in by_event:
            how, best = "event_id", by_event[r["event_id"]]
        elif r["committee_code"] in tracked:
            held = dt.date.fromisoformat(r["held_date"])
            gw, score, sub_hit = words(r["title"]), -1, None
            subs = [words(x) for x in r["subcommittees"].split(";") if x.strip()]
            for day, v in vids[r["committee_code"]]:
                if -1 <= (day - held).days <= 3:
                    s = len(gw & v["_w"]) / max(1, min(len(gw), len(v["_w"])))
                    if s > score:
                        score, best = s, v
                    if subs and sub_hit is None and any(sw and sw <= v["_w"] for sw in subs):
                        sub_hit = v
            if best is not None and score >= 0.5:
                how = "date+title"
            elif sub_hit is not None:
                how, best = "date+subcommittee", sub_hit
            elif best is not None:
                how = "date_only"
        out[r["package_id"]] = (how, (best or {}).get("videoId"))
    return out


def read_jsonl(*patterns):
    """package_id -> last line written for it, across files in sorted order."""
    out = {}
    for f in sorted(f for p in patterns for f in glob.glob(p)):
        for line in open(f):
            line = line.strip()
            if line:
                r = json.loads(line)
                out[r["package_id"]] = r
    return out


def main(out_path, data_dir=None, channels_csv=None):
    global YT_DIR, GPO_CSV, CHANNELS_CSV
    if data_dir:
        YT_DIR, GPO_CSV = data_dir, f"{data_dir}/gpo_hearings.csv"
    if channels_csv:
        CHANNELS_CSV = channels_csv
    channels = list(csv.DictReader(open(CHANNELS_CSV)))
    gpo = list(csv.DictReader(open(GPO_CSV)))
    vids, by_event, first_copy = load_youtube(channels)
    auto = auto_match(gpo, vids, by_event)

    ## the research input list (hearings automatic matching couldn't place) and their prior status
    url2pkg = {g["html_url"]: g["package_id"] for g in gpo}
    prior = {url2pkg[r["transcript_url"]]: r["youtube_status"]
             for r in csv.DictReader(open(f"{RESEARCH}/data/swarm_input_hearings.csv"))}
    research = {p: r for p, r in read_jsonl(f"{RESEARCH}/agent_results/possible_*.jsonl", f"{RESEARCH}/agent_results/novideo_*.jsonl").items() if p in prior}
    missing = set(prior) - set(research)
    assert not missing, f"{len(missing)} researched hearings have no agent verdict"

    ## step 2: automatic verdicts + agent verdicts
    rows = []
    for g in gpo:
        pid, congress = g["package_id"], int(g["congress"])
        if congress < 113:
            continue
        row = {"package_id": pid, "held_date": g["held_date"], "congress": congress, "chamber": g["chamber"],
               "committee_code": g["committee_code"], "committee_name": g["committee_name"],
               "subcommittees": g["subcommittees"], "title": g["title"], "transcript_url": g["html_url"]}
        if pid in research:
            r = research[pid]
            row.update(source="swarm", verdict=r["verdict"], confidence=r["confidence"],
                       video_ids=" ".join(r.get("video_ids") or []), channel=r.get("channel", ""),
                       evidence=r["evidence"], prior_status=prior[pid])
        elif auto[pid][0] in AUTO_OK:
            how, vid = auto[pid]
            row.update(source="auto", verdict="found_tracked", confidence="medium" if how == "date+subcommittee" else "high",
                       video_ids=vid or "", channel="", evidence=f"automatic match ({how})", prior_status="matched automatically")
        else:
            row.update(source="excluded", verdict="before_channel_existed", confidence="", video_ids="", channel="",
                       evidence="held before the committee's earliest tracked video", prior_status="")
        row.update(verification="", verdict_note="", shared_video="")
        rows.append(row)
    rows.sort(key=lambda r: (r["held_date"], r["package_id"]))
    by_id = {r["package_id"]: r for r in rows}

    ## step 3: adversarial verification
    for pid, v in read_jsonl(f"{RESEARCH}/agent_results/verify_*.jsonl").items():
        r = by_id[pid]
        r["verification"] = v["outcome"]
        if v["outcome"] in ("refuted", "revised"):
            old = r["verdict"]
            r["verdict"] = v["corrected_verdict"]
            r["video_ids"] = " ".join(v.get("video_ids") or [])
            r["channel"] = v.get("channel", "")
            r["evidence"] = f"{v['evidence']} [verification {v['outcome']}; first pass: {old}]"

    ## step 4: off-channel claims that are really on a tracked channel
    tracked_handles = {h.strip().lower() for c in channels for h in [c["handle"]] + c["secondary"].split(";") if h.strip()}
    video_channel = json.load(open(f"{RESEARCH}/data/untracked_claim_video_channels.json"))
    for r in rows:
        if r["verdict"] == "found_untracked" and r["video_ids"]:
            handles = {video_channel[v].lower() for v in r["video_ids"].split() if video_channel.get(v)}
            if handles and handles <= tracked_handles:
                r["verdict"] = "found_tracked"
                r["evidence"] += " [reclassified: video is on a tracked channel of another committee]"

    ## step 5: one video matched to hearings on different dates
    uses = collections.defaultdict(list)
    for r in rows:
        if r["verdict"] in FOUND:
            for v in r["video_ids"].split():
                uses[v].append(r)
    shared = {v: rs for v, rs in uses.items() if len(rs) > 1}
    for v, rs in shared.items():
        for r in rs:
            r["shared_video"] = (r["shared_video"] + " " + v).strip()
    for v, rs in shared.items():
        if len({r["held_date"] for r in rs}) == 1:
            continue  # same day: joint hearings or several packages for one proceeding
        copy = first_copy.get(v)
        pub = dt.date.fromisoformat(copy["publishedAt"][:10]) if copy else None
        keep = sorted(rs, key=lambda r: abs((pub - dt.date.fromisoformat(r["held_date"])).days) if pub else 0)[0]
        for r in rs:
            if r is not keep:
                r["verdict_note"] = "video also matched to a hearing on another date; this match is likely wrong"
    for r in rows:
        if r["verdict_note"] and r["source"] == "auto":
            r["verdict"] = "unconfirmed"

    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} hearings to {out_path}")
    print(collections.Counter(r["verdict"] for r in rows))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=os.path.join(RESEARCH, "..", "hearing_video_verdicts.csv"))
    ap.add_argument("--data-dir", help="Folder with gpo_hearings.csv and youtube_NN.json as of commit 8247617.")
    ap.add_argument("--channels-csv", help="Channel list as of commit 8247617.")
    a = ap.parse_args()
    main(a.out, a.data_dir, a.channels_csv)
