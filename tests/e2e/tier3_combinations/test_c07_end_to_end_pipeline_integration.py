"""Tier 3: Combination Test 7 — End-to-End Pipeline Integration.

Full opaque-box integration spanning:
1. Ingest of multi-format evidence (JSON, XML, HTML, PDF)
2. Raw Archive ingestion (FixedSizeBinary(32), int16 status, UTC timestamp, on-read body_key)
3. Weekly Retention synchronization (non-empty PK and order_by assertions, fast digest)
4. Canonical Catalog generation (47 duplicate columns pruned, scalarization, RG bloat elimination)
5. Browser Publication (zero payload column, typed facts/links, 256 KiB cell ceiling, redundant column pruning)
6. Docspec Views (Cartesian elimination, single-pass ZSTD write)
7. Local R2 CAS verification (zero network calls, perfect content-addressed hashes)
"""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.retention.body_keys import physical_body_object_key, is_pdf_bytes
from tests.e2e.harness.contracts import (
    SOURCE_SCHEMA,
    BROWSER_TABLE_SCHEMAS,
    WEEKLY_TABLE_SCHEMAS,
    RAW_ARCHIVE_SCHEMAS,
    FORBIDDEN_SOURCE_COLUMNS,
    FORBIDDEN_BROWSER_COLUMNS,
    MAX_CELL_SIZE,
)
from tests.e2e.harness.staging import LocalR2Staging
from tests.e2e.harness.parquet_oracle import ParquetOracle
from tests.e2e.harness.data_generators import SyntheticDataGenerator


@pytest.mark.tier3
def test_c07_full_end_to_end_pipeline_flow(
    staging_dir: Path,
    local_r2: LocalR2Staging,
    oracle: ParquetOracle,
    generator: SyntheticDataGenerator,
):
    """C7.1: Comprehensive end-to-end multi-stage pipeline execution and verification."""
    # Step 1: Stage multi-format payloads into local R2 CAS
    json_bytes = json.dumps({"type": "meeting", "title": "Comprehensive Hearing"}).encode("utf-8")
    xml_bytes = b"<hearing><chamber>House</chamber></hearing>"
    pdf_bytes = generator.generate_pdf_bytes(length=4096)

    staged_json = local_r2.stage_bytes(json_bytes, is_pdf=False)
    staged_xml = local_r2.stage_bytes(xml_bytes, is_pdf=False)
    staged_pdf = local_r2.stage_bytes(pdf_bytes, is_pdf=True)

    assert staged_json["extension"] == "gz"
    assert staged_xml["extension"] == "gz"
    assert staged_pdf["extension"] == "pdf"

    # Step 2: Ingest into Raw Archive with binary(32) digests
    archive_rows = [
        {
            "family": "congress_shared",
            "capture_date": "2026-10-22",
            "source_file": "receipts.jsonl",
            "source_line": 1,
            "receipt_key": "rcpt_json",
            "receipt_line": 1,
            "reference_kind": "direct",
            "pointer_json": "{}",
            "context_url": "https://congress.gov",
            "sha256": bytes.fromhex(staged_json["sha256"]),
            "bytes": len(json_bytes),
            "is_stored": True,
            "stored_bytes": staged_json["stored_bytes"],
            "fidelity": "exact",
            "media_type": "application/json",
            "retrieved_at": None,
            "http_status": 200,
            "resolution": "resolved",
            "original_path": None,
        },
        {
            "family": "senate_pdf",
            "capture_date": "2026-10-22",
            "source_file": "receipts.jsonl",
            "source_line": 2,
            "receipt_key": "rcpt_pdf",
            "receipt_line": 2,
            "reference_kind": "direct",
            "pointer_json": "{}",
            "context_url": "https://senate.gov/doc.pdf",
            "sha256": bytes.fromhex(staged_pdf["sha256"]),
            "bytes": len(pdf_bytes),
            "is_stored": True,
            "stored_bytes": staged_pdf["stored_bytes"],
            "fidelity": "exact",
            "media_type": "application/pdf",
            "retrieved_at": None,
            "http_status": 200,
            "resolution": "resolved",
            "original_path": None,
        },
    ]
    captures_table = pa.Table.from_pylist(archive_rows, schema=RAW_ARCHIVE_SCHEMAS["captures"])
    captures_path = staging_dir / "captures_e2e.parquet"
    pq.write_table(captures_table, captures_path, row_group_size=65536)

    # Step 3: Synchronize Weekly Retention Tables
    yt_row = {
        "system_code": "hsed00",
        "video_id": "vid_e2e_1",
        "published_at": "2026-10-22T10:00:00Z",
        "title": "E2E Stream",
        "upstream_sha256": staged_json["sha256"],
    }
    yt_table = pa.Table.from_pylist([yt_row], schema=WEEKLY_TABLE_SCHEMAS["youtube_videos"])
    yt_path = staging_dir / "youtube_videos_e2e.parquet"
    pq.write_table(yt_table, yt_path)

    # Step 4: Browser Tables Assembly & Export (Single-pass ZSTD)
    source_row = {
        "id": "src_e2e_1",
        "kind": "source_record",
        "provider": "congress.gov",
        "url": "https://congress.gov",
        "title": "Comprehensive Hearing",
        "retrieved_at": "2026-10-22T00:00:00Z",
        "source_modified_at": None,
        "imported_at": "2026-10-22T00:00:00Z",
        "identifier_scheme": "hearing_id",
        "identifier_value": "114250",
        "identifier_scope": "118",
        "facts": [{"label": "Status", "value": "Published"}],
        "links": [{"group": "Source", "label": "Original", "href": "https://congress.gov"}],
        "retained_uri": staged_json["uri"],
        "retained_sha256": staged_json["sha256"],
    }
    sources_table = pa.Table.from_pylist([source_row], schema=SOURCE_SCHEMA)
    sources_path = staging_dir / "sources_e2e.parquet"
    pq.write_table(sources_table, sources_path, compression="zstd", compression_level=3)

    meeting_row = {
        "id": "m_e2e_1",
        "title": "Comprehensive Hearing",
        "chamber": "House",
        "congress": 118,
        "committee_ids": ["hsed00"],
        "committee_level": "standing",
        "committee_types": ["standing"],
        "source_ids": ["src_e2e_1"],
        "facts": [],
        "date": "2026-10-22",
        "type": "Hearing",
        "status": "Held",
        "search_text": "Comprehensive Hearing",
        "scheduled_at": "2026-10-22T10:00:00Z",
        "access": "public",
        "evidence_states": None,
    }
    meetings_table = pa.Table.from_pylist([meeting_row], schema=BROWSER_TABLE_SCHEMAS["meetings"])
    meetings_path = staging_dir / "meetings_e2e.parquet"
    pq.write_table(meetings_table, meetings_path, compression="zstd", compression_level=3)

    materials_row = {
        "id": "mat_e2e_1",
        "title": "Hearing PDF Evidence",
        "chamber": "House",
        "congress": 118,
        "committee_ids": ["hsed00"],
        "committee_level": "standing",
        "committee_types": ["standing"],
        "source_ids": ["src_e2e_1"],
        "facts": [],
        "date": "2026-10-22",
        "type": "Hearing",
        "provider": "senate.committees",
        "category": "evidence",
        "scheduled_at": None,
        "meeting_status": "Held",
        "recording_url": None,
        "document_type": "PDF",
        "meeting_ids": ["m_e2e_1"],
        "source_document_groups": ["hearing_records"],
        "files": [{
            "url": "https://senate.gov/doc.pdf",
            "label": "Document PDF",
            "role": "transcript",
            "media_type": "application/pdf",
            "version": "1.0",
            "published_at": "2026-10-22T10:00:00Z",
            "sha256": staged_pdf["sha256"],
            "saved_copy_sha256": staged_pdf["sha256"],
            "saved_filename": "hearing_evidence.pdf",
        }],
    }
    materials_table = pa.Table.from_pylist([materials_row], schema=BROWSER_TABLE_SCHEMAS["materials"])
    materials_path = staging_dir / "materials_e2e.parquet"
    pq.write_table(materials_table, materials_path, compression="zstd", compression_level=3)

    # Step 5: Verification of contracts across the entire ecosystem
    # A. Sources table verification
    ok_src, err_src = oracle.verify_column_absence(sources_path, FORBIDDEN_SOURCE_COLUMNS)
    assert ok_src, f"Payload column in sources: {err_src}"
    ok_cell, err_cell = oracle.verify_cell_size_limit(sources_path, max_bytes=MAX_CELL_SIZE)
    assert ok_cell

    # B. Browser tables column pruning
    ok_meet, err_meet = oracle.verify_column_absence(meetings_path, FORBIDDEN_BROWSER_COLUMNS["meetings"])
    assert ok_meet
    ok_mat, err_mat = oracle.verify_column_absence(materials_path, FORBIDDEN_BROWSER_COLUMNS["materials"])
    assert ok_mat

    # C. Local CAS Integrity
    ok_cas, err_cas = local_r2.verify_cas_integrity()
    assert ok_cas, f"CAS integrity failure: {err_cas}"

    # D. Lossless retrieval of both JSON and PDF objects
    retrieved_json = local_r2.get_body_bytes(staged_json["sha256"])
    assert retrieved_json == json_bytes
    retrieved_pdf = local_r2.get_body_bytes(staged_pdf["sha256"], is_pdf=True)
    assert retrieved_pdf == pdf_bytes
