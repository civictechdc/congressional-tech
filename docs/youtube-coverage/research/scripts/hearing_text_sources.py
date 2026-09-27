"""
Where the text of each committee meeting since the 113th Congress can be found.

    python docs/youtube-coverage/research/scripts/hearing_text_sources.py [--youtube-dir ~/hearing-text/youtube] [--senate-dir ~/hearing-text/senate]

One row per Congress.gov meeting record (hearings, markups, business meetings; scheduled or
rescheduled), with the GPO transcript(s) matched to it, its recordings (Congress.gov's video
link, a tracked video carrying its event ID whatever its length, or a tracked video of the
committee posted within a day before to three days after with a matching title: the same
rules the matcher uses for printed hearings), and which of those has text: `gpo` (a printed transcript),
`youtube_captions` / `senate_captions` (a caption track fetched by `youtube-captions` or
`senate-captions`), `video_no_captions`, or `no_video`. Writes
docs/youtube-coverage/research/data/hearing_text_sources.csv, plus meetings_without_records.csv
for the meetings with none of those, and prints the totals.
"""
import argparse, collections, csv, gzip, json, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages/congress_api/src")); sys.path.insert(0, str(ROOT / "packages/congress_shared/src"))
import datetime as dt  # noqa: E402
from congress_api.gpo.match import ALIAS, EVENT_ID, VIDEO_ID, similarity, words  # noqa: E402
from congress_api.senate.isvp import COMM, STREAM, archive_url, live_url, parse_player_url, player_url  # noqa: E402

GPO = ROOT / "apps/committee_youtube/data/gpo_hearings.csv"
MEETINGS = ROOT.parent / "pipeline-data/congress_meetings.jsonl.gz"
YOUTUBE = ROOT.parent / "pipeline-data/youtube"
CHANNELS = ROOT / "packages/congress_shared/src/congress_shared/youtube/youtube-accounts.csv"
OUT = ROOT / "docs/youtube-coverage/research/data/hearing_text_sources.csv"
OUT_NONE = ROOT / "docs/youtube-coverage/research/data/meetings_without_records.csv"


_sess = requests.Session()
_sess.mount("https://", requests.adapters.HTTPAdapter(pool_maxsize=32))


def probe_senate_day(comm_day):
    """Player URLs of the recordings the Senate archive has for a committee on a day (plain, A and B names)."""
    comm, day = comm_day
    d = dt.date.fromisoformat(day)
    out = []
    for suffix in ("", "A", "B"):
        fn = f"{comm}{suffix}{d:%m%d%y}"
        for url in (archive_url(comm, fn), live_url(comm, fn)):
            try:
                if _sess.head(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"}).status_code == 200:
                    out.append(player_url(comm, fn)); break
            except requests.RequestException:
                pass
    return out


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
    by_code_day: dict = collections.defaultdict(list)  # (committee code, upload date) -> videos, for date-window matching
    for i, c in enumerate(csv.DictReader(open(CHANNELS))):
        path = YOUTUBE / f"youtube_{i:02d}.json"
        if not path.exists():
            continue
        for t, rows in json.load(open(path)).items():
            if t.startswith("youtube_videos_"):
                for v in rows.values():
                    for a, b in EVENT_ID.findall(v["title"] + " " + v["description"]):
                        vid_by_eid[a or b].append(v["videoId"])
                    by_code_day[(c["systemCode"], v["publishedAt"][:10])].append((v["videoId"], words(v["title"]), v.get("duration") or 0))

    def window_matches(codes, day, title):
        """Tracked videos of the committee posted a day before to three days after, with a similar title
        and at least 20 minutes (a markup's or short hearing's full recording; a few-minute clip isn't)."""
        tw, out = words(title), []
        d0 = dt.date.fromisoformat(day)
        for code in codes:
            for k in range(-1, 4):
                for vid, vw, dur in by_code_day.get((code, (d0 + dt.timedelta(days=k)).isoformat()), []):
                    if dur >= 1200 and similarity(tw, vw) >= 0.5:
                        out.append(vid)
        return out
    yt_caps = {r["video_id"]: r["kind"] for r in csv.DictReader(open(Path(youtube_dir).expanduser() / "captions_index.csv"))} if (Path(youtube_dir).expanduser() / "captions_index.csv").exists() else {}
    sen_caps = {r["filename"]: r["kind"] for r in csv.DictReader(open(Path(senate_dir).expanduser() / "captions_index.csv"))} if (Path(senate_dir).expanduser() / "captions_index.csv").exists() else {}
    meetings = []
    with gzip.open(MEETINGS, "rt", encoding="utf-8") as f:
        for line in f:
            m = json.loads(line)
            if m.get("meetingStatus") in ("Scheduled", "Rescheduled") and int(m.get("congress", 0)) >= 113:
                meetings.append(m)
    ## Meetings with no Congress.gov video link: does the Senate player's archive have a recording for the committee that day?
    ## Senate meetings, and joint bodies the Senate studio records (JEC, Helsinki, the China commissions)
    probe_days = sorted({(COMM[c["systemCode"][:4] + "00"], m["date"][:10]) for m in meetings
                         if m.get("chamber") != "House" and not m.get("videos") and any(COMM.get(c["systemCode"][:4] + "00") in STREAM for c in m.get("committees", []))
                         for c in m.get("committees", []) if COMM.get(c["systemCode"][:4] + "00") in STREAM})
    probed = dict(zip(probe_days, ThreadPoolExecutor(12).map(probe_senate_day, probe_days)))
    print(f"senate.gov probe: {len(probe_days)} committee-days without a Congress.gov link, recordings for {sum(1 for v in probed.values() if v)}")
    rows, totals = [], collections.Counter()
    for m in meetings:
        if True:  # (body kept at its indent)
            codes = list(dict.fromkeys(ALIAS.get(c["systemCode"][:4] + "00", c["systemCode"][:4] + "00") for c in m.get("committees", [])))
            packages = set(by_eid.get(m["eventId"], ())) | {p for c in codes for p in by_day.get((c, m["date"][:10]), ())}
            urls = [v.get("url", "") for v in (m.get("videos") or [])]
            youtube = list(dict.fromkeys([VIDEO_ID.search(u).group(1) for u in urls if VIDEO_ID.search(u)] + vid_by_eid.get(m["eventId"], [])
                                         + (window_matches(codes, m["date"][:10], m.get("title") or "") if not packages else [])))
            senate = [u for u in urls if parse_player_url(u)] or [u for c in codes for u in probed.get((COMM.get(c), m["date"][:10]), [])]
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
                         "youtube_ids": " ".join(youtube), "senate_urls": " ".join(senate), "text_source": source,
                         "documents": "yes" if (m.get("witnessDocuments") or m.get("meetingDocuments")) else "no"})
            totals[(m.get("chamber", ""), source)] += 1
    rows.sort(key=lambda r: (r["date"], r["event_id"]))
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print(len(rows), "meetings ->", OUT.relative_to(ROOT))
    ## the meetings with nothing: no print, no recording found anywhere, no captions
    none_rows = [r for r in rows if r["text_source"] == "no_video"]
    with open(OUT_NONE, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["event_id", "congress", "chamber", "type", "date", "committees", "title", "documents"]); w.writeheader()
        w.writerows([{k: r[k] for k in w.fieldnames} for r in none_rows])
    print(len(none_rows), "meetings with no print, recording or captions ->", OUT_NONE.relative_to(ROOT),
          f"({sum(1 for r in none_rows if r['documents'] == 'yes')} with witness or meeting documents, {sum(1 for r in none_rows if r['documents'] == 'no')} bare calendar entries)")
    for chamber in ("House", "Senate", "NoChamber"):
        n = sum(v for (ch, _), v in totals.items() if ch == chamber)
        if n:
            print(f"  {chamber} ({n:,}): " + ", ".join(f"{s} {totals[(chamber, s)]:,} ({totals[(chamber, s)] / n:.0%})" for s in ("gpo", "youtube_captions", "senate_captions", "video_no_captions", "no_video") if totals[(chamber, s)]))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--youtube-dir", default="~/hearing-text/youtube"); p.add_argument("--senate-dir", default="~/hearing-text/senate")
    a = p.parse_args(); main(a.youtube_dir, a.senate_dir)
