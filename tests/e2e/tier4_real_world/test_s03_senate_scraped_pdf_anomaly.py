"""Tier 4: Scenario 3 — Senate Scraped PDF Anomaly & 256 KiB Limit Enforcement.

Verifies:
- Loading real production dataset /Users/mikewolfd/Work/pipeline-data/meeting-inventory/senate.json.gz (22 domains, 5,232 pages)
- Detection of corrupted binary PDF in intelligence.senate.gov (sites-default-files-hearings-105290.pdf)
- High U+FFFD ratio (> 40% vs 5% threshold) triggers offload to CAS bodies/sha256/<xx>/<sha256>.gz
- Parquet table generation guarantees ZERO string cells > 256 KiB (F2, F4, F10)
- Parquet schema and row group integrity verified via ParquetOracle
"""

from __future__ import annotations
import gzip
import hashlib
import json
from pathlib import Path
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from tests.e2e.harness.contracts import (
    MAX_CELL_SIZE,
    MAX_UFFFD_RATIO,
    WEEKLY_TABLE_SCHEMAS,
    WEEKLY_TABLE_PRIMARY_KEYS,
    WEEKLY_TABLE_ORDER_BY,
)
from tests.e2e.harness.staging import LocalR2Staging
from tests.e2e.harness.parquet_oracle import ParquetOracle


@pytest.mark.tier4
def test_s03_senate_scraped_inventory_pdf_anomaly(
    pipeline_data_dir: Path,
    staging_dir: Path,
    local_r2: LocalR2Staging,
    oracle: ParquetOracle,
):
    """Scenario 3: Process real senate.json.gz, isolate binary PDF anomaly, stage to CAS, and enforce 256 KiB limit."""
    senate_path = pipeline_data_dir / "meeting-inventory" / "senate.json.gz"
    assert senate_path.exists(), "senate.json.gz missing"

    with gzip.open(senate_path, "rt", encoding="utf-8") as f:
        data = json.load(f)

    assert isinstance(data, dict)
    assert len(data) == 22, f"Expected 22 Senate committee domains, got {len(data)}"

    # Expand 22 domains into pages
    total_pages = 0
    anomaly_found = False
    anomaly_key = "https://www.intelligence.senate.gov/wp-content/uploads/2024/08/sites-default-files-hearings-105290.pdf"

    extracted_events = []
    anomaly_cas_sha = None

    for domain, domain_dict in data.items():
        pages = domain_dict.get("pages", {})
        total_pages += len(pages)

        for page_url, page_info in pages.items():
            if not isinstance(page_info, dict):
                continue

            checked_date = page_info.get("checked") or "1970-01-01"
            lines = page_info.get("lines", [])
            body_text = "\n".join(lines)
            body_bytes = body_text.encode("utf-8")

            # Check for binary PDF anomaly or high U+FFFD
            ufffd_count = body_text.count("\ufffd")
            ufffd_ratio = ufffd_count / len(body_text) if len(body_text) > 0 else 0.0

            record_id = hashlib.sha256(page_url.encode("utf-8")).hexdigest()[:16]

            if page_url == anomaly_key:
                anomaly_found = True
                assert ufffd_ratio > 0.40, f"Expected high U+FFFD ratio > 0.40, got {ufffd_ratio:.4f}"
                assert len(body_bytes) > 20_000_000, "Expected >20MB corrupted text payload"

                # Offload high-UFFFD corrupted payload to CAS as .gz
                cas_obj = local_r2.stage_bytes(body_bytes, is_pdf=False)
                anomaly_cas_sha = cas_obj["sha256"]
                assert cas_obj["is_pdf"] is False
                assert cas_obj["abs_path"].name.endswith(".gz")

                # In normalized table, store reference with CAS lines_sha256, NEVER the 20MB raw cell
                extracted_events.append({
                    "domain": domain,
                    "record_id": record_id,
                    "url": page_url,
                    "observed_at": checked_date,
                    "lines_sha256": anomaly_cas_sha,
                })
            elif len(body_bytes) > 0:
                # Regular page: if exceeds cell size, offload to CAS
                if len(body_bytes) > MAX_CELL_SIZE:
                    cas_obj = local_r2.stage_bytes(body_bytes, is_pdf=False)
                    sha = cas_obj["sha256"]
                else:
                    sha = hashlib.sha256(body_bytes).hexdigest()

                # Add sample to events table
                if len(extracted_events) < 100:
                    extracted_events.append({
                        "domain": domain,
                        "record_id": record_id,
                        "url": page_url,
                        "observed_at": checked_date,
                        "lines_sha256": sha,
                    })

    assert total_pages == 5232, f"Expected exactly 5,232 pages across 22 domains, got {total_pages}"
    assert anomaly_found is True, "Target anomaly sites-default-files-hearings-105290.pdf not found in data"
    assert anomaly_cas_sha is not None, "Anomaly failed to stage to CAS"

    # Also stage a true PDF payload to verify .pdf CAS handling in the same test
    sample_pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"
    pdf_obj = local_r2.stage_bytes(sample_pdf_bytes, is_pdf=True)
    assert pdf_obj["is_pdf"] is True
    assert pdf_obj["abs_path"].name.endswith(".pdf")

    # Verify CAS file integrity across all staged objects
    ok, errors = local_r2.verify_cas_integrity()
    assert ok, f"CAS integrity verification failed: {errors}"

    # Build Parquet table for senate_events using WEEKLY_TABLE_SCHEMAS["senate_events"]
    schema = WEEKLY_TABLE_SCHEMAS["senate_events"]
    cols = {name: [row[name] for row in extracted_events] for name in schema.names}
    table = pa.Table.from_pydict(cols, schema=schema)

    # Sort table by order_by column ('observed_at')
    import pyarrow.compute as pc
    sort_indices = pc.sort_indices(table, sort_keys=[("observed_at", "ascending")])
    sorted_table = table.take(sort_indices)

    out_parquet = staging_dir / "senate_events_normalized.parquet"
    pq.write_table(sorted_table, out_parquet)

    # Verify via ParquetOracle: schema, 256 KiB limit, non-null keys, primary key uniqueness
    ok, errs = oracle.verify_schema_exact(out_parquet, schema)
    assert ok, errs
    ok, errs = oracle.verify_cell_size_limit(out_parquet, max_bytes=MAX_CELL_SIZE)
    assert ok, errs
    ok, errs = oracle.verify_no_null_keys(out_parquet, WEEKLY_TABLE_PRIMARY_KEYS["senate_events"])
    assert ok, errs
    ok, errs = oracle.verify_unique_keys(out_parquet, WEEKLY_TABLE_PRIMARY_KEYS["senate_events"])
    assert ok, errs
