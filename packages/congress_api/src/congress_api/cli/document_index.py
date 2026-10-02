"""Local archive filename/document index command."""

import argparse
import json
from pathlib import Path

from congress_api.retention.document_index import (
    build,
    refresh_source_metadata,
    reindex_documents,
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
    refresh = parser.add_mutually_exclusive_group()
    refresh.add_argument(
        "--documents-only",
        action="store_true",
        help="Refresh both document indexes from existing filename metadata; no parsing or fetching",
    )
    refresh.add_argument(
        "--metadata-only",
        action="store_true",
        help="Reparse indexed filenames and selected retained records/PDF covers; no discovery or network access",
    )
    refresh.add_argument(
        "--source-metadata-only",
        action="store_true",
        help="Refresh retained parent context, response validity and untyped PDF covers; no filename parsing or fetching",
    )
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    if (
        not (args.documents_only or args.metadata_only or args.source_metadata_only)
        and args.inventory_dir is None
    ):
        parser.error(
            "--inventory-dir is required unless a metadata or document refresh is selected"
        )
    result = (
        refresh_source_metadata(args.archive)
        if args.source_metadata_only
        else reindex_documents(args.archive)
        if args.documents_only
        else refresh_filename_metadata(args.archive, workers=args.workers)
        if args.metadata_only
        else build(args.archive, args.inventory_dir, workers=args.workers)
    )
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
