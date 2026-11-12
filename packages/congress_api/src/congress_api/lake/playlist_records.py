"""Lake producer for `playlist_records`: the URIs each HLS playlist body lists (ct-9s7b).

One row per playlist body and parser version. The model resolves the literal URIs
against each address the body was fetched from, so a caption segment a held
playlist lists is never published as a recording track.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import pyarrow as pa

from ..parsers.captions import playlist_uris
from ._record_producer import (
    GOOD_FETCH_CAPTURE_SQL, PK, append_record_table, build_record_table,
    create_record_table, normalize_record_sha, source_ast_digest, stage_record_table,
)
from .versions import version_digest
from .video_records import NO_INLINE_SQL

ROOT = Path(__file__).resolve().parents[5]
TABLE_SCHEMA = ROOT / "model/lake/playlist-records.schema.json"
SOURCE = "hls"
URIS = pa.list_(pa.field("element", pa.string(), nullable=False))
ARROW_SCHEMA = pa.schema([
    pa.field("record_sha", pa.binary(32), nullable=False),
    pa.field("parser_version", pa.string(), nullable=False),
    pa.field("status", pa.string(), nullable=False),
    pa.field("error_type", pa.string()),
    pa.field("source", pa.string(), nullable=False),
    pa.field("segments", URIS, nullable=False),
    pa.field("playlists", URIS, nullable=False),
])
SCHEMA = ARROW_SCHEMA

# All held recording playlists may declare child segments. Include mislabeled media
# where the fetch address supplies the playlist extension used by the model.
PLAYLIST_CAPTURE_SQL = """
regexp_like(coalesce(c.url,c.requested_url,c.context_url),'(?i)(?:youtube|youtu[.]be|senate)') AND (
 c.sniffed_format = 'm3u8'
 OR lower(split_part(coalesce(c.media_type,''),';',1)) IN ('application/vnd.apple.mpegurl','application/x-mpegurl')
 OR regexp_like(coalesce(c.url,c.requested_url,c.context_url),'(?i)[.]m3u8(?:[?#]|$)'))
"""
CANDIDATE_SQL = f"""SELECT encode(c.sha256,'hex') AS record_sha,min(coalesce(c.stored_suffix,'')) AS stored_suffix,'{SOURCE}' AS source
FROM captures c WHERE {GOOD_FETCH_CAPTURE_SQL} AND {PLAYLIST_CAPTURE_SQL} GROUP BY c.sha256"""


def current_versions(*, root: Path = ROOT) -> dict[str, str]:
    package = Path(__file__).resolve().parents[1]
    # Only the playlist reader's own definition, so other caption code can change without a re-read.
    return {SOURCE: version_digest(packages={}, files={
        "producer": Path(__file__),
        "shared_producer": package / "lake/_record_producer.py",
        "schema": Path(root) / "model/lake/playlist-records.schema.json",
    }, values={"source": SOURCE, "parser": source_ast_digest(package / "parsers/captions.py", ["playlist_uris"])})}


def build_row(record_sha: str | bytes, source: str, payload: bytes | str, *, parser_version: str) -> dict[str, Any]:
    if source != SOURCE:
        raise ValueError(f"Unsupported playlist_records source {source!r}")
    try:
        text = payload if isinstance(payload, str) else bytes(payload).decode("utf-8-sig")
    except UnicodeDecodeError:
        parsed = dict(status="error", error_type="not_utf8", segments=[], playlists=[])
    else:
        parsed = playlist_uris(text)
    return dict(record_sha=normalize_record_sha(record_sha), parser_version=str(parser_version), source=source, **parsed)


def table(rows: Sequence[Mapping[str, Any]]) -> pa.Table:
    return build_record_table(rows, payload_col="segments", schema=ARROW_SCHEMA, extra_cols=("playlists",))


def stage(*, captures: Any, engine: Any, work: Path, existing: Any = None, local_root: Path | str | None = None,
          raw_store: Any = None, unreadable_files: Sequence[Mapping[str, Any]] = (), parser_version: str | Mapping[str, str] | None = None,
          max_work_items: int | None = None, decided_at: str | None = None, unreadable_store: Any = None) -> dict[str, Any]:
    """Stage missing rows from `captures`; nothing is written to the lake here."""
    return stage_record_table(parser_name="playlist_records", out_filename="playlist-records.parquet",
        candidate_sql=CANDIDATE_SQL, inline_sql=NO_INLINE_SQL, build_row_fn=build_row, table_fn=table,
        captures=captures, engine=engine, work=work, version=current_versions() if parser_version is None else parser_version,
        existing=existing, local_root=local_root, raw_store=raw_store, unreadable_files=unreadable_files,
        max_work_items=max_work_items, decided_at=decided_at, unreadable_store=unreadable_store)


__all__ = ["ARROW_SCHEMA", "CANDIDATE_SQL", "PK", "SCHEMA", "SOURCE", "build_row", "current_versions", "stage", "table"]


def create_table(*, engine, work, catalog_root, table, location, create_namespace=False):
    return create_record_table(schema_path=TABLE_SCHEMA, engine=engine, work=work,
        catalog_root=catalog_root, table=table, location=location, create_namespace=create_namespace)


def append(staged, *, engine, work, catalog_root, table):
    return append_record_table(staged, parser_name="playlist_records", default_version="", current_version_fn=current_versions,
        engine=engine, work=work, catalog_root=catalog_root, table=table)
