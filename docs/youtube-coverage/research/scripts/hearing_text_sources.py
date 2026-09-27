"""
Where the text of each committee meeting since the 113th Congress can be found.

    python docs/youtube-coverage/research/scripts/hearing_text_sources.py [--youtube-dir ~/hearing-text/youtube] [--senate-dir ~/hearing-text/senate]

One row per Congress.gov meeting record (hearings, markups, business meetings; scheduled or
rescheduled), with the GPO transcript(s) matched to it, its recordings (Congress.gov's video
link; a tracked video carrying its event ID whatever its length; a tracked video of the
committee posted within a day before to three days after with a matching title or naming one
of the same bills, the matcher's rules for printed hearings; a Natural Resources archive upload
titled with the meeting's date and subcommittee; or a recording on the Senate player's archive
for a Senate or joint committee, or for a House committee's joint hearing with its Senate
counterpart), and which of those has text: `gpo` (a printed transcript),
`youtube_captions` / `senate_captions` (a caption track fetched by `youtube-captions` or
`senate-captions`), `video_no_captions`, or `no_video`. Writes
docs/youtube-coverage/research/data/hearing_text_sources.csv, plus meetings_without_records.csv
for the meetings with none of those, and prints the totals.
"""
import argparse, collections, csv, gzip, json, re, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zoneinfo import ZoneInfo

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


## House committees whose joint hearings with their Senate counterpart the Senate studio records
SENATE_COUNTERPART = {"hsvr00": "vetaff", "hsas00": "armed", "hsfa00": "foreign", "hsju00": "judiciary", "hsap00": "approps", "hsag00": "ag", "hsbu00": "budget", "hssm00": "smbiz"}
JOINT_WITH_SENATE = re.compile(r"\bjoint\b.*\bsenate\b|\bsenate\b.*\bjoint\b", re.I | re.S)
BILL = re.compile(r"\b(H\.?\s?R\.?|H\.?\s?J\.?\s?Res\.?|H\.?\s?Con\.?\s?Res\.?|H\.?\s?Res\.?|S\.?\s?J\.?\s?Res\.?|S\.?\s?Con\.?\s?Res\.?|S\.?\s?Res\.?|S\.)\s?(\d{1,5})\b", re.I)
## "3.2.16. EMR. 10:00 AM." or "12/14/2015. EMR Field Hearing. 10:00 AM": Natural Resources' 2016-18 archive titles
DATED_TITLE = re.compile(r"^(\d{1,2})[./](\d{1,2})[./](\d{2}|\d{4})\.?\s+([A-Za-z&]+)\b.*?(\d{1,2}):(\d{2})\s*([AP])\.?M", re.I | re.S)
NR_UNITS = {"FC": "hsii00", "EMR": "hsii06", "FL": "hsii10", "WPO": "hsii13", "OI": "hsii15", "O&I": "hsii15", "IIANA": "hsii24"}
ET = ZoneInfo("America/New_York")


def codes_of(m):
    """A meeting's committee codes at the parent-committee level, through the matcher's aliases."""
    return list(dict.fromkeys(ALIAS.get(c["systemCode"][:4] + "00", c["systemCode"][:4] + "00") for c in m.get("committees", [])))


def senate_comms(m, codes):
    """Senate player streams that may hold a meeting's recording: those of its Senate and joint committees, or,
    for a House committee's joint hearing with its Senate counterpart, the counterpart's stream."""
    if m.get("chamber") != "House":
        return [COMM[c] for c in codes if COMM.get(c) in STREAM]
    if JOINT_WITH_SENATE.search(m.get("title") or ""):
        return [SENATE_COUNTERPART[c] for c in codes if c in SENATE_COUNTERPART]
    return []


def bills(title):
    """Bill numbers named in a title, normalised: {("HR", "2810"), ("SJRES", "7")}."""
    return {(re.sub(r"[\s.]", "", kind).upper(), num) for kind, num in BILL.findall(title)}


def dated_title(title):
    """(date, subcommittee code, minutes past midnight) from a Natural Resources archive title, else None."""
    m = DATED_TITLE.match(title)
    if not m or m.group(4).upper() not in NR_UNITS:
        return None
    mo, d, y, unit, hh, mm, ap = m.groups()
    try:
        day = dt.date(int(y) if len(y) == 4 else 2000 + int(y), int(mo), int(d))
    except ValueError:
        return None
    return day, NR_UNITS[unit.upper()], (int(hh) % 12 + (12 if ap.upper() == "P" else 0)) * 60 + int(mm)


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
    dated: dict = collections.defaultdict(list)  # (committee code, date in the title) -> archive uploads titled with date, unit and hour
    for i, c in enumerate(csv.DictReader(open(CHANNELS))):
        path = YOUTUBE / f"youtube_{i:02d}.json"
        if not path.exists():
            continue
        for t, rows in json.load(open(path)).items():
            if t.startswith("youtube_videos_"):
                for v in rows.values():
                    for a, b in EVENT_ID.findall(v["title"] + " " + v["description"]):
                        vid_by_eid[a or b].append(v["videoId"])
                    by_code_day[(c["systemCode"], v["publishedAt"][:10])].append((v["videoId"], v["title"], v.get("duration") or 0))
                    d = dated_title(v["title"])
                    if d and (v.get("duration") or 0) >= 1200:
                        dated[(c["systemCode"], d[0].isoformat())].append((v["videoId"], d[1], d[2]))

    def window_matches(m, codes):
        """Tracked videos of the committee at least 20 minutes long (a markup's or short hearing's full recording; a
        few-minute clip isn't): posted a day before to three days after the meeting with a similar title or naming one
        of the same bills, or titled with the meeting's date and subcommittee (Natural Resources' 2016-18 archive
        uploads); when that subcommittee met twice that day, the upload whose hour is nearest the meeting's."""
        day, title = m["date"][:10], m.get("title") or ""
        tw, tb, out = words(title), bills(title), []
        d0 = dt.date.fromisoformat(day)
        for code in codes:
            for k in range(-1, 4):
                for vid, vt, dur in by_code_day.get((code, (d0 + dt.timedelta(days=k)).isoformat()), []):
                    if dur >= 1200 and (similarity(tw, words(vt)) >= 0.5 or (tb and tb & bills(vt))):
                        out.append(vid)
            units = {c["systemCode"] for c in m.get("committees", [])}
            same_day = [(vid, minutes) for vid, unit, minutes in dated.get((code, day), []) if unit in units]
            if same_day:
                start = dt.datetime.fromisoformat(m["date"].replace("Z", "+00:00")).astimezone(ET) if "T" in m["date"] else None
                out.append(min(same_day, key=(lambda x: abs(x[1] - start.hour * 60 - start.minute)) if start else (lambda x: 0))[0])
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
    probe_days = sorted({(comm, m["date"][:10]) for m in meetings if not m.get("videos") for comm in senate_comms(m, codes_of(m))})
    probed = dict(zip(probe_days, ThreadPoolExecutor(12).map(probe_senate_day, probe_days)))
    print(f"senate.gov probe: {len(probe_days)} committee-days without a Congress.gov link, recordings for {sum(1 for v in probed.values() if v)}")
    rows, totals = [], collections.Counter()
    for m in meetings:
        if True:  # (body kept at its indent)
            codes = codes_of(m)
            packages = set(by_eid.get(m["eventId"], ())) | {p for c in codes for p in by_day.get((c, m["date"][:10]), ())}
            urls = [v.get("url", "") for v in (m.get("videos") or [])]
            youtube = list(dict.fromkeys([VIDEO_ID.search(u).group(1) for u in urls if VIDEO_ID.search(u)] + vid_by_eid.get(m["eventId"], [])
                                         + (window_matches(m, codes) if not packages else [])))
            senate = [u for u in urls if parse_player_url(u)] or [u for comm in senate_comms(m, codes) for u in probed.get((comm, m["date"][:10]), [])]
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
