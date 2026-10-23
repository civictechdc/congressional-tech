"""Tier 4: Scenario 2 — Congress Committees Multi-Congress Sync against Real Production Data.

Verifies:
- Loading real production dataset /Users/mikewolfd/Work/pipeline-data/congress_committees.jsonl.gz (3,424 rows)
- Nested record['committee'] extraction for systemCode, chamber, and updateDate
- Compound primary key ('congress', 'system_code') yields 3,424 distinct rows (0 nulls, no 14-row collapse)
- Deduplication of 460 unique detail objects offloaded via detail_sha256 to local CAS
"""

from __future__ import annotations
import gzip
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


@pytest.mark.tier4
def test_s02_congress_committees_real_sync(
    pipeline_data_dir: Path,
    staging_dir: Path,
    local_r2: LocalR2Staging,
    oracle: ParquetOracle,
):
    """Scenario 2: Process real congress_committees.jsonl.gz into normalized Arrow table with deduplicated detail in CAS."""
    gz_path = pipeline_data_dir / "congress_committees.jsonl.gz"
    assert gz_path.exists(), "congress_committees.jsonl.gz missing"

    extracted_rows = []
    unique_details = {}

    with gzip.open(gz_path, "rt", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            comm = rec.get("committee") or {}

            sys_code = comm.get("systemCode") or comm.get("system_code") or ""
            chamber = comm.get("chamber") or ""
            update_date = comm.get("updateDate") or comm.get("update_date") or ""
            congress = int(rec.get("congress") or comm.get("congress") or 0)

            # Deduplicate detail
            detail = rec.get("detail")
            detail_sha = None
            if detail:
                detail_bytes = json.dumps(detail, sort_keys=True).encode("utf-8")
                if detail_bytes not in unique_details:
                    staged = local_r2.stage_bytes(detail_bytes, is_pdf=False)
                    unique_details[detail_bytes] = staged["sha256"]
                detail_sha = unique_details[detail_bytes]

            extracted_rows.append({
                "congress": congress,
                "system_code": str(sys_code),
                "chamber": str(chamber),
                "update_date": str(update_date),
                "detail_sha256": detail_sha,
            })

    # Assertions on real dataset
    assert len(extracted_rows) == 3424, f"Expected 3,424 rows, got {len(extracted_rows)}"

    # 1. Zero NULL or empty system_code, chamber, update_date
    assert all(r["system_code"] != "" for r in extracted_rows)
    assert all(r["chamber"] != "" for r in extracted_rows)
    assert all(r["update_date"] != "" for r in extracted_rows)

    # 2. Distinct primary keys
    keys = {(r["congress"], r["system_code"]) for r in extracted_rows}
    assert len(keys) == 3424, f"Primary key collapse: expected 3,424 unique keys, got {len(keys)}"

    # 3. Deduplication of detail objects: 460 unique across 3,424 rows
    assert len(unique_details) == 460, f"Expected 460 unique detail objects, got {len(unique_details)}"

    # 4. Build Arrow table conforming to schema
    schema = WEEKLY_TABLE_SCHEMAS["congress_committees"]
    table = pa.Table.from_pylist(extracted_rows, schema=schema)
    out_path = staging_dir / "congress_committees_real.parquet"
    pq.write_table(table, out_path)

    # 5. Verify through Oracle
    ok_pk, err_pk = oracle.verify_no_null_keys(out_path, WEEKLY_TABLE_PRIMARY_KEYS["congress_committees"])
    assert ok_pk, f"PK failure: {err_pk}"
    ok_order, err_order = oracle.verify_no_null_keys(out_path, [WEEKLY_TABLE_ORDER_BY["congress_committees"]])
    assert ok_order, f"Order-by failure: {err_order}"
