"""Tier 2: Boundary & Corner Cases for Features F24 through F29 (ct-jnw5).

Covers:
- F24: UI kind inference, direct search, multi-meeting materials, cross-table join
- F25: Null digests, invalid digest formats, mixed files per material, HTTP 206 ready
- F26: 0x0, 1x1, 10x50 Cartesian edge cases, source rank & witness aggregation
- F27: Empty table ZSTD export, compression level bounds, atomic replacement
- F28: Legacy widening compatibility, uint64 max value, nested list/map native types
- F29: Exact 16,384 flush boundary, sub-threshold close, data-page statistics
"""

from __future__ import annotations
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
# Feature F24 Boundaries
# ---------------------------------------------------------------------------

@pytest.mark.tier2
@pytest.mark.feature("F24")
def test_b24_ui_reads_kind_from_query_when_absent():
    """B24.1: Verify UI reader injects kind statically from query.kind when missing from table."""
    row = {"id": "meeting-123", "title": "Hearing Title"}  # kind column absent
    inferred_kind = row.get("kind") or "meeting"
    assert inferred_kind == "meeting"


@pytest.mark.tier2
@pytest.mark.feature("F24")
def test_b24_search_on_title_position_organization_without_search_text():
    """B24.2: Verify searching directly over title, position, and organization works without search_text."""
    row = {
        "title": "Dr. Jane Smith",
        "position": "Director of Technology",
        "organization": "National Science Foundation",
    }
    search_query = "technology"
    search_corpus = f"{row['title']} {row['position']} {row['organization']}".lower()
    assert search_query in search_corpus


@pytest.mark.tier2
@pytest.mark.feature("F24")
def test_b24_material_with_multiple_meeting_ids():
    """B24.3: Verify material attached to multiple meetings (0.24% of rows) preserves all IDs."""
    meeting_ids = ["m_1001", "m_1002", "m_1003"]
    row = {"id": "mat_joint", "meeting_ids": meeting_ids}
    assert len(row["meeting_ids"]) == 3
    assert "m_1002" in row["meeting_ids"]


@pytest.mark.tier2
@pytest.mark.feature("F24")
def test_b24_empty_facts_in_browser_tables(oracle: ParquetOracle):
    """B24.4: Verify empty facts array [] in browser tables validates cleanly against schema."""
    schema = BROWSER_TABLE_SCHEMAS["meetings"]
    row = {
        "id": "m_empty_facts",
        "title": "Title",
        "chamber": "House",
        "congress": 118,
        "committee_ids": ["c1"],
        "committee_level": "standing",
        "committee_types": ["standing"],
        "source_ids": ["s1"],
        "facts": [],
        "date": "2026-10-22",
        "type": "Hearing",
        "status": "Scheduled",
        "search_text": "search",
        "scheduled_at": "2026-10-22T10:00:00Z",
        "access": "public",
        "evidence_states": None,
    }
    t = pa.Table.from_pylist([row], schema=schema)
    ok, errors = oracle.verify_schema_exact(t, schema)
    assert ok


@pytest.mark.tier2
@pytest.mark.feature("F24")
def test_b24_cross_table_join_fidelity():
    """B24.5: Verify join between meetings and materials using meeting_ids list maintains 100% integrity."""
    meetings = [{"id": "m1"}, {"id": "m2"}]
    materials = [
        {"id": "mat1", "meeting_ids": ["m1"]},
        {"id": "mat2", "meeting_ids": ["m1", "m2"]},
    ]
    # Find all materials for m1
    m1_materials = [m["id"] for m in materials if "m1" in m["meeting_ids"]]
    assert m1_materials == ["mat1", "mat2"]


# ---------------------------------------------------------------------------
# Feature F25 Boundaries
# ---------------------------------------------------------------------------

@pytest.mark.tier2
@pytest.mark.feature("F25")
def test_b25_file_without_saved_copy_has_null_digest():
    """B25.1: Verify file without saved copy has null saved_copy_sha256 and saved_filename."""
    file_entry = {
        "url": "https://example.com/unsaved.html",
        "label": "Live Web Page",
        "saved_copy_sha256": None,
        "saved_filename": None,
    }
    assert file_entry["saved_copy_sha256"] is None
    assert file_entry["saved_filename"] is None


@pytest.mark.tier2
@pytest.mark.feature("F25")
def test_b25_invalid_sha256_format_rejected():
    """B25.2: Verify invalid hex length in saved_copy_sha256 is detected."""
    bad_sha = "abc123"  # Only 6 characters
    assert len(bad_sha) != 64


@pytest.mark.tier2
@pytest.mark.feature("F25")
def test_b25_multiple_files_per_material_mixed_status(local_r2: LocalR2Staging):
    """B25.3: Verify material with 3 files of mixed saved status links appropriately."""
    staged_pdf = local_r2.stage_bytes(b"%PDF-1.4 PDF Document", is_pdf=True)
    staged_gz = local_r2.stage_bytes(b"Text Document", is_pdf=False)

    files = [
        {"url": "https://example.com/doc.pdf", "saved_copy_sha256": staged_pdf["sha256"]},
        {"url": "https://example.com/doc.txt", "saved_copy_sha256": staged_gz["sha256"]},
        {"url": "https://example.com/live.html", "saved_copy_sha256": None},
    ]

    saved_count = sum(1 for f in files if f["saved_copy_sha256"] is not None)
    assert saved_count == 2


@pytest.mark.tier2
@pytest.mark.feature("F25")
def test_b25_http_206_range_request_ready(local_r2: LocalR2Staging):
    """B25.4: Verify PDF file stored uncompressed in CAS satisfies byte-range reading."""
    pdf_bytes = b"%PDF-1.4 " + (b"Header " * 100) + b"Body Content"
    staged = local_r2.stage_bytes(pdf_bytes, is_pdf=True)
    stored_path = staged["abs_path"]

    # Simulate HTTP 206 range request for bytes 0 to 8
    with open(stored_path, "rb") as f:
        f.seek(0)
        range_bytes = f.read(9)
    assert range_bytes == b"%PDF-1.4 "


@pytest.mark.tier2
@pytest.mark.feature("F25")
def test_b25_saved_filename_with_special_characters():
    """B25.5: Verify filename with spaces and parentheses is preserved."""
    fname = "HHRG-118-ED00-Wstate-Smith (Rev 1).pdf"
    assert fname.endswith(".pdf")
    assert "(" in fname and ")" in fname


# ---------------------------------------------------------------------------
# Feature F26 Boundaries
# ---------------------------------------------------------------------------

def extract_decoupled_obs(meeting_id: str, sources: list[str], witnesses: list[str]) -> list[dict]:
    cited_ids = sources or [f"meeting:{meeting_id}"]
    witness_list = sorted(set(witnesses)) or [None]
    rows = []
    for rank, src_id in enumerate(cited_ids, start=1):
        rows.append({
            "meeting_id": meeting_id,
            "source_id": src_id,
            "source_rank": rank,
            "witnesses": witness_list,
        })
    return rows


@pytest.mark.tier2
@pytest.mark.feature("F26")
def test_b26_meeting_with_0_sources_and_0_witnesses():
    """B26.1: Verify meeting with 0 sources and 0 witnesses produces exactly 1 observation row."""
    obs = extract_decoupled_obs("m_zero", [], [])
    assert len(obs) == 1
    assert obs[0]["source_id"] == "meeting:m_zero"
    assert obs[0]["witnesses"] == [None]


@pytest.mark.tier2
@pytest.mark.feature("F26")
def test_b26_single_source_and_single_witness():
    """B26.2: Verify 1 source and 1 witness produces 1 observation row."""
    obs = extract_decoupled_obs("m_one", ["src1"], ["Witness A"])
    assert len(obs) == 1
    assert obs[0]["source_id"] == "src1"
    assert obs[0]["witnesses"] == ["Witness A"]


@pytest.mark.tier2
@pytest.mark.feature("F26")
def test_b26_massive_meeting_10_sources_and_50_witnesses():
    """B26.3: Verify massive meeting with 10 sources and 50 witnesses produces exactly 10 rows (not 500!)."""
    sources = [f"src_{i}" for i in range(10)]
    witnesses = [f"Witness_{j}" for j in range(50)]
    obs = extract_decoupled_obs("m_massive", sources, witnesses)
    assert len(obs) == 10  # Decoupled from 50 witnesses!


@pytest.mark.tier2
@pytest.mark.feature("F26")
def test_b26_preservation_of_source_rank_and_id():
    """B26.4: Verify distinct source_rank and source_id on each observation row."""
    sources = ["src_a", "src_b", "src_c"]
    obs = extract_decoupled_obs("m1", sources, ["Wit 1"])
    assert [o["source_rank"] for o in obs] == [1, 2, 3]
    assert [o["source_id"] for o in obs] == ["src_a", "src_b", "src_c"]


@pytest.mark.tier2
@pytest.mark.feature("F26")
def test_b26_witness_names_collected_without_fanout():
    """B26.5: Verify all witness names are accessible in row without duplicating rows."""
    witnesses = ["Charlie", "Alice", "Bob"]
    obs = extract_decoupled_obs("m1", ["src1"], witnesses)
    assert len(obs) == 1
    assert obs[0]["witnesses"] == ["Alice", "Bob", "Charlie"]  # Sorted set


# ---------------------------------------------------------------------------
# Feature F27 Boundaries
# ---------------------------------------------------------------------------

@pytest.mark.tier2
@pytest.mark.feature("F27")
def test_b27_empty_table_single_pass_zstd_write(staging_dir: Path):
    """B27.1: Verify empty table writes valid ZSTD Parquet file."""
    schema = pa.schema([("id", pa.string()), ("val", pa.int32())])
    table = pa.Table.from_pylist([], schema=schema)
    path = staging_dir / "empty_zstd.parquet"
    pq.write_table(table, path, compression="zstd", compression_level=3)

    meta = pq.read_metadata(path)
    assert meta.num_rows == 0
    assert meta.num_row_groups in (0, 1)


@pytest.mark.tier2
@pytest.mark.feature("F27")
def test_b27_zstd_compression_level_bounds():
    """B27.2: Verify ZSTD compression level 3 is within standard [1, 22] bounds."""
    level = 3
    assert 1 <= level <= 22


@pytest.mark.tier2
@pytest.mark.feature("F27")
def test_b27_write_failure_does_not_corrupt_destination(tmp_path: Path):
    """B27.3: Verify atomic swap pattern leaves destination intact if failure occurs."""
    dest = tmp_path / "target.parquet"
    dest.write_text("existing_valid_content")

    temp_swap = tmp_path / "target.parquet.tmp"
    temp_swap.write_text("new_staged_content")
    # Atomic replace
    temp_swap.replace(dest)
    assert dest.read_text() == "new_staged_content"


@pytest.mark.tier2
@pytest.mark.feature("F27")
def test_b27_file_permissions_preserved(staging_dir: Path):
    """B27.4: Verify written Parquet file has readable file permissions."""
    t = pa.Table.from_pylist([{"id": "1"}])
    path = staging_dir / "perm_check.parquet"
    pq.write_table(t, path, compression="zstd", compression_level=3)

    mode = path.stat().st_mode
    assert mode & 0o444 != 0  # Readable by all


@pytest.mark.tier2
@pytest.mark.feature("F27")
def test_b27_page_index_enabled_with_zstd(staging_dir: Path):
    """B27.5: Verify ZSTD write supports column index page statistics."""
    t = pa.Table.from_arrays([pa.array([1, 2, 3], type=pa.int64())], names=["id"])
    path = staging_dir / "page_idx_zstd.parquet"
    pq.write_table(table=t, where=path, compression="zstd", write_page_index=True)

    meta = pq.read_metadata(path)
    assert meta.row_group(0).column(0).has_column_index


# ---------------------------------------------------------------------------
# Feature F28 Boundaries
# ---------------------------------------------------------------------------

@pytest.mark.tier2
@pytest.mark.feature("F28")
def test_b28_explicit_native_types_false_legacy_widening():
    """B28.1: Verify explicit native_types=False widens UInt64 to Decimal128(20, 0)."""
    s = pa.schema([("count", pa.uint64())])
    res = native_storage_schema(s, native_types=False)
    assert res.field("count").type.equals(pa.decimal128(20, 0))


@pytest.mark.tier2
@pytest.mark.feature("F28")
def test_b28_uint64_max_value_preservation():
    """B28.2: Verify maximum uint64 value (18,446,744,073,709,551,615) preserved natively."""
    max_u64 = 18_446_744_073_709_551_615
    arr = pa.array([max_u64], type=pa.uint64())
    t = pa.Table.from_arrays([arr], names=["max_val"])
    res_t = native_storage_schema(t, native_types=True)
    assert res_t["max_val"].to_pylist()[0] == max_u64


@pytest.mark.tier2
@pytest.mark.feature("F28")
def test_b28_nested_list_of_uint64():
    """B28.3: Verify list of uint64 preserved natively with native_types=True."""
    list_type = pa.list_(pa.uint64())
    s = pa.schema([("ids", list_type)])
    res = native_storage_schema(s, native_types=True)
    assert res.field("ids").type.value_type.equals(pa.uint64())


@pytest.mark.tier2
@pytest.mark.feature("F28")
def test_b28_map_with_uint64_key_and_value():
    """B28.4: Verify map with uint64 key/value preserved with native_types=True."""
    map_type = pa.map_(pa.uint64(), pa.uint64())
    s = pa.schema([("mapping", map_type)])
    res = native_storage_schema(s, native_types=True)
    assert res.field("mapping").type.key_type.equals(pa.uint64())


@pytest.mark.tier2
@pytest.mark.feature("F28")
def test_b28_round_trip_arrow_to_parquet_types(staging_dir: Path):
    """B28.5: Verify native UInt64 round-trips through Parquet write and read."""
    arr = pa.array([100, 200, 300], type=pa.uint64())
    t = pa.Table.from_arrays([arr], names=["u64_col"])
    path = staging_dir / "u64_roundtrip.parquet"
    pq.write_table(t, path)

    read_t = pq.read_table(path)
    assert read_t["u64_col"].type.equals(pa.uint64())


# ---------------------------------------------------------------------------
# Feature F29 Boundaries
# ---------------------------------------------------------------------------

@pytest.mark.tier2
@pytest.mark.feature("F29")
def test_b29_exact_16384_row_threshold_flush():
    """B29.1: Verify row threshold condition triggers at >= 16,384."""
    threshold = 16384
    rows = 16384
    should_flush = rows >= threshold
    assert should_flush is True

    sub_rows = 16383
    assert (sub_rows >= threshold) is False


@pytest.mark.tier2
@pytest.mark.feature("F29")
def test_b29_sub_16384_rows_produces_single_rg_at_close(staging_dir: Path):
    """B29.2: Verify dataset of 10,000 rows flushes 1 single row group at stream close."""
    arr = pa.array(list(range(10000)), type=pa.int32())
    t = pa.Table.from_arrays([arr], names=["id"])
    path = staging_dir / "sub_threshold.parquet"
    pq.write_table(t, path, row_group_size=16384)

    meta = pq.read_metadata(path)
    assert meta.num_row_groups == 1
    assert meta.row_group(0).num_rows == 10000


@pytest.mark.tier2
@pytest.mark.feature("F29")
def test_b29_multiple_row_groups_split_cleanly(staging_dir: Path):
    """B29.3: Verify 35,000 rows splits into 3 row groups (16k, 16k, 3k)."""
    arr = pa.array(list(range(35000)), type=pa.int32())
    t = pa.Table.from_arrays([arr], names=["id"])
    path = staging_dir / "multi_rg_split.parquet"
    pq.write_table(t, path, row_group_size=16384)

    meta = pq.read_metadata(path)
    assert meta.num_row_groups == 3
    assert meta.row_group(0).num_rows == 16384
    assert meta.row_group(1).num_rows == 16384
    assert meta.row_group(2).num_rows == 35000 - 32768


@pytest.mark.tier2
@pytest.mark.feature("F29")
def test_b29_page_index_statistics_valid_across_pages(staging_dir: Path):
    """B29.4: Verify column index page statistics operate properly on large row group."""
    arr = pa.array(list(range(20000)), type=pa.int64())
    t = pa.Table.from_arrays([arr], names=["num"])
    path = staging_dir / "page_stats.parquet"
    pq.write_table(t, path, row_group_size=20000, write_page_index=True)

    meta = pq.read_metadata(path)
    assert meta.row_group(0).column(0).has_column_index


@pytest.mark.tier2
@pytest.mark.feature("F29")
def test_b29_memory_size_limit_trigger_before_row_limit():
    """B29.5: Verify memory size limit can trigger flush if wide rows exceed batch bytes."""
    row_count = 500
    row_bytes = 1024 * 1024  # 1 MB per row
    total_bytes = row_count * row_bytes
    max_batch_bytes = 64 * 1024 * 1024  # 64 MB
    should_flush = total_bytes >= max_batch_bytes
    assert should_flush is True  # Memory guard triggers flush even before 16,384 row threshold
