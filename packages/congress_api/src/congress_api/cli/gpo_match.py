"""Cli: gpo match."""

import argparse
import collections
import csv
import datetime as dt
import gzip
import json
import logging
from pathlib import Path

from congress_shared.globals import (
    DATA_DIR,
    DEFAULT_CHANNELS_CSV,
    DEFAULT_GPO_HEARINGS_FILE,
    DEFAULT_HEARING_VIDEOS_FILE,
    DEFAULT_MEETINGS_FILE,
    add_global_args,
)

from congress_api.matching.committees import ALIAS, codes_of
from congress_api.matching.gpo_videos import (
    EVENT_ID,
    SENATE_VIDEO,
    VIDEO_ID,
    candidates,
    dates_in_text,
    is_clip,
    matching_days,
    words,
)

DEFAULT_OVERRIDES_FILE = DATA_DIR / "hearing_video_overrides.csv"


COLUMNS = ["package_id", "congress", "chamber", "committee_code", "held_date", "hearing_dates", "record_type",
           "status", "video_ids", "channels", "method", "score", "video_minutes", "flags", "source", "note"]


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
            for code in codes_of(m):
                out[code][m["date"][:10]].append(rec)
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
        h["_dates"] = matching_days(h)
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
