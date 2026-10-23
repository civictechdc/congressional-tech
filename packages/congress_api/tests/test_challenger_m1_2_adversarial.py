"""Adversarial stress-testing suite authored by Challenger 2 (ct-8v02).

Empirically tests and reproduces findings:
1. Cell Limit Bypass: Nested structs (facts, links) and lists (roles, committee_ids) exceeding 256 KiB bypass MAX_CELL_SIZE guard.
2. Fact Label Mapping Bug: Payload 'type' maps to 'Type' instead of 'Type at the source' (breaking frontend contract & test_assembled_roundtable_keeps_native_hearing_as_source_evidence).
3. Appearance-Linked Material Meeting ID Drop: Material link to appearance fails to resolve meeting_id from subjects when not in query_rows meeting_id.
4. Schema Verification: Zero payload column in SOURCE_SCHEMA.
5. CAS Path Generation & Integrity: Verified content-addressed layout for PDF and gzip.
"""

import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from committee_explorer.parquet import (
    MAX_CELL_SIZE,
    SOURCE_SCHEMA,
    TABLE_SCHEMAS,
    _source_facts,
    _source_row,
    _write_sources,
    _write_table,
    write_tables,
)


def test_sources_parquet_zero_payload_column():
    """Verify SOURCE_SCHEMA contains ZERO payload column."""
    assert "payload" not in SOURCE_SCHEMA.names
    assert "identifier" not in SOURCE_SCHEMA.names
    assert "title" in SOURCE_SCHEMA.names
    assert "facts" in SOURCE_SCHEMA.names
    assert "links" in SOURCE_SCHEMA.names
    assert "retained_sha256" in SOURCE_SCHEMA.names
    assert "retained_uri" in SOURCE_SCHEMA.names


def test_cas_path_generation_pdf_and_gzip():
    """Verify CAS layout bodies/sha256/<xx>/<sha256>.{gz,pdf} and streamable PDF."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        stage = Path(tmp_dir)
        pdf_bytes = b"%PDF-1.7 streamable binary test"
        json_obj = {"title": "Hearing Title", "status": "held"}

        pdf_source = {"id": "src-pdf", "payload": pdf_bytes}
        json_source = {"id": "src-json", "payload": json_obj}

        row_pdf = _source_row(pdf_source, stage=stage)
        row_json = _source_row(json_source, stage=stage)

        pdf_sha = hashlib.sha256(pdf_bytes).hexdigest()
        expected_pdf_uri = f"bodies/sha256/{pdf_sha[:2]}/{pdf_sha}.pdf"
        assert row_pdf["retained_uri"] == expected_pdf_uri
        assert row_pdf["retained_sha256"] == pdf_sha
        assert (stage / expected_pdf_uri).exists()
        assert (stage / expected_pdf_uri).read_bytes() == pdf_bytes

        json_bytes = json.dumps(json_obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        json_sha = hashlib.sha256(json_bytes).hexdigest()
        expected_json_uri = f"bodies/sha256/{json_sha[:2]}/{json_sha}.gz"
        assert row_json["retained_uri"] == expected_json_uri
        assert row_json["retained_sha256"] == json_sha
        assert (stage / expected_json_uri).exists()
        assert gzip.decompress((stage / expected_json_uri).read_bytes()) == json_bytes


def test_nested_cells_exceeding_256_kib_bypass_guard():
    """Verify recursive cell size guard rejects nested strings in facts/links exceeding MAX_CELL_SIZE."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        stage = Path(tmp_dir)
        row_oversized_fact = {k: None for k in SOURCE_SCHEMA.names}
        row_oversized_fact["id"] = "src-oversized-fact"
        # Nested string of 300,000 bytes (> 262,144 bytes)
        row_oversized_fact["facts"] = [{"label": "Giant Note", "value": "X" * 300_000}]

        with pytest.raises(ValueError, match="exceeds 256 KiB limit"):
            _write_sources([row_oversized_fact], stage)


def test_fact_mapping_type_at_the_source_bug():
    """Verify 'type' maps to 'Type at the source' per frontend contract."""
    payload = {"type": "Hearing", "title": "Prediction Markets"}
    facts = _source_facts(payload, {})
    fact_dict = {f["label"]: f["value"] for f in facts}
    assert fact_dict.get("Type at the source") == "Hearing"


def test_material_link_to_appearance_drops_meeting_id_bug():
    """Verify material_link correctly resolves meeting_id from subjects when linked to appearance."""
    def ref(kind, id): return dict(kind=kind, id=id)
    records = [
        dict(kind="meeting", id="meeting"),
        dict(kind="appearance", id="witness", meeting=ref("meeting", "meeting")),
    ]
    queries = [
        dict(id="meeting", kind="meeting", title="Meeting"),
        dict(id="witness", kind="appearance", title="Witness"),  # Note: no meeting_id in query row
    ]
    records += [
        dict(kind="material", id="witness-file"),
        dict(kind="material_version", id="witness-file-v", material=ref("material", "witness-file")),
        dict(kind="material_link", id="witness-file-link", material=ref("material", "witness-file"), subject=ref("appearance", "witness")),
    ]
    queries.append(dict(kind="material", id="witness-file", type="document", title="Witness File"))

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        write_tables(iter(records), [], queries, tmp_path, lambda *args, **kwargs: None)
        materials = pq.read_table(tmp_path / "materials.parquet").to_pylist()
        witness_mat = next(r for r in materials if r["id"] == "witness-file")
        
        assert "meeting_id" not in witness_mat
        assert witness_mat["meeting_ids"] == ["meeting"]
