"""Retain Congress-scoped committee snapshots.

These rows are committee lists and details, not committee meetings.
"""

from __future__ import annotations

import gzip
from pathlib import Path

from congress_api.models.congress import CommitteeSnapshot
from congress_api.retention.jsonl import write as write_jsonl


def read(path: Path) -> list[dict]:
    """Return every retained committee snapshot.

    Validates ``CommitteeSnapshot``. This is not ``retention.meetings.read``
    and does not apply inventory scope.
    """
    if not Path(path).exists():
        return []
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [CommitteeSnapshot.model_validate_json(line).source_dict() for line in stream if line.strip()]


def write(records: dict[str, dict], path: Path) -> None:
    """Write committee snapshots keyed by ``congress|systemCode``.

    Keys are not meeting source URLs. Bytes go through the shared JSONL writer.
    """
    write_jsonl(records, path)
