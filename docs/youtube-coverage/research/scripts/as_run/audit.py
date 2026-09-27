"""Audit the swarm's results: completeness, valid verdicts, and every claimed video resolves to the claimed channel."""
import glob, json, os, sys, collections, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import yt, requests

W = os.path.dirname(os.path.abspath(__file__))
VERDICTS = {"found_tracked", "found_untracked", "partial_only", "not_public", "no_video_found"}
batches = sorted(glob.glob(f"{W}/possible_*.json") + glob.glob(f"{W}/novideo_*.json"))
rows, problems, status = {}, [], {}
for b in batches:
    name = os.path.basename(b)[:-5]
    packets = {p["package_id"]: p for p in json.load(open(b))}
    res_path = f"{W}/results/{name}.jsonl"
    got = collections.defaultdict(list)
    if os.path.exists(res_path):
        for i, line in enumerate(open(res_path)):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                problems.append((name, f"line {i+1}: bad JSON")); continue
            got[r.get("package_id")].append(r)
    missing = [p for p in packets if p not in got]
    extra = [p for p in got if p not in packets]
    dup = [p for p, v in got.items() if len(v) > 1]
    status[name] = (len(packets), len(packets) - len(missing), len(dup), len(extra))
    for pid, rs in got.items():
        if pid not in packets:
            continue
        r = rs[-1]  # last write wins
        p = packets[pid]
        if r.get("verdict") not in VERDICTS:
            problems.append((name, pid, f"bad verdict {r.get('verdict')}"))
        r["_batch"], r["_packet"] = name, p
        rows[pid] = r

## verify video claims
tracked_all = set()
for r in rows.values():
    tracked_all |= {h.lower() for h in r["_packet"]["tracked_channels"]}
checks = collections.Counter()
for pid, r in rows.items():
    if r.get("verdict") not in ("found_tracked", "found_untracked", "partial_only"):
        continue
    vids = r.get("video_ids") or []
    if r["verdict"] != "partial_only" and not vids:
        problems.append((r["_batch"], pid, "found_* with no video_ids")); checks["no_ids"] += 1; continue
    tracked = {h.lower() for h in r["_packet"]["tracked_channels"]}
    for v in vids:
        o = yt.oembed(v)
        if "channel_url" not in o:
            ## 401 = public video with embedding disabled; oembed can't name its channel
            code = requests.get("https://www.youtube.com/oembed", params={"url": f"https://www.youtube.com/watch?v={v}", "format": "json"}, timeout=30).status_code
            if code == 401 or yt.local_find_video(v):
                checks["embed_disabled_or_local"] += 1; continue
            problems.append((r["_batch"], pid, f"video {v} does not resolve (HTTP {code})")); checks["unresolved"] += 1; continue
        handle = o["channel_url"].rstrip("/").split("/")[-1].lower()
        if r["verdict"] == "found_tracked" and handle not in tracked:
            ## a video on a different tracked committee's channel is still "tracked" by us, but flag it
            problems.append((r["_batch"], pid, f"found_tracked but {v} is on {handle}, not {sorted(tracked)}"))
            checks["tracked_mismatch"] += 1
        elif r["verdict"] == "found_untracked" and handle in tracked:
            checks["untracked_is_tracked"] += 1
        else:
            checks["ok"] += 1
        lv = yt.local_find_video(v)
        if lv and r["verdict"] == "found_tracked":
            gap = (dt.date.fromisoformat(lv["publishedAt"]) - dt.date.fromisoformat(r["_packet"]["held_date"])).days
            if not -3 <= gap <= 60:
                problems.append((r["_batch"], pid, f"video {v} published {gap} days from hearing"))
                checks["date_far"] += 1

print("batch: packets / answered / duplicates / extras")
for k, v in status.items():
    print(f"  {k}: {v}")
print("verdicts:", collections.Counter(r.get("verdict") for r in rows.values()))
print("confidence by verdict:", collections.Counter((r.get("verdict"), r.get("confidence")) for r in rows.values()))
print("video checks:", dict(checks))
print(f"{len(problems)} problems")
for p in problems[:60]:
    print("  ", p)
json.dump({pid: {k: v for k, v in r.items() if k != "_packet"} for pid, r in rows.items()}, open(f"{W}/results/_merged.json", "w"))
