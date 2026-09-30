"""Sorted gzip JSONL snapshots with atomic replace.

Meeting and committee retention share this writer. Each caller owns its row
type; this module does not validate them.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path


def write(records: dict, path: Path) -> None:
    """Write record values as gzip JSONL, ordered by sorted dict key.

    ``mtime=0`` keeps identical content byte-identical. A failed replace leaves
    the previous file in place and removes the temporary.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(temporary, "wb") as raw, gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as stream:
            for key in sorted(records):
                stream.write((json.dumps(records[key], sort_keys=True) + "\n").encode("utf-8"))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
