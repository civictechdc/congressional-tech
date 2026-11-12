#!/usr/bin/env python3
"""Withdraw wrong page_deadline/memory_limit decisions and retry those bodies (ct-a73a)."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

import duckdb
from docspec_client import NativeDatasets
from congress_api.lake import body_text, tables
from congress_api.retention.body_store import BodyStore, LocalAdapter
from congress_api.retention.provenance import active_unreadable_rows, import_unreadable, instant, parquet_records, validate_provenance
from congress_api.retention.provenance_inventory import unreadable_inventory
from congress_api.retention.r2_edge_rules import PUBLIC_HOSTNAME

DEFAULT_SLICE = Path('/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/body-text-slice-20261109')
DEFAULT_CAPTURES = Path('/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/body-text-full-20261110/inputs/captures-all.parquet')
DEFAULT_STRATEGY = 'congress_api.parsers.body_text:apple_vision'
LIVE_WRITERS_PATTERN = r'bt_full_driver\.py|congress_api\.cli\.body_text|nightly_publish\.py'


def _load_unreadable(unr_dir: Path) -> list[dict]:
    rows = [json.loads(ln) for f in sorted(unr_dir.glob('*.jsonl'))
            for ln in f.read_text().splitlines() if ln.strip()]
    for r in rows:
        validate_provenance('unreadable', r)
    return rows


def _withdraw_record(rec: dict, decided_at: str, decided_by: str) -> dict:
    ident = json.dumps(['withdrawn', rec['id'], rec['body_sha256'], rec['parser'], rec['parser_version'], decided_at],
                       separators=(',', ':'))
    out = dict(id=sha256(ident.encode()).hexdigest(), body_sha256=rec['body_sha256'], parser=rec['parser'],
               parser_version=rec['parser_version'], reason='withdrawn', decided_by=decided_by,
               decided_at=decided_at, supersedes=rec['id'])
    validate_provenance('unreadable', out)
    return out


def _filter_captures(captures: Path, shas: set[str], out_parquet: Path) -> int:
    src = captures.as_posix().replace("'", "''")
    dst = out_parquet.as_posix().replace("'", "''")
    with duckdb.connect() as con:
        con.execute("SET memory_limit='1GB'; SET threads=2")
        con.execute('CREATE TEMP TABLE target_shas (sha_hex VARCHAR)')
        con.executemany('INSERT INTO target_shas VALUES (?)', [(s,) for s in sorted(shas)])
        con.execute(f"COPY (SELECT c.* FROM read_parquet('{src}') c JOIN target_shas t "
                    f"ON lower(hex(c.sha256)) = t.sha_hex) TO '{dst}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        return int(con.execute(f"SELECT count(*) FROM read_parquet('{dst}')").fetchone()[0])

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--apply', action='store_true')
    ap.add_argument('--unreadable-root', type=Path, default=DEFAULT_SLICE / 'unreadable-store')
    ap.add_argument('--catalog-root', type=Path, default=DEFAULT_SLICE / 'catalog')
    ap.add_argument('--captures', type=Path, default=DEFAULT_CAPTURES)
    ap.add_argument('--local-root', type=Path)
    ap.add_argument('--origin', default=f'https://{PUBLIC_HOSTNAME}')
    ap.add_argument('--body-listing', type=Path)
    ap.add_argument('--reasons', default='page_deadline,memory_limit')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--decided-by', default='ct-a73a-retry')
    ap.add_argument('--decided-at')
    ap.add_argument('--strategy', default=DEFAULT_STRATEGY)
    ap.add_argument('--allow-concurrent', action='store_true')
    ap.add_argument('--work-dir', type=Path, required=True)
    args = ap.parse_args(argv)

    if args.apply and not args.allow_concurrent:
        proc = subprocess.run(['pgrep', '-fl', LIVE_WRITERS_PATTERN], capture_output=True, text=True, check=False)
        if hits := [ln.strip() for ln in (proc.stdout or '').splitlines() if ln.strip() and __file__ not in ln]:
            raise RuntimeError('Refusing --apply while a live writer is running:\n  ' + '\n  '.join(hits))

    reasons = {r.strip() for r in args.reasons.split(',') if r.strip()}
    decided_at = args.decided_at or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    instant(decided_at)
    work_dir = args.work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    unr_dir = args.unreadable_root / 'provenance' / 'unreadable'
    all_rows = _load_unreadable(unr_dir)
    active = active_unreadable_rows(all_rows)
    withdrawn_shas = {r['body_sha256'] for r in all_rows
                      if r.get('reason') == 'withdrawn' and r.get('decided_by') == args.decided_by and r.get('body_sha256')}
    to_withdraw = [r for r in active if r.get('reason') in reasons and r.get('body_sha256') and r['body_sha256'] not in withdrawn_shas]
    target_shas = {r['body_sha256'] for r in to_withdraw} | withdrawn_shas
    if not target_shas:
        raise SystemExit(f'No target decisions found for reasons={sorted(reasons)}')

    local_root = args.local_root.resolve() if args.local_root else None
    origin, listing = (None if local_root else args.origin), (args.body_listing.resolve() if (args.body_listing and not local_root) else None)
    table_ids = {n: {'namespace': ['archive'], 'name': n} for n in ('readings', 'body_text')}
    cfg = os.environ.get('DOCSPEC_JOB_CONFIG')

    with (NativeDatasets.from_config(cfg) if cfg else NativeDatasets()) as engine, TemporaryDirectory(dir=work_dir, prefix='run-') as scratch_raw:
        scratch = Path(scratch_raw)
        filtered, staged_jsonl = scratch / 'captures-target.parquet', scratch / 'withdrawals.jsonl'
        capture_rows = _filter_captures(args.captures, target_shas, filtered)
        withdrawals = [_withdraw_record(r, decided_at, args.decided_by) for r in to_withdraw]
        staged_jsonl.write_text(''.join(json.dumps(w, separators=(',', ':')) + '\n' for w in withdrawals))

        store = BodyStore(LocalAdapter(args.unreadable_root))
        target_items = lambda p: [r for r in parquet_records(p['work_list']) if r['body_sha'].hex() in target_shas]
        if args.dry_run:
            unr_files = unreadable_inventory(store, work=scratch / 'inv').files()
            current = tables.resolve_tables(engine=engine, work=scratch / 'current', catalog_root=args.catalog_root,
                                            tables={'readings': table_ids['readings']})['readings']
            before = body_text.plan(captures=filtered, engine=engine, work=scratch / 'before', decided_at=decided_at,
                                    local_root=local_root, existing=current, unreadable_files=unr_files, body_listing=listing)
            after_files = unr_files + ([dict(key='provenance/unreadable/staged.jsonl', path=str(staged_jsonl))] if withdrawals else [])
            after = body_text.plan(captures=filtered, engine=engine, work=scratch / 'after', decided_at=decided_at,
                                   local_root=local_root, existing=current, unreadable_files=after_files, body_listing=listing)
            summary = dict(mode='dry-run', unreadable_total_records=len(all_rows), unreadable_active_records=len(active),
                targeted_decisions=len(to_withdraw), targeted_distinct_bodies=len(target_shas),
                targeted_by_reason=dict(sorted(Counter(r['reason'] for r in to_withdraw).items())),
                filtered_capture_rows=capture_rows, global_work_items_delta=after['work_items'] - before['work_items'],
                targeted_work_items_before_withdraw=len(target_items(before)),
                targeted_work_items_after_withdraw=len(target_items(after)),
                worker_memory_bytes=body_text.WORKER_MEMORY_BYTES, parser_memory_bytes=body_text.PARSER_MEMORY_BYTES)
            (work_dir / 'dry-run-summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n')
            print(json.dumps(summary, indent=2, sort_keys=True))
            return 0

        imported = import_unreadable(store, staged_jsonl, decided_at=decided_at) if withdrawals else None
        unr_files = unreadable_inventory(store, work=scratch / 'inv').files()
        current = tables.resolve_tables(engine=engine, work=scratch / 'current', catalog_root=args.catalog_root,
                                        tables={'readings': table_ids['readings']})['readings']
        planned = body_text.plan(captures=filtered, engine=engine, work=scratch / 'plan', decided_at=decided_at,
                                 local_root=local_root, existing=current, unreadable_files=unr_files, body_listing=listing)
        items = target_items(planned)
        prior_path = work_dir / 'apply-summary.json'
        outcomes = ({o['body_sha256']: o for o in json.loads(prior_path.read_text()).get('outcomes', [])} if prior_path.is_file() else {})
        staged = None
        if items:
            staged = body_text.stage(planned, items, engine=engine, work=scratch / 'stage', unreadable_store=store,
                                     parser_workers=args.workers, strategy=args.strategy, origin=origin)
            body_text.append(staged, engine=engine, work=scratch / 'commit', catalog_root=args.catalog_root, tables=table_ids)
            staged['body_text'].unlink(missing_ok=True)
            for row in staged.get('body_outcomes', ()):
                outcomes[row['body_sha256']] = row
        active_after = {r['body_sha256'] for r in active_unreadable_rows(_load_unreadable(unr_dir))}
        for s in target_shas:
            outcomes.setdefault(s, dict(body_sha256=s, status=('unreadable' if s in active_after else 'read'), reason=None, error=None, peak_rss_bytes=None))
        summary = dict(mode='apply', withdrawn_count=len(withdrawals), imported_withdrawal=imported,
                       planned_work_items=len(items), pending_reads=(staged['pending_reads'] if staged else 0),
                       outcomes=[outcomes[s] for s in sorted(outcomes)])
        prior_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n')
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

if __name__ == '__main__':
    raise SystemExit(main())
