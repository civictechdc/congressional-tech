"""Compaction utility for Viewer review rows (review/rows/part-*.parquet).

Drops:
- record_json (redundant JSON blob duplicating typed columns)
- canonical_url (100% identical to url)
- 100% NULL columns (committee, chamber, congress, bill_id, member_bioguide, etc.)

Preserves:
- All populated typed columns (id/row_id, url, sha256, format, http_status, fetched_at, etc.)
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

FORBIDDEN_REVIEW_COLUMNS = frozenset({"record_json", "canonical_url"})
DEFAULT_REVIEW_ROW_GROUP_SIZE = 32768


def prune_review_table(table: pa.Table) -> pa.Table:
    """Drop forbidden and 100% NULL columns from review rows while keeping populated typed columns."""
    if len(table) == 0:
        kept_names = [c for c in table.schema.names if c not in FORBIDDEN_REVIEW_COLUMNS]
        return table.select(kept_names)

    kept_columns = []
    num_rows = len(table)

    for field in table.schema:
        name = field.name
        if name in FORBIDDEN_REVIEW_COLUMNS:
            continue
        col = table[name]
        # Check if 100% NULL
        if col.null_count == num_rows:
            continue
        kept_columns.append(name)

    return table.select(kept_columns)


def compact_review_rows(
    source: Path | str | pa.Table,
    destination: Path | str | None = None,
    *,
    row_group_size: int = DEFAULT_REVIEW_ROW_GROUP_SIZE,
    compression: str = "zstd",
    compression_level: int = 3,
) -> pa.Table:
    """Compact review rows by dropping redundant and dead columns.

    Args:
        source: Input file path or pyarrow Table.
        destination: Optional output parquet file path.
        row_group_size: Row group size (minimum 16,384).
        compression: Parquet codec ('zstd').
        compression_level: ZSTD level (3).

    Returns:
        Compacted pyarrow Table.
    """
    row_group_size = max(16384, int(row_group_size))

    if isinstance(source, (str, Path)):
        source_path = Path(source)
        if source_path.is_file():
            table = pq.read_table(source_path)
        elif source_path.is_dir():
            files = sorted(source_path.glob("*.parquet"))
            table = pa.concat_tables([pq.read_table(f) for f in files]) if files else pa.Table.from_pylist([])
        else:
            raise FileNotFoundError(f"Review rows source not found: {source}")
    else:
        table = source

    compacted = prune_review_table(table)

    if destination is not None:
        dest_path = Path(destination)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(
            compacted,
            dest_path,
            compression=compression,
            compression_level=compression_level,
            row_group_size=row_group_size,
            write_page_index=True,
            write_statistics=True,
        )

    return compacted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Input review rows parquet file or directory")
    parser.add_argument("destination", type=Path, help="Output compacted review rows parquet file")
    parser.add_argument("--row-group-size", type=int, default=DEFAULT_REVIEW_ROW_GROUP_SIZE)
    args = parser.parse_args()

    out_table = compact_review_rows(
        args.source,
        args.destination,
        row_group_size=args.row_group_size,
    )
    print(f"Compacted {len(out_table)} review rows into {args.destination} ({len(out_table.schema.names)} columns)")


if __name__ == "__main__":
    main()
