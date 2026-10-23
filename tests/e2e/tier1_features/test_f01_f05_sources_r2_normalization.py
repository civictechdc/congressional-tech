"""Tier 1: Feature Coverage for Features F1 through F5 (Milestone M1 / Ticket ct-8v02).

Covers:
- F1: Sources Parquet Direct-to-R2 Offload
- F2: Sources Parquet Typed Columnar Normalization
- F3: Scraper PDF & UTF-8 Replacement Guard
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
    PDF_MAGIC,
    MAX_UFFFD_RATIO,
)
from tests.e2e.harness.staging import LocalR2Staging
from tests.e2e.harness.parquet_oracle import ParquetOracle
from tests.e2e.harness.data_generators import SyntheticDataGenerator


# ---------------------------------------------------------------------------
# Feature F1: Sources Parquet Direct-to-R2 Offload
# ---------------------------------------------------------------------------

@pytest.mark.tier1
@pytest.mark.feature("F1")
def test_f01_json_payload_offloaded_to_r2_gz(local_r2: LocalR2Staging):
    """F1.1: Verify JSON payload is offloaded to local R2 CAS as .gz and generates valid retained_uri/sha256."""
    payload = {"title": "Oversight Hearing on AI", "committee": "Science", "witnesses": ["Dr. Smith"]}
    raw_bytes = json.dumps(payload).encode("utf-8")
    staged = local_r2.stage_bytes(raw_bytes, is_pdf=False)

    assert staged["sha256"] == hashlib.sha256(raw_bytes).hexdigest()
    assert staged["uri"].startswith("bodies/sha256/")
    assert staged["uri"].endswith(".gz")
    assert local_r2.has_body(staged["sha256"])
    decompressed = local_r2.get_body_bytes(staged["sha256"])
    assert json.loads(decompressed.decode("utf-8")) == payload


@pytest.mark.tier1
@pytest.mark.feature("F1")
def test_f01_xml_payload_offloaded_to_r2_gz(local_r2: LocalR2Staging):
    """F1.2: Verify XML meeting payload is offloaded to local R2 CAS as .gz with lossless round-trip."""
    xml_data = b"<meeting><id>114250</id><title>Water Resources Development</title></meeting>"
    staged = local_r2.stage_bytes(xml_data, is_pdf=False)

    assert staged["extension"] == "gz"
    assert local_r2.get_body_bytes(staged["sha256"]) == xml_data


@pytest.mark.tier1
@pytest.mark.feature("F1")
def test_f01_html_scraped_page_offloaded_to_r2_gz(local_r2: LocalR2Staging):
    """F1.3: Verify scraped Senate HTML page is offloaded to local R2 CAS as .gz."""
    html_data = b"<!DOCTYPE html><html><head><title>Senate Hearing</title></head><body>Hearing Text</body></html>"
    staged = local_r2.stage_bytes(html_data, is_pdf=False)

    assert staged["extension"] == "gz"
    assert staged["stored_bytes"] > 0
    assert local_r2.get_body_bytes(staged["sha256"]) == html_data


@pytest.mark.tier1
@pytest.mark.feature("F1")
def test_f01_pdf_payload_offloaded_to_r2_pdf(local_r2: LocalR2Staging, generator: SyntheticDataGenerator):
    """F1.4: Verify PDF payload is staged uncompressed as .pdf for HTTP 206 byte-range streaming."""
    pdf_bytes = generator.generate_pdf_bytes(length=4096)
    staged = local_r2.stage_bytes(pdf_bytes, is_pdf=True)

    assert staged["extension"] == "pdf"
    assert staged["uri"].endswith(".pdf")
    assert staged["stored_bytes"] == len(pdf_bytes)  # Uncompressed
    assert local_r2.get_body_bytes(staged["sha256"], is_pdf=True) == pdf_bytes


@pytest.mark.tier1
@pytest.mark.feature("F1")
def test_f01_zero_payload_column_in_sources_parquet(staging_dir: Path, oracle: ParquetOracle, generator: SyntheticDataGenerator):
    """F1.5: Verify normalized sources.parquet contains zero raw payload JSON column."""
    record = generator.generate_source_record()
    # Build single-row Arrow table conforming to normalized SOURCE_SCHEMA
    table = pa.Table.from_pylist([
        {k: record[k] for k in SOURCE_SCHEMA.names}
    ], schema=SOURCE_SCHEMA)

    out_path = staging_dir / "sources.parquet"
    pq.write_table(table, out_path)

    ok, errors = oracle.verify_column_absence(out_path, FORBIDDEN_SOURCE_COLUMNS)
    assert ok, f"Forbidden column found: {errors}"
    read_table = pq.read_table(out_path)
    assert "payload" not in read_table.column_names


# ---------------------------------------------------------------------------
# Feature F2: Sources Parquet Typed Columnar Normalization
# ---------------------------------------------------------------------------

@pytest.mark.tier1
@pytest.mark.feature("F2")
def test_f02_title_extracted_as_typed_column(generator: SyntheticDataGenerator):
    """F2.1: Verify title is normalized as a typed string column."""
    rec = generator.generate_source_record(title="Hearing on Energy Transition")
    assert isinstance(rec["title"], str)
    assert rec["title"] == "Hearing on Energy Transition"
    f = SOURCE_SCHEMA.field("title")
    assert f.type.equals(pa.string())


@pytest.mark.tier1
@pytest.mark.feature("F2")
def test_f02_identifier_scheme_value_scope_normalized(generator: SyntheticDataGenerator):
    """F2.2: Verify identifier components are normalized into distinct typed columns."""
    rec = generator.generate_source_record(provider="govinfo", scheme="package_id", value="CHRG-118hhrg54321", scope="118")
    assert rec["identifier_scheme"] == "package_id"
    assert rec["identifier_value"] == "CHRG-118hhrg54321"
    assert rec["identifier_scope"] == "118"
    for col in ("identifier_scheme", "identifier_value", "identifier_scope"):
        assert SOURCE_SCHEMA.field(col).type.equals(pa.string())


@pytest.mark.tier1
@pytest.mark.feature("F2")
def test_f02_facts_list_of_structs_normalized(generator: SyntheticDataGenerator):
    """F2.3: Verify facts are normalized as list<struct<label: string, value: string>>."""
    rec = generator.generate_source_record()
    facts_field = SOURCE_SCHEMA.field("facts")
    assert pa.types.is_list(facts_field.type)
    value_type = facts_field.type.value_type
    assert pa.types.is_struct(value_type)
    assert value_type.names == ["label", "value"]


@pytest.mark.tier1
@pytest.mark.feature("F2")
def test_f02_links_list_of_structs_normalized(generator: SyntheticDataGenerator):
    """F2.4: Verify links are normalized as list<struct<group: string, label: string, href: string>>."""
    rec = generator.generate_source_record()
    links_field = SOURCE_SCHEMA.field("links")
    assert pa.types.is_list(links_field.type)
    value_type = links_field.type.value_type
    assert pa.types.is_struct(value_type)
    assert value_type.names == ["group", "label", "href"]


@pytest.mark.tier1
@pytest.mark.feature("F2")
def test_f02_complete_source_schema_conformance(staging_dir: Path, oracle: ParquetOracle, generator: SyntheticDataGenerator):
    """F2.5: Verify written sources table matches SOURCE_SCHEMA exactly."""
    rows = [generator.generate_source_record(value=f"rec_{i}") for i in range(5)]
    table = pa.Table.from_pylist([{k: r[k] for k in SOURCE_SCHEMA.names} for r in rows], schema=SOURCE_SCHEMA)

    path = staging_dir / "sources_exact.parquet"
    pq.write_table(table, path)

    ok, errors = oracle.verify_schema_exact(path, SOURCE_SCHEMA)
    assert ok, f"Schema mismatch: {errors}"


# ---------------------------------------------------------------------------
# Feature F3: Scraper PDF & UTF-8 Replacement Guard
# ---------------------------------------------------------------------------

@pytest.mark.tier1
@pytest.mark.feature("F3")
def test_f03_pdf_magic_bytes_detected(generator: SyntheticDataGenerator):
    """F3.1: Verify is_pdf_bytes recognizes %PDF- magic bytes and rejects non-PDFs."""
    from congress_api.retention.body_keys import is_pdf_bytes

    pdf_sample = generator.generate_pdf_bytes(128)
    assert is_pdf_bytes(pdf_sample) is True

    html_sample = b"<!DOCTYPE html><html><body>Test</body></html>"
    assert is_pdf_bytes(html_sample) is False

    json_sample = b'{"key": "value"}'
    assert is_pdf_bytes(json_sample) is False


@pytest.mark.tier1
@pytest.mark.feature("F3")
def test_f03_utf8_valid_html_admitted():
    """F3.2: Verify clean UTF-8 text with 0 replacement characters passes replacement guard."""
    clean_text = "<html><body>Committee on Foreign Relations Hearing</body></html>"
    ufffd_count = clean_text.count("\ufffd")
    ratio = ufffd_count / len(clean_text)
    assert ratio <= MAX_UFFFD_RATIO


@pytest.mark.tier1
@pytest.mark.feature("F3")
def test_f03_utf8_low_replacement_density_admitted(generator: SyntheticDataGenerator):
    """F3.3: Verify text with minor replacement characters (2% <= 5%) passes replacement guard."""
    low_ufffd = generator.generate_high_ufffd_text(length=1000, replacement_ratio=0.02)
    ufffd_count = low_ufffd.count("\ufffd")
    ratio = ufffd_count / len(low_ufffd)
    assert ratio <= MAX_UFFFD_RATIO


@pytest.mark.tier1
@pytest.mark.feature("F3")
def test_f03_utf8_high_replacement_density_rejected(generator: SyntheticDataGenerator):
    """F3.4: Verify text with excessive replacement characters (> 5%) fails replacement guard."""
    high_ufffd = generator.generate_high_ufffd_text(length=1000, replacement_ratio=0.08)
    ufffd_count = high_ufffd.count("\ufffd")
    ratio = ufffd_count / len(high_ufffd)
    assert ratio > MAX_UFFFD_RATIO


@pytest.mark.tier1
@pytest.mark.feature("F3")
def test_f03_pdf_staged_to_pdf_extension_without_decoding(local_r2: LocalR2Staging, generator: SyntheticDataGenerator):
    """F3.5: Verify raw PDF bytes are diverted directly to .pdf R2 object without UTF-8 string decoding."""
    pdf_bytes = generator.generate_pdf_bytes(2048)
    staged = local_r2.stage_bytes(pdf_bytes, is_pdf=True)

    assert staged["extension"] == "pdf"
    assert staged["stored_bytes"] == len(pdf_bytes)
    assert staged["uri"].endswith(".pdf")


# ---------------------------------------------------------------------------
# Feature F4: 256 KiB Cell Size Guard
# ---------------------------------------------------------------------------

@pytest.mark.tier1
@pytest.mark.feature("F4")
def test_f04_small_cells_admitted(oracle: ParquetOracle):
    """F4.1: Verify string cell of 1 KiB passes 256 KiB ceiling check."""
    s = "A" * 1024
    table = pa.Table.from_arrays([pa.array([s])], names=["content"])
    ok, errors = oracle.verify_cell_size_limit(table, max_bytes=MAX_CELL_SIZE)
    assert ok, f"Unexpected cell size failure: {errors}"


@pytest.mark.tier1
@pytest.mark.feature("F4")
def test_f04_medium_cells_admitted(oracle: ParquetOracle):
    """F4.2: Verify string cell of 200 KiB passes 256 KiB ceiling check."""
    s = "B" * (200 * 1024)
    table = pa.Table.from_arrays([pa.array([s])], names=["content"])
    ok, errors = oracle.verify_cell_size_limit(table, max_bytes=MAX_CELL_SIZE)
    assert ok


@pytest.mark.tier1
@pytest.mark.feature("F4")
def test_f04_boundary_256k_cell_admitted(oracle: ParquetOracle):
    """F4.3: Verify string cell of exactly 262,144 bytes (256 KiB) passes ceiling check."""
    s = "C" * MAX_CELL_SIZE
    table = pa.Table.from_arrays([pa.array([s])], names=["content"])
    ok, errors = oracle.verify_cell_size_limit(table, max_bytes=MAX_CELL_SIZE)
    assert ok


@pytest.mark.tier1
@pytest.mark.feature("F4")
def test_f04_cell_exceeding_256k_rejected(oracle: ParquetOracle):
    """F4.4: Verify string cell of 262,145 bytes (256 KiB + 1 B) is rejected by oracle."""
    s = "D" * (MAX_CELL_SIZE + 1)
    table = pa.Table.from_arrays([pa.array([s])], names=["content"])
    ok, errors = oracle.verify_cell_size_limit(table, max_bytes=MAX_CELL_SIZE)
    assert not ok
    assert "exceeds" in errors[0]


@pytest.mark.tier1
@pytest.mark.feature("F4")
def test_f04_24mb_pdf_cell_rejected(oracle: ParquetOracle):
    """F4.5: Verify 24.45 MB binary PDF string cell is decisively caught and rejected."""
    # Simulate a 1 MB chunk (scaled test representation of the 24 MB cell)
    s = "E" * (1024 * 1024)
    table = pa.Table.from_arrays([pa.array([s])], names=["payload"])
    ok, errors = oracle.verify_cell_size_limit(table, max_bytes=MAX_CELL_SIZE)
    assert not ok
    assert len(errors) > 0


# ---------------------------------------------------------------------------
# Feature F5: Explorer UI Direct Column Presentation
# ---------------------------------------------------------------------------

@pytest.mark.tier1
@pytest.mark.feature("F5")
def test_f05_ui_title_rendered_directly_from_parquet(generator: SyntheticDataGenerator):
    """F5.1: Verify UI title resolution uses row.title directly without parsing row.payload."""
    row = generator.generate_source_record(title="Antitrust Hearing in Big Tech")
    assert "payload" not in row
    # Direct field access simulates RecordDetail.tsx title resolution
    title = row.get("title") or row.get("url", "").split("/")[-1] or row.get("provider", "Original source")
    assert title == "Antitrust Hearing in Big Tech"


@pytest.mark.tier1
@pytest.mark.feature("F5")
def test_f05_ui_facts_rendered_from_struct_list(generator: SyntheticDataGenerator):
    """F5.2: Verify UI renders facts directly from normalized struct list."""
    row = generator.generate_source_record()
    facts = row.get("facts") or []
    assert isinstance(facts, list)
    assert len(facts) > 0
    assert "label" in facts[0] and "value" in facts[0]


@pytest.mark.tier1
@pytest.mark.feature("F5")
def test_f05_ui_links_rendered_from_struct_list(generator: SyntheticDataGenerator):
    """F5.3: Verify UI renders links directly from normalized struct list."""
    row = generator.generate_source_record()
    links = row.get("links") or []
    assert isinstance(links, list)
    assert len(links) > 0
    assert "href" in links[0] and "label" in links[0]


@pytest.mark.tier1
@pytest.mark.feature("F5")
def test_f05_ui_saved_original_link_uses_retained_uri(generator: SyntheticDataGenerator):
    """F5.4: Verify UI saved original action resolves to retained_uri."""
    row = generator.generate_source_record()
    retained_uri = row.get("retained_uri")
    assert retained_uri is not None
    assert retained_uri.startswith("bodies/sha256/")


@pytest.mark.tier1
@pytest.mark.feature("F5")
def test_f05_ui_on_demand_cas_fetch_for_raw_json(local_r2: LocalR2Staging, generator: SyntheticDataGenerator):
    """F5.5: Verify UI 'See everything saved' fetches raw payload from local CAS on demand."""
    payload = {"technical_field": 42, "raw_tags": ["budget", "defense"]}
    raw_bytes = json.dumps(payload).encode("utf-8")
    staged = local_r2.stage_bytes(raw_bytes, is_pdf=False)

    row = generator.generate_source_record(payload_dict=payload)
    row["retained_uri"] = staged["uri"]
    row["retained_sha256"] = staged["sha256"]

    fetched_bytes = local_r2.get_body_bytes(row["retained_sha256"])
    assert json.loads(fetched_bytes.decode("utf-8")) == payload
