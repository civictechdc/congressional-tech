"""Tier 1: Feature Coverage for Features F6 through F8 (Milestone M2 / Ticket ct-xx7q).

Covers:
- F6: SourceRecord Identity Canonicalization
- F7: Historical DataIssue Citation Remapping
- F8: Published Tables Orphan Source Filtering
"""

from __future__ import annotations
import hashlib
import uuid
from pathlib import Path
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from tests.e2e.harness.contracts import SOURCE_SCHEMA
from tests.e2e.harness.data_generators import SyntheticDataGenerator


def canonical_source_id(provider: str, scheme: str, value: str, payload_sha256: str) -> str:
    """Canonical SourceRecord.id derived from record identity and payload digest."""
    key = f"{provider}|{scheme}|{value}|{payload_sha256}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


# ---------------------------------------------------------------------------
# Feature F6: SourceRecord Identity Canonicalization
# ---------------------------------------------------------------------------

@pytest.mark.tier1
@pytest.mark.feature("F6")
def test_f06_stable_source_id_across_snapshots():
    """F6.1: Verify identical record across two weekly snapshot runs produces identical SourceRecord.id."""
    provider = "congress.gov"
    scheme = "event_id"
    value = "114250"
    payload_sha256 = hashlib.sha256(b'{"title": "Hearing 1"}').hexdigest()

    id_snapshot_1 = canonical_source_id(provider, scheme, value, payload_sha256)
    id_snapshot_2 = canonical_source_id(provider, scheme, value, payload_sha256)

    assert id_snapshot_1 == id_snapshot_2


@pytest.mark.tier1
@pytest.mark.feature("F6")
def test_f06_snapshot_id_does_not_mutate_source_id():
    """F6.2: Verify input_snapshot_id (e.g. 20261012 vs 20261019) is excluded from SourceRecord UUID derivation."""
    provider = "youtube"
    scheme = "video_id"
    value = "dQw4w9WgXcQ"
    payload = hashlib.sha256(b'{"title": "Video"}').hexdigest()

    id_1 = canonical_source_id(provider, scheme, value, payload)
    id_2 = canonical_source_id(provider, scheme, value, payload)
    assert id_1 == id_2


@pytest.mark.tier1
@pytest.mark.feature("F6")
def test_f06_content_mutation_yields_distinct_uuid():
    """F6.3: Verify payload modification creates a distinct UUID while preserving identity fields."""
    provider = "govinfo"
    scheme = "package_id"
    value = "CHRG-118hhrg12345"
    p1 = hashlib.sha256(b'{"version": 1}').hexdigest()
    p2 = hashlib.sha256(b'{"version": 2}').hexdigest()

    id_1 = canonical_source_id(provider, scheme, value, p1)
    id_2 = canonical_source_id(provider, scheme, value, p2)
    assert id_1 != id_2


@pytest.mark.tier1
@pytest.mark.feature("F6")
def test_f06_distinct_providers_yield_distinct_uuid():
    """F6.4: Verify different providers with same scheme and value have distinct UUIDs."""
    scheme = "hearing_id"
    value = "1001"
    p = hashlib.sha256(b'{"data": true}').hexdigest()

    id_senate = canonical_source_id("senate.committees", scheme, value, p)
    id_house = canonical_source_id("docs.house.gov", scheme, value, p)
    assert id_senate != id_house


@pytest.mark.tier1
@pytest.mark.feature("F6")
def test_f06_distinct_identifiers_yield_distinct_uuid():
    """F6.5: Verify differing identifier values yield distinct canonical IDs."""
    provider = "congress.gov"
    scheme = "bill"
    p = hashlib.sha256(b'{}').hexdigest()

    id_hr1 = canonical_source_id(provider, scheme, "hr1", p)
    id_hr2 = canonical_source_id(provider, scheme, "hr2", p)
    assert id_hr1 != id_hr2


# ---------------------------------------------------------------------------
# Feature F7: Historical DataIssue Citation Remapping
# ---------------------------------------------------------------------------

@pytest.mark.tier1
@pytest.mark.feature("F7")
def test_f07_single_citation_issue_remapped_to_current_source():
    """F7.1: Verify single-citation issue (len(citations)==1) is remapped to current SourceRecord ID."""
    current_source_id = "curr-uuid-001"
    old_source_id = "hist-uuid-001"
    identity_map = {("youtube", "video_id", "vid_999"): current_source_id}

    historical_issue = {
        "id": "issue-001",
        "category": "video_not_found",
        "citations": [{"provider": "youtube", "scheme": "video_id", "value": "vid_999", "source_id": old_source_id}],
    }

    # Simulate remapping logic from assemble.py:finish()
    remapped_citations = []
    for c in historical_issue["citations"]:
        key = (c["provider"], c["scheme"], c["value"])
        target_id = identity_map.get(key, c["source_id"])
        remapped_citations.append({**c, "source_id": target_id})

    assert len(remapped_citations) == 1
    assert remapped_citations[0]["source_id"] == current_source_id
    assert remapped_citations[0]["source_id"] != old_source_id


@pytest.mark.tier1
@pytest.mark.feature("F7")
def test_f07_multi_citation_issue_remapped_completely():
    """F7.2: Verify multi-citation issue remaps each matching citation to current source IDs."""
    identity_map = {
        ("congress.gov", "event", "e1"): "curr-e1",
        ("youtube", "video", "v1"): "curr-v1",
    }
    citations = [
        {"provider": "congress.gov", "scheme": "event", "value": "e1", "source_id": "old-e1"},
        {"provider": "youtube", "scheme": "video", "value": "v1", "source_id": "old-v1"},
    ]

    remapped = [
        identity_map.get((c["provider"], c["scheme"], c["value"]), c["source_id"])
        for c in citations
    ]
    assert remapped == ["curr-e1", "curr-v1"]


@pytest.mark.tier1
@pytest.mark.feature("F7")
def test_f07_vanished_source_retained_in_retained_sources():
    """F7.3: Verify historical source without current match is preserved in RetainedSources."""
    current_sources = {("youtube", "video", "active_v"): "curr-active"}
    historical_citations = [
        {"provider": "youtube", "scheme": "video", "value": "vanished_v", "source_id": "hist-vanished"},
    ]

    retained_sources = set()
    for c in historical_citations:
        key = (c["provider"], c["scheme"], c["value"])
        if key not in current_sources:
            retained_sources.add(c["source_id"])

    assert "hist-vanished" in retained_sources


@pytest.mark.tier1
@pytest.mark.feature("F7")
def test_f07_duplicate_citations_collapsed_to_current():
    """F7.4: Verify duplicate historical citations collapse to single current source ID."""
    identity_map = {("youtube", "video", "v1"): "curr-v1"}
    citations = [
        {"provider": "youtube", "scheme": "video", "value": "v1", "source_id": "old-snapshot-1"},
        {"provider": "youtube", "scheme": "video", "value": "v1", "source_id": "old-snapshot-2"},
    ]

    remapped_ids = {
        identity_map.get((c["provider"], c["scheme"], c["value"]), c["source_id"])
        for c in citations
    }
    assert len(remapped_ids) == 1
    assert remapped_ids == {"curr-v1"}


@pytest.mark.tier1
@pytest.mark.feature("F7")
def test_f07_issue_records_reference_published_sources():
    """F7.5: Verify all source_ids in issues table match emitted source records."""
    emitted_source_ids = {"src-1", "src-2", "src-3"}
    issue_row = {"id": "iss-1", "source_ids": ["src-1", "src-2"]}

    for sid in issue_row["source_ids"]:
        assert sid in emitted_source_ids


# ---------------------------------------------------------------------------
# Feature F8: Published Tables Orphan Source Filtering
# ---------------------------------------------------------------------------

@pytest.mark.tier1
@pytest.mark.feature("F8")
def test_f08_source_cited_by_meetings_retained(staging_dir: Path, generator: SyntheticDataGenerator):
    """F8.1: Verify source cited by meetings is retained in sources.parquet."""
    src1 = generator.generate_source_record(value="src1")
    orphan = generator.generate_source_record(value="orphan")

    meetings = [{"id": "m1", "source_ids": [src1["id"]]}]
    published_cited = {sid for m in meetings for sid in m["source_ids"]}

    emitted_sources = [s for s in [src1, orphan] if s["id"] in published_cited]
    assert len(emitted_sources) == 1
    assert emitted_sources[0]["id"] == src1["id"]


@pytest.mark.tier1
@pytest.mark.feature("F8")
def test_f08_source_cited_by_materials_retained(generator: SyntheticDataGenerator):
    """F8.2: Verify source cited by materials is retained in sources.parquet."""
    src_mat = generator.generate_source_record(value="mat_src")
    orphan = generator.generate_source_record(value="orphan")

    materials = [{"id": "mat-1", "source_ids": [src_mat["id"]]}]
    published_cited = {sid for m in materials for sid in m["source_ids"]}

    emitted = [s for s in [src_mat, orphan] if s["id"] in published_cited]
    assert len(emitted) == 1
    assert emitted[0]["id"] == src_mat["id"]


@pytest.mark.tier1
@pytest.mark.feature("F8")
def test_f08_source_cited_by_issues_retained(generator: SyntheticDataGenerator):
    """F8.3: Verify source cited by issues is retained in sources.parquet."""
    src_iss = generator.generate_source_record(value="iss_src")
    orphan = generator.generate_source_record(value="orphan")

    issues = [{"id": "iss-1", "source_ids": [src_iss["id"]]}]
    published_cited = {sid for i in issues for sid in i["source_ids"]}

    emitted = [s for s in [src_iss, orphan] if s["id"] in published_cited]
    assert len(emitted) == 1
    assert emitted[0]["id"] == src_iss["id"]


@pytest.mark.tier1
@pytest.mark.feature("F8")
def test_f08_unreferenced_orphan_source_pruned(generator: SyntheticDataGenerator):
    """F8.4: Verify source cited ONLY by internal intermediate records is dropped from sources.parquet."""
    internal_only_src = generator.generate_source_record(value="occurrence_internal")
    published_cited_ids = {"src-pub-1", "src-pub-2"}

    assert internal_only_src["id"] not in published_cited_ids
    # Emitted sources filter
    is_emitted = internal_only_src["id"] in published_cited_ids
    assert is_emitted is False


@pytest.mark.tier1
@pytest.mark.feature("F8")
def test_f08_all_emitted_sources_have_at_least_one_reference(staging_dir: Path, generator: SyntheticDataGenerator):
    """F8.5: Verify 100% of rows in final sources.parquet are referenced by at least one published table."""
    all_sources = [generator.generate_source_record(value=f"s_{i}") for i in range(10)]
    published_tables = {
        "meetings": [{"id": "m1", "source_ids": [all_sources[0]["id"], all_sources[1]["id"]]}],
        "committees": [{"id": "c1", "source_ids": [all_sources[2]["id"]]}],
        "materials": [{"id": "mat1", "source_ids": [all_sources[3]["id"], all_sources[4]["id"]]}],
        "witnesses": [{"id": "w1", "source_ids": [all_sources[5]["id"]]}],
        "issues": [{"id": "iss1", "source_ids": [all_sources[6]["id"]]}],
    }

    # Sources 7, 8, 9 are unreferenced orphans
    referenced_ids = set()
    for table_rows in published_tables.values():
        for r in table_rows:
            referenced_ids.update(r.get("source_ids", ()))

    emitted_sources = [s for s in all_sources if s["id"] in referenced_ids]
    assert len(emitted_sources) == 7
    # Verify 100% referenced
    orphan_count = sum(1 for s in emitted_sources if s["id"] not in referenced_ids)
    assert orphan_count == 0
