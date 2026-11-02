"""Prove one compatible readings entry over local bodies, and optionally write it to the registry.

    python -m congress_api.lake.compatible_proof --parser html --old <pin> --old-lock <uv.lock> \
        --base <readings.parquet> --captures <captures.parquet> --raw-root <mirror> --work <dir> \
        [--sample 2000 | --sample-keys <csv with a sha column>] [--evidence <file>]... [--write]
    python -m congress_api.lake.compatible_proof --parser readings --old <bundle pin> \
        --decisions <unreadable.jsonl>... --captures ... --raw-root ... --work <dir> [--write]

Kept apart from compatible_versions (which the readings bundle hashes) so proof tooling can
change without moving a pin. Every recompute runs the current producer (readings.stage_once)
over a pinned subset; the comparison is compatible_versions.prove_unchanged, so the proof is
over lake rows, not a reader's in-process output.

Cost: the base readings column scan is O(N) narrow; the local-body listing is O(files in the
mirror); ranking is O(L log L) over local candidates; recompute is O(sample) body reads.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.lake import compatible_versions as cv
from congress_api.lake import readings
from congress_api.retention.provenance import file_pin, parquet_output, run_job

SUFFIXES = ('', '.gz', '.pdf')
ATTEST_BODIES = 20


def local_bodies(raw_root):
    """body hex -> mirror-relative key, listing the mirror once."""
    root = Path(raw_root) / 'bodies/sha256'
    found = {}
    for path in root.glob('*/*'):
        stem = path.name.split('.', 1)[0]
        if len(stem) == 64 and path.name[64:] in SUFFIXES:
            found.setdefault(stem, path.relative_to(raw_root).as_posix())
    return found


def choose_sample(*, base, parser, old, local, size, engine, work):
    """Pre-chosen keys: the `size` lowest sha256(body_sha) local bodies plus every local error path."""
    # Narrow keys only, through a file: a query result is bounded by the metadata allowance.
    directory = work / 'candidates'
    run_job(directory, engine, inputs=[dict(name='r', kind='parquet', path=str(base))], steps=[], queries=[],
        outputs=[parquet_output(directory, 'keys', f"SELECT encode(body_sha,'hex') AS body,status FROM r "
            f"WHERE parser='{parser}' AND parser_version='{old}'", ['body'])])
    rows = pq.read_table(directory / 'keys.parquet').to_pylist()
    candidates = [r for r in rows if r['body'] in local]
    ranked = sorted(candidates, key=lambda r: sha256(bytes.fromhex(r['body'])).digest())
    chosen = {r['body'] for r in ranked[:size]} | {r['body'] for r in candidates if r['status'] in ('error', 'size_limit')}
    return sorted(chosen), len(rows), len(candidates)


def write_keys(path, bodies):
    pq.write_table(pa.table(dict(body_sha=pa.array([bytes.fromhex(b) for b in bodies], pa.binary(32)))), path)
    return path


def recompute(*, bodies, local, captures, raw_root, engine, work, decided_at):
    """Stage the current producer over exactly these bodies. Capture sniff facts are dropped so
    every body gets a fresh sniff reading; bodies settle on nothing older."""
    keys = write_keys(work / 'keys.parquet', bodies)
    run_job(work / 'subset', engine, inputs=[dict(name='c', kind='parquet', path=str(captures)), dict(name='k', kind='parquet', path=str(keys))],
        steps=[], queries=[], outputs=[parquet_output(work / 'subset', 'captures',
            'SELECT c.* EXCLUDE(sniffed_format,sniff_version,intact),cast(NULL AS VARCHAR) AS sniffed_format,'
            'cast(NULL AS VARCHAR) AS sniff_version,cast(NULL AS BOOLEAN) AS intact FROM c JOIN k ON c.sha256=k.body_sha',
            ['receipt_key', 'receipt_line', 'capture_index'])])
    # The mirror's bodies are symlinks into a shared object store, and the producer refuses a
    # path that resolves outside its root, so the sample is copied into a private root: O(sample).
    root = work / 'bodies'
    for b in bodies:
        target = root / local[b]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(raw_root) / local[b], target)
    inventory = work / 'inventory.parquet'
    rows = [dict(body_sha=bytes.fromhex(b), physical_key=local[b], relative_path=local[b],
                 stored_bytes=(root / local[b]).stat().st_size, stored_gzip=local[b].endswith('.gz')) for b in bodies]
    pq.write_table(pa.Table.from_pylist(rows, schema=pa.schema([('body_sha', pa.binary(32)), ('physical_key', pa.string()),
        ('relative_path', pa.string()), ('stored_bytes', pa.int64()), ('stored_gzip', pa.bool_())])), inventory)
    # The recompute reads no existing rows, so the registry cannot matter to it; an empty one
    # keeps a stale entry (the one being re-proved) from blocking its own replacement.
    empty = work / 'empty-registry.json'
    empty.write_text(json.dumps(dict(version=2, entries=[])))
    staged = readings.stage_once(captures=work / 'subset/captures.parquet', body_inventory=inventory, local_root=root,
        engine=engine, work=work / 'stage', decided_at=decided_at, registry=empty)
    return keys, staged


ATTEST = r'''
import importlib.metadata, json, sys
sys.path[:0] = json.loads(sys.argv[1])
from congress_api.lake import readings
request = json.loads(sys.argv[2])
version = readings.current_version(request['parser'])
# The parsers themselves, outside the supervisor's read-phase guard (no worker here).
import gzip
for payload in request['payloads']:
    data = open(payload['path'], 'rb').read()
    if request['parser'] == 'sniff':
        from congress_api.retention.sniff import read_sniff
        read_sniff(lambda start, length: data[start:start + length], stored_size=len(data), stored_gzip=payload['path'].endswith('.gz'))
    else:
        from congress_api.parsers.archive_readings import read_page
        read_page(gzip.decompress(data) if data[:2] == b'\x1f\x8b' else data, request['parser'])
owners = importlib.metadata.packages_distributions()
loaded = sorted({d.lower() for m in list(sys.modules) for d in owners.get(m.split('.')[0], [])})
print(json.dumps(dict(version=version, loaded=loaded)))
'''


def _locked(path):
    return {p['name'].lower(): p.get('version') for p in tomllib.loads(Path(path).read_text()).get('package', [])}


def attest_lock_only(*, parser, old, old_lock, raw_root, local, bodies, work):
    """A different tool family: the committed tree plus the old lock must recompute the old pin,
    and parsing real bodies must load none of the distributions the lock change touched."""
    root = Path(readings.ROOT)
    tree = Path(tempfile.mkdtemp(dir=work))
    archive = subprocess.run(['git', '-C', str(root), 'archive', 'HEAD', 'packages', 'model', 'uv.lock'], check=True, capture_output=True).stdout
    subprocess.run(['tar', '-x', '-C', str(tree)], input=archive, check=True)
    (tree / 'uv.lock').write_bytes(Path(old_lock).read_bytes())
    paths = [str(p) for p in sorted((tree / 'packages').glob('*/src'))]
    payloads = [dict(path=str(Path(raw_root) / local[b]), parser=parser, stored_bytes=(Path(raw_root) / local[b]).stat().st_size,
                     stored_gzip=False) for b in bodies[:ATTEST_BODIES]]
    done = subprocess.run([sys.executable, '-I', '-c', ATTEST, json.dumps(paths), json.dumps(dict(parser=parser, payloads=payloads))],
        capture_output=True, text=True, cwd=tree)
    if done.returncode:
        raise ValueError('Lock-only attestation failed in the committed tree: ' + done.stderr[-2000:])
    result = json.loads(done.stdout.strip().splitlines()[-1])
    old_pins, new_pins = _locked(old_lock), _locked(root / 'uv.lock')
    changed = sorted(n for n in set(old_pins) | set(new_pins) if old_pins.get(n) != new_pins.get(n))
    touched = sorted(set(changed) & set(result['loaded']))
    if result['version'] != old:
        raise ValueError(f'The committed tree with the old lock recomputes {result["version"]}, not {old}')
    if touched:
        raise ValueError(f'Parsing loaded distributions the lock change touched: {touched}')
    return dict(recomputed=result['version'], changed_distributions=changed, parsed_bodies=len(payloads))


def prove_bundle(*, old, decisions, captures, raw_root, engine, work, decided_at, current):
    """Re-read every decision body under the current producer; each must reach the same reason."""
    old_rows = [json.loads(line) for f in decisions for line in Path(f).read_text().splitlines() if line.strip()]
    old_rows = [r for r in old_rows if r['parser'] == 'readings' and r['parser_version'] == old]
    local = local_bodies(raw_root)
    missing = sorted({r['body_sha256'] for r in old_rows} - set(local))
    if not old_rows or missing:
        raise ValueError(f'Bundle proof needs every decision body local; missing {len(missing)}: {missing}')
    _, staged = recompute(bodies=sorted({r['body_sha256'] for r in old_rows}), local=local, captures=captures,
        raw_root=raw_root, engine=engine, work=work, decided_at=decided_at)
    path = Path(staged['work_list']).parent / 'parsed/unreadable.jsonl'
    new = {r['body_sha256']: r['reason'] for r in map(json.loads, path.read_text().splitlines())} if path.exists() else {}
    before = {r['body_sha256']: r['reason'] for r in old_rows}
    differences = sum(new.get(b) not in (None, reason) for b, reason in before.items())
    proof = dict(scope='full', version=old, current=current, recompute_sha256=cv.recompute_sha256(cv.WHOLE),
        old_input_sha256=sha256(b''.join(Path(f).read_bytes() for f in decisions)).hexdigest(),
        new_input_sha256=file_pin(path)['sha256'] if path.exists() else sha256(b'').hexdigest(),
        rows=len(before), columns=1, differences=differences, only_old=sum(b not in new for b in before),
        only_new=sum(b not in before for b in new))
    return proof


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    for name in ('--parser', '--old', '--captures', '--raw-root', '--work'):
        parser.add_argument(name, required=True)
    parser.add_argument('--old-lock')
    parser.add_argument('--base')
    parser.add_argument('--decisions', action='append', default=[])
    parser.add_argument('--sample', type=int, default=2000)
    parser.add_argument('--sample-keys')
    parser.add_argument('--evidence', action='append', default=[], help='Supporting files recorded by sha256')
    parser.add_argument('--decided-at', default='2026-11-02T00:00:00Z')
    parser.add_argument('--engine-config', default=None)
    parser.add_argument('--reason', default=None)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args(argv)
    from docspec_client.client import NativeDatasets
    import os
    pins = cv.current_pins()
    work = Path(args.work).resolve()
    work.mkdir(parents=True, exist_ok=False)
    with NativeDatasets.from_config(args.engine_config or os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        if args.parser == 'readings':
            basis, recompute_sql = 'bundle', cv.WHOLE
            proof = prove_bundle(old=args.old, decisions=args.decisions, captures=args.captures, raw_root=args.raw_root,
                engine=engine, work=work, decided_at=args.decided_at, current=pins['readings'])
            report = dict(proof=proof)
        else:
            recompute_sql = cv.reader_recompute_sql(args.parser) or cv.WHOLE
            basis = 'predicate' if recompute_sql != cv.WHOLE else 'lock_only' if args.parser == 'sniff' else 'whole'
            local = local_bodies(args.raw_root)
            if args.sample_keys:
                import csv
                with open(args.sample_keys) as stream:
                    bodies = sorted({row['sha'] for row in csv.DictReader(stream)} & set(local))
                total = candidates = None
            else:
                bodies, total, candidates = choose_sample(base=args.base, parser=args.parser, old=args.old, local=local,
                    size=args.sample, engine=engine, work=work)
            keys, staged = recompute(bodies=bodies, local=local, captures=args.captures, raw_root=args.raw_root,
                engine=engine, work=work, decided_at=args.decided_at)
            counts, differing = cv.prove_unchanged(engine=engine, work=work / 'proof', old=args.base, new=staged['readings'],
                parser=args.parser, version=args.old, current=pins[args.parser], recompute_sql=recompute_sql, sample_keys=keys)
            proof = dict(scope='sample', version=args.old, current=pins[args.parser], recompute_sha256=cv.recompute_sha256(recompute_sql),
                old_input_sha256=file_pin(args.base)['sha256'], new_input_sha256=file_pin(staged['readings'])['sha256'],
                sample_keys_sha256=file_pin(keys)['sha256'], **counts)
            if basis == 'lock_only':
                proof['lock_only'] = attest_lock_only(parser=args.parser, old=args.old, old_lock=args.old_lock,
                    raw_root=args.raw_root, local=local, bodies=bodies, work=work)
            report = dict(proof=proof, differing=differing, sampled=len(bodies), rows_at_old=total, local_at_old=candidates)
        if args.evidence:
            proof['evidence'] = {Path(f).name: file_pin(f)['sha256'] for f in args.evidence}
        entry = dict(parser=args.parser, version=args.old, current=pins[args.parser], basis=basis, recompute_sql=recompute_sql,
            reason=args.reason or f'{basis} proof over {proof.get("rows")} rows', proof=proof)
        report['entry'] = entry
        (work / 'proof.json').write_text(json.dumps(report, indent=1, sort_keys=True) + '\n')
        print(json.dumps(report, sort_keys=True))
        if args.write:
            registry = json.loads(cv.REGISTRY.read_text())
            entries = [e for e in registry['entries'] if (e['parser'], e['version']) != (args.parser, args.old)] + [entry]
            cv.validate_entries(entries, current=pins)
            cv.REGISTRY.write_text(json.dumps(dict(version=2, entries=entries), indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
