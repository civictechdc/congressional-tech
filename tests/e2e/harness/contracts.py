"""Authoritative Interface Contracts and Schema Specifications for Epic ct-4t6s.

Derived directly from PROJECT.md, ORIGINAL_REQUEST.md, and Spec Miner Survey Baselines.
"""

from __future__ import annotations
import pyarrow as pa

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MAX_CELL_SIZE = 256 * 1024  # 256 KiB = 262,144 bytes strict ceiling
PDF_MAGIC = b"%PDF-"
MAX_UFFFD_RATIO = 0.05  # 5% maximum replacement character threshold

# ---------------------------------------------------------------------------
# 1. Sources Schema (PROJECT.md § Interface Contracts 1)
# ---------------------------------------------------------------------------
NOTE_STRUCT = pa.struct([
    ("label", pa.string()),
    ("value", pa.string()),
])

LINK_STRUCT = pa.struct([
    ("group", pa.string()),
    ("label", pa.string()),
    ("href", pa.string()),
])

SOURCE_SCHEMA = pa.schema([
    ("id", pa.string()),
    ("kind", pa.string()),
    ("provider", pa.string()),
    ("url", pa.string()),
    ("title", pa.string()),
    ("retrieved_at", pa.string()),
    ("source_modified_at", pa.string()),
    ("imported_at", pa.string()),
    ("identifier_scheme", pa.string()),
    ("identifier_value", pa.string()),
    ("identifier_scope", pa.string()),
    ("facts", pa.list_(NOTE_STRUCT)),
    ("links", pa.list_(LINK_STRUCT)),
    ("retained_uri", pa.string()),
    ("retained_sha256", pa.string()),
])

FORBIDDEN_SOURCE_COLUMNS = frozenset({"payload"})

# ---------------------------------------------------------------------------
# 2. Browser Tables (F24 & ct-jnw5)
# ---------------------------------------------------------------------------
MATERIAL_FILE_LINK = pa.struct([
    ("url", pa.string()),
    ("label", pa.string()),
    ("role", pa.string()),
    ("media_type", pa.string()),
    ("version", pa.string()),
    ("published_at", pa.string()),
    ("sha256", pa.string()),
    ("saved_copy_sha256", pa.string()),
    ("saved_filename", pa.string()),
])

ASPECTS_STRUCT = pa.struct([(k, pa.string()) for k in ("recording", "transcript", "documents", "witnesses", "captions")])

BROWSER_TABLE_SCHEMAS: dict[str, pa.Schema] = {
    "committees": pa.schema([
        ("id", pa.string()),
        ("title", pa.string()),
        ("chamber", pa.string()),
        ("congress", pa.int32()),
        ("committee_level", pa.string()),
        ("committee_types", pa.list_(pa.string())),
        ("source_ids", pa.list_(pa.string())),
        ("facts", pa.list_(NOTE_STRUCT)),
        ("committee_type", pa.string()),
        ("source_committee_type", pa.string()),
        ("committee_code", pa.string()),
        ("parent_committee_id", pa.string()),
    ]),
    "meetings": pa.schema([
        ("id", pa.string()),
        ("title", pa.string()),
        ("chamber", pa.string()),
        ("congress", pa.int32()),
        ("committee_ids", pa.list_(pa.string())),
        ("committee_level", pa.string()),
        ("committee_types", pa.list_(pa.string())),
        ("source_ids", pa.list_(pa.string())),
        ("facts", pa.list_(NOTE_STRUCT)),
        ("date", pa.string()),
        ("type", pa.string()),
        ("status", pa.string()),
        ("search_text", pa.string()),
        ("scheduled_at", pa.string()),
        ("access", pa.string()),
        ("evidence_states", ASPECTS_STRUCT),
    ]),
    "materials": pa.schema([
        ("id", pa.string()),
        ("title", pa.string()),
        ("chamber", pa.string()),
        ("congress", pa.int32()),
        ("committee_ids", pa.list_(pa.string())),
        ("committee_level", pa.string()),
        ("committee_types", pa.list_(pa.string())),
        ("source_ids", pa.list_(pa.string())),
        ("facts", pa.list_(NOTE_STRUCT)),
        ("date", pa.string()),
        ("type", pa.string()),
        ("provider", pa.string()),
        ("category", pa.string()),
        ("scheduled_at", pa.string()),
        ("meeting_status", pa.string()),
        ("recording_url", pa.string()),
        ("document_type", pa.string()),
        ("meeting_ids", pa.list_(pa.string())),
        ("source_document_groups", pa.list_(pa.string())),
        ("files", pa.list_(MATERIAL_FILE_LINK)),
    ]),
    "witnesses": pa.schema([
        ("id", pa.string()),
        ("title", pa.string()),
        ("chamber", pa.string()),
        ("congress", pa.int32()),
        ("committee_ids", pa.list_(pa.string())),
        ("committee_level", pa.string()),
        ("committee_types", pa.list_(pa.string())),
        ("source_ids", pa.list_(pa.string())),
        ("facts", pa.list_(NOTE_STRUCT)),
        ("date", pa.string()),
        ("meeting_id", pa.string()),
        ("position", pa.string()),
        ("organization", pa.string()),
        ("participation", pa.string()),
        ("roles", pa.list_(pa.string())),
    ]),
    "issues": pa.schema([
        ("id", pa.string()),
        ("title", pa.string()),
        ("chamber", pa.string()),
        ("congress", pa.int32()),
        ("committee_ids", pa.list_(pa.string())),
        ("committee_level", pa.string()),
        ("committee_types", pa.list_(pa.string())),
        ("source_ids", pa.list_(pa.string())),
        ("facts", pa.list_(NOTE_STRUCT)),
        ("date", pa.string()),
        ("status", pa.string()),
        ("meeting_id", pa.string()),
        ("category", pa.string()),
        ("selection", pa.string()),
        ("severity", pa.string()),
        ("subject_kind", pa.string()),
        ("subject_id", pa.string()),
    ]),
    "sources": SOURCE_SCHEMA,
}

FORBIDDEN_BROWSER_COLUMNS: dict[str, set[str]] = {
    "committees": {"committee_ids", "kind"},
    "meetings": {"meeting_id", "explanation", "kind"},
    "materials": {"appearance_ids", "explanation", "kind"},  # scalar meeting_id removed, meeting_ids kept
    "witnesses": {"search_text", "explanation", "kind"},
    "issues": {"issue_count", "kind"},
}

# ---------------------------------------------------------------------------
# 3. Weekly Retention Normalized Schemas (F9-F15 & ct-q29c)
# ---------------------------------------------------------------------------
WEEKLY_TABLE_SCHEMAS: dict[str, pa.Schema] = {
    "youtube_videos": pa.schema([
        pa.field("system_code", pa.string(), nullable=False),
        pa.field("video_id", pa.string(), nullable=False),
        pa.field("published_at", pa.string(), nullable=False),
        pa.field("title", pa.string(), nullable=True),
        pa.field("upstream_sha256", pa.string(), nullable=True),
    ]),
    "congress_committees": pa.schema([
        pa.field("congress", pa.int64(), nullable=False),
        pa.field("system_code", pa.string(), nullable=False),
        pa.field("chamber", pa.string(), nullable=False),
        pa.field("update_date", pa.string(), nullable=False),
        pa.field("detail_sha256", pa.string(), nullable=True),
    ]),
    "house_events": pa.schema([
        pa.field("event_id", pa.string(), nullable=False),
        pa.field("merge_timestamp", pa.string(), nullable=False),  # imported_at or checked
        pa.field("witness_status", pa.string(), nullable=True),
        pa.field("seed", pa.string(), nullable=True),
        pa.field("source_body_sha256", pa.string(), nullable=True),
    ]),
    "senate_events": pa.schema([
        pa.field("domain", pa.string(), nullable=False),
        pa.field("record_id", pa.string(), nullable=False),
        pa.field("url", pa.string(), nullable=False),
        pa.field("observed_at", pa.string(), nullable=False),
        pa.field("lines_sha256", pa.string(), nullable=True),
    ]),
    "gpo_observations": pa.schema([
        pa.field("package_id", pa.string(), nullable=False),
        pa.field("retrieved_at", pa.string(), nullable=False),
        pa.field("acquisition", pa.string(), nullable=False),
        pa.field("evidence_sha256", pa.string(), nullable=True),
    ]),
    "captions": pa.schema([
        pa.field("source", pa.string(), nullable=False),
        pa.field("native_id", pa.string(), nullable=False),
        pa.field("kind", pa.string(), nullable=True),
        pa.field("outcome", pa.string(), nullable=False),
        pa.field("observed_at", pa.string(), nullable=False),
        pa.field("receipt_json", pa.string(), nullable=True),
    ]),
}

WEEKLY_TABLE_PRIMARY_KEYS: dict[str, tuple[str, ...]] = {
    "youtube_videos": ("system_code", "video_id"),
    "congress_committees": ("congress", "system_code"),
    "house_events": ("event_id",),
    "senate_events": ("domain", "record_id"),
    "gpo_observations": ("package_id",),
    "captions": ("source", "native_id"),
}

WEEKLY_TABLE_ORDER_BY: dict[str, str] = {
    "youtube_videos": "published_at",
    "congress_committees": "update_date",
    "house_events": "merge_timestamp",
    "senate_events": "observed_at",
    "gpo_observations": "retrieved_at",
    "captions": "observed_at",
}

# ---------------------------------------------------------------------------
# 4. Raw Archive Tightened Schemas (F17-F19 & ct-v9ua)
# ---------------------------------------------------------------------------
RAW_ARCHIVE_SCHEMAS: dict[str, pa.Schema] = {
    "captures": pa.schema([
        ("family", pa.string()),
        ("capture_date", pa.string()),
        ("source_file", pa.string()),
        ("source_line", pa.int64()),
        ("receipt_key", pa.string()),
        ("receipt_line", pa.int64()),
        ("reference_kind", pa.string()),
        ("pointer_json", pa.string()),
        ("context_url", pa.string()),
        ("sha256", pa.binary(32)),             # FixedSizeBinary(32)
        ("bytes", pa.int64()),
        ("is_stored", pa.bool_()),             # Replaces stored_sha256
        ("stored_bytes", pa.int64()),
        ("fidelity", pa.string()),
        ("media_type", pa.string()),
        ("retrieved_at", pa.timestamp("us", tz="UTC")),  # UTC microsecond timestamp
        ("http_status", pa.int16()),           # int16 instead of int64
        ("resolution", pa.string()),
        ("original_path", pa.string()),
    ]),
    "state": pa.schema([
        ("url", pa.string()),
        ("family", pa.string()),
        ("sha256", pa.binary(32)),             # FixedSizeBinary(32)
        ("media_type", pa.string()),
        ("fidelity", pa.string()),
        ("retrieved_at", pa.timestamp("us", tz="UTC")),
        ("outcome", pa.string()),
        ("checked_at", pa.timestamp("us", tz="UTC")),
        ("next_attempt_at", pa.timestamp("us", tz="UTC")),
        ("http_status", pa.int16()),
        ("attempts", pa.int32()),
        ("links_scanned", pa.bool_()),
    ]),
}

FORBIDDEN_RAW_ARCHIVE_COLUMNS = frozenset({"body_key", "stored_sha256"})

# ---------------------------------------------------------------------------
# 5. Canonical Catalog & Review Schemas (F20-F23 & ct-8od2)
# ---------------------------------------------------------------------------
FORBIDDEN_CATALOG_TOP_LEVEL_COLUMNS = frozenset({
    f"source_{field}" for field in (
        "associated_url", "attempt", "auth", "boundary", "branch", "bundle",
        "category", "chamber", "classification", "collection", "committee",
        "congress", "context", "date", "description", "disposition", "document",
        "family", "file", "fingerprint", "format", "group", "header", "id",
        "identifier", "index", "item", "key", "kind", "label", "layer", "line",
        "link", "location", "media", "metadata", "mode", "modified", "name",
        "number", "observation", "occurrence", "offset", "order", "origin",
        "package", "page", "parent", "part", "path", "period", "phase",
        "pipeline", "pointer", "position", "prefix", "probe", "program",
        "project", "protocol", "provenance", "provider", "publication",
        "publisher", "purpose", "qualifier", "range", "rate", "raw",
        "reading", "receipt", "record", "reference", "region", "release",
        "repaired", "report", "representation", "resolution", "resource",
        "response", "result", "retained", "revision", "role", "root", "route",
        "row", "rule", "sample", "scale", "scenario", "schema", "scope",
        "score", "section", "seed", "segment", "selection", "sequence",
        "series", "server", "session", "shard", "signature", "site", "size",
        "snapshot", "source", "stage", "stamp", "state", "status", "step",
        "storage", "stream", "string", "structure", "subcommittee", "subject",
        "summary", "system", "table", "tag", "target", "task", "term",
        "tier", "time", "timestamp", "title", "token", "topic", "trace",
        "track", "transcript", "type", "unit", "update", "upstream", "uri",
        "url", "value", "variable", "variant", "vector", "version", "view",
        "viewer", "volume", "watermark", "witness", "zone"
    )
})

FORBIDDEN_REVIEW_ROWS_COLUMNS = frozenset({"record_json", "canonical_url"})

CANONICAL_CATALOG_SCHEMAS = {
    "readings": pa.schema([
        ("retained_page_id", pa.string()),
        ("reading_id", pa.string()),
        ("raw_leaf", pa.string()),
        ("normalized_leaf", pa.string()),
        ("canonical_leaf", pa.string()),
        ("congress", pa.int32()),
        ("document_family", pa.string()),
        ("document_kind", pa.string()),
        ("format", pa.string()),
    ]),
    "review_rows": pa.schema([
        ("id", pa.string()),
        ("url", pa.string()),
        ("sha256", pa.string()),
        ("congress", pa.int32()),
        ("chamber", pa.string()),
        ("title", pa.string()),
        ("format", pa.string()),
        ("http_status", pa.int16()),
        ("fetched_at", pa.timestamp("us", tz="UTC")),
    ]),
}
