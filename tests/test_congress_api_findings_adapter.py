"""Print matcher decisions surface unlink failures instead of silent skips."""

from datetime import UTC, datetime

from committee_meeting.common import Ref
from congress_api.adapters.common import AdapterContext
from congress_api.adapters.findings import print_links

NOW = datetime(2026, 9, 30, tzinfo=UTC)


def context():
    return AdapterContext(NOW, "print-input", "congress_api.inventory.prints",
                          lambda kind, key: kind + ":" + key)


def decision(**changes):
    row = {
        "event_id": "12", "package_id": "CHRG-118hhrg1", "rule": "package_event_id",
        "rule_version": "1", "basis": "derived",
    }
    row.update(changes)
    return row


def versions(package="CHRG-118hhrg1"):
    return {package: (Ref(kind="material", id="material-1"), Ref(kind="material_version", id="version-1"))}


def test_unique_print_decision_creates_transcript_link():
    meetings = {(118, "house", "12"): Ref(kind="meeting", id="meeting-12")}
    result = list(print_links([decision()], context(), meetings=meetings, versions=versions()))
    source, link = result
    assert source.payload["package_id"] == "CHRG-118hhrg1"
    assert link.kind == "material_link" and link.role == "transcript"
    assert link.subject.id == "meeting-12" and link.material.id == "material-1"
    assert link.provenance.method.name.endswith("package_event_id")


def test_ambiguous_event_yields_issue_without_link():
    meetings = {
        (118, "house", "12"): Ref(kind="meeting", id="older"),
        (119, "house", 12): Ref(kind="meeting", id="newer"),  # int event id still counts
    }
    result = list(print_links([decision()], context(), meetings=meetings, versions=versions()))
    assert [r.kind for r in result] == ["source_record", "data_issue"]
    issue = result[1]
    assert issue.category == "unlinked" and issue.subject.id == result[0].id
    assert "2 entries" in issue.explanation
    assert not any(r.kind == "material_link" for r in result)


def test_missing_version_yields_issue_without_link():
    meetings = {(118, "house", "12"): Ref(kind="meeting", id="meeting-12")}
    result = list(print_links([decision()], context(), meetings=meetings, versions={}))
    assert [r.kind for r in result] == ["source_record", "data_issue"]
    issue = result[1]
    assert issue.category == "unlinked" and "not present" in issue.summary
    assert not any(r.kind == "material_link" for r in result)
