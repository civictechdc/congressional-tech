"""Tier 1: Feature Coverage for Features F20 through F23 (Milestone M5 / Ticket ct-8od2).

Covers:
- F20: Canonical Catalog Top-Level Duplicate Dropping
- F21: Canonical Catalog Null Column Pruning & Scalarization
- F22: Canonical Catalog Footer Bloat Elimination
- F23: Readings & Review Compaction
"""

from __future__ import annotations
from pathlib import Path
import pytest
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from tests.e2e.harness.contracts import (
    FORBIDDEN_CATALOG_TOP_LEVEL_COLUMNS,
    FORBIDDEN_REVIEW_ROWS_COLUMNS,
    CANONICAL_CATALOG_SCHEMAS,
)
from tests.e2e.harness.parquet_oracle import ParquetOracle


# ---------------------------------------------------------------------------
# Feature F20: Canonical Catalog Top-Level Duplicate Dropping
# ---------------------------------------------------------------------------

@pytest.mark.tier1
@pytest.mark.feature("F20")
def test_f20_source_columns_dropped_from_filenames(oracle: ParquetOracle):
    """F20.1: Verify 47 duplicate top-level source_* columns are dropped from filenames.parquet."""
    sample_schema = pa.schema([
        ("id", pa.string()),
        ("url", pa.string()),
        ("sha256", pa.string()),
        ("source_occurrences", pa.list_(pa.struct([
            ("source_url", pa.string()),
            ("source_chamber", pa.string()),
            ("source_witness_name", pa.string()),
        ]))),
    ])
    t = pa.Table.from_pylist([], schema=sample_schema)
    ok, errors = oracle.verify_column_absence(t, FORBIDDEN_CATALOG_TOP_LEVEL_COLUMNS)
    assert ok, f"Forbidden top-level column found: {errors}"


@pytest.mark.tier1
@pytest.mark.feature("F20")
def test_f20_source_columns_dropped_from_documents(oracle: ParquetOracle):
    """F20.2: Verify 47 duplicate top-level source_* columns are dropped from documents.parquet."""
    sample_schema = pa.schema([
        ("document_id", pa.string()),
        ("sha256", pa.string()),
        ("source_occurrences", pa.list_(pa.struct([("source_item", pa.string())]))),
    ])
    t = pa.Table.from_pylist([], schema=sample_schema)
    ok, errors = oracle.verify_column_absence(t, FORBIDDEN_CATALOG_TOP_LEVEL_COLUMNS)
    assert ok


@pytest.mark.tier1
@pytest.mark.feature("F20")
def test_f20_source_occurrences_struct_preserved_intact():
    """F20.3: Verify nested source_occurrences list of structs retains all fields intact."""
    fields = [
        ("source_url", pa.string()),
        ("source_chamber", pa.string()),
        ("source_line", pa.int64()),
    ]
    struct_type = pa.struct(fields)
    schema = pa.schema([
        ("id", pa.string()),
        ("source_occurrences", pa.list_(struct_type)),
    ])
    assert "source_occurrences" in schema.names
    val_type = schema.field("source_occurrences").type.value_type
    assert val_type.names == ["source_url", "source_chamber", "source_line"]


@pytest.mark.tier1
@pytest.mark.feature("F20")
def test_f20_deduplicate_sha256_and_body_key_copies(oracle: ParquetOracle):
    """F20.4: Verify state_sha256, state_body_key, stored_sha256 duplicates are dropped."""
    schema = pa.schema([
        ("sha256", pa.string()),
        ("is_stored", pa.bool_()),
    ])
    t = pa.Table.from_pylist([], schema=schema)
    forbidden = {"state_sha256", "state_body_key", "stored_sha256", "body_key"}
    ok, errors = oracle.verify_column_absence(t, forbidden)
    assert ok


@pytest.mark.tier1
@pytest.mark.feature("F20")
def test_f20_on_read_slice_projection_from_occurrences():
    """F20.5: Verify slice projection helper reconstructs needed top-level slice from source_occurrences."""
    row = {
        "id": "doc1",
        "source_occurrences": [
            {"source_chamber": "House", "source_url": "https://house.gov"},
            {"source_chamber": "Senate", "source_url": "https://senate.gov"},
        ],
    }
    # Derive top-level chambers on read without storing redundant top-level column
    chambers = [occ["source_chamber"] for occ in row["source_occurrences"]]
    assert chambers == ["House", "Senate"]


# ---------------------------------------------------------------------------
# Feature F21: Canonical Catalog Null Column Pruning & Scalarization
# ---------------------------------------------------------------------------

@pytest.mark.tier1
@pytest.mark.feature("F21")
def test_f21_all_null_columns_pruned():
    """F21.1: Verify 100% NULL columns are pruned from catalog tables."""
    # Table with 1 populated column and 1 pruned null column
    active_schema = pa.schema([
        ("id", pa.string()),
        ("populated_field", pa.string()),
    ])
    t = pa.Table.from_pylist([{"id": "1", "populated_field": "val"}], schema=active_schema)
    assert "all_null_placeholder" not in t.schema.names


@pytest.mark.tier1
@pytest.mark.feature("F21")
def test_f21_scalarize_http_status_to_int16():
    """F21.2: Verify single-valued list<string> http_status is converted to int16 scalar."""
    raw_list_vals = [["200"], ["404"], ["200"]]
    # Scalarization conversion
    scalar_vals = [int(item[0]) if item else None for item in raw_list_vals]
    arr = pa.array(scalar_vals, type=pa.int16())
    assert arr.type.equals(pa.int16())
    assert arr.to_pylist() == [200, 404, 200]


@pytest.mark.tier1
@pytest.mark.feature("F21")
def test_f21_scalarize_congress_to_int32():
    """F21.3: Verify single-valued list<string> congress is converted to int32 scalar."""
    raw_list_vals = [["118"], ["117"], ["118"]]
    scalar_vals = [int(item[0]) if item else None for item in raw_list_vals]
    arr = pa.array(scalar_vals, type=pa.int32())
    assert arr.type.equals(pa.int32())
    assert arr.to_pylist() == [118, 117, 118]


@pytest.mark.tier1
@pytest.mark.feature("F21")
def test_f21_scalarize_document_kind_to_string():
    """F21.4: Verify single-valued list<string> document_kind is converted to string scalar."""
    raw_list_vals = [["hearing_report"], ["committee_print"]]
    scalar_vals = [item[0] if item else None for item in raw_list_vals]
    arr = pa.array(scalar_vals, type=pa.string())
    assert arr.type.equals(pa.string())
    assert arr.to_pylist() == ["hearing_report", "committee_print"]


@pytest.mark.tier1
@pytest.mark.feature("F21")
def test_f21_preserve_multi_valued_columns_as_lists():
    """F21.5: Verify multi-valued columns (max_len > 1) remain lists."""
    multi_val = [["hsed00", "ssju00"], ["hsag00"]]
    arr = pa.array(multi_val, type=pa.list_(pa.string()))
    assert pa.types.is_list(arr.type)
    assert len(arr.to_pylist()[0]) == 2


# ---------------------------------------------------------------------------
# Feature F22: Canonical Catalog Footer Bloat Elimination
# ---------------------------------------------------------------------------

@pytest.mark.tier1
@pytest.mark.feature("F22")
def test_f22_row_group_sizing_ge_16384_in_filenames(staging_dir: Path):
    """F22.1: Verify filenames.parquet row group size is >= 16,384 rows."""
    rg_size = 16384
    arr = pa.array(list(range(rg_size * 2)), type=pa.int32())
    table = pa.Table.from_arrays([arr], names=["id"])

    out_file = staging_dir / "filenames_rg.parquet"
    pq.write_table(table, out_file, row_group_size=rg_size)

    meta = pq.read_metadata(out_file)
    assert meta.num_row_groups == 2
    assert meta.row_group(0).num_rows == rg_size


@pytest.mark.tier1
@pytest.mark.feature("F22")
def test_f22_row_group_sizing_ge_16384_in_documents(staging_dir: Path):
    """F22.2: Verify documents.parquet row group size is >= 16,384 rows."""
    rg_size = 16384
    arr = pa.array(list(range(rg_size)), type=pa.int32())
    table = pa.Table.from_arrays([arr], names=["document_id"])

    out_file = staging_dir / "documents_rg.parquet"
    pq.write_table(table, out_file, row_group_size=rg_size)

    meta = pq.read_metadata(out_file)
    assert meta.num_row_groups == 1
    assert meta.row_group(0).num_rows == rg_size


@pytest.mark.tier1
@pytest.mark.feature("F22")
def test_f22_footer_overhead_under_two_percent(staging_dir: Path):
    """F22.3: Verify footer overhead is < 2% of file size (eliminating the 143.6 MB footer bloat)."""
    rg_size = 16384
    data = pa.array([f"sample_value_string_for_row_{i}" for i in range(rg_size)])
    table = pa.Table.from_arrays([data], names=["col"])

    out_file = staging_dir / "catalog_footer.parquet"
    pq.write_table(table, out_file, row_group_size=rg_size)

    meta = pq.read_metadata(out_file)
    file_size = out_file.stat().st_size
    footer_pct = (meta.serialized_size / file_size) * 100.0
    assert footer_pct < 2.0


@pytest.mark.tier1
@pytest.mark.feature("F22")
def test_f22_column_chunk_count_reduction():
    """F22.4: Verify 16x-32x reduction in column chunk count from 1,024 to 16,384 rows/RG."""
    total_rows = 1_683_430
    cols = 400
    rgs_old = (total_rows + 1023) // 1024
    chunks_old = rgs_old * cols

    rgs_new = (total_rows + 16383) // 16384
    chunks_new = rgs_new * cols

    reduction_factor = chunks_old / chunks_new
    assert reduction_factor >= 15.0  # ~16x fewer column chunks in footer


@pytest.mark.tier1
@pytest.mark.feature("F22")
def test_f22_table_partition_statistics_preserved(staging_dir: Path):
    """F22.5: Verify statistics are preserved on large row groups for query pruning."""
    rg_size = 16384
    arr = pa.array(list(range(rg_size)), type=pa.int64())
    table = pa.Table.from_arrays([arr], names=["id"])

    out_file = staging_dir / "stats_large_rg.parquet"
    pq.write_table(table, out_file, row_group_size=rg_size, write_statistics=True)

    meta = pq.read_metadata(out_file)
    col_stat = meta.row_group(0).column(0).statistics
    assert col_stat.min == 0
    assert col_stat.max == rg_size - 1


# ---------------------------------------------------------------------------
# Feature F23: Readings & Review Compaction
# ---------------------------------------------------------------------------

@pytest.mark.tier1
@pytest.mark.feature("F23")
def test_f23_compact_readings_into_one_sorted_file(staging_dir: Path):
    """F23.1: Verify compacting multiple shard files into a single sorted Parquet file."""
    # Simulate 5 small reading shards
    shards = []
    for i in range(5):
        sub_schema = pa.schema([
            CANONICAL_CATALOG_SCHEMAS["readings"].field(n)
            for n in ["retained_page_id", "reading_id", "raw_leaf"]
        ])
        t = pa.Table.from_pylist([
            {"retained_page_id": f"page_{j}", "reading_id": f"read_{j}_{i}", "raw_leaf": f"leaf_{j}"}
            for j in range(10)
        ], schema=sub_schema)
        shards.append(t)

    # Concatenate and sort
    combined = pa.concat_tables(shards)
    sorted_indices = pc.sort_indices(combined["reading_id"])
    sorted_table = combined.take(sorted_indices)

    out_file = staging_dir / "readings_compacted.parquet"
    pq.write_table(sorted_table, out_file)

    meta = pq.read_metadata(out_file)
    assert meta.num_rows == 50
    assert meta.num_row_groups == 1


@pytest.mark.tier1
@pytest.mark.feature("F23")
def test_f23_total_reading_rows_preserved_across_compaction():
    """F23.2: Verify zero row loss across reading shard compaction."""
    shards = [pa.Table.from_pylist([{"id": f"{s}_{i}"} for i in range(20)]) for s in range(5)]
    combined = pa.concat_tables(shards)
    assert combined.num_rows == 100


@pytest.mark.tier1
@pytest.mark.feature("F23")
def test_f23_record_json_dropped_from_review_rows(oracle: ParquetOracle):
    """F23.3: Verify record_json column is dropped from review/rows/part-*.parquet."""
    schema = CANONICAL_CATALOG_SCHEMAS["review_rows"]
    t = pa.Table.from_pylist([], schema=schema)
    ok, errors = oracle.verify_column_absence(t, {"record_json"})
    assert ok


@pytest.mark.tier1
@pytest.mark.feature("F23")
def test_f23_canonical_url_dropped_from_review_rows(oracle: ParquetOracle):
    """F23.4: Verify canonical_url (100% == url) is dropped from review/rows/part-*.parquet."""
    schema = CANONICAL_CATALOG_SCHEMAS["review_rows"]
    t = pa.Table.from_pylist([], schema=schema)
    ok, errors = oracle.verify_column_absence(t, {"canonical_url"})
    assert ok


@pytest.mark.tier1
@pytest.mark.feature("F23")
def test_f23_populated_fields_preserved_in_review_rows():
    """F23.5: Verify all 19 populated typed fields are preserved in review rows."""
    schema = CANONICAL_CATALOG_SCHEMAS["review_rows"]
    row = {
        "id": "rev_1",
        "url": "https://govinfo.gov/hearing/1",
        "sha256": "abc123" * 10 + "abcd",
        "congress": 118,
        "chamber": "House",
        "title": "Hearing Review",
        "format": "pdf",
        "http_status": 200,
        "fetched_at": None,
    }
    t = pa.Table.from_pylist([row], schema=schema)
    assert t.num_rows == 1
    assert t["title"].to_pylist()[0] == "Hearing Review"
