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

``candidates`` scores one hearing. Durable assignment, overrides, and CSV verdicts
live in ``matching.gpo_decisions``. A hearing is scored on every day in
``hearing_dates`` when present, else on GPO's held date; on both when the transcript
names one day and GPO another. Multi-hearing volumes (Appropriations "Part N") match
meetings by subcommittee, because their title names no hearing.
"""

import datetime as dt
import re

from congress_api.parsers.gpo_hearings import is_multi_hearing_volume
from congress_api.parsers.text import STOP, words


CLIP_SECONDS = 1200


CLIP_TITLE_SECONDS = 1800


CLIP_TITLE = re.compile(r"\b(q&a|questions?|opening statement|opening remarks|statement|remarks|round of questions|closing)\b"
                        r"|^(sen\.|senator|rep\.|chairman|chair|ranking member|subcommittee chairman|vice chair)\s", re.I)


EVENT_ID = re.compile(r"(?:event\s*id|\bid)\s*[:=#]?\s*(1\d{5})(?!\d)|house-event/(1\d{5})(?!\d)", re.I)


SENATE_VIDEO = re.compile(r"https?://www\.senate\.gov/isvp/")


VIDEO_ID = re.compile(r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|live/|embed/|shorts/|v/)|youtu\.be/)([\w-]{11})")


MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}


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


def _in_range(day):
    return day is not None and "2005" <= day <= "2100"


def _six_digit_date(code, context_dates=None):
    """Resolve one 6-digit token. Prefer MMDDYY; never keep both parses.

    Committees usually write hearing dates as MMDDYY ("031815"); YYMMDD ("140115") also
    appears. One valid parse is enough. When both are valid and differ, keep a date only if
    ``context_dates`` (held days or an upload window) names it—MMDDYY first when both agree.
    """
    mmddyy = valid_date(2000 + int(code[4:]), int(code[:2]), int(code[2:4]))
    yymmdd = valid_date(2000 + int(code[:2]), int(code[2:4]), int(code[4:]))
    ordered = list(dict.fromkeys(day for day in (mmddyy, yymmdd) if _in_range(day)))
    if len(ordered) <= 1:
        return set(ordered)
    if not context_dates:
        return set()
    agreed = [day for day in ordered if day in context_dates]
    return {agreed[0]} if agreed else set()


def dates_in_text(text, context_dates=None):
    """ISO dates from a video title/description. Separators, 8-digit codes, and month names
    stay as-is; compact 6-digit tokens go through :func:`_six_digit_date`."""
    found = set()
    for m, d, y in re.findall(r"(?<!\d)(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})(?!\d)", text):
        y = int(y) + (2000 if len(y) == 2 else 0)
        found.add(valid_date(y, int(m), int(d)))
    for mon, d, y in re.findall(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})", text.lower()):
        found.add(valid_date(int(y), MONTHS[mon], int(d)))
    for code in re.findall(r"(?<!\d)(\d{8})(?!\d)", text):  # 20160107
        found.add(valid_date(int(code[:4]), int(code[4:6]), int(code[6:])))
    for code in re.findall(r"(?<!\d)(\d{6})(?!\d)", text):
        found |= _six_digit_date(code, context_dates)
    found.discard(None)
    return {d for d in found if _in_range(d)}


def matching_days(h):
    """The days to match a hearing on: those its transcript's day headers give, else GPO's held date.
    When the transcript names one day and GPO another, either may be the misprint (CHRG-113hhrg88456's
    GPO date is wrong, CHRG-113hhrg86002's day header is), so both count. A volume's GPO date is a
    placeholder and never counts beside the transcript's days."""
    days = set(filter(None, (h.get("hearing_dates") or "").split(";")))
    if h["held_date"] and (not days or (len(days) == 1 and not is_multi_hearing_volume(h["title"]))):
        days.add(h["held_date"])
    return sorted(days)


def is_clip(v):
    """A short video, or a short-ish one titled as a member's questions or statement."""
    d = v.get("duration")
    return d is not None and (d < CLIP_SECONDS or (d < CLIP_TITLE_SECONDS and bool(CLIP_TITLE.search(v.get("title", "")))))


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
    ## a volume prints several hearings under a title that names none of them; a two-day hearing, or one GPO misdated,
    ##  also lists its days but is still matched by its title
    volume = bool(h["hearing_dates"]) and is_multi_hearing_volume(h["title"])
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
            if any(-1 <= (dt.date.fromisoformat(v["published"]) - dt.date.fromisoformat(day)).days <= 3 for day in dates):
                if similarity(title_w, v["words"]) >= 0.5:
                    out.append((60, "date window + title", v))
                elif any(sw and sw <= v["words"] for sw in sub_w):
                    out.append((50, "date window + subcommittee", v))
    return out
