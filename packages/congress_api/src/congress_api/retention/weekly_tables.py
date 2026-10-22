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
import json
import os
from pathlib import Path
import shutil
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from congress_shared.custody import write_atomic_bytes
from docspec_client import DocSpecFailure, NativeDatasets

WEEKLY_TABLE_DEFINITION = "weekly-retention-v1"
PARQUET_ROW_GROUP_SIZE = 2048

WEEKLY_TABLE_SCHEMAS: dict[str, pa.Schema] = {
    "congress_meetings": pa.schema([
        pa.field("source_url", pa.string(), nullable=False),
        pa.field("event_id", pa.string(), nullable=True),
        pa.field("congress", pa.int64(), nullable=True),
        pa.field("chamber", pa.string(), nullable=True),
        pa.field("update_date", pa.string(), nullable=True),
        pa.field("payload_json", pa.string(), nullable=False),
    ]),
    "congress_committees": pa.schema([
        pa.field("source_url", pa.string(), nullable=False),
        pa.field("system_code", pa.string(), nullable=True),
        pa.field("chamber", pa.string(), nullable=True),
        pa.field("update_date", pa.string(), nullable=True),
        pa.field("payload_json", pa.string(), nullable=False),
    ]),
    "house_events": pa.schema([
        pa.field("event_id", pa.string(), nullable=False),
        pa.field("imported_at", pa.string(), nullable=True),
        pa.field("witness_status", pa.string(), nullable=True),
        pa.field("seed", pa.string(), nullable=True),
        pa.field("payload_json", pa.string(), nullable=False),
    ]),
    "senate_events": pa.schema([
        pa.field("record_id", pa.string(), nullable=False),
        pa.field("url", pa.string(), nullable=True),
        pa.field("observed_at", pa.string(), nullable=True),
        pa.field("payload_json", pa.string(), nullable=False),
    ]),
    "gpo_hearings": pa.schema([
        pa.field("package_id", pa.string(), nullable=False),
        pa.field("congress", pa.string(), nullable=True),
        pa.field("chamber", pa.string(), nullable=True),
        pa.field("committee_name", pa.string(), nullable=True),
        pa.field("issued_date", pa.string(), nullable=True),
        pa.field("last_modified", pa.string(), nullable=True),
        pa.field("title", pa.string(), nullable=True),
        pa.field("payload_json", pa.string(), nullable=False),
    ]),
    "gpo_observations": pa.schema([
        pa.field("package_id", pa.string(), nullable=False),
        pa.field("retrieved_at", pa.string(), nullable=True),
        pa.field("acquisition", pa.string(), nullable=True),
        pa.field("payload_json", pa.string(), nullable=False),
    ]),
    "youtube_videos": pa.schema([
        pa.field("system_code", pa.string(), nullable=False),
        pa.field("video_id", pa.string(), nullable=False),
        pa.field("published_at", pa.string(), nullable=True),
        pa.field("title", pa.string(), nullable=True),
        pa.field("payload_json", pa.string(), nullable=False),
    ]),
    "captions": pa.schema([
        pa.field("source", pa.string(), nullable=False),
        pa.field("native_id", pa.string(), nullable=False),
        pa.field("kind", pa.string(), nullable=True),
        pa.field("outcome", pa.string(), nullable=True),
        pa.field("observed_at", pa.string(), nullable=True),
        pa.field("last_successful_json", pa.string(), nullable=True),
        pa.field("receipt_json", pa.string(), nullable=True),
    ]),
    "transcripts": pa.schema([
        pa.field("capture_id", pa.string(), nullable=False),
        pa.field("model", pa.string(), nullable=False),
        pa.field("start", pa.float64(), nullable=False),
        pa.field("end", pa.float64(), nullable=False),
        pa.field("observed_at", pa.string(), nullable=False),
        pa.field("payload_json", pa.string(), nullable=False),
    ]),
    "rejected_pages": pa.schema([
        pa.field("url", pa.string(), nullable=False),
        pa.field("offset", pa.int64(), nullable=False),
        pa.field("retrieved_at", pa.string(), nullable=False),
        pa.field("response_json", pa.string(), nullable=False),
    ]),
}

WEEKLY_TABLE_KEYS: dict[str, tuple[str, ...]] = {
    "congress_meetings": ("source_url",),
    "congress_committees": ("source_url",),
    "house_events": ("event_id",),
    "senate_events": ("record_id",),
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
            "payload_json": "replace",
        },
    },
    "congress_committees": {
        "order_by": "update_date",
        "columns": {
            "system_code": "latest_or_backfill",
            "chamber": "latest_or_backfill",
            "payload_json": "replace",
        },
    },
    "house_events": {
        "order_by": "imported_at",
        "columns": {
            "witness_status": "latest_or_backfill",
            "seed": "latest_or_backfill",
            "payload_json": "latest_or_backfill",
        },
    },
    "senate_events": {
        "order_by": "observed_at",
        "columns": {
            "url": "latest_or_backfill",
            "payload_json": "latest_or_backfill",
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
            "payload_json": "replace",
        },
    },
    "gpo_observations": {
        "order_by": "retrieved_at",
        "columns": {
            "acquisition": "latest_or_backfill",
            "payload_json": "latest_or_backfill",
        },
    },
    "youtube_videos": {
        "order_by": "published_at",
        "columns": {
            "title": "latest_or_backfill",
            "payload_json": "replace",
        },
    },
    "captions": {
        "order_by": "observed_at",
        "columns": {
            "kind": "latest_or_backfill",
            "outcome": "replace",
            "last_successful_json": "latest_or_backfill",
            "receipt_json": "replace",
        },
    },
    "transcripts": {
        "order_by": "observed_at",
        "columns": {
            "model": "replace",
            "start": "replace",
            "end": "replace",
            "payload_json": "replace",
        },
    },
    "rejected_pages": {
        "order_by": "retrieved_at",
        "columns": {
            "response_json": "replace",
        },
    },
}


def resolve_docspec_binary(binary: Path | str | None = None) -> Path:
    """Locate the native ``docspec`` binary for incremental table operations."""
    if binary is not None:
        return Path(binary).resolve()
    env_bin = os.environ.get("DOCSPEC_BIN")
    if env_bin and Path(env_bin).exists():
        return Path(env_bin).resolve()
    candidates = (
        Path("/Users/mikewolfd/.gemini/antigravity/brain/b9128fc0-078b-4f90-8508-e77d78324209/scratch/worktrees/wt-ss-023x-65bz/target/debug/docspec"),
        Path("/Users/mikewolfd/Work/spicy-stack/docspec-rs/target/debug/docspec"),
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    found = shutil.which("docspec")
    if found:
        return Path(found).resolve()
    raise FileNotFoundError("Unable to locate native docspec binary")


def is_parquet_path(path: Path | str | None) -> bool:
    if path is None:
        return False
    suffixes = Path(path).suffixes
    return bool(suffixes and suffixes[-1] == ".parquet")


def canonical_json_str(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def build_arrow_table(dataset: str, rows: Iterable[Mapping[str, Any]]) -> pa.Table:
    """Build a deterministically sorted Arrow table for ``dataset``."""
    schema = WEEKLY_TABLE_SCHEMAS[dataset]
    keys = WEEKLY_TABLE_KEYS[dataset]
    materialized = list(rows)
    materialized.sort(key=lambda row: tuple(row.get(k) or "" for k in keys))
    columns = {
        field.name: [row.get(field.name) for row in materialized]
        for field in schema
    }
    return pa.Table.from_pydict(columns, schema=schema)


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
        or (inc_order is not None and inc_order >= ext_order)
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
            if inc_val is not None and (ext_val is None or inc_val >= ext_val):
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
                    merged[name] = inc_val
                else:
                    merged[name] = ext_val
    return merged


def meeting_to_row(source_url: str, record: Mapping[str, Any]) -> dict[str, Any]:
    congress_val = record.get("congress")
    try:
        congress_int = int(congress_val) if congress_val is not None else None
    except (TypeError, ValueError):
        congress_int = None
    row_dict = dict(record)
    row_dict.setdefault("_url", source_url)
    return {
        "source_url": str(source_url),
        "event_id": str(record["eventId"]) if record.get("eventId") is not None else None,
        "congress": congress_int,
        "chamber": str(record["chamber"]) if record.get("chamber") is not None else None,
        "update_date": str(record["updateDate"]) if record.get("updateDate") is not None else None,
        "payload_json": canonical_json_str(row_dict),
    }


def committee_to_row(source_url: str, record: Mapping[str, Any]) -> dict[str, Any]:
    row_dict = dict(record)
    row_dict.setdefault("_url", source_url)
    return {
        "source_url": str(source_url),
        "system_code": str(record["systemCode"]) if record.get("systemCode") is not None else None,
        "chamber": str(record["chamber"]) if record.get("chamber") is not None else None,
        "update_date": str(record["updateDate"]) if record.get("updateDate") is not None else None,
        "payload_json": canonical_json_str(row_dict),
    }


def house_event_to_row(event_id: str, record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "event_id": str(event_id),
        "imported_at": str(record["imported_at"]) if record.get("imported_at") is not None else None,
        "witness_status": str(record["witness_status"]) if record.get("witness_status") is not None else None,
        "seed": str(record["seed"]) if record.get("seed") is not None else None,
        "payload_json": canonical_json_str(record),
    }


def senate_event_to_row(record_id: str, record: Mapping[str, Any]) -> dict[str, Any]:
    url = record.get("url") if isinstance(record, Mapping) else None
    observed_at = record.get("observed_at") if isinstance(record, Mapping) else None
    return {
        "record_id": str(record_id),
        "url": str(url) if url is not None else None,
        "observed_at": str(observed_at) if observed_at is not None else None,
        "payload_json": canonical_json_str(record),
    }


def gpo_hearing_to_row(package_id: str, record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "package_id": str(package_id),
        "congress": str(record["congress"]) if record.get("congress") is not None else None,
        "chamber": str(record["chamber"]) if record.get("chamber") is not None else None,
        "committee_name": str(record["committee_name"]) if record.get("committee_name") is not None else None,
        "issued_date": str(record["issued_date"]) if record.get("issued_date") is not None else None,
        "last_modified": str(record["last_modified"]) if record.get("last_modified") is not None else None,
        "title": str(record["title"]) if record.get("title") is not None else None,
        "payload_json": canonical_json_str(record),
    }


def gpo_observation_to_row(package_id: str, record: Mapping[str, Any]) -> dict[str, Any]:
    observations = record.get("observations") if isinstance(record, Mapping) else None
    retrieved_at = None
    acquisition = None
    if isinstance(observations, Mapping):
        for obs in observations.values():
            if isinstance(obs, Mapping):
                ts = obs.get("retrieved_at")
                if ts and (retrieved_at is None or str(ts) > retrieved_at):
                    retrieved_at = str(ts)
                acq = obs.get("acquisition")
                if acq and acquisition is None:
                    acquisition = str(acq)
    return {
        "package_id": str(package_id),
        "retrieved_at": retrieved_at,
        "acquisition": acquisition,
        "payload_json": canonical_json_str(record),
    }


def youtube_video_to_row(system_code: str, record: Mapping[str, Any]) -> dict[str, Any]:
    video_id = str(record.get("video_id") or record.get("id") or "")
    return {
        "system_code": str(system_code),
        "video_id": video_id,
        "published_at": str(record["published_at"]) if record.get("published_at") is not None else None,
        "title": str(record["title"]) if record.get("title") is not None else None,
        "payload_json": canonical_json_str(record),
    }


def caption_to_row(
    source: str,
    native_id: str,
    *,
    kind: str | None = None,
    receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    outcome = None
    observed_at = None
    last_successful_json = None
    receipt_json = None
    if receipt is not None:
        outcome = str(receipt["outcome"]) if receipt.get("outcome") is not None else None
        observed_at = str(receipt["observed_at"]) if receipt.get("observed_at") is not None else None
        if receipt.get("last_successful") is not None:
            last_successful_json = canonical_json_str(receipt["last_successful"])
        receipt_json = canonical_json_str(receipt)
        if kind is None and receipt.get("kind") is not None:
            kind = str(receipt["kind"])
    return {
        "source": str(source),
        "native_id": str(native_id),
        "kind": str(kind) if kind is not None else None,
        "outcome": outcome,
        "observed_at": observed_at,
        "last_successful_json": last_successful_json,
        "receipt_json": receipt_json,
    }


def transcript_to_row(capture_id: str, capture_payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "capture_id": str(capture_id),
        "model": str(capture_payload.get("model") or ""),
        "start": float(capture_payload.get("start") or 0.0),
        "end": float(capture_payload.get("end") or 0.0),
        "observed_at": str(capture_payload.get("observed_at") or ""),
        "payload_json": canonical_json_str(capture_payload),
    }


def rejected_page_to_row(
    *,
    url: str,
    offset: int,
    retrieved_at: str,
    response: Any,
) -> dict[str, Any]:
    return {
        "url": str(url),
        "offset": int(offset),
        "retrieved_at": str(retrieved_at),
        "response_json": canonical_json_str(response),
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
        sink = pa.BufferOutputStream()
        pq.write_table(table, sink, compression="zstd", row_group_size=PARQUET_ROW_GROUP_SIZE)
        digest = sha256(sink.getvalue().to_pybytes()).hexdigest()[:16]
        base = self.latest_version(dataset)
        base_id = base["id"] if base is not None else "init"
        raw = f"{prefix}-{dataset}-{base_id}-{digest}"
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
        for idx, chunk in enumerate(batched(rows, max(1, int(chunk_size)))):
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
