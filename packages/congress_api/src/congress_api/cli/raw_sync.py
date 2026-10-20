"""Collect missing linked source files into the append-only R2 capture log."""

import argparse
from collections import Counter
from datetime import datetime, timezone
from functools import partial
from hashlib import sha256
import gzip
import json
import os
from pathlib import Path
import signal
import threading
from uuid import uuid4

from congress_api.acquisition.raw_sync import run_sync, response_capacity, RETRY_OUTCOMES
from congress_api.cli.common import positive, nonnegative
from congress_api.cli.raw_progress import ProgressLog
from congress_api.parsers.archive_links import json_links
from congress_api.retention.raw_archive import Archive
from congress_api.retention.raw_catalog import update_from_raw
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


def add_catalog_modes(mode):
    mode.add_argument('--adopt-raw', type=Path, metavar='INPUTS_JSON',
                      help='Adopt investigated capture/state files and retained readings from exact input pins; no acquisition')
    mode.add_argument('--adopt-catalog', metavar='OPERATION',
                      help='Adopt the exact existing catalog pair under a stable operation name; no interpretation replay')
    mode.add_argument('--qualify-sources', action='store_true',
                      help='Qualify all retained source contributions against exact selected source/document values')
    mode.add_argument('--upgrade-source-rules', metavar='VERSION',
                      help='Explicitly apply named source rules to the complete retained inventory after qualification')


def operation_mode(args):
    for field, label in (('adopt_raw', 'adopt-raw'), ('adopt_catalog', 'adopt-catalog'),
                         ('qualify_sources', 'qualify-sources'), ('upgrade_source_rules', 'upgrade-source-rules'),
                         ('update_only', 'update'), ('plan_only', 'plan')):
        if getattr(args, field, None):
            return label
    return 'capture'


def adoption_inputs(path):
    """Read only explicit investigated pins; never discover adoption inputs."""
    from congress_api.retention.derived_files import file_identity
    from congress_api.retention.raw_adoption_inputs import raw_source_pins
    with path.open('rb') as source:
        payload = source.read((1 << 20) + 1)
    if len(payload) > 1 << 20:
        raise ValueError('Raw adoption input receipt exceeds its byte budget')
    value = json.loads(payload)
    if (not isinstance(value, dict) or set(value) != {'version', 'operation', 'inputs', 'filename_version'}
            or type(value['version']) is not int or value['version'] != 2
            or not isinstance(value['operation'], str) or not value['operation'].strip()
            or not isinstance(value['inputs'], dict) or set(value['inputs']) != {'captures', 'state'}
            or not isinstance(value['filename_version'], dict)
            or set(value['filename_version']) != {'selector_sha256', 'selected_ref'}):
        raise ValueError('Raw adoption requires exact input pins, an operation, and a catalog cursor')
    if any(not isinstance(entry, dict) or set(entry) != {'path', 'sha256', 'source'}
           for entry in value['inputs'].values()):
        raise ValueError('Raw adoption input requires exact local and source pins')
    sources = raw_source_pins({name: entry['source'] for name, entry in value['inputs'].items()})
    paths, hashes = {}, {}
    for name, entry in value['inputs'].items():
        if (not isinstance(entry['path'], str) or not entry['path']
                or not isinstance(entry['sha256'], str) or len(entry['sha256']) != 64
                or any(char not in '0123456789abcdef' for char in entry['sha256'])):
            raise ValueError('Raw adoption input requires an exact path and SHA-256')
        paths[name] = (path.parent / entry['path']).resolve()
        if file_identity(paths[name])['sha256'] != entry['sha256']:
            raise ValueError('Investigated raw adoption input digest changed: ' + name)
        hashes[name] = entry['sha256']
    return dict(paths=paths, sha256s=hashes, operation=value['operation'],
                filename_version=value['filename_version'], source_pins=sources)


def adopt_catalog(store, *, raw_storage, directory, candidate):
    """Use the maintained exact-value adoption owner without grouping replay."""
    import pyarrow.parquet as pq
    from congress_api.retention.catalog_publication import read_catalog
    from congress_api.retention.catalog_selection import NativeCatalogSnapshot
    from congress_api.retention.catalog_dependency_storage import CatalogDependencyStorage
    from congress_api.retention.catalog_adoption import adopt_native_catalog
    from congress_api.retention.catalog_raw_updates import MAX_ROWS, MAX_BYTES
    from congress_api.retention.immutable_metadata import encoded
    with read_catalog(store, native=raw_storage.native) as previous:
        if isinstance(previous, NativeCatalogSnapshot):
            dependencies = CatalogDependencyStorage.for_snapshot(previous)
        elif previous.filenames_path is not None:
            with pq.ParquetFile(previous.filenames_path) as file:
                schema = file.schema_arrow
            dependencies = CatalogDependencyStorage(native=raw_storage.native, store=store,
                namespace='catalog-dependencies-v2', source_schema=schema, max_rows=MAX_ROWS, max_bytes=MAX_BYTES)
        else:
            raise ValueError('Catalog adoption requires an existing exact catalog pair')
        result = adopt_native_catalog(store, native=raw_storage.native, previous=previous,
            dependencies=dependencies, candidate=candidate, directory=directory,
            max_chunk_rows=MAX_ROWS, max_chunk_bytes=MAX_BYTES, rules=dict(interpretation='preserved-exact-values-v1'))
        result['selected_identity'] = dict(selected_ref=result['selection'],
            selector_sha256=sha256(encoded(dict(version=2, selection=result['selection']))).hexdigest())
        return result


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bucket", default="congressional-tech-raw")
    p.add_argument("--account-id", default=os.environ.get("CLOUDFLARE_ACCOUNT_ID"))
    p.add_argument("--transport", choices=("auto", "zyte", "direct"), default="auto")
    p.add_argument("--fetcher-binary", default="source-fetch", help="Path to the Rust reqwest worker")
    p.add_argument("--files-per-second", "--requests-per-second", type=positive, default=60,
                   help="Maximum new file starts per second; redirects and fallback share the file slot")
    p.add_argument("--seed", action="append", type=Path, default=[],
                   help="Saved JSON/JSONL link metadata; catalog updates do not acquire URLs")
    p.add_argument(
        "--limit",
        type=positive,
        default=5000,
        help="Maximum captures/replays per run; unfinished URLs remain queued",
    )
    p.add_argument("--workers", type=positive, default=80)
    p.add_argument("--initial-only", action="store_true",
                   help="Admit only pending URLs and their in-run retries; leave historical failures and retained replays alone")
    p.add_argument("--retry-outcome", action="append", choices=sorted(RETRY_OUTCOMES), default=[],
                   help="Retry this failed outcome; outcomes other than retry_later/request_failed require --urls")
    p.add_argument("--retry-now", action="store_true",
                   help="Explicitly retry selected failures before next_attempt_at; requires --urls and --retry-outcome. In-run Retry-After waits still apply")
    p.add_argument("--urls", type=Path,
                   help="JSON array of exact URLs eligible for this capture; other state remains checkpointed")
    p.add_argument("--reinspect-retained", action="store_true",
                   help="Read only the selected retained bodies, appending new readings without source HTTP; requires --urls")
    p.add_argument("--index-workers", type=positive, default=2)
    p.add_argument("--max-seconds", type=positive, default=5400)
    p.add_argument("--max-file-mib", type=nonnegative, default=64,
                   help="Per-file policy cap; 0 removes it and uses the existing body/spool capacity")
    p.add_argument("--request-timeout-seconds", type=positive, default=300,
                   help="Native HTTP deadline per request, at most 900 seconds; read-idle timeout remains 90 seconds")
    p.add_argument("--metadata-workers", type=positive, default=3,
                   help="Spawned Python processes for CPU-heavy body metadata extraction")
    p.add_argument("--max-buffer-mib", type=positive, default=2048,
                   help="Bound parent body payloads; process copies, parsers and indexes add overhead")
    p.add_argument("--download-workers", type=positive, default=16,
                   help="Maximum captures downloading or awaiting a body reader")
    p.add_argument("--max-spool-mib", type=positive, default=2048,
                   help="Bound temporary native response files separately from processing memory")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--plan-only", action="store_true")
    mode.add_argument("--capture-only", action="store_true",
                      help="Save captures, receipts and retry state without updating document tables")
    mode.add_argument("--update-only", action="store_true",
                      help="Add retained evidence to document tables, preserving existing metadata; no acquisition")
    mode.add_argument("--rebuild-only", action="store_true",
                      help=argparse.SUPPRESS)
    add_catalog_modes(mode)
    p.add_argument(
        "--local-mirror",
        type=Path,
        help="Read-only local planning; requires --plan-only",
    )
    p.add_argument('--native-config', type=Path,
                   help='Explicit native runtime settings; existing raw data requires one-time adoption')
    p.add_argument('--catalog-directory', type=Path,
                   help='Retain exact catalog continuation inputs here; defaults beside the summary')
    p.add_argument("--repair", action="store_true",
                   help=argparse.SUPPRESS)
    p.add_argument("--inspect-bodies", action="store_true",
                   help=argparse.SUPPRESS)
    p.add_argument("--summary", type=Path, default=Path("raw-capture-summary.json"))
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    with ProgressLog(args.summary.with_suffix('.progress.json')) as log:
        return run(args, log)


def capture_sources(args, store, run_id, *, raw_storage):
    """Finish collection and release its working state before catalog processing."""
    progress.report('load_capture_state')
    archive = Archive(store, run_id, storage=raw_storage)
    stop = threading.Event()
    previous_handlers = {sig: signal.signal(sig, lambda *_: stop.set())
                         for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        resource_bounded = args.max_file_mib == 0
        max_bytes = (response_capacity(args.max_buffer_mib * 1024**2, args.max_spool_mib * 1024**2)
                     if resource_bounded else args.max_file_mib * 1024**2)
        options = dict(
            limit=args.limit, workers=args.workers, max_seconds=args.max_seconds,
            max_bytes=max_bytes, stop=stop,
            max_buffer_bytes=args.max_buffer_mib * 1024**2,
            download_workers=args.download_workers, max_spool_bytes=args.max_spool_mib * 1024**2,
            metadata_workers=args.metadata_workers, initial_only=args.initial_only,
            retry_outcomes=args.retry_outcome, urls=args.selected_urls,
            reinspect_retained=args.reinspect_retained,
            retry_now=args.retry_now, resource_bounded=resource_bounded,
        )
        if args.reinspect_retained:
            def no_fetch(url):
                raise RuntimeError('Source HTTP is disabled during retained reinspection')
            summary = run_sync(archive, (), fetch=no_fetch, **options)
            summary.update(fetcher='retained', http_requests=0, file_dispatches=0)
            summary['accounting'].update(native_request_dispatches=0, file_dispatches=0)
            return summary
        with RustFetcher(
            args.fetcher_binary, files_per_second=args.files_per_second,
            workers=args.workers, max_bytes=max_bytes,
            request_timeout=args.request_timeout_seconds,
            limit_basis='resource_budget' if resource_bounded else 'file_policy',
        ) as fetcher:
            summary = run_sync(
                archive, seed_files(args.seed), fetch_spooled=partial(fetcher.fetch_spooled, transport=args.transport),
                **options,
            )
        summary.update(fetcher="reqwest", files_per_second=args.files_per_second,
                       request_timeout_seconds=args.request_timeout_seconds,
                       workers=args.workers, download_workers=args.download_workers,
                       metadata_workers=args.metadata_workers,
                       max_buffer_mib=args.max_buffer_mib, max_spool_mib=args.max_spool_mib,
                       max_file_mib=args.max_file_mib, effective_response_capacity_bytes=max_bytes,
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
        if operation_mode(args) == 'capture':
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


def run(args, log, *, store=None, raw_storage=None):
    mode = operation_mode(args)
    metadata_only = mode not in {'capture', 'plan'}
    if args.capture_only and metadata_only:
        raise SystemExit('--capture-only cannot be combined with catalog or adoption modes')
    if args.upgrade_source_rules is not None and not args.upgrade_source_rules.strip():
        raise SystemExit('A source rule upgrade requires an explicit nonempty rule version')
    if args.adopt_catalog is not None and not args.adopt_catalog.strip():
        raise SystemExit('Catalog adoption requires a nonempty stable operation name')
    if mode in {'adopt-raw', 'adopt-catalog'} and args.seed:
        raise SystemExit('Exact adoption does not accept seed changes')
    if args.retry_now and (not args.urls or not args.retry_outcome or not args.capture_only or args.reinspect_retained):
        raise SystemExit('--retry-now requires --capture-only, --urls and --retry-outcome')
    if set(args.retry_outcome) - {'retry_later', 'request_failed'} and not args.urls:
        raise SystemExit('Historical outcome retries require --urls')
    if args.urls and (not args.capture_only or args.repair or args.seed):
        raise SystemExit('--urls requires --capture-only without --repair or --seed')
    if args.reinspect_retained and (not args.urls or args.retry_outcome or args.initial_only):
        raise SystemExit('--reinspect-retained requires --urls without --retry-outcome or --initial-only')
    args.selected_urls = None
    if args.urls:
        args.selected_urls = json.loads(args.urls.read_text())
        if not isinstance(args.selected_urls, list) or any(
                not isinstance(url, str) or not url for url in args.selected_urls):
            raise SystemExit('--urls must contain a JSON array of nonempty URL strings')
    if args.retry_outcome and (not args.capture_only or args.initial_only or args.repair or args.seed):
        raise SystemExit("--retry-outcome requires --capture-only without --initial-only, --repair or --seed")
    if args.initial_only and (args.repair or args.rebuild_only or mode != 'capture'):
        raise SystemExit("--initial-only requires acquisition without --repair")
    if args.inspect_bodies:
        raise SystemExit("--inspect-bodies requires scoped native reprocessing; use explicit retained URL reinspection")
    if args.rebuild_only or args.repair:
        raise SystemExit("Full rebuild and repair are not operational routes; use --update-only or explicit reviewed adoption")
    raw_inputs = adoption_inputs(args.adopt_raw) if args.adopt_raw else None
    if raw_storage is None:
        if args.native_config is None:
            raise SystemExit('--native-config is required; raw archive adoption is explicit')
        from congress_api.retention.docspec import NativeDatasets
        from congress_api.retention.raw_storage import RawStorage
        native = NativeDatasets.from_config(args.native_config)
    if store is None:
        store = connect_storage(args, log)
    if raw_storage is None:
        if raw_inputs is not None:
            import pyarrow.parquet as pq
            with pq.ParquetFile(raw_inputs['paths']['state']) as state:
                raw_storage = RawStorage(store, native, state_schema=state.schema_arrow)
        else:
            raw_storage = RawStorage.open(store, native)
    if raw_storage.store is not store:
        raise ValueError('Raw/catalog commands must share one guarded store owner')
    if not args.plan_only and not metadata_only and not args.reinspect_retained and args.transport in {"auto", "zyte"}:
        zyte.token()
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:12]
    )
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
            archive = Archive(store, run_id, storage=raw_storage)
            for item in seed_files(args.seed):
                archive.seed_links(item)
            archive.admit_pending_urls()
            summary.update(known_urls=len(archive.state),
                           outcomes=dict(Counter(s["outcome"] for s in archive.state.values())))
            summary["planning_status"] = "completed"
        else:
            if not metadata_only:
                active_stage = 'acquisition_status'
                summary['acquisition_status'] = 'running'
                save_summary(args.summary, summary)
                summary.update(capture_sources(args, store, run_id, raw_storage=raw_storage))
                summary['acquisition_status'] = 'completed'
            if mode == 'adopt-raw':
                from congress_api.retention.raw_adoption import adopt_archive
                active_stage = 'raw_adoption_status'
                summary[active_stage] = 'running'
                save_summary(args.summary, summary)
                candidate = sha256(raw_inputs['operation'].encode()).hexdigest()[:32]
                directory = (args.catalog_directory or args.summary.with_suffix('.catalog-update')) / ('adopt-raw-' + candidate)
                selected = adopt_archive(raw_storage, directory=directory, **raw_inputs)
                summary['raw_adoption'] = dict(identity=selected.identity)
                summary[active_stage] = 'completed'
            elif not args.capture_only:
                active_stage = 'catalog_status'
                summary['catalog_status'] = 'running'
                save_summary(args.summary, summary)
                raw_identity = raw_storage.snapshot().identity
                candidate = (raw_identity[:32] if mode == 'update' or mode == 'capture' else
                    sha256(json.dumps([mode, args.adopt_catalog if mode == 'adopt-catalog' else raw_identity,
                                       args.upgrade_source_rules], separators=(',', ':')).encode()).hexdigest()[:32])
                directory = (args.catalog_directory or args.summary.with_suffix('.catalog-update')) / candidate
                options = dict(raw_storage=raw_storage, directory=directory, candidate=candidate)
                if mode == 'adopt-catalog':
                    summary['catalog'] = adopt_catalog(store, **options)
                else:
                    operation = update_from_raw
                    if mode in {'qualify-sources', 'upgrade-source-rules'}:
                        from congress_api.retention import raw_catalog
                        operation = (raw_catalog.qualify_source_contributions if mode == 'qualify-sources'
                                     else raw_catalog.upgrade_source_rules)
                    if mode == 'upgrade-source-rules':
                        options['rule_version'] = args.upgrade_source_rules
                    summary['catalog'] = operation(store, seeds=seed_files(args.seed) if args.seed else (), **options)
                summary['catalog_status'] = 'completed'
                summary.setdefault('accounting', {}).update(
                    filename_rows=summary['catalog']['counts']['source_rows'],
                    grouped_documents=summary['catalog']['counts']['document_rows'],
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
