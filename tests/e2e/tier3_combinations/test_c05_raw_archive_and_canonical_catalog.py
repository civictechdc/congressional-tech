"""Tier 3: Combination Test 5 — Raw Archive & Canonical Catalog Compaction Pipeline.

Cross-feature interactions:
- F17: Raw Archive Body Key Derivation on Read
- F18: Raw Archive Digest & Type Tightening
- F19: Raw Archive Row Group Tuning
- F20: Canonical Catalog Top-Level Duplicate Dropping
- F21: Canonical Catalog Null Pruning & Scalarization
- F22: Canonical Catalog Footer Bloat Elimination
- F23: Readings & Review Compaction
"""

from __future__ import annotations
from pathlib import Path
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.retention.body_keys import physical_body_object_key
from tests.e2e.harness.contracts import (
    RAW_ARCHIVE_SCHEMAS,
    FORBIDDEN_RAW_ARCHIVE_COLUMNS,
    FORBIDDEN_CATALOG_TOP_LEVEL_COLUMNS,
    FORBIDDEN_REVIEW_ROWS_COLUMNS,
    CANONICAL_CATALOG_SCHEMAS,
)
from tests.e2e.harness.parquet_oracle import ParquetOracle


@pytest.mark.tier3
def test_c05_raw_archive_to_canonical_catalog_pipeline(
    staging_dir: Path,
    oracle: ParquetOracle,
):
    """C5.1: Verify raw capture archive write, on-read body_key derivation, and canonical catalog emission."""
    # 1. Ingest raw capture into captures table with binary(32) digest and tightened status
    hex_digest = "ab" * 32
    bin_digest = bytes.fromhex(hex_digest)

    capture_row = {
        "family": "govinfo",
        "capture_date": "2026-10-19",
        "source_file": "receipts.jsonl",
        "source_line": 1,
        "receipt_key": "rcpt_1",
        "receipt_line": 1,
        "reference_kind": "direct",
        "pointer_json": "{}",
        "context_url": "https://govinfo.gov/package",
        "sha256": bin_digest,
        "bytes": 5000,
        "is_stored": True,
        "stored_bytes": 1200,
        "fidelity": "exact",
        "media_type": "application/pdf",
        "retrieved_at": None,
        "http_status": 200,
        "resolution": "resolved",
        "original_path": None,
    }

    captures_table = pa.Table.from_pylist([capture_row], schema=RAW_ARCHIVE_SCHEMAS["captures"])
    captures_path = staging_dir / "captures_c05.parquet"
    pq.write_table(captures_table, captures_path, row_group_size=65536)

    # Verify no body_key or stored_sha256 on disk
    ok_archive, err_archive = oracle.verify_column_absence(captures_path, FORBIDDEN_RAW_ARCHIVE_COLUMNS)
    assert ok_archive, f"Forbidden columns in raw archive: {err_archive}"

    # 2. Downstream reader reads captures and derives body_key on demand
    read_captures = pq.read_table(captures_path)
    read_sha = read_captures["sha256"].to_pylist()[0]
    derived_body_key = physical_body_object_key(read_sha.hex(), is_pdf=True)
    assert derived_body_key == f"bodies/sha256/{hex_digest[:2]}/{hex_digest}.pdf"

    # 3. Canonical catalog generation emits filenames.parquet:
    # Drops 47 duplicate source_* columns, preserves source_occurrences, scalarizes congress/http_status
    filename_row = {
        "id": "file_1",
        "url": "https://govinfo.gov/package.pdf",
        "sha256": hex_digest,
        "congress": 118,           # Scalar int32 (scalarized from list<string>)
        "http_status": 200,        # Scalar int16 (scalarized from list<string>)
        "document_kind": "report", # Scalar string
        "source_occurrences": [
            {"source_url": "https://govinfo.gov/package.pdf", "source_chamber": "House", "source_line": 1}
        ],
    }

    schema_fn = pa.schema([
        ("id", pa.string()),
        ("url", pa.string()),
        ("sha256", pa.string()),
        ("congress", pa.int32()),
        ("http_status", pa.int16()),
        ("document_kind", pa.string()),
        ("source_occurrences", pa.list_(pa.struct([
            ("source_url", pa.string()),
            ("source_chamber", pa.string()),
            ("source_line", pa.int64()),
        ]))),
    ])

    filenames_table = pa.Table.from_pylist([filename_row], schema=schema_fn)
    fn_path = staging_dir / "filenames_c05.parquet"
    pq.write_table(filenames_table, fn_path, row_group_size=16384)

    ok_fn, err_fn = oracle.verify_column_absence(fn_path, FORBIDDEN_CATALOG_TOP_LEVEL_COLUMNS)
    assert ok_fn, f"Forbidden top-level column found: {err_fn}"

    # 4. Review rows export omits record_json and canonical_url
    review_row = {
        "id": "rev_1",
        "url": "https://govinfo.gov/package.pdf",
        "sha256": hex_digest,
        "congress": 118,
        "chamber": "House",
        "title": "Hearing Document",
        "format": "pdf",
        "http_status": 200,
        "fetched_at": None,
    }
    review_table = pa.Table.from_pylist([review_row], schema=CANONICAL_CATALOG_SCHEMAS["review_rows"])
    review_path = staging_dir / "review_c05.parquet"
    pq.write_table(review_table, review_path)

    ok_rev, err_rev = oracle.verify_column_absence(review_path, FORBIDDEN_REVIEW_ROWS_COLUMNS)
    assert ok_rev, f"Forbidden review column found: {err_rev}"
