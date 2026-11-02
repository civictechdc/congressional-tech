"""Lake producer for `video_records`: typed channels and uploads of retained YouTube caches,
and the videos of retained YouTube Data API videoListResponse bodies (source `youtube_api`).

One row per body, source and parser version. Upstream API JSON stays in the body, which
`record_sha` references; it is about 231 MB of 267 MB and is evidence, not a queryable fact.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import pyarrow as pa

from ..parsers.youtube_video import api_rows, cache_rows
from ._record_producer import PK, build_record_table, normalize_record_sha, stage_record_table
from .versions import version_digest

ROOT = Path(__file__).resolve().parents[5]
TABLE_SCHEMA = ROOT / "model/lake/video-records.schema.json"
SOURCE = "youtube_cache"
API_SOURCE = "youtube_api"
SOURCES = (SOURCE, API_SOURCE)
CANDIDATE_BODIES_SQL = ROOT / "model/sql/youtube-cache-bodies.sql"
API_BODIES_SQL = ROOT / "model/sql/youtube-api-bodies.sql"
NO_INLINE_SQL = "SELECT cast(NULL AS VARCHAR) AS receipt_key,cast(NULL AS INT) AS receipt_line,cast(NULL AS VARCHAR) AS source_url WHERE false"

CHANNEL_STRUCT = pa.struct([
    pa.field("handle", pa.string(), nullable=False),
    pa.field("channel_id", pa.string()),
    pa.field("title", pa.string()),
    pa.field("custom_url", pa.string()),
    pa.field("uploads_scan_complete", pa.bool_()),
])
VIDEO_STRUCT = pa.struct([
    pa.field("handle", pa.string(), nullable=False),
    pa.field("video_id", pa.string(), nullable=False),
    pa.field("channel_id", pa.string()),
    pa.field("channel_title", pa.string()),
    pa.field("title", pa.string()),
    pa.field("description", pa.string()),
    pa.field("published_at", pa.string()),
    pa.field("video_published_at", pa.string()),
    pa.field("duration_seconds", pa.int32()),
    pa.field("available", pa.bool_()),
    pa.field("has_caption", pa.bool_()),
    pa.field("details_checked_at", pa.string()),
    pa.field("stated_event_ids", pa.list_(pa.field("element", pa.int64(), nullable=False)), nullable=False),
])
ARROW_SCHEMA = pa.schema([
    pa.field("record_sha", pa.binary(32), nullable=False),
    pa.field("parser_version", pa.string(), nullable=False),
    pa.field("status", pa.string(), nullable=False),
    pa.field("error_type", pa.string()),
    pa.field("source", pa.string(), nullable=False),
    pa.field("channels", pa.list_(pa.field("element", CHANNEL_STRUCT, nullable=False)), nullable=False),
    pa.field("videos", pa.list_(pa.field("element", VIDEO_STRUCT, nullable=False)), nullable=False),
])
SCHEMA = ARROW_SCHEMA


def current_versions(*, root: Path = ROOT) -> dict[str, str]:
    package = Path(__file__).resolve().parents[1]
    files = {"producer": Path(__file__), "parser": package / "parsers/youtube_video.py",
             "schema": Path(root) / "model/lake/video-records.schema.json"}
    return {SOURCE: version_digest(packages={}, files={**files,
        "cache": package.parents[1].parent / "congress_shared/src/congress_shared/youtube_cache.py",
        "selection": Path(root) / "model/sql/youtube-cache-bodies.sql",
    }, values={"source": SOURCE}), API_SOURCE: version_digest(packages={}, files={**files,
        "selection": Path(root) / "model/sql/youtube-api-bodies.sql",
    }, values={"source": API_SOURCE})}


def candidate_sql(*, root: Path = ROOT) -> str:
    """The latest good body per cache path, and each retained API body, under the rules the model selects with."""
    cache = (Path(root) / "model/sql/youtube-cache-bodies.sql").read_text()
    api = (Path(root) / "model/sql/youtube-api-bodies.sql").read_text()
    return (f"SELECT record_sha,stored_suffix,'{SOURCE}' AS source FROM ({cache}) s "
            f"UNION ALL SELECT record_sha,stored_suffix,'{API_SOURCE}' AS source FROM ({api}) a")


def build_row(record_sha: str | bytes, source: str, payload: bytes | str, *, parser_version: str) -> dict[str, Any]:
    if source == API_SOURCE:
        channels, videos = [], api_rows(payload)
    elif source == SOURCE:
        channels, videos = cache_rows(payload)
    else:
        raise ValueError(f"Unsupported video_records source {source!r}")
    return dict(record_sha=normalize_record_sha(record_sha), parser_version=str(parser_version), status="completed",
        error_type=None, source=source, channels=channels, videos=videos)


def table(rows: Sequence[Mapping[str, Any]]) -> pa.Table:
    return build_record_table(rows, payload_col="videos", schema=ARROW_SCHEMA, extra_cols=("channels",))


def stage(*, captures: Any, engine: Any, work: Path, existing: Any = None, local_root: Path | str | None = None,
          raw_store: Any = None, unreadable_files: Sequence[Mapping[str, Any]] = (), parser_version: str | Mapping[str, str] | None = None,
          max_work_items: int | None = None, decided_at: str | None = None, unreadable_store: Any = None) -> dict[str, Any]:
    """Stage missing rows from `captures`; nothing is written to the lake here."""
    return stage_record_table(parser_name="video_records", out_filename="video-records.parquet",
        candidate_sql=candidate_sql(), inline_sql=NO_INLINE_SQL, build_row_fn=build_row, table_fn=table,
        captures=captures, engine=engine, work=work, version=current_versions() if parser_version is None else parser_version,
        existing=existing, local_root=local_root, raw_store=raw_store, unreadable_files=unreadable_files,
        max_work_items=max_work_items, decided_at=decided_at, unreadable_store=unreadable_store)


__all__ = ["API_SOURCE", "ARROW_SCHEMA", "PK", "SCHEMA", "SOURCE", "SOURCES", "build_row", "candidate_sql", "current_versions", "stage", "table"]
