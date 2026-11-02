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

import ast
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

PK = ["record_sha", "source", "parser_version"]


def source_ast_digest(source_file: Path, symbols: Sequence[str]) -> str:
    """Compute a deterministic AST digest for the named top-level definitions in `source_file`.

    Line numbers, comments, and edits to unrelated top-level definitions do not change the digest.
    """
    tree = ast.parse(Path(source_file).read_text(encoding="utf-8"))
    by_name: dict[str, list[str]] = {}
    for node in tree.body:
        names: list[str] = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = [node.name]
        elif isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        for name in names:
            by_name.setdefault(name, []).append(ast.dump(node, annotate_fields=True, include_attributes=False))
    parts: list[str] = []
    for sym in symbols:
        if sym not in by_name:
            raise KeyError(f"Symbol {sym!r} not found in {source_file}")
        parts.extend(by_name[sym])
    return sha256("\n".join(parts).encode("utf-8")).hexdigest()


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
    extra_cols: Sequence[str] = (),
) -> pa.Table:
    """Convert record row dicts into a sorted PyArrow Table conforming to `schema`."""
    sha_type = schema.field("record_sha").type
    binary_sha = pa.types.is_binary(sha_type) or pa.types.is_fixed_size_binary(sha_type)
    normalized: list[dict[str, Any]] = []
    for r in rows:
        sha_hex = normalize_record_sha(r["record_sha"])
        row_dict: dict[str, Any] = {
            "record_sha": bytes.fromhex(sha_hex) if binary_sha else sha_hex,
            "parser_version": str(r["parser_version"]),
            "status": str(r.get("status") or "completed"),
            "error_type": r.get("error_type"),
            "source": str(r["source"]),
            payload_col: list(r.get(payload_col) or []),
            "_sort_sha": sha_hex,
        }
        for col in extra_cols:
            row_dict[col] = r.get(col)
        normalized.append(row_dict)
    normalized.sort(key=lambda r: (r["_sort_sha"], r["source"], r["parser_version"]))
    for r in normalized:
        r.pop("_sort_sha", None)
    if not normalized:
        return pa.Table.from_pylist([], schema=schema)
    return pa.Table.from_pylist(normalized, schema=schema)


def _resolve_source_version(
    source: str,
    parser_version: str | Mapping[str, str],
) -> str:
    if isinstance(parser_version, Mapping):
        if source not in parser_version:
            raise KeyError(f"Missing parser_version for source {source!r}")
        return str(parser_version[source])
    return str(parser_version)


def filter_unprocessed_inputs(
    inputs: Iterable[Mapping[str, Any]],
    existing: pa.Table | Sequence[Mapping[str, Any]] | None = None,
    *,
    parser_version: str | Mapping[str, str],
) -> list[dict[str, Any]]:
    """Anti-join candidate inputs on `(record_sha, source, parser_version)` before parsing payloads."""
    existing_keys_3: set[tuple[str, str, str]] = set()
    existing_keys_2: set[tuple[str, str]] = set()
    if existing is not None:
        if isinstance(existing, pa.Table):
            has_source = "source" in existing.schema.names
            cols = ["record_sha", "source", "parser_version"] if has_source else ["record_sha", "parser_version"]
            for row in existing.select(cols).to_pylist():
                sha_hex = normalize_record_sha(row["record_sha"])
                ver = str(row["parser_version"])
                if has_source and row.get("source") is not None:
                    existing_keys_3.add((sha_hex, str(row["source"]), ver))
                else:
                    existing_keys_2.add((sha_hex, ver))
        else:
            for row in existing:
                sha_hex = normalize_record_sha(row["record_sha"])
                ver = str(row["parser_version"])
                if row.get("source") is not None:
                    existing_keys_3.add((sha_hex, str(row["source"]), ver))
                else:
                    existing_keys_2.add((sha_hex, ver))

    pending: list[dict[str, Any]] = []
    seen_in_batch: set[tuple[str, str, str]] = set()
    for item in inputs:
        sha_hex = normalize_record_sha(item["record_sha"])
        src = str(item["source"])
        ver = str(item["parser_version"]) if item.get("parser_version") else _resolve_source_version(src, parser_version)
        key3 = (sha_hex, src, ver)
        if key3 in existing_keys_3 or (sha_hex, ver) in existing_keys_2 or key3 in seen_in_batch:
            continue
        seen_in_batch.add(key3)
        pending.append({**item, "record_sha": sha_hex, "source": src, "parser_version": ver})
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


def _candidate_rel_paths(record_sha: str, stored_suffix: str | None) -> list[str]:
    suffix = stored_suffix if stored_suffix is not None else ".gz"
    rel_candidates = [f"bodies/sha256/{record_sha[:2]}/{record_sha}{suffix}"]
    if suffix != "":
        rel_candidates.append(f"bodies/sha256/{record_sha[:2]}/{record_sha}")
    if suffix != ".gz":
        rel_candidates.append(f"bodies/sha256/{record_sha[:2]}/{record_sha}.gz")
    return rel_candidates


def _atomic_write_cache(target: Path, data: bytes) -> None:
    import os
    import threading

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, target)
    except OSError:
        pass


def _read_candidate_body(
    record_sha: str,
    stored_suffix: str | None,
    *,
    local_root: Path | None,
    raw_store: Any,
) -> bytes:
    import gzip as _gzip

    rel_candidates = _candidate_rel_paths(record_sha, stored_suffix)

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
                    if local_root is not None:
                        _atomic_write_cache(Path(local_root) / rel, raw_bytes)
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


def _prefetch_candidate_bodies(
    work_items: Sequence[Mapping[str, Any]],
    *,
    local_root: Path,
    raw_store: Any,
    max_workers: int = 32,
) -> None:
    """Concurrently prefetch R2 candidate bodies into `local_root` so subsequent stages read locally."""
    from concurrent.futures import ThreadPoolExecutor

    if not work_items or raw_store is None:
        return
    adapter = getattr(raw_store, "adapter", None)
    if getattr(adapter, "root", None) is not None or not (
        hasattr(adapter, "client") and hasattr(adapter, "bucket")
    ):
        return

    missing: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for item in work_items:
        rec_sha = item["record_sha"]
        if rec_sha in seen:
            continue
        seen.add(rec_sha)
        suffix = item["stored_suffix"] if item.get("stored_suffix") is not None else ".gz"
        rels = _candidate_rel_paths(rec_sha, suffix)
        if not any((local_root / rel).is_file() for rel in rels):
            missing.append((rec_sha, suffix))

    if len(missing) <= 1:
        return

    def _fetch_one(pair: tuple[str, str | None]) -> None:
        rec_sha, suffix = pair
        for rel in _candidate_rel_paths(rec_sha, suffix):
            target = local_root / rel
            if target.is_file():
                return
            try:
                resp = adapter.client.get_object(Bucket=adapter.bucket, Key=rel)
                body = resp["Body"]
                raw_bytes = body.read() if hasattr(body, "read") else bytes(body)
                _atomic_write_cache(target, raw_bytes)
                return
            except Exception as exc:
                if _is_missing_key_error(exc):
                    continue
                raise

    with ThreadPoolExecutor(max_workers=min(max_workers, len(missing))) as pool:
        list(pool.map(_fetch_one, missing))




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
            if local_root is not None:
                _atomic_write_cache(Path(local_root) / receipt_key, raw_bytes)
    if raw_bytes is None:
        raise FileNotFoundError(f"Missing receipt object for key={receipt_key}")
    if raw_bytes[:2] == b"\x1f\x8b":
        raw_bytes = _gzip.decompress(raw_bytes)
    lines = raw_bytes.splitlines()
    # INLINE_CONGRESS_MEETINGS_SQL is ordered by receipt_key, receipt_line; keep at most one receipt in memory.
    cache.clear()
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


GOOD_FETCH_CAPTURE_SQL = (
    "c.mode = 'fetch' AND c.complete AND c.outcome IN ('stored', 'unchanged') "
    "AND c.http_status BETWEEN 200 AND 299 AND c.sha256 IS NOT NULL"
)

CONGRESS_GOV_CAPTURE_SQL = (
    "coalesce(c.sniffed_format, '') NOT IN ('html', 'pdf', 'zip', 'vtt', 'm3u8') "
    "AND lower(coalesce(c.media_type, '')) NOT LIKE '%html%' "
    "AND lower(coalesce(c.url, c.requested_url, '')) NOT LIKE '%.html%' "
    "AND (c.family = 'congress/meetings' "
    "OR lower(coalesce(c.url, c.requested_url, '')) LIKE '%api.congress.gov%/committee-meeting%' "
    "OR lower(coalesce(c.url, c.requested_url, '')) LIKE '%congress.gov/committee-meeting%')"
)

HOUSE_XML_CAPTURE_SQL = (
    "(c.family IN ('house/meeting-xml', 'house/witness-xml', 'house/Committees') "
    "OR (lower(coalesce(c.url, c.requested_url, c.context_url, '')) LIKE '%docs.house.gov%' "
    "AND (lower(coalesce(c.url, c.requested_url, c.context_url, '')) LIKE '%.xml%' OR c.sniffed_format = 'xml')))"
)

MODS_CAPTURE_SQL = (
    "(upper(coalesce(c.url, '')) LIKE '%CHRG%' "
    "OR upper(coalesce(c.requested_url, '')) LIKE '%CHRG%' "
    "OR upper(coalesce(c.context_url, '')) LIKE '%CHRG%' "
    "OR upper(coalesce(c.member_path, '')) LIKE '%CHRG%') "
    "AND (c.family = 'govinfo/mods' "
    "OR ((lower(coalesce(c.url, '')) LIKE '%mods%' "
    "OR lower(coalesce(c.requested_url, '')) LIKE '%mods%' "
    "OR lower(coalesce(c.context_url, '')) LIKE '%mods%' "
    "OR lower(coalesce(c.member_path, '')) LIKE '%mods%') "
    "AND (coalesce(c.sniffed_format, '') = 'xml' "
    "OR lower(coalesce(c.media_type, '')) LIKE '%xml%' "
    "OR lower(coalesce(c.url, c.requested_url, '')) LIKE '%.xml%' "
    "OR lower(coalesce(c.context_url, '')) LIKE '%/mods%' "
    "OR lower(coalesce(c.member_path, '')) LIKE '%.xml%')))"
)

SENATE_PAGE_CAPTURE_SQL = (
    "c.member_path IS NULL "
    "AND coalesce(c.family, '') <> 'documents' "
    "AND coalesce(c.sniffed_format, '') NOT IN ('pdf', 'xml', 'json', 'zip', 'vtt', 'm3u8') "
    "AND lower(coalesce(c.media_type, '')) NOT LIKE '%pdf%' "
    "AND lower(coalesce(c.url, c.requested_url, '')) NOT LIKE '%.pdf%' "
    "AND (c.family IN ('senate/hearings', 'senate/pages', 'senate/hearing-page') "
    "OR (lower(coalesce(c.url, c.requested_url, '')) LIKE '%.senate.gov%' "
    "AND coalesce(c.sniffed_format, '') = 'html' "
    "AND (lower(coalesce(c.url, c.requested_url, '')) LIKE '%hearing%' "
    "OR lower(coalesce(c.url, c.requested_url, '')) LIKE '%meeting%' "
    "OR lower(coalesce(c.url, c.requested_url, '')) LIKE '%business%')))"
)


CANDIDATE_MEETING_RECORDS_SQL = f"""WITH classified AS (
    SELECT c.sha256, coalesce(c.stored_suffix, '') AS stored_suffix, 'congress_gov' AS source
    FROM captures c
    WHERE {GOOD_FETCH_CAPTURE_SQL}
      AND {CONGRESS_GOV_CAPTURE_SQL}
    UNION ALL
    SELECT c.sha256, coalesce(c.stored_suffix, '') AS stored_suffix, 'house_xml' AS source
    FROM captures c
    WHERE {GOOD_FETCH_CAPTURE_SQL}
      AND {HOUSE_XML_CAPTURE_SQL}
)
SELECT encode(sha256, 'hex') AS record_sha,
    min(stored_suffix) AS stored_suffix,
    source
FROM classified
GROUP BY sha256, source"""


CANDIDATE_APPEARANCE_RECORDS_SQL = f"""WITH classified AS (
    SELECT c.sha256, coalesce(c.stored_suffix, '') AS stored_suffix, 'congress_gov' AS source
    FROM captures c
    WHERE {GOOD_FETCH_CAPTURE_SQL}
      AND {CONGRESS_GOV_CAPTURE_SQL}
    UNION ALL
    SELECT c.sha256, coalesce(c.stored_suffix, '') AS stored_suffix, 'house_xml' AS source
    FROM captures c
    WHERE {GOOD_FETCH_CAPTURE_SQL}
      AND {HOUSE_XML_CAPTURE_SQL}
    UNION ALL
    SELECT c.sha256, coalesce(c.stored_suffix, '') AS stored_suffix, 'mods' AS source
    FROM captures c
    WHERE {GOOD_FETCH_CAPTURE_SQL}
      AND {MODS_CAPTURE_SQL}
    UNION ALL
    SELECT c.sha256, coalesce(c.stored_suffix, '') AS stored_suffix, 'senate_page' AS source
    FROM captures c
    WHERE {GOOD_FETCH_CAPTURE_SQL}
      AND {SENATE_PAGE_CAPTURE_SQL}
)
SELECT encode(sha256, 'hex') AS record_sha,
    min(stored_suffix) AS stored_suffix,
    source
FROM classified
GROUP BY sha256, source"""


def _inline_rank(line: bytes) -> tuple[str, int]:
    """How current one inline line is: (updateDate, witness count); unreadable lines rank last."""
    try:
        meetings = unwrap_congress_gov_payload(line)
    except (ValueError, TypeError):
        return ("", 0)
    if not meetings:
        return ("", 0)
    return (str(meetings[0].get("updateDate") or ""), len(meetings[0].get("witnesses") or []))


def _current_inline_lines(
    candidates: Path, *, local_root: Path | None, raw_store: Any
) -> list[tuple[str, bytes, str]]:
    """The current line per source URL, as (sha256, line, url).

    Receipts repeat each meeting on every fetch, and only the newest is current: a
    superseded line would otherwise be missing work on every run. A line without a URL
    stands alone. Equal ranks take the later line, so the choice is stable; on the
    corpus they differ only in fetch envelope for all but one URL. Reads O(L) lines,
    holding one receipt and the current lines.
    """
    receipt_cache: dict[str, list[bytes]] = {}
    current: dict[str, tuple[tuple[str, int], bytes, str]] = {}
    for batch in pq.ParquetFile(candidates).iter_batches(columns=["receipt_key", "receipt_line", "source_url"]):
        for ref in batch.to_pylist():
            r_key, r_line = ref["receipt_key"], int(ref["receipt_line"])
            lines = _read_receipt_lines(r_key, local_root=local_root, raw_store=raw_store, cache=receipt_cache)
            if not 1 <= r_line <= len(lines):
                continue
            url = ref.get("source_url") or ""
            rank = _inline_rank(lines[r_line - 1])
            slot = url or f"{r_key}:{r_line}"
            if slot not in current or rank >= current[slot][0]:
                current[slot] = (rank, lines[r_line - 1], url)
    return [(sha256(line).hexdigest(), line, url) for _, line, url in current.values()]


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
    version: str | Mapping[str, str],
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
        fields=[field(name, "Utf8") for name in ("id", "body_sha256", "record_sha", "parser", "parser_version", "supersedes")],
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
                body_sha256="Utf8",
                record_sha="Utf8",
                parser="Utf8",
                parser_version="Utf8",
                supersedes="Utf8",
            )
        )
    existing_sha_expr = "lower(encode(e.record_sha, 'hex'))"
    existing_has_source = True
    if existing is not None:
        inputs.append(table_input("existing", existing))
        parquet_path = (
            existing.get("path")
            if isinstance(existing, Mapping) and existing.get("kind") == "parquet"
            else (existing if isinstance(existing, (str, Path)) else None)
        )
        if parquet_path is not None and Path(parquet_path).is_file():
            ex_schema = pq.read_schema(parquet_path)
            if "record_sha" in ex_schema.names:
                st = ex_schema.field("record_sha").type
                if not (pa.types.is_binary(st) or pa.types.is_fixed_size_binary(st)):
                    existing_sha_expr = "lower(e.record_sha)"
            existing_has_source = "source" in ex_schema.names

    if isinstance(version, Mapping):
        when_clauses = " ".join(
            f"WHEN '{src.replace(chr(39), chr(39)*2)}' THEN '{ str(v).replace(chr(39), chr(39)*2) }'"
            for src, v in sorted(version.items())
        )
        ver_col_sql = f"CASE c.source {when_clauses} END"
        inline_ver = str(version.get("congress_gov") or next(iter(version.values())))
        version_list_sql = ", ".join("'" + str(v).replace("'", "''") + "'" for v in sorted(set(version.values())))
    else:
        ver_col_sql = "'" + str(version).replace("'", "''") + "'"
        inline_ver = str(version)
        version_list_sql = ver_col_sql

    versioned_candidates_sql = f"SELECT c.*, {ver_col_sql} AS parser_version FROM ({candidate_sql}) c"
    short_name = {"meeting_records": "meetings", "appearance_records": "appearances"}.get(parser_name, parser_name)

    missing = (
        f" WHERE c.source IS NOT NULL AND c.parser_version IS NOT NULL AND NOT EXISTS (SELECT 1 FROM unreadable u "
        f"WHERE lower(coalesce(u.record_sha, u.body_sha256))=lower(c.record_sha) "
        f"AND u.parser IN ('{parser_name}', '{short_name}', '{parser_name}.' || c.source) "
        f"AND u.parser_version=c.parser_version "
        f"AND NOT EXISTS (SELECT 1 FROM unreadable s WHERE s.supersedes=u.id))"
    )
    if existing is not None:
        src_cond = " AND e.source=c.source" if existing_has_source else ""
        missing += (
            f" AND NOT EXISTS (SELECT 1 FROM existing e WHERE {existing_sha_expr}=c.record_sha"
            + src_cond
            + " AND e.parser_version=c.parser_version)"
        )

    inline_ver_sql = "'" + inline_ver.replace("'", "''") + "'"
    queries: list[dict[str, Any]] = [
        dict(
            name="unreadable_shas",
            sql=(
                f"SELECT DISTINCT lower(coalesce(u.record_sha, u.body_sha256)) AS record_sha FROM unreadable u "
                f"WHERE u.parser IN ('{parser_name}', '{short_name}', '{parser_name}.congress_gov') "
                f"AND u.parser_version="
                + inline_ver_sql
                + " AND coalesce(u.record_sha, u.body_sha256) IS NOT NULL"
                + " AND NOT EXISTS (SELECT 1 FROM unreadable s WHERE s.supersedes=u.id)"
            ),
        ),
    ]
    if existing is not None:
        inline_src_filter = " AND e.source='congress_gov'" if existing_has_source else ""
        queries.append(
            dict(
                name="existing_shas",
                sql=(
                    f"SELECT DISTINCT {existing_sha_expr} AS record_sha FROM existing e "
                    f"WHERE e.parser_version={inline_ver_sql}{inline_src_filter}"
                ),
            )
        )

    reports = run_job(
        work,
        engine,
        inputs=inputs,
        steps=[dict(name="candidates", sql=versioned_candidates_sql)],
        outputs=[
            parquet_output(work, "work-list", "SELECT c.* FROM candidates c" + missing, ["record_sha", "source"]),
            parquet_output(work, "inline-candidates", inline_sql, ["receipt_key", "receipt_line"]),
        ],
        queries=queries,
    )

    work_list_path = work / "work-list.parquet"
    work_items = pq.read_table(work_list_path).to_pylist()
    if max_work_items is not None and len(work_items) > max_work_items:
        raise BackfillRequired(
            dict(
                work_items=len(work_items),
                work_list=work_list_path,
                parser=parser_name,
                parser_version=version,
            ),
            max_work_items,
        )
    local_root_path = Path(local_root) if local_root is not None else None
    excluded_inline_shas = {row["record_sha"] for row in reports.get("unreadable_shas", []) if row.get("record_sha")}
    if existing is not None:
        excluded_inline_shas.update(row["record_sha"] for row in reports.get("existing_shas", []) if row.get("record_sha"))
    seen_inline_shas = {item["record_sha"] for item in work_items if item.get("source") == "congress_gov"}

    inline_items: list[dict[str, Any]] = []
    for rec_sha, line_bytes, source_url in _current_inline_lines(
        work / "inline-candidates.parquet", local_root=local_root_path, raw_store=raw_store
    ):
        if rec_sha not in excluded_inline_shas and rec_sha not in seen_inline_shas:
            seen_inline_shas.add(rec_sha)
            inline_items.append(
                {
                    "record_sha": rec_sha,
                    "source": "congress_gov",
                    "payload": line_bytes,
                    "source_url": source_url or None,
                    "parser_version": inline_ver,
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

    effective_local_root = local_root_path if local_root_path is not None else (work / "body-cache")
    _prefetch_candidate_bodies(work_items, local_root=effective_local_root, raw_store=raw_store)

    rows: list[dict[str, Any]] = []
    unreadable_records: list[dict[str, Any]] = []
    decision_time = decided_at or "2026-10-30T00:00:00Z"

    for item in work_items:
        rec_sha = item["record_sha"]
        item_ver = str(item.get("parser_version") or _resolve_source_version(item["source"], version))
        suffix = item["stored_suffix"] if item.get("stored_suffix") is not None else ".gz"
        try:
            payload_bytes = _read_candidate_body(
                rec_sha,
                suffix,
                local_root=effective_local_root,
                raw_store=raw_store,
            )
            kwargs: dict[str, Any] = {
                "record_sha": rec_sha,
                "source": item["source"],
                "payload": payload_bytes,
                "parser_version": item_ver,
            }
            if pass_source_url and item.get("source_url"):
                kwargs["source_url"] = item.get("source_url")
            rows.append(build_row_fn(**kwargs))
        except (ValueError, KeyError, ET.ParseError, UnicodeDecodeError) as exc:
            unreadable_records.append(
                {
                    "id": f"unreadable:{parser_name}:{item_ver}:{rec_sha}",
                    "body_sha256": rec_sha,
                    "record_sha": rec_sha,
                    "parser": parser_name,
                    "parser_version": item_ver,
                    "reason": f"{type(exc).__name__}: {exc}",
                    "decided_by": parser_name,
                    "decided_at": decision_time,
                    "supersedes": None,
                }
            )
    for inline_item in inline_items:
        rec_sha = inline_item["record_sha"]
        item_ver = str(inline_item["parser_version"])
        try:
            kwargs = {
                "record_sha": rec_sha,
                "source": inline_item["source"],
                "payload": inline_item["payload"],
                "parser_version": item_ver,
            }
            if pass_source_url and inline_item.get("source_url"):
                kwargs["source_url"] = inline_item.get("source_url")
            rows.append(build_row_fn(**kwargs))
        except (ValueError, KeyError, ET.ParseError, UnicodeDecodeError) as exc:
            unreadable_records.append(
                {
                    "id": f"unreadable:{parser_name}:{item_ver}:{rec_sha}",
                    "body_sha256": None,
                    "record_sha": rec_sha,
                    "parser": parser_name,
                    "parser_version": item_ver,
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
    current_version_fn: Callable[[], str | Mapping[str, str]],
    engine: Any,
    work: Path,
    catalog_root: Path | None,
    table: dict[str, Any],
    parser_version: str | Mapping[str, str] | None = None,
) -> Any:
    from .tables import append_rows

    if isinstance(staged_parquet, Mapping):
        if staged_parquet.get("unreadable_pending"):
            raise ValueError("Pending unreadable decisions require durable import")
        raw_ver = staged_parquet.get("parser_version") or parser_version or current_version_fn()
        source_path = Path(staged_parquet["records"])
    else:
        raw_ver = parser_version or default_version
        source_path = Path(staged_parquet)

    if isinstance(raw_ver, Mapping):
        resolved_version = json.dumps(dict(raw_ver), sort_keys=True, separators=(",", ":"))
    else:
        resolved_version = str(raw_ver)

    return append_rows(
        source_path,
        engine=engine,
        work=work,
        catalog_root=catalog_root,
        table=table,
        keys=PK,
        definition=f"{parser_name}:{resolved_version}",
    )
