"""Read generated CSV/YouTube tables and retain deterministic compressed or incremental state.

These are local pipeline formats, separate from publisher source parsing."""

import csv
import gzip
import json
from pathlib import Path

from congress_shared.custody import canonical_json_bytes, write_atomic_bytes
from congress_shared.youtube_cache import decode_cache

from congress_api.matching.meetings import in_inventory_scope
from congress_api.retention import house as house_retention
from congress_api.retention import senate as senate_retention
from congress_api.retention.meetings import read_meetings as read_meeting_rows
from congress_api.retention.weekly_tables import (
    WeeklyRetentionTables,
    youtube_video_to_row,
)


def read_csv(path):
    with Path(path).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def read_youtube_videos(
    directory,
    channels,
    *,
    weekly_tables: WeeklyRetentionTables | None = None,
):
    """Yield (committee code, unchanged video row) from generated channel caches.

    Cache numbers follow the channels table, including channels without a file.
    These are locally generated JSON tables, not native YouTube API responses.
    When ``weekly_tables`` is provided, also incrementally updates ``youtube_videos``.
    """
    pending_rows = []
    for i, channel in enumerate(channels):
        path = Path(directory) / f"youtube_{i:02d}.json"
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as stream:
            tables = json.load(stream)
        for _, row in decode_cache(tables).videos():
            if weekly_tables is not None:
                pending_rows.append(youtube_video_to_row(channel["systemCode"], row))
            yield channel["systemCode"], row
    if weekly_tables is not None and pending_rows:
        weekly_tables.upsert_rows("youtube_videos", pending_rows)


def write_csv(path, rows, fields):
    import io

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    write_atomic_bytes(path, buf.getvalue().encode("utf-8"), temp_mode="fixed", fsync=False)


def read_state(
    path,
    *,
    weekly_tables: WeeklyRetentionTables | None = None,
):
    state = {}
    if path is not None and Path(path).exists():
        with gzip.open(path, "rt", encoding="utf-8") as f:
            state = json.load(f)
    if weekly_tables is not None:
        if weekly_tables.latest_version("house_events") is not None:
            state.setdefault("house", {}).update(house_retention.read_events(weekly_tables))
        if weekly_tables.latest_version("senate_events") is not None:
            state.setdefault("senate", {}).update(senate_retention.read_events(weekly_tables))
    return state


def write_state(
    path,
    state,
    *,
    compresslevel=9,
    weekly_tables: WeeklyRetentionTables | None = None,
):
    if weekly_tables is not None and isinstance(state, dict):
        if isinstance(state.get("house"), dict) and state["house"]:
            house_retention.upsert_events(state["house"], weekly_tables)
        if isinstance(state.get("senate"), dict) and state["senate"]:
            senate_retention.upsert_events(state["senate"], weekly_tables)
    if path is not None:
        write_atomic_bytes(
            path,
            gzip.compress(
                canonical_json_bytes(state, ensure_ascii=False),
                compresslevel=compresslevel,
                mtime=0,
            ),
            temp_mode="fixed",
        )


def read_meetings(
    path: Path | None = None,
    *,
    weekly_tables: WeeklyRetentionTables | None = None,
):
    """Return meetings inside inventory scope.

    ``retention.meetings.read`` returns the full snapshot. This wrapper passes
    ``in_inventory_scope`` to ``retention.meetings.read_meetings``, so a bare
    call still drops meetings outside that scope.
    """
    return read_meeting_rows(path, scope=in_inventory_scope, tables=weekly_tables)
