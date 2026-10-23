"""Arrow schemas and record normalizers for raw capture and state tables.

Extracted from raw_archive.py to decouple raw_storage and raw_archive,
breaking circular import dependencies.
"""
from datetime import datetime, timezone
import pyarrow as pa
import pyarrow.parquet as pq


CAPTURE_SCHEMA = pa.schema([
    ("family", pa.string()),
    ("capture_date", pa.string()),
    ("source_file", pa.string()),
    ("source_line", pa.int64()),
    ("receipt_key", pa.string()),
    ("receipt_line", pa.int64()),
    ("reference_kind", pa.string()),
    ("pointer_json", pa.string()),
    ("context_url", pa.string()),
    ("sha256", pa.binary(32)),
    ("bytes", pa.int64()),
    ("is_stored", pa.bool_()),
    ("stored_bytes", pa.int64()),
    ("fidelity", pa.string()),
    ("media_type", pa.string()),
    ("retrieved_at", pa.timestamp("us", tz="UTC")),
    ("http_status", pa.int16()),
    ("resolution", pa.string()),
    ("original_path", pa.string()),
])

STATE_SCHEMA = pa.schema([
    ("url", pa.string()),
    ("family", pa.string()),
    ("sha256", pa.binary(32)),
    ("media_type", pa.string()),
    ("fidelity", pa.string()),
    ("retrieved_at", pa.timestamp("us", tz="UTC")),
    ("outcome", pa.string()),
    ("checked_at", pa.timestamp("us", tz="UTC")),
    ("next_attempt_at", pa.timestamp("us", tz="UTC")),
    ("http_status", pa.int16()),
    ("attempts", pa.int32()),
    ("links_scanned", pa.bool_()),
])

LEGACY_CAPTURE_SCHEMA = pa.schema([
    ("family", pa.string()),
    ("capture_date", pa.string()),
    ("source_file", pa.string()),
    ("source_line", pa.int64()),
    ("receipt_key", pa.string()),
    ("receipt_line", pa.int64()),
    ("reference_kind", pa.string()),
    ("pointer_json", pa.string()),
    ("context_url", pa.string()),
    ("body_key", pa.string()),
    ("sha256", pa.string()),
    ("bytes", pa.int64()),
    ("stored_sha256", pa.string()),
    ("stored_bytes", pa.int64()),
    ("fidelity", pa.string()),
    ("media_type", pa.string()),
    ("retrieved_at", pa.string()),
    ("http_status", pa.int64()),
    ("resolution", pa.string()),
    ("original_path", pa.string()),
])

LEGACY_STATE_SCHEMA = pa.schema([
    ("url", pa.string()),
    ("family", pa.string()),
    ("body_key", pa.string()),
    ("sha256", pa.string()),
    ("media_type", pa.string()),
    ("fidelity", pa.string()),
    ("retrieved_at", pa.string()),
    ("outcome", pa.string()),
    ("checked_at", pa.string()),
    ("next_attempt_at", pa.string()),
    ("http_status", pa.int64()),
    ("attempts", pa.int64()),
    ("links_scanned", pa.bool_()),
])

RAW_ARCHIVE_ROW_GROUP_SIZE = 65536


def parse_sha256(val):
    """Normalize sha256 input to 32 bytes or None."""
    if val is None:
        return None
    if isinstance(val, (bytes, bytearray)):
        if len(val) == 32:
            return bytes(val)
        if len(val) == 64:
            try:
                return bytes.fromhex(bytes(val).decode("ascii"))
            except Exception as e:
                raise ValueError(f"Invalid sha256 bytes hex: {val!r}") from e
        raise ValueError(f"Invalid sha256 bytes length: {len(val)}")
    if isinstance(val, str):
        if not val:
            return None
        if len(val) != 64:
            raise ValueError(f"Invalid sha256 hex string length {len(val)}, expected 64")
        try:
            return bytes.fromhex(val)
        except Exception as e:
            raise ValueError(f"Invalid sha256 hex string: {val!r}") from e
    raise ValueError(f"Invalid sha256 type: {type(val)}")


def format_sha256(val):
    """Format 32-byte sha256 binary as 64-character lowercase hex string."""
    if val is None:
        return None
    if isinstance(val, (bytes, bytearray)):
        if len(val) == 32:
            return bytes(val).hex()
        if len(val) == 64:
            return bytes(val).decode("ascii")
        return bytes(val).hex()
    if isinstance(val, str):
        return val.lower()
    return str(val).lower()


def parse_timestamp(val):
    """Normalize timestamp input to UTC datetime with tzinfo=timezone.utc."""
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc)
    if isinstance(val, str):
        cleaned = val.strip()
        if not cleaned:
            return None
        try:
            s = cleaned.replace("Z", "+00:00") if cleaned.endswith("Z") else cleaned
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception as e:
            raise ValueError(f"Invalid timestamp string: {val!r}") from e
    return val


def format_timestamp(val):
    """Format UTC datetime as ISO-8601 string."""
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            val = val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc).isoformat()
    if isinstance(val, str):
        return val
    return str(val)


def parse_http_status(val):
    """Validate and cast HTTP status code to int16 range."""
    if val is None:
        return None
    status = int(val)
    if not (-32768 <= status <= 32767):
        raise ValueError(f"http_status {status} exceeds int16 range")
    return status


def derive_body_key(sha256_val, media_type=None):
    """Derive CAS body_key dynamically from sha256 and media_type."""
    if sha256_val is None:
        return None
    hex_str = format_sha256(sha256_val)
    if not hex_str:
        return None
    from congress_api.retention.body_keys import physical_body_object_key
    return physical_body_object_key(hex_str, content_type_or_format=media_type)


def with_derived_body_keys(table_or_rows):
    """Add derived body_key column or field to PyArrow table or row list."""
    if isinstance(table_or_rows, pa.Table):
        if "body_key" in table_or_rows.column_names:
            return table_or_rows
        sha_col = (
            table_or_rows["sha256"].to_pylist()
            if "sha256" in table_or_rows.column_names
            else [None] * len(table_or_rows)
        )
        media_col = (
            table_or_rows["media_type"].to_pylist()
            if "media_type" in table_or_rows.column_names
            else [None] * len(table_or_rows)
        )
        body_keys = [derive_body_key(s, m) for s, m in zip(sha_col, media_col)]
        idx = table_or_rows.schema.get_field_index("sha256")
        if idx != -1:
            return table_or_rows.add_column(idx, "body_key", pa.array(body_keys, type=pa.string()))
        return table_or_rows.append_column("body_key", pa.array(body_keys, type=pa.string()))
    elif isinstance(table_or_rows, list):
        return [
            {
                **r,
                "body_key": r.get("body_key")
                or derive_body_key(r.get("sha256"), r.get("media_type")),
            }
            for r in table_or_rows
        ]
    return table_or_rows


def normalize_capture_dict(d):
    """Normalize a capture record dictionary to match CAPTURE_SCHEMA."""
    if not isinstance(d, dict):
        return d
    sha = parse_sha256(d.get("sha256"))
    if sha is None and d.get("body_key"):
        from congress_api.retention.body_keys import body_key_digest
        b_digest = body_key_digest(d.get("body_key"))
        if b_digest:
            sha = parse_sha256(b_digest)
    stored_sha = d.get("stored_sha256")
    if "is_stored" in d and d["is_stored"] is not None:
        is_stored = bool(d["is_stored"])
    elif stored_sha is not None:
        sha_hex = format_sha256(sha)
        stored_hex = format_sha256(stored_sha)
        is_stored = bool(stored_hex and (sha_hex is None or stored_hex == sha_hex))
    else:
        is_stored = False if sha is not None else None

    return {
        "family": d.get("family"),
        "capture_date": d.get("capture_date"),
        "source_file": d.get("source_file"),
        "source_line": d.get("source_line"),
        "receipt_key": d.get("receipt_key"),
        "receipt_line": d.get("receipt_line"),
        "reference_kind": d.get("reference_kind"),
        "pointer_json": d.get("pointer_json"),
        "context_url": d.get("context_url"),
        "sha256": sha,
        "bytes": d.get("bytes"),
        "is_stored": is_stored,
        "stored_bytes": d.get("stored_bytes"),
        "fidelity": d.get("fidelity"),
        "media_type": d.get("media_type"),
        "retrieved_at": parse_timestamp(d.get("retrieved_at")),
        "http_status": parse_http_status(d.get("http_status")),
        "resolution": d.get("resolution"),
        "original_path": d.get("original_path"),
    }


def normalize_state_dict(d):
    """Normalize a state record dictionary to match STATE_SCHEMA."""
    if not isinstance(d, dict):
        return d
    return {
        "url": d.get("url"),
        "family": d.get("family"),
        "sha256": parse_sha256(d.get("sha256")),
        "media_type": d.get("media_type"),
        "fidelity": d.get("fidelity"),
        "retrieved_at": parse_timestamp(d.get("retrieved_at")),
        "outcome": d.get("outcome"),
        "checked_at": parse_timestamp(d.get("checked_at")),
        "next_attempt_at": parse_timestamp(d.get("next_attempt_at")),
        "http_status": parse_http_status(d.get("http_status")),
        "attempts": int(d["attempts"]) if d.get("attempts") is not None else None,
        "links_scanned": bool(d["links_scanned"]) if d.get("links_scanned") is not None else None,
    }


def prepare_capture_table(rows):
    """Produce a validated pa.Table matching CAPTURE_SCHEMA."""
    if isinstance(rows, pa.Table):
        if rows.schema.equals(CAPTURE_SCHEMA, check_metadata=False):
            return rows
        rows = rows.to_pylist()
    normalized = [normalize_capture_dict(r) for r in rows]
    return pa.Table.from_pylist(normalized, schema=CAPTURE_SCHEMA)


def prepare_state_table(rows, schema=None):
    """Produce a validated pa.Table matching STATE_SCHEMA or extended state schema."""
    target_schema = schema or STATE_SCHEMA
    if isinstance(rows, pa.Table):
        if rows.schema.equals(target_schema, check_metadata=False):
            return rows
        rows = rows.to_pylist()
    normalized = [normalize_state_dict(r) for r in rows]
    return pa.Table.from_pylist(normalized, schema=target_schema)


def encode_table(table, *, row_group_size=RAW_ARCHIVE_ROW_GROUP_SIZE, write_statistics=True):
    stream = pa.BufferOutputStream()
    pq.write_table(
        table,
        stream,
        compression="zstd",
        row_group_size=row_group_size,
        write_statistics=write_statistics,
    )
    return stream.getvalue().to_pybytes()

