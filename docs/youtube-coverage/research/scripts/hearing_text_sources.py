"""
Where the text of each committee meeting since the 113th Congress can be found.

    python docs/youtube-coverage/research/scripts/hearing_text_sources.py [--youtube-dir ~/hearing-text/youtube] [--senate-dir ~/hearing-text/senate]

One row per Congress.gov meeting record (hearings, markups, business meetings; scheduled or
rescheduled), with the GPO transcript(s) matched to it, its recordings (Congress.gov's video
link; a tracked video carrying its event ID whatever its length; a tracked video of the
committee posted within a day before to three days after with a matching title or naming one
of the same bills, the matcher's rules for printed hearings; an upload titled with the meeting's
date, or a generic hearing or markup title posted that day, when the committee held nothing else
that day or the title names the meeting's subcommittee; or a recording on the Senate player's archive
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
## Dates in upload titles: "10-29-13 Full Committee Business Meeting", "June 28, 2013 Full Committee Business Meeting",
## and Natural Resources' 2016-18 archive titles "3.2.16. EMR. 10:00 AM." (date, subcommittee, hour)
MONTHS = "january february march april may june july august september october november december".split()
TITLE_DATE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{2}|\d{4})\b|\b(" + "|".join(m[:3] for m in MONTHS) + r")[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})\b", re.I)
TITLE_UNIT_TIME = re.compile(r"^\S+\s+([A-Za-z&]+)\b.*?(\d{1,2}):(\d{2})\s*([AP])\.?M", re.I | re.S)
NR_UNITS = {"FC": "hsii00", "EMR": "hsii06", "FL": "hsii10", "WPO": "hsii13", "OI": "hsii15", "O&I": "hsii15", "IIANA": "hsii24"}
## session uploads under generic titles ("Full Committee Markup", "Business Meeting", "Legislative Hearing | Federal Lands Subcommittee")
HEARING_WORDS = re.compile(r"\bhearing\b", re.I)
MARKUP_WORDS = re.compile(r"\b(markup|mark-up|business meeting|organizational|organizing)\b", re.I)
NAME_STOP = set("house senate committee subcommittee on the and of for".split())
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


def session_kind_fits(meeting_type, title):
    """Does an upload's generic title agree with the meeting's type: a hearing for a Hearing, a markup or business
    meeting for a Markup, either for a Meeting?"""
    hearing, markup = bool(HEARING_WORDS.search(title)), bool(MARKUP_WORDS.search(title))
    return (hearing and not markup) if meeting_type == "Hearing" else markup if meeting_type == "Markup" else (hearing or markup) if meeting_type == "Meeting" else False


def title_dates(title):
    """The calendar dates written in a title (numeric or month-name), as a set."""
    out = set()
    for mo, d, y, mon, d2, y2 in TITLE_DATE.findall(title):
        try:
            out.add(dt.date(int(y) if len(y) == 4 else 2000 + int(y), int(mo), int(d)) if mo else dt.date(int(y2), MONTHS.index(mon.lower()[:3] + {"jan": "uary", "feb": "ruary", "mar": "ch", "apr": "il", "may": "", "jun": "e", "jul": "y", "aug": "ust", "sep": "tember", "oct": "ober", "nov": "ember", "dec": "ember"}[mon.lower()[:3]]) + 1, int(d2)))
        except (ValueError, KeyError):
            pass
    return out


def unit_and_minutes(title):
    """(subcommittee code, minutes past midnight) from a Natural Resources archive title ("3.2.16. EMR. 10:00 AM."), else (None, None)."""
    m = TITLE_UNIT_TIME.match(title)
    if not m or m.group(1).upper() not in NR_UNITS:
        return None, None
    unit, hh, mm, ap = m.groups()
    return NR_UNITS[unit.upper()], (int(hh) % 12 + (12 if ap.upper() == "P" else 0)) * 60 + int(mm)


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
    dated: dict = collections.defaultdict(list)  # (committee code, date in the title) -> uploads of 20+ minutes titled with that date
    for i, c in enumerate(csv.DictReader(open(CHANNELS))):
        path = YOUTUBE / f"youtube_{i:02d}.json"
        if not path.exists():
            continue
        for t, rows in json.load(open(path)).items():
            if t.startswith("youtube_videos_"):
                for v in rows.values():
                    for a, b in EVENT_ID.findall(v["title"] + " " + v["description"]):
                        vid_by_eid[a or b].append(v["videoId"])
                    by_code_day[(c["systemCode"], v["publishedAt"][:10])].append((v["videoId"], v["title"], v.get("duration") or 0, bool(EVENT_ID.search(v["title"] + " " + v["description"]))))
                    if (v.get("duration") or 0) >= 1200:
                        for day in title_dates(v["title"]):
                            dated[(c["systemCode"], day.isoformat())].append((v["videoId"], *unit_and_minutes(v["title"])))

    def window_matches(m, codes, meetings_that_day, units_that_day, parent_words):
        """Tracked videos of the committee at least 20 minutes long (a markup's or short hearing's full recording; a
        few-minute clip isn't) that fit the meeting one of three ways: posted a day before to three days after it with a
        similar title or naming one of the same bills; titled with the meeting's date, when the meeting is the
        committee's only one that day or the title names its subcommittee (Natural Resources' 2016-18 archive uploads,
        nearest hour when that subcommittee met twice); or a session upload, a generic hearing or markup title that
        agrees with the meeting's type and carries no other date and no event ID, posted on the meeting's day (or the
        next, when the committee did not meet then), when the meeting is the committee's only one that day or the
        title names its subcommittee and that subcommittee met only once."""
        day, title = m["date"][:10], m.get("title") or ""
        tw, tb, out = words(title), bills(title), []
        d0 = dt.date.fromisoformat(day)
        units = {c["systemCode"] for c in m.get("committees", [])}
        start = dt.datetime.fromisoformat(m["date"].replace("Z", "+00:00")).astimezone(ET) if "T" in m["date"] else None
        for code in codes:
            sub_words = [set(words(c.get("name", ""))) - parent_words.get(code, set()) - NAME_STOP
                         for c in m.get("committees", []) if not c["systemCode"].endswith("00") and units_that_day[(c["systemCode"], day)] == 1]
            for k in range(-1, 4):
                d = (d0 + dt.timedelta(days=k)).isoformat()
                for vid, vt, dur, tagged in by_code_day.get((code, d), []):
                    if dur < 1200:
                        continue
                    if similarity(tw, words(vt)) >= 0.5 or (tb and tb & bills(vt)):
                        out.append(vid)
                    elif (k == 0 or (k == 1 and meetings_that_day[(code, d)] == 0)) and not tagged and not (title_dates(vt) - {d0}) \
                            and session_kind_fits(m.get("type"), vt) and (meetings_that_day[(code, day)] == 1 or any(sw and sw <= set(words(vt)) for sw in sub_words)):
                        out.append(vid)
            same_day = [(vid, minutes) for vid, unit, minutes in dated.get((code, day), []) if unit in units or (unit is None and meetings_that_day[(code, day)] == 1)]
            if same_day and start and any(minutes is not None for _, minutes in same_day):
                same_day = [min(same_day, key=lambda x: abs((x[1] if x[1] is not None else 10**6) - start.hour * 60 - start.minute))]
            out.extend(vid for vid, _ in same_day)
        return list(dict.fromkeys(out))
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
    ## how many meetings each committee, and each subcommittee, held on each day; the words of each parent committee's name
    meetings_that_day = collections.Counter((c, m["date"][:10]) for m in meetings for c in codes_of(m))
    units_that_day = collections.Counter((c["systemCode"], m["date"][:10]) for m in meetings for c in m.get("committees", []))
    parent_words = {c["systemCode"]: set(words(c["name"])) for m in meetings for c in m.get("committees", []) if c["systemCode"].endswith("00") and c.get("name")}
    print(f"senate.gov probe: {len(probe_days)} committee-days without a Congress.gov link, recordings for {sum(1 for v in probed.values() if v)}")
    rows, totals = [], collections.Counter()
    for m in meetings:
        if True:  # (body kept at its indent)
            codes = codes_of(m)
            packages = set(by_eid.get(m["eventId"], ())) | {p for c in codes for p in by_day.get((c, m["date"][:10]), ())}
            urls = [v.get("url", "") for v in (m.get("videos") or [])]
            youtube = list(dict.fromkeys([VIDEO_ID.search(u).group(1) for u in urls if VIDEO_ID.search(u)] + vid_by_eid.get(m["eventId"], [])
                                         + (window_matches(m, codes, meetings_that_day, units_that_day, parent_words) if not packages else [])))
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
