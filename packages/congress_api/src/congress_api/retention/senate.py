"""Read captured Senate HTML from a local cache and retain incremental Senate events."""

from collections.abc import Sequence
import datetime as dt
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
    text = path.read_bytes().decode("utf-8", "replace") if path.exists() else ""
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
