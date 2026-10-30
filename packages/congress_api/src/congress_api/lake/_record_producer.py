"""Shared lake producer helpers for `meeting_records` and `appearance_records` (Phase 2 Track D4).

Centralizes:
- SHA-256 record identifier normalization (`normalize_record_sha`)
- Congress.gov meeting payload unwrapping (`unwrap_congress_gov_payload`)
- Incremental `(record_sha, parser_version)` anti-join (`filter_unprocessed_inputs`)
- Raw body and inline receipt reading (`_read_candidate_body`, `_read_receipt_lines`)
- Native staging job orchestration (`stage_record_table`)
- Native Iceberg table creation and append (`create_record_table`, `append_record_table`)
"""

from __future__ import annotations

from hashlib import sha256
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from ..models.congress import CommitteeMeeting
from ..parsers.congress import meeting_from_xml, parse_congress_xml

PK = ["record_sha", "parser_version"]


def normalize_record_sha(value: str | bytes) -> str:
    """Normalize a SHA-256 record identifier to a 64-character lowercase hex string."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        if len(raw) == 32:
            return raw.hex()
        text = raw.decode("ascii").strip().lower()
    elif isinstance(value, str):
        text = value.strip().lower()
    else:
        raise TypeError(f"Unsupported record_sha type: {type(value)!r}")
    if text.startswith("sha256:"):
        text = text[len("sha256:") :]
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise ValueError(f"Invalid SHA-256 hex digest: {value!r}")
    return text


def unwrap_congress_gov_payload(
    payload: bytes | str | Mapping[str, Any] | CommitteeMeeting,
    *,
    allow_list_page: bool = False,
) -> list[dict[str, Any]]:
    """Unwrap a Congress.gov meeting detail body or inline receipt record into meeting dicts."""
    if isinstance(payload, CommitteeMeeting):
        return [payload.source_dict()]

    if isinstance(payload, (bytes, bytearray, memoryview)):
        raw_bytes = bytes(payload).strip()
        if not raw_bytes:
            return []
        if raw_bytes.startswith(b"<"):
            root = parse_congress_xml(raw_bytes)
            if root.find("committeeMeeting") is not None or root.tag == "committeeMeeting":
                return [meeting_from_xml(root).source_dict()]
            return []
        data = json.loads(raw_bytes.decode("utf-8"))
    elif isinstance(payload, str):
        text = payload.strip()
        if not text:
            return []
        if text.startswith("<"):
            root = parse_congress_xml(text.encode("utf-8"))
            if root.find("committeeMeeting") is not None or root.tag == "committeeMeeting":
                return [meeting_from_xml(root).source_dict()]
            return []
        data = json.loads(text)
    elif isinstance(payload, Mapping):
        data = dict(payload)
    else:
        raise TypeError(f"Unsupported congress_gov payload type: {type(payload)!r}")

    if not data:
        return []

    if (
        "committeeMeeting" not in data
        and "eventId" not in data
        and "event_id" not in data
        and "committeeMeetings" not in data
        and "witnesses" not in data
    ):
        for wrapper_key in ("record", "payload", "body", "data"):
            inner = data.get(wrapper_key)
            if isinstance(inner, Mapping):
                data = dict(inner)
                break
        else:
            if isinstance(data.get("_source_xml"), Mapping):
                from ..retention.body_files import content_bytes

                return unwrap_congress_gov_payload(
                    content_bytes(data["_source_xml"]),
                    allow_list_page=allow_list_page,
                )
            return []

    if isinstance(data.get("committeeMeeting"), Mapping):
        return [dict(data["committeeMeeting"])]

    if "eventId" in data or "event_id" in data or "witnesses" in data:
        return [data]

    if allow_list_page and "committeeMeetings" in data:
        items = data.get("committeeMeetings") or []
        return [
            dict(item)
            for item in items
            if isinstance(item, Mapping)
            and (item.get("eventId") or item.get("event_id"))
            and any(k in item for k in ("title", "date", "committees", "meetingStatus", "type", "videos", "witnesses"))
        ]

    return []


def build_record_table(
    rows: Sequence[Mapping[str, Any]],
    *,
    payload_col: str,
    schema: pa.Schema,
) -> pa.Table:
    """Convert record row dicts into a sorted PyArrow Table conforming to `schema`."""
    normalized = [
        {
            "record_sha": normalize_record_sha(r["record_sha"]),
            "parser_version": str(r["parser_version"]),
            "source": str(r["source"]),
            payload_col: list(r.get(payload_col) or []),
        }
        for r in rows
    ]
    normalized.sort(key=lambda r: (r["record_sha"], r["parser_version"]))
    if not normalized:
        return pa.Table.from_pylist([], schema=schema)
    return pa.Table.from_pylist(normalized, schema=schema)


def filter_unprocessed_inputs(
    inputs: Iterable[Mapping[str, Any]],
    existing: pa.Table | Sequence[Mapping[str, Any]] | None = None,
    *,
    parser_version: str,
) -> list[dict[str, Any]]:
    """Anti-join candidate inputs on `(record_sha, parser_version)` before parsing payloads."""
    existing_keys: set[tuple[str, str]] = set()
    if existing is not None:
        if isinstance(existing, pa.Table):
            for row in existing.select(["record_sha", "parser_version"]).to_pylist():
                existing_keys.add((normalize_record_sha(row["record_sha"]), str(row["parser_version"])))
        else:
            for row in existing:
                existing_keys.add((normalize_record_sha(row["record_sha"]), str(row["parser_version"])))

    pending: list[dict[str, Any]] = []
    seen_in_batch: set[tuple[str, str]] = set()
    for item in inputs:
        sha_hex = normalize_record_sha(item["record_sha"])
        ver = str(item.get("parser_version") or parser_version)
        key = (sha_hex, ver)
        if key in existing_keys or key in seen_in_batch:
            continue
        seen_in_batch.add(key)
        pending.append({**item, "record_sha": sha_hex, "parser_version": ver})
    return pending


def _is_missing_key_error(exc: Exception) -> bool:
    if isinstance(exc, (FileNotFoundError, KeyError)):
        return True
    response = getattr(exc, "response", None)
    if isinstance(response, Mapping):
        code = str((response.get("Error") or {}).get("Code") or "")
        status = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
        if code in {"NoSuchKey", "404", "NotFound"} or status == 404:
            return True
    return False


def _read_candidate_body(
    record_sha: str,
    stored_suffix: str | None,
    *,
    local_root: Path | None,
    raw_store: Any,
) -> bytes:
    import gzip as _gzip

    suffix = stored_suffix if stored_suffix is not None else ".gz"
    rel_candidates = [f"bodies/sha256/{record_sha[:2]}/{record_sha}{suffix}"]
    if suffix != "":
        rel_candidates.append(f"bodies/sha256/{record_sha[:2]}/{record_sha}")
    if suffix != ".gz":
        rel_candidates.append(f"bodies/sha256/{record_sha[:2]}/{record_sha}.gz")

    raw_bytes: bytes | None = None
    if local_root is not None:
        base = Path(local_root)
        for rel in rel_candidates:
            candidate = base / rel
            if candidate.is_file():
                raw_bytes = candidate.read_bytes()
                break
    if raw_bytes is None and raw_store is not None:
        adapter = getattr(raw_store, "adapter", None)
        adapter_root = getattr(adapter, "root", None)
        if adapter_root is not None:
            for rel in rel_candidates:
                candidate = Path(adapter_root) / rel
                if candidate.is_file():
                    raw_bytes = candidate.read_bytes()
                    break
        elif hasattr(adapter, "client") and hasattr(adapter, "bucket"):
            for rel in rel_candidates:
                try:
                    resp = adapter.client.get_object(Bucket=adapter.bucket, Key=rel)
                    body = resp["Body"]
                    raw_bytes = body.read() if hasattr(body, "read") else bytes(body)
                    break
                except Exception as exc:
                    if _is_missing_key_error(exc):
                        continue
                    raise
    if raw_bytes is None:
        raise FileNotFoundError(f"Missing raw body for record_sha={record_sha}")
    if raw_bytes[:2] == b"\x1f\x8b":
        try:
            payload = _gzip.decompress(raw_bytes)
        except (_gzip.BadGzipFile, EOFError, OSError) as exc:
            raise ValueError(f"Corrupt gzip body for record_sha={record_sha}") from exc
    else:
        payload = raw_bytes
    actual_sha = sha256(payload).hexdigest()
    if actual_sha != record_sha:
        raise ValueError(f"Body SHA-256 mismatch for record_sha={record_sha}: got {actual_sha}")
    return payload


def _read_receipt_lines(
    receipt_key: str,
    *,
    local_root: Path | None,
    raw_store: Any,
    cache: dict[str, list[bytes]],
) -> list[bytes]:
    import gzip as _gzip

    if receipt_key in cache:
        return cache[receipt_key]
    raw_bytes: bytes | None = None
    if local_root is not None:
        candidate = Path(local_root) / receipt_key
        if candidate.is_file():
            raw_bytes = candidate.read_bytes()
    if raw_bytes is None and raw_store is not None:
        adapter = getattr(raw_store, "adapter", None)
        adapter_root = getattr(adapter, "root", None)
        if adapter_root is not None:
            candidate = Path(adapter_root) / receipt_key
            if candidate.is_file():
                raw_bytes = candidate.read_bytes()
        elif hasattr(adapter, "client") and hasattr(adapter, "bucket"):
            resp = adapter.client.get_object(Bucket=adapter.bucket, Key=receipt_key)
            body = resp["Body"]
            raw_bytes = body.read() if hasattr(body, "read") else bytes(body)
    if raw_bytes is None:
        raise FileNotFoundError(f"Missing receipt object for key={receipt_key}")
    if raw_bytes[:2] == b"\x1f\x8b":
        raw_bytes = _gzip.decompress(raw_bytes)
    lines = raw_bytes.splitlines()
    cache[receipt_key] = lines
    return lines


INLINE_CONGRESS_MEETINGS_SQL = """SELECT DISTINCT receipt_key, receipt_line,
    coalesce(url, requested_url, context_url, '') AS source_url
    FROM captures
    WHERE sha256 IS NULL AND outcome = 'saved-record'
      AND receipt_key IS NOT NULL AND receipt_line IS NOT NULL
      AND (family = 'congress/meetings'
           OR coalesce(url, requested_url, '') ILIKE '%api.congress.gov%/committee-meeting%'
           OR coalesce(url, requested_url, '') ILIKE '%congress.gov/committee-meeting%')
    ORDER BY receipt_key, receipt_line"""


def stage_record_table(
    *,
    parser_name: str,
    out_filename: str,
    candidate_sql: str,
    inline_sql: str = INLINE_CONGRESS_MEETINGS_SQL,
    build_row_fn: Callable[..., dict[str, Any]],
    table_fn: Callable[[Sequence[Mapping[str, Any]]], pa.Table],
    captures: Any,
    engine: Any,
    work: Path,
    version: str,
    existing: Any = None,
    local_root: Path | str | None = None,
    raw_store: Any = None,
    unreadable_files: Sequence[Mapping[str, Any]] = (),
    max_work_items: int | None = None,
    decided_at: str | None = None,
    unreadable_store: Any = None,
    pass_source_url: bool = False,
) -> dict[str, Any]:
    """Stage missing record rows from `captures` via native anti-join."""
    from ..retention.body_store import BodyStore, LocalAdapter
    from ..retention.provenance import (
        field,
        finish_stage,
        import_unreadable,
        imported_unreadable_provenance,
        json_input,
        parquet_output,
        run_job,
    )
    from .readings import BackfillRequired
    from .tables import table_input

    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=False)

    inputs: list[dict[str, Any]] = [table_input("captures", captures)]
    unreadable_schema = dict(
        fields=[field(name, "Utf8") for name in ("id", "record_sha", "parser", "parser_version", "supersedes")],
        metadata={},
    )
    if unreadable_files:
        inputs.append(dict(name="unreadable", kind="json_lines", files=list(unreadable_files), schema=unreadable_schema))
    else:
        inputs.append(
            json_input(
                work,
                "unreadable",
                [],
                id="Utf8",
                record_sha="Utf8",
                parser="Utf8",
                parser_version="Utf8",
                supersedes="Utf8",
            )
        )
    if existing is not None:
        inputs.append(table_input("existing", existing))

    version_sql = "'" + version.replace("'", "''") + "'"
    missing = (
        f" WHERE c.source IS NOT NULL AND NOT EXISTS (SELECT 1 FROM unreadable u "
        f"WHERE u.record_sha=c.record_sha AND u.parser='{parser_name}' AND u.parser_version="
        + version_sql
        + " AND NOT EXISTS (SELECT 1 FROM unreadable s WHERE s.supersedes=u.id))"
    )
    if existing is not None:
        missing += (
            " AND NOT EXISTS (SELECT 1 FROM existing e WHERE e.record_sha=c.record_sha "
            "AND e.parser_version=" + version_sql + ")"
        )

    queries: list[dict[str, Any]] = [
        dict(name="inline_candidates", sql=inline_sql),
        dict(
            name="unreadable_shas",
            sql=(
                f"SELECT DISTINCT u.record_sha FROM unreadable u "
                f"WHERE u.parser='{parser_name}' AND u.parser_version="
                + version_sql
                + " AND NOT EXISTS (SELECT 1 FROM unreadable s WHERE s.supersedes=u.id)"
            ),
        ),
    ]
    if existing is not None:
        queries.append(
            dict(
                name="existing_shas",
                sql="SELECT DISTINCT record_sha FROM existing WHERE parser_version=" + version_sql,
            )
        )

    reports = run_job(
        work,
        engine,
        inputs=inputs,
        steps=[dict(name="candidates", sql=candidate_sql)],
        outputs=[parquet_output(work, "work-list", "SELECT c.* FROM candidates c" + missing, ["record_sha"])],
        queries=queries,
    )

    work_list_path = work / "work-list.parquet"
    work_items = pq.read_table(work_list_path).to_pylist()
    local_root_path = Path(local_root) if local_root is not None else None
    excluded_shas = {row["record_sha"] for row in reports.get("unreadable_shas", []) if row.get("record_sha")}
    if existing is not None:
        excluded_shas.update(row["record_sha"] for row in reports.get("existing_shas", []) if row.get("record_sha"))
    seen_shas = {item["record_sha"] for item in work_items}

    receipt_cache: dict[str, list[bytes]] = {}
    inline_items: list[dict[str, Any]] = []
    for inline_ref in reports.get("inline_candidates", []):
        r_key = inline_ref["receipt_key"]
        r_line = int(inline_ref["receipt_line"])
        lines = _read_receipt_lines(r_key, local_root=local_root_path, raw_store=raw_store, cache=receipt_cache)
        if 1 <= r_line <= len(lines):
            line_bytes = lines[r_line - 1]
            rec_sha = sha256(line_bytes).hexdigest()
            if rec_sha not in excluded_shas and rec_sha not in seen_shas:
                seen_shas.add(rec_sha)
                inline_items.append(
                    {
                        "record_sha": rec_sha,
                        "source": "congress_gov",
                        "payload": line_bytes,
                        "source_url": inline_ref.get("source_url") or None,
                        "parser_version": version,
                    }
                )

    total_work_items = len(work_items) + len(inline_items)
    if max_work_items is not None and total_work_items > max_work_items:
        raise BackfillRequired(
            dict(
                work_items=total_work_items,
                work_list=work_list_path,
                parser=parser_name,
                parser_version=version,
            ),
            max_work_items,
        )

    rows: list[dict[str, Any]] = []
    unreadable_records: list[dict[str, Any]] = []
    decision_time = decided_at or "2026-10-30T00:00:00Z"

    for item in work_items:
        rec_sha = item["record_sha"]
        suffix = item["stored_suffix"] if item.get("stored_suffix") is not None else ".gz"
        try:
            payload_bytes = _read_candidate_body(
                rec_sha,
                suffix,
                local_root=local_root_path,
                raw_store=raw_store,
            )
            kwargs: dict[str, Any] = {
                "record_sha": rec_sha,
                "source": item["source"],
                "payload": payload_bytes,
                "parser_version": version,
            }
            if pass_source_url:
                kwargs["source_url"] = item.get("source_url") or None
            rows.append(build_row_fn(**kwargs))
        except (ValueError, KeyError, ET.ParseError, UnicodeDecodeError) as exc:
            unreadable_records.append(
                {
                    "id": f"unreadable:{parser_name}:{version}:{rec_sha}",
                    "body_sha256": rec_sha,
                    "record_sha": rec_sha,
                    "parser": parser_name,
                    "parser_version": version,
                    "reason": f"{type(exc).__name__}: {exc}",
                    "decided_by": parser_name,
                    "decided_at": decision_time,
                    "supersedes": None,
                }
            )
    for inline_item in inline_items:
        rec_sha = inline_item["record_sha"]
        try:
            kwargs = {
                "record_sha": rec_sha,
                "source": inline_item["source"],
                "payload": inline_item["payload"],
                "parser_version": version,
            }
            if pass_source_url:
                kwargs["source_url"] = inline_item.get("source_url")
            rows.append(build_row_fn(**kwargs))
        except (ValueError, KeyError, ET.ParseError, UnicodeDecodeError) as exc:
            unreadable_records.append(
                {
                    "id": f"unreadable:{parser_name}:{version}:{rec_sha}",
                    "body_sha256": None,
                    "record_sha": rec_sha,
                    "parser": parser_name,
                    "parser_version": version,
                    "reason": f"{type(exc).__name__}: {exc}",
                    "decided_by": parser_name,
                    "decided_at": decision_time,
                    "supersedes": None,
                }
            )

    unreadable_key = unreadable_path = unreadable_stage = unreadable_provenance = unreadable_custody = None
    pending = bool(unreadable_records and unreadable_store is None)
    if unreadable_records:
        decisions_path = work / "unreadable-decisions.jsonl"
        decisions_path.write_text(
            "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in unreadable_records),
            encoding="utf-8",
        )
        if pending:
            unreadable_stage = work / "unreadable-stage"
            unreadable_stage.mkdir()
            imported = import_unreadable(
                BodyStore(LocalAdapter(unreadable_stage)),
                decisions_path,
                decided_at=decision_time,
            )
            unreadable_path = str(unreadable_stage / imported["key"])
            finish_stage(
                unreadable_stage,
                kind="unreadable",
                provenance=imported["key"],
                records=len(unreadable_records),
                inputs={},
                extra=dict(decided_at=decision_time),
            )
        else:
            imported = import_unreadable(unreadable_store, decisions_path, decided_at=decision_time)
            unreadable_provenance, unreadable_custody = imported_unreadable_provenance(
                imported, unreadable_store, decisions_path
            )
        unreadable_key = imported["key"]

    produced_table = table_fn(rows)
    out_path = work / out_filename
    pq.write_table(produced_table, out_path)
    return dict(
        records=out_path,
        work_list=work_list_path,
        work_items=total_work_items,
        produced=produced_table.num_rows,
        parser_version=version,
        unreadable_key=unreadable_key,
        unreadable_path=unreadable_path,
        unreadable_stage=unreadable_stage,
        unreadable_pending=pending,
        unreadable_provenance=unreadable_provenance,
        _unreadable_custody=unreadable_custody,
    )


def create_record_table(
    *,
    schema_path: Path,
    engine: Any,
    work: Path,
    catalog_root: Path | None,
    table: dict[str, Any],
    location: str,
    create_namespace: bool = False,
) -> Any:
    from .tables import create_table as native_create

    return native_create(
        engine=engine,
        work=work,
        catalog_root=catalog_root,
        table=table,
        schema=json.loads(schema_path.read_text()),
        location=location,
        create_namespace=create_namespace,
    )


def append_record_table(
    staged_parquet: Path | Mapping[str, Any],
    *,
    parser_name: str,
    default_version: str,
    current_version_fn: Callable[[], str],
    engine: Any,
    work: Path,
    catalog_root: Path | None,
    table: dict[str, Any],
    parser_version: str | None = None,
) -> Any:
    from .tables import append_rows

    if isinstance(staged_parquet, Mapping):
        if staged_parquet.get("unreadable_pending"):
            raise ValueError("Pending unreadable decisions require durable import")
        resolved_version = str(staged_parquet.get("parser_version") or parser_version or current_version_fn())
        source_path = Path(staged_parquet["records"])
    else:
        resolved_version = str(parser_version or default_version)
        source_path = Path(staged_parquet)

    return append_rows(
        source_path,
        engine=engine,
        work=work,
        catalog_root=catalog_root,
        table=table,
        keys=PK,
        definition=f"{parser_name}:{resolved_version}",
    )
