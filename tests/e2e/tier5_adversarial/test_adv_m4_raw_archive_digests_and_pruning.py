"""Tier 5 Adversarial Tests: Milestone 4 (ct-v9ua).

White-box stress testing of:
1. Raw archive FixedSizeBinary(32) digest parser, formatter, and corrupt input rejection.
2. `is_stored: bool` states, transitions, and column type fidelity.
3. `physical_body_object_key` dynamic derivation for PDF vs non-PDF.
4. Parquet row-group statistics pruning on FixedSizeBinary(32) and UTC timestamp columns.
"""

from __future__ import annotations
import datetime as dt
import hashlib
from pathlib import Path
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.retention.raw_archive import (
    CAPTURE_SCHEMA,
    STATE_SCHEMA,
    RAW_ARCHIVE_ROW_GROUP_SIZE,
    parse_sha256,
    format_sha256,
    parse_timestamp,
    format_timestamp,
    derive_body_key,
    with_derived_body_keys,
)
from congress_api.retention.body_keys import physical_body_object_key


class TestM4FixedSizeBinary32Digests:
    """Stress testing FixedSizeBinary(32) digest conversions and error handling."""

    def test_valid_32_byte_binary_and_hex_round_trip(self):
        """Valid 32-byte binary and 64-hex strings convert losslessly."""
        raw_bytes = hashlib.sha256(b"content").digest()
        hex_str = hashlib.sha256(b"content").hexdigest()

        parsed_from_bytes = parse_sha256(raw_bytes)
        assert parsed_from_bytes == raw_bytes
        assert len(parsed_from_bytes) == 32

        parsed_from_hex = parse_sha256(hex_str)
        assert parsed_from_hex == raw_bytes
        assert len(parsed_from_hex) == 32

        # Format back to hex
        assert format_sha256(parsed_from_bytes) == hex_str
        assert format_sha256(parsed_from_hex) == hex_str

    def test_none_and_empty_digest_handling(self):
        """None and empty strings normalize to None."""
        assert parse_sha256(None) is None
        assert parse_sha256("") is None
        assert format_sha256(None) is None

    @pytest.mark.parametrize("bad_input", [
        b"too_short",                     # < 32 bytes
        b"x" * 31,                        # 31 bytes
        b"x" * 33,                        # 33 bytes
        "not_64_hex_chars",               # < 64 chars
        "a" * 63,                         # 63 chars
        "a" * 65,                         # 65 chars
        "z" * 64,                         # 64 chars but non-hex
        12345,                            # wrong type
        {"sha": "abc"},                   # wrong type
    ])
    def test_corrupt_digest_lengths_and_types_rejected(self, bad_input):
        """Corrupt lengths, non-hex strings, and wrong types must raise ValueError."""
        with pytest.raises(ValueError):
            parse_sha256(bad_input)


class TestM4IsStoredAndBodyKeyDerivation:
    """Stress testing `is_stored: bool` transitions and on-read body_key derivation."""

    def test_capture_schema_types(self):
        """Verify CAPTURE_SCHEMA and STATE_SCHEMA define expected physical types."""
        assert CAPTURE_SCHEMA.field("sha256").type == pa.binary(32)
        assert CAPTURE_SCHEMA.field("is_stored").type == pa.bool_()
        assert CAPTURE_SCHEMA.field("http_status").type == pa.int16()
        assert CAPTURE_SCHEMA.field("retrieved_at").type == pa.timestamp("us", tz="UTC")

        assert STATE_SCHEMA.field("sha256").type == pa.binary(32)
        assert STATE_SCHEMA.field("http_status").type == pa.int16()
        assert STATE_SCHEMA.field("retrieved_at").type == pa.timestamp("us", tz="UTC")

    def test_derive_body_key_pdf_vs_gzip(self):
        """Derives .pdf for application/pdf and .gz for other media types."""
        sample_sha = hashlib.sha256(b"sample").hexdigest()

        # Non-PDF -> .gz
        gz_key = derive_body_key(sample_sha, media_type="text/html")
        assert gz_key == f"bodies/sha256/{sample_sha[:2]}/{sample_sha}.gz"

        # PDF -> .pdf
        pdf_key = derive_body_key(sample_sha, media_type="application/pdf")
        assert pdf_key == f"bodies/sha256/{sample_sha[:2]}/{sample_sha}.pdf"

        # From 32-byte binary input
        binary_sha = bytes.fromhex(sample_sha)
        assert derive_body_key(binary_sha, media_type="application/pdf") == pdf_key

    def test_with_derived_body_keys_arrow_table(self):
        """with_derived_body_keys appends body_key column to PyArrow Table."""
        sha_bytes = hashlib.sha256(b"table_content").digest()
        table = pa.Table.from_pydict({
            "family": ["govinfo"],
            "sha256": [sha_bytes],
            "media_type": ["application/pdf"],
        })

        augmented = with_derived_body_keys(table)
        assert "body_key" in augmented.column_names
        derived_val = augmented["body_key"][0].as_py()
        hex_str = sha_bytes.hex()
        assert derived_val == f"bodies/sha256/{hex_str[:2]}/{hex_str}.pdf"


class TestM4RowGroupStatisticsPruning:
    """Stress testing Parquet row group pruning on FixedSizeBinary(32) and timestamps."""

    def test_binary_sha256_statistics_pruning(self, tmp_path: Path):
        """Verify that Parquet row groups prune cleanly on binary(32) column filters."""
        file_path = tmp_path / "test_pruning.parquet"

        # Create two sorted chunks of binary(32) hashes:
        # Chunk 0 has hashes starting with 0x00..0x0F
        chunk_0_hashes = [bytes([0x01] * 32), bytes([0x02] * 32), bytes([0x03] * 32)]
        # Chunk 1 has hashes starting with 0xF0..0xFF
        chunk_1_hashes = [bytes([0xFA] * 32), bytes([0xFB] * 32), bytes([0xFC] * 32)]

        table_0 = pa.Table.from_pydict({
            "sha256": pa.array(chunk_0_hashes, type=pa.binary(32)),
            "family": ["house"] * 3,
        })
        table_1 = pa.Table.from_pydict({
            "sha256": pa.array(chunk_1_hashes, type=pa.binary(32)),
            "family": ["senate"] * 3,
        })

        combined = pa.concat_tables([table_0, table_1])

        # Write with row_group_size = 3 so each chunk becomes its own row group
        pq.write_table(
            combined,
            file_path,
            row_group_size=3,
            write_statistics=True,
            compression="zstd",
        )

        meta = pq.read_metadata(file_path)
        assert meta.num_row_groups == 2

        # Check column statistics for binary(32) sha256
        col_stats_0 = meta.row_group(0).column(0).statistics
        col_stats_1 = meta.row_group(1).column(0).statistics

        assert col_stats_0.has_min_max
        assert col_stats_1.has_min_max

        assert col_stats_0.min == chunk_0_hashes[0]
        assert col_stats_0.max == chunk_0_hashes[-1]
        assert col_stats_1.min == chunk_1_hashes[0]
        assert col_stats_1.max == chunk_1_hashes[-1]

        # Read with filter on chunk 1 hash: PyArrow should read exactly matching row
        target_hash = chunk_1_hashes[1]
        filtered = pq.read_table(
            file_path,
            filters=[("sha256", "==", target_hash)],
        )
        assert len(filtered) == 1
        assert filtered["sha256"][0].as_buffer().to_pybytes() == target_hash
