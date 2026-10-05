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
    p.add_argument("--files-per-second", "--requests-per-second", type=positive, default=60,
                   help="Maximum new file starts per second; redirects and fallback share the file slot")
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
    p.add_argument("--max-buffer-mib", type=positive, default=512,
                   help="Bound in-flight body payloads; encoded representations add overhead")
    p.add_argument("--download-workers", type=positive, default=16,
                   help="Maximum captures downloading or awaiting a body reader")
    p.add_argument("--max-spool-mib", type=positive, default=2048,
                   help="Bound temporary native response files separately from processing memory")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--plan-only", action="store_true")
    mode.add_argument("--capture-only", action="store_true",
                      help="Save captures, receipts and retry state without rebuilding document tables")
    mode.add_argument("--update-only", action="store_true",
                      help="Add retained evidence to document tables, preserving existing metadata; no acquisition")
    mode.add_argument("--rebuild-only", action="store_true",
                      help="Explicitly reinterpret retained metadata with current rules; no acquisition")
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
            args.fetcher_binary, files_per_second=args.files_per_second,
            workers=args.workers, max_bytes=args.max_file_mib * 1024**2,
        ) as fetcher:
            summary = run_sync(
                archive, seed_files(args.seed), fetch_spooled=partial(fetcher.fetch_spooled, transport=args.transport),
                limit=args.limit, workers=args.workers, max_seconds=args.max_seconds,
                max_bytes=args.max_file_mib * 1024**2, stop=stop,
                max_buffer_bytes=args.max_buffer_mib * 1024**2,
                download_workers=args.download_workers, max_spool_bytes=args.max_spool_mib * 1024**2,
            )
        summary.update(fetcher="reqwest", files_per_second=args.files_per_second,
                       workers=args.workers, download_workers=args.download_workers,
                       max_buffer_mib=args.max_buffer_mib, max_spool_mib=args.max_spool_mib,
                       http_requests=fetcher.sequence, file_dispatches=fetcher.file_dispatches)
        summary.setdefault("accounting", {}).update(native_request_dispatches=fetcher.sequence,
                                     file_dispatches=fetcher.file_dispatches,
                                     rate_limit_basis="new files; redirects and fallback continue the same file",
                                     http_request_starts=None,
                                     http_request_starts_basis="unavailable; native commands are counted before worker execution")
        return summary
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)


def save_summary(path, summary):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(summary, indent=2) + "\n")
    temporary.replace(path)


def connect_storage(args, log):
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
        storage_config = Config(
            retries={"mode": "standard", "max_attempts": 5},
            max_pool_connections=args.workers + 4,
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        )
        async_options = {}
        if not (args.plan_only or args.rebuild_only or args.update_only):
            from aiobotocore.session import get_session
            async_options['async_client'] = lambda: get_session().create_client(
                's3', **client_args, config=storage_config)
        store = R2Store(
            boto3.client("s3", **client_args, config=storage_config),
            args.bucket,
            **async_options,
        )
        if not args.plan_only:
            # Status is best-effort and bounded; it must not hold up data work.
            status_store = R2Store(boto3.client("s3", **client_args, config=Config(
                connect_timeout=3, read_timeout=5, retries={"total_max_attempts": 1},
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            )), args.bucket)
            log.publish = lambda payload: status_store.put('status/raw-source-sync.json', payload)
    return store


def run(args, log, *, store=None):
    if args.capture_only and args.inspect_bodies:
        raise SystemExit("--inspect-bodies requires a catalog rebuild; omit --capture-only")
    if store is None:
        store = connect_storage(args, log)
    metadata_only = args.rebuild_only or args.update_only
    if not args.plan_only and not metadata_only and args.transport in {"auto", "zyte"}:
        zyte.token()
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:12]
    )
    mode = 'rebuild' if args.rebuild_only else 'update' if args.update_only else 'plan' if args.plan_only else 'capture'
    with log.lock:
        log.state.update(run_id=run_id, mode=mode)
    summary = dict(mode=mode,
                   run_id=run_id, bucket=args.bucket, acquisition_status="not_run",
                   catalog_status="not_run", planning_status="not_run")
    active_stage = "planning_status"
    try:
        if args.plan_only:
            summary["planning_status"] = "running"
            progress.report('load_capture_state')
            archive = Archive(store, run_id, repair=args.repair)
            for item in seed_files(args.seed):
                archive.seed(item)
            summary.update(known_urls=len(archive.state),
                           outcomes=dict(Counter(s["outcome"] for s in archive.state.values())))
            summary["planning_status"] = "completed"
        else:
            if not metadata_only:
                active_stage = 'acquisition_status'
                summary['acquisition_status'] = 'running'
                save_summary(args.summary, summary)
                summary.update(capture_sources(args, store, run_id))
                summary['acquisition_status'] = 'completed'
            if not args.capture_only:
                active_stage = 'catalog_status'
                summary['catalog_status'] = 'running'
                save_summary(args.summary, summary)
                summary['catalog'] = rebuild_catalog(
                    store, seeds=seed_files(args.seed) if args.seed else (), workers=args.index_workers,
                    repair=args.repair or args.rebuild_only, inspect_bodies=args.inspect_bodies,
                )
                summary['catalog_status'] = 'completed'
                summary.setdefault('accounting', {}).update(
                    filename_rows=summary['catalog'].get('rows'),
                    grouped_documents=summary['catalog'].get('document_rows'),
                )
    except BaseException as error:
        summary[active_stage] = 'failed'
        summary['error_type'] = type(error).__name__
        save_summary(args.summary, summary)
        raise
    summary.update(run_id=run_id, bucket=args.bucket)
    if not metadata_only:
        summary["transport"] = args.transport
    save_summary(args.summary, summary)
    if args.capture_only:
        progress.report('capture_saved')
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
