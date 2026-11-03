"""Lake producer for `committee_records`: amendments and committee votes House meeting XML links.

These rows are document links as the publisher lists them, never ballots or tallies.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence
import xml.etree.ElementTree as ET

import pyarrow as pa

from ..parsers.house_documents import active, read_xml
from ..parsers.house_xml import parse_house_meeting, strip_house_meeting_prefix
from ._record_producer import append_record_table, create_record_table, GOOD_FETCH_CAPTURE_SQL, HOUSE_XML_CAPTURE_SQL, PK, build_record_table, normalize_record_sha, stage_record_table
from .versions import version_digest
from .video_records import NO_INLINE_SQL

ROOT = Path(__file__).resolve().parents[5]
TABLE_SCHEMA = ROOT / "model/lake/committee-records.schema.json"
SOURCE = "house_xml"

RECORD_STRUCT = pa.struct([
    pa.field("ordinal", pa.int32(), nullable=False),
    pa.field("kind", pa.string(), nullable=False),
    pa.field("bill", pa.string()),
    pa.field("number", pa.string()),
    pa.field("sponsor_bioguide", pa.string()),
    pa.field("amendment_type", pa.string()),
    pa.field("enbloc", pa.string()),
    pa.field("description", pa.string()),
    pa.field("url", pa.string()),
])
ARROW_SCHEMA = pa.schema([
    pa.field("record_sha", pa.binary(32), nullable=False),
    pa.field("parser_version", pa.string(), nullable=False),
    pa.field("status", pa.string(), nullable=False),
    pa.field("error_type", pa.string()),
    pa.field("source", pa.string(), nullable=False),
    pa.field("records", pa.list_(pa.field("element", RECORD_STRUCT, nullable=False)), nullable=False),
    pa.field("event_id", pa.string()),
    pa.field("updated", pa.string()),
])
SCHEMA = ARROW_SCHEMA

CANDIDATE_SQL = f"""SELECT encode(c.sha256,'hex') AS record_sha,min(coalesce(c.stored_suffix,'')) AS stored_suffix,'{SOURCE}' AS source
FROM captures c WHERE {GOOD_FETCH_CAPTURE_SQL} AND {HOUSE_XML_CAPTURE_SQL} GROUP BY c.sha256"""


def current_versions(*, root: Path = ROOT) -> dict[str, str]:
    package = Path(__file__).resolve().parents[1]
    return {SOURCE: version_digest(packages={}, files={
        "producer": Path(__file__),
        "shared_producer": package / "lake/_record_producer.py",
        "documents": package / "parsers/house_documents.py",
        "house_xml": package / "parsers/house_xml.py",
        "lock": Path(root) / "uv.lock",
        "schema": Path(root) / "model/lake/committee-records.schema.json",
    }, values={"source": SOURCE})}


def _blank(value: str) -> str | None:
    return value or None


def build_row(record_sha: str | bytes, source: str, payload: bytes | str, *, parser_version: str) -> dict[str, Any]:
    """A witness list or another XML root gives no records, so it is not parsed again."""
    if source != SOURCE:
        raise ValueError(f"Unsupported committee_records source {source!r}")
    sha, event_id, updated, records = normalize_record_sha(record_sha), None, None, []
    raw = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
    try:
        root = parse_house_meeting(raw) if raw.strip() else None
    except (ET.ParseError, ValueError):
        root = None
    if root is not None and root.tag == "committee-meeting" and active(root):
        event_id = strip_house_meeting_prefix((root.get("meeting-id") or "").strip()) or None
        updated = (root.get("update-date") or "").strip() or None
        _, found = read_xml(root, None)
        records = [dict(ordinal=index, kind=item["kind"], bill=_blank(item["bill"]), number=_blank(item["number"]),
            sponsor_bioguide=_blank(item["sponsor_bioguide"]), amendment_type=_blank(item["amendment_type"]),
            enbloc=_blank(item["enbloc"]), description=_blank(item["description"]), url=_blank(item["url"]))
            for index, item in enumerate(found)]
    return dict(record_sha=sha, parser_version=str(parser_version), status="completed", error_type=None,
        source=source, records=records, event_id=event_id, updated=updated)


def table(rows: Sequence[Mapping[str, Any]]) -> pa.Table:
    return build_record_table(rows, payload_col="records", schema=ARROW_SCHEMA, extra_cols=("event_id", "updated"))


def stage(*, captures: Any, engine: Any, work: Path, existing: Any = None, local_root: Path | str | None = None,
          raw_store: Any = None, unreadable_files: Sequence[Mapping[str, Any]] = (), parser_version: str | Mapping[str, str] | None = None,
          max_work_items: int | None = None, decided_at: str | None = None, unreadable_store: Any = None) -> dict[str, Any]:
    """Stage missing rows from `captures`; nothing is written to the lake here."""
    return stage_record_table(parser_name="committee_records", out_filename="committee-records.parquet",
        candidate_sql=CANDIDATE_SQL, inline_sql=NO_INLINE_SQL, build_row_fn=build_row, table_fn=table,
        captures=captures, engine=engine, work=work, version=current_versions() if parser_version is None else parser_version,
        existing=existing, local_root=local_root, raw_store=raw_store, unreadable_files=unreadable_files,
        max_work_items=max_work_items, decided_at=decided_at, unreadable_store=unreadable_store)


__all__ = ["ARROW_SCHEMA", "CANDIDATE_SQL", "PK", "SCHEMA", "SOURCE", "build_row", "current_versions", "stage", "table"]


def create_table(*, engine: Any, work: Path, catalog_root: Path | None, table: dict[str, Any], location: str,
                 create_namespace: bool = False) -> Any:
    return create_record_table(schema_path=ROOT / "model/lake/committee-records.schema.json", engine=engine, work=work,
        catalog_root=catalog_root, table=table, location=location, create_namespace=create_namespace)


def append(staged: Mapping[str, Any], *, engine: Any, work: Path, catalog_root: Path | None, table: dict[str, Any]) -> Any:
    """Append a staged table; the rows carry their per-source parser version."""
    return append_record_table(staged, parser_name="committee_records", default_version="", current_version_fn=current_versions,
        engine=engine, work=work, catalog_root=catalog_root, table=table)
