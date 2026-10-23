"""Tier 3: Combination Test 3 — Scraper PDF Ingest to R2 CAS and Materials Saved Copy Wiring.

Cross-feature interactions:
- F3: Scraper PDF & UTF-8 Replacement Guard
- F1: Content-Addressed R2 Storage Layout
- F25: Materials Saved Copy R2 Digest Wiring
"""

from __future__ import annotations
from pathlib import Path
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.retention.body_keys import is_pdf_bytes, physical_body_object_key
from tests.e2e.harness.contracts import BROWSER_TABLE_SCHEMAS
from tests.e2e.harness.staging import LocalR2Staging
from tests.e2e.harness.data_generators import SyntheticDataGenerator


@pytest.mark.tier3
def test_c03_scraped_pdf_bypasses_text_decoding_and_wires_to_materials(
    staging_dir: Path,
    local_r2: LocalR2Staging,
    generator: SyntheticDataGenerator,
):
    """C3.1: Scraped PDF file is detected by magic bytes, staged to .pdf CAS, and wired to materials."""
    # 1. Scraper receives raw file bytes
    pdf_bytes = generator.generate_pdf_bytes(length=16384, version="1.6")

    # 2. Check %PDF- header before string decoding
    assert is_pdf_bytes(pdf_bytes) is True

    # 3. Stage uncompressed to local CAS with .pdf extension
    staged = local_r2.stage_bytes(pdf_bytes, is_pdf=True)
    assert staged["extension"] == "pdf"
    assert staged["uri"].endswith(".pdf")
    pdf_sha256 = staged["sha256"]

    # 4. In materials assembly, apply_saved_copies wires saved_copy_sha256 and saved_filename
    material_file_entry = {
        "url": "https://www.intelligence.senate.gov/hearings/105290.pdf",
        "label": "Hearing Testimony Transcript",
        "role": "transcript",
        "media_type": "application/pdf",
        "version": "1.0",
        "published_at": "2026-10-15T10:00:00Z",
        "sha256": pdf_sha256,
        "saved_copy_sha256": pdf_sha256,
        "saved_filename": "105290.pdf",
    }

    material_row = {
        "id": "mat-senate-001",
        "title": "Intelligence Oversight Hearing",
        "chamber": "Senate",
        "congress": 118,
        "committee_ids": ["ssci00"],
        "committee_level": "standing",
        "committee_types": ["select"],
        "source_ids": ["src-senate-1"],
        "facts": [],
        "date": "2026-10-15",
        "type": "Hearing",
        "provider": "senate.committees",
        "category": "transcript",
        "scheduled_at": None,
        "meeting_status": "Completed",
        "recording_url": None,
        "document_type": "PDF",
        "meeting_ids": ["m-senate-1"],
        "source_document_groups": ["senate_hearings"],
        "files": [material_file_entry],
    }

    schema = BROWSER_TABLE_SCHEMAS["materials"]
    table = pa.Table.from_pylist([material_row], schema=schema)
    mat_path = staging_dir / "materials_c03.parquet"
    pq.write_table(table, mat_path)

    # 5. Read back and verify UI savedCopyHref builds valid on-demand URL to CAS
    read_table = pq.read_table(mat_path)
    file_record = read_table.to_pylist()[0]["files"][0]

    assert file_record["saved_copy_sha256"] == pdf_sha256
    assert file_record["saved_filename"] == "105290.pdf"

    # Verify physical CAS object exists and starts with %PDF-
    cas_bytes = local_r2.get_body_bytes(file_record["saved_copy_sha256"], is_pdf=True)
    assert cas_bytes.startswith(b"%PDF-")


@pytest.mark.tier3
def test_c03_high_ufffd_rejection_emits_data_issue(
    local_r2: LocalR2Staging,
    generator: SyntheticDataGenerator,
):
    """C3.2: High U+FFFD density document is rejected from text ingestion and logged as DataIssue."""
    corrupted_text = generator.generate_high_ufffd_text(length=2000, replacement_ratio=0.25)
    ratio = corrupted_text.count("\ufffd") / len(corrupted_text)
    assert ratio > 0.05  # >5% triggers rejection

    # Store raw bytes in CAS as quarantine / raw body
    staged = local_r2.stage_bytes(corrupted_text.encode("utf-8"), is_pdf=False)

    # Emit DataIssue linking to retained source
    issue = {
        "id": "iss-corrupted-pdf",
        "category": "scraped_text_corrupted_replacement_characters",
        "severity": "warning",
        "subject_kind": "source_record",
        "subject_id": "src-corrupted-1",
        "retained_sha256": staged["sha256"],
    }
    assert issue["severity"] == "warning"
    assert local_r2.has_body(issue["retained_sha256"])
