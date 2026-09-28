"""Retained House evidence must not change recovery CSV behavior."""

import datetime as dt
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from congress_api.house import evidence, records, repository
from congress_api.inventory.common import read_state, write_state

FIXTURES = Path(__file__).parent / "fixtures/meeting_inventory"


def xml(name):
    return repository.parse_xml((FIXTURES / name).read_bytes())


def test_formats_keep_three_documents_and_six_exact_urls():
    root = xml("house-formats.xml")
    result = records.parsed(root, None, "", "unfetched")
    groups = result["evidence"]["document_groups"]
    assert result["evidence"]["schema_version"] == evidence.SCHEMA_VERSION
    assert len(groups) == len(result["documents"]) == 3
    assert [file["url"] for group in groups for file in group["files"]] == [file.get("doc-url") for file in root.findall("meeting-documents/meeting-document/files/file")]
    assert sum(len(group["files"]) for group in groups) == 6
    assert [file["format"] for file in groups[0]["files"]] == ["PDF", "XML"]
    assert groups[0]["files"][0]["url"].startswith("http://")
    assert "%20" in groups[0]["files"][0]["url"]
    assert result["documents"][0][2].startswith("https://")  # Existing CSV spelling is stable.
    assert groups[0]["metadata"]["attributes"]["publish-date"] == "2017-07-07T11:59:00.303"
    assert groups[0]["files"][0]["metadata"]["attributes"]["add-date"] == "2017-07-07T11:57:02.243"
    assert all(group["owning_witness_selector"] is None for group in groups)


def test_witness_ownership_and_order_are_source_local():
    result = records.parsed(xml("house-formats.xml"), xml("house-witnesses.xml"), "", "present")
    retained = result["evidence"]
    witness = retained["witness_observations"][0]
    assert witness["selector"] == "/witness-list/panel[1]/witness[1]"
    assert witness["panel_selector"] == retained["panels"][0]["selector"]
    assert witness["display_order"] == "NA"  # Do not invent numeric ordering.
    assert retained["panels"][0]["sort_order"] == "1"
    assert witness["source_order"] == 1
    assert witness["metadata"]["attributes"]["testified"] == "Yes"
    witness_documents = [group for group in retained["document_groups"] if group["source"] == "witness_xml"]
    assert len(witness_documents) == 2
    assert {group["owning_witness_selector"] for group in witness_documents} == {witness["selector"]}
    assert witness_documents[0]["files"][0]["selector"].endswith("/witness-document[1]/files/file[1]")
    assert {group["type"] for group in witness_documents} == {"WB", "WS"}


def test_removed_rows_survive_evidence_but_not_current_csvs():
    root = xml("house-removed.xml")
    wlist = xml("house-witnesses.xml")
    wlist.find("panel/witness").set("remove-date", "2026-09-27")
    result = records.parsed(root, wlist, "", "present")
    assert result["documents"] == result["amendments"] == result["witnesses"] == []
    assert len(result["evidence"]["document_groups"]) == 5
    assert all(not group["active"] for group in result["evidence"]["document_groups"])
    assert all(not file["active"] for group in result["evidence"]["document_groups"] for file in group["files"])
    assert not result["evidence"]["witness_observations"][0]["active"]


def test_removed_file_keeps_its_exact_source_attributes():
    root = xml("house-formats.xml")
    root.find("meeting-documents/meeting-document/files/file").set("remove-date", "2026-09-27")
    result = records.parsed(root, None, "", "unfetched")
    group = result["evidence"]["document_groups"][0]
    assert group["active"] and not group["files"][0]["active"] and group["files"][1]["active"]
    assert result["documents"][0][2].endswith(".xml")


def test_seed_import_time_is_not_a_live_check(tmp_path):
    path = tmp_path / "docs_house_xml/meeting/106245.xml"
    path.parent.mkdir(parents=True)
    path.write_bytes((FIXTURES / "house-formats.xml").read_bytes())
    seeded = records.seed({"eventId": "106245"}, tmp_path)
    assert dt.datetime.fromisoformat(seeded["imported_at"]).utcoffset() == dt.timedelta(0)
    assert "last_check" not in seeded and "retrieved_at" not in seeded
    assert seeded["seed"] == "research cache"


def test_live_receipts_preserve_absence_and_retrieval_without_document_fetches(monkeypatch):
    called = []
    def get(_session, url, **_kwargs):
        called.append(url)
        return SimpleNamespace(status_code=404, content=b"") if "WList" in url else SimpleNamespace(status_code=200, content=(FIXTURES / "house-formats.xml").read_bytes())
    monkeypatch.setattr(records.http, "get_with_retry", get)
    result = records.fetch({"eventId": "106245"}, {"urls": ["https://docs.house.gov/meetings/RU/RU00/20170712/106245/HHRG-115-RU00-20170712.xml"]})
    check = result["last_check"]
    assert check["mode"] == "live" and check["outcome"] == "present"
    assert check["receipts"][0]["outcome"] == "retrieved"
    assert check["receipts"][1]["outcome"] == "not_found"
    assert len(called) == 2  # Linked PDF/XML document bodies are not fetched.
    assert dt.datetime.fromisoformat(result["retrieved_at"]).tzinfo is not None


def source_inputs(tmp_path, count=3):
    meetings = [{"eventId": str(index), "congress": 119, "date": "2026-09-26", "meetingStatus": "Scheduled", "updateDate": "v1", "chamber": "House", "title": "Hearing", "type": "Hearing", "committees": []} for index in range(count)]
    path = tmp_path / "meetings.jsonl.gz"
    path.write_bytes(gzip.compress("".join(json.dumps(m) + "\n" for m in meetings).encode()))
    gpo = tmp_path / "gpo.csv"
    gpo.write_text("package_id\n")
    saved = {m["eventId"]: {"documents": [], "witnesses": [], "amendments": [], "status": "xml", "checked": "2026-09-27", "version": "v1"} for m in meetings}
    write_state(tmp_path / "house.json.gz", saved)
    return dict(meetings=path, gpo_path=gpo, state_dir=tmp_path, output_dir=tmp_path, as_of=dt.date(2026, 9, 27))


def test_parser_upgrade_uses_bounded_queue_and_legacy_state_works_offline(tmp_path, monkeypatch):
    args = source_inputs(tmp_path)
    records.main(**args, offline=True)
    legacy_csv = (tmp_path / "house_documents_found.csv").read_bytes()
    calls = []
    def fetch(m, previous, through_zyte=False, *, check=None):
        calls.append(m["eventId"])
        return {**previous, "evidence": evidence.retained_evidence(None, None)}
    monkeypatch.setattr(records, "fetch", fetch)
    records.main(**args, refresh_limit=1)
    assert len(calls) == 1
    assert sum("evidence" in item for item in read_state(tmp_path / "house.json.gz").values()) == 1
    assert (tmp_path / "house_documents_found.csv").read_bytes() == legacy_csv


def test_failed_refresh_keeps_prior_observation_and_failure_receipt(tmp_path, monkeypatch):
    args = source_inputs(tmp_path, count=1)
    def refused(*args, **kwargs):
        raise RuntimeError("403 Forbidden")
    monkeypatch.setattr(records.http, "get_with_retry", refused)
    with pytest.raises(RuntimeError, match="1 failed"):
        records.main(**args, refresh_limit=1)
    saved = read_state(tmp_path / "house.json.gz")["0"]
    assert saved["checked"] == "2026-09-27" and saved["version"] == "v1"
    assert saved["status"] == "xml"  # The prior source result was not rewritten as absent.
    assert saved["last_check"]["outcome"] == "error"
    assert saved["last_check"]["receipts"][0]["outcome"] == "error"
    assert "retrieved_at" not in saved


def test_first_check_failure_stays_incomplete_offline(tmp_path, monkeypatch):
    args = source_inputs(tmp_path, count=1)
    write_state(tmp_path / "house.json.gz", {})
    monkeypatch.setattr(records.http, "get_with_retry", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("403 Forbidden")))
    with pytest.raises(RuntimeError, match="1 missing, 1 failed"):
        records.main(**args)
    saved = read_state(tmp_path / "house.json.gz")["0"]
    assert saved["status"] == "error" and "checked" not in saved
    assert saved["last_check"]["outcome"] == "error"
    with pytest.raises(RuntimeError, match="1 missing, 0 failed"):
        records.main(**args, offline=True)


def test_no_meeting_page_is_an_absence_receipt_not_a_publication_claim(monkeypatch):
    monkeypatch.setattr(records.http, "get_with_retry", lambda *args, **kwargs: SimpleNamespace(status_code=200, content=b"No meeting data is available"))
    result = records.fetch({"eventId": "1"}, {})
    assert result["status"] == "page"  # Keep legacy parsing behavior.
    assert result["page_status"] == "no_meeting_data"
    assert result["last_check"]["outcome"] == "not_found"
