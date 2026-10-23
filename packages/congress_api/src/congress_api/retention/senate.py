"""Read captured Senate HTML from a local cache and retain incremental Senate events."""

from collections.abc import Sequence
import datetime as dt
from hashlib import sha256
import json
import re
from pathlib import Path

from congress_api.retention.weekly_tables import WeeklyRetentionTables, senate_event_to_row


def cached_html_path(cache, url):
    """Retained hearing page: ``{cache}/senate_pages/{slug}.html``."""
    return Path(cache) / "senate_pages" / (re.sub(r"\W+", "_", url)[-180:] + ".html")


def seed_fetch(
    cache,
    url,
    *,
    record_id: str | None = None,
    tables: WeeklyRetentionTables | None = None,
):
    path = cached_html_path(cache, url)
    if not path.exists():
        return ""
    data = path.read_bytes()
    if not data:
        return ""

    is_pdf = data[:5] == b"%PDF-"
    is_binary = False
    text = ""
    if is_pdf:
        is_binary = True
    else:
        decoded = data.decode("utf-8", "replace")
        fffd_count = decoded.count("\ufffd")
        if fffd_count > 0 and (fffd_count / max(1, len(decoded)) > 0.05):
            is_binary = True
        else:
            text = decoded

    if is_binary:
        digest = sha256(data).hexdigest()
        rel_key = Path("bodies") / "sha256" / digest[:2] / f"{digest}.pdf"
        dest = Path(cache) / rel_key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        if tables is not None and hasattr(tables, "workspace") and tables.workspace:
            tables_dest = Path(tables.workspace) / rel_key
            if tables_dest != dest:
                tables_dest.parent.mkdir(parents=True, exist_ok=True)
                tables_dest.write_bytes(data)
        return ""

    if tables is not None and text:
        rid = record_id or re.sub(r"\W+", "_", url)[-180:]
        observed = dt.datetime.fromtimestamp(path.stat().st_mtime, dt.UTC).isoformat()
        upsert_events(
            {rid: {"url": url, "observed_at": observed, "html": text}},
            tables,
        )
    return text


def upsert_events(events: dict[str, dict], tables: WeeklyRetentionTables):
    """Incrementally admit or update ``senate_events`` rows by ``record_id``."""
    return tables.upsert_rows(
        "senate_events",
        (senate_event_to_row(record_id, events[record_id]) for record_id in sorted(events)),
    )


def read_events(
    tables: WeeklyRetentionTables,
    *,
    record_ids: Sequence[str] | None = None,
) -> dict[str, dict]:
    """Read Senate events from the incremental ``senate_events`` table."""
    if record_ids is not None:
        arrow_table = tables.read_keys("senate_events", record_ids, key="record_id")
        return {
            row["record_id"]: json.loads(row["payload_json"])
            for row in arrow_table.to_pylist()
        }
    return {
        row["record_id"]: json.loads(row["payload_json"])
        for row in tables.iter_rows("senate_events", columns=("record_id", "payload_json"))
    }
