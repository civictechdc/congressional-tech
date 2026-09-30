"""Build the meeting text index from weekly inputs and parsed source outputs.

Recording rules retain event IDs, bill/title matches, date-labelled uploads,
Natural Resources subcommittee/time labels, generic session uploads and joint
hearing sharing. Twenty minutes separates weak matches from member clips.
Print and transcript ownership is evaluated before caption availability.
"""

import collections
import datetime as dt
import re

from zoneinfo import ZoneInfo

from congress_api.matching.captions import text_source
from congress_api.matching.committees import codes_of
from congress_api.matching.gpo_videos import EVENT_ID, VIDEO_ID, similarity, words
from congress_api.matching.meetings import HEARING_TYPES, NOT_HELD, TRANSCRIPT, meeting_access, meeting_type
from congress_api.matching.prints import attached_prints, match_prints, same_day_title_groups, title_key
from congress_api.parsers.senate_player import COMM, STREAM, parse_player_url

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


SESSION_RECAP = re.compile(r"\b(highlights?|takeaways?|recap|reactions?)\b", re.I)


NAME_STOP = set("house senate committee subcommittee on the and of for".split())


ET = ZoneInfo("America/New_York")


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


def session_family(kind):
    """Recording matching groups business with markup and field with hearing.

    These compatibility groups never replace the meeting's actual type.
    """
    return "hearing" if kind in HEARING_TYPES else "markup" if kind in ("markup", "business") else kind


def session_kind_fits(meeting, title):
    """Upload-title hints constrain weak matches; they do not classify meetings."""
    # A long reaction video can mention a hearing without recording it. Exact
    # IDs and topic/bill matches are evaluated separately from this fallback.
    if SESSION_RECAP.search(title):
        return False
    family = session_family(meeting_type(meeting)[0])
    hearing, markup = bool(HEARING_WORDS.search(title)), bool(MARKUP_WORDS.search(title))
    return (hearing and not markup) if family == "hearing" else markup if family == "markup" else (hearing or markup) if family == "meeting" else False


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


def build(meetings, gpo, videos, documents, pages, recordings, probed, yt_caps, sen_caps):
    """Match supplied rows; ``videos`` contains (committee code, video row) pairs."""
    video_flags = {}
    vid_by_eid = collections.defaultdict(list)
    by_code_day: dict = collections.defaultdict(list)  # (committee code, upload date) -> videos, for date-window matching
    dated: dict = collections.defaultdict(list)  # (committee code, date in the title) -> uploads of 20+ minutes titled with that date
    for code, v in videos:
        video_flags[v["videoId"]] = v.get("caption")
        for a, b in EVENT_ID.findall(v["title"] + " " + v["description"]):
            vid_by_eid[a or b].append(v["videoId"])
        by_code_day[(code, v["publishedAt"][:10])].append((v["videoId"], v["title"], v.get("duration") or 0, bool(EVENT_ID.search(v["title"] + " " + v["description"]))))
        if (v.get("duration") or 0) >= 1200:
            for day in title_dates(v["title"]):
                dated[(code, day.isoformat())].append((v["videoId"], *unit_and_minutes(v["title"])))

    def window_matches(m, codes):
        """Tracked videos of the committee at least 20 minutes long (a markup's or short hearing's full recording; a
        few-minute clip isn't) that fit the meeting one of three ways: posted a day before to three days after it with a
        similar title or naming one of the same bills; titled with the meeting's date, when the meeting is the
        committee's only one that day or the title names its subcommittee (Natural Resources' 2016-18 archive uploads,
        nearest hour when that subcommittee met twice); or a session upload, a generic hearing or markup title that
        agrees with the meeting's type and carries no other day's date and no event ID, posted on the meeting's day (or
        the next, when the committee held no session of that kind then), when the meeting is the committee's only one
        that day or the title names its subcommittee (by any name it has carried) and that subcommittee met only once.
        A title date that differs only in the year is a typo ("3-12-2012 Committee Business Meeting", posted 2014-03-13)."""
        day, title = m["date"][:10], m.get("title") or ""
        tw, tb, out = words(title), bills(title), []
        d0 = dt.date.fromisoformat(day)
        units = {c["systemCode"] for c in m.get("committees", [])}
        start = dt.datetime.fromisoformat(m["date"].replace("Z", "+00:00")).astimezone(ET) if "T" in m["date"] else None
        for code in codes:
            sub_words = [ws for c in m.get("committees", []) if not c["systemCode"].endswith("00") and units_that_day[(c["systemCode"], day)] == 1
                         for ws in unit_names[c["systemCode"]]]
            for k in range(-1, 4):
                d = (d0 + dt.timedelta(days=k)).isoformat()
                for vid, vt, dur, tagged in by_code_day.get((code, d), []):
                    if dur < 1200:
                        continue
                    if similarity(tw, words(vt)) >= 0.5 or (tb and tb & bills(vt)):
                        out.append(vid)
                    elif (k == 0 or (k == 1 and ("markup" if MARKUP_WORDS.search(vt) else "hearing") not in kinds_that_day[(code, d)])) and not tagged and all((t.month, t.day) == (d0.month, d0.day) for t in title_dates(vt)) \
                            and session_kind_fits(m, vt) and (meetings_that_day[(code, day)] == 1 or any(sw and sw <= set(words(vt)) for sw in sub_words)):
                        out.append(vid)
            same_day = [(vid, minutes) for vid, unit, minutes in dated.get((code, day), []) if unit in units or (unit is None and meetings_that_day[(code, day)] == 1)]
            if same_day and start and any(minutes is not None for _, minutes in same_day):
                same_day = [min(same_day, key=lambda x: abs((x[1] if x[1] is not None else 10**6) - start.hour * 60 - start.minute))]
            out.extend(vid for vid, _ in same_day)
        return list(dict.fromkeys(out))
    ## how many meetings each committee, and each subcommittee, held on each day, and of which kinds; the words of each parent committee's name
    meetings_that_day = collections.Counter((c, m["date"][:10]) for m in meetings for c in codes_of(m))
    kinds_that_day = collections.defaultdict(set)
    for m in meetings:
        for c in codes_of(m):
            kinds_that_day[(c, m["date"][:10])].add(session_family(meeting_type(m)[0]))
    units_that_day = collections.Counter((c["systemCode"], m["date"][:10]) for m in meetings for c in m.get("committees", []))
    parent_words = {c["systemCode"]: set(words(c["name"])) for m in meetings for c in m.get("committees", []) if c["systemCode"].endswith("00") and c.get("name")}
    ## every name a subcommittee has carried, as its distinctive words: Congress.gov leaves the name blank on many records
    unit_names = collections.defaultdict(list)
    for m in meetings:
        for c in m.get("committees", []):
            ws = set(words(c.get("name") or "")) - parent_words.get(c["systemCode"][:4] + "00", set()) - NAME_STOP
            if ws and not c["systemCode"].endswith("00") and ws not in unit_names[c["systemCode"]]:
                unit_names[c["systemCode"]].append(ws)
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
                                     + (window_matches(m, codes) if not packages else [])
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
        r["text_source"] = text_source(r, yt_caps, sen_caps, video_flags)
        if r["text_source"] == "no_video":
            r["not_held"] = r["not_held"] or ("yes" if NOT_HELD.match(re.sub(r"^\W+", "", page_title.get(r["event_id"], ""))) else "")
        r["gpo_packages"], r["youtube_ids"], r["senate_urls"] = " ".join(sorted(r["gpo_packages"])), " ".join(r["youtube_ids"]), " ".join(r["senate_urls"])
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
