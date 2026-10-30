"""CLI to stream-copy uncompressed .pdf sibling objects and verification provenance (B13)."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

from congress_shared.custody import write_atomic_bytes
from congress_shared.storage import connect_r2
from docspec_client.client import NativeDatasets

from congress_api.retention.body_store import BodyStore, LocalAdapter, R2Adapter
from congress_api.retention.pdf_backfill import apply_staged, backfill_uncompressed_pdfs
from congress_api.retention.writer_identity import writer_identity

ROOT = Path(__file__).resolve().parents[4]


def _load_selector(path: Path | None) -> Any:
    if path is None:
        return None
    if path.suffix == '.json':
        return json.loads(path.read_text(encoding='utf-8'))
    return path


def main(argv: list[str] | None = None, *, store: BodyStore | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidates', type=Path, help='Explicit candidate SHA-256 or key list (JSON/JSONL/Parquet)')
    parser.add_argument('--captures', type=Path, help='Captures Parquet path or native_table pin JSON')
    parser.add_argument('--readings', type=Path, help='Readings Parquet path or native_table pin JSON')
    parser.add_argument('--verification-inventory', type=Path, help='Optional JSON array of {key,path} verification files')
    parser.add_argument('--engine-config', type=Path, help='Native engine runtime config JSON')
    parser.add_argument('--local-store', type=Path, help='Local raw store directory instead of R2')
    parser.add_argument('--bucket', default='congressional-tech-raw', help='Cloudflare R2 raw bucket name')
    parser.add_argument('--work', type=Path, help='Work directory for staged verification records and report')
    parser.add_argument('--dry-run', action='store_true', help='Plan candidate .pdf copies without reading or writing')
    parser.add_argument('--stage-only', action='store_true', help='Stage verification.jsonl in --work without publishing')
    parser.add_argument('--apply-staged', action='store_true', help='Publish staged verification.jsonl from --work')
    parser.add_argument('--output', type=Path, help='Optional path to write the JSON report')
    args = parser.parse_args(argv)

    if args.apply_staged and args.work is None:
        parser.error('--apply-staged requires --work')
    if args.stage_only and args.work is None:
        parser.error('--stage-only requires --work')
    if not args.apply_staged and args.candidates is None and not all((args.captures, args.readings, args.engine_config)):
        parser.error('Provide --candidates or all of --captures, --readings, and --engine-config')

    target_store = store
    if target_store is None:
        if args.local_store is not None:
            target_store = BodyStore(LocalAdapter(args.local_store))
        else:
            writer_identity(ROOT, 'pdf-backfill')
            client = connect_r2(
                bucket=args.bucket,
                connect_timeout=15,
                read_timeout=180,
                retries={'mode': 'standard', 'max_attempts': 5},
            )
            target_store = BodyStore(R2Adapter(client, args.bucket))

    if args.apply_staged:
        report = apply_staged(args.work, target_store)
    else:
        v_files = json.loads(args.verification_inventory.read_text(encoding='utf-8')) if args.verification_inventory else ()
        engine = NativeDatasets.from_config(args.engine_config) if args.engine_config else None
        report = backfill_uncompressed_pdfs(
            target_store,
            args.candidates,
            captures=_load_selector(args.captures),
            readings=_load_selector(args.readings),
            verification_files=v_files,
            engine=engine,
            work=args.work,
            checked_at=datetime.now(timezone.utc).isoformat(),
            dry_run=args.dry_run,
            stage_only=args.stage_only,
            root=ROOT,
        )

    rendered = json.dumps(report, indent=2) + '\n'
    if args.output:
        write_atomic_bytes(args.output, rendered.encode('utf-8'), temp_mode='unique', fsync=False)
    sys.stdout.write(rendered)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
