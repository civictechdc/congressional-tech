"""Read typed retained Congress.gov meetings and write deterministic snapshots."""

import gzip
import json
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

from congress_shared.custody import write_atomic_bytes

from congress_api.matching.meetings import in_inventory_scope
from congress_api.models.congress import CommitteeMeeting
from congress_api.retention.jsonl import iter_json_lines, write as write_jsonl
from congress_api.retention.weekly_tables import (
    WeeklyRetentionTables,
    is_parquet_path,
    meeting_to_row,
)


def all_meetings(row: dict) -> bool:
    """Keep every validated meeting row."""
    return True


def read(path: Path | None = None, *, tables: WeeklyRetentionTables | None = None) -> dict[str, dict]:
    """Return the full meeting snapshot, keyed by source URL.

    Does not apply a scope. ``read_meetings`` is the list reader; its default
    scope is ``in_inventory_scope``.
    """
    return {url: row.source_dict() for url, row in read_models(path, tables=tables).items()}


def _iter_models(path: Path | None = None, *, tables: WeeklyRetentionTables | None = None):
    if tables is not None and (path is None or not Path(path).exists()):
        for row in tables.iter_rows("congress_meetings", columns=("payload_json",)):
            yield CommitteeMeeting.model_validate_json(row["payload_json"])
        return
    if path is None:
        return
    if is_parquet_path(path):
        for line in iter_json_lines(path, dataset="congress_meetings", tables=tables):
            yield CommitteeMeeting.model_validate_json(line)
        return
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            yield CommitteeMeeting.model_validate_json(line)


def read_models(path: Path | None = None, *, tables: WeeklyRetentionTables | None = None) -> dict[str, CommitteeMeeting]:
    """Return every retained meeting model, keyed by ``_url``.

    Duplicate source URLs raise. This reader does not apply a scope.
    ``read_meetings`` does. ``read`` is the dict interface. A missing file
    returns an empty dict.
    """
    if (path is None or not Path(path).exists()) and (
        tables is None or tables.latest_version("congress_meetings") is None
    ):
        return {}
    result = {}
    for row in _iter_models(path, tables=tables):
        if row.source_url is None:
            raise ValueError("Retained meeting lacks _url")
        if row.source_url in result:
            raise ValueError(f"Duplicate meeting source URL: {row.source_url}")
        result[row.source_url] = row
    return result


def iter_meetings(
    path: Path | None = None,
    *,
    scope: Callable[[dict], bool] = in_inventory_scope,
    tables: WeeklyRetentionTables | None = None,
) -> Iterator[dict]:
    """Stream validated meeting rows without holding the filtered snapshot in memory."""
    for model in _iter_models(path, tables=tables):
        row = model.source_dict()
        if scope(row):
            yield row


def read_meetings(
    path: Path | None = None,
    *,
    scope: Callable[[dict], bool] = in_inventory_scope,
    tables: WeeklyRetentionTables | None = None,
) -> list[dict]:
    """Return validated meeting rows in file order.

    ``scope`` defaults to ``in_inventory_scope`` (Scheduled or Rescheduled,
    congress 113 or later). Pass another predicate, such as
    ``scheduled_or_rescheduled`` or ``all_meetings``, for a different
    population. This reader does not require ``_url`` and does not reject
    duplicate source URLs. A missing file raises ``FileNotFoundError``.
    """
    return list(iter_meetings(path, scope=scope, tables=tables))


RELEASE_MEETING_COLUMNS = ("event_id", "congress", "title", "meeting_date", "status", "congress_gov_updated",
                           "committees", "videos")


def _dated_name(committee, day):
    """The committee's name in force on ``day``, else its current name."""
    if committee is None:
        return ""
    for entry in sorted(committee["names"] or (), key=lambda entry: entry["start"] or day, reverse=True):
        if day and (entry["start"] is None or entry["start"] <= day) and (entry["end"] is None or day <= entry["end"]):
            return entry["name"]
    return committee["name"] or ""


def read_release_meetings(
    meetings_path: Path,
    committees_path: Path,
    *,
    scope: Callable[[dict], bool] = all_meetings,
) -> Iterator[dict]:
    """Stream an archive release's ``meetings.parquet`` in the weekly file's field names.

    The release is the lake's current meeting per event, so it replaces the weekly
    Congress.gov snapshot that nothing refreshes since ct-klyz. Committee names come
    from the same release's ``committees.parquet`` (the name in force on the meeting
    date). ``date`` is the meeting's own calendar date, not a UTC timestamp. Only the
    fields ``gpo-match`` and ``congress-committees`` read are mapped. A file without
    the expected columns raises ``ValueError``.
    """
    import pyarrow.parquet as pq

    committees = {row["system_code"]: row for row in pq.read_table(
        committees_path, columns=["system_code", "name", "names"]).to_pylist()}
    with pq.ParquetFile(meetings_path) as source:
        missing = set(RELEASE_MEETING_COLUMNS) - set(source.schema_arrow.names)
        if missing:
            raise ValueError(f"{meetings_path} is not a release meetings table; lacks {sorted(missing)}")
        for batch in source.iter_batches(batch_size=4096, columns=list(RELEASE_MEETING_COLUMNS)):
            for row in batch.to_pylist():
                day = row["meeting_date"]
                meeting = {
                    "eventId": str(row["event_id"]), "congress": row["congress"], "title": row["title"],
                    "meetingStatus": row["status"], "date": day.isoformat() if day else None,
                    "updateDate": row["congress_gov_updated"].isoformat() if row["congress_gov_updated"] else None,
                    "committees": [{"systemCode": c["system_code"], "name": _dated_name(committees.get(c["system_code"]), day)}
                                   for c in row["committees"] or ()],
                    "videos": [{"name": v["name"], "url": v["url"]} for v in row["videos"] or ()],
                }
                if scope(meeting):
                    yield meeting


def read_by_urls(
    urls: Sequence[str],
    *,
    tables: WeeklyRetentionTables,
) -> dict[str, dict]:
    """Read only matching meeting URLs from the incremental ``congress_meetings`` table."""
    arrow_table = tables.read_keys("congress_meetings", urls, key="source_url")
    result: dict[str, dict] = {}
    for row in arrow_table.to_pylist():
        model = CommitteeMeeting.model_validate_json(row["payload_json"])
        result[row["source_url"]] = model.source_dict()
    return result


def upsert_meetings(records: dict[str, dict], tables: WeeklyRetentionTables) -> dict | None:
    """Incrementally admit or update ``congress_meetings`` rows by ``source_url``."""
    return tables.upsert_rows(
        "congress_meetings",
        (meeting_to_row(url, records[url]) for url in sorted(records)),
    )


def write(
    records: dict[str, dict],
    path: Path,
    *,
    tables: WeeklyRetentionTables | None = None,
) -> None:
    """Write the full meeting snapshot. Rows are validated on read, not here."""
    write_jsonl(records, path, dataset="congress_meetings", tables=tables)


def write_pending(path, urls, responses=None):
    payload = {"urls": sorted(set(urls))}
    if responses:
        payload["responses"] = responses
    write_atomic_bytes(
        path,
        (json.dumps(payload, indent=2) + "\n").encode("utf-8"),
        temp_mode="fixed",
    )
