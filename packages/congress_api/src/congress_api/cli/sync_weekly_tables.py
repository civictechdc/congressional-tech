"""Sync retained weekly pipeline files into incremental docspec-rs WeeklyRetentionTables."""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
from pathlib import Path
import sys
from typing import Any

from congress_shared.youtube_cache import decode_cache

from congress_api.retention import captions as captions_retention
from congress_api.retention import gpo as gpo_retention
from congress_api.retention import house as house_retention
from congress_api.retention import rejected_pages as rejected_pages_retention
from congress_api.retention import senate as senate_retention
from congress_api.retention.weekly_tables import (
    WeeklyRetentionTables,
    gpo_hearing_to_row,
    gpo_observation_to_row,
    meeting_to_row,
    youtube_video_to_row,
)


def _iter_meetings_rows(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            url = record.get("_url") or record.get("url") or str(record.get("eventId") or "")
            if url:
                yield meeting_to_row(url, record)


def _iter_gpo_hearing_rows(path: Path):
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            pkg = row.get("package_id")
            if pkg:
                yield gpo_hearing_to_row(pkg, row)


def _iter_gpo_observation_rows(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            pkg = record.get("package_id")
            if pkg:
                yield gpo_observation_to_row(pkg, record)


def _iter_youtube_rows(youtube_dir: Path, channels_csv: Path | None = None):
    channels_by_idx: dict[int, str] = {}
    if channels_csv and channels_csv.is_file():
        with channels_csv.open("r", encoding="utf-8", newline="") as handle:
            for idx, row in enumerate(csv.DictReader(handle)):
                if row.get("systemCode"):
                    channels_by_idx[idx] = row["systemCode"]
    for path in sorted(youtube_dir.glob("youtube_*.json")):
        stem_digits = path.stem.removeprefix("youtube_")
        idx = int(stem_digits) if stem_digits.isdigit() else -1
        default_code = channels_by_idx.get(idx, path.stem)
        with path.open("r", encoding="utf-8") as stream:
            tables = json.load(stream)
        for _, row in decode_cache(tables).videos():
            if row.get("videoId"):
                yield youtube_video_to_row(default_code, row)


def sync_weekly_retention_tables(
    workspace: Path | str,
    *,
    pipeline_data: Path | str,
    data_dir: Path | str,
    channels_csv: Path | str | None = None,
    chunk_size: int = 10_000,
) -> dict[str, Any]:
    """Sync available weekly retention files into ``WeeklyRetentionTables(workspace)`` in bounded chunks."""
    p_dir = Path(pipeline_data)
    d_dir = Path(data_dir)
    c_csv = Path(channels_csv) if channels_csv else None
    synced: dict[str, str | None] = {}

    with WeeklyRetentionTables(workspace) as wt:
        house_path = p_dir / "meeting-inventory" / "house.json.gz"
        if house_path.is_file():
            with gzip.open(house_path, "rt", encoding="utf-8") as fh:
                house_state = json.load(fh)
            if isinstance(house_state, dict) and house_state:
                pin = house_retention.upsert_events(house_state, wt)
                synced["house_events"] = pin["id"] if pin else None
            del house_state

        senate_path = p_dir / "meeting-inventory" / "senate.json.gz"
        if senate_path.is_file():
            with gzip.open(senate_path, "rt", encoding="utf-8") as fh:
                senate_state = json.load(fh)
            if isinstance(senate_state, dict) and senate_state:
                pin = senate_retention.upsert_events(senate_state, wt)
                synced["senate_events"] = pin["id"] if pin else None
            del senate_state

        inventory_path = p_dir / "meeting-inventory" / "inventory.json.gz"
        if inventory_path.is_file():
            with gzip.open(inventory_path, "rt", encoding="utf-8") as fh:
                inventory_state = json.load(fh)
            if isinstance(inventory_state, dict) and inventory_state:
                pin = captions_retention.upsert_captions(inventory_state, wt)
                synced["captions"] = pin["id"] if pin else None
            del inventory_state

        rejected_path = p_dir / "meeting-inventory" / "rejected-pages.json.gz"
        if rejected_path.is_file():
            with gzip.open(rejected_path, "rt", encoding="utf-8") as fh:
                rejected_state = json.load(fh)
            if isinstance(rejected_state, dict) and rejected_state:
                pin = rejected_pages_retention.upsert_rejected(rejected_state, wt)
                synced["rejected_pages"] = pin["id"] if pin else None
            del rejected_state

        meetings_path = p_dir / "congress_meetings.jsonl.gz"
        if meetings_path.is_file():
            pin = wt.upsert_rows(
                "congress_meetings",
                _iter_meetings_rows(meetings_path),
                chunk_size=chunk_size,
            )
            synced["congress_meetings"] = pin["id"] if pin else None

        gpo_csv_path = d_dir / "gpo_hearings.csv"
        if gpo_csv_path.is_file():
            pin = wt.upsert_rows(
                "gpo_hearings",
                _iter_gpo_hearing_rows(gpo_csv_path),
                chunk_size=chunk_size,
            )
            synced["gpo_hearings"] = pin["id"] if pin else None

        gpo_evidence_path = p_dir / "gpo-evidence.jsonl.gz"
        if gpo_evidence_path.is_file():
            pin = wt.upsert_rows(
                "gpo_observations",
                _iter_gpo_observation_rows(gpo_evidence_path),
                chunk_size=chunk_size,
            )
            synced["gpo_observations"] = pin["id"] if pin else None

        youtube_dir = p_dir / "youtube"
        if youtube_dir.is_dir():
            pin = wt.upsert_rows(
                "youtube_videos",
                _iter_youtube_rows(youtube_dir, c_csv),
                chunk_size=chunk_size,
            )
            synced["youtube_videos"] = pin["id"] if pin else None

    return {"workspace": str(Path(workspace).resolve()), "synced": synced}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        type=Path,
        default=os.environ.get("DOCSPEC_RETENTION_WORKSPACE"),
        required=not bool(os.environ.get("DOCSPEC_RETENTION_WORKSPACE")),
        help="Path to the docspec-rs WeeklyRetentionTables workspace",
    )
    parser.add_argument(
        "--pipeline-data",
        type=Path,
        default=Path("pipeline-data"),
        help="Path to the checked-out pipeline-data directory",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("apps/committee_youtube/data"),
        help="Path to the committee_youtube data directory",
    )
    parser.add_argument(
        "--channels-csv",
        type=Path,
        default=Path("packages/congress_shared/src/congress_shared/youtube/youtube-accounts.csv"),
        help="Optional YouTube accounts CSV for channel systemCode lookup",
    )
    parser.add_argument("--chunk-size", type=int, default=10_000)
    args = parser.parse_args(argv)
    report = sync_weekly_retention_tables(
        args.workspace,
        pipeline_data=args.pipeline_data,
        data_dir=args.data_dir,
        channels_csv=args.channels_csv,
        chunk_size=args.chunk_size,
    )
    sys.stdout.write(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
