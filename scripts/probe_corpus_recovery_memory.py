"""Offline synthetic RSS comparison; no network, credentials, or retained inputs.

Run from the repository with --baseline-ref to compare an earlier implementation
against the current worktree. Each measurement uses a fresh child process. This
measures end-to-end import memory, including required encoded index payloads.
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

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'packages/congress_api/src')]


def child(args):
    import pyarrow as pa
    from congress_api.retention.raw_archive import STATE_SCHEMA, CAPTURE_SCHEMA
    # Evaluate only tracked local code selected by the caller. No git mutation.
    for name in ('assemble_corpus_recovery_import', 'import_corpus_recovery_batch',
                 'verify_corpus_recovery_import_preservation'):
        module = types.ModuleType(name)
        module.__file__ = str(ROOT / 'scripts' / (name + '.py'))
        source = (subprocess.check_output(['git', 'show', f'{args.ref}:scripts/{name}.py'], cwd=ROOT, text=True)
                  if args.ref else Path(module.__file__).read_text())
        sys.modules[name] = module
        exec(compile(source, module.__file__, 'exec'), module.__dict__)
    importer = sys.modules['import_corpus_recovery_batch']
    # Generate Arrow columns directly so Python input-row allocation does not
    # conceal the cost of converting the entire baseline back to dictionaries.
    state = pa.table({field.name: pa.array((f'https://example.test/{i}' for i in range(args.rows)), type=field.type)
                      if field.name == 'url' else pa.nulls(args.rows, type=field.type) for field in STATE_SCHEMA}, schema=STATE_SCHEMA)
    if args.mode == 'preservation':
        return preservation_probe(args, state)
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
        result = importer.import_batch(Store(), prepared=prepared, body_paths={key:path},
            captures=pa.Table.from_pylist([], schema=CAPTURE_SCHEMA), state=state,
            source_file='synthetic', receipt_prefix='receipts/synthetic', guard=lambda:None,
            journal=lambda *args:None, save_payload=lambda *args:None)
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return dict(ref=args.ref or 'worktree', rows=args.rows, additions=args.additions,
                mode=args.mode,
                peak_rss_bytes=rss if sys.platform == 'darwin' else rss*1024,
                import_seconds=round(time.monotonic()-started, 3), complete=result['complete'],
                states_preserved=result['existing_download_states_preserved'], new_pending_states=result['new_pending_states'])


def preservation_probe(args, state):
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
        result = sys.modules['verify_corpus_recovery_import_preservation'].verify(root)
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return dict(ref=args.ref or 'worktree', mode=args.mode, rows=args.rows, additions=args.additions,
                peak_rss_bytes=rss if sys.platform == 'darwin' else rss*1024,
                verify_seconds=round(time.monotonic()-started, 3), **result)


def run(args):
    results = []
    for ref in (args.baseline_ref, ''):
        command = [sys.executable, str(Path(__file__).resolve()), '--child', '--mode', args.mode,
                   '--rows', str(args.rows), '--additions', str(args.additions)]
        if ref:
            command += ['--ref', ref]
        results.append(json.loads(subprocess.check_output(command, cwd=ROOT, text=True)))
    return dict(synthetic_only=True, results=results,
                peak_rss_reduction_bytes=results[0]['peak_rss_bytes']-results[1]['peak_rss_bytes'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-ref', default='37ee074')
    parser.add_argument('--rows', type=int, default=200000)
    parser.add_argument('--additions', type=int, default=1525)
    parser.add_argument('--mode', choices=('import', 'preservation'), default='import')
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--ref', default='', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 0 <= args.rows <= 1500000 or not 0 <= args.additions <= 10000:
        parser.error('Synthetic probe must stay within 1,500,000 rows and 10,000 additions')
    print(json.dumps(child(args) if args.child else run(args), indent=2))
