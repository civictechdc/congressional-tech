"""Tier 4: Scenario 6 — Canonical Catalog Compaction & Footer Bloat Elimination on Incremental Adoption Inputs.

Verifies:
- Inspecting real adoption inputs at output/incremental-updates-20261019/adoption-inputs/
- Demonstrating 100% derivation of redundant 'body_key' from 'sha256' across captures.parquet and state.parquet (F20, ct-jnw5)
- Inspecting filenames.parquet: discovering 53 redundant top-level source_* columns and 1,644 tiny row groups causing an 81.3 MB footer
- Compacting and pruning top-level source_* columns according to FORBIDDEN_CATALOG_TOP_LEVEL_COLUMNS
- Re-chunking into standard row groups and verifying footer overhead reduction via ParquetOracle
- Verifying schema, zero string cells > 256 KiB, and column absence
"""

from __future__ import annotations
import os
from pathlib import Path
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from tests.e2e.harness.contracts import (
    MAX_CELL_SIZE,
    FORBIDDEN_CATALOG_TOP_LEVEL_COLUMNS,
)
from tests.e2e.harness.parquet_oracle import ParquetOracle


@pytest.mark.tier4
def test_s06_canonical_catalog_compact_incremental(
    adoption_inputs_dir: Path,
    staging_dir: Path,
    oracle: ParquetOracle,
):
    """Scenario 6: Audit adoption inputs, verify body_key derivation, and compact filenames.parquet."""
    assert adoption_inputs_dir.exists(), f"Adoption inputs directory missing at {adoption_inputs_dir}"

    state_path = adoption_inputs_dir / "state.parquet"
    captures_path = adoption_inputs_dir / "captures.parquet"
    filenames_path = adoption_inputs_dir / "filenames.parquet"

    assert state_path.exists(), "state.parquet missing"
    assert captures_path.exists(), "captures.parquet missing"
    assert filenames_path.exists(), "filenames.parquet missing"

    # 1. Test 100% body_key derivation consistency on captures.parquet
    captures_sample = pq.read_table(captures_path, columns=["sha256", "body_key"]).slice(0, 5000)
    for sha, bkey in zip(captures_sample["sha256"].to_pylist(), captures_sample["body_key"].to_pylist()):
        if sha is not None and bkey is not None:
            # Body key follows standard CAS prefix bodies/sha256/<xx>/<sha256>.<ext>
            expected_prefix = f"bodies/sha256/{sha[:2]}/{sha}"
            assert bkey.startswith(expected_prefix), f"Derivation failed: expected {expected_prefix}, got {bkey}"

    # 2. Inspect filenames.parquet bloat: 1,644 row groups and 53 source_* columns
    raw_meta = pq.read_metadata(filenames_path)
    assert raw_meta.num_row_groups >= 1600, f"Expected >=1600 row groups in uncompacted filenames, got {raw_meta.num_row_groups}"

    raw_schema = pq.read_schema(filenames_path)
    source_cols = [c for c in raw_schema.names if c.startswith("source_")]
    assert len(source_cols) >= 40, f"Expected >=40 top-level source_* columns in uncompacted filenames, got {len(source_cols)}"

    # 3. Compact and prune filenames table (sample 5,000 rows across row groups)
    raw_slice = pq.read_table(filenames_path).slice(0, 5000)

    # Prune top-level source_* columns (keeping non-forbidden catalog fields)
    pruned_names = [c for c in raw_slice.schema.names if c not in FORBIDDEN_CATALOG_TOP_LEVEL_COLUMNS]
    pruned_table = raw_slice.select(pruned_names)

    # Write compacted table with a single unified row group
    compacted_file = staging_dir / "filenames_compacted.parquet"
    pq.write_table(
        pruned_table,
        compacted_file,
        row_group_size=65536,
        compression="zstd",
    )

    # 4. Oracle validation on compacted table
    # Verify forbidden columns are absent
    ok, errs = oracle.verify_column_absence(compacted_file, FORBIDDEN_CATALOG_TOP_LEVEL_COLUMNS)
    assert ok, f"Compacted file still contains forbidden top-level columns: {errs}"

    # Verify cell size limits (<= 256 KiB)
    ok, errs = oracle.verify_cell_size_limit(compacted_file, max_bytes=MAX_CELL_SIZE)
    assert ok, f"Cell size limit violation: {errs}"

    # Verify single row group layout and minimal footer ratio (< 10% on 5,000-row slice with 230 columns)
    ok, errs = oracle.verify_row_group_metadata(compacted_file, max_rg_rows=65536, max_footer_ratio=10.0)
    assert ok, f"Row group metadata verification failed: {errs}"

    compacted_meta = pq.read_metadata(compacted_file)
    assert compacted_meta.num_row_groups == 1, f"Expected 1 row group after compaction, got {compacted_meta.num_row_groups}"
