"""Lake producer for `transcript_headings`: who a GPO printed hearing's own transcript seats at the table (ct-sfra).

One row per GovInfo hearing HTML body (`.../html/CHRG-<n>[hsj]hrg<n>.htm`, fetched directly or as a ZIP member) and
parser version: its testimony headings, the people they name and its committee roster page
(parsers.gpo_headings). Context-free: the model binds each body to its print through captures and decides, from the
print's entries, whether a person the index names appeared (owner decision 2026-11-11, 'Transcripts decide in the
rule'). Each body is read once; bytes that are not UTF-8 read as U+FFFD (headings are ASCII).
Cost: O(B) per body in its bytes; the Phase A sample measured 2.8 ms a print and 2.39 GB of stored gzip for one body
of each of the 34,595 prints with a transcript.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import pyarrow as pa

from ..parsers.gpo import parse_transcript_html
from ..parsers.gpo_headings import transcript_entries
from ._record_producer import (
    GOOD_FETCH_CAPTURE_SQL, PK, append_record_table, build_record_table,
    create_record_table, normalize_record_sha, source_ast_digest, stage_record_table,
)
from .versions import version_digest
from .video_records import NO_INLINE_SQL

ROOT = Path(__file__).resolve().parents[5]
TABLE_SCHEMA = ROOT / "model/lake/transcript-headings.schema.json"
SOURCE = "gpo_html"
ENTRY = pa.struct([
    pa.field("kind", pa.string(), nullable=False),
    pa.field("name", pa.string(), nullable=False),
    pa.field("family", pa.string(), nullable=False),
    pa.field("given", pa.string(), nullable=False),
    pa.field("style", pa.string()),
    pa.field("line", pa.int32()),
])
ARROW_SCHEMA = pa.schema([
    pa.field("record_sha", pa.binary(32), nullable=False),
    pa.field("parser_version", pa.string(), nullable=False),
    pa.field("status", pa.string(), nullable=False),
    pa.field("error_type", pa.string()),
    pa.field("source", pa.string(), nullable=False),
    pa.field("entries", pa.list_(pa.field("element", ENTRY, nullable=False)), nullable=False),
])
SCHEMA = ARROW_SCHEMA

# The print's HTML rendition, at its own address or as a ZIP member (member_path wins: the ZIP's URL is not it).
TRANSCRIPT_ADDRESS = "coalesce(c.member_path,c.url,c.requested_url,c.context_url,'')"
TRANSCRIPT_CAPTURE_SQL = f"regexp_like({TRANSCRIPT_ADDRESS},'(?i)(?:^|/)html/CHRG-[0-9]+[hsj]hrg[0-9]+[.]htm$')"
CANDIDATE_SQL = f"""SELECT encode(c.sha256,'hex') AS record_sha,min(coalesce(c.stored_suffix,'')) AS stored_suffix,'{SOURCE}' AS source
FROM captures c WHERE {GOOD_FETCH_CAPTURE_SQL} AND {TRANSCRIPT_CAPTURE_SQL} GROUP BY c.sha256"""


def current_versions(*, root: Path = ROOT) -> dict[str, str]:
    package = Path(__file__).resolve().parents[1]
    return {SOURCE: version_digest(packages={}, files={
        "producer": Path(__file__),
        "shared_producer": package / "lake/_record_producer.py",
        "reader": package / "parsers/gpo_headings.py",
        "schema": Path(root) / "model/lake/transcript-headings.schema.json",
    }, values={"source": SOURCE,
               # Only the definitions the reader uses from shared modules, so their other code can change freely.
               "html": source_ast_digest(package / "parsers/gpo.py", ["parse_transcript_html"]),
               "roster": source_ast_digest(package / "parsers/gpo_text.py", ["ROSTER_LINE", "ROLE_WORDS", "roster"]),
               "person_key": source_ast_digest(package / "parsers/witness_names.py", ["person_key"])})}


def build_row(record_sha: str | bytes, source: str, payload: bytes | str, *, parser_version: str) -> dict[str, Any]:
    if source != SOURCE:
        raise ValueError(f"Unsupported transcript_headings source {source!r}")
    data = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
    try:
        text = parse_transcript_html(data).text
    except UnicodeDecodeError:
        text = parse_transcript_html(data, decoded_text=data.decode("utf-8", "replace")).text
    return dict(record_sha=normalize_record_sha(record_sha), parser_version=str(parser_version), source=source,
                status="completed", error_type=None, entries=transcript_entries(text))


def table(rows: Sequence[Mapping[str, Any]]) -> pa.Table:
    return build_record_table(rows, payload_col="entries", schema=ARROW_SCHEMA)


def stage(*, captures: Any, engine: Any, work: Path, existing: Any = None, local_root: Path | str | None = None,
          raw_store: Any = None, unreadable_files: Sequence[Mapping[str, Any]] = (), parser_version: str | Mapping[str, str] | None = None,
          max_work_items: int | None = None, decided_at: str | None = None, unreadable_store: Any = None) -> dict[str, Any]:
    """Stage missing rows from `captures`; nothing is written to the lake here."""
    return stage_record_table(parser_name="transcript_headings", out_filename="transcript-headings.parquet",
        candidate_sql=CANDIDATE_SQL, inline_sql=NO_INLINE_SQL, build_row_fn=build_row, table_fn=table,
        captures=captures, engine=engine, work=work, version=current_versions() if parser_version is None else parser_version,
        existing=existing, local_root=local_root, raw_store=raw_store, unreadable_files=unreadable_files,
        max_work_items=max_work_items, decided_at=decided_at, unreadable_store=unreadable_store)


__all__ = ["ARROW_SCHEMA", "CANDIDATE_SQL", "PK", "SCHEMA", "SOURCE", "build_row", "current_versions", "stage", "table"]


def create_table(*, engine, work, catalog_root, table, location, create_namespace=False):
    return create_record_table(schema_path=TABLE_SCHEMA, engine=engine, work=work,
        catalog_root=catalog_root, table=table, location=location, create_namespace=create_namespace)


def append(staged, *, engine, work, catalog_root, table):
    return append_record_table(staged, parser_name="transcript_headings", default_version="", current_version_fn=current_versions,
        engine=engine, work=work, catalog_root=catalog_root, table=table)
