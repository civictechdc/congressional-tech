"""Collect missing linked source files into the append-only R2 capture log."""

import argparse
from collections import Counter
from datetime import datetime, timezone
from functools import partial
import gzip
import json
import os
from pathlib import Path
import signal
import threading
from uuid import uuid4

from congress_api.acquisition.raw_sync import run_sync
from congress_api.cli.common import positive
from congress_api.cli.raw_progress import ProgressLog
from congress_api.parsers.archive_links import json_links
from congress_api.retention.raw_archive import Archive
from congress_api.retention.raw_catalog import rebuild_catalog
from congress_api.retention import raw_progress as progress
from congress_api.retention.r2 import R2Store
from congress_api.transport.rust_fetch import RustFetcher
from congress_api.transport import zyte


class LocalReadOnly:
    def __init__(self, root):
        self.root = root

    def read(self, key):
        path = self.root / key
        return path.read_bytes() if path.is_file() else None

    def keys(self, prefix):
        return sorted(
            str(p.relative_to(self.root)) for p in (self.root / prefix).rglob("*.gz")
        )

    def put(self, *args, **kwargs):
        raise RuntimeError("Local planning is read-only")


def seed_files(paths):
    for path in paths:
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as stream:
            records = (
                (json.loads(line) for line in stream if line.strip())
                if ".jsonl" in path.name
                else [json.load(stream)]
            )
            for record in records:
                yield from json_links(record, source=path.name)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bucket", default="congressional-tech-raw")
    p.add_argument("--account-id", default=os.environ.get("CLOUDFLARE_ACCOUNT_ID"))
    p.add_argument("--transport", choices=("auto", "zyte", "direct"), default="auto")
    p.add_argument("--fetcher-binary", default="source-fetch", help="Path to the Rust reqwest worker")
    p.add_argument("--requests-per-second", type=positive, default=40)
    p.add_argument("--seed", action="append", type=Path, default=[],
                   help="Saved JSON/JSONL link metadata; rebuild mode reads it without acquiring URLs")
    p.add_argument(
        "--limit",
        type=positive,
        default=5000,
        help="Maximum captures/replays per run; unfinished URLs remain queued",
    )
    p.add_argument("--workers", type=positive, default=80)
    p.add_argument("--index-workers", type=positive, default=2)
    p.add_argument("--max-seconds", type=positive, default=5400)
    p.add_argument("--max-file-mib", type=positive, default=64)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--plan-only", action="store_true")
    mode.add_argument("--rebuild-only", action="store_true",
                      help="Rebuild and publish both document tables from retained R2 evidence; no acquisition")
    p.add_argument(
        "--local-mirror",
        type=Path,
        help="Read-only local planning; requires --plan-only",
    )
    p.add_argument("--repair", action="store_true",
                   help="Reconstruct saved state and replay all source evidence")
    p.add_argument("--inspect-bodies", action="store_true",
                   help="Also inspect retained document contents; normal updates use receipts and filenames")
    p.add_argument("--summary", type=Path, default=Path("raw-capture-summary.json"))
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    with ProgressLog(args.summary.with_suffix('.progress.json')) as log:
        return run(args, log)


def capture_sources(args, store, run_id):
    """Finish collection and release its working state before catalog processing."""
    progress.report('load_capture_state')
    archive = Archive(store, run_id, repair=args.repair)
    stop = threading.Event()
    previous_handlers = {sig: signal.signal(sig, lambda *_: stop.set())
                         for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        with RustFetcher(
            args.fetcher_binary, requests_per_second=args.requests_per_second,
            workers=args.workers, max_bytes=args.max_file_mib * 1024**2,
        ) as fetcher:
            summary = run_sync(
                archive, seed_files(args.seed), fetch=partial(fetcher.fetch, transport=args.transport),
                limit=args.limit, workers=args.workers, max_seconds=args.max_seconds,
                max_bytes=args.max_file_mib * 1024**2, stop=stop,
            )
        summary.update(fetcher="reqwest", requests_per_second=args.requests_per_second,
                       workers=args.workers, http_requests=fetcher.sequence)
        return summary
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)


def save_summary(path, summary):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2) + "\n")


def run(args, log):
    progress.report('connect_storage')
    if args.local_mirror:
        if not args.plan_only:
            raise SystemExit("--local-mirror requires --plan-only")
        store = LocalReadOnly(args.local_mirror)
    else:
        import boto3
        from botocore.config import Config

        if not all(
            (
                args.account_id,
                os.environ.get("R2_ACCESS_KEY_ID"),
                os.environ.get("R2_SECRET_ACCESS_KEY"),
            )
        ):
            raise SystemExit(
                "CLOUDFLARE_ACCOUNT_ID, R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY are required"
            )
        client_args = dict(
            endpoint_url=f"https://{args.account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            region_name="auto",
        )
        store = R2Store(
            boto3.client("s3", **client_args, config=Config(
                    retries={"mode": "standard", "max_attempts": 5},
                    max_pool_connections=args.workers + 4,
                    request_checksum_calculation="when_required",
                    response_checksum_validation="when_required",
                )),
            args.bucket,
        )
        if not args.plan_only:
            # Status is best-effort and bounded; it must not hold up data work.
            status_store = R2Store(boto3.client("s3", **client_args, config=Config(
                connect_timeout=3, read_timeout=5, retries={"total_max_attempts": 1},
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            )), args.bucket)
            log.publish = lambda payload: status_store.put('status/raw-source-sync.json', payload)
    if not args.plan_only and not args.rebuild_only and args.transport in {"auto", "zyte"}:
        zyte.token()
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:12]
    )
    with log.lock:
        log.state.update(run_id=run_id, mode='rebuild' if args.rebuild_only else 'plan' if args.plan_only else 'capture')
    if args.rebuild_only:
        summary = dict(mode="rebuild", catalog=rebuild_catalog(
            store, seeds=seed_files(args.seed) if args.seed else (), workers=args.index_workers, repair=args.repair, inspect_bodies=args.inspect_bodies,
        ))
    elif args.plan_only:
        progress.report('load_capture_state')
        archive = Archive(store, run_id, repair=args.repair)
        seeds = seed_files(args.seed)
        for item in seeds:
            archive.seed(item)
        summary = dict(
            mode="plan",
            known_urls=len(archive.state),
            outcomes=dict(Counter(s["outcome"] for s in archive.state.values())),
        )
    else:
        summary = dict(mode="capture", **capture_sources(args, store, run_id))
        # A later catalog failure must not hide already committed acquisitions.
        save_summary(args.summary, {**summary, 'run_id': run_id, 'bucket': args.bucket,
                                   'transport': args.transport, 'catalog_status': 'pending'})
        summary['catalog'] = rebuild_catalog(
            store, seeds=seed_files(args.seed), workers=args.index_workers, repair=args.repair, inspect_bodies=args.inspect_bodies,
        )
        summary['catalog_status'] = 'completed'
    summary.update(run_id=run_id, bucket=args.bucket)
    if not args.rebuild_only:
        summary["transport"] = args.transport
    save_summary(args.summary, summary)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
