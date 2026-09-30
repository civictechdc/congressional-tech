"""Read typed retained Congress.gov meetings and write deterministic snapshots."""

import gzip
import json
from pathlib import Path

from congress_api.models.congress import CommitteeMeeting


def read(path: Path) -> dict[str, dict]:
    return {url: row.source_dict() for url, row in read_models(path).items()}


def read_models(path: Path) -> dict[str, CommitteeMeeting]:
    """Read native meeting models; ``read`` retains the existing dict interface."""
    if not Path(path).exists():
        return {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        rows = (CommitteeMeeting.model_validate_json(line) for line in f)
        result = {}
        for row in rows:
            if row.source_url is None:
                raise ValueError("Retained meeting lacks _url")
            result[row.source_url] = row
        return result


def write(records: dict[str, dict], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    ## sorted, and mtime=0 so identical content gives identical bytes
    try:
        with open(temporary, "wb") as raw, gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as f:
            for url in sorted(records):
                f.write((json.dumps(records[url], sort_keys=True) + "\n").encode("utf-8"))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


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
