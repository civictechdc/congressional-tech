"""Incremental docspec-rs Arrow/Parquet tables for weekly retention datasets.

Provides canonical Arrow schemas, primary keys, and declarative ``UpdateMergeSpec``
rules for the weekly retention modules so incremental runs update only changed
keys and stream Arrow/Parquet batches without re-parsing entire ``.json.gz`` or
CSV archives on every run.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from hashlib import sha256
from itertools import batched
import gzip
import json
import os
from pathlib import Path
import shutil
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from congress_shared.custody import write_atomic_bytes
from docspec_client import DocSpecFailure, NativeDatasets, resolve_docspec_binary

WEEKLY_TABLE_DEFINITION = "weekly-retention-v1"
PARQUET_ROW_GROUP_SIZE = 2048

WEEKLY_TABLE_SCHEMAS: dict[str, pa.Schema] = {
    "congress_meetings": pa.schema([
        pa.field("source_url", pa.string(), nullable=False),
        pa.field("event_id", pa.string(), nullable=True),
        pa.field("congress", pa.int64(), nullable=True),
        pa.field("chamber", pa.string(), nullable=True),
        pa.field("update_date", pa.string(), nullable=False),
        pa.field("raw_sha256", pa.string(), nullable=True),
        pa.field("payload_json", pa.string(), nullable=True),
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
        pa.field("merge_timestamp", pa.string(), nullable=False),
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
    "gpo_hearings": pa.schema([
        pa.field("package_id", pa.string(), nullable=False),
        pa.field("congress", pa.string(), nullable=True),
        pa.field("chamber", pa.string(), nullable=True),
        pa.field("committee_name", pa.string(), nullable=True),
        pa.field("issued_date", pa.string(), nullable=True),
        pa.field("last_modified", pa.string(), nullable=False),
        pa.field("title", pa.string(), nullable=True),
    ]),
    "gpo_observations": pa.schema([
        pa.field("package_id", pa.string(), nullable=False),
        pa.field("retrieved_at", pa.string(), nullable=False),
        pa.field("acquisition", pa.string(), nullable=False),
        pa.field("evidence_sha256", pa.string(), nullable=True),
    ]),
    "youtube_videos": pa.schema([
        pa.field("system_code", pa.string(), nullable=False),
        pa.field("video_id", pa.string(), nullable=False),
        pa.field("published_at", pa.string(), nullable=False),
        pa.field("title", pa.string(), nullable=True),
        pa.field("upstream_sha256", pa.string(), nullable=True),
    ]),
    "captions": pa.schema([
        pa.field("source", pa.string(), nullable=False),
        pa.field("native_id", pa.string(), nullable=False),
        pa.field("kind", pa.string(), nullable=True),
        pa.field("outcome", pa.string(), nullable=False),
        pa.field("observed_at", pa.string(), nullable=False),
        pa.field("receipt_json", pa.string(), nullable=True),
    ]),
    "transcripts": pa.schema([
        pa.field("capture_id", pa.string(), nullable=False),
        pa.field("model", pa.string(), nullable=False),
        pa.field("start", pa.float64(), nullable=False),
        pa.field("end", pa.float64(), nullable=False),
        pa.field("observed_at", pa.string(), nullable=False),
        pa.field("transcript_sha256", pa.string(), nullable=True),
        pa.field("payload_json", pa.string(), nullable=True),
    ]),
    "rejected_pages": pa.schema([
        pa.field("url", pa.string(), nullable=False),
        pa.field("offset", pa.int64(), nullable=False),
        pa.field("retrieved_at", pa.string(), nullable=False),
        pa.field("response_sha256", pa.string(), nullable=True),
        pa.field("response_json", pa.string(), nullable=True),
    ]),
}

WEEKLY_TABLE_KEYS: dict[str, tuple[str, ...]] = {
    "congress_meetings": ("source_url",),
    "congress_committees": ("congress", "system_code"),
    "house_events": ("event_id",),
    "senate_events": ("domain", "record_id"),
    "gpo_hearings": ("package_id",),
    "gpo_observations": ("package_id",),
    "youtube_videos": ("system_code", "video_id"),
    "captions": ("source", "native_id"),
    "transcripts": ("capture_id",),
    "rejected_pages": ("url", "offset", "retrieved_at"),
}

WEEKLY_TABLE_MERGES: dict[str, dict[str, Any]] = {
    "congress_meetings": {
        "order_by": "update_date",
        "columns": {
            "event_id": "latest_or_backfill",
            "congress": "latest_or_backfill",
            "chamber": "latest_or_backfill",
            "raw_sha256": "replace",
            "payload_json": "replace",
        },
    },
    "congress_committees": {
        "order_by": "update_date",
        "columns": {
            "chamber": "latest_or_backfill",
            "detail_sha256": "replace",
        },
    },
    "house_events": {
        "order_by": "merge_timestamp",
        "columns": {
            "witness_status": "latest_or_backfill",
            "seed": "latest_or_backfill",
            "source_body_sha256": "replace",
        },
    },
    "senate_events": {
        "order_by": "observed_at",
        "columns": {
            "url": "latest_or_backfill",
            "lines_sha256": "replace",
        },
    },
    "gpo_hearings": {
        "order_by": "last_modified",
        "columns": {
            "congress": "latest_or_backfill",
            "chamber": "latest_or_backfill",
            "committee_name": "latest_or_backfill",
            "issued_date": "latest_or_backfill",
            "title": "latest_or_backfill",
        },
    },
    "gpo_observations": {
        "order_by": "retrieved_at",
        "columns": {
            "acquisition": "latest_or_backfill",
            "evidence_sha256": "replace",
        },
    },
    "youtube_videos": {
        "order_by": "published_at",
        "columns": {
            "title": "latest_or_backfill",
            "upstream_sha256": "replace",
        },
    },
    "captions": {
        "order_by": "observed_at",
        "columns": {
            "kind": "latest_or_backfill",
            "outcome": "replace",
            "receipt_json": "replace",
        },
    },
    "transcripts": {
        "order_by": "observed_at",
        "columns": {
            "model": "replace",
            "start": "replace",
            "end": "replace",
            "transcript_sha256": "replace",
            "payload_json": "replace",
        },
    },
    "rejected_pages": {
        "order_by": "retrieved_at",
        "columns": {
            "response_sha256": "replace",
            "response_json": "replace",
        },
    },
}


def is_parquet_path(path: Path | str | None) -> bool:
    if path is None:
        return False
    suffixes = Path(path).suffixes
    return bool(suffixes and suffixes[-1] == ".parquet")


def canonical_json_str(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def stage_body_bytes(
    data: bytes,
    staging_dir: Path | str,
    *,
    is_pdf: bool | None = None,
) -> tuple[str, str]:
    """Stage raw payload bytes into local R2 CAS bodies/sha256/<xx>/<sha256>.{gz,pdf}."""
    digest = sha256(data).hexdigest()
    prefix = digest[:2]
    pdf = (data[:5] == b"%PDF-") if is_pdf is None else is_pdf
    ext = "pdf" if pdf else "gz"
    rel_key = f"bodies/sha256/{prefix}/{digest}.{ext}"

    target_path = Path(staging_dir) / rel_key
    if not target_path.exists():
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if pdf:
            target_path.write_bytes(data)
        else:
            target_path.write_bytes(gzip.compress(data, mtime=0))
    return digest, rel_key


def build_arrow_table(dataset: str, rows: Iterable[Mapping[str, Any]]) -> pa.Table:
    """Build a deterministically sorted Arrow table for ``dataset``."""
    schema = WEEKLY_TABLE_SCHEMAS[dataset]
    keys = WEEKLY_TABLE_KEYS[dataset]
    materialized = list(rows)

    # Validate non-empty primary keys
    for row in materialized:
        for k in keys:
            val = row.get(k)
            if val is None or (isinstance(val, str) and not val.strip()):
                raise ValueError(f"Dataset {dataset!r} primary key column {k!r} cannot be empty or null")

    materialized.sort(key=lambda row: tuple(row.get(k) for k in keys))
    columns = {
        field.name: [row.get(field.name) for row in materialized]
        for field in schema
    }
    table = pa.Table.from_pydict(columns, schema=schema)

    # Validate cell size ceiling: <= 256 KiB
    for col_name in table.column_names:
        field = schema.field(col_name)
        if pa.types.is_string(field.type) or pa.types.is_binary(field.type) or pa.types.is_large_string(field.type):
            col = table.column(col_name)
            for chunk in col.chunks:
                if len(chunk) > 0:
                    lens = pc.binary_length(chunk)
                    max_len = pc.max(lens).as_py() or 0
                    if max_len > 256 * 1024:
                        raise ValueError(
                            f"Dataset {dataset!r} column {col_name!r} exceeds 256 KiB cell limit (found {max_len:,} bytes)"
                        )
    return table


def write_parquet_table(path: Path | str, dataset: str, rows: Iterable[Mapping[str, Any]]) -> pa.Table:
    """Atomically write ``rows`` for ``dataset`` as a bounded-row-group Parquet file."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    table = build_arrow_table(dataset, rows)
    sink = pa.BufferOutputStream()
    pq.write_table(
        table,
        sink,
        compression="zstd",
        row_group_size=PARQUET_ROW_GROUP_SIZE,
        use_dictionary=True,
        write_statistics=True,
    )
    write_atomic_bytes(target, sink.getvalue().to_pybytes(), temp_mode="fixed", fsync=False)
    return table


def iter_parquet_rows(
    path: Path | str,
    *,
    columns: Sequence[str] | None = None,
    batch_size: int = 1024,
) -> Iterator[dict[str, Any]]:
    """Stream rows from a Parquet file in bounded Arrow batches."""
    target = Path(path)
    if not target.exists():
        return
    parquet_file = pq.ParquetFile(target)
    for batch in parquet_file.iter_batches(batch_size=batch_size, columns=list(columns) if columns else None):
        for row in batch.to_pylist():
            yield row


def merge_row_with_policy(
    dataset: str,
    existing: Mapping[str, Any] | None,
    incoming: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply ``WEEKLY_TABLE_MERGES[dataset]`` semantics to an existing and incoming row."""
    schema = WEEKLY_TABLE_SCHEMAS[dataset]
    if existing is None:
        return {field.name: incoming.get(field.name) for field in schema}
    merge_spec = WEEKLY_TABLE_MERGES.get(dataset)
    if not merge_spec:
        return {field.name: incoming.get(field.name) for field in schema}
    order_col = merge_spec["order_by"]
    col_policies = merge_spec.get("columns", {})
    inc_order = incoming.get(order_col)
    ext_order = existing.get(order_col)
    incoming_is_newer_or_equal = (
        ext_order is None
        or (inc_order is not None and str(inc_order) >= str(ext_order))
    )
    merged: dict[str, Any] = {}
    keys = set(WEEKLY_TABLE_KEYS[dataset])
    for field in schema:
        name = field.name
        inc_val = incoming.get(name)
        ext_val = existing.get(name)
        if name in keys:
            merged[name] = inc_val if inc_val is not None else ext_val
        elif name == order_col:
            if inc_val is not None and (ext_order is None or str(inc_val) >= str(ext_order)):
                merged[name] = inc_val
            else:
                merged[name] = ext_val
        else:
            policy = col_policies.get(name, "replace")
            if policy == "latest_or_backfill":
                if incoming_is_newer_or_equal:
                    merged[name] = inc_val if inc_val is not None else ext_val
                else:
                    merged[name] = ext_val if ext_val is not None else inc_val
            elif policy == "min":
                vals = [v for v in (ext_val, inc_val) if v is not None]
                merged[name] = min(vals) if vals else None
            elif policy == "max":
                vals = [v for v in (ext_val, inc_val) if v is not None]
                merged[name] = max(vals) if vals else None
            else:
                if incoming_is_newer_or_equal:
                    merged[name] = inc_val if inc_val is not None else ext_val
                else:
                    merged[name] = ext_val
    return merged


def meeting_to_row(
    source_url: str,
    record: Mapping[str, Any],
    *,
    staging_dir: Path | str | None = None,
) -> dict[str, Any]:
    congress_val = record.get("congress")
    try:
        congress_int = int(congress_val) if congress_val is not None else None
    except (TypeError, ValueError):
        congress_int = None
    row_dict = dict(record)
    row_dict.setdefault("_url", source_url)

    payload_str = canonical_json_str(row_dict)
    payload_bytes = payload_str.encode("utf-8")
    raw_sha256 = record.get("raw_sha256")
    if raw_sha256 is None:
        raw_sha256 = sha256(payload_bytes).hexdigest()
        if staging_dir is not None:
            stage_body_bytes(payload_bytes, staging_dir, is_pdf=False)

    update_date = str(record.get("updateDate") or record.get("update_date") or "1970-01-01T00:00:00Z")
    payload_json = payload_str if len(payload_bytes) <= 256 * 1024 else None

    return {
        "source_url": str(source_url),
        "event_id": str(record["eventId"]) if record.get("eventId") is not None else None,
        "congress": congress_int,
        "chamber": str(record["chamber"]) if record.get("chamber") is not None else None,
        "update_date": update_date,
        "raw_sha256": raw_sha256,
        "payload_json": payload_json,
    }


def committee_to_row(
    source_url_or_key: str,
    record: Mapping[str, Any],
    *,
    staging_dir: Path | str | None = None,
    unique_details: dict[bytes, str] | None = None,
) -> dict[str, Any]:
    comm = record.get("committee") if isinstance(record.get("committee"), Mapping) else record
    system_code = str(
        comm.get("systemCode")
        or comm.get("system_code")
        or record.get("systemCode")
        or record.get("system_code")
        or ""
    ).strip()
    if not system_code and source_url_or_key and not source_url_or_key.startswith("http"):
        system_code = source_url_or_key.strip()
    if not system_code:
        raise ValueError(f"congress_committees row missing system_code: {record}")

    congress_val = record.get("congress") or comm.get("congress")
    if congress_val is None:
        congress = 118
    else:
        congress = int(congress_val)

    chamber = str(comm.get("chamber") or record.get("chamber") or "").strip()
    if not chamber:
        if system_code.startswith("hs"):
            chamber = "House"
        elif system_code.startswith("ss"):
            chamber = "Senate"
        elif system_code.startswith("js"):
            chamber = "Joint"
        else:
            chamber = "House"

    update_date = str(
        comm.get("updateDate")
        or comm.get("update_date")
        or record.get("updateDate")
        or record.get("update_date")
        or record.get("retrieved_at")
        or "1970-01-01T00:00:00Z"
    ).strip()

    detail = record.get("detail")
    detail_sha256 = record.get("detail_sha256")
    if detail_sha256 is None and detail:
        if isinstance(detail, (dict, list)):
            detail_bytes = json.dumps(detail, sort_keys=True).encode("utf-8")
        elif isinstance(detail, str):
            detail_bytes = detail.encode("utf-8")
        elif isinstance(detail, (bytes, bytearray)):
            detail_bytes = bytes(detail)
        else:
            detail_bytes = str(detail).encode("utf-8")

        if unique_details is not None and detail_bytes in unique_details:
            detail_sha256 = unique_details[detail_bytes]
        else:
            detail_sha256 = sha256(detail_bytes).hexdigest()
            if unique_details is not None:
                unique_details[detail_bytes] = detail_sha256
            if staging_dir is not None:
                stage_body_bytes(detail_bytes, staging_dir, is_pdf=False)

    return {
        "congress": congress,
        "system_code": system_code,
        "chamber": chamber,
        "update_date": update_date,
        "detail_sha256": detail_sha256,
    }


def house_event_to_row(
    event_id: str,
    record: Mapping[str, Any],
    *,
    staging_dir: Path | str | None = None,
) -> dict[str, Any]:
    eid = str(event_id or record.get("event_id") or record.get("eventId") or "").strip()
    if not eid:
        raise ValueError(f"house_events row missing event_id: {record}")

    ts = (
        record.get("merge_timestamp")
        or record.get("imported_at")
        or record.get("checked")
        or record.get("xml_update")
        or record.get("version")
    )
    if ts is not None and isinstance(ts, str):
        ts = ts.strip()
    if not ts:
        raise ValueError(f"house_events row missing merge timestamp: {record}")

    body_sha = record.get("source_body_sha256")
    if body_sha is None:
        source_bodies = record.get("source_bodies")
        docs = record.get("documents")
        if source_bodies and isinstance(source_bodies, dict):
            first_body = next(iter(source_bodies.values()), None)
            if isinstance(first_body, dict) and first_body.get("sha256"):
                body_sha = first_body["sha256"]
            else:
                body_bytes = json.dumps(source_bodies, sort_keys=True).encode("utf-8")
                body_sha = sha256(body_bytes).hexdigest()
                if staging_dir is not None:
                    stage_body_bytes(body_bytes, staging_dir, is_pdf=False)
        elif docs and isinstance(docs, list):
            doc_bytes = json.dumps(docs, sort_keys=True).encode("utf-8")
            if len(doc_bytes) > 4096:
                body_sha = sha256(doc_bytes).hexdigest()
                if staging_dir is not None:
                    stage_body_bytes(doc_bytes, staging_dir, is_pdf=False)

    return {
        "event_id": eid,
        "merge_timestamp": str(ts),
        "witness_status": str(record["witness_status"]) if record.get("witness_status") is not None else None,
        "seed": str(record["seed"]) if record.get("seed") is not None else None,
        "source_body_sha256": body_sha,
    }


def senate_event_to_row(
    domain_or_id: str,
    record: Mapping[str, Any],
    record_id: str | None = None,
    *,
    staging_dir: Path | str | None = None,
) -> dict[str, Any]:
    pages = record.get("pages")
    page_dict = {}
    if record.get("url"):
        page_url = str(record["url"])
        rec_id = str(record_id or record.get("record_id") or sha256(page_url.encode("utf-8")).hexdigest()[:16])
        domain = str(record.get("domain") or (domain_or_id if "." in domain_or_id else "senate.gov"))
    elif isinstance(pages, Mapping) and pages:
        page_url = next(iter(pages.keys()))
        if isinstance(pages[page_url], Mapping):
            page_dict = pages[page_url]
        rec_id = str(record_id or record.get("record_id") or sha256(page_url.encode("utf-8")).hexdigest()[:16])
        domain = str(record.get("domain") or (domain_or_id if "." in domain_or_id else "senate.gov"))
    else:
        rec_id = str(domain_or_id)
        domain = str(record.get("domain") or (domain_or_id if "." in domain_or_id else "senate.gov"))
        page_url = str(record.get("url") or f"https://{domain}/{rec_id}")

    obs_at = (
        record.get("observed_at")
        or record.get("checked")
        or page_dict.get("observed_at")
        or page_dict.get("checked")
        or "1970-01-01T00:00:00Z"
    )

    lines_sha256 = record.get("lines_sha256")
    if lines_sha256 is None:
        lines = record.get("lines")
        html = record.get("html")
        if lines:
            body_text = "\n".join(lines) if isinstance(lines, list) else str(lines)
            body_bytes = body_text.encode("utf-8")
        elif html:
            body_text = str(html)
            body_bytes = body_text.encode("utf-8")
        else:
            body_text = None
            body_bytes = None

        if body_bytes:
            is_pdf = body_bytes.startswith(b"%PDF-") or page_url.lower().endswith(".pdf")
            lines_sha256 = sha256(body_bytes).hexdigest()
            if staging_dir is not None:
                stage_body_bytes(body_bytes, staging_dir, is_pdf=is_pdf)

    return {
        "domain": domain,
        "record_id": rec_id,
        "url": page_url,
        "observed_at": str(obs_at),
        "lines_sha256": lines_sha256,
    }


def gpo_hearing_to_row(package_id: str, record: Mapping[str, Any]) -> dict[str, Any]:
    pkg = str(package_id or record.get("package_id") or "").strip()
    if not pkg:
        raise ValueError(f"gpo_hearings row missing package_id: {record}")
    last_mod = str(
        record.get("last_modified")
        or record.get("lastModified")
        or record.get("issued_date")
        or "1970-01-01"
    )
    return {
        "package_id": pkg,
        "congress": str(record["congress"]) if record.get("congress") is not None else None,
        "chamber": str(record["chamber"]) if record.get("chamber") is not None else None,
        "committee_name": str(record["committee_name"]) if record.get("committee_name") is not None else None,
        "issued_date": str(record["issued_date"]) if record.get("issued_date") is not None else None,
        "last_modified": last_mod,
        "title": str(record["title"]) if record.get("title") is not None else None,
    }


def gpo_observation_to_row(
    package_id: str,
    record: Mapping[str, Any],
    *,
    staging_dir: Path | str | None = None,
) -> dict[str, Any]:
    pkg = str(package_id or record.get("package_id") or "").strip()
    if not pkg:
        raise ValueError(f"gpo_observations row missing package_id: {record}")

    timestamps: list[str] = []
    acquisitions: list[str] = []

    # Parser-stale refreshes can have only a rejected MODS response, with no
    # fresh listing or accepted metadata. Those checks are retained evidence too.
    for sec_name in ("mods", "listing", "manifest", "failed_mods", "failed_manifest"):
        sec = record.get(sec_name)
        if isinstance(sec, Mapping):
            if sec.get("retrieved_at"):
                timestamps.append(str(sec["retrieved_at"]))
            if sec.get("acquisition"):
                acquisitions.append(str(sec["acquisition"]))
            payload = sec.get("payload")
            if isinstance(payload, Mapping):
                if payload.get("lastModified"):
                    timestamps.append(str(payload["lastModified"]))
                if payload.get("dateIssued"):
                    timestamps.append(str(payload["dateIssued"]))

    transcripts_obj = record.get("transcripts")
    if isinstance(transcripts_obj, Mapping):
        for t in transcripts_obj.values():
            if isinstance(t, Mapping):
                if t.get("retrieved_at"):
                    timestamps.append(str(t["retrieved_at"]))
                if t.get("acquisition"):
                    acquisitions.append(str(t["acquisition"]))

    if record.get("retrieved_at"):
        timestamps.append(str(record["retrieved_at"]))
    if record.get("acquisition"):
        acquisitions.append(str(record["acquisition"]))
    if record.get("checked_at"):
        timestamps.append(str(record["checked_at"]))

    obs = record.get("observations")
    if isinstance(obs, Mapping):
        for o in obs.values():
            if isinstance(o, Mapping):
                if o.get("retrieved_at"):
                    timestamps.append(str(o["retrieved_at"]))
                if o.get("acquisition"):
                    acquisitions.append(str(o["acquisition"]))

    retrieved_at = max(timestamps) if timestamps else None
    if not retrieved_at:
        raise ValueError(f"gpo_observations row missing retrieved_at timestamp: {record}")
    acquisition = acquisitions[0] if acquisitions else "http"

    evidence_sha256 = record.get("evidence_sha256") or record.get("mods_sha256")
    if evidence_sha256 is None:
        mods = record.get("mods") if isinstance(record.get("mods"), Mapping) else {}
        if mods.get("sha256"):
            evidence_sha256 = str(mods["sha256"])
        elif mods.get("body"):
            body_bytes = mods["body"].encode("utf-8") if isinstance(mods["body"], str) else bytes(mods["body"])
            evidence_sha256 = sha256(body_bytes).hexdigest()
            if staging_dir is not None:
                stage_body_bytes(body_bytes, staging_dir, is_pdf=False)

    return {
        "package_id": pkg,
        "retrieved_at": str(retrieved_at),
        "acquisition": str(acquisition),
        "evidence_sha256": evidence_sha256,
    }


def youtube_video_to_row(
    system_code: str,
    record: Mapping[str, Any],
    *,
    staging_dir: Path | str | None = None,
) -> dict[str, Any]:
    vid = str(record.get("videoId") or record.get("video_id") or record.get("id") or "").strip()
    if not vid:
        raise ValueError(f"youtube_video row missing videoId: {record}")
    pub_at = (
        record.get("publishedAt")
        or record.get("videoPublishedAt")
        or record.get("published_at")
        or record.get("details_checked_at")
    )
    if not pub_at:
        raise ValueError(f"youtube_video row missing published_at: {record}")

    upstream = record.get("upstream")
    upstream_sha256 = record.get("upstream_sha256")
    if upstream_sha256 is None and upstream:
        if isinstance(upstream, (dict, list)):
            upstream_bytes = json.dumps(upstream, sort_keys=True).encode("utf-8")
        elif isinstance(upstream, str):
            upstream_bytes = upstream.encode("utf-8")
        elif isinstance(upstream, (bytes, bytearray)):
            upstream_bytes = bytes(upstream)
        else:
            upstream_bytes = str(upstream).encode("utf-8")
        if staging_dir is not None:
            upstream_sha256, _ = stage_body_bytes(upstream_bytes, staging_dir, is_pdf=False)
        else:
            upstream_sha256 = sha256(upstream_bytes).hexdigest()

    return {
        "system_code": str(system_code or record.get("systemCode") or ""),
        "video_id": vid,
        "published_at": str(pub_at),
        "title": str(record["title"]) if record.get("title") is not None else None,
        "upstream_sha256": upstream_sha256,
    }


def caption_to_row(
    source: str,
    native_id: str,
    *,
    kind: str | None = None,
    outcome: str | None = None,
    observed_at: str | None = None,
    receipt: Mapping[str, Any] | None = None,
    default_observed_at: str | None = "2026-09-27",
) -> dict[str, Any]:
    out = outcome or "present"
    obs = observed_at or default_observed_at or "2026-09-27"
    receipt_json = None
    if receipt is not None:
        out = str(receipt["outcome"]) if receipt.get("outcome") is not None else out
        obs = str(receipt["observed_at"]) if receipt.get("observed_at") is not None else obs
        receipt_json = canonical_json_str(receipt)
        if kind is None and receipt.get("kind") is not None:
            kind = str(receipt["kind"])
    return {
        "source": str(source),
        "native_id": str(native_id),
        "kind": str(kind) if kind is not None else None,
        "outcome": str(out),
        "observed_at": str(obs),
        "receipt_json": receipt_json,
    }


def transcript_to_row(
    capture_id: str,
    capture_payload: Mapping[str, Any],
    *,
    staging_dir: Path | str | None = None,
) -> dict[str, Any]:
    cid = str(capture_id or capture_payload.get("capture_id") or "").strip()
    if not cid:
        raise ValueError(f"transcripts row missing capture_id: {capture_payload}")
    obs_at = str(capture_payload.get("observed_at") or "1970-01-01T00:00:00Z")

    payload_str = canonical_json_str(capture_payload)
    payload_bytes = payload_str.encode("utf-8")
    t_sha256 = capture_payload.get("transcript_sha256")
    if t_sha256 is None:
        t_sha256 = sha256(payload_bytes).hexdigest()
        if staging_dir is not None:
            stage_body_bytes(payload_bytes, staging_dir, is_pdf=False)
    payload_json = payload_str if len(payload_bytes) <= 256 * 1024 else None

    return {
        "capture_id": cid,
        "model": str(capture_payload.get("model") or ""),
        "start": float(capture_payload.get("start") or 0.0),
        "end": float(capture_payload.get("end") or 0.0),
        "observed_at": obs_at,
        "transcript_sha256": t_sha256,
        "payload_json": payload_json,
    }


def rejected_page_to_row(
    *,
    url: str,
    offset: int,
    retrieved_at: str,
    response: Any,
    staging_dir: Path | str | None = None,
) -> dict[str, Any]:
    u = str(url).strip()
    if not u:
        raise ValueError("rejected_pages row missing url")
    r_at = str(retrieved_at).strip()
    if not r_at:
        raise ValueError("rejected_pages row missing retrieved_at")

    resp_json = canonical_json_str(response)
    resp_bytes = resp_json.encode("utf-8")
    resp_sha256 = sha256(resp_bytes).hexdigest()
    if staging_dir is not None:
        stage_body_bytes(resp_bytes, staging_dir, is_pdf=False)
    response_json = resp_json if len(resp_bytes) <= 256 * 1024 else None

    return {
        "url": u,
        "offset": int(offset),
        "retrieved_at": r_at,
        "response_sha256": resp_sha256,
        "response_json": response_json,
    }


class WeeklyRetentionTables:
    """Incremental ``docspec-rs`` table manager for the weekly retention datasets."""

    def __init__(self, workspace: Path | str, *, binary: Path | str | None = None):
        self.workspace = Path(workspace).resolve()
        self.binary = resolve_docspec_binary(binary)
        self.datasets = NativeDatasets(self.binary, self.workspace)

    def close(self) -> None:
        self.datasets.close()

    def __enter__(self) -> WeeklyRetentionTables:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def latest_version(self, dataset: str) -> dict[str, Any] | None:
        return self.datasets.try_latest(dataset)

    def _resolve_pin(self, dataset: str, version: str | dict[str, Any] | None) -> dict[str, Any] | None:
        if isinstance(version, dict):
            return version
        if version is None:
            return self.latest_version(dataset)
        return self.datasets.release(dataset, version)

    def _operation_id(self, dataset: str, prefix: str, table: pa.Table) -> str:
        hasher = sha256()
        hasher.update(str(table.num_rows).encode("ascii"))
        for col in table.columns:
            for chunk in col.chunks:
                for buf in chunk.buffers():
                    if buf is not None:
                        hasher.update(buf)
        digest = hasher.hexdigest()[:16]
        base = self.latest_version(dataset)
        base_id = base["id"] if base is not None else "init"
        combined = sha256(f"{base_id}:{digest}".encode("utf-8")).hexdigest()[:24]
        raw = f"{prefix}-{dataset}-{combined}"
        return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in raw)[:64]

    def _upsert_batch(
        self,
        dataset: str,
        chunk: Sequence[Mapping[str, Any]],
        *,
        operation: str | None = None,
        deletions: pa.Table | None = None,
        use_merge: bool = True,
    ) -> dict[str, Any] | None:
        keys = WEEKLY_TABLE_KEYS[dataset]
        order_by = WEEKLY_TABLE_MERGES.get(dataset, {}).get("order_by") if use_merge else None

        for i, row in enumerate(chunk):
            for k in keys:
                val = row.get(k)
                if val is None or (isinstance(val, str) and not val.strip()):
                    raise ValueError(
                        f"Integrity violation in dataset {dataset!r} row {i}: "
                        f"primary key column {k!r} cannot be empty or null. Row: {row}"
                    )
            if order_by:
                ord_val = row.get(order_by)
                if ord_val is None or (isinstance(ord_val, str) and not ord_val.strip()):
                    raise ValueError(
                        f"Integrity violation in dataset {dataset!r} row {i}: "
                        f"merge order_by column {order_by!r} cannot be null or empty. Row: {row}"
                    )

        deduped: dict[tuple[Any, ...], dict[str, Any]] = {}
        for row in chunk:
            key_tuple = tuple(row.get(k) for k in keys)
            deduped[key_tuple] = merge_row_with_policy(dataset, deduped.get(key_tuple), row)
        table = build_arrow_table(dataset, deduped.values())
        base = self.latest_version(dataset)
        if base is None:
            op_id = operation or self._operation_id(dataset, "admit", table)
            return self.datasets.run_table(
                table,
                dataset=dataset,
                operation=op_id,
                definition=WEEKLY_TABLE_DEFINITION,
            )

        op_id = operation or self._operation_id(dataset, "update", table)
        merge_spec = WEEKLY_TABLE_MERGES.get(dataset) if use_merge else None
        try:
            return self.datasets.update_table(
                table,
                dataset=dataset,
                operation=op_id,
                definition=WEEKLY_TABLE_DEFINITION,
                base=base["id"],
                keys=keys,
                deletions=deletions,
                merge=merge_spec,
            )
        except DocSpecFailure as err:
            if merge_spec is None or "unknown field `merge`" not in str(err):
                raise
            # Pre-ss-023x binary compatibility fallback: read only the affected keys
            # and apply the declarative merge spec before submitting replace_keys.
            existing_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
            if len(keys) == 1:
                key_col = keys[0]
                lookup_vals = [str(k[0]) for k in deduped if k[0] is not None]
                if lookup_vals:
                    existing_table = self.read_keys(dataset, lookup_vals, key=key_col)
                    for row in existing_table.to_pylist():
                        existing_by_key[(row.get(key_col),)] = row
            else:
                for row in self.iter_rows(dataset):
                    k_tuple = tuple(row.get(k) for k in keys)
                    if k_tuple in deduped:
                        existing_by_key[k_tuple] = row
            merged_rows = [
                merge_row_with_policy(dataset, existing_by_key.get(k_tuple), inc_row)
                for k_tuple, inc_row in deduped.items()
            ]
            merged_table = build_arrow_table(dataset, merged_rows)
            fallback_op = operation or self._operation_id(dataset, "update-merged", merged_table)
            return self.datasets.update_table(
                merged_table,
                dataset=dataset,
                operation=fallback_op,
                definition=WEEKLY_TABLE_DEFINITION,
                base=base["id"],
                keys=keys,
                deletions=deletions,
                merge=None,
            )

    def upsert_rows(
        self,
        dataset: str,
        rows: Iterable[Mapping[str, Any]],
        *,
        operation: str | None = None,
        deletions: pa.Table | None = None,
        use_merge: bool = True,
        chunk_size: int = 10_000,
    ) -> dict[str, Any] | None:
        """Incrementally admit or update ``dataset`` in bounded chunks by primary key and ``UpdateMergeSpec``."""
        last_pin = self.latest_version(dataset)
        saw_chunk = False
        max_rows = max(1, int(chunk_size))
        max_chunk_bytes = 2_000_000
        chunk: list[Mapping[str, Any]] = []
        chunk_bytes = 0
        idx = 0
        for row in rows:
            row_bytes = sum(len(v) if isinstance(v, (str, bytes)) else 16 for v in row.values())
            if chunk and (len(chunk) >= max_rows or chunk_bytes + row_bytes > max_chunk_bytes):
                saw_chunk = True
                chunk_op = (f"{operation}-{idx}" if idx > 0 else operation) if operation else None
                last_pin = self._upsert_batch(
                    dataset,
                    chunk,
                    operation=chunk_op,
                    deletions=deletions if idx == 0 else None,
                    use_merge=use_merge,
                )
                idx += 1
                chunk = []
                chunk_bytes = 0
            chunk.append(row)
            chunk_bytes += row_bytes
        if chunk:
            saw_chunk = True
            chunk_op = (f"{operation}-{idx}" if idx > 0 else operation) if operation else None
            last_pin = self._upsert_batch(
                dataset,
                chunk,
                operation=chunk_op,
                deletions=deletions if idx == 0 else None,
                use_merge=use_merge,
            )
        if not saw_chunk and deletions is not None:
            return self._upsert_batch(
                dataset,
                (),
                operation=operation,
                deletions=deletions,
                use_merge=use_merge,
            )
        return last_pin

    def read_table(
        self,
        dataset: str,
        *,
        version: str | dict[str, Any] | None = None,
        columns: Sequence[str] | None = None,
    ) -> pa.Table:
        """Read ``dataset`` as an Arrow Table at ``version`` (or latest)."""
        pin = self._resolve_pin(dataset, version)
        if pin is None:
            return build_arrow_table(dataset, ())
        return self.datasets.read_arrow(
            pin,
            columns=list(columns) if columns is not None else None,
            schema=WEEKLY_TABLE_SCHEMAS[dataset],
        )

    def iter_batches(
        self,
        dataset: str,
        *,
        version: str | dict[str, Any] | None = None,
        columns: Sequence[str] | None = None,
        batch_size: int = 1024,
    ) -> Iterator[pa.RecordBatch]:
        """Stream Arrow ``RecordBatch``es from ``dataset`` without materializing a full Python list."""
        pin = self._resolve_pin(dataset, version)
        if pin is None:
            return
        with self.datasets.source_batches(
            pin,
            schema=WEEKLY_TABLE_SCHEMAS[dataset],
            columns=list(columns) if columns is not None else None,
        ) as reader:
            for batch in reader:
                if batch.num_rows <= batch_size:
                    yield batch
                else:
                    for offset in range(0, batch.num_rows, batch_size):
                        yield batch.slice(offset, min(batch_size, batch.num_rows - offset))

    def iter_rows(
        self,
        dataset: str,
        *,
        version: str | dict[str, Any] | None = None,
        columns: Sequence[str] | None = None,
        batch_size: int = 1024,
    ) -> Iterator[dict[str, Any]]:
        """Stream row dictionaries from ``dataset`` in bounded Arrow batches."""
        for batch in self.iter_batches(dataset, version=version, columns=columns, batch_size=batch_size):
            for row in batch.to_pylist():
                yield row

    def read_keys(
        self,
        dataset: str,
        values: Sequence[str],
        *,
        key: str | None = None,
        version: str | dict[str, Any] | None = None,
        columns: Sequence[str] | None = None,
    ) -> pa.Table:
        """Read only matching keys from ``dataset`` using native key-scoped lookup."""
        pin = self._resolve_pin(dataset, version)
        if pin is None or not values:
            return build_arrow_table(dataset, ())
        key_col = key or WEEKLY_TABLE_KEYS[dataset][0]
        full_schema = WEEKLY_TABLE_SCHEMAS[dataset]
        target_schema = (
            pa.schema([full_schema.field(name) for name in columns], metadata=full_schema.metadata)
            if columns is not None
            else full_schema
        )
        return self.datasets.read_keys(
            pin,
            key_col,
            [str(v) for v in values],
            columns=list(columns) if columns is not None else None,
            schema=target_schema,
        )
