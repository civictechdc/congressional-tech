"""Sorted gzip JSONL or Parquet/docspec-rs snapshots with atomic replace.

Meeting and committee retention share this writer. Each caller owns its row
type; this module does not validate them.
"""

from __future__ import annotations

import gzip
import io
import json
from pathlib import Path

from congress_shared.custody import write_atomic_bytes

from congress_api.retention.weekly_tables import (
    WeeklyRetentionTables,
    committee_to_row,
    is_parquet_path,
    iter_parquet_rows,
    meeting_to_row,
    write_parquet_table,
)


def _record_to_table_row(dataset: str, key: str, value: dict) -> dict:
    if dataset == "congress_committees":
        return committee_to_row(key, value)
    return meeting_to_row(key, value)


def write(
    records: dict,
    path: Path,
    *,
    dataset: str = "congress_meetings",
    tables: WeeklyRetentionTables | None = None,
) -> None:
    """Write record values as gzip JSONL or Parquet, ordered by sorted dict key.

    ``mtime=0`` keeps identical content byte-identical. A failed replace leaves
    the previous file in place and removes the temporary. When ``tables`` is
    provided, also incrementally updates the ``docspec-rs`` dataset.
    """
    if tables is not None:
        tables.upsert_rows(
            dataset,
            (_record_to_table_row(dataset, key, records[key]) for key in sorted(records)),
        )
    if is_parquet_path(path):
        write_parquet_table(
            path,
            dataset,
            (_record_to_table_row(dataset, key, records[key]) for key in sorted(records)),
        )
        return
    buf = io.BytesIO()
    with gzip.GzipFile(filename="", fileobj=buf, mode="wb", mtime=0) as stream:
        for key in sorted(records):
            stream.write((json.dumps(records[key], sort_keys=True) + "\n").encode("utf-8"))
    write_atomic_bytes(path, buf.getvalue(), temp_mode="fixed", fsync=False)


def iter_json_lines(
    path: Path,
    *,
    dataset: str = "congress_meetings",
    tables: WeeklyRetentionTables | None = None,
):
    """Yield raw JSON line strings from a Parquet/docspec table or gzip JSONL file."""
    if tables is not None and (path is None or not Path(path).exists()):
        for row in tables.iter_rows(dataset, columns=("payload_json",)):
            yield row["payload_json"]
        return
    if is_parquet_path(path):
        if not Path(path).exists():
            raise FileNotFoundError(path)
        for row in iter_parquet_rows(path, columns=("payload_json",)):
            yield row["payload_json"]
        return
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        yield from stream

