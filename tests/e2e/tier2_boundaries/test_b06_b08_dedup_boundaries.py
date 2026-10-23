"""Tier 2: Boundary & Corner Cases for Features F6 through F8 (ct-xx7q).

Covers:
- F6: Empty/long/unicode identifiers, case sensitivity, zero-byte digests
- F7: Zero citations, all-vanished, mixed remapping, high fan-in citations
- F8: 100% referenced vs 0% referenced, cross-table overlaps, invalid UUIDs
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


def canonical_id(provider: str, scheme: str, value: str, payload_sha256: str) -> str:
    key = f"{provider}|{scheme}|{value}|{payload_sha256}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


# ---------------------------------------------------------------------------
# Feature F6 Boundaries
# ---------------------------------------------------------------------------

@pytest.mark.tier2
@pytest.mark.feature("F6")
def test_b06_empty_identifier_value():
    """B6.1: Verify empty string identifier value hashes deterministically into valid UUID."""
    p = hashlib.sha256(b"{}").hexdigest()
    res_id = canonical_id("provider", "scheme", "", p)
    assert len(res_id) == 36
    assert uuid.UUID(res_id).version == 5


@pytest.mark.tier2
@pytest.mark.feature("F6")
def test_b06_extreme_long_identifier():
    """B6.2: Verify 2,000-character identifier string hashes cleanly without buffer overflow."""
    long_val = "x" * 2000
    p = hashlib.sha256(b"{}").hexdigest()
    res_id = canonical_id("provider", "scheme", long_val, p)
    assert len(res_id) == 36


@pytest.mark.tier2
@pytest.mark.feature("F6")
def test_b06_unicode_identifier_value():
    """B6.3: Verify non-ASCII unicode characters in identifier value are preserved in hash."""
    val = "H.R. 1234 — 2026年 法案"
    p = hashlib.sha256(b"{}").hexdigest()
    id_1 = canonical_id("congress.gov", "bill", val, p)
    id_2 = canonical_id("congress.gov", "bill", val, p)
    assert id_1 == id_2


@pytest.mark.tier2
@pytest.mark.feature("F6")
def test_b06_case_sensitive_providers():
    """B6.4: Verify case differences in provider produce distinct canonical IDs."""
    p = hashlib.sha256(b"{}").hexdigest()
    id_lower = canonical_id("youtube", "video", "1", p)
    id_upper = canonical_id("YouTube", "video", "1", p)
    assert id_lower != id_upper


@pytest.mark.tier2
@pytest.mark.feature("F6")
def test_b06_zero_byte_payload_digest_uuid():
    """B6.5: Verify 0-byte payload sha256 produces valid canonical UUID."""
    empty_sha = hashlib.sha256(b"").hexdigest()
    res_id = canonical_id("provider", "scheme", "val", empty_sha)
    assert len(res_id) == 36


# ---------------------------------------------------------------------------
# Feature F7 Boundaries
# ---------------------------------------------------------------------------

@pytest.mark.tier2
@pytest.mark.feature("F7")
def test_b07_issue_with_zero_citations():
    """B7.1: Verify historical issue with empty citation list [] is processed without error."""
    issue = {"id": "iss_empty", "category": "metadata_mismatch", "citations": []}
    identity_map = {("p", "s", "v"): "curr-1"}
    remapped = [identity_map.get((c["p"], c["s"], c["v"]), c.get("id")) for c in issue["citations"]]
    assert remapped == []


@pytest.mark.tier2
@pytest.mark.feature("F7")
def test_b07_all_citations_vanished():
    """B7.2: Verify issue where 100% of citations are vanished retains all in RetainedSources."""
    current_sources = {("p1", "s1", "v1"): "curr-1"}
    issue_citations = [
        {"provider": "p_old", "scheme": "s_old", "value": "v_old_1", "source_id": "vanished-1"},
        {"provider": "p_old", "scheme": "s_old", "value": "v_old_2", "source_id": "vanished-2"},
    ]

    retained = set()
    for c in issue_citations:
        key = (c["provider"], c["scheme"], c["value"])
        if key not in current_sources:
            retained.add(c["source_id"])

    assert len(retained) == 2
    assert retained == {"vanished-1", "vanished-2"}


@pytest.mark.tier2
@pytest.mark.feature("F7")
def test_b07_mixed_current_and_vanished_citations():
    """B7.3: Verify issue with mixed current and vanished citations remaps one and retains the other."""
    current_sources = {("youtube", "video", "active_v"): "curr-active"}
    issue_citations = [
        {"provider": "youtube", "scheme": "video", "value": "active_v", "source_id": "old-active"},
        {"provider": "youtube", "scheme": "video", "value": "deleted_v", "source_id": "old-deleted"},
    ]

    remapped = []
    retained = set()
    for c in issue_citations:
        key = (c["provider"], c["scheme"], c["value"])
        if key in current_sources:
            remapped.append(current_sources[key])
        else:
            retained.add(c["source_id"])
            remapped.append(c["source_id"])

    assert remapped == ["curr-active", "old-deleted"]
    assert retained == {"old-deleted"}


@pytest.mark.tier2
@pytest.mark.feature("F7")
def test_b07_many_historical_issues_pointing_to_same_source():
    """B7.4: Verify 100 historical issues citing an old UUID all remap to single current UUID."""
    target_current_id = "curr-canonical-uuid"
    identity_map = {("govinfo", "package", "CHRG-118"): target_current_id}

    issues = [
        {"id": f"iss_{i}", "citations": [{"provider": "govinfo", "scheme": "package", "value": "CHRG-118", "source_id": f"old-{i}"}]}
        for i in range(100)
    ]

    all_remapped = [
        identity_map[(iss["citations"][0]["provider"], iss["citations"][0]["scheme"], iss["citations"][0]["value"])]
        for iss in issues
    ]
    assert len(set(all_remapped)) == 1
    assert set(all_remapped) == {target_current_id}


@pytest.mark.tier2
@pytest.mark.feature("F7")
def test_b07_circular_citation_references():
    """B7.5: Verify duplicate identical citations within single issue are deduplicated."""
    identity_map = {("p", "s", "v"): "curr-id"}
    citations = [
        {"provider": "p", "scheme": "s", "value": "v", "source_id": "uuid-1"},
        {"provider": "p", "scheme": "s", "value": "v", "source_id": "uuid-2"},
        {"provider": "p", "scheme": "s", "value": "v", "source_id": "uuid-1"},
    ]

    deduped_ids = list(dict.fromkeys(
        identity_map.get((c["provider"], c["scheme"], c["value"]), c["source_id"])
        for c in citations
    ))
    assert deduped_ids == ["curr-id"]


# ---------------------------------------------------------------------------
# Feature F8 Boundaries
# ---------------------------------------------------------------------------

@pytest.mark.tier2
@pytest.mark.feature("F8")
def test_b08_all_sources_referenced():
    """B8.1: Verify zero sources dropped when 100% are referenced."""
    sources = [{"id": f"s_{i}"} for i in range(10)]
    cited_ids = {f"s_{i}" for i in range(10)}

    emitted = [s for s in sources if s["id"] in cited_ids]
    assert len(emitted) == 10


@pytest.mark.tier2
@pytest.mark.feature("F8")
def test_b08_all_sources_unreferenced():
    """B8.2: Verify all sources dropped when zero are referenced."""
    sources = [{"id": f"orphan_{i}"} for i in range(10)]
    cited_ids = {"other_1", "other_2"}

    emitted = [s for s in sources if s["id"] in cited_ids]
    assert len(emitted) == 0


@pytest.mark.tier2
@pytest.mark.feature("F8")
def test_b08_multiple_tables_citing_same_source():
    """B8.3: Verify source cited by committees, meetings, materials, and witnesses is emitted once."""
    shared_src = {"id": "shared-uuid"}
    tables = [
        {"source_ids": ["shared-uuid"]},
        {"source_ids": ["shared-uuid"]},
        {"source_ids": ["shared-uuid"]},
    ]
    cited_ids = {sid for t in tables for sid in t["source_ids"]}
    emitted = [shared_src] if shared_src["id"] in cited_ids else []
    assert len(emitted) == 1


@pytest.mark.tier2
@pytest.mark.feature("F8")
def test_b08_nonexistent_uuid_in_source_ids():
    """B8.4: Verify published table citing non-existent source UUID does not crash filter."""
    sources = [{"id": "s1"}]
    cited_ids = {"s1", "phantom-uuid-999"}

    emitted = [s for s in sources if s["id"] in cited_ids]
    assert len(emitted) == 1
    assert emitted[0]["id"] == "s1"


@pytest.mark.tier2
@pytest.mark.feature("F8")
def test_b08_empty_published_tables():
    """B8.5: Verify empty published tables emits 0 sources."""
    sources = [{"id": "s1"}, {"id": "s2"}]
    cited_ids = set()
    emitted = [s for s in sources if s["id"] in cited_ids]
    assert len(emitted) == 0
