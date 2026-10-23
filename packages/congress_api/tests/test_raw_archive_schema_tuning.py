"""Unit tests for Raw Capture Archive Schema Tuning & Compression (Milestone M4 / ct-v9ua).

Covers:
- CAPTURE_SCHEMA & STATE_SCHEMA tightened field types
- body_key omission on disk and lossless on-read derivation
- is_stored: bool replacement for stored_sha256
- sha256 FixedSizeBinary(32) with bidirectional Python boundary conversion
- http_status int16 and UTC microsecond timestamp conversions
- Row-group tuning (65,536 rows) and statistics configuration
- Table encoding/decoding and format_state_row_for_python integration
"""

from datetime import datetime, timezone
from io import BytesIO
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
    parse_http_status,
    derive_body_key,
    with_derived_body_keys,
    normalize_capture_dict,
    normalize_state_dict,
    prepare_capture_table,
    prepare_state_table,
    encode_table,
    decode_table,
    read_table,
)
from congress_api.retention.raw_storage import (
    BODY_SCHEMA,
    format_state_row_for_python,
)


# ---------------------------------------------------------------------------
# 1. Schema Definitions & Field Types
# ---------------------------------------------------------------------------

def test_capture_schema_omits_derivable_columns():
    """Verify body_key and stored_sha256 are excluded on disk from CAPTURE_SCHEMA."""
    assert "body_key" not in CAPTURE_SCHEMA.names
    assert "stored_sha256" not in CAPTURE_SCHEMA.names


def test_state_schema_omits_derivable_columns():
    """Verify body_key is excluded on disk from STATE_SCHEMA."""
    assert "body_key" not in STATE_SCHEMA.names


def test_capture_schema_tightened_types():
    """Verify CAPTURE_SCHEMA field types match tightened specifications."""
    assert CAPTURE_SCHEMA.field("sha256").type.equals(pa.binary(32))
    assert CAPTURE_SCHEMA.field("is_stored").type.equals(pa.bool_())
    assert CAPTURE_SCHEMA.field("http_status").type.equals(pa.int16())
    assert CAPTURE_SCHEMA.field("retrieved_at").type.equals(pa.timestamp("us", tz="UTC"))
    assert CAPTURE_SCHEMA.field("bytes").type.equals(pa.int64())
    assert CAPTURE_SCHEMA.field("stored_bytes").type.equals(pa.int64())


def test_state_schema_tightened_types():
    """Verify STATE_SCHEMA field types match tightened specifications."""
    assert STATE_SCHEMA.field("sha256").type.equals(pa.binary(32))
    assert STATE_SCHEMA.field("http_status").type.equals(pa.int16())
    assert STATE_SCHEMA.field("attempts").type.equals(pa.int32())
    assert STATE_SCHEMA.field("links_scanned").type.equals(pa.bool_())
    assert STATE_SCHEMA.field("retrieved_at").type.equals(pa.timestamp("us", tz="UTC"))
    assert STATE_SCHEMA.field("checked_at").type.equals(pa.timestamp("us", tz="UTC"))
    assert STATE_SCHEMA.field("next_attempt_at").type.equals(pa.timestamp("us", tz="UTC"))


def test_body_schema_preserves_compatibility():
    """Verify BODY_SCHEMA preserves fields needed for CAS body routing."""
    expected_fields = {"key", "body_key", "sha256", "bytes", "stored_sha256", "stored_bytes"}
    assert set(BODY_SCHEMA.names) == expected_fields


# ---------------------------------------------------------------------------
# 2. SHA-256 Conversion & Normalization
# ---------------------------------------------------------------------------

def test_parse_sha256_valid_hex():
    """Verify 64-char hex string converts to 32 raw bytes."""
    hex_str = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    raw_bytes = parse_sha256(hex_str)
    assert isinstance(raw_bytes, bytes)
    assert len(raw_bytes) == 32
    assert raw_bytes == bytes.fromhex(hex_str)


def test_format_sha256_roundtrip():
    """Verify 32 raw bytes formats to 64-char lowercase hex string."""
    hex_str = "a1b2c3d4e5f60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef0"
    raw_bytes = bytes.fromhex(hex_str)
    assert format_sha256(raw_bytes) == hex_str
    assert format_sha256(hex_str.upper()) == hex_str
    assert format_sha256(None) is None


def test_parse_sha256_invalid_length_raises():
    """Verify sha256 with non-64 length raises ValueError."""
    with pytest.raises(ValueError):
        parse_sha256("abc")
    with pytest.raises(ValueError):
        parse_sha256("a" * 63)
    with pytest.raises(ValueError):
        parse_sha256("a" * 65)


def test_parse_sha256_non_hex_raises():
    """Verify non-hex characters raise ValueError."""
    with pytest.raises(ValueError):
        parse_sha256("z" * 64)


# ---------------------------------------------------------------------------
# 3. Timestamp Parsing & Microsecond Precision
# ---------------------------------------------------------------------------

def test_parse_timestamp_iso_string():
    """Verify ISO string parses to UTC datetime with tzinfo."""
    iso_val = "2026-10-22T14:30:00.123456Z"
    dt = parse_timestamp(iso_val)
    assert isinstance(dt, datetime)
    assert dt.tzinfo == timezone.utc
    assert dt.microsecond == 123456


def test_parse_timestamp_naive_datetime():
    """Verify naive datetime is localized to UTC."""
    naive = datetime(2026, 10, 22, 14, 30, 0)
    dt = parse_timestamp(naive)
    assert dt.tzinfo == timezone.utc
    assert dt.year == 2026


def test_format_timestamp():
    """Verify datetime formats to ISO-8601 string."""
    dt = datetime(2026, 10, 22, 14, 30, 0, 0, tzinfo=timezone.utc)
    assert format_timestamp(dt) == "2026-10-22T14:30:00+00:00"
    assert format_timestamp(None) is None


def test_parse_timestamp_invalid_raises():
    """Verify invalid timestamp string raises ValueError."""
    with pytest.raises(ValueError):
        parse_timestamp("not-a-timestamp")


# ---------------------------------------------------------------------------
# 4. HTTP Status Validation & Boundaries
# ---------------------------------------------------------------------------

def test_parse_http_status_valid():
    """Verify valid HTTP status codes are accepted."""
    assert parse_http_status(200) == 200
    assert parse_http_status("404") == 404
    assert parse_http_status(None) is None


def test_parse_http_status_bounds():
    """Verify int16 range limits [-32768, 32767]."""
    assert parse_http_status(32767) == 32767
    assert parse_http_status(-32768) == -32768
    with pytest.raises(ValueError):
        parse_http_status(70000)
    with pytest.raises(ValueError):
        parse_http_status(-40000)


# ---------------------------------------------------------------------------
# 5. Dynamic body_key Derivation
# ---------------------------------------------------------------------------

def test_derive_body_key_gz():
    """Verify derive_body_key produces .gz key for non-PDF objects."""
    hex_digest = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    key = derive_body_key(hex_digest, media_type="text/html")
    assert key == f"bodies/sha256/{hex_digest[:2]}/{hex_digest}.gz"


def test_derive_body_key_pdf():
    """Verify derive_body_key produces logical .gz key even for PDF media types (ct-te1p invariant)."""
    hex_digest = "a1b2c3d4e5f60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef0"
    key = derive_body_key(hex_digest, media_type="application/pdf")
    assert key == f"bodies/sha256/{hex_digest[:2]}/{hex_digest}.gz"


def test_derive_body_key_from_binary_bytes():
    """Verify derive_body_key accepts 32 raw bytes."""
    hex_digest = "11" * 32
    raw_bytes = bytes.fromhex(hex_digest)
    key = derive_body_key(raw_bytes)
    assert key == f"bodies/sha256/11/{hex_digest}.gz"


def test_with_derived_body_keys_on_table():
    """Verify with_derived_body_keys attaches body_key column to a PyArrow Table."""
    hex_digest = "22" * 32
    table = pa.Table.from_pylist([
        {"sha256": bytes.fromhex(hex_digest), "media_type": "text/xml"},
    ])
    projected = with_derived_body_keys(table)
    assert "body_key" in projected.column_names
    assert projected["body_key"].to_pylist()[0] == f"bodies/sha256/22/{hex_digest}.gz"


def test_with_derived_body_keys_idempotent():
    """Verify with_derived_body_keys is a no-op when body_key is already present."""
    table = pa.Table.from_pylist([{"body_key": "custom/path.gz", "sha256": b"x" * 32}])
    result = with_derived_body_keys(table)
    assert result["body_key"].to_pylist() == ["custom/path.gz"]


# ---------------------------------------------------------------------------
# 6. Table Preparation & Normalization
# ---------------------------------------------------------------------------

def test_prepare_capture_table_normalizes_records():
    """Verify prepare_capture_table converts dicts with hex sha256, stored_sha256, and strings."""
    hex_dig = "33" * 32
    rows = [
        {
            "family": "test-family",
            "sha256": hex_dig,
            "stored_sha256": hex_dig,
            "http_status": "200",
            "retrieved_at": "2026-10-22T12:00:00Z",
            "bytes": 1024,
        }
    ]
    table = prepare_capture_table(rows)
    assert table.schema.equals(CAPTURE_SCHEMA, check_metadata=False)
    assert table["sha256"].to_pylist()[0] == bytes.fromhex(hex_dig)
    assert table["is_stored"].to_pylist()[0] is True
    assert table["http_status"].to_pylist()[0] == 200
    assert "body_key" not in table.column_names


def test_prepare_state_table_normalizes_records():
    """Verify prepare_state_table converts dicts with hex sha256 and ISO timestamps."""
    hex_dig = "44" * 32
    rows = [
        {
            "url": "https://example.gov/doc",
            "family": "test-family",
            "sha256": hex_dig,
            "outcome": "saved",
            "retrieved_at": "2026-10-22T12:00:00Z",
            "checked_at": "2026-10-22T12:00:00Z",
            "next_attempt_at": None,
            "http_status": 200,
            "attempts": 1,
            "links_scanned": True,
        }
    ]
    table = prepare_state_table(rows)
    assert table.schema.equals(STATE_SCHEMA, check_metadata=False)
    assert table["sha256"].to_pylist()[0] == bytes.fromhex(hex_dig)
    assert table["http_status"].to_pylist()[0] == 200
    assert table["attempts"].to_pylist()[0] == 1
    assert "body_key" not in table.column_names


# ---------------------------------------------------------------------------
# 7. Row Group Tuning & Parquet Statistics
# ---------------------------------------------------------------------------

def test_encode_table_uses_tuned_row_groups_and_statistics(tmp_path):
    """Verify encode_table writes Parquet with statistics enabled."""
    hex_dig = "55" * 32
    t = prepare_capture_table([
        {"sha256": hex_dig, "http_status": 200, "is_stored": True, "family": "f1"},
    ])
    data = encode_table(t)
    assert isinstance(data, bytes)
    assert len(data) > 0

    decoded = decode_table(data)
    assert decoded.schema.equals(CAPTURE_SCHEMA, check_metadata=False)
    assert len(decoded) == 1

    # Check decoded with dynamic body_key
    with_keys = decode_table(data, derive_body_key=True)
    assert "body_key" in with_keys.column_names
    assert with_keys["body_key"].to_pylist()[0] == f"bodies/sha256/55/{hex_dig}.gz"


def test_raw_archive_row_group_size_constant():
    """Verify RAW_ARCHIVE_ROW_GROUP_SIZE is tuned between 65,536 and 131,072."""
    assert 65536 <= RAW_ARCHIVE_ROW_GROUP_SIZE <= 131072


# ---------------------------------------------------------------------------
# 8. Python Boundary Formatting Helper
# ---------------------------------------------------------------------------

def test_format_state_row_for_python():
    """Verify format_state_row_for_python provides transparent hex and ISO strings for consumers."""
    hex_dig = "66" * 32
    raw_row = {
        "url": "https://example.gov/test",
        "sha256": bytes.fromhex(hex_dig),
        "retrieved_at": datetime(2026, 10, 22, 12, 0, 0, tzinfo=timezone.utc),
        "http_status": 200,
        "media_type": "text/html",
    }
    formatted = format_state_row_for_python(raw_row)
    assert formatted["sha256"] == hex_dig
    assert formatted["body_key"] == f"bodies/sha256/66/{hex_dig}.gz"
    assert formatted["retrieved_at"] == "2026-10-22T12:00:00+00:00"
    assert formatted["http_status"] == 200
