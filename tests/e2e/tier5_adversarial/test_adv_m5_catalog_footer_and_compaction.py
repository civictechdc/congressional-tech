"""Tier 5 Adversarial Tests: Milestone 5 (ct-8od2).

White-box stress testing of:
1. Catalog footer overhead ratio scaling between small and large row-group configurations.
2. `scalarize_catalog_columns` edge cases:
   - Empty tables (0 rows).
   - Columns with all empty lists [].
   - Columns with multi-element lists (must NOT scalarize).
   - Non-numeric values in integer columns (http_status, congress, source_receipt_line fallback).
   - Struct list columns like source_occurrences (must never scalarize).
3. `compact_readings` compaction idempotency across repeated executions.
"""

from __future__ import annotations
from pathlib import Path
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from viewer_publication.filename_exports import (
    scalarize_catalog_columns,
    prune_catalog_null_columns,
    prune_catalog_top_level_source_columns,
)
from viewer_publication.compact_readings import (
    compact_readings,
    deduplicate_reading_table,
    sort_reading_table,
)
from tests.e2e.harness.parquet_oracle import ParquetOracle


class TestM5ScalarizationEdgeCases:
    """Stress testing scalarize_catalog_columns under hostile and boundary inputs."""

    def test_empty_table_zero_rows_scalarization(self):
        """Empty table (0 rows) with list<string> column preserves schema and does not crash."""
        empty_table = pa.Table.from_pydict({
            "http_status": pa.array([], type=pa.list_(pa.string())),
            "format": pa.array([], type=pa.list_(pa.string())),
        })
        scalarized = scalarize_catalog_columns(empty_table)
        assert len(scalarized) == 0
        # Empty columns are scalarized to their typed scalar types
        assert scalarized.schema.field("http_status").type == pa.int16()
        assert scalarized.schema.field("format").type == pa.string()

    def test_all_empty_lists_scalarize_to_null_scalars(self):
        """Column containing only empty lists [ [], [] ] scalarizes to [None, None]."""
        table = pa.Table.from_pydict({
            "format": pa.array([[], []], type=pa.list_(pa.string())),
            "http_status": pa.array([[], []], type=pa.list_(pa.string())),
        })
        scalarized = scalarize_catalog_columns(table)
        assert scalarized.schema.field("format").type == pa.string()
        assert scalarized.schema.field("http_status").type == pa.int16()
        assert scalarized["format"].to_pylist() == [None, None]
        assert scalarized["http_status"].to_pylist() == [None, None]

    def test_multi_element_list_retains_list_type(self):
        """Column containing any multi-element list (max_len > 1) MUST NOT scalarize."""
        table = pa.Table.from_pydict({
            "tags": pa.array([["hearing", "senate"], ["markup"]], type=pa.list_(pa.string())),
            "single": pa.array([["pdf"], ["xml"]], type=pa.list_(pa.string())),
        })
        scalarized = scalarize_catalog_columns(table)
        # tags has max_len = 2 > 1 -> remains list<string>
        assert pa.types.is_list(scalarized.schema.field("tags").type)
        assert scalarized["tags"].to_pylist() == [["hearing", "senate"], ["markup"]]

        # single has max_len = 1 <= 1 -> scalarized to string
        assert scalarized.schema.field("single").type == pa.string()
        assert scalarized["single"].to_pylist() == ["pdf", "xml"]

    def test_non_numeric_integer_column_fallback_to_string(self):
        """Non-numeric string in http_status or congress gracefully falls back to string array."""
        table = pa.Table.from_pydict({
            "http_status": pa.array([["200"], ["UNKNOWN_ERROR"], [None]], type=pa.list_(pa.string())),
            "congress": pa.array([["118th"], ["117"], [None]], type=pa.list_(pa.string())),
        })
        scalarized = scalarize_catalog_columns(table)
        # "UNKNOWN_ERROR" fails int16 parsing -> falls back to string
        assert scalarized.schema.field("http_status").type == pa.string()
        assert scalarized["http_status"].to_pylist() == ["200", "UNKNOWN_ERROR", None]

        # "118th" fails int32 parsing -> falls back to string
        assert scalarized.schema.field("congress").type == pa.string()
        assert scalarized["congress"].to_pylist() == ["118th", "117", None]

    def test_source_occurrences_struct_list_never_scalarized(self):
        """source_occurrences: list<struct<...>> must NEVER be scalarized even if max_len <= 1."""
        occ_struct = pa.struct([("url", pa.string()), ("status", pa.int32())])
        table = pa.Table.from_pydict({
            "source_occurrences": pa.array(
                [[{"url": "https://example.com", "status": 200}]],
                type=pa.list_(occ_struct),
            ),
        })
        scalarized = scalarize_catalog_columns(table)
        assert pa.types.is_list(scalarized.schema.field("source_occurrences").type)
        assert pa.types.is_struct(scalarized.schema.field("source_occurrences").type.value_type)


class TestM5FooterOverheadRatio:
    """Stress testing Parquet footer ratio overhead across row-group configurations."""

    def test_large_row_groups_keep_footer_overhead_under_two_percent(self, tmp_path: Path):
        """Wide table written with >= 16,384 row groups keeps footer overhead ratio < 2%."""
        file_path = tmp_path / "wide_table_16k.parquet"
        num_rows = 20_000
        # 40 columns
        data = {f"col_{i}": [f"value_{r}" for r in range(num_rows)] for i in range(40)}
        table = pa.Table.from_pydict(data)

        pq.write_table(
            table,
            file_path,
            row_group_size=16384,
            compression="zstd",
            write_statistics=True,
        )

        meta = pq.read_metadata(file_path)
        file_size = file_path.stat().st_size
        metadata_bytes = meta.serialized_size
        footer_ratio = metadata_bytes / file_size

        assert meta.num_row_groups <= 2
        # Footer overhead should be well under 2%
        assert footer_ratio < 0.02, f"Footer ratio {footer_ratio:.4f} exceeded 2% limit"


class TestM5ReadingCompactionIdempotency:
    """Stress testing reading compaction idempotency across repeated runs."""

    def test_repeated_compaction_produces_identical_output(self, tmp_path: Path):
        """Compacting already compacted readings produces identical row count, schema, and rows."""
        input_dir = tmp_path / "raw_shards"
        input_dir.mkdir(parents=True, exist_ok=True)

        # Generate 5 small shards with overlapping / duplicate reading_id
        schema = pa.schema([
            ("reading_id", pa.string()),
            ("retained_page_id", pa.string()),
            ("raw_leaf", pa.string()),
            ("congress", pa.int32()),
        ])

        for shard_idx in range(5):
            shard_path = input_dir / f"shard_{shard_idx:03d}.parquet"
            pydict = {
                "reading_id": [f"read_{shard_idx * 10 + i}" for i in range(20)],
                "retained_page_id": [f"page_{shard_idx}" for _ in range(20)],
                "raw_leaf": [f"leaf_{i}" for i in range(20)],
                "congress": [118 for _ in range(20)],
            }
            pq.write_table(pa.Table.from_pydict(pydict, schema=schema), shard_path)

        # Run compaction Pass 1
        pass1_dir = tmp_path / "compacted_pass1"
        res1 = compact_readings(input_dir, pass1_dir, max_files=1, deduplicate=True)
        file1 = pass1_dir / "readings-00000.parquet"
        assert file1.exists()
        t1 = pq.read_table(file1)

        # Run compaction Pass 2 taking Pass 1 as input
        pass2_dir = tmp_path / "compacted_pass2"
        res2 = compact_readings(pass1_dir, pass2_dir, max_files=1, deduplicate=True)
        file2 = pass2_dir / "readings-00000.parquet"
        assert file2.exists()
        t2 = pq.read_table(file2)

        # Verify exact idempotency
        assert len(t1) == len(t2)
        assert t1.schema == t2.schema
        assert t1["reading_id"].to_pylist() == t2["reading_id"].to_pylist()
        assert t1.to_pydict() == t2.to_pydict()
