"""
Match every GPO hearing transcript to the committee YouTube video(s) that record it.

    gpo-match --tinydb_dir DIR --meetings PATH --output-path gpo_hearing_videos.csv

Evidence, strongest first (score in brackets):

  [100] Congress.gov links the video from the meeting record that has the hearing's event ID.
  [ 95] The video's title or description names the hearing's event ID ("EventID=117681",
        "(ID: 117681)"), whenever it was uploaded. Committees did this for years of
        back-catalogue uploads.
  [ 90] Congress.gov links the video from a same-day meeting of the committee with a matching title.
  [ 80] The video names the hearing's date ("031815 -", "7/23/2013.", "Hearing Date: ...") and
        its title or subcommittee matches.
  [ 75] Congress.gov links the video from the committee's only meeting that day.
  [ 70] The video names the hearing's date, and it's the committee's only hearing that day.
  [ 60] Posted 1 day before to 3 days after, with a similar title.
  [ 55] Event ID or Congress.gov evidence for a video posted more than a week after the hearing
        whose title doesn't match it, or matches a hearing held the week it was posted
        (committees mistag videos; see `stale`).
  [ 50] Posted 1 day before to 3 days after, naming the hearing's subcommittee.

Rules:
- Each video goes to its best-scoring hearing. Hearings on the same day may share a
  video (joint hearings, or several GPO packages for one proceeding); hearings on
  different days may not.
- A video found by weaker evidence (score under 90) counts as a clip, not a full recording,
  when it's under 20 minutes, or under 30 minutes with a member-clip title ("Wyden Q&A ...",
  "Chairman Smith Questions Witnesses ...", "Opening Statement ..."). Senate party channels
  post 10-25 minute question rounds for most hearings; measured on the September 2026 data,
  nearly every weak match under 20 minutes was one.
- Multi-hearing volumes (Appropriations "Part N") are matched on every hearing day
  listed in `hearing_dates`.
- Curated verdicts in the overrides file (seeded from the September 2026 research
  pass) apply where they exist. A "no video"/"clips only" verdict gives way to strong
  new evidence (score 90+) or a dated recording of 30+ minutes, unless the row is
  locked (`lock=yes`, for matches that were reviewed and rejected).
- Recordings off YouTube give status `full_recording_offsite` when YouTube has no full
  recording: a senate.gov player link in the hearing's Congress.gov meeting record (the
  Senate hosts its own video), or a `found_offsite` override (C-SPAN, an archived file,
  another site; `video_ids` holds the URLs and `channel` the host).
"""
import argparse
import collections
import csv
import datetime as dt
import gzip
import json
import logging
import os
import re
from pathlib import Path

from congress_shared.globals import (
    DATA_DIR,
    DEFAULT_CHANNELS_CSV,
    DEFAULT_GPO_HEARINGS_FILE,
    DEFAULT_HEARING_VIDEOS_FILE,
    DEFAULT_MEETINGS_FILE,
    DEFAULT_TINYDB_DIR,
    add_global_args,
)

DEFAULT_OVERRIDES_FILE = DATA_DIR / "hearing_video_overrides.csv"
STOP = set("the a an of and to in on for with from at by is are be as or its it this that hearing hearings "
           "subcommittee committee house u.s. us part examining examine review oversight markup meeting full".split())
## meeting records filed under select subcommittees whose videos live on the parent's channels
ALIAS = {"jjec00": "jsec00", "hlvc00": "hsgo00", "hlfd00": "hsju00", "hlqj00": "hsju00"}
CLIP_SECONDS = 1200
CLIP_TITLE_SECONDS = 1800
CLIP_TITLE = re.compile(r"\b(q&a|questions?|opening statement|opening remarks|statement|remarks|round of questions|closing)\b"
                        r"|^(sen\.|senator|rep\.|chairman|chair|ranking member|subcommittee chairman|vice chair)\s", re.I)
EVENT_ID = re.compile(r"(?:event\s*id|\bid)\s*[:=#]?\s*(1\d{5})(?!\d)|house-event/(1\d{5})(?!\d)", re.I)
SENATE_VIDEO = re.compile(r"https?://www\.senate\.gov/isvp/")
VIDEO_ID = re.compile(r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|live/|embed/|shorts/|v/)|youtu\.be/)([\w-]{11})")
MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}
COLUMNS = ["package_id", "congress", "chamber", "committee_code", "held_date", "hearing_dates", "record_type",
           "status", "video_ids", "channels", "method", "score", "video_minutes", "flags", "source", "note"]


def words(s):
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if w not in STOP and len(w) > 2}


def similarity(a, b):
    return len(a & b) / max(1, min(len(a), len(b)))


## words that say nothing about a hearing's topic ("W&M Hearing: Jun 13, 2013 PM Part A")
GENERIC = set("full sub hearing hearings markup markups meeting business session day part live stream livestream "
              "january february march april may june july august september october november december "
              "jan feb mar apr jun jul aug sep sept oct nov dec".split())


def generic_title(title):
    """True when a title is only a date/code label, with no topic words to contradict a date match."""
    return all(w in GENERIC or w.isdigit() or len(w) <= 5 for w in words(title))


def valid_date(y, m, d):
    try:
        return dt.date(y, m, d).isoformat()
    except ValueError:
        return None


def dates_in_text(text):
    """ISO dates written in a video title/description, in the formats committees use."""
    found = set()
    for m, d, y in re.findall(r"(?<!\d)(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})(?!\d)", text):
        y = int(y) + (2000 if len(y) == 2 else 0)
        found.add(valid_date(y, int(m), int(d)))
    for mon, d, y in re.findall(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})", text.lower()):
        found.add(valid_date(int(y), MONTHS[mon], int(d)))
    for code in re.findall(r"(?<!\d)(\d{8})(?!\d)", text):  # 20160107
        found.add(valid_date(int(code[:4]), int(code[4:6]), int(code[6:])))
    for code in re.findall(r"(?<!\d)(\d{6})(?!\d)", text):  # 031815 (MMDDYY) or 140115 (YYMMDD)
        found.add(valid_date(2000 + int(code[4:]), int(code[:2]), int(code[2:4])))
        found.add(valid_date(2000 + int(code[:2]), int(code[2:4]), int(code[4:])))
    found.discard(None)
    return {d for d in found if "2005" <= d <= "2100"}


def is_clip(v):
    """A short video, or a short-ish one titled as a member's questions or statement."""
    d = v.get("duration")
    return d is not None and (d < CLIP_SECONDS or (d < CLIP_TITLE_SECONDS and bool(CLIP_TITLE.search(v.get("title", "")))))


def load_videos(tinydb_dir, channels):
    """Committee code -> list of video dicts from the weekly YouTube fetch."""
    by_code = collections.defaultdict(list)
    for i, row in enumerate(channels):
        path = Path(tinydb_dir) / f"youtube_{i:02d}.json"
        if not path.exists():
            continue
        for table, rows in json.load(open(path)).items():
            if not table.startswith("youtube_videos_"):
                continue
            for v in rows.values():
                text = f"{v['title']} {v['description']}"
                by_code[row["systemCode"]].append({
                    "videoId": v["videoId"], "channel": table[len("youtube_videos_"):],
                    "published": v["publishedAt"][:10], "title": v["title"], "words": words(v["title"]),
                    "dates": dates_in_text(text), "event_ids": {a or b for a, b in EVENT_ID.findall(text)},
                    "duration": v.get("duration"), "audio_only": "audio recording" in text.lower() or "audio only" in text.lower(),
                })
    return by_code


def load_meetings(path):
    """Parent committee code -> date -> meeting records."""
    out = collections.defaultdict(lambda: collections.defaultdict(list))
    if not Path(path).exists():
        logging.warning(f"No meetings file at {path}; Congress.gov evidence skipped")
        return out
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            m = json.loads(line)
            if m.get("meetingStatus") not in ("Scheduled", "Rescheduled"):
                continue
            urls = [v.get("url", "") for v in (m.get("videos") or [])]
            rec = {"eventId": m["eventId"], "title": m.get("title") or "", "words": words(m.get("title")),
                   "subcommittees": [c.get("name", "") for c in m.get("committees", []) if not c["systemCode"].endswith("00")],
                   "videos": [VIDEO_ID.search(u).group(1) for u in urls if VIDEO_ID.search(u)],
                   ## the Senate hosts hearing video on its own player, not YouTube
                   "offsite": [u for u in urls if SENATE_VIDEO.match(u)]}
            for code in {ALIAS.get(c["systemCode"][:4] + "00", c["systemCode"][:4] + "00") for c in m.get("committees", [])}:
                out[code][m["date"][:10]].append(rec)
    return out


def stale(score, v, last_day, title_w, week_titles):
    """Committees mistag videos with another hearing's event ID, and Congress.gov links follow the
    tag. A video uploaded more than a week after this hearing ranks below a same-week title match
    (60) when its title doesn't match this hearing, or matches a hearing held the week it was
    uploaded; the hearing it was really posted for then keeps it. Back-catalogue uploads keep
    their strength: their titles name the hearing and no other hearing claims that week."""
    if not v.get("published") or (dt.date.fromisoformat(v["published"]) - last_day).days <= 7:
        return score
    vw = v.get("words") or words(v.get("title"))
    if similarity(title_w, vw) < 0.5 or any(similarity(t, vw) >= 0.5 for t in week_titles(v["published"])):
        return 55
    return score


def candidates(h, videos, meetings, hearings_on_day, titles_on_day):
    """(score, method, video) evidence for one hearing."""
    code, dates = h["committee_code"], h["_dates"]
    title_w = words(h["title"])

    def week_titles(published):
        """Titles of this committee's other hearings held in the week a video was uploaded (1 day after to 3 days before)."""
        pub = dt.date.fromisoformat(published)
        return [t for k in range(-1, 4) for d in [(pub - dt.timedelta(days=k)).isoformat()] if d not in dates for t in titles_on_day.get((code, d), [])]
    sub_w = [words(re.sub(r"^.*?Subcommittee on ", "", s)) for s in h["subcommittees"].split(";") if s.strip()]
    volume = bool(h["hearing_dates"])
    by_id = {v["videoId"]: v for v in videos}
    out = []

    ## Congress.gov meeting records for this hearing
    event_ids = {h["event_id"]} - {""}
    for day in dates:
        day_meetings = meetings.get(code, {}).get(day, [])
        for m in day_meetings:
            if m["eventId"] in event_ids:
                score = 100
            elif volume:
                ## volumes: a meeting of the same subcommittee that day
                score = 90 if sub_w and any(sw and sw <= words(" ".join(m["subcommittees"])) for sw in sub_w) else 0
            elif similarity(title_w, m["words"]) >= 0.4:
                score = 90
            elif len(day_meetings) == 1:
                score = 75
            else:
                score = 0
            if score:
                ## only a confidently identified meeting's event ID is trusted for
                ##  date-free matching below; a weak identification could pull in
                ##  another hearing's videos
                if score >= 90:
                    event_ids.add(m["eventId"])
                for vid in m["videos"]:
                    v = by_id.get(vid) or {"videoId": vid, "channel": "", "published": day, "duration": None, "audio_only": False}
                    out.append((stale(score, v, dt.date.fromisoformat(max(dates)), title_w, week_titles), "congress.gov link", v))
                for url in m["offsite"]:
                    out.append((score, "congress.gov link (senate.gov)", {"videoId": url, "channel": "senate.gov", "published": day, "duration": None, "audio_only": False, "offsite": True}))

    first_day = min(dates)
    last_day = dt.date.fromisoformat(max(dates))
    for v in videos:
        if v["published"] < (dt.date.fromisoformat(first_day) - dt.timedelta(days=1)).isoformat():
            continue  # uploaded before the hearing
        if event_ids & v["event_ids"]:
            out.append((stale(95, v, last_day, title_w, week_titles), "event ID in video", v))
            continue
        for day in dates:
            if day in v["dates"]:
                sub_hit = any(sw and sw <= v["words"] for sw in sub_w)
                if sub_hit or similarity(title_w, v["words"]) >= 0.5:
                    out.append((80, "date in video + title", v))
                elif hearings_on_day[(code, day)] == 1 and generic_title(v["title"]):
                    ## a bare date label ("W&M Hearing: Jun 13, 2013"); a titled video
                    ##  about something else that day (press conference, other hearing) isn't it
                    out.append((70, "date in video", v))
                break
        else:
            if volume:
                continue  # volume titles are too generic for window matching
            gap = (dt.date.fromisoformat(v["published"]) - dt.date.fromisoformat(h["held_date"])).days
            if -1 <= gap <= 3:
                if similarity(title_w, v["words"]) >= 0.5:
                    out.append((60, "date window + title", v))
                elif any(sw and sw <= v["words"] for sw in sub_w):
                    out.append((50, "date window + subcommittee", v))
    return out


def main(output_path, tinydb_dir, channels_csv_path, gpo_path, meetings_path, overrides_path, coverage_path, no_overrides=False):
    channels = list(csv.DictReader(open(channels_csv_path)))
    tracked_codes = {c["systemCode"] for c in channels}
    videos = load_videos(tinydb_dir, channels)
    first_video = {code: min(v["published"] for v in vs) for code, vs in videos.items() if vs}
    meetings = load_meetings(meetings_path)
    hearings = [h for h in csv.DictReader(open(gpo_path))]
    for h in hearings:
        h["committee_code"] = ALIAS.get(h["committee_code"], h["committee_code"])
        h["_dates"] = sorted(set(filter(None, (h.get("hearing_dates") or "").split(";")))) or [d for d in [h["held_date"]] if d]
    hearings_on_day = collections.Counter((h["committee_code"], d) for h in hearings for d in h["_dates"])
    titles_on_day = collections.defaultdict(list)
    for h in hearings:
        for d in h["_dates"]:
            titles_on_day[(h["committee_code"], d)].append(words(h["title"]))

    overrides = {}
    if not no_overrides and Path(overrides_path).exists():
        overrides = {r["package_id"]: r for r in csv.DictReader(open(overrides_path))}

    ## gather evidence
    pairs, clips = [], collections.defaultdict(list)
    by_pid = {h["package_id"]: h for h in hearings}
    offsite = collections.defaultdict(dict)  # pid -> {url: score}
    for h in hearings:
        if not h["_dates"]:
            continue  # GPO gave no hearing date; nothing to match on
        for score, method, v in candidates(h, videos.get(h["committee_code"], []), meetings, hearings_on_day, titles_on_day):
            if v.get("offsite"):
                offsite[h["package_id"]][v["videoId"]] = max(score, offsite[h["package_id"]].get(v["videoId"], 0))
                continue
            if score < 90 and is_clip(v):
                clips[h["package_id"]].append(v)
                continue
            pairs.append((score, method, h["package_id"], v))

    ## curated overrides first: their videos are reserved for their hearings. A video
    ##  on a tracked channel takes its length, date and channel from the fetch, so
    ##  the flags and minutes are as good as for automatic matches.
    assigned = collections.defaultdict(list)   # pid -> [(score, method, video)]
    video_days = {}                            # videoId -> set of hearing days it's assigned to
    fetched = {v["videoId"]: v for vs in videos.values() for v in vs}
    for pid, o in overrides.items():
        if pid in by_pid and o["verdict"] in ("found_tracked", "found_untracked"):
            for vid in o["video_ids"].split():
                v = fetched.get(vid) or {"videoId": vid, "channel": o["channel"], "duration": None, "audio_only": False}
                assigned[pid].append((99, "research", v))
                video_days.setdefault(vid, set()).update(by_pid[pid]["_dates"])

    ## greedy, best evidence first; ties go to the hearing closest to the upload date
    def closeness(p):
        v, h = p[3], by_pid[p[2]]
        if not v.get("published"):
            return 0
        return -min(abs((dt.date.fromisoformat(v["published"]) - dt.date.fromisoformat(d)).days) for d in h["_dates"])
    for score, method, pid, v in sorted(pairs, key=lambda p: (p[0], closeness(p)), reverse=True):
        if any(a[2]["videoId"] == v["videoId"] for a in assigned[pid]):
            continue
        days = set(by_pid[pid]["_dates"])
        taken = video_days.get(v["videoId"])
        if taken is not None and not (taken & days):
            continue  # already the recording of a hearing on another day
        if pid in overrides and overrides[pid]["verdict"] in ("found_tracked", "found_untracked"):
            continue  # curated videos stand
        assigned[pid].append((score, method, v))
        video_days.setdefault(v["videoId"], set()).update(days)

    ## verdicts
    rows = []
    for h in hearings:
        pid, code = h["package_id"], h["committee_code"]
        got = assigned.get(pid, [])
        o = overrides.get(pid)
        best = max((a[0] for a in got), default=0)
        flags, note, source = [], "", "auto"
        ## a research "no video"/"clips only" verdict gives way to strong new evidence,
        ##  or to a dated recording of at least 30 minutes (e.g. a channel's later re-upload)
        total_seconds = sum(a[2].get("duration") or 0 for a in got)
        beats_negative = best >= 90 or (best >= 70 and total_seconds >= 1800)
        if o and o.get("lock") == "yes":
            got = [a for a in got if a[1] == "research"]  # reviewed verdict: automatic evidence can't overturn it
        if o and o["verdict"] in ("no_video_found", "partial_only") and not beats_negative:
            got = []
        if got and not (o and o["verdict"] == "not_public" and best < 90):
            status = "full_recording"
            if o and o["verdict"] in ("no_video_found", "partial_only"):
                note = f"research verdict was {o['verdict']}; newer evidence found a recording"
            if any(a[1] == "research" for a in got):
                source, note = "research", o.get("note", "")
        elif o and o["verdict"] != "found_offsite":  # an offsite verdict is applied below, after the automatic statuses
            status = {"partial_only": "clips_only", "no_video_found": "no_video_found", "not_public": "not_public"}.get(o["verdict"], o["verdict"])
            source, note = "research", o.get("note", "")
        elif clips.get(pid):
            status = "clips_only"
        elif h.get("record_type") == "errata":
            status = "not_public"
            note = "errata cover sheet, not a proceeding"
        elif code not in tracked_codes:
            status = "committee_not_tracked"
        elif not h["_dates"]:
            status = "no_video_found"
            note = "GPO record has no hearing date to match on"
        elif code not in first_video or max(h["_dates"]) < first_video[code]:
            status = "before_channel"
        else:
            status = "no_video_found"
        offsite_urls, offsite_method = "", ""
        if status in ("no_video_found", "clips_only", "before_channel", "committee_not_tracked"):
            if o and o["verdict"] == "found_offsite":
                status, source, note, offsite_urls, offsite_method = "full_recording_offsite", "research", o.get("note", ""), o["video_ids"], "research"
                offsite_host = o["channel"]
            elif offsite.get(pid):
                status, offsite_method = "full_recording_offsite", "congress.gov link (senate.gov)"
                offsite_urls, offsite_host, best = " ".join(sorted(offsite[pid])), "senate.gov", max(offsite[pid].values())
        vids = [a[2] for a in got] if status == "full_recording" else []
        if any(v.get("audio_only") for v in vids):
            flags.append("audio_only")
        if h["hearing_dates"]:
            covered = {d for d in h["_dates"] for a in got if a[2].get("published") and abs(
                (dt.date.fromisoformat(a[2]["published"]) - dt.date.fromisoformat(d)).days) <= 3}
            flags.append(f"volume_days_with_video={len(covered)}/{len(h['_dates'])}")
        if len({d for v in vids for d in video_days.get(v["videoId"], ())} - set(h["_dates"])):
            flags.append("video_shared_with_same_day_hearing")
        minutes = sum(v["duration"] for v in vids if v.get("duration")) // 60 if any(v.get("duration") for v in vids) else ""
        rows.append({
            "package_id": pid, "congress": h["congress"], "chamber": h["chamber"], "committee_code": code,
            "held_date": h["held_date"], "hearing_dates": h["hearing_dates"], "record_type": h.get("record_type", "hearing"),
            "status": status,
            "video_ids": offsite_urls if status == "full_recording_offsite" else " ".join(v["videoId"] for v in vids),
            "channels": offsite_host if status == "full_recording_offsite" else " ".join(sorted({v["channel"] for v in vids if v.get("channel")})),
            "method": offsite_method if status == "full_recording_offsite" else "; ".join(sorted({a[1] for a in got})) if vids else "",
            "score": best if vids or status == "full_recording_offsite" else "",
            "video_minutes": minutes, "flags": " ".join(flags), "source": source, "note": note,
        })

    rows.sort(key=lambda r: (r["held_date"], r["package_id"]))
    with open(output_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    write_coverage(rows, channels, coverage_path)
    counts = collections.Counter(r["status"] for r in rows)
    logging.info(f"Wrote {len(rows)} hearings to {output_path}: {dict(counts)}")
    return rows


def write_coverage(rows, channels, path):
    """Hearings per congress x committee x status, for dashboards and reports."""
    names = {c["systemCode"]: c["committee"] for c in channels}
    counts = collections.Counter((r["congress"], r["committee_code"], r["status"]) for r in rows)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["congress", "committee_code", "committee_name", "status", "hearings"])
        for (congress, code, status), n in sorted(counts.items(), key=lambda kv: (int(kv[0][0]), kv[0][1], kv[0][2])):
            w.writerow([congress, code, names.get(code, ""), status, n])


def parse_args_and_run():
    parser = argparse.ArgumentParser(description="Match GPO hearing transcripts to committee YouTube videos.")
    add_global_args(parser)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_HEARING_VIDEOS_FILE)
    parser.add_argument("--coverage-path", type=Path, default=None,
                        help="Per congress x committee summary (default: next to --output-path).")
    parser.add_argument("--channels-csv-path", type=Path, default=DEFAULT_CHANNELS_CSV)
    parser.add_argument("--gpo-path", type=Path, default=DEFAULT_GPO_HEARINGS_FILE)
    parser.add_argument("--meetings", type=Path, default=DEFAULT_MEETINGS_FILE)
    parser.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES_FILE)
    parser.add_argument("--no-overrides", action="store_true", help="Automatic evidence only (for evaluating the matcher).")
    args = parser.parse_known_args()[0]
    coverage = args.coverage_path or Path(args.output_path).with_name("gpo_hearing_video_coverage.csv")
    main(args.output_path, args.tinydb_dir, args.channels_csv_path, args.gpo_path, args.meetings,
         args.overrides, coverage, no_overrides=args.no_overrides)


if __name__ == "__main__":
    parse_args_and_run()
