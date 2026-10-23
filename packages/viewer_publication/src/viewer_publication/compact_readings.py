"""Compaction utility for reading shards (readings/*.parquet).

Compacts hundreds of small fragmented Parquet files into 1-2 sorted,
efficient Parquet files with large row groups (>= 16,384 rows) and
ZSTD compression.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Iterable, Sequence

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

DEFAULT_READING_ROW_GROUP_SIZE = 32768


def deduplicate_reading_table(
    table: pa.Table,
    *,
    key_columns: Sequence[str] | None = None,
) -> pa.Table:
    """Deduplicate reading records by primary key (latest record wins)."""
    if len(table) == 0:
        return table

    names = table.schema.names
    if key_columns is None:
        if "reading_id" in names:
            key_columns = ["reading_id"]
        elif "body_key" in names and "parser_fingerprint" in names:
            key_columns = ["body_key", "parser_fingerprint"]
        else:
            return table

    # Ensure all key columns exist in table
    valid_keys = [c for c in key_columns if c in names]
    if not valid_keys:
        return table

    # Deduplicate in python keeping latest
    pylist = table.to_pylist()
    deduped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in pylist:
        key = tuple(row.get(col) for col in valid_keys)
        deduped[key] = row

    return pa.Table.from_pylist(list(deduped.values()), schema=table.schema)


def sort_reading_table(
    table: pa.Table,
    *,
    sort_columns: Sequence[str] | None = None,
) -> pa.Table:
    """Sort reading table by primary key or specified sort columns."""
    if len(table) == 0:
        return table

    names = table.schema.names
    if sort_columns is None:
        if "body_key" in names and "parser_fingerprint" in names:
            sort_columns = ["body_key", "parser_fingerprint"]
        elif "retained_page_id" in names and "reading_id" in names:
            sort_columns = ["retained_page_id", "reading_id"]
        elif "reading_id" in names:
            sort_columns = ["reading_id"]
        else:
            sort_columns = [names[0]]

    valid_cols = [c for c in sort_columns if c in names]
    if not valid_cols:
        return table

    sort_keys = [(col, "ascending") for col in valid_cols]
    try:
        indices = pc.sort_indices(table, sort_keys=sort_keys)
        return table.take(indices)
    except Exception:
        # Fallback sorting on single column
        indices = pc.sort_indices(table[valid_cols[0]])
        return table.take(indices)


def compact_readings(
    source: Path | str | Sequence[Path | str] | Sequence[pa.Table],
    destination: Path | str,
    *,
    max_files: int = 2,
    row_group_size: int = DEFAULT_READING_ROW_GROUP_SIZE,
    compression: str = "zstd",
    compression_level: int = 3,
    sort_columns: Sequence[str] | None = None,
    deduplicate: bool = True,
    fallback_schema: pa.Schema | None = None,
) -> dict[str, Any]:
    """Compact fragmented reading files into 1-2 sorted Parquet files.

    Args:
        source: Directory containing .parquet files, sequence of file paths, or tables.
        destination: Output directory or output .parquet file path.
        max_files: Maximum number of output files (1 or 2).
        row_group_size: Row group size (minimum 16,384 rows).
        compression: Parquet codec ('zstd').
        compression_level: ZSTD compression level.
        sort_columns: Columns to sort by.
        deduplicate: Whether to deduplicate records by primary key.
        fallback_schema: Schema to use if all source files are empty.

    Returns:
        Summary dict containing written file paths, total rows, and stats.
    """
    row_group_size = max(16384, int(row_group_size))
    tables: list[pa.Table] = []

    if isinstance(source, (str, Path)):
        source_path = Path(source)
        if source_path.is_dir():
            file_paths = sorted(source_path.glob("*.parquet"))
        elif source_path.is_file():
            file_paths = [source_path]
        else:
            file_paths = []
        for fp in file_paths:
            try:
                tables.append(pq.read_table(fp))
            except Exception:
                pass
    elif isinstance(source, Sequence):
        for item in source:
            if isinstance(item, pa.Table):
                tables.append(item)
            elif isinstance(item, (str, Path)):
                p = Path(item)
                if p.is_file():
                    tables.append(pq.read_table(p))

    # Unify tables
    if not tables:
        if fallback_schema is None:
            fallback_schema = pa.schema([
                ("retained_page_id", pa.string()),
                ("reading_id", pa.string()),
                ("raw_leaf", pa.string()),
                ("normalized_leaf", pa.string()),
                ("canonical_leaf", pa.string()),
                ("congress", pa.int32()),
                ("document_family", pa.string()),
                ("document_kind", pa.string()),
                ("format", pa.string()),
            ])
        combined = pa.Table.from_pylist([], schema=fallback_schema)
    else:
        combined = pa.concat_tables(tables, promote_options="default")

    if deduplicate and len(combined) > 0:
        combined = deduplicate_reading_table(combined)

    if len(combined) > 0:
        combined = sort_reading_table(combined, sort_columns=sort_columns)

    dest_path = Path(destination)
    output_files: list[Path] = []

    if dest_path.suffix == ".parquet":
        # Destination is a single file path
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(
            combined,
            dest_path,
            compression=compression,
            compression_level=compression_level,
            row_group_size=row_group_size,
            write_page_index=True,
            write_statistics=True,
        )
        output_files.append(dest_path)
    else:
        dest_path.mkdir(parents=True, exist_ok=True)
        # Determine number of output files (1 or 2)
        total_rows = len(combined)
        num_files = 1 if (total_rows <= row_group_size * 2 or max_files <= 1) else min(max_files, 2)

        if num_files == 1:
            out_file = dest_path / "readings-00000.parquet"
            pq.write_table(
                combined,
                out_file,
                compression=compression,
                compression_level=compression_level,
                row_group_size=row_group_size,
                write_page_index=True,
                write_statistics=True,
            )
            output_files.append(out_file)
        else:
            split_idx = (total_rows + 1) // 2
            part0 = combined.slice(0, split_idx)
            part1 = combined.slice(split_idx)
            out0 = dest_path / "readings-00000.parquet"
            out1 = dest_path / "readings-00001.parquet"
            pq.write_table(
                part0,
                out0,
                compression=compression,
                compression_level=compression_level,
                row_group_size=row_group_size,
                write_page_index=True,
                write_statistics=True,
            )
            pq.write_table(
                part1,
                out1,
                compression=compression,
                compression_level=compression_level,
                row_group_size=row_group_size,
                write_page_index=True,
                write_statistics=True,
            )
            output_files.extend([out0, out1])

    return {
        "total_rows": len(combined),
        "num_files": len(output_files),
        "files": [str(p) for p in output_files],
        "schema": combined.schema,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Input directory of readings parquet shards")
    parser.add_argument("destination", type=Path, help="Destination directory or parquet file")
    parser.add_argument("--max-files", type=int, default=2, help="Maximum number of output files (1 or 2)")
    parser.add_argument("--row-group-size", type=int, default=DEFAULT_READING_ROW_GROUP_SIZE)
    args = parser.parse_args()

    result = compact_readings(
        args.source,
        args.destination,
        max_files=args.max_files,
        row_group_size=args.row_group_size,
    )
    print(f"Compacted {result['total_rows']} reading rows into {result['num_files']} file(s):")
    for f in result["files"]:
        print(f"  {f}")


if __name__ == "__main__":
    main()
