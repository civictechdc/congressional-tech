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
from committee_meeting.provenance import Citation, Provenance, SourceRecord


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
