"""Senate scheduling dates and live source observations have separate meanings."""
import datetime as dt
import gzip
import json
from types import SimpleNamespace

import pytest
from committee_meeting.common import Ref
from congress_api.acquisition import senate as records
from congress_api.adapters.common import AdapterContext
from congress_api.adapters.senate import records as adapted_records
from congress_api.models.content import RawContent
from congress_api.parsers.senate import parsed as records_parsed
from congress_api.retention.tables import read_state, write_state
from congress_api.transport import http as records_http

HOST = "budget.senate.gov"
PAGE = "https://www.budget.senate.gov/hearings/retained"
LISTING = "https://www.budget.senate.gov/hearings?page=1"
HTML = b"<title>Retained hearing</title><p>September 20, 2026</p>"
STAMP = "2026-09-27T12:00:00+00:00"
TODAY = dt.date(2026, 9, 27)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(records, "timestamp", lambda: STAMP)


def setup_inputs(tmp_path, *, saved=True, listing_checked="2026-09-27"):
    meeting = {"eventId": "1", "congress": 119, "date": "2026-09-20", "meetingStatus": "Scheduled", "updateDate": "v1",
               "chamber": "Senate", "type": "Meeting", "title": "Hearings to examine transparency", "committees": [{"systemCode": "ssbu00"}]}
    path = tmp_path / "meetings.jsonl.gz"
    path.write_bytes(gzip.compress((json.dumps(meeting) + "\n").encode()))
    if saved:
        page = {"title": "Prior hearing", "lines": ["September 20, 2026"], "witnesses": [{"name": "Alex Smith"}], "documents": [["witness statement", "Testimony", "https://example.org/statement.pdf"]],
                "checked": "2026-09-01", "version": "", "events": ["1"], "retrieved_at": "2026-09-01T12:00:00+00:00"}
        write_state(tmp_path / "senate.json.gz", {HOST: {"versions": {"1": "v1"}, "checked": listing_checked, "listings": {PAGE: ["2026-09-20", "Retained hearing"]}, "pages": {PAGE: page}}})
    return dict(meetings=path, state_dir=tmp_path, output_dir=tmp_path, as_of=TODAY)


def test_cache_import_has_only_import_time_and_schedule_day(tmp_path, monkeypatch):
    monkeypatch.setattr(records, "seed_fetch", lambda cache, url: HTML.decode())
    monkeypatch.setattr(records_http, "get_with_retry", lambda *args, **kwargs: pytest.fail("cache import made a live request"))
    result, activity = records.fetch_page(PAGE, {"events": ["1"]}, dt.date(2020, 1, 1), cache=tmp_path)
    assert result["imported_at"] == STAMP and result["checked"] == "2020-01-01"
    assert "retrieved_at" not in result and "last_check" not in result and "events" not in result
    assert "last_check" not in activity and activity["events"] == ["1"] and result["title"] == "Retained hearing"


@pytest.mark.parametrize("status,expected", [(200, "present"), (404, "not_found")])
def test_live_page_receipt_uses_actual_time_and_preserves_existing_result(status, expected, monkeypatch):
    calls = []
    def response(_session, url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(status_code=status, content=HTML)
    monkeypatch.setattr(records_http, "get_with_retry", response)
    result, activity = records.fetch_page(PAGE, {}, dt.date(2020, 1, 1))
    assert calls == [(PAGE, {"allowed": (200, 404)})]
    assert result["checked"] == "2020-01-01"
    assert "last_check" not in result and "observation_check" not in result and "events" not in result
    check = activity["last_check"]
    assert check["mode"] == "live" and check["outcome"] == expected and check["completed_at"] == STAMP
    assert check["receipts"] == [{"url": PAGE, "started_at": STAMP, "completed_at": STAMP, "status_code": status, "outcome": "retrieved" if status == 200 else "not_found"}]
    legacy = {k: value for k, value in result.items() if k not in ("last_check", "observation_check", "retrieved_at", "checked", "events", "version", "parser_version")}
    assert legacy == (records_parsed(HTML.decode(), PAGE) if status == 200 else {"title": "", "lines": [], "witnesses": [], "documents": [], "absent": True, "raw_html": RawContent.from_bytes(HTML, "text/html").source_dict()})


def test_failed_page_refresh_keeps_good_result_and_exports_error(tmp_path, monkeypatch):
    args = setup_inputs(tmp_path)
    prior = read_state(tmp_path / "senate.json.gz")[HOST]["pages"][PAGE]
    def refused(*args, **kwargs):
        raise RuntimeError("403 Forbidden")
    monkeypatch.setattr(records_http, "get_with_retry", refused)
    with pytest.raises(RuntimeError, match="403 Forbidden"):
        records.main(**args)
    state = read_state(tmp_path / "senate.json.gz")
    page = state[HOST]["pages"][PAGE]
    workflow = state[HOST]["workflow"][PAGE]
    kept = {key: value for key, value in prior.items() if key not in ("events", "candidate_events", "match_details", "last_check", "observation_check", "cache_replay")}
    assert {key: page[key] for key in kept} == kept
    assert "events" not in page and "last_check" not in page
    assert workflow["events"] == prior["events"]
    assert workflow["last_check"]["outcome"] == state[HOST]["last_attempt"]["outcome"] == "error"
    assert workflow["last_check"]["receipts"][0]["url"] == PAGE
    context = AdapterContext(now=dt.datetime(2026, 9, 28, tzinfo=dt.UTC), input_id="senate-state", provider="senate", ids=lambda kind,key: kind+":"+key)
    emitted = list(adapted_records(state, context, meetings={(119, "senate", "1"): Ref(kind="meeting", id="meeting-1")}))
    assessment, = [item for item in emitted if item.kind == "assessment"]
    assert assessment.status == "error" and assessment.scope == PAGE
    assert assessment.observed_at == dt.datetime.fromisoformat(STAMP)
    assert any(item.kind == "material" for item in emitted)
    assert any(item.kind == "appearance" for item in emitted)
    source, = [item for item in emitted if item.kind == "source_record"]
    assert source.retrieved_at == dt.datetime.fromisoformat(prior["retrieved_at"])


def test_failed_listing_refresh_keeps_old_listing_and_failure_receipt(tmp_path, monkeypatch):
    args = setup_inputs(tmp_path, listing_checked="2026-09-01")
    prior = read_state(tmp_path / "senate.json.gz")[HOST]
    monkeypatch.setattr(records, "listed", lambda host,get,saved: get(LISTING))
    def refused(*args, **kwargs):
        raise RuntimeError("503 Unavailable")
    monkeypatch.setattr(records_http, "get_with_retry", refused)
    with pytest.raises(RuntimeError, match="503 Unavailable"):
        records.main(**args)
    saved = read_state(tmp_path / "senate.json.gz")[HOST]
    assert saved["listings"] == prior["listings"]
    assert {url: {key: value for key, value in page.items() if key != "events"} for url, page in saved["pages"].items()} == {
        url: {key: value for key, value in page.items() if key != "events"} for url, page in prior["pages"].items()}
    assert saved["workflow"][PAGE]["events"] == ["1"] and "events" not in saved["pages"][PAGE]
    assert saved["checked"] == prior["checked"]
    assert saved["last_check"]["receipts"][0]["url"] == LISTING and saved["last_check"]["outcome"] == "error"


def test_successful_listing_receipts_and_seed_import_are_distinct(tmp_path, monkeypatch):
    args = setup_inputs(tmp_path, saved=False)
    def listing(host, get, saved):
        get(LISTING)
        return [(dt.date(2026, 9, 20), PAGE, "Retained hearing")], {"form": "/hearings?page={}", "from_0": False}
    monkeypatch.setattr(records, "listed", listing)
    monkeypatch.setattr(records_http, "get_with_retry", lambda *args, **kwargs: SimpleNamespace(status_code=200, content=HTML))
    monkeypatch.setattr("congress_api.matching.senate_pages.match_pages", lambda *args: ([], [], []))
    records.main(**args)
    saved = read_state(tmp_path / "senate.json.gz")[HOST]
    assert saved["last_check"]["receipts"][0]["url"] == LISTING
    assert saved["last_check"]["receipts"][0]["status_code"] == 200
    assert saved["pages"][PAGE]["retrieved_at"] == STAMP
    write_state(tmp_path / "senate.json.gz", {})
    monkeypatch.setattr(records, "seed_fetch", lambda cache,url: HTML.decode())
    monkeypatch.setattr(records_http, "get_with_retry", lambda *args, **kwargs: pytest.fail("seed import made a live request"))
    records.main(**args, seed_cache=tmp_path, offline=True)
    seeded = read_state(tmp_path / "senate.json.gz")[HOST]
    assert seeded["imported_at"] == seeded["pages"][PAGE]["imported_at"] == STAMP
    assert "last_check" not in seeded and "last_check" not in seeded["pages"][PAGE]


def test_initial_page_failure_remains_incomplete_offline(tmp_path, monkeypatch):
    args = setup_inputs(tmp_path)
    state = read_state(tmp_path / "senate.json.gz")
    state[HOST]["pages"] = {}
    write_state(tmp_path / "senate.json.gz", state)
    monkeypatch.setattr(records_http, "get_with_retry", lambda *args, **kwargs: SimpleNamespace(status_code=200, content=b"unrecognized page"))
    with pytest.raises(RuntimeError, match="Unrecognized"):
        records.main(**args)
    saved = read_state(tmp_path / "senate.json.gz")[HOST]
    page = saved["pages"][PAGE]
    assert page["status"] == "error" and "checked" not in page and "last_check" not in page
    assert saved["workflow"][PAGE]["last_check"]["receipts"][0]["outcome"] == "unrecognized_page"
    with pytest.raises(RuntimeError, match="incomplete"):
        records.main(**args, offline=True)


@pytest.mark.parametrize("content,headers", [(b"%PDF-1.7\n<title>Misleading title in binary</title>", {}), (b"opaque bytes", {"Content-Type": "application/pdf; version=1.7"})])
def test_pdf_response_never_enters_html_parser(content, headers, tmp_path, monkeypatch):
    args = setup_inputs(tmp_path)
    prior = read_state(tmp_path / "senate.json.gz")[HOST]["pages"][PAGE]
    monkeypatch.setattr(records_http, "get_with_retry", lambda *args, **kwargs: SimpleNamespace(status_code=200, content=content, headers=headers))
    monkeypatch.setattr(records, "parsed", lambda *args: pytest.fail("PDF response entered HTML parser"))
    with pytest.raises(RuntimeError, match="PDF content"):
        records.main(**args)
    host = read_state(tmp_path / "senate.json.gz")[HOST]
    saved = host["pages"][PAGE]
    kept = {key: value for key, value in prior.items() if key not in ("events", "candidate_events", "match_details", "last_check", "observation_check", "cache_replay")}
    assert {key: saved[key] for key in kept} == kept
    receipt, = host["workflow"][PAGE]["last_check"]["receipts"]
    assert receipt["outcome"] == "unsupported_format" and receipt["detected_format"] == "pdf"


def test_legacy_garbled_pdf_lines_remain_raw_with_unverified_issue():
    url = "https://www.intelligence.senate.gov/wp-content/uploads/2024/08/sites-default-files-hearings-105290.pdf"
    payload = {"title": "", "lines": ["\x04\ufffd\x06\ufffd garbled bytes"], "documents": [], "witnesses": [], "events": []}
    context = AdapterContext(now=dt.datetime(2026, 9, 28, tzinfo=dt.UTC), input_id="senate-state", provider="senate", ids=lambda kind,key: kind+":"+key)
    emitted = list(adapted_records({"intelligence.senate.gov": {"pages": {url: payload}}}, context, meetings={}))
    source, = [item for item in emitted if item.kind == "source_record"]
    assert source.payload == payload
    issue, = [item for item in emitted if item.kind == "data_issue" and item.id.endswith("possible-binary-source")]
    assert issue.category == "unverified" and issue.provenance.basis == "inferred"
    assert "format remains unverified" in issue.explanation
