"""Retain the upstream bytes separately from the small GPO CSV.

Cached replay never invents a retrieval time. Source rosters remain XML evidence;
being named in MODS is not an assertion of attendance at a hearing.
"""

from __future__ import annotations

from collections.abc import Sequence
import csv
from dataclasses import fields
import gzip
import json
from pathlib import Path

from congress_shared.custody import write_atomic_bytes

from congress_api.models.content import RawContent
from congress_api.models.gpo import GpoEvidenceObservation, GpoEvidenceRecord
from congress_api.parsers.gpo_hearings import GpoHearing
from congress_api.retention import tables
from congress_api.retention.weekly_tables import (
    WeeklyRetentionTables,
    gpo_hearing_to_row,
    gpo_observation_to_row,
    is_parquet_path,
    iter_parquet_rows,
    write_parquet_table,
)


def read_csv(
    path: Path | None = None,
    *,
    weekly_tables: WeeklyRetentionTables | None = None,
) -> dict[str, dict]:
    if weekly_tables is not None and (path is None or not Path(path).exists()):
        return {
            row["package_id"]: json.loads(row["payload_json"])
            for row in weekly_tables.iter_rows("gpo_hearings", columns=("package_id", "payload_json"))
        }
    if path is None or not Path(path).exists():
        return {}
    if is_parquet_path(path):
        return {
            row["package_id"]: json.loads(row["payload_json"])
            for row in iter_parquet_rows(path, columns=("package_id", "payload_json"))
        }
    with open(path, newline="", encoding="utf-8") as handle:
        return {row["package_id"]: row for row in csv.DictReader(handle)}


def write_csv(
    rows: dict[str, dict],
    path: Path,
    *,
    weekly_tables: WeeklyRetentionTables | None = None,
) -> None:
    if weekly_tables is not None:
        upsert_hearings(rows, weekly_tables)
    if is_parquet_path(path):
        write_parquet_table(
            path,
            "gpo_hearings",
            (gpo_hearing_to_row(pkg, rows[pkg]) for pkg in sorted(rows)),
        )
        return
    field_names = [field.name for field in fields(GpoHearing)]
    def ordered_rows():
        # Keep sorting inside the writer's temporary-file cleanup boundary.
        for package_id in sorted(rows):
            yield rows[package_id]
    tables.write_csv(path, ordered_rows(), field_names)


def upsert_hearings(rows: dict[str, dict], weekly_tables: WeeklyRetentionTables):
    """Incrementally admit or update ``gpo_hearings`` rows by ``package_id``."""
    return weekly_tables.upsert_rows(
        "gpo_hearings",
        (gpo_hearing_to_row(pkg, rows[pkg]) for pkg in sorted(rows)),
    )


def write_pending(values, path):
    write_atomic_bytes(
        path,
        (json.dumps(values, sort_keys=True) + '\n').encode('utf-8'),
        temp_mode='fixed',
    )


def observation(data: bytes, url: str, media_type: str, *, retrieved_at=None):
    content = RawContent.from_bytes(data, media_type)
    return GpoEvidenceObservation(**content.source_dict(), url=url, retrieved_at=retrieved_at,
        acquisition='http' if retrieved_at else 'cached-replay').source_dict()


def body_bytes(value):
    return GpoEvidenceObservation.model_validate(value).body_bytes()


def write_observation(value: GpoEvidenceObservation, path: Path):
    """Atomically retain one source response beside a local extracted transcript."""
    write_atomic_bytes(
        path,
        value.model_dump_json(by_alias=True, exclude_unset=True).encode('utf-8'),
        temp_mode='fixed',
    )


def _iter_observation_lines(
    path: Path | None = None,
    *,
    weekly_tables: WeeklyRetentionTables | None = None,
):
    if weekly_tables is not None and (path is None or not Path(path).exists()):
        for row in weekly_tables.iter_rows("gpo_observations", columns=("payload_json",)):
            yield row["payload_json"]
        return
    if path is None or not Path(path).exists():
        return
    if is_parquet_path(path):
        for row in iter_parquet_rows(path, columns=("payload_json",)):
            yield row["payload_json"]
        return
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        yield from stream


def read(
    path: Path | None = None,
    *,
    weekly_tables: WeeklyRetentionTables | None = None,
    package_ids: Sequence[str] | None = None,
):
    if package_ids is not None and weekly_tables is not None:
        arrow_table = weekly_tables.read_keys("gpo_observations", package_ids, key="package_id")
        return {
            row["package_id"]: GpoEvidenceRecord.model_validate_json(row["payload_json"]).source_dict()
            for row in arrow_table.to_pylist()
        }
    result = {}
    for line in _iter_observation_lines(path, weekly_tables=weekly_tables):
        value = GpoEvidenceRecord.model_validate_json(line).source_dict()
        package = value['package_id']
        if package in result:
            raise ValueError(f'Duplicate GPO evidence package: {package}')
        result[package] = value
    return result


def upsert_observations(values: dict[str, dict], weekly_tables: WeeklyRetentionTables):
    """Incrementally admit or update ``gpo_observations`` rows by ``package_id``."""
    return weekly_tables.upsert_rows(
        "gpo_observations",
        (gpo_observation_to_row(pkg, values[pkg]) for pkg in sorted(values)),
    )


def write(
    values,
    path: Path,
    *,
    weekly_tables: WeeklyRetentionTables | None = None,
):
    import io
    if weekly_tables is not None:
        upsert_observations(values, weekly_tables)
    if is_parquet_path(path):
        write_parquet_table(
            path,
            "gpo_observations",
            (gpo_observation_to_row(pkg, values[pkg]) for pkg in sorted(values)),
        )
        return
    # Stable gzip headers keep a replay with identical data byte-identical.
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode='wb', mtime=0, filename='') as stream:
        for package in sorted(values):
            stream.write((json.dumps(values[package], ensure_ascii=False, separators=(',', ':'), sort_keys=True) + '\n').encode())
    write_atomic_bytes(path, buf.getvalue(), temp_mode='fixed', fsync=False)
