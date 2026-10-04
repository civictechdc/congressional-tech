"""Local archive filename/document index command."""

import argparse
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.cli.raw_progress import ProgressLog
from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.raw_catalog import rebuild_catalog
from congress_api.retention.raw_archive import CAPTURE_SCHEMA
from congress_api.retention.document_index import (
    build,
    refresh_filename_metadata,
)


def main():
    parser = argparse.ArgumentParser(
        description="Build or refresh raw-document filename tables"
    )
    parser.add_argument("archive", type=Path)
    parser.add_argument(
        "--inventory-dir",
        type=Path,
        help="Directory containing filenames.parquet and urls.parquet",
    )
    parser.add_argument('--repair', action='store_true', help='Reconstruct source inventory from receipts')
    parser.add_argument('--inspect-bodies', action='store_true', help='Also inspect retained document contents')
    # Old invocations remain valid, but all refresh modes use the same updater.
    for flag in ('--documents-only', '--metadata-only', '--source-metadata-only'):
        parser.add_argument(flag, action='store_true', help=argparse.SUPPRESS)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    with ProgressLog(args.archive / 'status/document-index.json'):
        if args.inventory_dir is not None:
            result = build(args.archive, args.inventory_dir, workers=args.workers, inspect_bodies=args.inspect_bodies)
        elif (args.archive / 'indexes/captures.parquet').exists():
            captures = pq.read_table(args.archive / 'indexes/captures.parquet')
            # Older local inventories omitted empty capture columns; keep the
            # remote writer strict and adapt this legacy input at the CLI edge.
            captures = pa.Table.from_arrays([
                captures[field.name].cast(field.type) if field.name in captures.column_names
                else pa.nulls(len(captures), field.type) for field in CAPTURE_SCHEMA], schema=CAPTURE_SCHEMA)
            result = rebuild_catalog(LocalStore(args.archive), captures,
                                     workers=args.workers, repair=args.repair,
                                     inspect_bodies=args.inspect_bodies)
        elif ((args.archive / 'indexes/catalog.json').exists()
              or (args.archive / 'indexes/document-filenames.parquet').exists()):
            # A standalone filename table can still be reinterpreted without an archive.
            result = refresh_filename_metadata(args.archive, workers=args.workers, inspect_bodies=args.inspect_bodies)
        else:
            parser.error('An archive capture index or existing filename table is required')
        print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
