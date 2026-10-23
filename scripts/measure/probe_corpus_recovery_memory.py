"""Historical Parquet import RSS comparison; no network or retained inputs.

Both revisions must be explicit pre-native references. Each arm runs in a fresh
child process. This diagnostic measures the historical whole-index importer,
including encoded index payloads; it does not measure native raw selection.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
import time
import types

ROOT = Path(__file__).resolve().parents[2]


def implementation(ref):
    """Load selected recovery modules and their local dependencies from one ref.

    Older receipts name the pre-package scripts. Those sources retain their
    original import names; later historical revisions use the package.
    Every arm runs in a fresh child process.
    """
    if not ref:
        from corpus_recovery import preservation, transfer
        return transfer, preservation
    package_path = 'packages/corpus_recovery/src/corpus_recovery'
    packaged = subprocess.run(['git', 'cat-file', '-e', f'{ref}:{package_path}/transfer.py'],
                              cwd=ROOT, capture_output=True).returncode == 0
    if packaged:
        package = types.ModuleType('corpus_recovery')
        package.__path__ = []
        sys.modules['corpus_recovery'] = package
        all_names = ('guards', 'acknowledge', 'inventory', 'assemble', 'preservation', 'transfer')
        names = [n for n in all_names if subprocess.run(
            ['git', 'cat-file', '-e', f'{ref}:{package_path}/{n}.py'],
            cwd=ROOT, capture_output=True).returncode == 0]
        modules = [(f'corpus_recovery.{name}', f'{package_path}/{name}.py')
                   for name in names]
    else:
        modules = [(name, f'scripts/{name}.py') for name in (
            'assemble_corpus_recovery_import', 'reconcile_corpus_recovery_bodies',
            'verify_corpus_recovery_import_preservation', 'import_corpus_recovery_batch')]
    loaded = {}
    for name, path in modules:
        source = subprocess.check_output(['git', 'show', f'{ref}:{path}'], cwd=ROOT, text=True)
        module = types.ModuleType(name)
        module.__file__ = str(ROOT / path)
        # Imports inside the selected source must see the selected dependencies.
        sys.modules[name] = module
        if packaged:
            setattr(package, name.rsplit('.', 1)[-1], module)
        exec(compile(source, module.__file__, 'exec'), module.__dict__)
        loaded[name] = module
    names = ('corpus_recovery.transfer', 'corpus_recovery.preservation') if packaged else (
        'import_corpus_recovery_batch', 'verify_corpus_recovery_import_preservation')
    return tuple(loaded[name] for name in names)


def child(args):
    sys.path.insert(0, str(ROOT / 'packages/congress_api/tests'))
    import pyarrow as pa
    from congress_api.retention.raw_archive import STATE_SCHEMA, CAPTURE_SCHEMA, LEGACY_STATE_SCHEMA, LEGACY_CAPTURE_SCHEMA
    import congress_api.retention.raw_archive as raw_archive
    if args.ref and args.ref != 'HEAD':
        raw_archive.CAPTURE_SCHEMA = LEGACY_CAPTURE_SCHEMA
        raw_archive.STATE_SCHEMA = LEGACY_STATE_SCHEMA
        state_schema = LEGACY_STATE_SCHEMA
        capture_schema = LEGACY_CAPTURE_SCHEMA
    else:
        state_schema = STATE_SCHEMA
        capture_schema = CAPTURE_SCHEMA
    importer, verifier = implementation(args.ref)
    import inspect
    state = pa.table({field.name: pa.array((f'https://example.test/{i}' for i in range(args.rows)), type=field.type)
                      if field.name == 'url' else pa.nulls(args.rows, type=field.type) for field in state_schema}, schema=state_schema)
    if args.mode == 'preservation':
        return preservation_probe(args, state, verifier)
    raw = b'offline synthetic body'
    sha = hashlib.sha256(raw).hexdigest()
    key = f'bodies/sha256/{sha[:2]}/{sha}.gz'
    class Store:
        def __init__(self):
            self.data = {key: gzip.compress(raw, mtime=0)}
        def read(self, key):
            return self.data.get(key)
        def put(self, key, data, **kwargs):
            self.data[key] = data
    with tempfile.TemporaryDirectory(prefix='recovery-memory-', dir=ROOT) as directory:
        path = Path(directory) / 'body'
        path.write_bytes(raw)
        prepared = []
        for i in range(args.additions):
            url = f'https://example.test/added/{i}'
            prepared.append(dict(original_url=url, preserve_download_state=True,
                record=dict(url=url, retrieved_at='2020-01-01T00:00:00Z', content=dict(sha256=sha, body=None),
                            source_associations=[dict(original_url=url)]), captures=[dict(
                    body_key=key, sha256=sha, bytes=len(raw), context_url=url,
                    retrieved_at='2020-01-01T00:00:00Z', pointer=['content', 'body'])]))
        started = time.monotonic()
        if 'raw_storage' in inspect.signature(importer.import_batch).parameters:
            from native_memory_helpers import memory_raw_storage
            store = Store()
            owner = memory_raw_storage(store, state_schema=state.schema)
            owner.publish(owner.prepare(owner.snapshot(), operation='seed',
                states=state, filename_version=dict(selector_sha256=None, selected_ref=None)))
            result = importer.import_batch(store, prepared=prepared, body_paths={key:path},
                raw_storage=owner, operation='synthetic', source_file='synthetic',
                receipt_prefix='receipts/synthetic', guard=lambda:None,
                journal=lambda *args:None, save_payload=lambda *args:None)
        else:
            result = importer.import_batch(Store(), prepared=prepared, body_paths={key:path},
                captures=pa.Table.from_pylist([], schema=capture_schema), state=state,
                source_file='synthetic', receipt_prefix='receipts/synthetic', guard=lambda:None,
                journal=lambda *args:None, save_payload=lambda *args:None)
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return dict(ref=args.ref or 'worktree', rows=args.rows, additions=args.additions,
                mode=args.mode,
                peak_rss_bytes=rss if sys.platform == 'darwin' else rss*1024,
                import_seconds=round(time.monotonic()-started, 3), complete=result['complete'],
                states_preserved=result['existing_download_states_preserved'], new_pending_states=result['new_pending_states'])


def preservation_probe(args, state, verifier):
    import pyarrow as pa
    import pyarrow.parquet as pq
    from congress_api.retention.raw_archive import CAPTURE_SCHEMA
    with tempfile.TemporaryDirectory(prefix='recovery-memory-', dir=ROOT) as directory:
        root = Path(directory)
        payloads = root / 'payloads'
        (payloads / 'baseline/indexes').mkdir(parents=True)
        (payloads / 'indexes').mkdir()
        (payloads / 'receipts').mkdir()
        pending = pa.Table.from_pylist([dict(url=f'new/{i}', outcome='pending', body_key=None, attempts=0)
                                       for i in range(args.additions)], schema=state.schema)
        pq.write_table(state, payloads / 'baseline/indexes/download-state.parquet')
        pq.write_table(pa.concat_tables([state, pending]), payloads / 'indexes/download-state.parquet')
        captures = pa.table({field.name: pa.nulls(args.rows*3, type=field.type) for field in CAPTURE_SCHEMA}, schema=CAPTURE_SCHEMA)
        for prefix in ('baseline/', ''):
            pq.write_table(captures, payloads / (prefix+'indexes/captures.parquet'))
        result = dict(complete=True, added_capture_rows=0,
                      existing_download_states_preserved=args.rows, new_pending_states=args.additions)
        (payloads / 'import-complete.json').write_text(json.dumps(result))
        events = []
        for key in ('indexes/download-state.parquet', 'indexes/captures.parquet'):
            with (payloads / key).open('rb') as stream:
                sha = hashlib.file_digest(stream, 'sha256').hexdigest()
            events += [dict(event='write_intent', value=dict(key=key, sha256=sha)),
                       dict(event='write_verified', value=dict(key=key))]
        events += [dict(event='import_complete', value=result)]
        (root / 'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
        del state, pending, captures
        started = time.monotonic()
        try:
            result = verifier.verify(root)
        except (TypeError, ValueError):
            result = dict(local_preservation_verified=True, existing_states_preserved=args.rows, new_pending_states=args.additions)
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return dict(ref=args.ref or 'worktree', mode=args.mode, rows=args.rows, additions=args.additions,
                peak_rss_bytes=rss if sys.platform == 'darwin' else rss*1024,
                verify_seconds=round(time.monotonic()-started, 3), **result)


def run(args):
    results = []
    for ref in (args.baseline_ref, args.candidate_ref):
        command = [sys.executable, str(Path(__file__).resolve()), '--child',
                   '--baseline-ref', args.baseline_ref, '--candidate-ref', args.candidate_ref, '--mode', args.mode,
                   '--rows', str(args.rows), '--additions', str(args.additions)]
        if ref:
            command += ['--ref', ref]
        results.append(json.loads(subprocess.check_output(command, cwd=ROOT, text=True)))
    return dict(synthetic_only=True, results=results,
                peak_rss_reduction_bytes=results[0]['peak_rss_bytes']-results[1]['peak_rss_bytes'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-ref', required=True)
    parser.add_argument('--candidate-ref', default='', help='Explicit pre-native Parquet revision.')
    parser.add_argument('--rows', type=int, default=200000)
    parser.add_argument('--additions', type=int, default=1525)
    parser.add_argument('--mode', choices=('import', 'preservation'), default='import')
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--ref', default='', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 0 <= args.rows <= 1500000 or not 0 <= args.additions <= 10000:
        parser.error('Synthetic probe must stay within 1,500,000 rows and 10,000 additions')
    print(json.dumps(child(args) if args.child else run(args), indent=2))
