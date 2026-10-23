"""Adversarial stress-testing suite for Milestone 3 (Ticket ct-q29c).

Authored by Reviewer/Critic for M3.
Empirically stress-tests:
1. Exact 256 KiB cell size boundary (262,144 bytes allowed, 262,145 bytes rejected).
2. Primary key and merge order_by integrity rejection (None, empty string, whitespace).
3. Zero-copy buffer hashing in _operation_id (determinism, sensitivity, no pq.write_table).
4. Local R2 CAS path formatting and gzip/pdf differentiation.
5. All 10 dataset schemas and typed Arrow normalization.
6. Detail deduplication across committees.
7. Edge-case and fallback logic across all 5 row builders.
"""

from __future__ import annotations
import gzip
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest.mock as mock

import pyarrow as pa
import pytest

from congress_api.retention.weekly_tables import (
    WEEKLY_TABLE_KEYS,
    WEEKLY_TABLE_MERGES,
    WEEKLY_TABLE_SCHEMAS,
    WeeklyRetentionTables,
    build_arrow_table,
    caption_to_row,
    committee_to_row,
    gpo_hearing_to_row,
    gpo_observation_to_row,
    house_event_to_row,
    meeting_to_row,
    merge_row_with_policy,
    rejected_page_to_row,
    senate_event_to_row,
    stage_body_bytes,
    transcript_to_row,
    youtube_video_to_row,
)
from congress_api.cli.sync_weekly_tables import _iter_inventory_rows


# ===========================================================================
# 1. Stress Test: 256 KiB Boundary (262,144 vs 262,145 bytes)
# ===========================================================================

def test_cell_size_boundary_exact_limit():
    """Verify exact 256 KiB (262,144 bytes) cell is accepted, and 262,145 is rejected."""
    # 262,144 bytes: exactly 256 KiB
    valid_text = "A" * 262_144
    rows_valid = [{
        "system_code": "hsju00",
        "video_id": "vid01",
        "published_at": "2026-10-01T00:00:00Z",
        "title": valid_text,
        "upstream_sha256": None,
    }]
    table = build_arrow_table("youtube_videos", rows_valid)
    assert table.num_rows == 1

    # 262,145 bytes: 256 KiB + 1 byte
    invalid_text = "A" * 262_145
    rows_invalid = [{
        "system_code": "hsju00",
        "video_id": "vid01",
        "published_at": "2026-10-01T00:00:00Z",
        "title": invalid_text,
        "upstream_sha256": None,
    }]
    with pytest.raises(ValueError, match="exceeds 256 KiB cell limit"):
        build_arrow_table("youtube_videos", rows_invalid)


def test_cell_size_all_nulls_handled_safely():
    """Verify that columns containing only nulls do not raise ValueError."""
    rows = [{
        "system_code": "hsju00",
        "video_id": "vid01",
        "published_at": "2026-10-01T00:00:00Z",
        "title": None,
        "upstream_sha256": None,
    }]
    table = build_arrow_table("youtube_videos", rows)
    assert table.num_rows == 1
    assert table.column("title")[0].as_py() is None


# ===========================================================================
# 2. Stress Test: Integrity Rejection for Primary Keys and Order_By
# ===========================================================================

@pytest.mark.parametrize("bad_key", [None, "", "   ", "\t\n"])
def test_build_arrow_table_rejects_empty_or_null_primary_keys(bad_key):
    """Verify build_arrow_table rejects null or empty/whitespace primary keys."""
    rows = [{
        "system_code": "hsju00",
        "video_id": bad_key,
        "published_at": "2026-10-01T00:00:00Z",
        "title": "Title",
        "upstream_sha256": None,
    }]
    with pytest.raises(ValueError, match="primary key column 'video_id' cannot be empty or null"):
        build_arrow_table("youtube_videos", rows)


@pytest.mark.parametrize("bad_val", [None, "", "   "])
def test_upsert_batch_rejects_empty_or_null_keys_and_order_by(tmp_path: Path, bad_val):
    """Verify _upsert_batch enforces non-null/non-empty PK and order_by."""
    with WeeklyRetentionTables(tmp_path) as wt:
        # Invalid primary key
        with pytest.raises(ValueError, match="primary key column 'event_id' cannot be empty or null"):
            wt._upsert_batch("house_events", [{
                "event_id": bad_val,
                "merge_timestamp": "2026-10-01T00:00:00Z",
                "witness_status": None,
                "seed": None,
                "source_body_sha256": None,
            }])

        # Invalid order_by
        with pytest.raises(ValueError, match="merge order_by column 'merge_timestamp' cannot be null or empty"):
            wt._upsert_batch("house_events", [{
                "event_id": "ev123",
                "merge_timestamp": bad_val,
                "witness_status": None,
                "seed": None,
                "source_body_sha256": None,
            }])


# ===========================================================================
# 3. Stress Test: Zero-Copy Fast Digest in _operation_id
# ===========================================================================

def test_operation_id_does_not_call_write_table(tmp_path: Path):
    """Verify _operation_id does not call pyarrow.parquet.write_table."""
    with WeeklyRetentionTables(tmp_path) as wt:
        table = build_arrow_table("house_events", [{
            "event_id": "ev1",
            "merge_timestamp": "2026-10-01T00:00:00Z",
            "witness_status": None,
            "seed": None,
            "source_body_sha256": None,
        }])
        with mock.patch("pyarrow.parquet.write_table") as mock_write:
            op_id = wt._operation_id("house_events", "test", table)
            assert mock_write.call_count == 0
            assert op_id.startswith("test-house_events-")
            assert len(op_id) <= 64


def test_operation_id_determinism_and_sensitivity(tmp_path: Path):
    """Verify _operation_id is deterministic and sensitive to single-cell mutations."""
    with WeeklyRetentionTables(tmp_path) as wt:
        t1 = build_arrow_table("house_events", [{
            "event_id": "ev1",
            "merge_timestamp": "2026-10-01T00:00:00Z",
            "witness_status": "present",
            "seed": None,
            "source_body_sha256": None,
        }])
        t2 = build_arrow_table("house_events", [{
            "event_id": "ev1",
            "merge_timestamp": "2026-10-01T00:00:00Z",
            "witness_status": "present",
            "seed": None,
            "source_body_sha256": None,
        }])
        t3 = build_arrow_table("house_events", [{
            "event_id": "ev1",
            "merge_timestamp": "2026-10-01T00:00:00Z",
            "witness_status": "absent",  # mutated cell
            "seed": None,
            "source_body_sha256": None,
        }])

        op1 = wt._operation_id("house_events", "sync", t1)
        op2 = wt._operation_id("house_events", "sync", t2)
        op3 = wt._operation_id("house_events", "sync", t3)

        assert op1 == op2, "Identical tables must produce identical operation_id"
        assert op1 != op3, "Different cell value must produce different operation_id"


# ===========================================================================
# 4. Stress Test: Local R2 CAS Path Layout & PDF vs GZ
# ===========================================================================

def test_stage_body_bytes_pdf_vs_gzip(tmp_path: Path):
    """Verify stage_body_bytes correctly differentiates PDF from non-PDF."""
    staging_dir = tmp_path / "cas"

    # Non-PDF payload -> .gz
    json_bytes = b'{"hello": "world"}'
    digest_gz, rel_key_gz = stage_body_bytes(json_bytes, staging_dir)
    assert rel_key_gz == f"bodies/sha256/{digest_gz[:2]}/{digest_gz}.gz"
    full_path_gz = staging_dir / rel_key_gz
    assert full_path_gz.is_file()
    # verify it is valid gzip
    with gzip.open(full_path_gz, "rb") as gz:
        assert gz.read() == json_bytes

    # PDF payload -> .pdf (uncompressed for HTTP 206 range requests)
    pdf_bytes = b"%PDF-1.4 Fake PDF contents for testing"
    digest_pdf, rel_key_pdf = stage_body_bytes(pdf_bytes, staging_dir)
    assert rel_key_pdf == f"bodies/sha256/{digest_pdf[:2]}/{digest_pdf}.pdf"
    full_path_pdf = staging_dir / rel_key_pdf
    assert full_path_pdf.is_file()
    # verify raw uncompressed bytes
    assert full_path_pdf.read_bytes() == pdf_bytes


# ===========================================================================
# 5. Stress Test: Schema Integrity Across All 10 Datasets
# ===========================================================================

def test_all_10_weekly_schemas_exist_and_conform():
    """Verify all 10 datasets are configured with schemas, keys, and merge specs."""
    expected_datasets = [
        "congress_meetings",
        "congress_committees",
        "house_events",
        "senate_events",
        "gpo_hearings",
        "gpo_observations",
        "youtube_videos",
        "captions",
        "transcripts",
        "rejected_pages",
    ]
    for ds in expected_datasets:
        assert ds in WEEKLY_TABLE_SCHEMAS, f"Missing schema for {ds}"
        assert ds in WEEKLY_TABLE_KEYS, f"Missing keys for {ds}"
        assert len(WEEKLY_TABLE_KEYS[ds]) >= 1, f"Empty primary keys for {ds}"
        schema = WEEKLY_TABLE_SCHEMAS[ds]
        # Verify PK fields exist in schema
        for k in WEEKLY_TABLE_KEYS[ds]:
            assert schema.get_field_index(k) >= 0, f"PK {k} not in schema for {ds}"

    # Verify gpo_hearings eliminates payload_json
    assert WEEKLY_TABLE_SCHEMAS["gpo_hearings"].get_field_index("payload_json") == -1

    # Verify youtube_videos has upstream_sha256 and no payload_json
    assert WEEKLY_TABLE_SCHEMAS["youtube_videos"].get_field_index("upstream_sha256") >= 0
    assert WEEKLY_TABLE_SCHEMAS["youtube_videos"].get_field_index("payload_json") == -1

    # Verify congress_committees key is ('congress', 'system_code')
    assert WEEKLY_TABLE_KEYS["congress_committees"] == ("congress", "system_code")


# ===========================================================================
# 6. Stress Test: Committee Detail Deduplication Across Congresses
# ===========================================================================

def test_committee_detail_deduplication(tmp_path: Path):
    """Verify unique_details cache prevents duplicate hashing and redundant CAS writes."""
    staging = tmp_path / "cas"
    unique_cache: dict[bytes, str] = {}
    shared_detail = {"name": "Judiciary", "subcommittees": ["Crime", "Courts"]}

    row117 = committee_to_row(
        "hsju00",
        {"congress": 117, "committee": {"systemCode": "hsju00", "chamber": "House"}, "detail": shared_detail},
        staging_dir=staging,
        unique_details=unique_cache,
    )
    row118 = committee_to_row(
        "hsju00",
        {"congress": 118, "committee": {"systemCode": "hsju00", "chamber": "House"}, "detail": shared_detail},
        staging_dir=staging,
        unique_details=unique_cache,
    )
    assert row117["detail_sha256"] is not None
    assert row117["detail_sha256"] == row118["detail_sha256"]
    assert len(unique_cache) == 1


# ===========================================================================
# 7. Stress Test: Row Builder Fallbacks and Error Handling
# ===========================================================================

def test_youtube_row_builder_fallbacks_and_errors(tmp_path: Path):
    """Test all fallback keys and error paths for youtube_video_to_row."""
    staging = tmp_path / "cas"

    # camelCase videoId
    r1 = youtube_video_to_row("hsju00", {"videoId": "v1", "publishedAt": "2026-01-01"}, staging_dir=staging)
    assert r1["video_id"] == "v1"
    assert r1["published_at"] == "2026-01-01"

    # snake_case video_id & videoPublishedAt
    r2 = youtube_video_to_row("hsju00", {"video_id": "v2", "videoPublishedAt": "2026-01-02"}, staging_dir=staging)
    assert r2["video_id"] == "v2"
    assert r2["published_at"] == "2026-01-02"

    # id & details_checked_at
    r3 = youtube_video_to_row("hsju00", {"id": "v3", "details_checked_at": "2026-01-03"}, staging_dir=staging)
    assert r3["video_id"] == "v3"
    assert r3["published_at"] == "2026-01-03"

    # Missing videoId raises ValueError
    with pytest.raises(ValueError, match="missing videoId"):
        youtube_video_to_row("hsju00", {"publishedAt": "2026-01-01"})

    # Missing published_at raises ValueError
    with pytest.raises(ValueError, match="missing published_at"):
        youtube_video_to_row("hsju00", {"videoId": "v1"})


def test_house_event_row_builder_timestamp_fallbacks():
    """Verify house_event_to_row falls back through all timestamp fields."""
    # merge_timestamp
    r1 = house_event_to_row("101", {"merge_timestamp": "2026-01-01"})
    assert r1["merge_timestamp"] == "2026-01-01"

    # imported_at
    r2 = house_event_to_row("102", {"imported_at": "2026-01-02"})
    assert r2["merge_timestamp"] == "2026-01-02"

    # checked
    r3 = house_event_to_row("103", {"checked": "2026-01-03"})
    assert r3["merge_timestamp"] == "2026-01-03"

    # xml_update
    r4 = house_event_to_row("104", {"xml_update": "2026-01-04"})
    assert r4["merge_timestamp"] == "2026-01-04"

    # version
    r5 = house_event_to_row("105", {"version": "2026-01-05"})
    assert r5["merge_timestamp"] == "2026-01-05"

    # Missing event_id raises ValueError
    with pytest.raises(ValueError, match="missing event_id"):
        house_event_to_row("", {"checked": "2026-01-01"})

    # Missing all timestamps raises ValueError
    with pytest.raises(ValueError, match="missing merge timestamp"):
        house_event_to_row("106", {"other": "value"})


def test_gpo_observation_timestamp_extraction():
    """Verify gpo_observation_to_row extracts latest timestamp from nested sections."""
    # From mods
    r1 = gpo_observation_to_row("PKG1", {"mods": {"retrieved_at": "2026-02-01T00:00:00Z"}})
    assert r1["retrieved_at"] == "2026-02-01T00:00:00Z"

    # From listing payload dateIssued
    r2 = gpo_observation_to_row("PKG2", {"listing": {"payload": {"dateIssued": "2026-03-01T00:00:00Z"}}})
    assert r2["retrieved_at"] == "2026-03-01T00:00:00Z"

    # From transcripts
    r3 = gpo_observation_to_row("PKG3", {"transcripts": {"t1": {"retrieved_at": "2026-04-01T00:00:00Z"}}})
    assert r3["retrieved_at"] == "2026-04-01T00:00:00Z"

    # Max timestamp selected across multiple sections
    r4 = gpo_observation_to_row("PKG4", {
        "mods": {"retrieved_at": "2026-01-01T00:00:00Z"},
        "listing": {"retrieved_at": "2026-05-01T00:00:00Z"},
        "checked_at": "2026-02-01T00:00:00Z",
    })
    assert r4["retrieved_at"] == "2026-05-01T00:00:00Z"

    # Missing all timestamps raises ValueError
    with pytest.raises(ValueError, match="missing retrieved_at timestamp"):
        gpo_observation_to_row("PKG5", {"mods": {}})


def test_inventory_rows_retains_all_5_sections():
    """Verify _iter_inventory_rows retains youtube, senate, mods, probes, witness_lists."""
    inventory_state = {
        "youtube": {"vid1": {"kind": "asr", "checked": "2026-09-01"}},
        "senate": {"sen1": "srt"},
        "mods": {"pkg1": {"version": "v1", "checked": "2026-09-02"}},
        "probes": {"pr1": {"source": "probe_src", "checked": "2026-09-03"}},
        "witness_lists": {"https://senate.gov/wl1": {"version": "wl_v1", "checked": "2026-09-04"}},
    }
    rows = list(_iter_inventory_rows(inventory_state))
    sources = {r["source"] for r in rows}
    assert sources == {"youtube", "senate", "mods", "probes", "witness_lists"}
    assert len(rows) == 5
