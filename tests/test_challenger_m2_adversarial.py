"""Adversarial stress tests for Milestone 2 (ct-xx7q).

Testing:
1. SourceRecord.id stability across snapshots and sensitivity to payload changes
2. Citation remapping in Assembly._dedup_citations (single citation, multi citation, vanished, subject, resolution)
3. Orphan filtering in parquet.py write_tables and write_catalog
4. Identity hashing resilience
"""

import gzip
import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
import pyarrow.parquet as pq
import pytest

from congress_api.adapters.common import AdapterContext
from committee_explorer.assemble import (
    Assembly,
    _source_identity_hash,
    _SpilledSources,
)
from committee_explorer.parquet import write_tables, write_catalog
from committee_meeting.common import Identifier, Ref
from committee_meeting.issues import DataIssue, IssueResolution
from committee_meeting.materials import Material, MaterialVersion, DocumentDetails
from committee_meeting.meetings import Appearance, Meeting
from committee_meeting.provenance import Citation, Provenance, SourceRecord


NOW = datetime(2026, 10, 22, 12, 0, 0, tzinfo=UTC)


def _make_ids():
    allocated = {}
    def ids(kind, key):
        if (kind, key) not in allocated:
            allocated[(kind, key)] = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{kind}:{key}"))
        return allocated[(kind, key)]
    return ids


# -----------------------------------------------------------------------------
# 1. SourceRecord.id Stability & Canonicalization
# -----------------------------------------------------------------------------

def test_source_id_stability_across_different_snapshot_ids():
    """Verify that different input_snapshot_ids produce byte-for-byte identical SourceRecord.id."""
    ctx1 = AdapterContext(now=NOW, input_id="20261012", provider="congress.gov", ids=_make_ids())
    ctx2 = AdapterContext(now=NOW, input_id="20261019", provider="congress.gov", ids=_make_ids())

    payload = {"title": "Hearing on Prediction Markets", "event_id": 114250}
    src1 = ctx1.source(native_key=114250, payload=payload)
    src2 = ctx2.source(native_key=114250, payload=payload)

    assert src1.id == src2.id
    assert src1.identifier.scheme == "congress.gov:record"
    assert src1.identifier.value == "114250"
    assert src1.input_snapshot_id == "20261012"
    assert src2.input_snapshot_id == "20261019"


def test_source_id_changes_when_payload_changes():
    """Verify that any mutation to payload results in a distinct SourceRecord.id."""
    ctx = AdapterContext(now=NOW, input_id="20261019", provider="congress.gov", ids=_make_ids())
    src1 = ctx.source(native_key=114250, payload={"title": "Version 1"})
    src2 = ctx.source(native_key=114250, payload={"title": "Version 2"})

    assert src1.id != src2.id
    assert src1.identifier.value == src2.identifier.value


def test_source_id_distinct_for_different_providers_same_key():
    """Verify that distinct providers with identical native_key produce distinct SourceRecord.id."""
    ctx1 = AdapterContext(now=NOW, input_id="20261019", provider="senate.committees", ids=_make_ids())
    ctx2 = AdapterContext(now=NOW, input_id="20261019", provider="house.events", ids=_make_ids())

    payload = {"data": 1}
    src1 = ctx1.source(native_key=1001, payload=payload)
    src2 = ctx2.source(native_key=1001, payload=payload)

    assert src1.id != src2.id


# -----------------------------------------------------------------------------
# 2. Citation Remapping in assemble.py
# -----------------------------------------------------------------------------

def test_dedup_citations_single_citation_remapped():
    """Verify single-citation issues are remapped to current source ID."""
    assembly = Assembly(now=NOW)
    current_src = SourceRecord(
        id="curr-src-uuid",
        provider="youtube",
        identifier=Identifier(scheme="youtube:video", value="vid-123"),
        payload={"title": "Current Video"},
    )
    assembly.sources[("source_record", current_src.id)] = current_src

    # Historical previous observation with old source ID
    ident_hash = _source_identity_hash("youtube", "youtube:video", "vid-123")
    identity_cache = {"old-src-uuid": (ident_hash, "2026-10-12T00:00:00Z")}

    old_citation = Citation(
        source=Ref(kind="source_record", id="old-src-uuid"),
        selector_type="json_pointer",
        selector="/title",
    )

    remapped = assembly._dedup_citations(
        citations=(old_citation,),
        previous=None,
        identity_cache=identity_cache,
    )

    assert len(remapped) == 1
    assert remapped[0].source.id == "curr-src-uuid"
    assert remapped[0].source.id != "old-src-uuid"


def test_dedup_citations_vanished_source_not_remapped():
    """Verify vanished source without current match preserves its historical source ID."""
    assembly = Assembly(now=NOW)
    current_src = SourceRecord(
        id="curr-src-uuid",
        provider="youtube",
        identifier=Identifier(scheme="youtube:video", value="vid-DIFFERENT"),
        payload={"title": "Other Video"},
    )
    assembly.sources[("source_record", current_src.id)] = current_src

    ident_hash = _source_identity_hash("youtube", "youtube:video", "vid-VANISHED")
    identity_cache = {"vanished-src-uuid": (ident_hash, "2026-10-12T00:00:00Z")}

    old_citation = Citation(
        source=Ref(kind="source_record", id="vanished-src-uuid"),
        selector_type="json_pointer",
        selector="/title",
    )

    remapped = assembly._dedup_citations(
        citations=(old_citation,),
        previous=None,
        identity_cache=identity_cache,
    )

    assert len(remapped) == 1
    assert remapped[0].source.id == "vanished-src-uuid"


def test_dedup_citations_current_replaces_historical_for_same_selector():
    """Verify current citation supersedes historical citation for same source identity and selector."""
    assembly = Assembly(now=NOW)
    current_src = SourceRecord(
        id="curr-src-uuid",
        provider="youtube",
        identifier=Identifier(scheme="youtube:video", value="vid-123"),
        payload={"title": "Updated Video"},
    )
    assembly.sources[("source_record", current_src.id)] = current_src

    ident_hash = _source_identity_hash("youtube", "youtube:video", "vid-123")
    identity_cache = {"old-src-uuid": (ident_hash, "2026-10-12T00:00:00Z")}

    old_cit = Citation(
        source=Ref(kind="source_record", id="old-src-uuid"),
        selector_type="json_pointer",
        selector="/title",
        quote="Old Quote",
    )
    new_cit = Citation(
        source=Ref(kind="source_record", id="curr-src-uuid"),
        selector_type="json_pointer",
        selector="/title",
        quote="Old Quote",
    )

    merged = assembly._dedup_citations(
        citations=(old_cit, new_cit),
        previous=None,
        identity_cache=identity_cache,
    )

    assert len(merged) == 1
    assert merged[0].source.id == "curr-src-uuid"


def test_finish_remaps_data_issue_subject_and_resolution():
    """Verify finish() remaps subject and resolution citations when subject is a source_record."""
    # First generation
    assembly1 = Assembly(now=NOW)
    src1 = SourceRecord(
        id="src-v1",
        provider="youtube",
        identifier=Identifier(scheme="youtube:video", value="v1"),
        payload={"v": 1},
    )
    issue1 = DataIssue(
        id="issue-001",
        subject=Ref(kind="source_record", id="src-v1"),
        category="unverified",
        status="resolved",
        summary="Missing field",
        detected_at=NOW,
        provenance=Provenance(citations=(Citation(source=Ref(kind="source_record", id="src-v1")),), basis="reported"),
        resolution=IssueResolution(
            decided_at=NOW,
            explanation="Manual fix",
            provenance=Provenance(citations=(Citation(source=Ref(kind="source_record", id="src-v1")),), basis="reported"),
        ),
    )
    assembly1.add([src1, issue1])
    cat1 = assembly1.finish()

    # Second generation with updated source (different UUID, same identity)
    prev_map = {("source_record", "src-v1"): src1, ("data_issue", "issue-001"): issue1}
    assembly2 = Assembly(previous=prev_map, now=NOW)
    src2 = SourceRecord(
        id="src-v2",
        provider="youtube",
        identifier=Identifier(scheme="youtube:video", value="v1"),
        payload={"v": 2},
    )
    assembly2.sources[("source_record", src2.id)] = src2
    cat2 = assembly2.finish()

    issue2 = next(r for r in cat2.records if r.kind == "data_issue")
    assert issue2.subject.id == "src-v2"
    assert issue2.provenance.citations[0].source.id == "src-v2"
    assert issue2.resolution.provenance.citations[0].source.id == "src-v2"
    # Old source should NOT be retained
    assert "src-v1" not in [s.id for s in assembly2.retained.records()]


# -----------------------------------------------------------------------------
# 3. Orphan Filtering in parquet.py
# -----------------------------------------------------------------------------

def test_parquet_orphan_filtering_active_vs_inactive(tmp_path):
    """Verify write_tables orphan filtering drops unreferenced sources when filter_orphans=True."""
    s_cited_meeting = {"id": "src-meeting", "kind": "source_record", "provider": "p1", "payload": {"p": 1}}
    s_cited_mat = {"id": "src-mat", "kind": "source_record", "provider": "p2", "payload": {"p": 2}}
    s_cited_witness = {"id": "src-wit", "kind": "source_record", "provider": "p3", "payload": {"p": 3}}
    s_cited_issue = {"id": "src-iss", "kind": "source_record", "provider": "p4", "payload": {"p": 4}}
    s_orphan_1 = {"id": "src-orphan-1", "kind": "source_record", "provider": "p5", "payload": {"p": 5}}
    s_orphan_2 = {"id": "src-orphan-2", "kind": "source_record", "provider": "p6", "payload": {"p": 6}}

    all_sources = sorted(
        [s_cited_meeting, s_cited_mat, s_cited_witness, s_cited_issue, s_orphan_1, s_orphan_2],
        key=lambda s: s["id"]
    )

    query_rows = [
        {"kind": "meeting", "id": "m1", "title": "M1"},
        {"kind": "material", "id": "mat1", "title": "Mat1"},
        {"kind": "appearance", "id": "w1", "title": "W1"},
        {"kind": "data_issue", "id": "iss1", "title": "Iss1", "subject": {"kind": "meeting", "id": "m1"}},
    ]

    records = [
        {"kind": "meeting", "id": "m1", "title": "M1", "provenance": {"citations": [{"source": {"id": "src-meeting"}}]}},
        {"kind": "material", "id": "mat1", "title": "Mat1", "provenance": {"citations": [{"source": {"id": "src-mat"}}]}},
        {"kind": "appearance", "id": "w1", "title": "W1", "provenance": {"citations": [{"source": {"id": "src-wit"}}]}},
        {"kind": "data_issue", "id": "iss1", "title": "Iss1", "subject": {"kind": "meeting", "id": "m1"}, "provenance": {"citations": [{"source": {"id": "src-iss"}}]}},
    ]

    # Run with filter_orphans=True
    stage_filtered = tmp_path / "filtered"
    stage_filtered.mkdir()
    write_tables(
        records=records,
        sources=all_sources,
        query_rows=query_rows,
        stage=stage_filtered,
        descriptor=lambda *a, **k: None,
        filter_orphans=True,
    )
    published_filtered = pq.read_table(stage_filtered / "sources.parquet").to_pylist()
    published_f_ids = {r["id"] for r in published_filtered}

    assert published_f_ids == {"src-meeting", "src-mat", "src-wit", "src-iss"}
    assert "src-orphan-1" not in published_f_ids
    assert "src-orphan-2" not in published_f_ids

    # Run with filter_orphans=False
    stage_unfiltered = tmp_path / "unfiltered"
    stage_unfiltered.mkdir()
    write_tables(
        records=records,
        sources=all_sources,
        query_rows=[dict(q) for q in query_rows],
        stage=stage_unfiltered,
        descriptor=lambda *a, **k: None,
        filter_orphans=False,
    )
    published_unfiltered = pq.read_table(stage_unfiltered / "sources.parquet").to_pylist()
    published_unf_ids = {r["id"] for r in published_unfiltered}

    assert published_unf_ids == {"src-meeting", "src-mat", "src-wit", "src-iss", "src-orphan-1", "src-orphan-2"}


def test_parquet_orphan_filtering_bypassed_when_no_published_tables(tmp_path):
    """Verify that when published tables are empty, sources are not erroneously dropped."""
    all_sources = [
        {"id": f"src-{i:03d}", "kind": "source_record", "provider": "test", "payload": {"i": i}}
        for i in range(5)
    ]
    stage = tmp_path / "no_tables"
    stage.mkdir()
    write_tables(
        records=(),
        sources=all_sources,
        query_rows=(),
        stage=stage,
        descriptor=lambda *a, **k: None,
        filter_orphans=True,
    )
    published = pq.read_table(stage / "sources.parquet").to_pylist()
    assert len(published) == 5
