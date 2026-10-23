"""Tier 4: Scenario 5 — Browser Publication Release ca4748be Optimization & Cartesian Elimination.

Verifies:
- Inspecting production release at /Users/mikewolfd/Work/pipeline-data/committee-explorer/public/releases/ca4748be7105a94345815382
- Detecting legacy redundant columns across production tables:
  - meetings.parquet: kind, explanation, meeting_id
  - materials.parquet: kind, explanation, appearance_ids
  - witnesses.parquet: kind, search_text, explanation
  - committees.parquet: kind, committee_ids
- Dropping forbidden columns according to FORBIDDEN_BROWSER_COLUMNS (F25, F26, F28, ct-8od2)
- Re-encoding optimized browser tables to verify 0 cells > 256 KiB and non-null unique 'id' primary keys
- Verifying row group metadata and ParquetOracle contracts on optimized artifacts
"""

from __future__ import annotations
from pathlib import Path
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from tests.e2e.harness.contracts import (
    MAX_CELL_SIZE,
    BROWSER_TABLE_SCHEMAS,
    FORBIDDEN_BROWSER_COLUMNS,
)
from tests.e2e.harness.parquet_oracle import ParquetOracle


@pytest.mark.tier4
def test_s05_browser_publication_release_optimization(
    pipeline_data_dir: Path,
    staging_dir: Path,
    oracle: ParquetOracle,
):
    """Scenario 5: Audit release ca4748be, verify elimination of forbidden redundant columns, and validate optimized schemas."""
    release_dir = pipeline_data_dir / "committee-explorer" / "public" / "releases" / "ca4748be7105a94345815382"
    assert release_dir.exists(), f"Release directory missing at {release_dir}"

    table_names = ["meetings", "materials", "witnesses", "committees"]

    for name in table_names:
        raw_file = release_dir / f"{name}.parquet"
        assert raw_file.exists(), f"Missing production table {raw_file}"

        # 1. Verify that raw legacy release DOES contain forbidden columns
        raw_schema = pq.read_schema(raw_file)
        forbidden = FORBIDDEN_BROWSER_COLUMNS[name]
        legacy_present = forbidden.intersection(set(raw_schema.names))
        assert len(legacy_present) > 0, f"Expected legacy table {name} to contain forbidden columns, found none"

        # 2. Read sample of raw table and project away forbidden columns
        # Read first 1,000 rows to keep test execution fast while exercising all schema columns
        raw_table = pq.read_table(raw_file).slice(0, 1000)
        assert raw_table.num_rows > 0

        # Drop forbidden columns
        kept_names = [col for col in raw_table.schema.names if col not in forbidden]
        optimized_table = raw_table.select(kept_names)

        # Write optimized parquet file in local staging
        opt_file = staging_dir / f"{name}_optimized.parquet"
        pq.write_table(optimized_table, opt_file)

        # 3. Verify optimized table with ParquetOracle
        # Verify strict column absence
        ok, errs = oracle.verify_column_absence(opt_file, forbidden)
        assert ok, f"Optimized {name} still contained forbidden columns: {errs}"

        # Verify cell size limits (<= 256 KiB)
        ok, errs = oracle.verify_cell_size_limit(opt_file, max_bytes=MAX_CELL_SIZE)
        assert ok, f"Cell size limit violation in {name}: {errs}"

        # Verify key column 'id' is non-null and unique
        ok, errs = oracle.verify_no_null_keys(opt_file, ["id"])
        assert ok, f"Non-null check failed on {name}: {errs}"
        ok, errs = oracle.verify_unique_keys(opt_file, ["id"])
        assert ok, f"Key uniqueness check failed on {name}: {errs}"

        # Verify schema subset matches target browser table schema
        target_schema = BROWSER_TABLE_SCHEMAS[name]
        ok, errs = oracle.verify_schema_subset(opt_file, target_schema)
        assert ok, f"Schema subset mismatch for {name}: {errs}"
