#!/usr/bin/env python3
"""Retry a frozen body-text failure inventory with explicit recovery versions.

Inputs are targets.json, captures-target.parquet, and baseline.json in --work-dir.
Completed corpus tables are immutable inputs. New attempts commit to the recovery
catalog with their own reading policy; per-body progress survives an interrupted batch.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import time

import pyarrow.parquet as pq
from docspec_client import NativeDatasets

from congress_api.lake import body_text, readings, tables
from congress_api.retention.body_store import BodyStore, LocalAdapter
from congress_api.retention.provenance import json_input, parquet_output, run_job
from congress_api.retention.public_origin import PublicOrigin


def write_json(path, value):
    temp = path.with_suffix(path.suffix + '.partial')
    temp.write_text(json.dumps(value, indent=2, default=str, sort_keys=True) + '\n')
    temp.replace(path)


def observed_copy(item, origin):
    """Observe one strong object pin; extraction still checks the decoded body SHA."""
    client = PublicOrigin(origin, user_agent='ct-body-text-recovery/1', timeout=30)
    candidates = item.get('copies') or [item['physical_key']]
    attempts = list(item.get('copy_observations', []))
    item = dict(item)
    item.pop('probe_error', None)
    for key in candidates * 3:
        try:
            response = client.get_object(Bucket=body_text.PUBLIC_BUCKET, Key=key, Range='bytes=0-0')
            response['Body'].close()
            match = re.fullmatch(r'bytes 0-0/([1-9][0-9]*)', response['ContentRange'])
            etag = response.get('ETag') or ''
            headers = {k:v for k,v in response.items() if k!='Body'}
            if response['ResponseMetadata']['HTTPStatusCode'] != 206 or not match or not etag or etag.startswith('W/'):
                attempts.append(dict(key=key,status='unpinned_response',response=headers))
                raise OSError('origin answer lacks a strong ETag and exact stored size')
            observed_size = int(match[1])
            attempts.append(dict(key=key, status='observed', stored_bytes=observed_size, etag=etag))
            # A fresh observed copy may have a different storage encoding. Its decoded SHA remains authoritative.
            return dict(item, physical_key=key, relative_path=key, captured_stored_bytes=item['stored_bytes'],
                        stored_bytes=observed_size, captured_stored_md5=item.get('stored_md5'), stored_md5=None,
                        listed_etag=etag, listing_refusal=None, copy_observations=attempts)
        except Exception as error:
            attempts.append(dict(key=key, status='refused', error=f'{type(error).__name__}: {error}'))
            time.sleep(0.2)
    return dict(item, probe_error=attempts[-1]['error'], copy_observations=attempts)


def prepare_items(work, engine, targets, versions, origin):
    ready = work / 'work-list.json'
    if ready.exists():
        items = json.loads(ready.read_text())
        if {i['body_sha256'] for i in items} != {t['body_sha256'] for t in targets} or any(i['parser_version'] != versions[i['parser']] for i in items):
            raise ValueError('Retained work list differs from recovery targets or versions')
        return items
    planned = work / 'copy-plan'
    if not (planned / 'copies.parquet').exists():
        planned.mkdir(parents=True, exist_ok=True)
        source = json_input(planned, 'target_json', [dict(body_hex=t['body_sha256']) for t in targets], body_hex='Utf8')
        run_job(planned, engine, inputs=[source, tables.table_input('captures', work / 'captures-target.parquet')],
                steps=[dict(name='candidates', sql="SELECT decode(body_hex,'hex') AS body_sha FROM target_json"),
                       *body_text.copy_selection_steps()],
                outputs=[parquet_output(planned, 'copies', 'SELECT * FROM body_copies', ['body_sha']),
                         parquet_output(planned, 'alternates', 'SELECT body_sha,physical_key FROM body_storage', ['body_sha','physical_key'])])
    copies = {r['body_sha'].hex(): r for r in pq.read_table(planned / 'copies.parquet').to_pylist()}
    alternates = {}
    for r in pq.read_table(planned / 'alternates.parquet').to_pylist():
        alternates.setdefault(r['body_sha'].hex(), []).append(r['physical_key'])
    items = []
    for target in targets:
        item = dict(copies[target['body_sha256']], **target)
        item.pop('body_sha')
        item['parser_version'] = versions[item['parser']]
        item['copies'] = [item['physical_key']] + [p for p in alternates[target['body_sha256']] if p != item['physical_key']]
        items.append(item)
    previous = {}
    journal = work / 'copy-observations.jsonl'
    if journal.exists():
        for line in journal.read_text().splitlines():
            value = json.loads(line)
            previous[value['body_sha256']] = value
    with ThreadPoolExecutor(max_workers=8) as pool, journal.open('a') as progress:
        futures = [pool.submit(observed_copy, previous.get(item['body_sha256'], item), origin)
                   for item in items if item['body_sha256'] not in previous or previous[item['body_sha256']].get('probe_error')]
        for future in as_completed(futures):
            result = future.result()
            progress.write(json.dumps(result, default=str, sort_keys=True) + '\n')
            progress.flush()
            previous[result['body_sha256']] = result
    items = [dict(previous[t['body_sha256']],parser_version=versions[t['parser']]) for t in targets]
    write_json(ready, items)
    return items


def reuse_completed(source, work, engine, catalog, table_ids, versions):
    """Carry forward successful byte-limit retries: lifting the pixel exclusion cannot change them."""
    receipt = work / 'carried-completed.json'
    if receipt.exists():
        return json.loads(receipt.read_text())
    outcomes = [o for p in sorted((source/'batches').glob('*/result.json'))
                for o in json.loads(p.read_text())['body_outcomes'] if o.get('reading_status')=='completed']
    wanted = {o['body_sha256'] for o in outcomes}
    pins = tables.resolve_tables(engine=engine,work=work/'resolve-reuse',catalog_root=source/'catalog',tables=table_ids)
    stage = work/'carried-stage'
    stage.mkdir(exist_ok=True)
    for name in ('body_text','readings'):
        schema = json.loads(body_text.SCHEMA.read_text()) if name=='body_text' else tables.load_schema(name)
        version = 'CASE s.parser ' + ' '.join(f"WHEN '{p}' THEN '{v}'" for p,v in versions.items()) + ' ELSE s.parser_version END AS parser_version'
        columns = ','.join(version if f['name']=='parser_version' else 's."'+f['name']+'"' for f in schema['fields'])
        selected = ','.join("'"+s+"'" for s in sorted(wanted))
        out = stage/name
        run_job(out,engine,inputs=[tables.table_input('source',pins[name])],steps=[],
                outputs=[parquet_output(out,'rows',f"SELECT {columns} FROM source s WHERE encode(s.body_sha,'hex') IN ({selected})",body_text.PK)])
        path=out/'rows.parquet'
        assert pq.ParquetFile(path).metadata.num_rows==len(wanted)
        tables.append_rows(path,engine=engine,work=stage/('append-'+name),catalog_root=catalog,
                           table=table_ids[name],keys=body_text.PK,definition='reuse completed recovery: pixel exclusion removed')
    for o in outcomes:
        o['prior_parser_version']=o['parser_version']
        o['parser_version']=versions[o['parser']]
        o['reused_from']=str(source)
    write_json(receipt,outcomes)
    return outcomes


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--work-dir', type=Path, required=True)
    ap.add_argument('--engine-config', default=os.environ.get('DOCSPEC_JOB_CONFIG'), required=not bool(os.environ.get('DOCSPEC_JOB_CONFIG')))
    ap.add_argument('--origin', default=body_text.ORIGIN)
    ap.add_argument('--pilot', action='store_true', help='One smallest body per original failure reason before the full pass')
    ap.add_argument('--max-batches', type=int)
    ap.add_argument('--reuse-completed',type=Path)
    args = ap.parse_args()
    work = args.work_dir.resolve()
    targets = json.loads((work / 'targets.json').read_text())
    if len({t['body_sha256'] for t in targets}) != len(targets):
        raise ValueError('Recovery inventory repeats a body')
    versions = body_text.recovery_versions()
    pin = dict(targets_sha256=sha256((work / 'targets.json').read_bytes()).hexdigest(),
               captures_sha256=sha256((work / 'captures-target.parquet').read_bytes()).hexdigest(), versions=versions)
    pin_path = work / 'input-pin.json'
    if pin_path.exists() and json.loads(pin_path.read_text()) != pin:
        raise ValueError('Recovery inputs or declared versions changed; keep the previous attempt separately')
    write_json(pin_path, pin)
    archive_root = Path(json.loads((work / 'baseline.json').read_text())['catalog']['readings']['metadata_location']).parents[4]
    lock_path = archive_root / 'nightly/lock'
    # The catalog and all output live in the main checkout; this lock coordinates with scheduled releases.
    lock = lock_path.open('a+')
    print('waiting for shared release/OCR lock', flush=True)
    while True:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            time.sleep(15)
    print('recovery lock acquired', flush=True)
    table_ids = {n: dict(namespace=['archive'], name=n) for n in ('readings','body_text')}
    catalog = work / 'catalog'
    with NativeDatasets.from_config(args.engine_config) as engine:
        if not (catalog / 'catalog.sqlite').exists():
            readings.create_table(engine=engine, work=work / 'create-readings', catalog_root=catalog,
                                  table=table_ids['readings'], location=work / 'tables/readings', create_namespace=True)
            body_text.create_table(engine=engine, work=work / 'create-text', catalog_root=catalog,
                                   table=table_ids['body_text'], location=work / 'tables/body_text')
        all_items = prepare_items(work, engine, targets, versions, args.origin)
        carried = reuse_completed(args.reuse_completed.resolve(),work,engine,catalog,table_ids,versions) if args.reuse_completed else []
        completed = {o['body_sha256'] for o in carried}
        results = sorted((work / 'batches').glob('*/result.json'))
        for p in results:
            completed.update(o['body_sha256'] for o in json.loads(p.read_text())['body_outcomes'])
        remaining = [i for i in all_items if not i.get('probe_error')]
        remaining.sort(key=lambda i: (i['stored_bytes'],i['body_sha256']))
        if args.pilot:
            selected = {}
            for item in remaining:
                selected.setdefault(item['previous_reason'],item)
            remaining = list(selected.values())
        remaining = [i for i in remaining if i['body_sha256'] not in completed]
        batches = []
        for low, high, count, workers, memory in [(0,128<<20,12,4,2<<30),(128<<20,512<<20,4,2,4<<30),(512<<20,float('inf'),1,1,6<<30)]:
            group = [i for i in remaining if low <= max(i['stored_bytes'],i.get('decoded_bytes') or 0) < high]
            batches.extend((group[n:n+count],workers,memory) for n in range(0,len(group),count))
        if args.max_batches is not None:
            batches = batches[:args.max_batches]
        store = BodyStore(LocalAdapter(work / 'unreadable-store'))
        for items,workers,memory in batches:
            number = len(list((work / 'batches').glob('batch-*'))) + 1
            batch = work / 'batches' / f'batch-{number:05d}'
            batch.mkdir(parents=True)
            write_json(batch / 'inputs.json',items)
            planned = dict(versions=versions, local_root=None, decided_at=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
            for item in items:
                item['body_sha'] = bytes.fromhex(item['body_sha256'])
            print(f'batch {number}: {len(items)} bodies, {workers} workers, {memory/(1<<30):g} GiB per worker',flush=True)
            staged = body_text.stage(planned,items,engine=engine,work=batch/'stage',unreadable_store=store,
                                     parser_workers=workers,parser_memory_bytes=workers*memory,
                                     strategy='congress_api.parsers.body_text:recovery_apple_vision',origin=args.origin,
                                     recovery=True,worker_memory_bytes=memory)
            staged['append'] = body_text.append(staged,engine=engine,work=batch/'commit',catalog_root=catalog,tables=table_ids)
            write_json(batch/'result.json',staged)
            staged['body_text'].unlink()
            print(f"batch {number} committed: {staged['body_text_rows']} texts, {staged['pending_reads']} pending, {staged['unreadable']} unreadable",flush=True)
        all_outcomes = carried + [o for p in sorted((work/'batches').glob('*/result.json')) for o in json.loads(p.read_text())['body_outcomes']]
        seen = {o['body_sha256'] for o in all_outcomes}
        summary = dict(targets=len(targets),attempted=len(seen),probe_refusals=sum(bool(i.get('probe_error')) for i in all_items),
                       outcomes=dict(Counter((o.get('reading_status') or o['status']) for o in all_outcomes)),
                       reasons=dict(Counter(o.get('reason') or 'completed' for o in all_outcomes)),versions=versions,
                       remaining=len(targets)-len(seen)-sum(bool(i.get('probe_error')) for i in all_items))
        write_json(work/'summary.json',summary)
        print(json.dumps(summary,sort_keys=True),flush=True)
    fcntl.flock(lock,fcntl.LOCK_UN)
    lock.close()


if __name__ == '__main__':
    main()
