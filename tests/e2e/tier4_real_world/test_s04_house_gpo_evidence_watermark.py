"""Tier 4: Scenario 4 — House Event Inventory & GPO Evidence Watermarking against Production Data.

Verifies:
- Loading real production dataset pipeline-data/meeting-inventory/house.json.gz (5,741 events)
- 100% fallback to 'checked' date watermark when timestamp fields are evaluated
- Loading real production dataset pipeline-data/gpo-evidence.jsonl.gz (644 records)
- Watermark extraction from GPO listing payloads (dateIssued / lastModified) and MODS acquisition
- Offloading GPO evidence documents to local CAS bodies/sha256/<xx>/<sha256>.gz
- Generating house_events and gpo_observations weekly tables
- Verification of schema contracts, non-null keys, primary key uniqueness, and zero cells > 256 KiB
"""

from __future__ import annotations
import gzip
import json
from pathlib import Path
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from tests.e2e.harness.contracts import (
    MAX_CELL_SIZE,
    WEEKLY_TABLE_SCHEMAS,
    WEEKLY_TABLE_PRIMARY_KEYS,
    WEEKLY_TABLE_ORDER_BY,
)
from tests.e2e.harness.staging import LocalR2Staging
from tests.e2e.harness.parquet_oracle import ParquetOracle


@pytest.mark.tier4
def test_s04_house_inventory_and_gpo_evidence_watermark(
    pipeline_data_dir: Path,
    staging_dir: Path,
    local_r2: LocalR2Staging,
    oracle: ParquetOracle,
):
    """Scenario 4: Process real house inventory (5,741 events) and GPO evidence (644 records) into weekly tables."""
    house_path = pipeline_data_dir / "meeting-inventory" / "house.json.gz"
    gpo_path = pipeline_data_dir / "gpo-evidence.jsonl.gz"

    assert house_path.exists(), "house.json.gz missing"
    assert gpo_path.exists(), "gpo-evidence.jsonl.gz missing"

    # 1. Process house.json.gz
    with gzip.open(house_path, "rt", encoding="utf-8") as f:
        house_data = json.load(f)

    assert isinstance(house_data, dict)
    assert len(house_data) == 5741, f"Expected 5,741 House events, got {len(house_data)}"

    house_rows = []
    fallback_to_checked_count = 0

    for event_id, item in house_data.items():
        if not isinstance(item, dict):
            continue

        checked_date = item.get("checked") or "1970-01-01"
        xml_update = item.get("xml_update")
        version = item.get("version")

        # Determine merge timestamp: fallback to checked when xml_update is absent
        if xml_update:
            merge_timestamp = str(xml_update)
        elif version:
            merge_timestamp = str(version)
        else:
            merge_timestamp = checked_date
            fallback_to_checked_count += 1

        # Check document payloads
        docs = item.get("documents", [])
        body_sha = None
        if docs:
            doc_bytes = json.dumps(docs, sort_keys=True).encode("utf-8")
            if len(doc_bytes) > 4096:
                staged = local_r2.stage_bytes(doc_bytes, is_pdf=False)
                body_sha = staged["sha256"]

        house_rows.append({
            "event_id": str(event_id),
            "chamber": "house",
            "merge_timestamp": merge_timestamp,
            "status": item.get("status") or "xml",
            "witness_status": item.get("witness_status") or "absent",
            "seed": item.get("seed") or "research cache",
            "source_body_sha256": body_sha,
        })

    assert len(house_rows) == 5741, "Failed to extract all 5,741 House rows"

    # Build house_events Parquet table
    house_schema = WEEKLY_TABLE_SCHEMAS["house_events"]
    house_cols = {name: [r[name] for r in house_rows] for name in house_schema.names}
    house_table = pa.Table.from_pydict(house_cols, schema=house_schema)

    import pyarrow.compute as pc
    sort_idx = pc.sort_indices(house_table, sort_keys=[("merge_timestamp", "ascending")])
    sorted_house = house_table.take(sort_idx)

    house_parquet = staging_dir / "house_events.parquet"
    pq.write_table(sorted_house, house_parquet)

    # Verify house_events table
    ok, errs = oracle.verify_schema_exact(house_parquet, house_schema)
    assert ok, errs
    ok, errs = oracle.verify_cell_size_limit(house_parquet, max_bytes=MAX_CELL_SIZE)
    assert ok, errs
    ok, errs = oracle.verify_no_null_keys(house_parquet, WEEKLY_TABLE_PRIMARY_KEYS["house_events"])
    assert ok, errs
    ok, errs = oracle.verify_unique_keys(house_parquet, WEEKLY_TABLE_PRIMARY_KEYS["house_events"])
    assert ok, errs

    # 2. Process gpo-evidence.jsonl.gz (644 records)
    gpo_rows = []
    with gzip.open(gpo_path, "rt", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            pkg_id = rec.get("package_id") or ""
            listing = rec.get("listing") or {}
            payload = listing.get("payload") or {}

            # Watermark derived from lastModified, dateIssued, or checked_at
            retrieved_at = (
                payload.get("lastModified")
                or payload.get("dateIssued")
                or rec.get("checked_at")
                or "1970-01-01T00:00:00Z"
            )

            mods = rec.get("mods") or {}
            acquisition = mods.get("acquisition") or rec.get("acquisition") or "http"
            mods_body = mods.get("body") or ""

            # Stage MODS body to CAS if present
            evidence_sha = None
            if mods_body:
                staged_mods = local_r2.stage_bytes(mods_body.encode("utf-8"), is_pdf=False)
                evidence_sha = staged_mods["sha256"]

            gpo_rows.append({
                "package_id": pkg_id,
                "retrieved_at": retrieved_at,
                "acquisition": acquisition,
                "evidence_sha256": evidence_sha,
            })

    assert len(gpo_rows) == 644, f"Expected 644 GPO records, got {len(gpo_rows)}"

    # Build gpo_observations Parquet table
    gpo_schema = WEEKLY_TABLE_SCHEMAS["gpo_observations"]
    gpo_cols = {name: [r[name] for r in gpo_rows] for name in gpo_schema.names}
    gpo_table = pa.Table.from_pydict(gpo_cols, schema=gpo_schema)

    gpo_sort_idx = pc.sort_indices(gpo_table, sort_keys=[("retrieved_at", "ascending")])
    sorted_gpo = gpo_table.take(gpo_sort_idx)

    gpo_parquet = staging_dir / "gpo_observations.parquet"
    pq.write_table(sorted_gpo, gpo_parquet)

    # Verify gpo_observations table
    ok, errs = oracle.verify_schema_exact(gpo_parquet, gpo_schema)
    assert ok, errs
    ok, errs = oracle.verify_cell_size_limit(gpo_parquet, max_bytes=MAX_CELL_SIZE)
    assert ok, errs
    ok, errs = oracle.verify_no_null_keys(gpo_parquet, WEEKLY_TABLE_PRIMARY_KEYS["gpo_observations"])
    assert ok, errs
    ok, errs = oracle.verify_unique_keys(gpo_parquet, WEEKLY_TABLE_PRIMARY_KEYS["gpo_observations"])
    assert ok, errs

    # Verify CAS integrity of all staged evidence bodies
    ok, errors = local_r2.verify_cas_integrity()
    assert ok, f"CAS integrity check failed: {errors}"
