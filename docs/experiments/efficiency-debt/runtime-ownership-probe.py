"""Bounded local runtime admission probe; never creates a real S3 client."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

SOURCE_DIRS = ('packages/congress_api/src', 'packages/house-naming/src',
    'packages/congress_shared/src', 'packages/committee_meeting/src',
    'packages/youtube_api/src', 'packages/corpus_recovery/src',
    'packages/viewer_publication/src', 'apps/committee_youtube/src',
    'apps/site/scripts', 'docs/youtube-coverage/research/scripts')


def fixture(root, destination):
    """Retain one small source-only alternate checkout and sealed import."""
    selected = destination / 'selected'
    files = [path for directory in SOURCE_DIRS for path in (root / directory).rglob('*')
             if path.is_file() and path.suffix in {'.py', '.json', '.csv'} and '__pycache__' not in path.parts]
    files.append(root / 'scripts/viewer_release_identity.py')
    size = sum(path.stat().st_size for path in files)
    assert size < 16 * 1024**2
    hashes = {}
    for path in files:
        relative = path.relative_to(root)
        target = selected / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        hashes[str(relative)] = hashlib.sha256(target.read_bytes()).hexdigest()
    batch = destination / 'batch'; batch.mkdir()
    imported = destination / 'imported'; (imported / 'payloads/indexes').mkdir(parents=True)
    (batch / 'prepared-source-records.json').write_text(json.dumps([{'captures': [{'body_key': 'body'}]}]))
    (batch / 'zip-receipts.json').write_text('[]')
    def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
    pins = {name: digest(batch / name) for name in ('prepared-source-records.json', 'zip-receipts.json')}
    (batch / 'manifest.json').write_text(json.dumps({'files': pins}))
    (batch / 'source-record-preparation.json').write_text(json.dumps({'unresolved': [], 'batch_manifest_sha256': digest(batch / 'manifest.json')}))
    (batch / 'import-readiness.json').write_text(json.dumps({'files': pins, 'capture_rows': 1, 'distinct_capture_bodykeys': 1}))
    (imported / 'payloads/import-complete.json').write_text(json.dumps({'complete': True, 'added_capture_rows': 1, 'distinct_bodies': 1}))
    events = [{'event': 'pins', 'value': {str(batch / name): digest(batch / name) for name in ('manifest.json', 'prepared-source-records.json', 'import-readiness.json')}},
              {'event': 'import_complete', 'value': {'complete': True, 'added_capture_rows': 1, 'distinct_bodies': 1}}]
    (imported / 'events.jsonl').write_text('\n'.join(map(json.dumps, events)))
    for name in ('captures.parquet', 'download-state.parquet'):
        (imported / 'payloads/indexes' / name).write_bytes(b'not read before client sentinel')
    (destination / '.cache').mkdir()
    (destination / 'baseline.json').write_text('{}')
    (destination / 'r2.conf').write_text('[congressionalraw]\nendpoint=https://invalid.test\naccess_key_id=sentinel\nsecret_access_key=sentinel\n')
    return {'source_bytes': size, 'source_files': len(files), 'source_sha256': hashes}


COMMAND = r'''
import importlib.util, inspect, json, shutil, sys, time, types
from pathlib import Path
from types import SimpleNamespace
driver, original, fixture, conflict, attempt = map(str, sys.argv[1:])
original, fixture = Path(original), Path(fixture)
started = time.perf_counter()
runtime = fixture/'selected'
if conflict in ('missing_corpus', 'symlink_corpus'):
    runtime = fixture/conflict
    if not runtime.exists():
        shutil.copytree(fixture/'selected', runtime,
            ignore=lambda directory, names: ['corpus_recovery'] if Path(directory).name == 'packages' else [])
        if conflict == 'symlink_corpus':
            (runtime/'packages/corpus_recovery').symlink_to(original/'packages/corpus_recovery', target_is_directory=True)
# A conflict is a real maintained module from the ambient checkout, not a stub.
if conflict in ('congress_api', 'corpus_recovery', 'viewer_publication'):
    __import__(conflict)
elif conflict == 'filename_resources':
    sys.path.insert(0, str(original/'apps/site/scripts'))
    __import__(conflict)
elif conflict == 'unknown':
    sys.modules['filename_unknown'] = types.ModuleType('filename_unknown')
elif conflict == 'extended_path':
    sys.path.insert(0, str(fixture/'selected/packages/congress_api/src'))
    import congress_api
    congress_api.__path__.append(str(original/'packages/congress_api/src/congress_api'))
spec = importlib.util.spec_from_file_location('publication_dispatch', driver)
dispatch = importlib.util.module_from_spec(spec); spec.loader.exec_module(dispatch)
dispatch.cloud_clear = lambda: None
import boto3
calls = {'client': 0, 'ownership_check': 0, 'direct_load': 0}
admission_calls = 0
owners = {}
direct_owners = {}
check_started = []
check_seconds = []
def profile(frame, event, value):
    global admission_calls
    if event == 'call' and frame.f_code.co_name == 'verify_import' and frame.f_code.co_filename.endswith('/corpus_recovery/admission.py'):
        admission_calls += 1
    if frame.f_code.co_filename == driver:
        if frame.f_code.co_name == 'check':
            if event == 'call':
                calls['ownership_check'] += 1
                check_started.append(time.perf_counter())
            elif event == 'return':
                check_seconds.append(time.perf_counter() - check_started.pop())
        if event == 'return' and frame.f_code.co_name == 'load' and value is not None:
            calls['direct_load'] += 1
            direct_owners[value.__name__] = str(Path(value.__file__).resolve())
            for child in vars(value).values():
                if isinstance(child, types.ModuleType) and child.__name__.startswith('filename_'):
                    direct_owners[child.__name__] = str(Path(child.__file__).resolve())
sys.setprofile(profile)
class ClientBoundary(Exception): pass
warm_boundary = None
def client(*args, **kwargs):
    global warm_boundary
    calls['client'] += 1
    local = inspect.currentframe().f_back.f_locals
    selected = local.get('selected')
    if selected is not None:
        # Count real filesystem resolution work on an unchanged admitted graph.
        # Pause profiling so the initial admission work counts remain separate.
        sys.setprofile(None)
        original_resolve = Path.resolve
        resolves = 0
        def resolve(path, *a, **kw):
            nonlocal resolves
            resolves += 1
            return original_resolve(path, *a, **kw)
        Path.resolve = resolve
        durations = []
        try:
            for _ in range(25):
                before = time.perf_counter()
                selected.check(local['builder'], local['publisher'])
                durations.append(time.perf_counter() - before)
        finally:
            Path.resolve = original_resolve
            sys.setprofile(profile)
        warm_boundary = {'checks': len(durations), 'path_resolves': resolves, 'seconds': durations}
    raise ClientBoundary('stopped before any real client or remote operation')
boto3.client = client
error = None
try:
    dispatch.run(SimpleNamespace(batch=fixture/'batch', imported=fixture/'imported', runtime=runtime,
        execute=True, resume=False, destination=fixture/attempt, control_root=fixture,
        baseline=fixture/'baseline.json', config=fixture/'r2.conf'))
except BaseException as caught:
    error = {'type': type(caught).__name__, 'message': str(caught)}
sys.setprofile(None)
prefixes = ('congress_api', 'house_naming', 'congress_shared', 'committee_meeting', 'youtube_api',
            'corpus_recovery', 'viewer_publication', 'committee_explorer', 'filename_', 'viewer_release_identity')
for name, module in list(sys.modules.items()):
    if name.startswith(prefixes):
        owners[name] = str(Path(module.__file__).resolve()) if getattr(module, '__file__', None) else None
print(json.dumps({'conflict': conflict, 'calls': calls, 'error': error, 'owners': owners,
    'direct_owners': direct_owners, 'elapsed_seconds': time.perf_counter()-started,
    'ownership_check_seconds': check_seconds,
    'admission_calls': admission_calls,
    'warm_boundary': warm_boundary,
    'remote_operations_possible': False}))
'''


def probe(driver, root, destination, conflict='clean', attempt='attempt'):
    started = time.perf_counter()
    result = subprocess.run([sys.executable, '-B', '-c', COMMAND, str(driver), str(root), str(destination), conflict, attempt],
                            text=True, capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    value = json.loads(result.stdout)
    value['process_seconds'] = time.perf_counter() - started
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--driver', type=Path, required=True)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.fixture.exists():
        args.fixture.mkdir(parents=True)
        (args.fixture/'fixture.json').write_text(json.dumps(fixture(args.root, args.fixture), indent=2)+'\n')
    values = [probe(args.driver.resolve(), args.root.resolve(), args.fixture.resolve(), conflict, args.output.stem+'-'+conflict)
              for conflict in ('clean', 'congress_api', 'filename_resources', 'corpus_recovery', 'viewer_publication',
                               'unknown', 'extended_path', 'missing_corpus', 'symlink_corpus')]
    args.output.write_text(json.dumps({'driver_sha256': hashlib.sha256(args.driver.read_bytes()).hexdigest(), 'cases': values}, indent=2)+'\n')
