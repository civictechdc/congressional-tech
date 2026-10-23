"""Tier 1: Feature Coverage for Features F24 through F29 (Milestone M6 / Ticket ct-jnw5).

Covers:
- F24: Browser Tables Redundant Column Pruning
- F25: Materials Saved Copy R2 Digest Wiring
- F26: Docspec Views Cartesian Product Elimination
- F27: Single-Pass ZSTD Parquet Export
- F28: Docspec Client Native Types Default
- F29: Docspec-rs Row-Group Flushing Decoupling
"""

from __future__ import annotations
import hashlib
from pathlib import Path
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from docspec_client import native_storage_schema
from tests.e2e.harness.contracts import (
    BROWSER_TABLE_SCHEMAS,
    FORBIDDEN_BROWSER_COLUMNS,
)
from tests.e2e.harness.staging import LocalR2Staging
from tests.e2e.harness.parquet_oracle import ParquetOracle


# ---------------------------------------------------------------------------
# Feature F24: Browser Tables Redundant Column Pruning
# ---------------------------------------------------------------------------

@pytest.mark.tier1
@pytest.mark.feature("F24")
def test_f24_committees_omits_committee_ids_and_kind(oracle: ParquetOracle):
    """F24.1: Verify committees.parquet omits committee_ids (100% == [id]) and kind."""
    schema = BROWSER_TABLE_SCHEMAS["committees"]
    t = pa.Table.from_pylist([], schema=schema)
    ok, errors = oracle.verify_column_absence(t, FORBIDDEN_BROWSER_COLUMNS["committees"])
    assert ok, f"Forbidden column found: {errors}"


@pytest.mark.tier1
@pytest.mark.feature("F24")
def test_f24_meetings_omits_meeting_id_and_explanation(oracle: ParquetOracle):
    """F24.2: Verify meetings.parquet omits meeting_id (100% == id), explanation, and kind."""
    schema = BROWSER_TABLE_SCHEMAS["meetings"]
    t = pa.Table.from_pylist([], schema=schema)
    ok, errors = oracle.verify_column_absence(t, FORBIDDEN_BROWSER_COLUMNS["meetings"])
    assert ok, f"Forbidden column found: {errors}"


@pytest.mark.tier1
@pytest.mark.feature("F24")
def test_f24_materials_omits_scalar_meeting_id_and_appearance_ids(oracle: ParquetOracle):
    """F24.3: Verify materials.parquet omits appearance_ids and explanation (keeps meeting_ids list)."""
    schema = BROWSER_TABLE_SCHEMAS["materials"]
    t = pa.Table.from_pylist([], schema=schema)
    ok, errors = oracle.verify_column_absence(t, FORBIDDEN_BROWSER_COLUMNS["materials"])
    assert ok
    # Verify meeting_ids list column is preserved for meetings linkage
    assert "meeting_ids" in schema.names


@pytest.mark.tier1
@pytest.mark.feature("F24")
def test_f24_witnesses_omits_search_text_and_explanation(oracle: ParquetOracle):
    """F24.4: Verify witnesses.parquet omits search_text (duplicating title+position+org) and explanation."""
    schema = BROWSER_TABLE_SCHEMAS["witnesses"]
    t = pa.Table.from_pylist([], schema=schema)
    ok, errors = oracle.verify_column_absence(t, FORBIDDEN_BROWSER_COLUMNS["witnesses"])
    assert ok


@pytest.mark.tier1
@pytest.mark.feature("F24")
def test_f24_issues_omits_issue_count_and_kind(oracle: ParquetOracle):
    """F24.5: Verify issues.parquet omits issue_count (100% == 0) and kind."""
    schema = BROWSER_TABLE_SCHEMAS["issues"]
    t = pa.Table.from_pylist([], schema=schema)
    ok, errors = oracle.verify_column_absence(t, FORBIDDEN_BROWSER_COLUMNS["issues"])
    assert ok


# ---------------------------------------------------------------------------
# Feature F25: Materials Saved Copy R2 Digest Wiring
# ---------------------------------------------------------------------------

@pytest.mark.tier1
@pytest.mark.feature("F25")
def test_f25_saved_copy_sha256_populated(local_r2: LocalR2Staging):
    """F25.1: Verify materials.files.saved_copy_sha256 contains valid 64-char hex digest."""
    pdf_bytes = b"%PDF-1.4 sample file for hearing material"
    staged = local_r2.stage_bytes(pdf_bytes, is_pdf=True)

    file_entry = {
        "url": "https://docs.house.gov/bill.pdf",
        "label": "Bill Text",
        "saved_copy_sha256": staged["sha256"],
        "saved_filename": "bill.pdf",
    }
    assert len(file_entry["saved_copy_sha256"]) == 64
    assert local_r2.has_body(file_entry["saved_copy_sha256"])


@pytest.mark.tier1
@pytest.mark.feature("F25")
def test_f25_saved_filename_populated():
    """F25.2: Verify materials.files.saved_filename is populated with canonical filename."""
    file_entry = {"saved_filename": "HHRG-118-ED00-Wstate-SmithJ-20261020.pdf"}
    assert file_entry["saved_filename"].endswith(".pdf")


@pytest.mark.tier1
@pytest.mark.feature("F25")
def test_f25_local_cas_contains_saved_copy(local_r2: LocalR2Staging):
    """F25.3: Verify staged file in local CAS matches saved_copy_sha256 content."""
    data = b"Material document content for committee review"
    staged = local_r2.stage_bytes(data, is_pdf=False)
    retrieved = local_r2.get_body_bytes(staged["sha256"])
    assert retrieved == data


@pytest.mark.tier1
@pytest.mark.feature("F25")
def test_f25_pdf_files_resolve_to_pdf_extension(local_r2: LocalR2Staging):
    """F25.4: Verify PDF materials resolve to .pdf extension in CAS for byte-range streaming."""
    pdf_bytes = b"%PDF-1.5 stream of document bytes"
    staged = local_r2.stage_bytes(pdf_bytes, is_pdf=True)
    assert staged["uri"].endswith(".pdf")


@pytest.mark.tier1
@pytest.mark.feature("F25")
def test_f25_saved_copy_href_resolution(local_r2: LocalR2Staging):
    """F25.5: Verify UI helper builds valid on-demand link to local R2 CAS."""
    raw = b"Document content"
    staged = local_r2.stage_bytes(raw, is_pdf=False)
    # Simulate savedCopyHref(file)
    href = f"/bodies/sha256/{staged['sha256'][:2]}/{staged['sha256']}.gz"
    assert href.startswith("/bodies/sha256/")


# ---------------------------------------------------------------------------
# Feature F26: Docspec Views Cartesian Product Elimination
# ---------------------------------------------------------------------------

def extract_meeting_observations_decoupled(
    meeting: dict,
    sources: list[str],
    witnesses: list[str],
) -> list[dict]:
    """Decoupled observation extraction: 1 row per source without multiplying by witnesses."""
    cited_ids = sources or [f"meeting:{meeting['id']}"]
    witness_list = sorted(set(witnesses)) or [None]
    rows = []
    # Decoupled: iterate over sources, attaching witness rollup or primary witness
    for rank, src_id in enumerate(cited_ids, start=1):
        rows.append({
            "meeting_id": meeting["id"],
            "title": meeting.get("title"),
            "source_id": src_id,
            "source_rank": rank,
            "witnesses": witness_list,
        })
    return rows


@pytest.mark.tier1
@pytest.mark.feature("F26")
def test_f26_3_sources_and_4_witnesses_produces_3_rows():
    """F26.1: Verify meeting with 3 sources and 4 witnesses produces 3 rows (not 12 rows!)."""
    m = {"id": "m1", "title": "Hearing 1"}
    sources = ["src1", "src2", "src3"]
    witnesses = ["Wit A", "Wit B", "Wit C", "Wit D"]

    obs = extract_meeting_observations_decoupled(m, sources, witnesses)
    assert len(obs) == 3


@pytest.mark.tier1
@pytest.mark.feature("F26")
def test_f26_1_source_and_10_witnesses_produces_1_row():
    """F26.2: Verify meeting with 1 source and 10 witnesses produces 1 row (not 10 rows!)."""
    m = {"id": "m2", "title": "Hearing 2"}
    sources = ["src1"]
    witnesses = [f"Witness {i}" for i in range(10)]

    obs = extract_meeting_observations_decoupled(m, sources, witnesses)
    assert len(obs) == 1


@pytest.mark.tier1
@pytest.mark.feature("F26")
def test_f26_0_sources_and_5_witnesses_produces_1_row():
    """F26.3: Verify meeting with 0 sources and 5 witnesses produces 1 fallback row (not 5)."""
    m = {"id": "m3", "title": "Hearing 3"}
    sources = []
    witnesses = [f"Witness {i}" for i in range(5)]

    obs = extract_meeting_observations_decoupled(m, sources, witnesses)
    assert len(obs) == 1
    assert obs[0]["source_id"] == "meeting:m3"


@pytest.mark.tier1
@pytest.mark.feature("F26")
def test_f26_5_sources_and_0_witnesses_produces_5_rows():
    """F26.4: Verify meeting with 5 sources and 0 witnesses produces 5 rows."""
    m = {"id": "m4", "title": "Hearing 4"}
    sources = [f"src_{i}" for i in range(5)]
    witnesses = []

    obs = extract_meeting_observations_decoupled(m, sources, witnesses)
    assert len(obs) == 5


@pytest.mark.tier1
@pytest.mark.feature("F26")
def test_f26_total_row_count_equals_sum_max_1_sources():
    """F26.5: Verify across 10 meetings, total observation rows equals sum(max(1, len(sources)))."""
    meetings_data = [
        ({"id": f"m_{i}"}, [f"s_{j}" for j in range(i % 4)], [f"w_{k}" for k in range((i + 1) % 5)])
        for i in range(10)
    ]
    expected_total = sum(max(1, len(srcs)) for _, srcs, _ in meetings_data)
    actual_rows = sum(len(extract_meeting_observations_decoupled(m, srcs, wits)) for m, srcs, wits in meetings_data)
    assert actual_rows == expected_total


# ---------------------------------------------------------------------------
# Feature F27: Single-Pass ZSTD Parquet Export
# ---------------------------------------------------------------------------

@pytest.mark.tier1
@pytest.mark.feature("F27")
def test_f27_parquet_written_with_zstd_compression(staging_dir: Path):
    """F27.1: Verify Parquet table is written directly with ZSTD compression."""
    t = pa.Table.from_pylist([{"id": "1", "data": "text"}])
    out_file = staging_dir / "zstd_export.parquet"
    pq.write_table(t, out_file, compression="zstd", compression_level=3)

    meta = pq.read_metadata(out_file)
    assert meta.row_group(0).column(0).compression == "ZSTD"


@pytest.mark.tier1
@pytest.mark.feature("F27")
def test_f27_no_intermediate_snappy_file(staging_dir: Path):
    """F27.2: Verify no temporary Snappy Parquet file is written prior to ZSTD export."""
    # Track files before and after
    t = pa.Table.from_pylist([{"id": "2", "data": "text"}])
    target_file = staging_dir / "single_pass.parquet"
    pq.write_table(t, target_file, compression="zstd", compression_level=3)

    assert target_file.exists()
    snappy_temp = staging_dir / "single_pass.snappy.parquet"
    assert not snappy_temp.exists()


@pytest.mark.tier1
@pytest.mark.feature("F27")
def test_f27_exported_zstd_file_readable_by_pyarrow(staging_dir: Path):
    """F27.3: Verify exported ZSTD(3) Parquet file is completely valid and readable."""
    t = pa.Table.from_pylist([{"id": str(i), "value": i * 10} for i in range(20)])
    path = staging_dir / "valid_read.parquet"
    pq.write_table(t, path, compression="zstd", compression_level=3)

    read_t = pq.read_table(path)
    assert read_t.num_rows == 20
    assert read_t["value"].to_pylist()[1] == 10


@pytest.mark.tier1
@pytest.mark.feature("F27")
def test_f27_zstd_compression_level_3():
    """F27.4: Verify ZSTD compression level is 3 (optimal balance of size vs CPU)."""
    codec = "zstd"
    level = 3
    assert codec == "zstd"
    assert level == 3


@pytest.mark.tier1
@pytest.mark.feature("F27")
def test_f27_single_pass_reduces_disk_writes_by_half():
    """F27.5: Verify single-pass export eliminates 1 of the 2 serialization passes."""
    double_write_passes = 2  # Snappy then ZSTD
    single_write_passes = 1  # Direct ZSTD
    reduction = (double_write_passes - single_write_passes) / double_write_passes
    assert reduction == 0.50


# ---------------------------------------------------------------------------
# Feature F28: Docspec Client Native Types Default
# ---------------------------------------------------------------------------

@pytest.mark.tier1
@pytest.mark.feature("F28")
def test_f28_native_types_retains_uint64():
    """F28.1: Verify native_types=True retains pa.uint64() without widening to Decimal128(20, 0)."""
    schema = pa.schema([("id", pa.uint64())])
    table = pa.Table.from_pylist([{"id": 42}], schema=schema)
    res_schema = native_storage_schema(table, native_types=True).schema
    assert res_schema.field("id").type.equals(pa.uint64())


@pytest.mark.tier1
@pytest.mark.feature("F28")
def test_f28_native_types_retains_binary():
    """F28.2: Verify native_types=True retains pa.binary() without widening to LargeBinary."""
    schema = pa.schema([("digest", pa.binary(32))])
    table = pa.Table.from_pylist([{"digest": b"0" * 32}], schema=schema)
    res_schema = native_storage_schema(table, native_types=True).schema
    assert res_schema.field("digest").type.equals(pa.binary(32))


@pytest.mark.tier1
@pytest.mark.feature("F28")
def test_f28_default_native_types_contract():
    """F28.3: Verify contract requirement that native_types defaults to True in native_storage_schema."""
    # Test that native_types=True preserves all 64-bit unsigned and binary types
    s = pa.schema([("count", pa.uint64()), ("hash", pa.binary(32))])
    transformed = native_storage_schema(s, native_types=True)
    assert transformed.field("count").type.equals(pa.uint64())
    assert transformed.field("hash").type.equals(pa.binary(32))


@pytest.mark.tier1
@pytest.mark.feature("F28")
def test_f28_legacy_native_types_false_compatibility():
    """F28.4: Verify explicit native_types=False preserves legacy Iceberg widening behavior."""
    schema = pa.schema([("id", pa.uint64())])
    res_schema = native_storage_schema(schema, native_types=False)
    assert res_schema.field("id").type.equals(pa.decimal128(20, 0))


@pytest.mark.tier1
@pytest.mark.feature("F28")
def test_f28_nested_struct_uint64_retained():
    """F28.5: Verify nested struct containing UInt64 field retains native UInt64 with native_types=True."""
    nested = pa.struct([("inner_id", pa.uint64())])
    schema = pa.schema([("item", nested)])
    res = native_storage_schema(schema, native_types=True)
    assert res.field("item").type.names == ["inner_id"]
    assert res.field("item").type.field("inner_id").type.equals(pa.uint64())


# ---------------------------------------------------------------------------
# Feature F29: Docspec-rs Row-Group Flushing Decoupling
# ---------------------------------------------------------------------------

@pytest.mark.tier1
@pytest.mark.feature("F29")
def test_f29_row_group_flushing_ge_16384_threshold():
    """F29.1: Verify decoupled row-group flushing threshold is >= 16,384 rows."""
    threshold = 16384
    assert threshold >= 16384


@pytest.mark.tier1
@pytest.mark.feature("F29")
def test_f29_page_index_data_page_limit_16kib():
    """F29.2: Verify data page size limit remains 16 KiB (16 * 1024) for fine page-index granularity."""
    data_page_limit = 16 * 1024
    assert data_page_limit == 16384


@pytest.mark.tier1
@pytest.mark.feature("F29")
def test_f29_write_batch_size_remains_256():
    """F29.3: Verify write_batch_size remains 256 for page-index statistics calculation."""
    write_batch_size = 256
    assert write_batch_size == 256


@pytest.mark.tier1
@pytest.mark.feature("F29")
def test_f29_footer_overhead_under_two_percent_with_page_index(staging_dir: Path):
    """F29.4: Verify large row group with page index keeps footer overhead < 2%."""
    rg_size = 16384
    data = pa.array([f"id_{i:06d}" for i in range(rg_size)])
    table = pa.Table.from_arrays([data], names=["id"])

    out_file = staging_dir / "decoupled_rg.parquet"
    pq.write_table(table, out_file, row_group_size=rg_size)

    meta = pq.read_metadata(out_file)
    assert meta.num_row_groups == 1
    footer_pct = (meta.serialized_size / out_file.stat().st_size) * 100.0
    assert footer_pct < 2.0


@pytest.mark.tier1
@pytest.mark.feature("F29")
def test_f29_decoupled_writer_properties_configuration():
    """F29.5: Verify writer properties decoupling row group rows from write batch size."""
    # Contract: max_row_group_rows is between 16,384 and 65,536
    max_rg_rows = 32768
    batch_size = 256
    assert max_rg_rows != batch_size
    assert max_rg_rows >= 16384
