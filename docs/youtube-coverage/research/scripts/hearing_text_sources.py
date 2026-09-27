"""
Where the text of each committee meeting since the 113th Congress can be found.

    python docs/youtube-coverage/research/scripts/hearing_text_sources.py [--youtube-dir ~/hearing-text/youtube] [--senate-dir ~/hearing-text/senate]

One row per Congress.gov meeting record (hearings, markups, business meetings; scheduled or
rescheduled), with the GPO transcript(s) matched to it, the recordings Congress.gov or the
YouTube fetch link to it, and which of those has text: `gpo` (a printed transcript),
`youtube_captions` / `senate_captions` (a caption track fetched by `youtube-captions` or
`senate-captions`), `video_no_captions`, or `no_video`. Writes
docs/youtube-coverage/research/data/hearing_text_sources.csv and prints the totals.
"""
import argparse, collections, csv, gzip, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages/congress_api/src")); sys.path.insert(0, str(ROOT / "packages/congress_shared/src"))
from congress_api.gpo.match import EVENT_ID, VIDEO_ID  # noqa: E402
from congress_api.senate.isvp import parse_player_url  # noqa: E402

GPO = ROOT / "apps/committee_youtube/data/gpo_hearings.csv"
MEETINGS = ROOT.parent / "pipeline-data/congress_meetings.jsonl.gz"
YOUTUBE = ROOT.parent / "pipeline-data/youtube"
CHANNELS = ROOT / "packages/congress_shared/src/congress_shared/youtube/youtube-accounts.csv"
OUT = ROOT / "docs/youtube-coverage/research/data/hearing_text_sources.csv"


def main(youtube_dir, senate_dir):
    gpo = [r for r in csv.DictReader(open(GPO)) if int(r["congress"]) >= 113]
    by_eid = collections.defaultdict(set); by_day = collections.defaultdict(set)
    for r in gpo:
        if r["event_id"]:
            by_eid[r["event_id"]].add(r["package_id"])
        for d in (r["hearing_dates"] or r["held_date"]).split(";"):
            if d:
                by_day[(r["committee_code"], d)].add(r["package_id"])
    vid_by_eid = collections.defaultdict(list)
    for i, c in enumerate(csv.DictReader(open(CHANNELS))):
        path = YOUTUBE / f"youtube_{i:02d}.json"
        if not path.exists():
            continue
        for t, rows in json.load(open(path)).items():
            if t.startswith("youtube_videos_"):
                for v in rows.values():
                    if (v.get("duration") or 0) >= 1200:
                        for a, b in EVENT_ID.findall(v["title"] + " " + v["description"]):
                            vid_by_eid[a or b].append(v["videoId"])
    yt_caps = {r["video_id"]: r["kind"] for r in csv.DictReader(open(Path(youtube_dir).expanduser() / "captions_index.csv"))} if (Path(youtube_dir).expanduser() / "captions_index.csv").exists() else {}
    sen_caps = {r["filename"]: r["kind"] for r in csv.DictReader(open(Path(senate_dir).expanduser() / "captions_index.csv"))} if (Path(senate_dir).expanduser() / "captions_index.csv").exists() else {}
    rows, totals = [], collections.Counter()
    with gzip.open(MEETINGS, "rt", encoding="utf-8") as f:
        for line in f:
            m = json.loads(line)
            if m.get("meetingStatus") not in ("Scheduled", "Rescheduled") or int(m.get("congress", 0)) < 113:
                continue
            codes = [c["systemCode"][:4] + "00" for c in m.get("committees", [])]
            packages = set(by_eid.get(m["eventId"], ())) | {p for c in codes for p in by_day.get((c, m["date"][:10]), ())}
            urls = [v.get("url", "") for v in (m.get("videos") or [])]
            youtube = list(dict.fromkeys([VIDEO_ID.search(u).group(1) for u in urls if VIDEO_ID.search(u)] + vid_by_eid.get(m["eventId"], [])))
            senate = [u for u in urls if parse_player_url(u)]
            if packages:
                source = "gpo"
            elif any(yt_caps.get(v) in ("manual", "auto") for v in youtube):
                source = "youtube_captions"
            elif any(sen_caps.get(parse_player_url(u)[1]) == "webvtt" for u in senate):
                source = "senate_captions"
            elif youtube or senate:
                source = "video_no_captions"
            else:
                source = "no_video"
            rows.append({"event_id": m["eventId"], "congress": m["congress"], "chamber": m.get("chamber", ""), "type": m.get("type", ""), "date": m["date"][:10],
                         "committees": ";".join(codes), "title": (m.get("title") or "").strip(), "gpo_packages": " ".join(sorted(packages)),
                         "youtube_ids": " ".join(youtube), "senate_urls": " ".join(senate), "text_source": source})
            totals[(m.get("chamber", ""), source)] += 1
    rows.sort(key=lambda r: (r["date"], r["event_id"]))
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print(len(rows), "meetings ->", OUT.relative_to(ROOT))
    for chamber in ("House", "Senate", "NoChamber"):
        n = sum(v for (ch, _), v in totals.items() if ch == chamber)
        if n:
            print(f"  {chamber} ({n:,}): " + ", ".join(f"{s} {totals[(chamber, s)]:,} ({totals[(chamber, s)] / n:.0%})" for s in ("gpo", "youtube_captions", "senate_captions", "video_no_captions", "no_video") if totals[(chamber, s)]))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--youtube-dir", default="~/hearing-text/youtube"); p.add_argument("--senate-dir", default="~/hearing-text/senate")
    a = p.parse_args(); main(a.youtube_dir, a.senate_dir)
