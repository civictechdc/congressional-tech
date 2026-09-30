"""Read typed retained Congress.gov meetings and write deterministic snapshots."""

import gzip
import json
from pathlib import Path

from congress_api.models.congress import CommitteeMeeting
from congress_api.retention.jsonl import write as write_jsonl


def read(path: Path) -> dict[str, dict]:
    """Return the full meeting snapshot, keyed by source URL.

    Does not apply inventory scope. ``retention.tables.read_meetings`` is the
    reader that keeps only in-scope meetings.
    """
    return {url: row.source_dict() for url, row in read_models(path).items()}


def read_models(path: Path) -> dict[str, CommitteeMeeting]:
    """Return every retained meeting model, keyed by ``_url``.

    Duplicate source URLs raise. This reader does not apply inventory scope;
    ``retention.tables.read_meetings`` does. ``read`` is the dict interface.
    """
    if not Path(path).exists():
        return {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        rows = (CommitteeMeeting.model_validate_json(line) for line in f)
        result = {}
        for row in rows:
            if row.source_url is None:
                raise ValueError("Retained meeting lacks _url")
            if row.source_url in result:
                raise ValueError(f"Duplicate meeting source URL: {row.source_url}")
            result[row.source_url] = row
        return result


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
