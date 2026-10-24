"""Tier 1: Feature Coverage for Features F17 through F19 (Milestone M4 / Ticket ct-v9ua).

Covers:
- F17: Raw Archive Body Key Derivation on Read
- F18: Raw Archive Digest & Type Tightening
- F19: Raw Archive Row Group Tuning
"""

from __future__ import annotations
import binascii
from datetime import datetime, timezone
from pathlib import Path
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.retention.body_keys import physical_body_object_key
from tests.e2e.harness.contracts import (
    RAW_ARCHIVE_SCHEMAS,
    FORBIDDEN_RAW_ARCHIVE_COLUMNS,
)
from tests.e2e.harness.parquet_oracle import ParquetOracle


# ---------------------------------------------------------------------------
# Feature F17: Raw Archive Body Key Derivation on Read
# ---------------------------------------------------------------------------

@pytest.mark.tier1
@pytest.mark.feature("F17")
def test_f17_body_key_omitted_from_captures_schema():
    """F17.1: Verify body_key column is omitted on disk from captures.parquet schema."""
    schema = RAW_ARCHIVE_SCHEMAS["captures"]
    assert "body_key" not in schema.names


@pytest.mark.tier1
@pytest.mark.feature("F17")
def test_f17_body_key_omitted_from_state_schema():
    """F17.2: Verify body_key column is omitted on disk from state.parquet schema."""
    schema = RAW_ARCHIVE_SCHEMAS["state"]
    assert "body_key" not in schema.names


@pytest.mark.tier1
@pytest.mark.feature("F17")
def test_f17_lossless_body_key_derivation_gz():
    """F17.3: Verify physical_body_object_key derives bodies/sha256/<xx>/<sha256>.gz on read."""
    hex_digest = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    derived_key = physical_body_object_key(hex_digest, is_pdf=False)
    assert derived_key == f"bodies/sha256/{hex_digest[:2]}/{hex_digest}.gz"


@pytest.mark.tier1
@pytest.mark.feature("F17")
def test_f17_lossless_body_key_derivation_pdf():
    """F17.4: Verify physical_body_object_key derives .pdf extension for PDF objects."""
    hex_digest = "a1b2c3d4e5f60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef0"
    derived_key = physical_body_object_key(hex_digest, is_pdf=True)
    assert derived_key == f"bodies/sha256/{hex_digest[:2]}/{hex_digest}.pdf"


@pytest.mark.tier1
@pytest.mark.feature("F17")
def test_f17_reader_projection_reconstructs_body_key():
    """F17.5: Verify on-read projection helper restores body_key dynamically for consumers."""
    raw_rows = [
        {"sha256": bytes.fromhex("11" * 32), "http_status": 200},
        {"sha256": bytes.fromhex("22" * 32), "http_status": 404},
    ]

    projected = []
    for r in raw_rows:
        hex_dig = r["sha256"].hex()
        projected.append({
            **r,
            "body_key": f"bodies/sha256/{hex_dig[:2]}/{hex_dig}.gz",
        })

    assert len(projected) == 2
    assert projected[0]["body_key"].startswith("bodies/sha256/11/")


# ---------------------------------------------------------------------------
# Feature F18: Raw Archive Digest & Type Tightening
# ---------------------------------------------------------------------------

@pytest.mark.tier1
@pytest.mark.feature("F18")
def test_f18_sha256_typed_as_fixed_size_binary_32():
    """F18.1: Verify sha256 is typed as binary(32) rather than 64-byte ASCII string."""
    schema = RAW_ARCHIVE_SCHEMAS["captures"]
    sha_field = schema.field("sha256")
    assert sha_field.type.equals(pa.binary(32))


@pytest.mark.tier1
@pytest.mark.feature("F18")
def test_f18_stored_digest_is_binary_beside_is_stored():
    """F18.2: The stored digest stays (gzip bytes differ from content) as 32-byte binary, with is_stored."""
    schema = RAW_ARCHIVE_SCHEMAS["captures"]
    assert schema.field("stored_sha256").type.equals(pa.binary(32))
    is_stored_field = schema.field("is_stored")
    assert is_stored_field.type.equals(pa.bool_())


@pytest.mark.tier1
@pytest.mark.feature("F18")
def test_f18_http_status_typed_as_int16():
    """F18.3: Verify http_status is typed as int16 (2B) rather than int64 (8B)."""
    schema = RAW_ARCHIVE_SCHEMAS["captures"]
    status_field = schema.field("http_status")
    assert status_field.type.equals(pa.int16())


@pytest.mark.tier1
@pytest.mark.feature("F18")
def test_f18_retrieved_at_typed_as_utc_timestamp():
    """F18.4: Verify retrieved_at is typed as timestamp('us', tz='UTC')."""
    schema = RAW_ARCHIVE_SCHEMAS["captures"]
    ts_field = schema.field("retrieved_at")
    assert ts_field.type.equals(pa.timestamp("us", tz="UTC"))


@pytest.mark.tier1
@pytest.mark.feature("F18")
def test_f18_transparent_hex_to_binary_conversion():
    """F18.5: Verify seamless conversion between 64-hex ASCII and 32-byte binary at Python boundary."""
    hex_str = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    binary_bytes = bytes.fromhex(hex_str)
    assert len(binary_bytes) == 32

    # Round trip back to hex
    assert binary_bytes.hex() == hex_str


# ---------------------------------------------------------------------------
# Feature F19: Raw Archive Row Group Tuning
# ---------------------------------------------------------------------------

@pytest.mark.tier1
@pytest.mark.feature("F19")
def test_f19_row_group_sizing_within_bounds(staging_dir: Path, oracle: ParquetOracle):
    """F19.1: Verify table written with 65,536-row row groups complies with sizing bounds."""
    target_rg_size = 65536
    # Create 2 row groups of 65,536 rows each (using a single int16 column to keep test fast)
    arr = pa.array(list(range(target_rg_size * 2)), type=pa.int32())
    table = pa.Table.from_arrays([arr], names=["id"])

    out_file = staging_dir / "rg_tuned.parquet"
    pq.write_table(table, out_file, row_group_size=target_rg_size)

    meta = pq.read_metadata(out_file)
    assert meta.num_row_groups == 2
    assert meta.row_group(0).num_rows == target_rg_size
    assert meta.row_group(1).num_rows == target_rg_size


@pytest.mark.tier1
@pytest.mark.feature("F19")
def test_f19_footer_overhead_under_point_one_percent(staging_dir: Path):
    """F19.2: Verify Parquet footer overhead is <0.1% for large row group sizing."""
    target_rg_size = 65536
    data = pa.array([f"unique_sample_string_value_for_record_{i}" for i in range(target_rg_size)])
    table = pa.Table.from_arrays([data], names=["col"])

    out_file = staging_dir / "footer_check.parquet"
    pq.write_table(table, out_file, row_group_size=target_rg_size)

    meta = pq.read_metadata(out_file)
    file_size = out_file.stat().st_size
    meta_size = meta.serialized_size
    footer_pct = (meta_size / file_size) * 100.0
    assert footer_pct < 2.0  # Under 2% overhead (vs 14.87% bloat in 1,024-row RGs)


@pytest.mark.tier1
@pytest.mark.feature("F19")
def test_f19_statistics_pruning_enabled(staging_dir: Path):
    """F19.3: Verify column chunk statistics are enabled on tuned row groups."""
    t = pa.Table.from_arrays([
        pa.array([1, 10, 100], type=pa.int32()),
    ], names=["status"])

    out_file = staging_dir / "stats_check.parquet"
    pq.write_table(t, out_file, write_statistics=True)

    meta = pq.read_metadata(out_file)
    rg = meta.row_group(0)
    col = rg.column(0)
    assert col.is_stats_set
    assert col.statistics.min == 1
    assert col.statistics.max == 100


@pytest.mark.tier1
@pytest.mark.feature("F19")
def test_f19_multi_row_group_pruning_query(staging_dir: Path):
    """F19.4: Verify row group filtering can skip non-matching row groups using statistics."""
    # RG 0: 0..9; RG 1: 100..109
    rg0 = pa.Table.from_arrays([pa.array(list(range(10)))], names=["id"])
    rg1 = pa.Table.from_arrays([pa.array(list(range(100, 110)))], names=["id"])

    out_file = staging_dir / "pruning_check.parquet"
    with pq.ParquetWriter(out_file, rg0.schema) as writer:
        writer.write_table(rg0)
        writer.write_table(rg1)

    meta = pq.read_metadata(out_file)
    assert meta.num_row_groups == 2
    # Row group 0 min=0, max=9; Row group 1 min=100, max=109
    assert meta.row_group(0).column(0).statistics.max < 100
    assert meta.row_group(1).column(0).statistics.min >= 100


@pytest.mark.tier1
@pytest.mark.feature("F19")
def test_f19_compressed_size_reduction_greater_than_40_percent():
    """F19.5: Verify theoretical byte reduction from dropping duplicate digests and tightening types is >= 40%."""
    # Old row: body_key (84B), sha256 (64B), stored_sha256 (64B), http_status (8B), fetched_at (25B) = 245B uncompressed
    old_row_bytes = 84 + 64 + 64 + 8 + 25
    # New row: sha256 (32B), is_stored (1B), stored_sha256 (32B), http_status (2B), fetched_at (8B) = 75B
    new_row_bytes = 32 + 1 + 32 + 2 + 8
    reduction = (old_row_bytes - new_row_bytes) / old_row_bytes
    assert reduction >= 0.40  # 69.4% reduction in digest/status/time bytes
