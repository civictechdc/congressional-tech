"""Focused coverage for parser review fixes (encoding, dates, speakers, captions)."""
import datetime as dt

import pytest
from congress_api.models.transcription import Header, Person
from congress_api.parsers.captions import _subtitle_uri
from congress_api.parsers.gpo import parse_transcript_html
from congress_api.parsers.gpo_hearings import hearing_days
from congress_api.parsers.gpo_text import parse_gpo_text
from congress_api.parsers.senate import parse_listing_page, parse_page
from congress_api.parsers.senate_page import DATE, century_year, written_day
from congress_api.matching import speaker_names as names
from congress_api.matching.gpo_speakers import bind_gpo_transcript


def test_parse_page_rejects_invalid_utf8():
    with pytest.raises(UnicodeDecodeError):
        parse_page(b"<html>\xff</html>", "https://example.org/hearings/x")


def test_parse_transcript_html_strict_utf8_or_decoded_text():
    with pytest.raises(UnicodeDecodeError):
        parse_transcript_html(b"<pre>caf\xe9</pre>")
    latin = b"<pre>caf\xe9</pre>"
    model = parse_transcript_html(latin, decoded_text=latin.decode("latin-1"))
    assert "café" in model.text
    assert model.source.body_bytes() == latin


def test_listing_month_only_url_ranks_by_month_end_not_day_15():
    page = '<a href="/2026/3/example-hearing">Example Hearing</a>'
    rows = parse_listing_page(page, "judiciary.senate.gov")
    assert len(rows) == 1
    day, url, title = rows[0]
    assert day == dt.date(2026, 3, 31) and day.day != 15
    assert title == "Example Hearing" and url.endswith("/2026/3/example-hearing")
    # Whole March stays in scope for a mid-month --since; April is out.
    assert day >= dt.date(2026, 3, 15)
    assert not (day >= dt.date(2026, 4, 1))


def test_listed_discovers_month_only_page_without_treating_it_as_the_15th():
    from congress_api.acquisition import senate as records
    page = (
        '<a href="/2026/3/first-hearing">First Hearing</a>'
        '<a href="/2026/3/second-hearing">Second Hearing</a>'
    )
    rows = records.listing_page("judiciary.senate.gov", "/hearings?page={}", 1, lambda _: page)
    assert {title for _, _, title in rows} == {"First Hearing", "Second Hearing"}
    assert all(day == dt.date(2026, 3, 31) and day.day != 15 for day, _, _ in rows)
    # Same comparison listed() uses for --since and pagination stop.
    assert max(day for day, _, _ in rows) >= dt.date(2026, 3, 20)
    assert [r for r in rows if r[0] >= dt.date(2026, 3, 20)] == rows
    assert [r for r in rows if r[0] >= dt.date(2026, 4, 1)] == []


def test_decoded_page_rejects_invalid_utf8_without_replacing():
    from types import SimpleNamespace
    from congress_api.acquisition import senate as records
    receipt = {}
    response = SimpleNamespace(content=b"<html>\xff</html>", headers={"Content-Type": "text/html"})
    with pytest.raises(UnicodeDecodeError):
        records.decoded_page(response, "https://www.judiciary.senate.gov/hearings/x", receipt)
    assert receipt["outcome"] == "error" and "UTF-8" in receipt["error"]
    ok = SimpleNamespace(content=b"<html>ok</html>", headers={})
    assert records.decoded_page(ok, "https://example.org/y", {}) == "<html>ok</html>"


@pytest.mark.parametrize("yy,expected", [(99, 1999), (26, 2026), (35, 1935), (0, 2000), (2026, 2026)])
def test_century_year_pivot(yy, expected):
    assert century_year(yy) == expected


def test_written_day_two_digit_years():
    assert written_day(next(DATE.finditer("6/12/99"))) == dt.date(1999, 6, 12)
    assert written_day(next(DATE.finditer("3/11/26"))) == dt.date(2026, 3, 11)


def test_speaker_match_shared_surname_is_ambiguous_without_prefer():
    people = {
        "lee-sheila": Person(name="Sheila Jackson Lee", role="member", surname="Jackson Lee"),
        "lee-laurel": Person(name="Laurel M. Lee", role="member", surname="Lee"),
    }
    assert names.match(people, "Lee") is None
    assert names.match(people, "Lee", prefer={"lee-sheila"}) == "lee-sheila"
    assert names.match(people, "Jackson Lee") == "lee-sheila"


def test_gpo_text_ambiguous_surname_becomes_unknown_not_first_hit():
    header = Header(title="Hearing", chamber="house")
    mods = {
        "lee-sheila": Person(name="Sheila Jackson Lee", role="member", surname="Jackson Lee"),
        "lee-laurel": Person(name="Laurel M. Lee", role="member", surname="Lee"),
    }
    # Two spaces of indent (print paragraph style) and a recurring attribution.
    body = (
        "  The committee met.\n"
        "  Ms. Lee. First turn.\n"
        "  Ms. Lee. Second turn.\n"
    )
    original = header.model_copy(deep=True)
    unresolved = parse_gpo_text(body, header, mods)
    assert {turn.speaker for turn in unresolved.turns if turn.kind == "speech"} == {"Ms. Lee"}
    transcript = bind_gpo_transcript(unresolved)
    assert header.time_convened == original.time_convened  # caller header unchanged
    speakers = {turn.speaker for turn in transcript.turns if turn.kind == "speech"}
    assert speakers.isdisjoint({"lee-sheila", "lee-laurel"})
    assert all(transcript.participants[k].role == "unknown" or k not in mods for k in speakers)


def test_hearing_days_skips_invalid_and_keeps_ordinary_or_volume():
    ordinary = "Wednesday, February 25, 2015\n"
    assert hearing_days(ordinary, 114) == ["2015-02-25"]
    assert hearing_days("WEDNESDAY, FEBRUARY 31, 2015\n", 114) == []
    volume = "APPROPRIATIONS FOR 2016Wednesday, March 17, 2015DHS\n"
    assert hearing_days(volume, 114, volume=True) == ["2015-03-17"]
    assert hearing_days(volume, 114, volume=False) == []


def test_subtitle_uri_prefers_english_then_default():
    master = (
        "#EXTM3U\n"
        '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="Spanish",LANGUAGE="spa",URI="spa.m3u8"\n'
        '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="English",LANGUAGE="eng",DEFAULT=YES,URI="eng.m3u8"\n'
    )
    assert _subtitle_uri(master) == "eng.m3u8"
    default_only = (
        "#EXTM3U\n"
        '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="French",LANGUAGE="fra",URI="fra.m3u8"\n'
        '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="Other",LANGUAGE="und",DEFAULT=YES,URI="und.m3u8"\n'
    )
    assert _subtitle_uri(default_only) == "und.m3u8"


def test_parse_gpo_text_does_not_mutate_caller_header():
    header = Header(title="Retained", chamber="house")
    before = header.model_dump()
    parse_gpo_text(
        "  The committee met at 10:00 a.m. in room 2154, Rayburn Building, Hon. Smith [presiding].\n"
        "  Mr. Smith. Hello.\n"
        "  Mr. Smith. Again.\n",
        header,
        {"smith": Person(name="Smith", role="chair", surname="Smith")},
    )
    assert header.model_dump() == before
