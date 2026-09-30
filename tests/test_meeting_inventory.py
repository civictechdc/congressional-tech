import datetime as dt
import json
from pathlib import Path

import pytest

from congress_api.house import repository
from congress_api.inventory import captions, completeness, text_sources
from congress_api.inventory.common import due, read_state, write_state
from congress_api.inventory.prints import match_prints
from congress_api.senate import pages, records

FIXTURES = Path(__file__).parent / "fixtures/meeting_inventory"


@pytest.mark.parametrize("sample", json.loads((FIXTURES / "house.json").read_text()), ids=lambda s: s["fixture"])
def test_house_xml(sample):
    root = repository.parse_xml((FIXTURES / sample["fixture"]).read_bytes())
    if "witnesses" in sample:
        assert repository.witness_rows(root) == sample["witnesses"]
    else:
        docs, amendments = repository.read_xml(root, None)
        assert [[k, n, u, sorted(files)] for k, n, u, files in docs] == sample["documents"]
        assert amendments == sample["amendments"]


@pytest.mark.parametrize("sample", json.loads((FIXTURES / "senate.json").read_text()), ids=lambda s: s["layout"])
def test_senate_layout(sample):
    page = (FIXTURES / sample["fixture"]).read_text()
    assert pages.witnesses(page, "https://example.org/hearing") == sample["expected"]


def test_house_addresses_use_filed_documents_before_record_guesses():
    m = {"eventId": "108754", "congress": 115, "type": "Hearing", "date": "2018-11-14", "committees": [{"systemCode": "hshm00"}],
         "witnessDocuments": [{"url": "https://docs.house.gov/meetings/AS/AS26/20181114/108754/HHRG-115-AS26-Wstate-ManfraJ-20181114.pdf"}]}
    assert repository.addresses(m)[0] == "https://docs.house.gov/meetings/AS/AS26/20181114/108754/HHRG-115-AS26-20181114.xml"
    m.update(committees=[{"systemCode": "hlig00"}], witnessDocuments=[])
    assert "/IG/IG00/" in repository.addresses(m)[0]


def test_witness_address_can_come_from_full_committee():
    root = repository.parse_xml(b'<committee-meeting meeting-type="HHRG" congress-num="114"><meeting-details><meeting-date><calendar-date>2015-09-30</calendar-date></meeting-date><committees><committee-name id="AS00"/></committees><subcommittees><committee-name id="AS26"/></subcommittees></meeting-details></committee-meeting>')
    urls = repository.addresses({"eventId": "103995"}, root)
    assert "/AS00/" in urls[0] and "/AS26/" in urls[1]


@pytest.mark.parametrize("field,value,expected", [("gpo_packages", ["CHRG-118hhrg1"], "gpo"),
    ("committee_transcripts", "https://example.org/transcript", "committee_transcript"),
    ("youtube_ids", ["observed"], "youtube_captions"), ("senate_urls", ["https://www.senate.gov/isvp/?comm=budget&filename=budget092023"], "senate_captions"),
    ("other_recordings", "https://example.org/video", "video_no_captions")])
def test_text_source_order(field, value, expected):
    row = dict(gpo_packages=[], committee_transcripts="", youtube_ids=[], senate_urls=[], other_recordings="")
    row[field] = value
    assert captions.text_source(row, {"observed": "auto"}, {}, {}) == expected


def test_caption_observation_overrides_flag_and_cutoff():
    row = dict(gpo_packages=[], committee_transcripts="", youtube_ids=["v"], senate_urls=[], other_recordings="")
    assert captions.text_source(row, {}, {}, {"v": False}) == "video_no_captions"
    assert captions.text_source(row, {"v": "auto"}, {}, {"v": False}) == "youtube_captions"
    assert captions.text_source(row, {"v": "none"}, {}, {"v": True}) == "video_no_captions"
    url = "https://www.senate.gov/isvp/?comm=budget&filename=budget092023"
    assert not captions.senate_caption(url, {"budget092023": "none"})
    assert not captions.senate_caption("https://www.senate.gov/isvp/?comm=xxxx&filename=xxxx012125", {})


def test_pdf_schedule_is_not_a_witness_affiliation():
    from congress_api.inventory.witness_lists import read_pdf
    people, text_present = read_pdf((FIXTURES / "house-member-schedule.pdf").read_bytes())
    assert text_present and people == []


def test_mods_witnesses_can_live_in_granules():
    from congress_api.gpo.fetch import mods_witnesses
    data = b'<mods xmlns="http://www.loc.gov/mods/v3"><relatedItem><extension><witness>Coffren, Lauren</witness></extension></relatedItem></mods>'
    assert mods_witnesses(data) == [{"name": "Lauren Coffren", "honorific": "", "position": "", "organization": ""}]


def test_completeness_preserves_legacy_title_newlines():
    m = {"eventId": "1", "congress": 119, "date": "2026-09-01", "type": "Meeting", "title": "Business\r\nmeeting"}
    r = dict(event_id="1", committees="ssju00", title=m["title"], gpo_packages="", youtube_ids="", senate_urls="", other_recordings="", text_source="no_video", rescheduled_to="", not_held="")
    rows, people = completeness.build([m], {"1": r}, set(), [], [], [], {}, {}, dt.date(2026, 9, 27), True, None)
    assert rows[0]["title"] == "Business\nmeeting" and people == []


def test_print_date_alone_does_not_assign_two_proceedings():
    ms = [{"eventId": e, "date": "2024-01-01", "title": title, "type": "Hearing", "committees": [{"systemCode": "hsju00"}]} for e, title in
          (("1", "Competition in digital markets"), ("2", "Agricultural commodity insurance"))]
    gpo = [{"package_id": "p", "event_id": "", "congress": "118", "committee_code": "hsju00", "held_date": "2024-01-01", "hearing_dates": "", "title": "Competition in digital markets"}]
    assert match_prints(ms, gpo) == {"1": {"p"}, "2": set()}
    ms[1]["meetingDocuments"] = [{"url": "https://example.org/CHRG-118hhrg123.pdf"}]
    gpo[0]["package_id"] = "CHRG-118hhrg123"
    assert match_prints(ms, gpo)["2"] == {"CHRG-118hhrg123"}


def test_dates_bill_names_nominees_and_natural_resources_time():
    assert text_sources.title_dates("June 28, 2013 Full Committee Business Meeting") == {dt.date(2013, 6, 28)}
    assert text_sources.unit_and_minutes("3.2.16. EMR. 10:00 AM.") == ("hsii06", 600)
    assert text_sources.bills("H.R. 2810 and S.J.Res. 7") == {("HR", "2810"), ("SJRES", "7")}
    assert completeness.nominees("Hearings to examine the nominations of Thomas Peter Feddo, of Virginia, to be Assistant Secretary of the Treasury for Investment Security.") == [("Thomas Peter Feddo", "Assistant Secretary of the Treasury for Investment Security")]


@pytest.mark.parametrize('native,title,upload,expected', [
    ('Meeting', 'Hearings to examine policy', 'Full Committee Markup', False),
    ('Meeting', 'Hearings to examine policy', 'Legislative Hearing', True),
    ('Meeting', 'Closed business meeting to consider nominations', 'Business Meeting', True),
    ('Field Hearing', 'Rural access', 'Oversight Hearing', True),
    ('Markup', 'Budget', 'Full Committee Markup', True),
    ('Briefing', 'Budget', 'Oversight Hearing', False),
    ('Meeting', 'Budget', 'Business Meeting', True),
    ('Open Hearing', 'Hearings to examine the nomination of Todd Blanche',
     'Senate Judiciary Democrats Offer Takeaways from Todd Blanche Hearing', False),
])
def test_generic_recording_matches_use_normalized_meeting_type(native, title, upload, expected):
    assert text_sources.session_kind_fits({'type': native, 'title': title}, upload) is expected


@pytest.mark.parametrize('title,expected', [
    ('Business Meeting (Open in a Closed Space)', True),
    ('Hearings on closed-door settlements', True),
    ('Closed business meeting to consider nominations', False),
    ('Open and closed hearings to examine worldwide threats', False),
    ('A briefing on the annual budget', False),
    ('The deposition of Mark Miller', False),
])
def test_rescheduling_exclusions_do_not_invent_closed_access(title, expected):
    assert text_sources.reschedule_candidate({'type': 'Meeting', 'title': title}) is expected


@pytest.mark.parametrize("caption,expected", [(True, "youtube_captions"), (False, "video_no_captions"), (None, "video_no_captions")])
def test_video_cache_reading_is_separate_from_matching(tmp_path, monkeypatch, caption, expected):
    from congress_api.inventory.common import read_youtube_videos

    channels = [{"systemCode": "hsag00"}, {"systemCode": "hsap00"}, {"systemCode": "hsju00"}]
    video = {"videoId": "retained-video", "title": "Competition in digital markets", "description": "",
             "publishedAt": "2024-01-02T12:00:00Z", "duration": 3600, "caption": caption,
             "future": {"native": [None, 0]}}
    (tmp_path / "youtube_00.json").write_text(json.dumps({"_default": {"1": {"ignore": True}}}))
    # Channel 01 has no saved file. Channel 02 must keep its committee association.
    (tmp_path / "youtube_02.json").write_text(json.dumps({"youtube_videos_example": {"5": video}}))
    videos = list(read_youtube_videos(tmp_path, channels))
    assert videos == [("hsju00", video)]
    meeting = {"eventId": "123456", "congress": 118, "chamber": "House", "date": "2024-01-02",
               "type": "Hearing", "title": video["title"], "committees": [{"systemCode": "hsju00"}]}

    def forbidden(*args, **kwargs):
        raise AssertionError("matching attempted file access")

    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    rows = text_sources.build([meeting], [], iter(videos), [], [], [], {}, {}, {})
    assert rows[0]["youtube_ids"] == video["videoId"]
    assert rows[0]["text_source"] == expected
    # Title/date matching must stay within the supplied committee.
    meeting["committees"] = [{"systemCode": "hsag00"}]
    assert text_sources.build([meeting], [], videos, [], [], [], {}, {}, {})[0]["youtube_ids"] == ""
    assert videos == [("hsju00", video)]


def test_invalid_video_cache_is_not_treated_as_a_missing_channel(tmp_path):
    from congress_api.inventory.common import read_youtube_videos

    (tmp_path / "youtube_00.json").write_bytes(b"{not json}")
    with pytest.raises(json.JSONDecodeError):
        list(read_youtube_videos(tmp_path, [{"systemCode": "hsju00"}]))


def test_incremental_refresh_and_deterministic_state(tmp_path):
    today = dt.date(2026, 9, 27)
    saved = {"checked": "2026-09-20", "version": "v1"}
    assert due(saved, "2026-09-10", "v1", today)
    assert not due(saved, "2025-09-10", "v1", today)
    assert due(saved, "2014-09-10", "v2", today)
    assert due({**saved, "xml_update": "2026-09-10T12:00:00"}, "2014-09-10", "v1", today)
    path = tmp_path / "state.json.gz"
    write_state(path, {"record": saved})
    first = path.read_bytes()
    write_state(path, read_state(path))
    assert path.read_bytes() == first


def test_senate_budget_prioritizes_oldest_check_across_sites():
    def site(url, checked):
        return {"versions": {"1": "v"}, "listings": {url: ["2019-01-01", "Hearing"]}, "pages": {url: {"checked": checked, "version": "", "events": []}}}
    state = {"a": site("https://a/page", "2025-01-01"), "z": site("https://z/page", "2024-01-01")}
    versions = {host: {"1": "v"} for host in state}
    assert records.refresh_urls(state, versions, dt.date(2026, 9, 27), 1) == {"https://z/page"}


def test_listing_date_is_not_hearing_evidence():
    page = '<div>March 4, 2024</div><a href="/hearings/a">Interior budget</a>'
    rows = records.listing_page("example.org", "/hearings?page={}", 1, lambda _: page)
    assert rows == [(dt.date(2024, 3, 4), "https://www.example.org/hearings/a", "Interior budget")]
    assert pages.written_day(next(pages.DATE.finditer("Wednesday, March 11th, 2026"))) == dt.date(2026, 3, 11)


def test_listing_decodes_html_entities_in_source_urls():
    # The Veterans listing publishes a literal ampersand inside the event path.
    page = '<div>June 7, 2022</div><a href="/2022/6/organizations &amp; advocates">Press conference</a>'
    rows = records.listing_page("veterans.senate.gov", "/hearings?page={}", 1, lambda _: page)
    assert rows == [(dt.date(2022, 6, 7), "https://www.veterans.senate.gov/2022/6/organizations & advocates", "Press conference")]


def test_house_refusal_is_not_saved_as_absence(monkeypatch):
    from congress_api.house.records import fetch_xml
    def refusal(*args, **kwargs):
        raise RuntimeError("403")
    monkeypatch.setattr("congress_api.http.get_with_retry", refusal)
    with pytest.raises(RuntimeError, match="403"):
        fetch_xml(["https://docs.house.gov/m.xml"], "committee-meeting", False)


def test_archive_absence_is_probed_once_and_outputs_settle(tmp_path, monkeypatch):
    import gzip
    from types import SimpleNamespace
    from congress_api.inventory.main import main
    m = {"eventId": "1", "congress": 116, "date": "2020-01-02", "chamber": "Senate", "type": "Meeting", "title": "Closed briefing", "meetingStatus": "Scheduled", "committees": [{"systemCode": "ssaf00"}]}
    meetings = tmp_path / "meetings.jsonl.gz"
    meetings.write_bytes(gzip.compress((json.dumps(m) + "\n").encode()))
    for name, header in {"gpo": "package_id", "videos": "package_id,status", "channels": "systemCode", "recordings": "event_id,recording", "house_documents_found": "event_id,kind,url", "senate_documents_found": "event_id,kind,url", "senate_hearing_pages_found": "event_id,title", "house_witnesses_found": "event_id,name", "senate_witnesses_found": "event_id,name"}.items():
        (tmp_path / f"{name}.csv").write_text(header + "\n")
    calls = []
    def absent(session, url, **kwargs):
        calls.append(url)
        return SimpleNamespace(status_code=404)
    from congress_api.inventory import acquisition
    from congress_api.inventory.common import write_state
    probes = {}
    days = [('ag', '2020-01-02')]
    # The acquisition seam is independent of orchestration and accepts the fake.
    acquisition.probe_days(days, probes, dt.date(2026, 9, 27), get=absent)
    assert len(calls) == 8
    assert acquisition.probe_days(days, probes, dt.date(2026, 9, 27), get=absent) == 0
    # Use the actual committee code selected for this fixture.
    from congress_api.inventory.text_sources import senate_comms
    from congress_api.committees import codes_of
    comm, = senate_comms(m, codes_of(m))
    write_state(tmp_path / 'inventory.json.gz', {'probes': {f'{comm}|2020-01-02': probes['ag|2020-01-02']}})
    args = dict(meetings=meetings, state_dir=tmp_path, output_dir=tmp_path, gpo_path=tmp_path / "gpo.csv", videos_path=tmp_path / "videos.csv", tinydb_dir=tmp_path,
                recordings=tmp_path / "recordings.csv", channels_csv_path=tmp_path / "channels.csv", as_of=dt.date(2026, 9, 27), offline=True)
    main(**args)
    first = (tmp_path / "hearing_text_sources.csv").read_bytes()
    assert len(calls) == 8
    main(**args)
    assert len(calls) == 8 and (tmp_path / "hearing_text_sources.csv").read_bytes() == first
