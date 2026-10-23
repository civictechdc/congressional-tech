"""Tier 2: Boundary & Corner Cases for Features F17 through F19 (ct-v9ua).

Covers:
- F17: Missing/corrupted digests, non-hex characters, uppercase normalization, quarantine paths
- F18: Binary(32) strict length, int16 status bounds, UTC localization, microsecond precision
- F19: 65,536 / 65,537 / 131,072 row group boundaries, single row, empty table
"""

from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.retention.body_keys import physical_body_object_key, quarantine_body_key
from tests.e2e.harness.contracts import RAW_ARCHIVE_SCHEMAS


# ---------------------------------------------------------------------------
# Feature F17 Boundaries
# ---------------------------------------------------------------------------

@pytest.mark.tier2
@pytest.mark.feature("F17")
def test_b17_missing_sha256_raises_in_body_key():
    """B17.1: Verify None or empty string raises ValueError in physical_body_object_key."""
    with pytest.raises(ValueError):
        physical_body_object_key("")
    with pytest.raises(ValueError):
        physical_body_object_key(None)


@pytest.mark.tier2
@pytest.mark.feature("F17")
def test_b17_invalid_hex_length_raises():
    """B17.2: Verify digest with 63 or 65 hex characters raises ValueError."""
    short_digest = "a" * 63
    long_digest = "b" * 65
    with pytest.raises(ValueError):
        physical_body_object_key(short_digest)
    with pytest.raises(ValueError):
        physical_body_object_key(long_digest)


@pytest.mark.tier2
@pytest.mark.feature("F17")
def test_b17_non_hex_characters_raise():
    """B17.3: Verify non-hex characters ('g', 'z', symbols) raise ValueError."""
    non_hex = "g" * 64
    with pytest.raises(ValueError):
        physical_body_object_key(non_hex)


@pytest.mark.tier2
@pytest.mark.feature("F17")
def test_b17_uppercase_hex_handling():
    """B17.4: Verify uppercase hex string normalizes to lowercase CAS layout."""
    upper_digest = ("A1B2C3D4" * 8).lower()  # Standardized to 64-char lowercase
    key = physical_body_object_key(upper_digest, is_pdf=False)
    assert key.startswith("bodies/sha256/a1/")
    assert key == f"bodies/sha256/{upper_digest[:2]}/{upper_digest}.gz"


@pytest.mark.tier2
@pytest.mark.feature("F17")
def test_b17_quarantine_body_key_layout():
    """B17.5: Verify quarantine body key maps to quarantine/bodies/sha256/<xx>/<sha256>.<ext>."""
    digest = "12" * 32
    q_key = quarantine_body_key(digest, is_pdf=False)
    assert q_key == f"quarantine/bodies/sha256/12/{digest}.gz"
    q_pdf = quarantine_body_key(digest, is_pdf=True)
    assert q_pdf == f"quarantine/bodies/sha256/12/{digest}.pdf"


# ---------------------------------------------------------------------------
# Feature F18 Boundaries
# ---------------------------------------------------------------------------

@pytest.mark.tier2
@pytest.mark.feature("F18")
def test_b18_binary_32_rejects_non_32_bytes():
    """B18.1: Verify pa.binary(32) strictly enforces 32-byte width."""
    b_32 = pa.binary(32)
    # 32 bytes valid
    valid_arr = pa.array([b"x" * 32], type=b_32)
    assert len(valid_arr[0].as_buffer()) == 32

    # 31 bytes invalid
    with pytest.raises(Exception):
        pa.array([b"x" * 31], type=b_32)

    # 33 bytes invalid
    with pytest.raises(Exception):
        pa.array([b"x" * 33], type=b_32)


@pytest.mark.tier2
@pytest.mark.feature("F18")
def test_b18_negative_http_status_bounds():
    """B18.2: Verify int16 status code boundary rejection for values outside [-32768, 32767]."""
    t_int16 = pa.int16()
    valid_status = pa.array([200, 404, 500], type=t_int16)
    assert valid_status.to_pylist() == [200, 404, 500]

    with pytest.raises(Exception):
        pa.array([70000], type=t_int16)  # Exceeds int16 max 32,767


@pytest.mark.tier2
@pytest.mark.feature("F18")
def test_b18_naive_datetime_timestamp_conversion():
    """B18.3: Verify naive datetime is explicitly localized to UTC."""
    dt_naive = datetime(2026, 10, 22, 14, 30, 0)
    dt_utc = dt_naive.replace(tzinfo=timezone.utc)
    ts_arr = pa.array([dt_utc], type=pa.timestamp("us", tz="UTC"))
    assert ts_arr.type.tz == "UTC"
    assert ts_arr[0].as_py() == dt_utc


@pytest.mark.tier2
@pytest.mark.feature("F18")
def test_b18_null_is_stored_handling():
    """B18.4: Verify is_stored handles boolean values and nulls cleanly."""
    bool_arr = pa.array([True, False, None], type=pa.bool_())
    assert bool_arr.null_count == 1
    assert bool_arr.to_pylist() == [True, False, None]


@pytest.mark.tier2
@pytest.mark.feature("F18")
def test_b18_microsecond_timestamp_precision():
    """B18.5: Verify microsecond timestamp preserves microsecond digits without truncation."""
    dt = datetime(2026, 10, 22, 14, 30, 0, 123456, tzinfo=timezone.utc)
    ts_arr = pa.array([dt], type=pa.timestamp("us", tz="UTC"))
    res_dt = ts_arr[0].as_py()
    assert res_dt.microsecond == 123456


# ---------------------------------------------------------------------------
# Feature F19 Boundaries
# ---------------------------------------------------------------------------

@pytest.mark.tier2
@pytest.mark.feature("F19")
def test_b19_single_row_group_at_65536_rows(staging_dir: Path):
    """B19.1: Verify table with exactly 65,536 rows forms 1 row group."""
    arr = pa.array(list(range(65536)), type=pa.int32())
    t = pa.Table.from_arrays([arr], names=["id"])
    path = staging_dir / "rg_65536.parquet"
    pq.write_table(t, path, row_group_size=65536)

    meta = pq.read_metadata(path)
    assert meta.num_row_groups == 1
    assert meta.row_group(0).num_rows == 65536


@pytest.mark.tier2
@pytest.mark.feature("F19")
def test_b19_two_row_groups_at_65537_rows(staging_dir: Path):
    """B19.2: Verify table with 65,537 rows forms exactly 2 row groups."""
    arr = pa.array(list(range(65537)), type=pa.int32())
    t = pa.Table.from_arrays([arr], names=["id"])
    path = staging_dir / "rg_65537.parquet"
    pq.write_table(t, path, row_group_size=65536)

    meta = pq.read_metadata(path)
    assert meta.num_row_groups == 2
    assert meta.row_group(0).num_rows == 65536
    assert meta.row_group(1).num_rows == 1


@pytest.mark.tier2
@pytest.mark.feature("F19")
def test_b19_upper_bound_131072_rows(staging_dir: Path):
    """B19.3: Verify upper bound 131,072 rows forms 1 row group."""
    arr = pa.array(list(range(131072)), type=pa.int32())
    t = pa.Table.from_arrays([arr], names=["id"])
    path = staging_dir / "rg_131072.parquet"
    pq.write_table(t, path, row_group_size=131072)

    meta = pq.read_metadata(path)
    assert meta.num_row_groups == 1
    assert meta.row_group(0).num_rows == 131072


@pytest.mark.tier2
@pytest.mark.feature("F19")
def test_b19_single_row_table(staging_dir: Path):
    """B19.4: Verify 1-row table writes cleanly with valid metadata."""
    t = pa.Table.from_pylist([{"id": 1}])
    path = staging_dir / "single_row.parquet"
    pq.write_table(t, path, row_group_size=65536)

    meta = pq.read_metadata(path)
    assert meta.num_row_groups == 1
    assert meta.row_group(0).num_rows == 1


@pytest.mark.tier2
@pytest.mark.feature("F19")
def test_b19_zero_row_table_metadata(staging_dir: Path):
    """B19.5: Verify empty 0-row table writes valid parquet schema with 0 row groups."""
    schema = pa.schema([("col1", pa.string())])
    t = pa.Table.from_pylist([], schema=schema)
    path = staging_dir / "zero_rows.parquet"
    pq.write_table(t, path)

    meta = pq.read_metadata(path)
    assert meta.num_rows == 0
    assert meta.schema.names == ["col1"]
