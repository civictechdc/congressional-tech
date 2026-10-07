"""Read generated CSV/YouTube tables and retain deterministic compressed state.

These are local pipeline formats, separate from publisher source parsing."""

import csv
import gzip
import json
from pathlib import Path

from congress_api.matching.meetings import in_inventory_scope
from congress_api.retention.meetings import read_meetings as read_meeting_rows


def read_csv(path):
    with Path(path).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def read_youtube_videos(directory, channels):
    """Yield (committee code, unchanged video row) from generated channel caches.

    Cache numbers follow the channels table, including channels without a file.
    These are locally generated JSON tables, not native YouTube API responses.
    """
    for i, channel in enumerate(channels):
        path = Path(directory) / f"youtube_{i:02d}.json"
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as stream:
            tables = json.load(stream)
        for name, rows in tables.items():
            if name.startswith("youtube_videos_"):
                for row in rows.values():
                    yield channel["systemCode"], row


def write_csv(path, rows, fields):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_state(path):
    if not Path(path).exists():
        return {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def write_state(path, state, *, compresslevel=9):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_bytes(gzip.compress(json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(), compresslevel=compresslevel, mtime=0))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_meetings(path):
    """Return meetings inside inventory scope.

    ``retention.meetings.read`` returns the full snapshot. This wrapper passes
    ``in_inventory_scope`` to ``retention.meetings.read_meetings``, so a bare
    call still drops meetings outside that scope.
    """
    return read_meeting_rows(path, scope=in_inventory_scope)
