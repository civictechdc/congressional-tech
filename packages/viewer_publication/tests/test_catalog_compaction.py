"""Unit tests for Canonical Catalog & Viewer Publication Compaction (ct-8od2 / Milestone 5).

Tests:
- F20: Drop 47 top-level source_* columns, preserve source_occurrences, deduplicate sha256/body_key.
- F21: Prune 100% NULL columns, convert single-valued list<string> (max_len <= 1) to typed scalars.
- F22: Row-group sizing >= 16,384 rows, footer bloat reduction (<2% footer overhead).
- F23: Readings compaction (721 shards into 1-2 files), review rows compaction (drop record_json, canonical_url).
"""
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from viewer_publication import (
    DEFAULT_CATALOG_ROW_GROUP_SIZE,
    DEFAULT_COMPRESSION_POLICY,
    DEFAULT_READING_ROW_GROUP_SIZE,
    DEFAULT_REVIEW_ROW_GROUP_SIZE,
    FORBIDDEN_CATALOG_DUPLICATE_DIGESTS,
    FORBIDDEN_CATALOG_TOP_LEVEL_COLUMNS,
    compact_catalog_file,
    compact_catalog_table,
    compact_readings,
    compact_review_rows,
    deduplicate_catalog_sha_and_body_keys,
    deduplicate_reading_table,
    project_source_slice,
    prune_catalog_null_columns,
    prune_catalog_top_level_source_columns,
    prune_review_table,
    scalarize_catalog_columns,
    sort_reading_table,
)


# ---------------------------------------------------------------------------
# Feature F20 Tests
# ---------------------------------------------------------------------------

def test_prune_top_level_source_columns_leaves_occurrences():
    occ_struct = pa.struct([
        ("source_url", pa.string()),
        ("source_chamber", pa.string()),
        ("source_line", pa.int64()),
    ])
    schema = pa.schema([
        ("id", pa.string()),
        ("url", pa.string()),
        ("source_url", pa.string()),               # Top-level source_url (retained)
        ("source_chamber", pa.list_(pa.string())),  # Duplicate top-level (forbidden)
        ("source_witness_name", pa.list_(pa.string())),  # Duplicate top-level (forbidden)
        ("source_occurrences", pa.list_(occ_struct)),    # Struct occurrences (retained)
    ])

    rows = [{
        "id": "doc1",
        "url": "https://govinfo.gov/doc1",
        "source_url": "https://govinfo.gov/source1",
        "source_chamber": ["House"],
        "source_witness_name": ["Jane Doe"],
        "source_occurrences": [
            {"source_url": "https://govinfo.gov/source1", "source_chamber": "House", "source_line": 10}
        ],
    }]
    table = pa.Table.from_pylist(rows, schema=schema)
    pruned = prune_catalog_top_level_source_columns(table)

    assert "id" in pruned.schema.names
    assert "url" in pruned.schema.names
    assert "source_url" in pruned.schema.names
    assert "source_occurrences" in pruned.schema.names
    assert "source_chamber" not in pruned.schema.names
    assert "source_witness_name" not in pruned.schema.names
    assert len(pruned) == 1
    assert pruned["source_occurrences"].to_pylist()[0][0]["source_chamber"] == "House"


def test_deduplicate_sha_and_body_keys():
    schema = pa.schema([
        ("sha256", pa.string()),
        ("state_sha256", pa.string()),
        ("state_body_key", pa.string()),
        ("stored_sha256", pa.string()),
        ("title", pa.string()),
    ])
    rows = [{
        "sha256": "abc" * 20 + "abcd",
        "state_sha256": "abc" * 20 + "abcd",
        "state_body_key": "bodies/sha256/ab/abc.gz",
        "stored_sha256": "abc" * 20 + "abcd",
        "title": "Title",
    }]
    table = pa.Table.from_pylist(rows, schema=schema)
    deduped = deduplicate_catalog_sha_and_body_keys(table)

    assert "sha256" in deduped.schema.names
    assert "title" in deduped.schema.names
    assert "state_sha256" not in deduped.schema.names
    assert "state_body_key" not in deduped.schema.names
    assert "stored_sha256" not in deduped.schema.names


def test_project_source_slice():
    row = {
        "id": "doc_x",
        "source_occurrences": [
            {"source_chamber": "House", "source_witness_name": "Alice"},
            {"source_chamber": "Senate", "source_witness_name": "Bob"},
        ],
    }
    chambers = project_source_slice(row, "source_chamber")
    assert chambers == ["House", "Senate"]

    witnesses = project_source_slice(row, "source_witness_name")
    assert witnesses == ["Alice", "Bob"]


# ---------------------------------------------------------------------------
# Feature F21 Tests
# ---------------------------------------------------------------------------

def test_prune_all_null_columns():
    schema = pa.schema([
        ("populated", pa.string()),
        ("partially_null", pa.string()),
        ("all_null", pa.string()),
    ])
    rows = [
        {"populated": "a", "partially_null": "x", "all_null": None},
        {"populated": "b", "partially_null": None, "all_null": None},
    ]
    table = pa.Table.from_pylist(rows, schema=schema)
    pruned = prune_catalog_null_columns(table)

    assert "populated" in pruned.schema.names
    assert "partially_null" in pruned.schema.names
    assert "all_null" not in pruned.schema.names


def test_scalarize_catalog_columns():
    schema = pa.schema([
        ("http_status", pa.list_(pa.string())),
        ("congress", pa.list_(pa.string())),
        ("document_kind", pa.list_(pa.string())),
        ("multi_val", pa.list_(pa.string())),
        ("empty_list_col", pa.list_(pa.string())),
        ("spaced_text", pa.list_(pa.string())),
    ])
    rows = [
        {
            "http_status": ["200"],
            "congress": ["118"],
            "document_kind": ["hearing"],
            "multi_val": ["a", "b"],
            "empty_list_col": [],
            "spaced_text": ["  leading and trailing  "],
        },
        {
            "http_status": ["404"],
            "congress": ["117"],
            "document_kind": ["report"],
            "multi_val": ["c"],
            "empty_list_col": None,
            "spaced_text": ["\tindented\n"],
        },
    ]
    table = pa.Table.from_pylist(rows, schema=schema)
    scalarized = scalarize_catalog_columns(table)

    # http_status converted to int16
    assert scalarized.schema.field("http_status").type.equals(pa.int16())
    assert scalarized["http_status"].to_pylist() == [200, 404]

    # congress converted to int32
    assert scalarized.schema.field("congress").type.equals(pa.int32())
    assert scalarized["congress"].to_pylist() == [118, 117]

    # document_kind converted to string
    assert scalarized.schema.field("document_kind").type.equals(pa.string())
    assert scalarized["document_kind"].to_pylist() == ["hearing", "report"]

    # multi_val retained as list<string>
    assert pa.types.is_list(scalarized.schema.field("multi_val").type)
    assert scalarized["multi_val"].to_pylist() == [["a", "b"], ["c"]]

    # empty_list_col scalarized to string nulls
    assert scalarized.schema.field("empty_list_col").type.equals(pa.string())
    assert scalarized["empty_list_col"].null_count == 2

    # whitespace preserved
    assert scalarized.schema.field("spaced_text").type.equals(pa.string())
    assert scalarized["spaced_text"].to_pylist() == ["  leading and trailing  ", "\tindented\n"]


# ---------------------------------------------------------------------------
# Feature F22 Tests
# ---------------------------------------------------------------------------

def test_catalog_row_group_sizing_and_footer_ratio(tmp_path: Path):
    num_rows = 16384
    table = pa.Table.from_pylist([
        {"id": f"id_{i}", "val": f"payload_data_string_for_testing_{i}"}
        for i in range(num_rows)
    ])
    out_file = tmp_path / "compacted_catalog.parquet"
    pq.write_table(table, out_file, row_group_size=DEFAULT_CATALOG_ROW_GROUP_SIZE)

    meta = pq.read_metadata(out_file)
    assert meta.num_row_groups == 1
    assert meta.row_group(0).num_rows == num_rows
    file_bytes = out_file.stat().st_size
    footer_pct = (meta.serialized_size / file_bytes) * 100.0
    assert footer_pct < 2.0


def test_compact_catalog_file_integration(tmp_path: Path):
    in_file = tmp_path / "raw_filenames.parquet"
    out_file = tmp_path / "compacted_filenames.parquet"

    # Create uncompacted table with dead columns, forbidden source_* columns, and duplicate digests
    rows = [
        {
            "id": f"fn_{i}",
            "source_url": f"https://example.com/{i}",
            "source_chamber": ["House"],
            "state_body_key": f"bodies/sha256/xx/{i}.gz",
            "state_sha256": f"sha_{i}",
            "all_null_col": None,
            "http_status": ["200"],
            "congress": ["118"],
            "source_occurrences": [{"source_chamber": "House", "source_line": i}],
        }
        for i in range(100)
    ]
    pq.write_table(pa.Table.from_pylist(rows), in_file, row_group_size=32)

    compacted = compact_catalog_file(in_file, out_file, row_group_size=16384)
    assert "source_chamber" not in compacted.schema.names
    assert "state_body_key" not in compacted.schema.names
    assert "state_sha256" not in compacted.schema.names
    assert "all_null_col" not in compacted.schema.names
    assert "source_occurrences" in compacted.schema.names
    assert compacted.schema.field("http_status").type.equals(pa.int16())
    assert compacted.schema.field("congress").type.equals(pa.int32())

    meta = pq.read_metadata(out_file)
    assert meta.num_row_groups == 1


# ---------------------------------------------------------------------------
# Feature F23 Tests (Readings & Review Compaction)
# ---------------------------------------------------------------------------

def test_compact_readings_shards(tmp_path: Path):
    readings_dir = tmp_path / "shards"
    readings_dir.mkdir()

    # Create 5 small reading shards with some duplicate keys
    for shard_idx in range(5):
        rows = [
            {
                "body_key": f"bodies/sha256/ab/{i:04d}.gz",
                "parser_fingerprint": "v1_parser",
                "status": "completed",
                "raw_leaf": f"leaf_{i}_{shard_idx}",
            }
            for i in range(20)
        ]
        shard_path = readings_dir / f"shard_{shard_idx:03d}.parquet"
        pq.write_table(pa.Table.from_pylist(rows), shard_path)

    out_dir = tmp_path / "compacted_readings"
    result = compact_readings(readings_dir, out_dir, max_files=2, row_group_size=16384)

    assert result["num_files"] in (1, 2)
    assert result["total_rows"] == 20  # Deduplicated across shards
    for f in result["files"]:
        meta = pq.read_metadata(f)
        assert meta.num_row_groups == 1


def test_compact_readings_empty_shards(tmp_path: Path):
    readings_dir = tmp_path / "empty_shards"
    readings_dir.mkdir()

    schema = pa.schema([
        ("retained_page_id", pa.string()),
        ("reading_id", pa.string()),
        ("raw_leaf", pa.string()),
    ])
    for i in range(3):
        pq.write_table(pa.Table.from_pylist([], schema=schema), readings_dir / f"empty_{i}.parquet")

    out_file = tmp_path / "compacted_empty.parquet"
    result = compact_readings(readings_dir, out_file)
    assert result["total_rows"] == 0
    assert Path(result["files"][0]).is_file()


def test_compact_review_rows(tmp_path: Path):
    in_file = tmp_path / "raw_review.parquet"
    out_file = tmp_path / "compacted_review.parquet"

    rows = [
        {
            "id": f"rev_{i}",
            "url": f"https://example.com/{i}",
            "canonical_url": f"https://example.com/{i}",  # 100% == url (dropped)
            "record_json": '{"dummy": "boilerplate"}',     # Dropped
            "sha256": "0" * 64,
            "congress": 118,
            "chamber": "House",
            "title": f"Review {i}",
            "format": "pdf",
            "http_status": 200,
            "all_null_field": None,                       # Dropped
        }
        for i in range(50)
    ]
    pq.write_table(pa.Table.from_pylist(rows), in_file)

    compacted = compact_review_rows(in_file, out_file, row_group_size=16384)
    assert "record_json" not in compacted.schema.names
    assert "canonical_url" not in compacted.schema.names
    assert "all_null_field" not in compacted.schema.names
    assert "url" in compacted.schema.names
    assert "sha256" in compacted.schema.names
    assert "title" in compacted.schema.names
    assert len(compacted) == 50

    meta = pq.read_metadata(out_file)
    assert meta.num_row_groups == 1
