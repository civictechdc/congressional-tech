"""Focused scoring helpers for GPO hearing ↔ YouTube matching."""

import datetime as dt

import pytest
from congress_api.matching.gpo_videos import (
    candidates,
    dates_in_text,
    is_clip,
    stale,
    words,
)


@pytest.mark.parametrize("text,context,expected", [
    ("Hearing 031815 full committee", None, {"2015-03-18"}),  # MMDDYY only valid as month-first
    ("Archive 140115 markup", None, {"2014-01-15"}),  # YYMMDD only (MMDDYY month=14 invalid)
    ("Ambiguous 061215 hearing", None, set()),  # both in-range → drop without context
    ("Ambiguous 061215 hearing", {"2015-06-12"}, {"2015-06-12"}),  # context prefers MMDDYY
    ("Ambiguous 061215 hearing", {"2006-12-15"}, {"2006-12-15"}),  # context may select YYMMDD
    ("Labeled 3/18/2015 hearing", None, {"2015-03-18"}),  # separators unchanged
    ("Packed 20160107 hearing", None, {"2016-01-07"}),  # 8-digit unchanged
    ("March 18, 2015 hearing", None, {"2015-03-18"}),  # month name unchanged
])
def test_dates_in_text_six_digit_disambiguation(text, context, expected):
    assert dates_in_text(text, context) == expected


def test_is_clip_duration_and_member_title_thresholds():
    assert is_clip({"duration": 1199, "title": "Full Committee Hearing"})
    assert not is_clip({"duration": 1200, "title": "Full Committee Hearing"})
    assert is_clip({"duration": 1799, "title": "Wyden Q&A with witnesses"})
    assert not is_clip({"duration": 1800, "title": "Wyden Q&A with witnesses"})
    assert not is_clip({"duration": None, "title": "Opening Statement"})


def test_stale_demotes_late_upload_without_title_match():
    last = dt.date(2015, 3, 18)
    title_w = words("Competition in digital information markets")
    late = {"published": "2015-04-01", "title": "Unrelated press conference", "words": words("Unrelated press conference")}
    assert stale(95, late, last, title_w, lambda _: []) == 55
    close = {"published": "2015-03-20", "title": "Competition in digital information markets",
             "words": words("Competition in digital information markets")}
    assert stale(95, close, last, title_w, lambda _: []) == 95


def _hearing(**updates):
    row = {
        "package_id": "CHRG-113hhrg1", "event_id": "117681", "committee_code": "hsju00",
        "title": "Competition in digital information markets", "subcommittees": "",
        "held_date": "2015-03-18", "hearing_dates": "", "_dates": ["2015-03-18"],
    }
    row.update(updates)
    return row


def _video(**updates):
    row = {
        "videoId": "abcdefghijk", "channel": "judiciary", "published": "2015-03-18",
        "title": "Competition in digital information markets",
        "words": words("Competition in digital information markets"),
        "dates": set(), "event_ids": set(), "duration": 3600, "audio_only": False,
    }
    row.update(updates)
    if "title" in updates and "words" not in updates:
        row["words"] = words(row["title"])
    return row


@pytest.mark.parametrize("label,hearing,video,meetings,hearings_on_day,expected_score,expected_method", [
    ("congress.gov event", _hearing(), _video(),
     {"hsju00": {"2015-03-18": [{"eventId": "117681", "words": words("Competition in digital information markets"),
                                "subcommittees": [], "videos": ["abcdefghijk"], "offsite": []}]}},
     {}, 100, "congress.gov link"),
    ("event id in video", _hearing(), _video(event_ids={"117681"}, published="2015-03-19"),
     {}, {}, 95, "event ID in video"),
    ("date in video + title", _hearing(), _video(dates={"2015-03-18"}, published="2015-03-19"),
     {}, {("hsju00", "2015-03-18"): 2}, 80, "date in video + title"),
    ("date in video generic", _hearing(), _video(title="W&M Hearing: Mar 18, 2015", dates={"2015-03-18"}, published="2015-03-19"),
     {}, {("hsju00", "2015-03-18"): 1}, 70, "date in video"),
    ("only meeting that day", _hearing(event_id=""), _video(videoId="only"),
     {"hsju00": {"2015-03-18": [{"eventId": "999999", "words": words("Other topic entirely here"),
                                "subcommittees": [], "videos": ["only"], "offsite": []}]}},
     {}, 75, "congress.gov link"),
    ("date window + title", _hearing(), _video(published="2015-03-20"),
     {}, {}, 60, "date window + title"),
    ("date window + subcommittee", _hearing(subcommittees="Subcommittee on Courts"),
     _video(title="Courts Subcommittee session", published="2015-03-20",
            words=words("Courts Subcommittee session")),
     {}, {}, 50, "date window + subcommittee"),
])
def test_candidates_score_tiers(label, hearing, video, meetings, hearings_on_day, expected_score, expected_method):
    scored = candidates(hearing, [video], meetings, hearings_on_day, {})
    assert any(score == expected_score and method == expected_method for score, method, _ in scored), (label, scored)
