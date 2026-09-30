"""Offline adaptation preserves source limitations and meeting boundaries."""
from datetime import UTC, datetime

from committee_meeting.common import Ref
from congress_api.adapters.common import AdapterContext
from congress_api.adapters.senate import records


NOW = datetime(2026, 9, 27, tzinfo=UTC)
PAGE = "https://example.senate.gov/hearings/evidence"
PDF = "http://example.senate.gov/download/Testimony%20A.pdf?download=1"


def context():
    return AdapterContext(now=NOW, input_id="senate-input", provider="senate.committee", ids=lambda kind, key: kind + ":" + key)


def page(**updates):
    return {"title": "Evidence hearing", "lines": ["September 20, 2026"], "witnesses": [{"name": "Alex Smith", "position": "Director", "organization": "Institute"}],
            "documents": [["witness statement", "Testimony", PDF]], "checked": "2026-09-25", "events": ["12"], "version": "", **updates}


def adapt(saved, meetings=None):
    state = {"example.senate.gov": {"listings": {PAGE: ["2026-09-20", "Evidence hearing"]}, "pages": {PAGE: saved}}}
    lookup = {(119, "senate", "12"): Ref(kind="meeting", id="meeting-12")} if meetings is None else meetings
    return list(records(state, context(), meetings=lookup))


def of_kind(rows, kind):
    return [row for row in rows if row.kind == kind]


def test_page_payload_exact_urls_and_match_provenance_survive():
    saved = page(extra_native_metadata={"future": True})
    rows = adapt(saved)
    source, = of_kind(rows, "source_record")
    assert source.payload == saved
    assert source.retrieved_at is None and source.imported_at == NOW
    assert source.input_snapshot_id == "senate-input"
    representation, = of_kind(rows, "representation")
    assert representation.locations[0].url == PDF
    assert representation.media_type == "application/pdf"
    link, = of_kind(rows, "material_link")
    assert link.subject.id == "meeting-12" and link.role == "statement"
    assert link.provenance.basis == "derived"
    assert link.provenance.method.name == "senate.records.match_pages" and link.provenance.method.version == "1"
    assert link.provenance.citations[0].selector == "/events/0"
    appearance, = of_kind(rows, "appearance")
    assert appearance.participation == "listed" and appearance.person is None
    assert appearance.affiliation.organization_name == "Institute"
    assert len(appearance.provenance.citations) == 2
    assert any(issue.category == "unverified" for issue in of_kind(rows, "data_issue"))


def test_ambiguous_event_cannot_link_or_create_fictional_appearances():
    lookup = {(118, "senate", "12"): Ref(kind="meeting", id="older"), (119, "senate", "12"): Ref(kind="meeting", id="newer")}
    rows = adapt(page(), lookup)
    assert len(of_kind(rows, "material")) == 1
    assert not of_kind(rows, "material_link") and not of_kind(rows, "appearance")
    assert not of_kind(rows, "meeting") and not of_kind(rows, "person")
    source, = of_kind(rows, "source_record")
    assert source.payload["witnesses"][0]["name"] == "Alex Smith"
    assert any(issue.category == "unlinked" for issue in of_kind(rows, "data_issue"))


def test_recorded_page_match_version_is_preserved():
    saved = page(match_details={"12": {"method": "senate.records.match_pages", "version": "2"}})
    rows = adapt(saved)
    link, = of_kind(rows, "material_link")
    assert link.provenance.method.name == "senate.records.match_pages"
    assert link.provenance.method.version == "2"
    assert link.provenance.citations[0].selector == "/match_details/12"
    assert of_kind(rows, "source_record")[0].payload == saved


def test_unmatched_document_is_retained():
    rows = adapt(page(events=[]))
    assert len(of_kind(rows, "material")) == len(of_kind(rows, "representation")) == 1
    assert not of_kind(rows, "material_link")
    assert any(issue.category == "unlinked" and issue.subject.kind == "material" for issue in of_kind(rows, "data_issue"))


def test_legacy_absence_is_unknown_even_with_checked_date():
    rows = adapt(page(absent=True, witnesses=[], documents=[]))
    assessment, = of_kind(rows, "assessment")
    assert assessment.status == "unknown" and assessment.observed_at is None
    assert assessment.scope == PAGE
    assert of_kind(rows, "source_record")[0].retrieved_at is None


def test_live_404_receipt_supports_bounded_absence():
    saved = page(absent=True, witnesses=[], documents=[], last_check={"mode": "live", "receipts": [
        {"url": PAGE, "status_code": 404, "outcome": "not_found", "completed_at": "2026-09-26T11:00:00+00:00"}]})
    rows = adapt(saved)
    assessment, = of_kind(rows, "assessment")
    assert assessment.status == "not_found" and assessment.observed_at == datetime(2026, 9, 26, 11, tzinfo=UTC)
    assert of_kind(rows, "source_record")[0].retrieved_at == assessment.observed_at
    other = page(absent=True, witnesses=[], documents=[], last_check={"mode": "live", "receipts": [
        {"url": PAGE + "/other", "status_code": 404, "outcome": "not_found", "completed_at": "2026-09-26T11:00:00+00:00"}]})
    assert of_kind(adapt(other), "assessment")[0].status == "unknown"


def test_site_wide_files_stay_unlinked_like_producer_filter():
    pages = {PAGE + f"/{index}": page(events=["12"]) for index in range(6)}
    state = {"example.senate.gov": {"pages": pages, "listings": {url: ["2026-09-20", "Evidence hearing"] for url in pages}}}
    rows = list(records(state, context(), meetings={(119, "senate", "12"): Ref(kind="meeting", id="meeting-12")}))
    assert len(of_kind(rows, "material")) == 6
    assert not of_kind(rows, "material_link")
    assert len(of_kind(rows, "appearance")) == 6
    assert all("site-wide" in issue.explanation for issue in of_kind(rows, "data_issue") if issue.subject.kind == "material")


def test_same_name_witness_rows_remain_separate_appearances():
    saved = page(witnesses=[{"name": "Alex Smith", "organization": "One"}, {"name": "Alex Smith", "organization": "Two"}])
    appearances = of_kind(adapt(saved), "appearance")
    assert len(appearances) == 2 and appearances[0].id != appearances[1].id
    assert {row.affiliation.organization_name for row in appearances} == {"One", "Two"}
    assert all(row.person is None for row in appearances)
    saved["events"] = ["12"]
    saved["witnesses"].reverse()
    reordered = of_kind(adapt(saved), "appearance")
    assert {row.affiliation.organization_name: row.id for row in appearances} == {row.affiliation.organization_name: row.id for row in reordered}


def test_nominee_role_uses_explicit_witness_position_without_changing_source_text():
    saved = page(title="Nomination hearing for Mark Cruz", witnesses=[
        {"name": "Mark Cruz", "position": "Nominee, Director of the Indian Health Service", "organization": "U.S. Department of Health and Human Services, Salem, Oregon"},
        {"name": "Introducing witness", "position": "Senator", "organization": "U.S. Senate"},
    ])
    rows = adapt(saved)
    nominee, introducer = of_kind(rows, "appearance")
    assert nominee.roles == ("witness", "nominee")
    assert nominee.affiliation.position == saved["witnesses"][0]["position"]
    assert introducer.roles == ("witness",)
    assert of_kind(rows, "source_record")[0].payload == saved
