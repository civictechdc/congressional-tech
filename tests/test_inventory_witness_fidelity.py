from pathlib import Path
import datetime as dt
from types import SimpleNamespace
from xml.etree.ElementTree import ParseError
from pypdf.errors import PyPdfError

import pytest

from congress_api.inventory import witness_lists
from congress_api.inventory.witness_lists import document_witnesses, pdf_observation
from congress_api.witnesses import witness

FIXTURES = Path(__file__).parent / "fixtures" / "meeting_inventory"


def test_real_pdf_keeps_unprefixed_academic_name_and_source_text():
    result = pdf_observation((FIXTURES / "witness-hubzone.pdf").read_bytes())
    assert [person["name"] for person in result["people"]] == ["William B. Shear", "Hannibal “Mike” Ware", "Shirley Bailey", "Mansooreh Mollaghasemi"]
    assert result["people"][-1]["organization"] == "Atria Technologies LLC, Orlando, FL"
    assert "*Testifying on behalf of the HUBZone Contractors National Council" in result["source_text"]
    assert "Mansooreh Mollaghasemi, Ph.D." in result["source_text"]


def test_retired_military_parenthetical_does_not_corrupt_person_name():
    result = pdf_observation((FIXTURES / "witness-military-affiliation.pdf").read_bytes())
    assert result["people"][1]["name"] == "Randall Wooten"
    assert "Colonel Randall Wooten (USAF, Ret.)" in result["source_text"]
    assert document_witnesses("Mr. Danny Pummill*\nPrincipal Deputy\nDepartment\n")[0]["name"] == "Danny Pummill"


@pytest.mark.parametrize("filename,names", [
    ("witness-scan-agriculture.pdf", ["Scott D. O’Malia", "Mark P. Wetjen"]),
    ("witness-scan-small-business.pdf", ["Maria Contreras-Sweet"]),
    ("witness-scan-judiciary.pdf", ["Donald F. McGahn II"]),
])
def test_reviewed_scan_requires_exact_bytes(filename, names):
    data = (FIXTURES / filename).read_bytes()
    result = pdf_observation(data)
    assert [person["name"] for person in result["people"]] == names
    assert result["text_present"] is False and not result["source_text"].strip()
    assert result["reviewed_reading"]["page"] == 1
    assert result["reviewed_reading"]["basis"] == "visual reading of rendered official PDF"
    altered = pdf_observation(data + b"\n")
    assert "reviewed_reading" not in altered and not altered["people"]


def test_member_day_schedule_stays_unparsed_without_inventing_people():
    result = pdf_observation((FIXTURES / "house-member-schedule.pdf").read_bytes())
    assert result["text_present"] and result["people"] == []
    assert "Time Slot" in result["source_text"]


@pytest.mark.parametrize('filename,names,pages,text_present', [
    ('witness-scan-immigration.pdf', ['Vivek Wadhwa', 'Michael Teitelbaum', 'Puneet S. Arora', 'Julian Castro',
                                    'Julie Myers Wood', 'Chris Crane', 'Jessica Vaughan', 'Muzaffar Chishti'], [1], False),
    ('witness-helium-multipage.pdf', ['Tim Spisak', 'Daniel Garcia-Diaz', 'Kimberly Elmore', 'Rodney Morgan',
                                   'Brad Boersen', 'Gary Page', 'Sam Aronson', 'David Joyner', 'Tom Thoman',
                                   'Kevin Lynch', 'Walter Nelson', 'Nick Haines', 'Scott Kaltrider'], [1, 2], True),
])
def test_visually_reviewed_column_and_unprefixed_names(filename, names, pages, text_present):
    data = (FIXTURES / filename).read_bytes()
    result = pdf_observation(data)
    assert [person['name'] for person in result['people']] == names
    assert result['text_present'] == text_present
    assert (result['reviewed_reading'].get('pages') or [result['reviewed_reading']['page']]) == pages
    assert len(result['pages']) == len(pages)
    assert 'reviewed_reading' not in pdf_observation(data + b'\n')


def test_mods_credentials_do_not_erase_later_location_or_organization_suffix():
    actual = witness("O'Malia, Hon. Scott D., Commissioner, U.S. Commodity Futures Trading Commission, Washington, D.C")
    assert actual["organization"] == "U.S. Commodity Futures Trading Commission, Washington, D.C"
    assert witness("Mansooreh Mollaghasemi, Ph.D., President, Atria Technologies, LLC")["organization"] == "Atria Technologies, LLC"


STAMP = "2026-09-27T12:00:00+00:00"
MODS = (FIXTURES.parent / "gpo_metadata" / "CHRG-113hhrg21122.xml").read_bytes()
URL = "https://www.govinfo.gov/metadata/pkg/CHRG-113hhrg21122/mods.xml"


def capture(state, *, today=dt.date(2026, 9, 27), offline=False, **kwargs):
    return witness_lists.get_witnesses("CHRG-113hhrg21122", URL, state, "v1", "2013-07-23", today, offline, package=True, **kwargs)


def test_live_mods_capture_uses_actual_receipt_time_and_retains_source_names(monkeypatch):
    monkeypatch.setattr(witness_lists, "timestamp", lambda: STAMP)
    monkeypatch.setattr(witness_lists.http, "get_with_retry", lambda *a, **k: SimpleNamespace(status_code=200, content=MODS))
    state = {}
    people = capture(state, today=dt.date(2020, 1, 1))
    saved = state["CHRG-113hhrg21122"]
    assert people and saved["source_witnesses"]
    assert saved["checked"] == "2020-01-01" and saved["retrieved_at"] == STAMP
    assert saved["last_check"] == saved["observation_check"] == {
        "mode": "live", "url": URL, "started_at": STAMP, "completed_at": STAMP, "status_code": 200, "outcome": "present"}
    monkeypatch.setattr(witness_lists.http, "get_with_retry", lambda *a, **k: pytest.fail("unchanged successful MODS requested again"))
    assert capture(state, today=dt.date(2026, 9, 27)) == people


def test_imported_mods_never_claims_a_live_retrieval(tmp_path, monkeypatch):
    (tmp_path / "mods").mkdir()
    (tmp_path / "mods" / "CHRG-113hhrg21122.xml").write_bytes(MODS)
    monkeypatch.setattr(witness_lists, "timestamp", lambda: STAMP)
    monkeypatch.setattr(witness_lists.http, "get_with_retry", lambda *a, **k: pytest.fail("cache import requested network"))
    state = {}
    assert capture(state, offline=True, seed_cache=tmp_path)
    saved = state["CHRG-113hhrg21122"]
    assert "retrieved_at" not in saved and saved["imported_at"] == STAMP
    assert saved["last_check"]["mode"] == "cache_import"


def test_unchanged_mods_404_is_retried_after_a_week(monkeypatch):
    calls = []
    def fetch(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(status_code=404 if len(calls) == 1 else 200, content=MODS)
    monkeypatch.setattr(witness_lists.http, "get_with_retry", fetch)
    state = {}
    assert capture(state, today=dt.date(2026, 9, 20)) == []
    assert capture(state, today=dt.date(2026, 9, 26)) == [] and len(calls) == 1
    assert capture(state, today=dt.date(2026, 9, 27)) and len(calls) == 2
    assert not state["CHRG-113hhrg21122"]["absent"]


@pytest.mark.parametrize("body", [b"<html><title>Access denied</title></html>", b"broken XML"])
def test_invalid_live_mods_keeps_prior_observation_and_retries_next_run(body, monkeypatch):
    monkeypatch.setattr(witness_lists, "timestamp", lambda: STAMP)
    monkeypatch.setattr(witness_lists.http, "get_with_retry", lambda *a, **k: SimpleNamespace(status_code=200, content=MODS))
    state = {}
    people = capture(state)
    prior = state["CHRG-113hhrg21122"].copy()
    # A package update requires a new capture even while the old check is young.
    state["CHRG-113hhrg21122"]["version"] = "old"
    monkeypatch.setattr(witness_lists.http, "get_with_retry", lambda *a, **k: SimpleNamespace(status_code=200, content=body))
    with pytest.raises((ValueError, ParseError)):
        capture(state)
    saved = state["CHRG-113hhrg21122"]
    assert saved["people"] == people and saved["observation_check"] == prior["observation_check"]
    assert saved["last_check"]["outcome"] == "error" and saved["last_check"]["status_code"] == 200
    assert saved["retrieved_at"] == prior["retrieved_at"]
    assert capture(state, offline=True) == people
    monkeypatch.setattr(witness_lists.http, "get_with_retry", lambda *a, **k: SimpleNamespace(status_code=200, content=MODS))
    assert capture(state) == people and state["CHRG-113hhrg21122"]["last_check"]["outcome"] == "present"


def test_first_failed_capture_stays_missing_offline_and_retryable_live(monkeypatch):
    def refused(*args, **kwargs):
        raise RuntimeError("503 Unavailable")
    monkeypatch.setattr(witness_lists.http, "get_with_retry", refused)
    state = {}
    with pytest.raises(RuntimeError, match="503"):
        capture(state)
    assert "people" not in state["CHRG-113hhrg21122"]
    with pytest.raises(RuntimeError, match="Missing saved witness source"):
        capture(state, offline=True)
    monkeypatch.setattr(witness_lists.http, "get_with_retry", lambda *a, **k: SimpleNamespace(status_code=200, content=MODS))
    assert capture(state)


def test_corrupt_pdf_is_failed_capture_not_an_empty_scan(monkeypatch):
    monkeypatch.setattr(witness_lists.http, "get_with_retry", lambda *a, **k: SimpleNamespace(status_code=200, content=b"%PDF-1.7 broken"))
    state = {}
    with pytest.raises(PyPdfError):
        witness_lists.get_witnesses("doc", URL, state, "v1", "2026-09-20", dt.date(2026, 9, 27), False)
    assert state["doc"]["last_check"]["outcome"] == "error" and "people" not in state["doc"]


def test_saved_offline_and_unchanged_mods_do_not_require_meeting_date(monkeypatch):
    monkeypatch.setattr(witness_lists.http, "get_with_retry", lambda *a, **k: pytest.fail("saved unchanged source fetched again"))
    state = {"key": {"people": [{"name": "Alex Smith"}], "version": "v1"}}
    for offline in (True, False):
        assert witness_lists.get_witnesses("key", URL, state, "v1", "", dt.date(2026, 9, 27), offline, package=True) == state["key"]["people"]
