"""Retain the upstream bytes separately from the small GPO CSV.

Cached replay never invents a retrieval time. Source rosters remain XML evidence;
being named in MODS is not an assertion of attendance at a hearing.
"""

from __future__ import annotations

import csv
import gzip
import json
from dataclasses import fields
from pathlib import Path

from congress_api.models.content import RawContent
from congress_api.models.gpo import GpoEvidenceObservation, GpoEvidenceRecord
from congress_api.parsers.gpo_hearings import GpoHearing


def read_csv(path: Path) -> dict[str, dict]:
    if not Path(path).exists():
        return {}
    with open(path, newline="", encoding="utf-8") as handle:
        return {row["package_id"]: row for row in csv.DictReader(handle)}


def write_csv(rows: dict[str, dict], path: Path) -> None:
    field_names = [field.name for field in fields(GpoHearing)]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    try:
        with open(temporary, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=field_names)
            writer.writeheader()
            ## sort so weekly diffs only show real changes
            for package_id in sorted(rows):
                writer.writerow(rows[package_id])
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_pending(values, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    try:
        temporary.write_text(json.dumps(values, sort_keys=True) + '\n')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def observation(data: bytes, url: str, media_type: str, *, retrieved_at=None):
    content = RawContent.from_bytes(data, media_type)
    return GpoEvidenceObservation(**content.source_dict(), url=url, retrieved_at=retrieved_at,
        acquisition='http' if retrieved_at else 'cached-replay').source_dict()


def body_bytes(value):
    return GpoEvidenceObservation.model_validate(value).body_bytes()


def write_observation(value: GpoEvidenceObservation, path: Path):
    """Atomically retain one source response beside a local extracted transcript."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    try:
        temporary.write_text(value.model_dump_json(by_alias=True, exclude_unset=True), encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read(path: Path | None):
    if path is None or not Path(path).exists():
        return {}
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        result = {}
        for line in stream:
            value = GpoEvidenceRecord.model_validate_json(line).source_dict()
            package = value['package_id']
            if package in result:
                raise ValueError(f'Duplicate GPO evidence package: {package}')
            result[package] = value
        return result


def write(values, path: Path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    # Stable gzip headers keep a replay with identical data byte-identical.
    try:
        with temporary.open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0, filename='') as stream:
            for package in sorted(values):
                stream.write((json.dumps(values[package], ensure_ascii=False, separators=(',', ':'), sort_keys=True) + '\n').encode())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
