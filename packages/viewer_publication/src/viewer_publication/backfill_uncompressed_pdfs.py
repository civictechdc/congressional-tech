"""CLI to backfill uncompressed .pdf sibling objects in R2 or LocalStore for accepted-files.json PDFs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from congress_shared.custody import write_atomic_bytes
from congress_shared.storage import connect_r2

from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.pdf_backfill import backfill_uncompressed_pdfs
from congress_api.retention.r2 import R2Store
from congress_api.retention.raw_storage import DEFAULT_ACCEPTED_FILES_PATH


def main(argv: list[str] | None = None, *, store: Any | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--accepted-files",
        type=Path,
        default=DEFAULT_ACCEPTED_FILES_PATH,
        help="Path to accepted-files.json",
    )
    parser.add_argument(
        "--local-store",
        type=Path,
        help="Optional local object-store directory instead of R2",
    )
    parser.add_argument(
        "--bucket",
        default="congressional-tech-raw",
        help="Cloudflare R2 bucket name (default: congressional-tech-raw)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check which .pdf objects would be backfilled without writing",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path to write the JSON backfill report",
    )
    args = parser.parse_args(argv)

    target_store = store
    if target_store is None:
        if args.local_store is not None:
            target_store = LocalStore(args.local_store, store_uncompressed_pdfs=True)
        else:
            client = connect_r2(
                bucket=args.bucket,
                connect_timeout=15,
                read_timeout=180,
                retries={"total_max_attempts": 3},
            )
            target_store = R2Store(client, args.bucket, store_uncompressed_pdfs=True)

    report = backfill_uncompressed_pdfs(
        target_store,
        args.accepted_files,
        dry_run=args.dry_run,
    )
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        write_atomic_bytes(
            args.output,
            rendered.encode("utf-8"),
            temp_mode="unique",
            fsync=False,
        )
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
