"""Retained publisher evidence survives the complete production index rebuild."""

from hashlib import sha256
import json
from pathlib import Path

import pytest

from congress_api.retention.raw_archive import CAPTURES_KEY
from congress_api.retention.raw_catalog import DOCUMENTS, rebuild_catalog
from test_raw_catalog import table
from test_raw_rebuild import retain
from test_raw_source_sync import MemoryStore


FIXTURES = Path(__file__).parent / "fixtures/meeting_inventory"
CSCE = json.loads((FIXTURES / "csce/cases.json").read_text())


def published_sources(store, url):
    return [row for row in table(store).to_pylist() if row["source_url"] == url]


def published_documents(store, url):
    return [row for row in table(store, DOCUMENTS).to_pylist()
            if url in (row.get("source_urls") or [])]


@pytest.mark.parametrize("case", CSCE, ids=lambda case: case["file"])
def test_retained_csce_context_survives_both_published_tables(case):
    store = MemoryStore()
    raw = (FIXTURES / "csce" / case["file"]).read_bytes()
    assert sha256(raw).hexdigest() == case["sha256"]
    receipt = retain(store, {}, family="senate/pages", source_file=case["file"],
                     url=case["url"], body=raw)
    before = dict(store.objects)
    rebuild_catalog(store, table(store, CAPTURES_KEY), workers=1)
    kinds = {"witness statement": "witness-statement", "witness biography": "witness-biography"}
    for expected in case["documents"]:
        sources = published_sources(store, expected["url"])
        documents = published_documents(store, expected["url"])
        assert sources and len(documents) == 1
        for row in [*sources, *documents]:
            assert row["body_key"] is None  # Retaining a page does not retain its attachments.
            assert row["source_page_date"] == [case["date"]]
            assert row["source_publisher_committee_code"] == ["jcse00"]
            assert row.get("source_witness_name") == (expected["witnesses"] or None)
            assert expected["kind"] in row["source_document_type"]
            if expected["kind"] in kinds:
                assert kinds[expected["kind"]] in row["document_kind"]
            matching = [occurrence for occurrence in row["source_occurrences"]
                        if occurrence.get("source_link_url") == [expected["url"]]]
            assert matching
            assert any(occurrence.get("source_receipt_key") == [receipt] for occurrence in matching)
            assert any(occurrence.get("source_page_sha256") == [case["sha256"]] for occurrence in matching)
    assert all(store.objects[key] == value for key, value in before.items())


def test_house_witness_xml_retains_owner_and_distinct_document_roles():
    store = MemoryStore()
    retain(store, {"eventId": 115588, "congress": 118, "chamber": "House",
                   "committees": [{"systemCode": "hsap01"}]},
           family="congress/meetings", source_file="meeting.json")
    receipt = retain(store, {}, family="house/witness-xml", source_file="witnesses.xml",
                     url="https://docs.house.gov/meetings/AP/AP01/20230329/115588/witnesslist.xml",
                     body=(FIXTURES / "house-witnesses.xml").read_bytes())
    rebuild_catalog(store, workers=1)
    for marker, kind, native in (("Bio", "witness-biography", "WB"), ("Wstate", "witness-statement", "WS")):
        url = f"http://docs.house.gov/meetings/AP/AP01/20230329/115588/HHRG-118-AP01-{marker}-CaliffR-20230329.pdf"
        sources = published_sources(store, url)
        documents = published_documents(store, url)
        assert sources and len(documents) == 1
        for row in [*sources, *documents]:
            assert row["document_kind"] == [kind]
            assert row["source_document_type"] == [native]
            assert row["source_committee_code"] == ["hsap01"]
            assert row["source_witness_name"] == ["The Honorable Robert M. Califf M.D., MACC"]
            assert any(occurrence.get("source_receipt_key") == [receipt]
                       for occurrence in row["source_occurrences"])


def test_repeated_csce_link_keeps_each_role_with_its_own_witness_context():
    store = MemoryStore()
    url = "https://www.csce.gov/shared.pdf"
    raw = (b'<html><div class="paragraph--witness"><div class="witness__field-name">Alex Smith</div>'
           b'<div class="witness__field-testimony"><a href="/shared.pdf"></a></div></div>'
           b'<p><a href="/shared.pdf">Panelist Biographies</a></p></html>')
    retain(store, {}, family="senate/pages", source_file="page.html",
           url="https://www.csce.gov/hearings/example", body=raw)
    rebuild_catalog(store, workers=1)
    sources, documents = published_sources(store, url), published_documents(store, url)
    assert sources and len(documents) == 1
    for row in [*sources, *documents]:
        claims = {tuple(occurrence["source_document_type"]): occurrence
                  for occurrence in row["source_occurrences"] if occurrence.get("source_document_type")}
        assert claims[("witness statement",)]["source_witness_name"] == ["Alex Smith"]
        assert not claims[("witness biography",)].get("source_witness_name")
        assert claims[("witness biography",)]["source_link_label"] == ["Panelist Biographies"]


def test_failed_generated_xml_probe_remains_a_probe_after_metadata_only_replay():
    store = MemoryStore()
    url = "https://example.test/McCullough-Longform-Vita.xml"
    retain(store, {"xml_url": url, "pdf_url": url.replace(".xml", ".pdf"),
                   "status": "not_found", "http_status": 404, "checked_at": "2026-09-27"},
           family="documents", source_file="external-sources/hearing-text/pdf_xml_probe/attempts.jsonl")
    rebuild_catalog(store, seeds=[{"url": url}], workers=1)
    sources, documents = published_sources(store, url), published_documents(store, url)
    assert sources and len(documents) == 1
    for row in [*sources, *documents]:
        assert row["record_role"] == ["capture-state"]
        assert row["source_probe_status"] == ["not_found"]
        assert row["source_association_basis"] == ["generated_xml_probe"]
        assert row["body_key"] is None


def test_unusable_retained_response_cannot_supply_document_identity():
    store = MemoryStore()
    for number in range(2):
        url = f"https://intelligence.house.gov/{number}.pdf"
        retain(store, {"url": url, "raw_path": "historical.pdf", "http_status": 200,
                       "usable": False, "body_complete": True, "format": "pdf_missing_eof"},
               family="documents", source_file="capture/receipts.jsonl", url=url,
               body=b"%PDF-1.7\ndamaged historical bytes", pointer=["raw_path"])
    rebuild_catalog(store, workers=1)
    documents = [row for row in table(store, DOCUMENTS).to_pylist()
                 if row.get("body_key")]
    assert len(documents) == 2
    assert len({row["document_id"] for row in documents}) == 2
    assert all(row["record_role"] == ["error-response"] for row in documents)
    assert all(row["response_usable"] == ["false"] for row in documents)
