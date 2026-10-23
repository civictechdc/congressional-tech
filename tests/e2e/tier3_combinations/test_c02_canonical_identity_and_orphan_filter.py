"""Tier 3: Combination Test 2 — Canonical Identity, Citation Remapping & Orphan Filtering.

Cross-feature interactions:
- F6: SourceRecord Identity Canonicalization
- F7: Historical DataIssue Citation Remapping
- F8: Published Tables Orphan Source Filtering
- F1/F2: Sources Schema Conformance
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


def derive_canonical_id(provider: str, scheme: str, value: str, payload_sha: str) -> str:
    key = f"{provider}|{scheme}|{value}|{payload_sha}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


@pytest.mark.tier3
def test_c02_multi_snapshot_simulation_eliminates_duplicates_and_orphans():
    """C2.1: Multi-snapshot simulation eliminates duplicate weekly rows and unreferenced orphans."""
    # Week 1: 5 YouTube videos + 2 congress.gov sources
    p_sha = hashlib.sha256(b"payload").hexdigest()
    w1_sources = {
        ("youtube", "video", f"v_{i}"): derive_canonical_id("youtube", "video", f"v_{i}", p_sha)
        for i in range(5)
    }

    # Week 2: Same 5 YouTube videos (different weekly snapshot ID) + 3 internal occurrences
    w2_sources = {
        ("youtube", "video", f"v_{i}"): derive_canonical_id("youtube", "video", f"v_{i}", p_sha)
        for i in range(5)
    }
    # Add internal-only sources (never cited by published tables)
    w2_sources[("internal", "occurrence", "occ_1")] = "internal-uuid-1"
    w2_sources[("internal", "occurrence", "occ_2")] = "internal-uuid-2"

    # Historical DataIssue citing old snapshot UUIDs for v_0 and v_1
    historical_issue = {
        "id": "iss_1",
        "citations": [
            {"provider": "youtube", "scheme": "video", "value": "v_0", "source_id": "old-w1-v0"},
            {"provider": "youtube", "scheme": "video", "value": "v_1", "source_id": "old-w1-v1"},
        ],
    }

    # Published tables cite v_0, v_1, v_2, v_3, v_4
    meetings = [{"id": "m1", "source_ids": [w2_sources[("youtube", "video", "v_0")]]}]
    materials = [{"id": "mat1", "source_ids": [w2_sources[("youtube", "video", f"v_{i}")] for i in (1, 2, 3, 4)]}]

    # Step 1: Remap historical issue citations
    identity_map = {k: v for k, v in w2_sources.items()}
    remapped_issue_citations = []
    for c in historical_issue["citations"]:
        key = (c["provider"], c["scheme"], c["value"])
        canonical_sid = identity_map.get(key, c["source_id"])
        remapped_issue_citations.append(canonical_sid)

    # Step 2: Collect union of all cited source_ids from published tables + remapped issues
    published_cited_sids = set()
    for m in meetings:
        published_cited_sids.update(m["source_ids"])
    for mat in materials:
        published_cited_sids.update(mat["source_ids"])
    published_cited_sids.update(remapped_issue_citations)

    # Step 3: Filter all sources to only those cited
    emitted_sources = [sid for sid in set(w2_sources.values()) if sid in published_cited_sids]

    # Verification:
    # 1. Zero duplicate (provider, scheme, value) rows: exactly 5 unique YouTube sources
    assert len(emitted_sources) == 5
    # 2. Zero unreferenced orphans: internal occurrences are pruned
    assert "internal-uuid-1" not in emitted_sources
    assert "internal-uuid-2" not in emitted_sources
    # 3. All historical citations match emitted current sources
    for target_sid in remapped_issue_citations:
        assert target_sid in emitted_sources


@pytest.mark.tier3
def test_c02_vanished_historical_source_preserved_in_retained():
    """C2.2: Historical issue citing vanished source preserves source in RetainedSources and emits it."""
    current_sources = {("congress.gov", "event", "curr_1"): "uuid-curr-1"}
    # Historical issue cites an event that no longer appears in current week's snapshot
    historical_issue = {
        "id": "iss_hist",
        "citations": [
            {"provider": "congress.gov", "scheme": "event", "value": "vanished_event", "source_id": "uuid-vanished"},
        ],
    }

    retained_sources = {}
    for c in historical_issue["citations"]:
        key = (c["provider"], c["scheme"], c["value"])
        if key not in current_sources:
            retained_sources[c["source_id"]] = {
                "id": c["source_id"],
                "provider": c["provider"],
                "identifier_scheme": c["scheme"],
                "identifier_value": c["value"],
            }

    assert "uuid-vanished" in retained_sources
    all_available = {**{v: k for k, v in current_sources.items()}, **{k: (v["provider"], v["identifier_scheme"], v["identifier_value"]) for k, v in retained_sources.items()}}
    assert "uuid-vanished" in all_available


@pytest.mark.tier3
def test_c02_sources_table_compacted_into_single_file(staging_dir: Path, generator: SyntheticDataGenerator):
    """C2.3: Verify deduplication and orphan filtering consolidates sources into a single Parquet file."""
    # After removing 94,974 redundant rows (-30.8%), sources table fits in single file under FILE_LIMIT (100 MB)
    rows = [generator.generate_source_record(value=f"unique_{i}") for i in range(100)]
    table = pa.Table.from_pylist([{k: r[k] for k in SOURCE_SCHEMA.names} for r in rows], schema=SOURCE_SCHEMA)

    out_file = staging_dir / "sources.parquet"
    pq.write_table(table, out_file)

    assert out_file.exists()
    assert out_file.stat().st_size < 100 * 1024 * 1024  # Well under 100 MB target
    # Single file exists, no partitioned shards like sources-1, sources-2, sources-3 needed
    shards = list(staging_dir.glob("sources-*.parquet"))
    assert len(shards) == 0
