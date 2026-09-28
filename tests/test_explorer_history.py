"""Issue history keeps evidence without reloading every old domain record."""
from collections import ChainMap
from datetime import UTC, datetime
import tracemalloc

import pytest

from committee_explorer.assemble import Assembly
from committee_explorer import history
from committee_meeting.common import Identifier, Ref
from committee_meeting.issues import DataIssue, IssueResolution
from committee_meeting.materials import DocumentDetails, Material, MaterialVersion, Representation
from committee_meeting.provenance import AlternativeValue, Citation, FieldEvidence, Provenance, SourceRecord


NOW = datetime(2026, 9, 27, tzinfo=UTC)


def observation(identifier="source"):
    source = SourceRecord(id=identifier, provider="fixture", identifier=Identifier(scheme="fixture", value=identifier), payload={"value": identifier})
    provenance = Provenance(basis="reported", citations=(Citation(source=Ref(kind="source_record", id=identifier)),))
    return source, provenance


def snapshot():
    source, provenance = observation()
    material = Material(id="material", title="Retained text", details=DocumentDetails(category="transcript"), provenance=provenance)
    version = MaterialVersion(id="version", material=Ref(kind="material", id="material"), provenance=provenance)
    representation = Representation(id="representation", version=Ref(kind="material_version", id="version"), provenance=provenance)
    issue = DataIssue(id="issue", subject=Ref(kind="representation", id="representation"), category="unverified", summary="File needs a check", detected_at=NOW, provenance=provenance)
    unrelated = Material(id="unrelated", details=DocumentDetails(), provenance=provenance)
    assembly = Assembly()
    assembly.add([source, material, version, representation, issue, unrelated])
    return assembly


def test_snapshot_keeps_only_issues_and_transitive_evidence(tmp_path):
    assembly = snapshot()
    history.save_history(tmp_path, "first", ChainMap(assembly.records, assembly.sources))
    with history.load_history(tmp_path, "first") as previous:
        assert len(previous) == 5 and ("material", "unrelated") not in previous
        assert {key[0] for key in previous} == {"source_record", "material", "material_version", "representation", "data_issue"}
        assert previous[("data_issue", "issue")].detected_at == NOW
        assert [record.id for record in previous.iter_issues()] == ["issue"]


def test_loading_history_does_not_eagerly_decode_records(tmp_path, monkeypatch):
    assembly = snapshot()
    history.save_history(tmp_path, "first", ChainMap(assembly.records, assembly.sources))
    original, decoded = history._decode, []
    def decode(payload):
        decoded.append(len(payload))
        return original(payload)
    monkeypatch.setattr(history, "_decode", decode)
    with history.load_history(tmp_path, "first") as previous:
        assert len(previous) == 5 and ("data_issue", "issue") in previous
        assert decoded == []
        previous[("data_issue", "issue")]
        assert len(decoded) == 1
        previous[("data_issue", "issue")]
        assert len(decoded) == 2  # No hidden whole-history cache.


def test_absent_issue_keeps_entire_graph_without_becoming_current(tmp_path):
    first = snapshot()
    history.save_history(tmp_path, "first", ChainMap(first.records, first.sources))
    with history.load_history(tmp_path, "first") as previous:
        current = Assembly(previous)
        catalog = current.finish()
    assert len(catalog.records) == 4 and len(catalog.sources) == 1
    assert current.current == set()
    issue = next(record for record in catalog.records if record.kind == "data_issue")
    assert issue.status == "open" and issue.detected_at == NOW


def test_recurring_issue_keeps_first_detection_and_both_source_observations(tmp_path):
    first = snapshot()
    history.save_history(tmp_path, "first", ChainMap(first.records, first.sources))
    new_source, provenance = observation("new-source")
    repeated = first.records[("data_issue", "issue")].model_copy(update={"detected_at": NOW.replace(day=28), "provenance": provenance})
    with history.load_history(tmp_path, "first") as previous:
        assembly = Assembly(previous)
        assembly.add([new_source, repeated])
        catalog = assembly.finish()
    issue = next(record for record in catalog.records if record.kind == "data_issue")
    assert issue.detected_at == NOW
    assert {citation.source.id for citation in issue.provenance.citations} == {"source", "new-source"}
    assert {source.id for source in catalog.sources} == {"source", "new-source"}


def test_closed_issue_stays_closed_when_absent_and_reopens_on_new_finding(tmp_path):
    first = snapshot()
    issue = first.records[("data_issue", "issue")]
    closed = issue.model_copy(update={"status": "dismissed", "resolution": IssueResolution(decided_at=NOW, explanation="Reviewed", provenance=issue.provenance)})
    first.add([closed])
    history.save_history(tmp_path, "first", ChainMap(first.records, first.sources))
    with history.load_history(tmp_path, "first") as previous:
        absent = Assembly(previous).finish()
        assert next(row for row in absent.records if row.kind == "data_issue").status == "dismissed"
        recurring = Assembly(previous)
        recurring.add([issue.model_copy(update={"detected_at": NOW.replace(day=28)})])
        reopened = next(row for row in recurring.finish().records if row.kind == "data_issue")
        assert reopened.status == "open" and reopened.resolution is None and reopened.detected_at == NOW


def label_conflict_snapshot(alternative="Reported edition; revision not established"):
    assembly = snapshot()
    source, provenance = observation("alternative-source")
    version = assembly.records[("material_version", "version")]
    version = version.model_copy(update={
        "label": "Reported recording; revision not established",
        "field_evidence": (FieldEvidence(path="/label", selected=version.provenance,
            alternatives=(AlternativeValue(value=alternative, provenance=provenance),),
            selection_reason="Later collector wins."),),
    })
    issue = assembly.records[("data_issue", "issue")].model_copy(update={
        "subject": Ref(kind="material_version", id="version"), "category": "conflicting",
        "field_path": "/label", "summary": "Sources disagree about label",
    })
    assembly.sources[(source.kind, source.id)] = source
    assembly.records[(version.kind, version.id)] = version
    assembly.records[(issue.kind, issue.id)] = issue
    return assembly


@pytest.mark.parametrize("alternative", ["Reported edition; revision not established", "Reported edition; revision not established."])
def test_rebuilt_version_does_not_revive_collector_label_conflict(tmp_path, alternative):
    first = label_conflict_snapshot(alternative)
    history.save_history(tmp_path, "first", ChainMap(first.records, first.sources))
    current_version = first.records[("material_version", "version")].model_copy(update={"label": None, "field_evidence": ()})
    with history.load_history(tmp_path, "first") as previous:
        assembly = Assembly(previous, now=NOW.replace(day=28))
        assembly.add([current_version])
        catalog = assembly.finish()
    issue = next(row for row in catalog.records if row.kind == "data_issue")
    assert issue.status == "dismissed"
    assert issue.id == "issue" and issue.detected_at == NOW
    assert issue.resolution.decided_at == NOW.replace(day=28)
    assert "Reported recording; revision not established" in issue.resolution.explanation
    assert "Reported edition; revision not established" in issue.resolution.explanation
    assert {citation.source.id for citation in issue.resolution.provenance.citations} == {"source", "alternative-source"}
    assert assembly.records[("material_version", "version")] == current_version
    # The decision must survive a second full build after the old field values
    # have left the current version and its retained history.
    history.save_history(tmp_path, "second", ChainMap(assembly.records, assembly.sources))
    with history.load_history(tmp_path, "second") as previous:
        next_assembly = Assembly(previous, now=NOW.replace(day=29))
        next_assembly.add([current_version])
        next_issue = next(row for row in next_assembly.finish().records if row.kind == "data_issue")
    assert next_issue == issue


@pytest.mark.parametrize("alternative", ["Revised edition", None, {"label": "Reported edition; revision not established"}])
def test_source_label_conflicts_are_never_dismissed_as_collector_defaults(tmp_path, alternative):
    first = label_conflict_snapshot(alternative)
    history.save_history(tmp_path, "first", ChainMap(first.records, first.sources))
    with history.load_history(tmp_path, "first") as previous:
        assembly = Assembly(previous, now=NOW.replace(day=28))
        current_version = first.records[("material_version", "version")].model_copy(update={"label": None, "field_evidence": ()})
        assembly.add([current_version])
        issue = next(row for row in assembly.finish().records if row.kind == "data_issue")
    assert issue.status == "open" and issue.resolution is None


@pytest.mark.parametrize("status", ["resolved", "dismissed"])
def test_collector_cleanup_preserves_manual_resolution(tmp_path, status):
    first = label_conflict_snapshot()
    old_issue = first.records[("data_issue", "issue")]
    resolution = IssueResolution(decided_at=NOW, explanation="Manual review", provenance=old_issue.provenance)
    old_issue = old_issue.model_copy(update={"status": status, "resolution": resolution})
    first.records[("data_issue", "issue")] = old_issue
    history.save_history(tmp_path, "first", ChainMap(first.records, first.sources))
    with history.load_history(tmp_path, "first") as previous:
        issue = next(row for row in Assembly(previous, now=NOW.replace(day=28)).finish().records if row.kind == "data_issue")
    assert issue == old_issue


@pytest.mark.parametrize("generate_issue", [False, True])
def test_current_label_disagreement_is_not_dismissed_using_old_defaults(tmp_path, generate_issue):
    first = label_conflict_snapshot()
    history.save_history(tmp_path, "first", ChainMap(first.records, first.sources))
    current_version = first.records[("material_version", "version")].model_copy(update={"label": "Revised edition"})
    with history.load_history(tmp_path, "first") as previous:
        assembly = Assembly(previous, ids=(lambda *_: "issue") if generate_issue else None, now=NOW.replace(day=28))
        assembly.add([current_version])
        issue = next(row for row in assembly.finish().records if row.kind == "data_issue")
    assert issue.status == "open" and issue.resolution is None and issue.detected_at == NOW
    assert assembly.records[("material_version", "version")] == current_version


def test_incomplete_or_conflicting_save_cannot_replace_previous_snapshot(tmp_path):
    first = snapshot()
    path = history.save_history(tmp_path, "first", ChainMap(first.records, first.sources))
    original = path.read_bytes()
    assert history.save_history(tmp_path, "first", ChainMap(first.records, first.sources)) == path
    with pytest.raises(ValueError, match="missing"):
        history.save_history(tmp_path, "broken", first.records)
    assert history.load_history(tmp_path, "broken") is None
    issue = first.records[("data_issue", "issue")]
    first.add([issue.model_copy(update={"summary": "Changed issue"})])
    with pytest.raises(ValueError, match="immutable"):
        history.save_history(tmp_path, "first", ChainMap(first.records, first.sources))
    assert path.read_bytes() == original
    assert not list((tmp_path / "issue-history").glob(".*.sqlite"))


def test_migration_streams_old_partitions_with_bounded_python_memory(tmp_path):
    first = snapshot()
    def rows():
        # A 16 MB irrelevant population is generated, never retained in a list.
        for index in range(4000):
            source, _ = observation(f"unused-{index}")
            yield source.model_copy(update={"payload": {"text": "x" * 4096}}).model_dump(mode="json")
        for record in (*first.sources.values(), *first.records.values()):
            yield record.model_dump(mode="json")
    tracemalloc.start()
    try:
        history.migrate_history(tmp_path, "migrated", rows())
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 4 * 1024 * 1024
    with history.load_history(tmp_path, "migrated") as retained:
        assert len(retained) == 5
    assert not list((tmp_path / "issue-history").glob(".migration-*"))


def test_history_rejects_path_escape_and_incompatible_schema(tmp_path):
    with pytest.raises(ValueError, match="publication ID"):
        history.load_history(tmp_path, "../escape")
    first = snapshot()
    path = history.save_history(tmp_path, "first", ChainMap(first.records, first.sources))
    import sqlite3
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE metadata SET value='unknown' WHERE key='schema_version'")
    with pytest.raises(ValueError, match="schema"):
        history.load_history(tmp_path, "first")
