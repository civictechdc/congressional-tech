"""Prove one compatible readings entry over local bodies, and optionally write it to the registry.

    python -m congress_api.lake.compatible_proof --parser sniff --old <pin> --old-lock <uv.lock> \
        --base <readings.parquet> --captures <captures.parquet> --raw-root <mirror> --work <dir> \
        [--sample 2000 | --sample-keys <csv with a sha column>] [--mirror-inventory <inventory.parquet>]
        [--evidence <file>]... [--write]
    python -m congress_api.lake.compatible_proof --parser readings --old <bundle pin> \
        --decisions <unreadable.jsonl>... --captures ... --raw-root ... --work <dir> [--write]

Pass the retained proof inventory as --mirror-inventory to reuse an immutable mirror.
The operator keeps the selected keys stable throughout the run. Targets must be read-only
and match the original key and stored size. For other inputs, the default uses a private copy.

Kept apart from compatible_versions (which the readings bundle hashes), with the comparison
(prove_unchanged) and the raw-key preflight, so tooling edits move no pin. Every recompute
runs the current producer (readings.stage_once) over a pinned subset and compares lake rows.

Cost: the base readings column scan is O(N) narrow; the local-body listing is O(files in the
mirror); ranking is O(L log L) over local candidates; recompute is O(sample) body reads.
"""
import argparse
import contextlib
import fcntl
from hashlib import file_digest, sha256
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tomllib

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.lake import compatible_versions as cv
from congress_api.lake import readings, tables
from congress_api.lake.tables import TABLE_SPECS, table_input
from congress_api.retention.body_keys import body_object_digest
from congress_api.retention.body_store import validate_key
from congress_api.retention.provenance import file_pin, parquet_output, run_job
from congress_shared.custody import custody_identity

SUFFIXES = ('', '.gz', '.pdf')
ATTEST_BODIES = 20
ATTESTATION_OWNER = b'congress-api compatibility proof lock attestation v1\n'


def local_bodies(raw_root):
    """body hex -> mirror-relative key, listing the mirror once."""
    root = Path(raw_root) / 'bodies/sha256'
    found = {}
    for path in root.glob('*/*'):
        stem = path.name.split('.', 1)[0]
        if len(stem) == 64 and path.name[64:] in SUFFIXES:
            found.setdefault(stem, path.relative_to(raw_root).as_posix())
    return found


def _oversize(parser, captures):
    """Inputs and steps for the page-parse size rule; nothing for sniff or without captures."""
    if parser not in cv.PAGE_PARSERS:
        return [], [], ''
    return ([table_input('captures', captures)], [dict(name='oversize', sql=cv.oversize_bodies_sql(), materialize=True)],
            ' AND NOT EXISTS (SELECT 1 FROM oversize z WHERE z.body_sha=r.body_sha)')


def kept_rows(*, base, parser, old, recompute_sql, engine, work, captures):
    """(body hex, status) of every old row the entry keeps: outside its recompute set and, for a
    page parser, at or under the page-parse bound."""
    # Narrow keys only, through a file: a query result is bounded by the metadata allowance.
    directory = work / 'candidates'
    p, v = cv._quote(parser), cv._quote(old)
    size_inputs, size_steps, size_rule = _oversize(parser, captures)
    run_job(directory, engine, inputs=[dict(name='r', kind='parquet', path=str(base)), *size_inputs], queries=[],
        steps=[dict(name='old_rows', sql=f'SELECT * FROM r WHERE parser={p} AND parser_version={v}'),
               dict(name='recompute', sql=cv.recompute_set_sql(recompute_sql, 'old_rows'), materialize=True), *size_steps],
        outputs=[parquet_output(directory, 'keys', "SELECT encode(r.body_sha,'hex') AS body,r.status FROM old_rows r "
            'WHERE NOT EXISTS (SELECT 1 FROM recompute x WHERE x.body_sha=r.body_sha)' + size_rule, ['body'])])
    return pq.read_table(directory / 'keys.parquet').to_pylist()


def choose_sample(rows, *, local, size, full):
    """Pre-chosen keys and their strata. A sample takes the `size` lowest sha256(body_sha) local
    completed rows and every local error/size_limit row; `full` takes every kept row and needs
    every body local."""
    candidates = [r for r in rows if r['body'] in local]
    if full and len(candidates) != len(rows):
        raise ValueError(f'A full proof needs every kept body local; {len(rows) - len(candidates)} of {len(rows)} are not')
    ranked = sorted((r for r in candidates if r['status'] not in cv.ERROR_STRATA), key=lambda r: sha256(bytes.fromhex(r['body'])).digest())
    chosen = {r['body'] for r in (candidates if full else ranked[:size])} | {r['body'] for r in candidates if r['status'] in cv.ERROR_STRATA}
    strata = {}
    for r in rows:
        stratum = strata.setdefault(r['status'], dict(population=0, local=0, sampled=0))
        stratum['population'] += 1
        stratum['local'] += r['body'] in local
        stratum['sampled'] += r['body'] in chosen
    return sorted(chosen), strata


def write_keys(path, bodies):
    pq.write_table(pa.table(dict(body_sha=pa.array([bytes.fromhex(b) for b in bodies], pa.binary(32)))), path)
    return path


def _mirror_sizes(inventory, bodies, local):
    """Bind each selected original mirror key to its retained stored size."""
    selected = {bytes.fromhex(body) for body in bodies}
    pinned = pq.read_table(inventory, columns=['body_sha', 'physical_key', 'relative_path', 'stored_bytes'],
                          filters=[('body_sha', 'in', selected)]).to_pylist() if selected else []
    sizes = {}
    for row in pinned:
        body = row['body_sha'].hex()
        validate_key(row['physical_key'])
        if (body in sizes or row['physical_key'] != local[body] or row['relative_path'] != local[body]
                or body_object_digest(row['physical_key']) != body
                or type(row['stored_bytes']) is not int or row['stored_bytes'] < 0):
            raise ValueError(f'Mirror inventory does not pin the original key and stored size for {body}')
        sizes[body] = row['stored_bytes']
    if len(sizes) != len(selected):
        raise ValueError('Mirror inventory is missing selected proof bodies')
    return sizes


def _mirror_identity(path):
    target = path.resolve(strict=True)
    return target, custody_identity(target)


def _require_mirror_custody(sources):
    for path, pin in sources.items():
        if _mirror_identity(path) != pin:
            raise ValueError(f'Mirror body changed while proving: {path}')


def recompute(*, bodies, local, captures, raw_root, engine, work, decided_at, mirror_inventory=None):
    """Stage the current producer over exactly these bodies. Capture sniff facts are dropped so
    every body gets a fresh sniff reading; bodies settle on nothing older."""
    keys = write_keys(work / 'keys.parquet', bodies)
    run_job(work / 'subset', engine, inputs=[dict(name='c', kind='parquet', path=str(captures)), dict(name='k', kind='parquet', path=str(keys))],
        steps=[], queries=[], outputs=[parquet_output(work / 'subset', 'captures',
            'SELECT c.* EXCLUDE(sniffed_format,sniff_version,intact),cast(NULL AS VARCHAR) AS sniffed_format,'
            'cast(NULL AS VARCHAR) AS sniff_version,cast(NULL AS BOOLEAN) AS intact FROM c JOIN k ON c.sha256=k.body_sha',
            ['receipt_key', 'receipt_line', 'capture_index'])])
    # The reader accepts mirror-relative paths through symlinks and checks the
    # original key. Direct reuse requires the caller's custody and immutability guarantee.
    root = Path(raw_root).resolve()
    if mirror_inventory is None:
        root = work / 'bodies'
        for b in bodies:
            target = root / local[b]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(raw_root) / local[b], target)
    inventory = work / 'inventory.parquet'
    sizes = _mirror_sizes(mirror_inventory, bodies, local) if mirror_inventory is not None else None
    sources = {}
    rows = []
    for body in bodies:
        key = local[body]
        path = root / key
        target = path
        if sizes is not None:
            target, identity = _mirror_identity(path)
            sources[path] = target, identity
        source = target.stat()
        if not stat.S_ISREG(source.st_mode):
            raise ValueError(f'Proof body is not a regular file: {key}')
        if sizes is not None:
            if source.st_mode & 0o222 or source.st_size != sizes[body]:
                raise ValueError(f'Mirror body must be read-only and match its pinned size: {key}')
            # The maintained reader verifies gzip bodies. Its plain sniff path
            # trusts a pinned size, so verify the plain entity before reuse.
            with target.open('rb') as stream:
                if stream.read(2) != b'\x1f\x8b':
                    stream.seek(0)
                    if file_digest(stream, 'sha256').hexdigest() != body:
                        raise ValueError(f'Mirror body digest differs from its key: {key}')
        rows.append(dict(body_sha=bytes.fromhex(body), physical_key=key, relative_path=key,
                         stored_bytes=source.st_size))
    # No storage encoding here: the reader decides it from the body's hash, never from a name.
    pq.write_table(pa.Table.from_pylist(rows, schema=pa.schema([('body_sha', pa.binary(32)), ('physical_key', pa.string()),
        ('relative_path', pa.string()), ('stored_bytes', pa.int64())])), inventory)
    # The recompute reads no existing rows, so the registry cannot matter to it; an empty one
    # keeps a stale entry (the one being re-proved) from blocking its own replacement.
    empty = work / 'empty-registry.json'
    empty.write_text(json.dumps(dict(version=2, entries=[])))
    staged = readings.stage_once(captures=work / 'subset/captures.parquet', body_inventory=inventory, local_root=root,
        engine=engine, work=work / 'stage', decided_at=decided_at, registry=empty)
    if sizes is not None:
        _require_mirror_custody(sources)
        if staged['pending_reads']:
            raise ValueError(f'Mirror proof has {staged["pending_reads"]} unread selected bodies')
        staged['mirror_sources'] = sources
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
        read_sniff(lambda start, length: data[start:start + length], stored_size=len(data), stored_gzip=payload['stored_gzip'])
    else:
        from congress_api.parsers.archive_readings import read_page
        read_page(gzip.decompress(data) if payload['stored_gzip'] else data, request['parser'])
owners = importlib.metadata.packages_distributions()
loaded = sorted({d.lower() for m in list(sys.modules) for d in owners.get(m.split('.')[0], [])})
print(json.dumps(dict(version=version, loaded=loaded)))
'''


def _stored_gzip(path, body):
    with open(path, 'rb') as stream:
        return readings._storage_gzip(stream, body, raw_io=contextlib.nullcontext)


def _locked(path):
    return {p['name'].lower(): p.get('version') for p in tomllib.loads(Path(path).read_text()).get('package', [])}


@contextlib.contextmanager
def attestation_lock(work, *, create=False):
    """Hold ownership of the disposable source tree across attestation subprocesses."""
    lock = Path(work) / 'lock-attestation.lock'
    mode = os.O_RDWR | os.O_CREAT | os.O_EXCL if create else os.O_RDONLY
    with os.fdopen(os.open(lock, mode | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600), 'r+b' if create else 'rb') as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError('Invalid compatibility proof attestation lock')
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Compatibility proof attestation is still active') from None
        if create:
            handle.write(ATTESTATION_OWNER)
            handle.flush()
        elif handle.read(len(ATTESTATION_OWNER) + 1) != ATTESTATION_OWNER:
            raise ValueError('Unowned compatibility proof attestation lock')
        yield handle.fileno()


def attest_lock_only(*, parser, old, old_lock, raw_root, local, bodies, work, mirror_sources=None):
    """A different tool family: the committed tree plus the old lock must recompute the old pin,
    and parsing real bodies must load none of the distributions the lock change touched."""
    root = Path(readings.ROOT)
    raw_root = Path(raw_root).resolve()
    source_paths = [raw_root / local[b] for b in bodies[:ATTEST_BODIES]]
    # The old tree may predate the hash rule, so the encoding is decided here, by the current one.
    payloads = [dict(path=str(path), parser=parser, stored_bytes=path.stat().st_size,
                     stored_gzip=_stored_gzip(path, body)) for path, body in zip(source_paths, bodies)]
    tree = Path(work) / 'lock-attestation'
    with attestation_lock(work, create=True) as fd:
        tree.mkdir(mode=0o700)
        try:
            archive = subprocess.run(['git', '-C', str(root), 'archive', 'HEAD', 'packages', 'model', 'uv.lock'],
                check=True, capture_output=True, pass_fds=(fd,)).stdout
            subprocess.run(['tar', '-x', '-C', str(tree)], input=archive, check=True, pass_fds=(fd,))
            (tree / 'uv.lock').write_bytes(Path(old_lock).read_bytes())
            paths = [str(p) for p in sorted((tree / 'packages').glob('*/src'))]
            done = subprocess.run([sys.executable, '-I', '-c', ATTEST, json.dumps(paths), json.dumps(dict(parser=parser, payloads=payloads))],
                capture_output=True, text=True, cwd=tree, pass_fds=(fd,))
        finally:
            shutil.rmtree(tree)
    if mirror_sources is not None:
        _require_mirror_custody({path: mirror_sources[path] for path in source_paths})
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


def _counts(values):
    counts = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def prove_bundle(*, old, decisions, captures, raw_root, engine, work, decided_at, current, mirror_inventory=None):
    """Re-read every decision body under the current producer; each must reach the same reason."""
    old_rows = [json.loads(line) for f in decisions for line in Path(f).read_text().splitlines() if line.strip()]
    old_rows = [r for r in old_rows if r['parser'] == 'readings' and r['parser_version'] == old]
    local = local_bodies(raw_root)
    missing = sorted({r['body_sha256'] for r in old_rows} - set(local))
    if not old_rows or missing:
        raise ValueError(f'Bundle proof needs every decision body local; missing {len(missing)}: {missing}')
    _, staged = recompute(bodies=sorted({r['body_sha256'] for r in old_rows}), local=local, captures=captures,
        raw_root=raw_root, engine=engine, work=work, decided_at=decided_at, mirror_inventory=mirror_inventory)
    path = Path(staged['work_list']).parent / 'parsed/unreadable.jsonl'
    new = {r['body_sha256']: r['reason'] for r in map(json.loads, path.read_text().splitlines())} if path.exists() else {}
    before = {r['body_sha256']: r['reason'] for r in old_rows}
    differences = sum(new.get(b) not in (None, reason) for b, reason in before.items())
    proof = dict(scope='full', version=old, current=current, recompute_sha256=cv.recompute_sha256(cv.WHOLE),
        old_input_sha256=sha256(b''.join(Path(f).read_bytes() for f in decisions)).hexdigest(),
        new_input_sha256=file_pin(path)['sha256'] if path.exists() else sha256(b'').hexdigest(),
        rows=len(before), columns=1, differences=differences, only_old=sum(b not in new for b in before),
        only_new=sum(b not in before for b in new),
        # Every decision body is read, so each reason's stratum is complete.
        strata={reason: dict(population=n, local=n, sampled=n) for reason, n in _counts(before.values()).items()})
    return proof


def duplicate_keys_sql(name, input_name='t'):
    keys = ','.join(TABLE_SPECS[name]['primary_key'])
    return f'SELECT count(*) AS duplicate_keys FROM (SELECT {keys} FROM {input_name} GROUP BY {keys} HAVING count(*)>1)'


def preflight(*, engine, work, inputs):
    """Reject raw duplicate primary keys before selection. `inputs` maps table name to its source."""
    work = Path(work)
    found = {}
    for name, source in inputs.items():
        rows = run_job(work / name, engine, inputs=[table_input('t', source)], steps=[], outputs=[],
            queries=[dict(name='keys', sql=duplicate_keys_sql(name))])['keys']
        found[name] = rows[0]['duplicate_keys']
    bad = {name: count for name, count in found.items() if count}
    if bad:
        raise ValueError(f'Raw primary keys are duplicated before selection: {bad}')
    return found


def prove_unchanged(*, engine, work, old, new, parser, version, current, recompute_sql=cv.WHOLE, sample_keys=None, captures=None):
    """Every old row at `version` outside the recompute set must equal its row at `current`.

    The compared domain K is the old rows outside the old side's recompute set: those are the
    rows an entry keeps. A K row that changes or vanishes is a difference; a row inside the
    set may change on purpose (its re-read can even move it out of the set, e.g. filling a
    fingerprint) and is not compared. With `sample_keys` (a parquet of body_sha chosen before
    the recompute) K is further limited to those. Queries only: no sorted export.
    """
    name = 'readings'
    schema = [f['name'] for f in tables.load_schema(name)['fields']]
    keys = [k for k in TABLE_SPECS[name]['primary_key'] if k != 'parser_version']
    compared = [c for c in schema if c not in keys and c != 'parser_version']
    on = lambda a, b: ' AND '.join(f'{a}.{k}={b}.{k}' for k in keys)
    p, old_v, new_v = map(cv._quote, (parser, version, current))
    if parser in cv.PAGE_PARSERS and captures is None:
        raise ValueError('A page parser proof needs captures for the page-parse size rule')
    size_inputs, size_steps, size_rule = _oversize(parser, captures)
    inputs = [table_input('old_input', old), table_input('new_input', new), *size_inputs]
    steps = [*size_steps, dict(name='old_rows', sql=f'SELECT * FROM old_input r WHERE r.parser={p} AND r.parser_version={old_v}'),
             dict(name='new_rows', sql=f'SELECT * FROM new_input r WHERE r.parser={p} AND r.parser_version={new_v}'),
             dict(name='old_recompute', sql=cv.recompute_set_sql(recompute_sql, 'old_rows'), materialize=True)]
    held = (f'SELECT {",".join(keys)} FROM old_rows r '
            'WHERE NOT EXISTS (SELECT 1 FROM old_recompute x WHERE x.body_sha=r.body_sha)' + size_rule)
    if sample_keys is not None:
        inputs.append(table_input('sample_keys', sample_keys))
        held = f'SELECT h.* FROM ({held}) h WHERE h.body_sha IN (SELECT body_sha FROM sample_keys)'
    steps += [dict(name='k', sql=held, materialize=True),
              dict(name='o', sql=f'SELECT r.* FROM old_rows r WHERE EXISTS (SELECT 1 FROM k WHERE {on("k", "r")})'),
              dict(name='n', sql=f'SELECT r.* FROM new_rows r WHERE EXISTS (SELECT 1 FROM k WHERE {on("k", "r")})')]
    present = f'o.{keys[0]} IS NOT NULL AND n.{keys[0]} IS NOT NULL'
    columns = ['count(*) AS total', f'count(*) FILTER (WHERE n.{keys[0]} IS NULL) AS only_old', f'count(*) FILTER (WHERE o.{keys[0]} IS NULL) AS only_new']
    columns += [f'count(*) FILTER (WHERE {present} AND o."{c}" IS DISTINCT FROM n."{c}") AS "{c}"' for c in compared]
    row = run_job(work, engine, inputs=inputs, steps=steps, outputs=[],
        queries=[dict(name='proof', sql='SELECT ' + ','.join(columns) + f' FROM o FULL JOIN n ON {on("o", "n")}')])['proof'][0]
    differing = {c: row[c] for c in compared if row[c]}
    return dict(rows=row['total'], columns=len(compared), differences=sum(differing.values()), only_old=row['only_old'], only_new=row['only_new']), differing


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    for name in ('--parser', '--old', '--captures', '--raw-root', '--work'):
        parser.add_argument(name, required=True)
    parser.add_argument('--old-lock')
    parser.add_argument('--base')
    parser.add_argument('--decisions', action='append', default=[])
    parser.add_argument('--sample', type=int, default=2000)
    parser.add_argument('--sample-keys', help='CSV with a sha column: only these local bodies may be sampled')
    parser.add_argument('--mirror-inventory', type=Path,
        help='Read a mirror kept immutable for this proof using its retained inventory of original keys and stored sizes')
    parser.add_argument('--full', action='store_true', help='Compare every kept row (always, for a predicate entry)')
    parser.add_argument('--evidence', action='append', default=[], help='Supporting files recorded by sha256')
    parser.add_argument('--decided-at', default='2026-11-02T00:00:00Z')
    parser.add_argument('--engine-config', default=None)
    parser.add_argument('--reason', default=None)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args(argv)
    from docspec_client.client import NativeDatasets
    pins = cv.current_pins()
    work = Path(args.work).resolve()
    work.mkdir(parents=True, exist_ok=False)
    with NativeDatasets.from_config(args.engine_config or os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        if args.parser == 'readings':
            basis, recompute_sql = 'bundle', cv.WHOLE
            proof = prove_bundle(old=args.old, decisions=args.decisions, captures=args.captures, raw_root=args.raw_root,
                engine=engine, work=work, decided_at=args.decided_at, current=pins['readings'],
                mirror_inventory=args.mirror_inventory)
            report = dict(proof=proof)
        else:
            recompute_sql = cv.reader_recompute_sql(args.parser) or cv.WHOLE
            basis = 'predicate' if args.parser in cv.PAGE_PARSERS else 'lock_only'
            local = local_bodies(args.raw_root)
            rows = kept_rows(base=args.base, parser=args.parser, old=args.old, recompute_sql=recompute_sql, engine=engine, work=work,
                captures=args.captures)
            full = basis == 'predicate' or args.full
            if args.sample_keys:
                import csv
                with open(args.sample_keys) as stream:
                    given = {row['sha'] for row in csv.DictReader(stream)}
                local = {b: k for b, k in local.items() if b in given}
            bodies, strata = choose_sample(rows, local=local, size=args.sample, full=full)
            keys, staged = recompute(bodies=bodies, local=local, captures=args.captures, raw_root=args.raw_root,
                engine=engine, work=work, decided_at=args.decided_at, mirror_inventory=args.mirror_inventory)
            counts, differing = prove_unchanged(engine=engine, work=work / 'proof', old=args.base, new=staged['readings'], captures=args.captures,
                parser=args.parser, version=args.old, current=pins[args.parser], recompute_sql=recompute_sql, sample_keys=keys)
            if args.parser in cv.PAGE_PARSERS:proof_bound = dict(page_parse_max_bytes=cv.page_parse_max_bytes())
            else:proof_bound = {}
            proof = dict(scope='full' if full else 'sample', strata=strata, **proof_bound, version=args.old, current=pins[args.parser], recompute_sha256=cv.recompute_sha256(recompute_sql),
                old_input_sha256=file_pin(args.base)['sha256'], new_input_sha256=file_pin(staged['readings'])['sha256'],
                sample_keys_sha256=file_pin(keys)['sha256'], **counts)
            if basis == 'lock_only':
                proof['lock_only'] = attest_lock_only(parser=args.parser, old=args.old, old_lock=args.old_lock,
                    raw_root=args.raw_root, local=local, bodies=bodies, work=work,
                    mirror_sources=staged.get('mirror_sources'))
            report = dict(proof=proof, differing=differing, sampled=len(bodies))
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
