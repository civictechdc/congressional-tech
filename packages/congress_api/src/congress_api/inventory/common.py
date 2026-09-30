"""Small file and meeting helpers for the source readers and final inventory.

State is parsed JSON with retained source bodies, compressed deterministically. A new
Congress.gov update is due immediately. Otherwise check recent meetings weekly,
meetings up to two years old every 28 days, and older meetings annually. Among
6,155 cached House XML records the 95th-percentile update lag was 330 days;
62 changed after two years and 19 were newer than Congress.gov's updateDate.
The seeded age groups imply 364 House and 404 Senate checks/week; source-reader
budgets of 400 and 450 cover that mean. These are due dates, with oldest checks
first when a synchronized backfill creates a larger queue.
"""
import csv
import datetime as dt
import gzip
import html
import json
import re
from pathlib import Path

from congress_api.models.congress import CommitteeMeeting

NOT_HELD = re.compile(r"^\s*(postponed|cancel+ed|rescheduled|test)\b", re.I)
TRANSCRIPT = re.compile(r"transcript", re.I)


def text(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value or ""))).strip()


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
    with temporary.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def read_state(path):
    if not Path(path).exists():
        return {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def write_state(path, state):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(gzip.compress(json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(), mtime=0))
    temporary.replace(path)


def in_inventory_scope(row):
    """The retained inventory and print matcher share this collection scope."""
    return row.get("meetingStatus") in ("Scheduled", "Rescheduled") and int(row.get("congress", 0)) >= 113


def read_meetings(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        records = (CommitteeMeeting.model_validate_json(line) for line in f)
        return [row for m in records if in_inventory_scope(row := m.source_dict())]


def due(previous, day, version, today):
    if not previous or previous.get("version") != version:
        return True
    ## A late XML revision puts even an old House meeting back on the faster schedule.
    day = max(day[:10], previous.get("xml_update", "")[:10])
    age = (today - dt.date.fromisoformat(day)).days
    interval = 7 if age <= 30 else 28 if age <= 730 else 365
    return (today - dt.date.fromisoformat(previous["checked"])).days >= interval


def source_args(parser):
    parser.add_argument("--meetings", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed-cache", type=lambda s: Path(s).expanduser(), help="read-only research cache, for one-time import")
    parser.add_argument("--offline", action="store_true", help="require saved results; make no requests")
    parser.add_argument("--as-of", type=dt.date.fromisoformat, default=dt.datetime.now(dt.UTC).date())


def nonnegative(value):
    number = int(value)
    if number < 0:
        raise ValueError("must be nonnegative")
    return number
