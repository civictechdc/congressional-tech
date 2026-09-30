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

CLOSED = re.compile(r"closed|briefing|deposition|executive session", re.I)
NOT_HELD = re.compile(r"^\s*(postponed|cancel+ed|rescheduled|test)\b", re.I)
TRANSCRIPT = re.compile(r"transcript", re.I)


def meeting_access(row):
    """Keep explicit native access, otherwise use explicit title phrases only."""
    native = str(row.get('type') or '').lower()
    reported = {value for value in ('open', 'closed') if re.search(r'\b' + value + r'\b', native)}
    if reported:
        return ('partly_closed' if len(reported) == 2 else reported.pop()), '/type'
    title = ' '.join(str(row.get('title') or '').lower().split())
    # Possibility is not a declaration that a closed portion will occur.
    title = re.sub(r'\b(?:possibility of|possibly|may (?:be|go into|hold))\s+(?:an?\s+)?(?:closed|open)\s+(?:session|hearing|meeting)\b', '', title)
    event = r'(?:hearings?|briefings?|(?:business\s+)?meetings?|mark[ -]?up(?:\s+sessions?)?|sessions?|panels?|roundtables?)'
    if re.search(r'\b(?:open\s*(?:and|&|/)\s*closed|closed\s*(?:and|&|/)\s*open)(?=\s*(?:[\])]|' + event + r'\b))', title):
        return 'partly_closed', '/title'
    found, primary = set(), set()
    subsequent = re.search(r'\b(?:followed|preceded)\s+by\b', title)
    for access in ('open', 'closed'):
        marker = r'[\[(]\s*' + access + r'\s*(?:[\])]|(?:session|hearing|briefing)\b|in a closed space\b|-\s*possibility of closing\b)'
        phrase = r'\b' + access + r'\s+(?:joint\s+)?' + event + r'\b'
        declaration = r'\b' + event + r'\s+(?:is\s+|will be\s+)?' + access + r'\b|^\W*' + access + r'\s+to (?:the )?public\b'
        matches = [match for pattern in (marker, phrase, declaration) for match in re.finditer(pattern, title)]
        if matches:
            found.add(access)
            if subsequent is None or any(match.start() < subsequent.start() for match in matches):
                primary.add(access)
    if len(found) == 2:
        return 'partly_closed', '/title'
    # A later closed session alone does not establish access to the main event.
    if primary:
        return primary.pop(), '/title'
    return 'unknown', None



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


def read_meetings(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        records = (CommitteeMeeting.model_validate_json(line) for line in f)
        return [m.source_dict() for m in records if m.meetingStatus in ("Scheduled", "Rescheduled") and m.congress >= 113]


def kind(m):
    """Senate/joint records are typed Meeting; their title distinguishes hearings."""
    title = (m.get("title") or "").strip().lower()
    if m.get("type") == "Markup" or re.match(r"(closed )?(business meeting to )?mark ?up", title):
        return "markup"
    if m.get("type") == "Hearing" or (m.get("chamber") != "House" and re.match(r"(an? )?(oversight |closed |open |joint )*hearings?\b", title)):
        return "hearing"
    return "business"


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
