"""Sorted gzip JSONL snapshots with atomic replace.

Meeting and committee retention share this writer. Each caller owns its row
type; this module does not validate them.
"""

from __future__ import annotations

import gzip
import io
import json
from pathlib import Path

from congress_shared.custody import write_atomic_bytes


def write(records: dict, path: Path) -> None:
    """Write record values as gzip JSONL, ordered by sorted dict key.

    ``mtime=0`` keeps identical content byte-identical. A failed replace leaves
    the previous file in place and removes the temporary.
    """
    buf = io.BytesIO()
    with gzip.GzipFile(filename="", fileobj=buf, mode="wb", mtime=0) as stream:
        for key in sorted(records):
            stream.write((json.dumps(records[key], sort_keys=True) + "\n").encode("utf-8"))
    write_atomic_bytes(path, buf.getvalue(), temp_mode="fixed", fsync=False)
