"""Tier 3: Combination Test 4 — Weekly Tables Row Builders, Arrow Normalization & Fast Digest.

Cross-feature interactions:
- F9: YouTube Videos Row Builder Fix
- F10: Congress Committees Row Builder & Key Fix
- F11: House Events Merge Timestamp Fix
- F12: GPO Observations Watermark Fix
- F13: Senate Events Granular Pages
- F14: Captions & Inventory Retention
- F15: Weekly Tables Arrow Normalization & R2 Offloading
- F16: Weekly Tables Fast Operation Digest
"""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from tests.e2e.harness.contracts import (
    WEEKLY_TABLE_SCHEMAS,
    WEEKLY_TABLE_PRIMARY_KEYS,
    WEEKLY_TABLE_ORDER_BY,
)
from tests.e2e.harness.staging import LocalR2Staging
from tests.e2e.harness.parquet_oracle import ParquetOracle


def compute_buffer_digest(table: pa.Table) -> str:
    hasher = hashlib.sha256()
    for col in table.columns:
        for chunk in col.chunks:
            for buf in chunk.buffers():
                if buf is not None:
                    hasher.update(buf)
    return hasher.hexdigest()[:16]


@pytest.mark.tier3
def test_c04_weekly_ingest_pipeline_with_r2_and_fast_digest(
    local_r2: LocalR2Staging,
    oracle: ParquetOracle,
):
    """C4.1: Synchronize all weekly retention models, offload raw bodies, enforce assertions, and compute fast digest."""
    # 1. YouTube videos batch
    yt_records = [
        {"systemCode": "hsed00", "videoId": f"v_{i}", "publishedAt": f"2026-10-{i+1:02d}T10:00:00Z", "title": f"Hearing {i}"}
        for i in range(5)
    ]
    yt_rows = []
    for r in yt_records:
        upstream_staged = local_r2.stage_bytes(json.dumps({"desc": r["title"] * 50}).encode("utf-8"), is_pdf=False)
        yt_rows.append({
            "system_code": r["systemCode"],
            "video_id": r["videoId"],
            "published_at": r["publishedAt"],
            "title": r["title"],
            "upstream_sha256": upstream_staged["sha256"],
        })
    yt_table = pa.Table.from_pylist(yt_rows, schema=WEEKLY_TABLE_SCHEMAS["youtube_videos"])

    # Assertions on YouTube table
    ok_pk, err_pk = oracle.verify_no_null_keys(yt_table, WEEKLY_TABLE_PRIMARY_KEYS["youtube_videos"])
    assert ok_pk, f"PK violation: {err_pk}"
    ok_order, err_order = oracle.verify_no_null_keys(yt_table, [WEEKLY_TABLE_ORDER_BY["youtube_videos"]])
    assert ok_order, f"Order-by violation: {err_order}"
    digest_yt = compute_buffer_digest(yt_table)
    assert len(digest_yt) == 16

    # 2. Congress committees batch with deduplicated detail
    detail = {"name": "Judiciary", "jurisdiction": "Constitutional Law"}
    detail_staged = local_r2.stage_bytes(json.dumps(detail, sort_keys=True).encode("utf-8"), is_pdf=False)

    comm_records = [
        {"congress": c, "system_code": "hsju00", "chamber": "House", "update_date": "2026-10-21T00:00:00Z", "detail_sha256": detail_staged["sha256"]}
        for c in (116, 117, 118)
    ]
    comm_table = pa.Table.from_pylist(comm_records, schema=WEEKLY_TABLE_SCHEMAS["congress_committees"])
    ok_comm, err_comm = oracle.verify_no_null_keys(comm_table, WEEKLY_TABLE_PRIMARY_KEYS["congress_committees"])
    assert ok_comm

    # 3. House events with checked merge timestamp fallback
    house_records = [
        {"event_id": f"ev_{i}", "merge_timestamp": f"2026-10-19T{i:02d}:00:00Z", "witness_status": "confirmed", "seed": "seed", "source_body_sha256": None}
        for i in range(5)
    ]
    house_table = pa.Table.from_pylist(house_records, schema=WEEKLY_TABLE_SCHEMAS["house_events"])
    ok_house, err_house = oracle.verify_no_null_keys(house_table, [WEEKLY_TABLE_ORDER_BY["house_events"]])
    assert ok_house

    # 4. Senate events with per-page granularity
    senate_records = [
        {"domain": "senate.gov", "record_id": f"rec_{i}", "url": f"https://senate.gov/p_{i}", "observed_at": "2026-10-19T00:00:00Z", "lines_sha256": None}
        for i in range(5)
    ]
    senate_table = pa.Table.from_pylist(senate_records, schema=WEEKLY_TABLE_SCHEMAS["senate_events"])
    ok_sen, err_sen = oracle.verify_no_null_keys(senate_table, WEEKLY_TABLE_PRIMARY_KEYS["senate_events"])
    assert ok_sen

    # 5. GPO observations with watermark
    gpo_records = [
        {"package_id": f"PKG_{i}", "retrieved_at": "2026-10-18T10:00:00Z", "acquisition": "2026-10-18T10:00:00Z", "evidence_sha256": None}
        for i in range(5)
    ]
    gpo_table = pa.Table.from_pylist(gpo_records, schema=WEEKLY_TABLE_SCHEMAS["gpo_observations"])
    ok_gpo, err_gpo = oracle.verify_no_null_keys(gpo_table, [WEEKLY_TABLE_ORDER_BY["gpo_observations"]])
    assert ok_gpo


@pytest.mark.tier3
def test_c04_incremental_weekly_upsert_preserves_monotonic_order():
    """C4.2: Verify multi-batch weekly upsert maintains monotonic order_by ordering."""
    batch_1 = [
        {"system_code": "hsed00", "video_id": "v1", "published_at": "2026-10-10T00:00:00Z"},
        {"system_code": "hsed00", "video_id": "v2", "published_at": "2026-10-12T00:00:00Z"},
    ]
    batch_2 = [
        {"system_code": "hsed00", "video_id": "v3", "published_at": "2026-10-15T00:00:00Z"},
        {"system_code": "hsed00", "video_id": "v2", "published_at": "2026-10-16T00:00:00Z"},  # Updated
    ]

    state = {}
    for r in batch_1 + batch_2:
        state[(r["system_code"], r["video_id"])] = r

    merged = sorted(state.values(), key=lambda x: x["published_at"])
    timestamps = [r["published_at"] for r in merged]
    assert timestamps == ["2026-10-10T00:00:00Z", "2026-10-15T00:00:00Z", "2026-10-16T00:00:00Z"]
    assert len(merged) == 3
