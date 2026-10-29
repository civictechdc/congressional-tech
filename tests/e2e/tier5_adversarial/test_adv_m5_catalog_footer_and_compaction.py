"""Parquet footer sizing and retained readings compaction remain checked."""

from __future__ import annotations
from pathlib import Path
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from viewer_publication.compact_readings import (
    compact_readings,
    deduplicate_reading_table,
    sort_reading_table,
)
from tests.e2e.harness.parquet_oracle import ParquetOracle


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
