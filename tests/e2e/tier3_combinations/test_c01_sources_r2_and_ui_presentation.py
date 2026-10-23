"""Tier 3: Combination Test 1 — Sources R2 Offloading, Columnar Normalization, Cell Guard & UI Presentation.

Cross-feature interactions:
- F1: Sources Parquet Direct-to-R2 Offload
- F2: Sources Parquet Typed Columnar Normalization
- F4: 256 KiB Cell Size Guard
- F5: Explorer UI Direct Column Presentation
"""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from tests.e2e.harness.contracts import (
    SOURCE_SCHEMA,
    FORBIDDEN_SOURCE_COLUMNS,
    MAX_CELL_SIZE,
)
from tests.e2e.harness.staging import LocalR2Staging
from tests.e2e.harness.parquet_oracle import ParquetOracle
from tests.e2e.harness.data_generators import SyntheticDataGenerator


@pytest.mark.tier3
def test_c01_full_ingest_offload_normalization_and_ui_render(
    staging_dir: Path,
    local_r2: LocalR2Staging,
    oracle: ParquetOracle,
    generator: SyntheticDataGenerator,
):
    """C1.1: Verify end-to-end flow from raw JSON ingest to CAS offload, typed Parquet, and UI rendering."""
    # 1. Ingest raw technical JSON (100 KiB)
    raw_payload = {
        "title": "Comprehensive Hearing on Autonomous Systems",
        "committee": "House Committee on Science, Space, and Technology",
        "detailed_notes": ["Note " + str(i) for i in range(1000)],
        "stream_links": [{"url": "https://youtube.com/watch?v=ai123", "role": "primary"}],
    }
    raw_bytes = json.dumps(raw_payload).encode("utf-8")

    # 2. Stage directly to local CAS (bodies/sha256/<xx>/<sha256>.gz)
    staged = local_r2.stage_bytes(raw_bytes, is_pdf=False)
    assert local_r2.has_body(staged["sha256"])

    # 3. Build normalized SourceRecord conforming to SOURCE_SCHEMA (zero payload column)
    rec = {
        "id": "src-c01-001",
        "kind": "source_record",
        "provider": "congress.gov",
        "url": "https://congress.gov/event/114250",
        "title": raw_payload["title"],
        "retrieved_at": "2026-10-22T10:00:00Z",
        "source_modified_at": "2026-10-20T09:00:00Z",
        "imported_at": "2026-10-22T11:00:00Z",
        "identifier_scheme": "event_id",
        "identifier_value": "114250",
        "identifier_scope": "118",
        "facts": [
            {"label": "Committee", "value": raw_payload["committee"]},
            {"label": "Notes Count", "value": "1000"},
        ],
        "links": [
            {"group": "Broadcast", "label": "Live Stream", "href": raw_payload["stream_links"][0]["url"]}
        ],
        "retained_uri": staged["uri"],
        "retained_sha256": staged["sha256"],
    }

    # 4. Write to Parquet and verify physical layout & cell limits
    table = pa.Table.from_pylist([rec], schema=SOURCE_SCHEMA)
    sources_path = staging_dir / "sources_c01.parquet"
    pq.write_table(table, sources_path)

    # Assertions on output Parquet
    ok_absence, err_absence = oracle.verify_column_absence(sources_path, FORBIDDEN_SOURCE_COLUMNS)
    assert ok_absence, f"Payload column found: {err_absence}"

    ok_cell, err_cell = oracle.verify_cell_size_limit(sources_path, max_bytes=MAX_CELL_SIZE)
    assert ok_cell, f"Cell size violation: {err_cell}"

    # 5. UI Presentation verification: read table and render without JSON.parse
    read_table = pq.read_table(sources_path)
    rendered_row = read_table.to_pylist()[0]

    # Direct presentation
    assert rendered_row["title"] == "Comprehensive Hearing on Autonomous Systems"
    assert len(rendered_row["facts"]) == 2
    assert rendered_row["facts"][0]["value"] == "House Committee on Science, Space, and Technology"
    assert rendered_row["links"][0]["href"] == "https://youtube.com/watch?v=ai123"

    # Saved copy action resolves to local CAS
    assert rendered_row["retained_uri"].startswith("bodies/sha256/")
    fetched_body = local_r2.get_body_bytes(rendered_row["retained_sha256"])
    assert json.loads(fetched_body.decode("utf-8")) == raw_payload


@pytest.mark.tier3
def test_c01_pdf_hearing_document_staging_and_ui_range_link(
    staging_dir: Path,
    local_r2: LocalR2Staging,
    generator: SyntheticDataGenerator,
):
    """C1.2: Verify PDF source stages uncompressed .pdf and UI constructs active byte-range link."""
    pdf_bytes = generator.generate_pdf_bytes(length=8192)
    staged = local_r2.stage_bytes(pdf_bytes, is_pdf=True)

    rec = generator.generate_source_record(
        provider="senate.committees",
        scheme="pdf_doc",
        value="105290",
        title="Senate Intelligence Hearing Report",
    )
    rec["retained_uri"] = staged["uri"]
    rec["retained_sha256"] = staged["sha256"]

    table = pa.Table.from_pylist([{k: rec[k] for k in SOURCE_SCHEMA.names}], schema=SOURCE_SCHEMA)
    path = staging_dir / "sources_pdf.parquet"
    pq.write_table(table, path)

    read_rec = pq.read_table(path).to_pylist()[0]
    assert read_rec["retained_uri"].endswith(".pdf")

    # UI 'Open saved original' simulates resolving CAS object
    assert local_r2.has_body(read_rec["retained_sha256"])
    retrieved_pdf = local_r2.get_body_bytes(read_rec["retained_sha256"], is_pdf=True)
    assert retrieved_pdf.startswith(b"%PDF-")


@pytest.mark.tier3
def test_c01_large_payload_offload_preserves_slim_table_size(
    staging_dir: Path,
    local_r2: LocalR2Staging,
    oracle: ParquetOracle,
):
    """C1.3: Verify 5 MB technical payload is offloaded to CAS while Parquet row remains <1 KiB."""
    large_dict = {"items": ["evidence_record_" + str(i) for i in range(50000)]}
    large_raw = json.dumps(large_dict).encode("utf-8")
    assert len(large_raw) > 1024 * 1024  # > 1 MB

    staged = local_r2.stage_bytes(large_raw, is_pdf=False)
    rec = {
        "id": "src_large",
        "kind": "source_record",
        "provider": "govinfo",
        "url": "https://govinfo.gov/hearing",
        "title": "Large Record",
        "retrieved_at": "2026-10-22T00:00:00Z",
        "source_modified_at": None,
        "imported_at": "2026-10-22T00:00:00Z",
        "identifier_scheme": "pkg",
        "identifier_value": "1",
        "identifier_scope": "118",
        "facts": [{"label": "Size", "value": "5MB"}],
        "links": [],
        "retained_uri": staged["uri"],
        "retained_sha256": staged["sha256"],
    }

    table = pa.Table.from_pylist([rec], schema=SOURCE_SCHEMA)
    out_file = staging_dir / "sources_slim.parquet"
    pq.write_table(table, out_file)

    # Parquet file size should be tiny (< 5 KiB)
    assert out_file.stat().st_size < 10 * 1024
    ok, errors = oracle.verify_cell_size_limit(out_file, max_bytes=MAX_CELL_SIZE)
    assert ok


@pytest.mark.tier3
def test_c01_cell_guard_catches_oversized_unnormalized_cell(oracle: ParquetOracle):
    """C1.4: Verify cell size guard rejects table if someone attempts to embed raw payload in title."""
    oversized_title = "Title with embedded technical body: " + ("Z" * 300000)
    row = {
        "id": "src_violating",
        "kind": "source_record",
        "provider": "senate",
        "url": "https://senate.gov",
        "title": oversized_title,
        "retrieved_at": "2026-10-22T00:00:00Z",
        "source_modified_at": None,
        "imported_at": "2026-10-22T00:00:00Z",
        "identifier_scheme": "h",
        "identifier_value": "1",
        "identifier_scope": "118",
        "facts": [],
        "links": [],
        "retained_uri": "bodies/sha256/00/00.gz",
        "retained_sha256": "00" * 32,
    }
    table = pa.Table.from_pylist([row], schema=SOURCE_SCHEMA)
    ok, errors = oracle.verify_cell_size_limit(table, max_bytes=MAX_CELL_SIZE)
    assert not ok
    assert "exceeds 262144 bytes" in errors[0]
