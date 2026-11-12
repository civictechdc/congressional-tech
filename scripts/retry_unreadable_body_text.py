#!/usr/bin/env python3
"""Supersede wrong body_text unreadable decisions (ct-a73a) and re-read ONLY those bodies at 2 GiB.

In --dry-run mode, reads unreadable-store, catalog, and captures-all.parquet strictly READ-ONLY,
validates every withdrawal record against congress_api.retention.provenance.validate_provenance,
builds a target-only captures Parquet in --work-dir, and runs body_text.plan() before and after
the staged withdrawals to prove:
  - 0 of the targeted bodies are on the work list before withdrawal, and
  - 100% of the targeted bodies re-enter the work list after withdrawal.

In --apply mode (run ONLY after bt_full_driver.py and other writers finish):
  1. Refuses if bt_full_driver.py, congress_api.cli.body_text, or nightly_publish.py is running
     (unless --allow-concurrent is explicitly passed).
  2. Persists targeted body_sha256 records to a durable manifest (target-manifest.json or
     --manifest) BEFORE importing any withdrawals so re-runs after transient pending_reads or
     crashes are 100% idempotent.
  3. Imports withdrawals ONLY for manifest decisions not yet superseded (skipping import cleanly
     when empty on resume), plans over unsettled manifest targets (with optional --body-listing),
     executes body_text.stage() + body_text.append() at WORKER_MEMORY_BYTES = 2 GiB, and emits
     a per-body outcomes table with status, reading_status, reason, error, and peak_rss_bytes.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any

import duckdb

DEFAULT_FULL_DIR = Path('/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/body-text-full-20261110')
DEFAULT_SLICE_DIR = Path('/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/body-text-slice-20261109')
DEFAULT_UNREADABLE_ROOT = DEFAULT_SLICE_DIR / 'unreadable-store'
DEFAULT_CATALOG_ROOT = DEFAULT_SLICE_DIR / 'catalog'
DEFAULT_CAPTURES = DEFAULT_FULL_DIR / 'inputs' / 'captures-all.parquet'
DEFAULT_FILENAME_READINGS = DEFAULT_SLICE_DIR / 'inputs' / 'filename-readings.parquet'
DEFAULT_REASONS = ('page_deadline', 'memory_limit')
LIVE_WRITER_PATTERN = r'bt_full_driver\.py|congress_api\.cli\.body_text|nightly_publish\.py'


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write('\n')
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _next_attempt_dir(work: Path, *, prefix: str) -> Path:
    work.mkdir(parents=True, exist_ok=True)
    idx = 1
    while True:
        candidate = work / f'{prefix}-{idx:04d}'
        if not candidate.exists():
            candidate.mkdir(parents=True, exist_ok=False)
            return candidate
        idx += 1


def check_no_live_writers() -> None:
    proc = subprocess.run(['pgrep', '-fl', LIVE_WRITER_PATTERN], capture_output=True, text=True, check=False)
    self_pid = os.getpid()
    lines = []
    for raw in proc.stdout.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        first = stripped.split(None, 1)[0]
        if first.isdigit() and int(first) == self_pid:
            continue
        lines.append(stripped)
    if lines:
        raise RuntimeError(
            'Refusing --apply while a live writer is running (pass --allow-concurrent to override):\n  '
            + '\n  '.join(lines)
        )


def _clean_record(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if not k.startswith('_')}


def scan_unreadable_store(unreadable_root: Path) -> dict[str, Any]:
    from congress_api.retention.provenance import active_unreadable_rows

    unr_dir = unreadable_root / 'provenance' / 'unreadable'
    files = sorted(unr_dir.glob('*.jsonl')) if unr_dir.exists() else []
    records: list[dict[str, Any]] = []
    for path in files:
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.strip():
                records.append({**json.loads(line), '_file': str(path), '_key': f'provenance/unreadable/{path.name}'})
    superseded_ids = {r['supersedes'] for r in records if r.get('supersedes')}
    active = active_unreadable_rows(records)
    active_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in sorted(active, key=lambda r: (r.get('decided_at') or '', r.get('id') or '')):
        if row.get('body_sha256'):
            active_by_key[(row['body_sha256'], row['parser'], row['parser_version'])] = row
    return {
        'files': [dict(key=f'provenance/unreadable/{p.name}', path=str(p)) for p in files],
        'total_records': len(records),
        'superseded_ids': superseded_ids,
        'active_records': active,
        'active_by_key': active_by_key,
    }


def build_withdrawals(targets: list[dict[str, Any]], *, decided_at: str, decided_by: str = 'ct-a73a') -> list[dict[str, Any]]:
    from congress_api.retention.provenance import validate_provenance

    rows = []
    for item in targets:
        identity = json.dumps(
            ['withdraw', item['id'], item['body_sha256'], item['parser'], item['parser_version'], decided_at],
            separators=(',', ':'),
        )
        row = dict(
            id=sha256(identity.encode()).hexdigest(),
            body_sha256=item['body_sha256'],
            parser=item['parser'],
            parser_version=item['parser_version'],
            reason='withdrawn',
            decided_by=decided_by,
            decided_at=decided_at,
            supersedes=item['id'],
        )
        validate_provenance('unreadable', row)
        rows.append(row)
    return rows


def filter_captures_for_targets(captures_path: Path, target_hexes: list[str], out_path: Path) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f'.{out_path.name}.', suffix='.parquet', dir=out_path.parent)
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        con = duckdb.connect()
        try:
            con.execute("SET memory_limit = '1GB'; SET threads = 2;")
            con.execute('CREATE TEMP TABLE target_shas (sha BLOB)')
            if target_hexes:
                con.executemany('INSERT INTO target_shas VALUES (from_hex(?))', [(h,) for h in sorted(set(target_hexes))])
            escaped_in = str(captures_path).replace("'", "''")
            escaped_out = str(tmp_path).replace("'", "''")
            con.execute(
                f"""
                COPY (
                    SELECT c.*
                    FROM read_parquet('{escaped_in}') c
                    SEMI JOIN target_shas t ON c.sha256 = t.sha
                ) TO '{escaped_out}' (FORMAT PARQUET, COMPRESSION ZSTD)
                """
            )
            count = con.execute(f"SELECT count(*) FROM read_parquet('{escaped_out}')").fetchone()[0]
        finally:
            con.close()
        os.replace(tmp_path, out_path)
        return count
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def select_target_work_items(work_list_path: Path, target_bytes: set[bytes]) -> list[dict[str, Any]]:
    from congress_api.retention.provenance import parquet_records

    return [item for item in parquet_records(work_list_path) if item['body_sha'] in target_bytes]


def query_target_readings(
    engine: Any,
    work_dir: Path,
    readings_pin: dict[str, Any],
    manifest_targets: list[dict[str, Any]],
) -> dict[tuple[str, str, str], dict[str, Any]]:
    if not manifest_targets:
        return {}
    from congress_api.lake.tables import table_input
    from congress_api.retention.provenance import json_input, run_job

    work_dir.mkdir(parents=True, exist_ok=False)
    target_rows = [
        dict(body_sha256=t['body_sha256'], parser=t['parser'], parser_version=t['parser_version'])
        for t in manifest_targets
    ]
    rows = run_job(
        work_dir,
        engine,
        inputs=[
            table_input('readings', readings_pin),
            json_input(work_dir, 'targets', target_rows, body_sha256='Utf8', parser='Utf8', parser_version='Utf8'),
        ],
        steps=[],
        outputs=[],
        queries=[
            dict(
                name='settled',
                sql="""
                    SELECT t.body_sha256, t.parser, t.parser_version, r.status, r.error_type
                    FROM targets t
                    JOIN readings r
                      ON r.body_sha = decode(t.body_sha256, 'hex')
                     AND r.parser = t.parser
                     AND r.parser_version = t.parser_version
                """,
            )
        ],
    )['settled']
    return {(r['body_sha256'], r['parser'], r['parser_version']): r for r in rows}


def build_final_outcomes(
    manifest_targets: list[dict[str, Any]],
    ledger: dict[str, dict[str, Any]],
    settled_readings: dict[tuple[str, str, str], dict[str, Any]],
    active_by_key: dict[tuple[str, str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    outcomes: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str]] = set()
    for target in sorted(manifest_targets, key=lambda t: (t['body_sha256'], t['parser'], t['parser_version'])):
        key = (target['body_sha256'], target['parser'], target['parser_version'])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        ledger_key = f"{target['body_sha256']}:{target['parser']}:{target['parser_version']}"
        recorded = ledger.get(ledger_key, {})
        peak_rss = recorded.get('peak_rss_bytes')
        if key in settled_readings:
            row = settled_readings[key]
            outcomes.append(
                dict(
                    body_sha256=target['body_sha256'],
                    parser=target['parser'],
                    parser_version=target['parser_version'],
                    original_reason=target.get('reason'),
                    status='read',
                    reading_status=row['status'],
                    reason=recorded.get('reason') or row.get('error_type'),
                    error=recorded.get('error') or row.get('error_type'),
                    peak_rss_bytes=peak_rss,
                )
            )
        elif key in active_by_key and active_by_key[key]['id'] != target['id']:
            unr = active_by_key[key]
            outcomes.append(
                dict(
                    body_sha256=target['body_sha256'],
                    parser=target['parser'],
                    parser_version=target['parser_version'],
                    original_reason=target.get('reason'),
                    status='unreadable',
                    reading_status=None,
                    reason=unr['reason'],
                    error=recorded.get('error') or unr['reason'],
                    peak_rss_bytes=peak_rss,
                )
            )
        else:
            outcomes.append(
                dict(
                    body_sha256=target['body_sha256'],
                    parser=target['parser'],
                    parser_version=target['parser_version'],
                    original_reason=target.get('reason'),
                    status='pending',
                    reading_status=None,
                    reason=recorded.get('reason'),
                    error=recorded.get('error'),
                    peak_rss_bytes=peak_rss,
                )
            )
    return outcomes


def main(argv: list[str] | None = None) -> int:
    from docspec_client.client import NativeDatasets
    from congress_api.lake import body_text
    from congress_api.lake.tables import resolve_tables, validate_catalog_authority
    from congress_api.parsers.body_text import VISION_STRATEGY
    from congress_api.retention.body_store import BodyStore, LocalAdapter
    from congress_api.retention.provenance import import_unreadable
    from congress_api.retention.provenance_inventory import unreadable_inventory

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run', action='store_true', help='Verify inventory, withdrawals, and reopened plan read-only')
    mode.add_argument('--apply', action='store_true', help='Import withdrawals and re-read targeted bodies at 2 GiB')
    ap.add_argument('--unreadable-root', type=Path, default=DEFAULT_UNREADABLE_ROOT)
    ap.add_argument('--catalog-root', type=Path, default=DEFAULT_CATALOG_ROOT)
    ap.add_argument('--captures', type=Path, default=DEFAULT_CAPTURES)
    ap.add_argument('--filename-readings', type=Path, default=None)
    ap.add_argument('--local-root', type=Path, default=None, help='Local raw body root (mutually exclusive with --origin)')
    ap.add_argument('--origin', default=None, help=f'Remote raw origin URL (default when --local-root omitted: {body_text.ORIGIN})')
    ap.add_argument('--body-listing', type=Path, default=None,
                    help='Optional R2 bucket listing Parquet (ct-jnjv) for MD5-less remote copies')
    ap.add_argument('--strategy', default=VISION_STRATEGY,
                    help='Page extraction strategy spec (default: Apple Vision OCR)')
    ap.add_argument('--manifest', type=Path, default=None,
                    help='Durable target manifest path (default: <work-dir>/target-manifest.json)')
    ap.add_argument('--allow-concurrent', action='store_true',
                    help='Bypass live-writer preflight check in --apply mode')
    ap.add_argument('--work-dir', type=Path, required=True, help='Working directory (preserved across --apply resumes)')
    ap.add_argument('--reasons', default=','.join(DEFAULT_REASONS),
                    help='Comma-separated unreadable reasons to supersede (default: page_deadline,memory_limit)')
    ap.add_argument('--workers', type=int, default=4, help='Worker count for --apply (default: 4)')
    ap.add_argument('--parser-memory-bytes', type=int, default=body_text.PARSER_MEMORY_BYTES)
    ap.add_argument('--decided-at', default=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
    ap.add_argument('--engine-config', default=os.environ.get('DOCSPEC_JOB_CONFIG'))
    args = ap.parse_args(argv)

    if not args.engine_config:
        ap.error('DOCSPEC_JOB_CONFIG or --engine-config is required')
    if args.local_root is not None and args.origin is not None:
        ap.error('--local-root and --origin are mutually exclusive')
    if args.local_root is not None and args.body_listing is not None:
        ap.error('--body-listing applies to remote --origin reads, not --local-root')
    assert body_text.WORKER_MEMORY_BYTES == 2 << 30, (
        f'Expected WORKER_MEMORY_BYTES == 2 GiB, got {body_text.WORKER_MEMORY_BYTES}'
    )

    if args.apply and not args.allow_concurrent:
        check_no_live_writers()

    local_root = args.local_root.resolve() if args.local_root is not None else None
    origin = None if local_root is not None else (args.origin or body_text.ORIGIN)
    body_listing = args.body_listing.resolve() if args.body_listing is not None else None
    unreadable_root = args.unreadable_root.resolve()
    catalog_root = args.catalog_root.resolve()
    captures_path = args.captures.resolve()

    if args.filename_readings is not None:
        filename_readings: Path | None = args.filename_readings.resolve()
    elif args.unreadable_root == DEFAULT_UNREADABLE_ROOT and DEFAULT_FILENAME_READINGS.is_file():
        filename_readings = DEFAULT_FILENAME_READINGS.resolve()
    else:
        filename_readings = None

    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    manifest_path = (args.manifest or (work / 'target-manifest.json')).resolve()

    reasons = tuple(r.strip() for r in args.reasons.split(',') if r.strip())
    scanned = scan_unreadable_store(unreadable_root)
    tables = {
        'readings': {'namespace': ['archive'], 'name': 'readings'},
        'body_text': {'namespace': ['archive'], 'name': 'body_text'},
    }

    if args.dry_run:
        attempt_dir = _next_attempt_dir(work, prefix='dry-run')
        if args.manifest is not None and manifest_path.is_file():
            targets = json.loads(manifest_path.read_text(encoding='utf-8'))['targets']
        else:
            targets = [_clean_record(r) for r in scanned['active_records'] if r.get('reason') in reasons]
        target_hexes = sorted({t['body_sha256'] for t in targets})
        target_bytes = {bytes.fromhex(h) for h in target_hexes}
        withdrawals = build_withdrawals(targets, decided_at=args.decided_at)
        withdraw_jsonl = attempt_dir / 'withdrawals.jsonl'
        withdraw_jsonl.write_text(''.join(json.dumps(r, separators=(',', ':')) + '\n' for r in withdrawals), encoding='utf-8')
        target_captures = attempt_dir / 'target-captures.parquet'
        capture_rows = filter_captures_for_targets(captures_path, target_hexes, target_captures)

        with NativeDatasets.from_config(args.engine_config) as engine:
            validate_catalog_authority(engine, catalog_root)
            current_readings = resolve_tables(
                engine=engine,
                work=attempt_dir / 'resolve-readings',
                catalog_root=catalog_root,
                tables={'readings': tables['readings']},
            )['readings']
            before = body_text.plan(
                captures=target_captures,
                engine=engine,
                work=attempt_dir / 'plan-before-withdraw',
                decided_at=args.decided_at,
                local_root=local_root,
                existing=current_readings,
                unreadable_files=scanned['files'],
                filename_readings=filename_readings,
                body_listing=body_listing,
            )
            after_files = (
                [*scanned['files'], dict(key='provenance/unreadable/staged-withdrawals.jsonl', path=str(withdraw_jsonl))]
                if withdrawals
                else list(scanned['files'])
            )
            after = body_text.plan(
                captures=target_captures,
                engine=engine,
                work=attempt_dir / 'plan-after-withdraw',
                decided_at=args.decided_at,
                local_root=local_root,
                existing=current_readings,
                unreadable_files=after_files,
                filename_readings=filename_readings,
                body_listing=body_listing,
            )
            before_targets = select_target_work_items(before['work_list'], target_bytes)
            after_targets = select_target_work_items(after['work_list'], target_bytes)
            assert len(before_targets) == 0, f'Expected 0 targeted items before withdrawal, got {len(before_targets)}'
            assert len(after_targets) == len(target_hexes), (
                f'Expected {len(target_hexes)} targeted items after withdrawal, got {len(after_targets)}'
            )
            assert all(i['physical_key'] is not None for i in after_targets)
            if origin is not None:
                assert all(i['stored_bytes'] is not None for i in after_targets)
            summary = {
                'mode': 'dry-run',
                'worker_memory_bytes': body_text.WORKER_MEMORY_BYTES,
                'parser_memory_bytes': args.parser_memory_bytes,
                'unreadable_total_records': scanned['total_records'],
                'unreadable_active_records': len(scanned['active_records']),
                'targeted_decisions': len(targets),
                'targeted_distinct_bodies': len(target_hexes),
                'targeted_by_reason': {
                    r: sum(1 for t in targets if t['reason'] == r) for r in reasons
                },
                'filtered_capture_rows': capture_rows,
                'targeted_work_items_before_withdraw': len(before_targets),
                'targeted_work_items_after_withdraw': len(after_targets),
                'targeted_stored_bytes': sum(i['stored_bytes'] or 0 for i in after_targets),
                'global_work_items_delta': after['work_items'] - before['work_items'],
                'withdrawals_staged_jsonl': str(withdraw_jsonl),
            }
            _write_json_atomic(work / 'dry-run-summary.json', summary)
            print(json.dumps(summary, indent=2, sort_keys=True))
            return 0

    # --apply mode: persist manifest BEFORE mutating unreadable-store so resumes stay idempotent.
    if manifest_path.is_file():
        manifest_data = json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest_targets: list[dict[str, Any]] = manifest_data['targets']
    else:
        manifest_targets = sorted(
            [_clean_record(r) for r in scanned['active_records'] if r.get('reason') in reasons],
            key=lambda r: (r['body_sha256'], r['parser'], r['parser_version'], r['id']),
        )
        _write_json_atomic(
            manifest_path,
            {
                'version': 1,
                'created_at': args.decided_at,
                'reasons': list(reasons),
                'targets': manifest_targets,
            },
        )

    attempt_dir = _next_attempt_dir(work, prefix='apply')
    target_hexes = sorted({t['body_sha256'] for t in manifest_targets})
    target_bytes = {bytes.fromhex(h) for h in target_hexes}

    target_captures = work / 'target-captures.parquet'
    if not target_captures.is_file():
        filter_captures_for_targets(captures_path, target_hexes, target_captures)

    active_ids = {r['id'] for r in scanned['active_records']}
    pending_withdraw_targets = [
        t for t in manifest_targets if t['id'] in active_ids and t['id'] not in scanned['superseded_ids']
    ]
    store = BodyStore(LocalAdapter(unreadable_root))
    if pending_withdraw_targets:
        withdrawals = build_withdrawals(pending_withdraw_targets, decided_at=args.decided_at)
        withdraw_jsonl = attempt_dir / 'withdrawals.jsonl'
        withdraw_jsonl.write_text(
            ''.join(json.dumps(r, separators=(',', ':')) + '\n' for r in withdrawals),
            encoding='utf-8',
        )
        imported = import_unreadable(store, withdraw_jsonl, decided_at=args.decided_at)
        withdrawal_key: str | None = imported['key']
        withdrawn_count = len(withdrawals)
    else:
        withdrawal_key = None
        withdrawn_count = 0

    ledger_path = work / 'outcomes-ledger.json'
    ledger: dict[str, dict[str, Any]] = (
        json.loads(ledger_path.read_text(encoding='utf-8')) if ledger_path.is_file() else {}
    )

    with NativeDatasets.from_config(args.engine_config) as engine:
        validate_catalog_authority(engine, catalog_root)
        current_readings = resolve_tables(
            engine=engine,
            work=attempt_dir / 'resolve-before',
            catalog_root=catalog_root,
            tables={'readings': tables['readings']},
        )['readings']
        inv_files = unreadable_inventory(store, work=attempt_dir / 'unreadable-inventory').files()
        planned = body_text.plan(
            captures=target_captures,
            engine=engine,
            work=attempt_dir / 'plan',
            decided_at=args.decided_at,
            local_root=local_root,
            existing=current_readings,
            unreadable_files=inv_files,
            filename_readings=filename_readings,
            body_listing=body_listing,
        )
        target_items = select_target_work_items(planned['work_list'], target_bytes)
        batches_summary = []
        applied = False
        for number, batch_items in enumerate(body_text.batches(iter(target_items))):
            batch_work = attempt_dir / f'batch-{number:06d}'
            staged = body_text.stage(
                planned,
                batch_items,
                engine=engine,
                work=batch_work / 'stage',
                unreadable_store=store,
                parser_workers=args.workers,
                parser_memory_bytes=args.parser_memory_bytes,
                strategy=args.strategy,
                origin=origin,
            )
            appended = body_text.append(
                staged,
                engine=engine,
                work=batch_work,
                catalog_root=catalog_root,
                tables=tables,
            )
            applied |= any(v is not None for v in appended.values())
            staged['body_text'].unlink()
            for outcome in staged['body_outcomes']:
                ledger_key = f"{outcome['body_sha256']}:{outcome['parser']}:{outcome['parser_version']}"
                ledger[ledger_key] = outcome
            _write_json_atomic(ledger_path, ledger)
            batches_summary.append({
                'work_items': staged['work_items'],
                'readings_rows': staged['readings_rows'],
                'body_text_rows': staged['body_text_rows'],
                'unreadable': staged['unreadable'],
                'unreadable_key': staged['unreadable_key'],
                'pending_reads': staged['pending_reads'],
                'ocr_pages': staged['ocr_pages'],
            })

        final_readings = resolve_tables(
            engine=engine,
            work=attempt_dir / 'resolve-after',
            catalog_root=catalog_root,
            tables={'readings': tables['readings']},
        )['readings']
        settled_readings = query_target_readings(
            engine,
            attempt_dir / 'settled-check',
            final_readings,
            manifest_targets,
        )

    final_scanned = scan_unreadable_store(unreadable_root)
    outcomes = build_final_outcomes(
        manifest_targets,
        ledger,
        settled_readings,
        final_scanned['active_by_key'],
    )
    summary = {
        'mode': 'apply',
        'manifest_path': str(manifest_path),
        'withdrawal_key': withdrawal_key,
        'withdrawn_count': withdrawn_count,
        'targeted_distinct_bodies': len(target_hexes),
        'reopened_target_work_items': len(target_items),
        'worker_memory_bytes': body_text.WORKER_MEMORY_BYTES,
        'applied': applied,
        'settled_readings': sum(1 for o in outcomes if o['status'] == 'read'),
        'settled_unreadable': sum(1 for o in outcomes if o['status'] == 'unreadable'),
        'pending_bodies': sum(1 for o in outcomes if o['status'] == 'pending'),
        'outcomes': outcomes,
        'batches': batches_summary,
    }
    _write_json_atomic(work / 'apply-summary.json', summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
