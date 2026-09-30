"""Build the meeting text index from weekly inputs and parsed source outputs.

YouTube ids come from Congress.gov video URLs, event ids named in a video's
title or description, curated non-HTTP recordings, and the ids already assigned
to one of the meeting's packages. Senate player URLs stay on the meeting or its
probed committee day. Package assignment, including clip length, cross-day
exclusivity, and off-YouTube fallback, is not repeated here. Print ownership is
evaluated before caption availability.
"""

import collections
import datetime as dt
import re

from congress_api.matching.captions import text_source
from congress_api.matching.committees import codes_of
from congress_api.matching.gpo_videos import EVENT_ID, VIDEO_ID
from congress_api.matching.meetings import NOT_HELD, TRANSCRIPT, meeting_access, meeting_type
from congress_api.matching.prints import attached_prints, match_prints, same_day_title_groups, title_key
from congress_api.parsers.senate_player import COMM, STREAM, parse_player_url

## House committees whose joint hearings with their Senate counterpart the Senate studio records
SENATE_COUNTERPART = {"hsvr00": "vetaff", "hsas00": "armed", "hsfa00": "foreign", "hsju00": "judiciary", "hsap00": "approps", "hsag00": "ag", "hsbu00": "budget", "hssm00": "smbiz"}


JOINT_WITH_SENATE = re.compile(r"\bjoint\b.*\bsenate\b|\bsenate\b.*\bjoint\b", re.I | re.S)


BILL = re.compile(r"\b(H\.?\s?R\.?|H\.?\s?J\.?\s?Res\.?|H\.?\s?Con\.?\s?Res\.?|H\.?\s?Res\.?|S\.?\s?J\.?\s?Res\.?|S\.?\s?Con\.?\s?Res\.?|S\.?\s?Res\.?|S\.)\s?(\d{1,5})\b", re.I)


## Dates in upload titles: "10-29-13 Full Committee Business Meeting", "June 28, 2013 Full Committee Business Meeting".
MONTHS = "january february march april may june july august september october november december".split()
_MONTH_NUMBERS = {name[:3]: i for i, name in enumerate(MONTHS, 1)}


TITLE_DATE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{2}|\d{4})\b|\b(" + "|".join(m[:3] for m in MONTHS) + r")[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})\b", re.I)


## Statuses whose video_ids ``gpo_decisions`` has already accepted as a recording.
ASSIGNED_RECORDING = frozenset({"full_recording", "full_recording_offsite"})


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


def reschedule_candidate(row):
    """Missing video alone cannot move a closed session or recurring briefing.

    Briefing/deposition exclusions are conservative matching policy, not evidence
    of closed access. Explicit open access still wins over words in the topic.
    """
    return (meeting_access(row)[0] not in ("closed", "partly_closed")
            and meeting_type(row)[0] != "briefing"
            and not re.search(r"\bdeposition\b", row.get("title") or "", re.I))


def title_dates(title):
    """The calendar dates written in a title (numeric or month-name), as a set."""
    out = set()
    for mo, d, y, mon, d2, y2 in TITLE_DATE.findall(title):
        try:
            if mo:
                year = int(y) if len(y) == 4 else 2000 + int(y)
                month, day = int(mo), int(d)
            else:
                year, day = int(y2), int(d2)
                month = _MONTH_NUMBERS[mon.lower()]
            out.add(dt.date(year, month, day))
        except (ValueError, KeyError):
            pass
    return out


def assigned_by_package(hearing_videos):
    """package id → tokens ``gpo_decisions`` already stored on an accepted recording row."""
    by_package = collections.defaultdict(list)
    for row in hearing_videos or ():
        if row.get("status") not in ASSIGNED_RECORDING:
            continue
        package = row.get("package_id") or ""
        if not package:
            continue
        for token in str(row.get("video_ids") or "").split():
            by_package[package].append(token)
    return by_package


def _place_assigned(token, youtube, senate, other):
    """Put one assigned token on the index field completeness already treats as a recording."""
    if parse_player_url(token):
        senate.append(token)
    elif token.startswith(("http://", "https://")):
        if match := VIDEO_ID.search(token):
            youtube.append(match.group(1))
        else:
            other.append(token)
    else:
        youtube.append(token)


def build(meetings, gpo, videos, documents, pages, recordings, probed, yt_caps, sen_caps, hearing_videos=()):
    """Match supplied rows; ``videos`` contains (committee code, video row) pairs.

    ``hearing_videos`` is the already written package-recording table. Its ids are
    copied onto meetings that own those packages. This function does not score them.
    """
    video_flags = {}
    vid_by_eid = collections.defaultdict(list)
    for _code, v in videos:
        video_flags[v["videoId"]] = v.get("caption")
        for a, b in EVENT_ID.findall(v["title"] + " " + v["description"]):
            vid_by_eid[a or b].append(v["videoId"])
    assigned = assigned_by_package(hearing_videos)
    found = collections.defaultdict(list)
    for r in recordings:
        found[r["event_id"]].append(r["recording"])
    found_transcripts, found_documents, attached = collections.defaultdict(list), set(), collections.defaultdict(set)
    for r in documents:
        found_documents.add(r["event_id"])
        attached[r["event_id"]] |= attached_prints([r["url"]])
        if r["kind"] == "transcript":
            found_transcripts[r["event_id"]].append(r["url"])
    page_title = {r["event_id"]: r["title"] for r in pages}
    prints = match_prints(meetings, gpo, attached, share=False)
    rows = []
    for m in meetings:
        codes = codes_of(m)
        packages = prints[m["eventId"]]
        urls = [v.get("url", "") for v in (m.get("videos") or [])]
        youtube = list(dict.fromkeys([VIDEO_ID.search(u).group(1) for u in urls if VIDEO_ID.search(u)] + vid_by_eid.get(m["eventId"], [])
                                     + [v for v in found[m["eventId"]] if not v.startswith("http")]))
        senate = [u for u in urls if parse_player_url(u)] or [u for comm in senate_comms(m, codes) for u in probed.get((comm, m["date"][:10]), [])]
        rows.append({"event_id": m["eventId"], "congress": m["congress"], "chamber": m.get("chamber", ""), "type": m.get("type", ""), "date": m["date"][:10],
                     "committees": ";".join(codes), "title": (m.get("title") or "").strip(), "gpo_packages": packages, "youtube_ids": youtube, "senate_urls": senate,
                     "other_recordings": " ".join(v for v in found[m["eventId"]] if v.startswith("http")),
                     "committee_transcripts": " ".join(dict.fromkeys([d["url"] for d in m.get("meetingDocuments") or [] if d.get("url") and TRANSCRIPT.search(f"{d.get('documentType')} {d.get('name')}")]
                                                                        + found_transcripts[m["eventId"]])),
                     ## a document has an address: Congress.gov's Senate records name documents without one
                     "text_source": "", "documents": "yes" if m["eventId"] in found_documents or any(d.get("url") for d in (m.get("witnessDocuments") or []) + (m.get("meetingDocuments") or [])) else "no",
                     "rescheduled_to": "", "not_held": "yes" if NOT_HELD.match(m.get("title") or "") else ""})
    ## a joint hearing is entered once per committee: same day, same title, one set of records
    for group in same_day_title_groups(rows).values():
        if len(group) > 1:
            packages = set().union(*(r["gpo_packages"] for r in group))
            youtube = list(dict.fromkeys(v for r in group for v in r["youtube_ids"]))
            senate = list(dict.fromkeys(u for r in group for u in r["senate_urls"]))
            for r in group:
                r["gpo_packages"], r["youtube_ids"], r["senate_urls"] = packages, youtube, senate
    for r in rows:
        youtube, senate = list(r["youtube_ids"]), list(r["senate_urls"])
        other = r["other_recordings"].split()
        for package in r["gpo_packages"]:
            for token in assigned.get(package, ()):
                _place_assigned(token, youtube, senate, other)
        r["youtube_ids"] = list(dict.fromkeys(youtube))
        r["senate_urls"] = list(dict.fromkeys(senate))
        r["other_recordings"] = " ".join(dict.fromkeys(token for token in other if token))
        r["text_source"] = text_source(r, yt_caps, sen_caps, video_flags)
        if r["text_source"] == "no_video":
            r["not_held"] = r["not_held"] or ("yes" if NOT_HELD.match(re.sub(r"^\W+", "", page_title.get(r["event_id"], ""))) else "")
        r["gpo_packages"], r["youtube_ids"], r["senate_urls"] = " ".join(sorted(r["gpo_packages"])), " ".join(sorted(r["youtube_ids"])), " ".join(sorted(r["senate_urls"]))
    ## a postponed meeting re-entered under a new event ID keeps its old record as Scheduled: point it at the twin that was held
    same_title = collections.defaultdict(list)
    for r in rows:
        if title_key(r["title"]) and r["text_source"] != "no_video":
            same_title[(r["committees"], title_key(r["title"]))].append(r)
    for r in rows:
        if r["text_source"] == "no_video" and title_key(r["title"]) and reschedule_candidate(r):
            later = [o for o in same_title[(r["committees"], title_key(r["title"]))] if 0 < (dt.date.fromisoformat(o["date"]) - dt.date.fromisoformat(r["date"])).days <= 60]
            if later:
                r["rescheduled_to"] = min(later, key=lambda o: o["date"])["event_id"]
    return sorted(rows, key=lambda r: (r["date"], r["event_id"]))
