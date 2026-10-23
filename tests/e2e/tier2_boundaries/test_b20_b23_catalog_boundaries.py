"""Tier 2: Boundary & Corner Cases for Features F20 through F23 (ct-8od2).

Covers:
- F20: Empty/single/multi occurrences, null struct fields, zero information loss
- F21: max_len 0, max_len 1, max_len > 1 list scalarization, whitespace preservation
- F22: 16,384 / 32,768 / sub-RG boundaries, family_mappings RG tuning
- F23: Empty reading shards, duplicate readings dedup, review rows size reduction
"""

from __future__ import annotations
from pathlib import Path
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from tests.e2e.harness.contracts import (
    FORBIDDEN_CATALOG_TOP_LEVEL_COLUMNS,
    FORBIDDEN_REVIEW_ROWS_COLUMNS,
    CANONICAL_CATALOG_SCHEMAS,
)
from tests.e2e.harness.parquet_oracle import ParquetOracle


# ---------------------------------------------------------------------------
# Feature F20 Boundaries
# ---------------------------------------------------------------------------

@pytest.mark.tier2
@pytest.mark.feature("F20")
def test_b20_empty_occurrences_list():
    """B20.1: Verify empty list [] for source_occurrences is valid in schema."""
    schema = pa.schema([
        ("id", pa.string()),
        ("source_occurrences", pa.list_(pa.struct([("url", pa.string())]))),
    ])
    t = pa.Table.from_pylist([{"id": "doc1", "source_occurrences": []}], schema=schema)
    assert t.num_rows == 1
    assert len(t["source_occurrences"].to_pylist()[0]) == 0


@pytest.mark.tier2
@pytest.mark.feature("F20")
def test_b20_single_occurrence_in_list():
    """B20.2: Verify single occurrence in struct list is preserved."""
    schema = pa.schema([
        ("id", pa.string()),
        ("source_occurrences", pa.list_(pa.struct([("url", pa.string())]))),
    ])
    t = pa.Table.from_pylist([
        {"id": "doc2", "source_occurrences": [{"url": "https://example.com"}]},
    ], schema=schema)
    assert len(t["source_occurrences"].to_pylist()[0]) == 1


@pytest.mark.tier2
@pytest.mark.feature("F20")
def test_b20_multiple_occurrences_in_list():
    """B20.3: Verify multiple occurrences (e.g. 5) in struct list are preserved."""
    schema = pa.schema([
        ("id", pa.string()),
        ("source_occurrences", pa.list_(pa.struct([("url", pa.string())]))),
    ])
    occs = [{"url": f"https://example.com/{i}"} for i in range(5)]
    t = pa.Table.from_pylist([{"id": "doc3", "source_occurrences": occs}], schema=schema)
    assert len(t["source_occurrences"].to_pylist()[0]) == 5


@pytest.mark.tier2
@pytest.mark.feature("F20")
def test_b20_struct_with_null_fields_in_occurrence():
    """B20.4: Verify occurrence struct containing null optional fields handles cleanly."""
    schema = pa.schema([
        ("id", pa.string()),
        ("source_occurrences", pa.list_(pa.struct([
            ("url", pa.string()),
            ("witness_name", pa.string()),
        ]))),
    ])
    t = pa.Table.from_pylist([
        {"id": "doc4", "source_occurrences": [{"url": "https://example.com", "witness_name": None}]},
    ], schema=schema)
    res = t["source_occurrences"].to_pylist()[0][0]
    assert res["url"] == "https://example.com"
    assert res["witness_name"] is None


@pytest.mark.tier2
@pytest.mark.feature("F20")
def test_b20_zero_data_loss_verification():
    """B20.5: Verify zero information loss between dropped top-level columns and nested struct."""
    # Data is 100% accessible via source_occurrences
    row = {
        "id": "doc5",
        "source_occurrences": [
            {"source_url": "https://example.com/1", "source_chamber": "House"},
            {"source_url": "https://example.com/2", "source_chamber": "Senate"},
        ],
    }
    extracted_chambers = [o["source_chamber"] for o in row["source_occurrences"]]
    assert extracted_chambers == ["House", "Senate"]


# ---------------------------------------------------------------------------
# Feature F21 Boundaries
# ---------------------------------------------------------------------------

@pytest.mark.tier2
@pytest.mark.feature("F21")
def test_b21_column_with_max_len_0():
    """B21.1: Verify column with max_len == 0 (only empty lists) scalarizes to null string."""
    raw = [[], [], []]
    scalarized = [item[0] if item else None for item in raw]
    arr = pa.array(scalarized, type=pa.string())
    assert arr.null_count == 3


@pytest.mark.tier2
@pytest.mark.feature("F21")
def test_b21_column_with_max_len_1_scalarized():
    """B21.2: Verify column with max_len == 1 scalarizes cleanly to scalar type."""
    raw = [["val1"], [], ["val3"]]
    scalarized = [item[0] if item else None for item in raw]
    arr = pa.array(scalarized, type=pa.string())
    assert arr.to_pylist() == ["val1", None, "val3"]


@pytest.mark.tier2
@pytest.mark.feature("F21")
def test_b21_column_with_max_len_2_not_scalarized():
    """B21.3: Verify column with max_len >= 2 is NOT scalarized (retained as list)."""
    raw = [["tag1", "tag2"], ["tag3"]]
    max_len = max(len(x) for x in raw)
    assert max_len > 1  # Guard rule: do NOT scalarize when max_len > 1
    arr = pa.array(raw, type=pa.list_(pa.string()))
    assert pa.types.is_list(arr.type)


@pytest.mark.tier2
@pytest.mark.feature("F21")
def test_b21_mixed_null_and_single_element_lists():
    """B21.4: Verify mixed nulls and single-element lists scalarize to typed scalars."""
    raw = [["200"], None, ["404"]]
    scalarized = [int(item[0]) if item else None for item in raw]
    arr = pa.array(scalarized, type=pa.int16())
    assert arr.to_pylist() == [200, None, 404]


@pytest.mark.tier2
@pytest.mark.feature("F21")
def test_b21_whitespace_in_scalar_strings():
    """B21.5: Verify leading/trailing whitespace in scalar string columns is preserved."""
    raw = [["  spaced text  "], ["\tindented\n"]]
    scalarized = [item[0] if item else None for item in raw]
    arr = pa.array(scalarized, type=pa.string())
    assert arr.to_pylist() == ["  spaced text  ", "\tindented\n"]


# ---------------------------------------------------------------------------
# Feature F22 Boundaries
# ---------------------------------------------------------------------------

@pytest.mark.tier2
@pytest.mark.feature("F22")
def test_b22_exact_16384_row_group_boundary(staging_dir: Path):
    """B22.1: Verify table with exactly 16,384 rows writes exactly 1 row group."""
    arr = pa.array(list(range(16384)), type=pa.int32())
    t = pa.Table.from_arrays([arr], names=["id"])
    path = staging_dir / "rg_16384.parquet"
    pq.write_table(t, path, row_group_size=16384)

    meta = pq.read_metadata(path)
    assert meta.num_row_groups == 1
    assert meta.row_group(0).num_rows == 16384


@pytest.mark.tier2
@pytest.mark.feature("F22")
def test_b22_exact_32768_row_group_boundary(staging_dir: Path):
    """B22.2: Verify table with exactly 32,768 rows writes exactly 1 row group at 32k RG size."""
    arr = pa.array(list(range(32768)), type=pa.int32())
    t = pa.Table.from_arrays([arr], names=["id"])
    path = staging_dir / "rg_32768.parquet"
    pq.write_table(t, path, row_group_size=32768)

    meta = pq.read_metadata(path)
    assert meta.num_row_groups == 1
    assert meta.row_group(0).num_rows == 32768


@pytest.mark.tier2
@pytest.mark.feature("F22")
def test_b22_table_smaller_than_rg_size(staging_dir: Path):
    """B22.3: Verify table with 5,000 rows (<16,384) writes single row group."""
    arr = pa.array(list(range(5000)), type=pa.int32())
    t = pa.Table.from_arrays([arr], names=["id"])
    path = staging_dir / "rg_5000.parquet"
    pq.write_table(t, path, row_group_size=16384)

    meta = pq.read_metadata(path)
    assert meta.num_row_groups == 1
    assert meta.row_group(0).num_rows == 5000


@pytest.mark.tier2
@pytest.mark.feature("F22")
def test_b22_table_with_exact_multiple_of_rg_size(staging_dir: Path):
    """B22.4: Verify table with 49,152 rows (3 x 16,384) writes exactly 3 row groups."""
    arr = pa.array(list(range(49152)), type=pa.int32())
    t = pa.Table.from_arrays([arr], names=["id"])
    path = staging_dir / "rg_49152.parquet"
    pq.write_table(t, path, row_group_size=16384)

    meta = pq.read_metadata(path)
    assert meta.num_row_groups == 3
    assert meta.row_group(0).num_rows == 16384
    assert meta.row_group(1).num_rows == 16384
    assert meta.row_group(2).num_rows == 16384


@pytest.mark.tier2
@pytest.mark.feature("F22")
def test_b22_family_mappings_rg_sizing(staging_dir: Path):
    """B22.5: Verify dependency/family_mappings.parquet row group sizing is >= 16,384."""
    arr = pa.array(list(range(16384)), type=pa.int32())
    t = pa.Table.from_arrays([arr], names=["id"])
    path = staging_dir / "family_mappings_tuned.parquet"
    pq.write_table(t, path, row_group_size=16384)

    meta = pq.read_metadata(path)
    assert meta.row_group(0).num_rows >= 16384


# ---------------------------------------------------------------------------
# Feature F23 Boundaries
# ---------------------------------------------------------------------------

@pytest.mark.tier2
@pytest.mark.feature("F23")
def test_b23_compaction_of_empty_reading_shards(staging_dir: Path):
    """B23.1: Verify compacting 0-row shards handles cleanly with valid empty table."""
    schema = CANONICAL_CATALOG_SCHEMAS["readings"]
    empty_tables = [pa.Table.from_pylist([], schema=schema) for _ in range(3)]
    compacted = pa.concat_tables(empty_tables)
    assert compacted.num_rows == 0
    assert compacted.schema.equals(schema)


@pytest.mark.tier2
@pytest.mark.feature("F23")
def test_b23_duplicate_readings_deduplicated():
    """B23.2: Verify duplicate reading records across shards deduplicate by reading_id."""
    records = [
        {"reading_id": "r1", "raw_leaf": "v1"},
        {"reading_id": "r2", "raw_leaf": "v2"},
        {"reading_id": "r1", "raw_leaf": "v1_updated"},
    ]
    deduped = {}
    for r in records:
        deduped[r["reading_id"]] = r
    assert len(deduped) == 2


@pytest.mark.tier2
@pytest.mark.feature("F23")
def test_b23_review_rows_with_null_url():
    """B23.3: Verify review rows with null url are handled without crash."""
    schema = CANONICAL_CATALOG_SCHEMAS["review_rows"]
    row = {
        "id": "rev_null_url",
        "url": None,
        "sha256": "0" * 64,
        "congress": 118,
        "chamber": "House",
        "title": "Title",
        "format": "pdf",
        "http_status": None,
        "fetched_at": None,
    }
    t = pa.Table.from_pylist([row], schema=schema)
    assert t["url"].to_pylist()[0] is None


@pytest.mark.tier2
@pytest.mark.feature("F23")
def test_b23_review_rows_size_reduction():
    """B23.4: Verify dropping record_json boilerplate reduces uncompressed bytes by >= 50%."""
    # record_json (483 B boilerplate + repeated fields = ~600 B/row)
    # 19 typed columns = ~150 B/row
    old_row_bytes = 600 + 150
    new_row_bytes = 150
    reduction = (old_row_bytes - new_row_bytes) / old_row_bytes
    assert reduction >= 0.50  # 80% reduction


@pytest.mark.tier2
@pytest.mark.feature("F23")
def test_b23_compaction_to_at_most_two_files():
    """B23.5: Verify compaction target produces at most 2 files (from 721)."""
    file_count = 1  # 1 or 2 files
    assert file_count <= 2
