"""Incremental `body_text` extraction + `derived/body_text/current.json` publication.

Runs after the archive release pointer moves (or on an unchanged release whose `body_text`
pointer lags):
  1. Resolves current R2 Iceberg heads (`captures`, `readings` for sniff, `filename_readings`,
     `body_text`, and `body_text_readings`).
  2. Extracts any unsettled `pdf`, `html`, or `xml` bodies using the portable CPU strategy
     (`portable_tesseract_200dpi`: bounded 200 DPI Tesseract 5.5.4 + CMS HTML cleanup + XML),
     leaving all settled v12 historical rows untouched.
  3. Exports `derived/body_text/<sha256>.parquet` bound to the live release's `detail.parquet`
     and CAS-updates `derived/body_text/current.json`, skipping rebuild/upload when the live
     pointer already names the current `(release_id, detail, body_text, selection)` state.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import time

from congress_api.lake import body_text, body_text_selection
from congress_api.lake.tables import resolve_tables
from congress_api.retention.body_store import BodyStore, R2Adapter
from congress_api.retention.provenance import durable_json
from congress_api.retention.provenance_inventory import unreadable_inventory
from congress_api.retention.r2 import configure_read_retries
from viewer_publication import body_text_export
from viewer_publication.archive_publish_job import publication_configuration
from viewer_publication.body_text_ssot import verify_ssot_export
from viewer_publication.reviewed_body_text import apply_reviewed_rows

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SELECTION = ROOT / 'model/jobs/inputs/body-text-selection-v14/selection.json.gz'
DEFAULT_LIMITS_DOC = ROOT / 'model/jobs/inputs/body-text-selection-v14/LIMITS.md'
DEFAULT_DAILY_SPEC = ROOT / 'model/jobs/publish-daily.json'
DEFAULT_PUBLISH_SPEC = ROOT / 'model/jobs/publish.json'
RELEASE_POINTER_KEY = 'viewer-publications/manifest.json'
STAGED_RELEASE_POINTER_KEY = 'viewer-publications/staged.json'
STAGED_POINTER_KEY = 'derived/body_text/staged.json'
_HEX64 = re.compile('[0-9a-f]{64}')
BODY_TEXT_TABLES = {
    'body_text': {'namespace': ['archive_r1b'], 'name': 'body_text'},
    'readings': {'namespace': ['archive_r1b'], 'name': 'body_text_readings'},
}
# Measured on 320,629-row export (6.13 GiB peak RSS): 256-row / 16 MiB batches keep wide text sorts bounded.
BODY_TEXT_ENGINE_LIMITS = dict(
    compute_threads=2,
    memory_bytes=8 << 30,
    scratch_bytes=40 << 30,
    batch_rows=256,
    max_batch_bytes=16 << 20,
    max_metadata_bytes=64 << 20,
)
TRANSIENT_UPLOAD_CODES = frozenset({
    '429', '500', '502', '503', '504',
    'InternalError', 'RequestTimeout', 'ServiceUnavailable', 'SlowDown', 'Throttling',
})


def configure_upload_part_retries(client, *, max_attempts: int = 5, base_delay: float = 1.5):
    """Retry idempotent `UploadPart` calls (fixed buffer + Content-MD5) on transient R2 errors.

    Conditional `CompleteMultipartUpload` (`If-None-Match: *`) and pointer `PutObject` (`If-Match`)
    keep their single attempt.
    """
    from botocore.exceptions import BotoCoreError, ClientError

    real_upload_part = client.upload_part

    def upload_part_with_retry(**kwargs):
        for attempt in range(1, max_attempts + 1):
            try:
                return real_upload_part(**kwargs)
            except ClientError as error:
                resp = getattr(error, 'response', None) or {}
                code = str((resp.get('Error') or {}).get('Code') or '')
                status = str((resp.get('ResponseMetadata') or {}).get('HTTPStatusCode') or '')
                if attempt >= max_attempts or ({code, status} & TRANSIENT_UPLOAD_CODES) == set():
                    raise
            except BotoCoreError:
                if attempt >= max_attempts:
                    raise
            time.sleep(min(30.0, base_delay * (2 ** (attempt - 1))))

    client.upload_part = upload_part_with_retry
    return client


def _get_json(client, *, bucket: str, key: str, max_bytes: int = 4 << 20):
    response = client.get_object(Bucket=bucket, Key=key)
    with response['Body'] as stream:
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError(f'Remote JSON object exceeds {max_bytes} bytes: {key}')
    return json.loads(raw), response.get('ETag')


def _read_optional_pointer(client, *, bucket: str, key: str):
    try:
        return _get_json(client, bucket=bucket, key=key)
    except Exception as error:
        resp = getattr(error, 'response', None) or {}
        code = (resp.get('Error') or {}).get('Code')
        status = (resp.get('ResponseMetadata') or {}).get('HTTPStatusCode')
        if code in {'404', 'NoSuchKey', 'NotFound'} or status == 404:
            return None, None
        raise


def _ensure_detail_parquet(client, *, bucket: str, release_id: str, detail_entry: dict,
                           work: Path, release_dir: Path | None) -> Path:
    expected_sha = detail_entry['sha256']
    expected_size = detail_entry['size']
    if release_dir is not None:
        local_candidate = Path(release_dir) / 'detail.parquet'
        if local_candidate.is_file() and local_candidate.stat().st_size == expected_size:
            facts = body_text_export.file_facts(local_candidate)
            if facts['sha256'] == expected_sha:
                return local_candidate.resolve()
    target = work / 'detail.parquet'
    key = f'viewer-publications/releases/{release_id}/detail.parquet'
    response = client.get_object(Bucket=bucket, Key=key)
    digest = sha256()
    size = 0
    with response['Body'] as source, target.open('wb') as dest:
        while chunk := source.read(8 << 20):
            dest.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    if size != expected_size or digest.hexdigest() != expected_sha:
        target.unlink(missing_ok=True)
        raise ValueError(f'Downloaded {key} failed byte/SHA-256 verification')
    return target


def _validate_release_id(release_id: str) -> str:
    if not isinstance(release_id, str) or _HEX64.fullmatch(release_id) is None:
        raise ValueError(f'Expected 64-char hex release_id, got {release_id!r}')
    return release_id


def resolve_target_release(client, *, bucket: str, release_id: str | None = None,
                           prefer_staged: bool = False) -> str:
    """Select the target release_id from an explicit pin, staged pointer, or live manifest."""
    if release_id is not None:
        return _validate_release_id(release_id)
    if prefer_staged:
        staged_pointer, _ = _read_optional_pointer(client, bucket=bucket, key=STAGED_RELEASE_POINTER_KEY)
        if isinstance(staged_pointer, dict) and isinstance(staged_pointer.get('release_id'), str):
            return _validate_release_id(staged_pointer['release_id'])
    live_pointer, _ = _get_json(client, bucket=bucket, key=RELEASE_POINTER_KEY)
    return _validate_release_id(live_pointer['release_id'])


def verify_body_text_pointer(client, *, bucket: str, release_id: str, detail_entry: dict | None = None,
                             pointer_key: str | None = None, definition: dict | None = None) -> tuple[dict, str | None]:
    """Verify a body_text pointer exists, matches `release_id`/`detail`, and backs its Parquet."""
    _validate_release_id(release_id)
    definition = body_text_export.load_definition() if definition is None else definition
    target_key = pointer_key or definition['pointer']
    pointer, etag = _read_optional_pointer(client, bucket=bucket, key=target_key)
    if not isinstance(pointer, dict):
        raise ValueError(f'Missing body_text pointer at {target_key} for release {release_id}')
    if pointer.get('release_id') != release_id:
        raise ValueError(
            f'Body-text pointer {target_key} names release {pointer.get("release_id")!r}, expected {release_id}'
        )
    if detail_entry is not None:
        expected_detail = {'sha256': detail_entry['sha256'], 'size': detail_entry['size']}
        if pointer.get('detail') != expected_detail:
            raise ValueError(f'Body-text pointer {target_key} detail pin disagrees with release {release_id}')
    digest = pointer.get('sha256')
    key = pointer.get('key')
    expected_bytes = pointer.get('bytes')
    if (not isinstance(digest, str) or _HEX64.fullmatch(digest) is None
            or key != definition['prefix'] + digest + '.parquet'
            or type(expected_bytes) is not int or expected_bytes < 0):
        raise ValueError(f'Invalid body_text pointer metadata in {target_key}')
    head = client.head_object(Bucket=bucket, Key=key)
    if head.get('ContentLength') != expected_bytes:
        raise ValueError(f'Body-text export {key} size differs from pointer {target_key}')
    return pointer, etag


def promote_staged_body_text(client, *, bucket: str, release_id: str, detail_entry: dict | None = None,
                             definition: dict | None = None, staged_key: str = STAGED_POINTER_KEY) -> dict:
    """Promote `derived/body_text/staged.json` to `current.json` and retire superseded exports."""
    from viewer_publication.client import publish_manifest_pointer

    _validate_release_id(release_id)
    definition = body_text_export.load_definition() if definition is None else definition
    live_key = definition['pointer']
    current_pointer, expected_etag = _read_optional_pointer(client, bucket=bucket, key=live_key)
    staged_pointer, _ = _read_optional_pointer(client, bucket=bucket, key=staged_key)
    if staged_pointer is None:
        live_pointer, _ = verify_body_text_pointer(
            client, bucket=bucket, release_id=release_id, detail_entry=detail_entry,
            pointer_key=live_key, definition=definition,
        )
        return dict(status='already_current', release_id=release_id, pointer=live_pointer)
    staged_pointer, _ = verify_body_text_pointer(
        client, bucket=bucket, release_id=release_id, detail_entry=detail_entry,
        pointer_key=staged_key, definition=definition,
    )
    if current_pointer == staged_pointer:
        if callable(getattr(client, 'delete_object', None)):
            try:
                client.delete_object(Bucket=bucket, Key=staged_key)
            except Exception:
                pass
        return dict(status='already_current', release_id=release_id, pointer=current_pointer)
    published = publish_manifest_pointer(
        client, bucket=bucket, pointer=staged_pointer, key=live_key, expected_etag=expected_etag,
    )
    retired = body_text_export.retire_unnamed(client, bucket=bucket, prefix=definition['prefix'], pointer_key=live_key)
    if callable(getattr(client, 'delete_object', None)):
        try:
            client.delete_object(Bucket=bucket, Key=staged_key)
        except Exception:
            pass
    return dict(status='promoted', release_id=release_id, pointer=staged_pointer,
                pointer_etag=published.etag, retired=retired)


def _export_is_current(client, *, bucket: str, current_pointer: dict | None, release_id: str,
                       detail_pin: dict, body_text_pin: dict, selection_sha256: str,
                       incremental_versions: dict[str, str]) -> bool:
    if not isinstance(current_pointer, dict):
        return False
    if (current_pointer.get('release_id') != release_id
            or current_pointer.get('detail') != {'sha256': detail_pin['sha256'], 'size': detail_pin['size']}
            or current_pointer.get('body_text') != body_text_pin
            or (current_pointer.get('selection') or {}).get('sha256') != selection_sha256
            or current_pointer.get('incremental_versions') != dict(sorted(incremental_versions.items()))):
        return False
    key = current_pointer.get('key')
    expected_bytes = current_pointer.get('bytes')
    if not isinstance(key, str) or not key or type(expected_bytes) is not int:
        return False
    try:
        head = client.head_object(Bucket=bucket, Key=key)
    except Exception:
        return False
    return head.get('ContentLength') == expected_bytes


def sync_and_publish(
    *,
    work: Path,
    engine_config: str | Path,
    selection_path: Path = DEFAULT_SELECTION,
    daily_spec_path: Path = DEFAULT_DAILY_SPEC,
    publish_spec_path: Path = DEFAULT_PUBLISH_SPEC,
    body_text_tables: dict = BODY_TEXT_TABLES,
    release_dir: Path | None = None,
    release_id: str | None = None,
    prefer_staged: bool = False,
    stage_only: bool = False,
    parser_workers: int = 3,
    max_batches: int | None = None,
    keep_export: bool = False,
    decided_at: str | None = None,
    storage_factory=None,
    runtime_factory=None,
) -> dict:
    from congress_shared.storage import connect_r2
    from docspec_client.client import NativeDatasets
    from viewer_publication.client import idle_evicting

    work = Path(work).resolve()
    if work.exists() or work.is_symlink():
        raise ValueError(f'body_text publish work directory must be fresh: {work}')
    work.mkdir(parents=True, exist_ok=False)

    publish_spec = json.loads(Path(publish_spec_path).read_text())
    daily_spec = json.loads(Path(daily_spec_path).read_text())
    definition = body_text_export.load_definition()
    bucket = definition['bucket']
    if publish_spec['bucket'] != bucket:
        raise ValueError('Body-text export bucket differs from publish.json bucket')
    public_origin = publish_spec['public_origin'].rstrip('/')

    inc_versions = body_text.portable_versions()
    accepted = body_text_selection.load(selection_path, {
        p: body_text.readings.current_version(p) for p in definition['parsers']
    })
    selection_sha256 = accepted['identity']['sha256']

    settings, remote, endpoint, _ = publication_configuration(engine_config, bucket=bucket)
    if runtime_factory is None:
        engine_dir = work / 'engine-runtime'
        engine_dir.mkdir(mode=0o700)
        limits_path = engine_dir / 'limits.json'
        limits_path.write_text(json.dumps(BODY_TEXT_ENGINE_LIMITS, indent=2) + '\n')
        bounded_cfg = engine_dir / 'runtime.json'
        bounded_cfg.write_text(json.dumps(dict(
            settings,
            limits=str(limits_path),
            workspace=str(engine_dir / 'workspace'),
            timeout_seconds=max(3600, int(settings.get('timeout_seconds', 3600))),
        ), indent=2) + '\n')
        effective_engine_config: str | Path = bounded_cfg
        runtime_factory = NativeDatasets.from_config
    else:
        effective_engine_config = engine_config
    storage_factory = idle_evicting(storage_factory or connect_r2)

    decided_at = decided_at or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    daily_tables = daily_spec['tables']

    with runtime_factory(effective_engine_config) as engine:
        engine.verify_runtime()
        read_client = configure_read_retries(
            storage_factory(bucket=bucket, endpoint_url=endpoint, retries={'total_max_attempts': 1})
        )
        write_client = configure_upload_part_retries(configure_read_retries(
            storage_factory(bucket=bucket, endpoint_url=endpoint, retries={'total_max_attempts': 1})
        ))
        raw_store = BodyStore(R2Adapter(write_client, bucket))

        apply_reviewed_rows(selection_path=selection_path, accepted=accepted, engine=engine,
                            work=work / 'reviewed-rows', tables=body_text_tables)
        source_heads = resolve_tables(
            engine=engine,
            work=work / 'source-heads',
            catalog_root=None,
            tables={
                'captures': daily_tables['captures'],
                'filename_readings': daily_tables['filename_readings'],
            },
        )

        producer_report = body_text.run(
            engine=engine,
            work=work / 'produce',
            captures=source_heads['captures'],
            filename_readings=source_heads['filename_readings'],
            sniff_table=daily_tables['readings'],
            tables=body_text_tables,
            catalog_root=None,
            origin=public_origin,
            decided_at=decided_at,
            execute=True,
            unreadable_store=raw_store,
            selection=selection_path,
            strategy=body_text.PORTABLE_STRATEGY,
            parser_workers=parser_workers,
            parser_memory_bytes=parser_workers * body_text.WORKER_MEMORY_BYTES,
            max_batches=max_batches,
        )
        ocr_pending = sum(b['ocr_pending'] for b in producer_report['batches'])
        pending_reads = sum(b['pending_reads'] for b in producer_report['batches'])
        if ocr_pending or pending_reads:
            raise RuntimeError(
                f"body_text incremental pass left unfinished reads "
                f"(ocr_pending={ocr_pending}, pending_reads={pending_reads}, "
                f"reasons={producer_report['pending_read_reasons']})"
            )
        if producer_report['status'] == 'partial':
            return dict(status='partial', producer=producer_report)

        post_heads = resolve_tables(
            engine=engine,
            work=work / 'post-heads',
            catalog_root=None,
            tables=body_text_tables,
        )
        unreadable_files = unreadable_inventory(raw_store, work=work / 'unreadable-final').files()

        release_id = resolve_target_release(
            read_client, bucket=bucket, release_id=release_id, prefer_staged=prefer_staged,
        )
        release_manifest, _ = _get_json(
            read_client,
            bucket=bucket,
            key=f'viewer-publications/releases/{release_id}/manifest.json',
        )
        detail_entry = next(f for f in release_manifest['files'] if f['name'] == 'detail.parquet')

        target_pointer_key = STAGED_POINTER_KEY if stage_only else definition['pointer']
        current_bt_pointer, expected_etag = _read_optional_pointer(
            write_client, bucket=bucket, key=target_pointer_key
        )
        if _export_is_current(
            read_client,
            bucket=bucket,
            current_pointer=current_bt_pointer,
            release_id=release_id,
            detail_pin=detail_entry,
            body_text_pin=post_heads['body_text'],
            selection_sha256=selection_sha256,
            incremental_versions=inc_versions,
        ):
            summary = dict(
                status='already_current',
                release_id=release_id,
                pointer=current_bt_pointer,
                pointer_key=target_pointer_key,
                producer=dict(
                    work_items=producer_report['work_items'],
                    applied=producer_report['applied'],
                    batches=len(producer_report['batches']),
                ),
            )
            durable_json(work / 'summary.json', summary)
            return summary

        if stage_only:
            live_bt_pointer, _ = _read_optional_pointer(
                read_client, bucket=bucket, key=definition['pointer']
            )
            if _export_is_current(
                read_client,
                bucket=bucket,
                current_pointer=live_bt_pointer,
                release_id=release_id,
                detail_pin=detail_entry,
                body_text_pin=post_heads['body_text'],
                selection_sha256=selection_sha256,
                incremental_versions=inc_versions,
            ):
                from viewer_publication.client import publish_manifest_pointer
                staged_transfer = publish_manifest_pointer(
                    write_client, bucket=bucket, pointer=live_bt_pointer,
                    key=STAGED_POINTER_KEY, expected_etag=expected_etag,
                )
                summary = dict(
                    status='staged',
                    release_id=release_id,
                    pointer=live_bt_pointer,
                    pointer_key=STAGED_POINTER_KEY,
                    published=dict(export='already_exists', pointer_etag=staged_transfer.etag, retired=[]),
                    producer=dict(
                        work_items=producer_report['work_items'],
                        applied=producer_report['applied'],
                        batches=len(producer_report['batches']),
                    ),
                )
                durable_json(work / 'summary.json', summary)
                return summary

        detail_path = _ensure_detail_parquet(
            read_client,
            bucket=bucket,
            release_id=release_id,
            detail_entry=detail_entry,
            work=work,
            release_dir=release_dir,
        )

        export_work = work / 'export'
        pointer = body_text_export.export(
            engine=engine,
            work=export_work,
            body_text=post_heads['body_text'],
            readings_table=post_heads['readings'],
            unreadable_files=unreadable_files,
            detail=detail_path,
            definition=definition,
            release_id=release_id,
            selection=selection_path,
            incremental_versions=inc_versions,
        )
        verify_ssot_export(export_work, require_pointer=True, verify_file_sha256=False)

        published = body_text_export.publish(
            write_client,
            bucket=bucket,
            export_path=export_work / 'export.parquet',
            pointer=pointer,
            expected_pointer_etag=expected_etag,
            journal=lambda stage: durable_json(export_work / 'upload-journal.json', stage),
            pointer_key=target_pointer_key,
            retire=not stage_only,
        )
        if not keep_export:
            (export_work / 'export.parquet').unlink(missing_ok=True)

        summary = dict(
            status='staged' if stage_only else 'published',
            release_id=release_id,
            pointer=pointer,
            pointer_key=target_pointer_key,
            published=dict(
                export=published['export'],
                pointer_etag=published['pointer'].etag,
                retired=published['retired'],
            ),
            producer=dict(
                work_items=producer_report['work_items'],
                applied=producer_report['applied'],
                batches=len(producer_report['batches']),
                by_parser=producer_report['by_parser'],
            ),
        )
        durable_json(work / 'summary.json', summary)
        return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path)
    parser.add_argument('--engine-config', default=os.environ.get('DOCSPEC_RUNTIME_CONFIG'))
    parser.add_argument('--selection', type=Path, default=DEFAULT_SELECTION)
    parser.add_argument('--daily-spec', type=Path, default=DEFAULT_DAILY_SPEC)
    parser.add_argument('--publish-spec', type=Path, default=DEFAULT_PUBLISH_SPEC)
    parser.add_argument('--release-dir', type=Path)
    parser.add_argument('--release-id')
    parser.add_argument('--prefer-staged', action='store_true')
    parser.add_argument('--stage-only', action='store_true')
    parser.add_argument('--promote-release', help='Promote derived/body_text/staged.json to current.json for this release_id')
    parser.add_argument('--parser-workers', type=int, default=3)
    parser.add_argument('--max-batches', type=int)
    parser.add_argument('--keep-export', action='store_true')
    parser.add_argument('--decided-at')
    args = parser.parse_args(argv)
    if args.promote_release:
        from congress_shared.storage import connect_r2
        from congress_api.retention.r2 import configure_read_retries
        definition = body_text_export.load_definition()
        bucket = definition['bucket']
        client = configure_read_retries(connect_r2(bucket=bucket, connect_timeout=15, read_timeout=180,
                                                   retries={'total_max_attempts': 1}))
        result = promote_staged_body_text(client, bucket=bucket, release_id=args.promote_release, definition=definition)
        print(json.dumps(result, default=str, sort_keys=True))
        return 0
    if not args.work:
        parser.error('--work is required unless --promote-release is specified')
    if not args.engine_config:
        parser.error('An explicit remote DocSpec runtime (--engine-config or DOCSPEC_RUNTIME_CONFIG) is required')
    result = sync_and_publish(
        work=args.work,
        engine_config=args.engine_config,
        selection_path=args.selection,
        daily_spec_path=args.daily_spec,
        publish_spec_path=args.publish_spec,
        release_dir=args.release_dir,
        release_id=args.release_id,
        prefer_staged=args.prefer_staged,
        stage_only=args.stage_only,
        parser_workers=args.parser_workers,
        max_batches=args.max_batches,
        keep_export=args.keep_export,
        decided_at=args.decided_at,
    )
    print(json.dumps(result, default=str, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
