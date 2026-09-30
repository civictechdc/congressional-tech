"""Read typed retained Congress.gov meetings and write deterministic snapshots."""

import gzip
import json
from collections.abc import Callable
from pathlib import Path

from congress_api.matching.meetings import in_inventory_scope
from congress_api.models.congress import CommitteeMeeting
from congress_api.retention.jsonl import write as write_jsonl


def all_meetings(row: dict) -> bool:
    """Keep every validated meeting row."""
    return True


def read(path: Path) -> dict[str, dict]:
    """Return the full meeting snapshot, keyed by source URL.

    Does not apply a scope. ``read_meetings`` is the list reader; its default
    scope is ``in_inventory_scope``.
    """
    return {url: row.source_dict() for url, row in read_models(path).items()}


def _iter_models(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            yield CommitteeMeeting.model_validate_json(line)


def read_models(path: Path) -> dict[str, CommitteeMeeting]:
    """Return every retained meeting model, keyed by ``_url``.

    Duplicate source URLs raise. This reader does not apply a scope.
    ``read_meetings`` does. ``read`` is the dict interface. A missing file
    returns an empty dict.
    """
    if not Path(path).exists():
        return {}
    result = {}
    for row in _iter_models(path):
        if row.source_url is None:
            raise ValueError("Retained meeting lacks _url")
        if row.source_url in result:
            raise ValueError(f"Duplicate meeting source URL: {row.source_url}")
        result[row.source_url] = row
    return result


def read_meetings(path: Path, *, scope: Callable[[dict], bool] = in_inventory_scope) -> list[dict]:
    """Return validated meeting rows in file order.

    ``scope`` defaults to ``in_inventory_scope`` (Scheduled or Rescheduled,
    congress 113 or later). Pass another predicate, such as
    ``scheduled_or_rescheduled`` or ``all_meetings``, for a different
    population. This reader does not require ``_url`` and does not reject
    duplicate source URLs. A missing file raises ``FileNotFoundError``.
    """
    selected = []
    for model in _iter_models(path):
        row = model.source_dict()
        if scope(row):
            selected.append(row)
    return selected


def write(records: dict[str, dict], path: Path) -> None:
    """Write the full meeting snapshot. Rows are validated on read, not here."""
    write_jsonl(records, path)


def write_pending(path, urls, responses=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        payload = {"urls": sorted(set(urls))}
        if responses:
            payload["responses"] = responses
        temporary.write_text(json.dumps(payload, indent=2) + "\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
