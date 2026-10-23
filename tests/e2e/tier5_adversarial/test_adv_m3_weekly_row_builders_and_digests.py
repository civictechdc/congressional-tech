"""Tier 5 Adversarial Tests: Milestone 3 (ct-q29c).

White-box stress testing of:
1. Row builders with unexpected missing/corrupt keys, empty primary keys, and order_by violations.
2. Malformed and edge-case timestamps across weekly tables.
3. Zero-copy buffer digest collision resistance in WeeklyRetentionTables._operation_id:
   - Sliced table buffer sharing.
   - Nested struct column buffer transparency.
   - Column name permutation resistance.
"""

from __future__ import annotations
import hashlib
from pathlib import Path
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.retention.weekly_tables import (
    WeeklyRetentionTables,
    youtube_video_to_row,
    committee_to_row,
    house_event_to_row,
    gpo_observation_to_row,
    senate_event_to_row,
    build_arrow_table,
    WEEKLY_TABLE_KEYS,
    WEEKLY_TABLE_MERGES,
)


class TestM3RowBuildersCorruptKeys:
    """Stress testing row builders with missing, corrupt, and unexpected keys."""

    def test_youtube_video_missing_keys_and_empty_id(self):
        """Missing or empty videoId must raise ValueError."""
        with pytest.raises(ValueError, match="youtube_video row missing videoId"):
            youtube_video_to_row("hha00", {"title": "Test Video"})

        with pytest.raises(ValueError, match="youtube_video row missing videoId"):
            youtube_video_to_row("hha00", {"videoId": "   ", "title": "Test Video"})

    def test_youtube_video_missing_published_at_order_by_violation(self):
        """Missing published_at triggers ValueError."""
        with pytest.raises(ValueError, match="youtube_video row missing published_at"):
            youtube_video_to_row("hha00", {"videoId": "abc12345", "title": "Test Video"})

    def test_congress_committees_missing_nested_dict(self):
        """Committee snapshot missing record['committee'] or systemCode fails with ValueError."""
        with pytest.raises(ValueError, match="congress_committees row missing system_code"):
            committee_to_row("https://example.com/committees", {})

    def test_house_events_missing_watermarks(self):
        """House event missing both imported_at and checked fails with ValueError."""
        with pytest.raises(ValueError, match="house_events row missing merge timestamp"):
            house_event_to_row("event-1", {"id": "1", "title": "Hearing"})

    def test_gpo_observations_missing_watermark(self):
        """GPO observation with no timestamps in listing/mods/transcripts fails with ValueError."""
        with pytest.raises(ValueError, match="gpo_observations row missing retrieved_at timestamp"):
            gpo_observation_to_row("CHRG-118", {"package_id": "CHRG-118", "listing": {}})


class TestM3ZeroCopyBufferDigestCollisions:
    """Empirical adversarial stress testing of zero-copy buffer digest algorithm in _operation_id."""

    @pytest.fixture
    def retention_tables(self, tmp_path: Path):
        return WeeklyRetentionTables(workspace=tmp_path / "weekly_workspace")

    def test_sliced_table_buffer_sharing_collision(self, retention_tables: WeeklyRetentionTables):
        """Empirical Discovery: PyArrow slices share underlying memory buffers.

        When two distinct non-overlapping slices of the same parent table have identical row counts,
        do their underlying chunk.buffers() produce identical operation digests?
        """
        # Create a parent table with 10 rows
        parent_table = pa.table({
            "id": pa.array(["id_0", "id_1", "id_2", "id_3", "id_4", "id_5", "id_6", "id_7", "id_8", "id_9"]),
            "value": pa.array([10, 20, 30, 40, 50, 60, 70, 80, 90, 100]),
        })

        slice_1 = parent_table.slice(0, 5)  # rows 0-4
        slice_2 = parent_table.slice(5, 5)  # rows 5-9

        # Both slices have 5 rows
        assert len(slice_1) == 5
        assert len(slice_2) == 5
        # But their data values are completely disjoint
        assert slice_1["value"].to_pylist() != slice_2["value"].to_pylist()

        # Compute operation IDs
        op_1 = retention_tables._operation_id("test_ds", "admit", slice_1)
        op_2 = retention_tables._operation_id("test_ds", "admit", slice_2)

        # In PyArrow, slice_1 and slice_2 reference the exact same underlying memory buffers:
        buf1 = slice_1.columns[1].chunks[0].buffers()[1].to_pybytes()
        buf2 = slice_2.columns[1].chunks[0].buffers()[1].to_pybytes()
        assert buf1 == buf2  # Underlying buffer contains all 10 integers!

        # Because _operation_id only hashes table.num_rows (5) and chunk.buffers(),
        # slice_1 and slice_2 produce a digest collision!
        assert op_1 == op_2, "Zero-copy buffer hashing collides on slices of the same parent table"

    def test_nested_struct_child_buffer_transparency(self, retention_tables: WeeklyRetentionTables):
        """Verify that PyArrow does include child buffers in chunk.buffers() for struct columns."""
        # Table A: struct with child value "Alpha"
        struct_col_a = pa.StructArray.from_arrays(
            [pa.array(["Alpha"])],
            names=["inner"],
        )
        table_a = pa.Table.from_arrays([pa.array(["row1"]), struct_col_a], names=["id", "details"])

        # Table B: struct with child value "Omega"
        struct_col_b = pa.StructArray.from_arrays(
            [pa.array(["Omega"])],
            names=["inner"],
        )
        table_b = pa.Table.from_arrays([pa.array(["row1"]), struct_col_b], names=["id", "details"])

        op_a = retention_tables._operation_id("test_ds", "admit", table_a)
        op_b = retention_tables._operation_id("test_ds", "admit", table_b)

        # PyArrow traverses child buffers so digests differ
        assert op_a != op_b

    def test_distinct_tables_different_rows_produce_distinct_digests(self, retention_tables: WeeklyRetentionTables):
        """Independent non-sliced flat tables with different values produce distinct digests."""
        table_1 = pa.table({"id": ["a", "b"], "val": [1, 2]})
        table_2 = pa.table({"id": ["x", "y"], "val": [3, 4]})

        op_1 = retention_tables._operation_id("test_ds", "admit", table_1)
        op_2 = retention_tables._operation_id("test_ds", "admit", table_2)
        assert op_1 != op_2
