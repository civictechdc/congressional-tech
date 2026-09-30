"""Durable GPO hearing ↔ video verdicts.

``gpo_videos.candidates`` scores evidence. This module assigns each video, applies
research overrides, and builds the CSV row.

- Each video goes to its best-scoring hearing. Hearings on the same day may share a
  video; hearings on different days may not.
- Evidence under 90 is a clip, not a full recording, when the video is under 20
  minutes, or under 30 minutes with a member-clip title.
- A research "no video" / "clips only" verdict yields to score 90+, or to score 70+
  totaling at least 30 minutes, unless ``lock=yes``.
- Off-YouTube recordings become ``full_recording_offsite`` only when YouTube has no
  full recording: a senate.gov player link, or a ``found_offsite`` override.
"""

import collections
import datetime as dt

from congress_api.matching.committees import ALIAS
from congress_api.matching.gpo_videos import candidates, is_clip, matching_days, words

COLUMNS = ["package_id", "congress", "chamber", "committee_code", "held_date", "hearing_dates", "record_type",
           "status", "video_ids", "channels", "method", "score", "video_minutes", "flags", "source", "note"]

_NEGATIVE = ("no_video_found", "partial_only")
_CURATED_FOUND = ("found_tracked", "found_untracked")
_OFFSITE_FALLBACK = ("no_video_found", "clips_only", "before_channel", "committee_not_tracked")
_OVERRIDE_STATUS = {"partial_only": "clips_only", "no_video_found": "no_video_found", "not_public": "not_public"}


def _prepare(hearings):
    for hearing in hearings:
        hearing["committee_code"] = ALIAS.get(hearing["committee_code"], hearing["committee_code"])
        hearing["_dates"] = matching_days(hearing)
    on_day = collections.Counter((h["committee_code"], day) for h in hearings for day in h["_dates"])
    titles = collections.defaultdict(list)
    for hearing in hearings:
        for day in hearing["_dates"]:
            titles[(hearing["committee_code"], day)].append(words(hearing["title"]))
    return on_day, titles


def _evidence(hearings, videos_by_code, meetings, on_day, titles):
    pairs, clips, offsite = [], collections.defaultdict(list), collections.defaultdict(dict)
    for hearing in hearings:
        if not hearing["_dates"]:
            continue
        videos = videos_by_code.get(hearing["committee_code"], [])
        for score, method, video in candidates(hearing, videos, meetings, on_day, titles):
            if video.get("offsite"):
                urls = offsite[hearing["package_id"]]
                urls[video["videoId"]] = max(score, urls.get(video["videoId"], 0))
            elif score < 90 and is_clip(video):
                clips[hearing["package_id"]].append(video)
            else:
                pairs.append((score, method, hearing["package_id"], video))
    return pairs, clips, offsite


def _closeness(pair, by_pid):
    video, hearing = pair[3], by_pid[pair[2]]
    if not video.get("published"):
        return 0
    published = dt.date.fromisoformat(video["published"])
    return -min(abs((published - dt.date.fromisoformat(day)).days) for day in hearing["_dates"])


def _assign(pairs, hearings, videos_by_code, overrides):
    """Greedy best-score assignment. Curated videos are reserved first; ties prefer the nearer upload."""
    by_pid = {h["package_id"]: h for h in hearings}
    fetched = {v["videoId"]: v for videos in videos_by_code.values() for v in videos}
    assigned, video_days = collections.defaultdict(list), {}
    for package_id, override in overrides.items():
        if package_id not in by_pid or override["verdict"] not in _CURATED_FOUND:
            continue
        for video_id in override["video_ids"].split():
            video = fetched.get(video_id) or {"videoId": video_id, "channel": override["channel"], "duration": None, "audio_only": False}
            assigned[package_id].append((99, "research", video))
            video_days.setdefault(video_id, set()).update(by_pid[package_id]["_dates"])
    ranked = sorted(pairs, key=lambda pair: (pair[0], _closeness(pair, by_pid)), reverse=True)
    for score, method, package_id, video in ranked:
        if any(item[2]["videoId"] == video["videoId"] for item in assigned[package_id]):
            continue
        days = set(by_pid[package_id]["_dates"])
        taken = video_days.get(video["videoId"])
        if taken is not None and not (taken & days):
            continue
        if package_id in overrides and overrides[package_id]["verdict"] in _CURATED_FOUND:
            continue
        assigned[package_id].append((score, method, video))
        video_days.setdefault(video["videoId"], set()).update(days)
    return assigned, video_days


def _automatic_status(hearing, code, tracked_codes, first_video):
    if hearing.get("record_type") == "errata":
        return "not_public", "errata cover sheet, not a proceeding"
    if code not in tracked_codes:
        return "committee_not_tracked", ""
    if not hearing["_dates"]:
        return "no_video_found", "GPO record has no hearing date to match on"
    if code not in first_video or max(hearing["_dates"]) < first_video[code]:
        return "before_channel", ""
    return "no_video_found", ""


def _verdict(hearing, assigned, clips, offsite, video_days, override, tracked_codes, first_video):
    package_id, code = hearing["package_id"], hearing["committee_code"]
    got = list(assigned.get(package_id, []))
    best = max((item[0] for item in got), default=0)
    flags, note, source = [], "", "auto"
    total_seconds = sum(item[2].get("duration") or 0 for item in got)
    beats_negative = best >= 90 or (best >= 70 and total_seconds >= 1800)
    if override and override.get("lock") == "yes":
        got = [item for item in got if item[1] == "research"]
    if override and override["verdict"] in _NEGATIVE and not beats_negative:
        got = []
    offsite_host = ""
    if got and not (override and override["verdict"] == "not_public" and best < 90):
        status = "full_recording"
        if override and override["verdict"] in _NEGATIVE:
            note = f"research verdict was {override['verdict']}; newer evidence found a recording"
        if any(item[1] == "research" for item in got):
            source, note = "research", override.get("note", "")
    elif override and override["verdict"] != "found_offsite":
        status = _OVERRIDE_STATUS.get(override["verdict"], override["verdict"])
        source, note = "research", override.get("note", "")
    elif clips.get(package_id):
        status = "clips_only"
    else:
        status, note = _automatic_status(hearing, code, tracked_codes, first_video)
    offsite_urls, offsite_method = "", ""
    if status in _OFFSITE_FALLBACK:
        if override and override["verdict"] == "found_offsite":
            status, source, note = "full_recording_offsite", "research", override.get("note", "")
            offsite_urls, offsite_method, offsite_host = override["video_ids"], "research", override["channel"]
        elif offsite.get(package_id):
            status, offsite_method = "full_recording_offsite", "congress.gov link (senate.gov)"
            offsite_urls, offsite_host, best = " ".join(sorted(offsite[package_id])), "senate.gov", max(offsite[package_id].values())
    videos = [item[2] for item in got] if status == "full_recording" else []
    if any(video.get("audio_only") for video in videos):
        flags.append("audio_only")
    if hearing["hearing_dates"]:
        covered = {day for day in hearing["_dates"] for item in got
                   if item[2].get("published") and abs((dt.date.fromisoformat(item[2]["published"]) - dt.date.fromisoformat(day)).days) <= 3}
        flags.append(f"volume_days_with_video={len(covered)}/{len(hearing['_dates'])}")
    shared_days = {day for video in videos for day in video_days.get(video["videoId"], ())} - set(hearing["_dates"])
    if shared_days:
        flags.append("video_shared_with_same_day_hearing")
    minutes = sum(video["duration"] for video in videos if video.get("duration")) // 60 if any(video.get("duration") for video in videos) else ""
    return {
        "package_id": package_id, "congress": hearing["congress"], "chamber": hearing["chamber"], "committee_code": code,
        "held_date": hearing["held_date"], "hearing_dates": hearing["hearing_dates"], "record_type": hearing.get("record_type", "hearing"),
        "status": status,
        "video_ids": offsite_urls if status == "full_recording_offsite" else " ".join(video["videoId"] for video in videos),
        "channels": offsite_host if status == "full_recording_offsite" else " ".join(sorted({video["channel"] for video in videos if video.get("channel")})),
        "method": offsite_method if status == "full_recording_offsite" else "; ".join(sorted({item[1] for item in got})) if videos else "",
        "score": best if videos or status == "full_recording_offsite" else "",
        "video_minutes": minutes, "flags": " ".join(flags), "source": source, "note": note,
    }


def decide(hearings, videos_by_code, meetings, overrides=None, tracked_codes=()):
    """CSV-shaped verdict rows. ``overrides`` is package_id -> research row; empty skips them."""
    overrides = overrides or {}
    tracked = set(tracked_codes)
    on_day, titles = _prepare(hearings)
    pairs, clips, offsite = _evidence(hearings, videos_by_code, meetings, on_day, titles)
    assigned, video_days = _assign(pairs, hearings, videos_by_code, overrides)
    first_video = {code: min(video["published"] for video in videos) for code, videos in videos_by_code.items() if videos}
    rows = [_verdict(hearing, assigned, clips, offsite, video_days, overrides.get(hearing["package_id"]), tracked, first_video)
            for hearing in hearings]
    rows.sort(key=lambda row: (row["held_date"], row["package_id"]))
    return rows
