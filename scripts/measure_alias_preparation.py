"""Measure exact alias indexing on a bounded high-cardinality/fanout fixture."""
import argparse
import gc
import hashlib
import importlib.util
import json
from pathlib import Path
import resource
import struct
import subprocess
import sys
import tempfile
import time
import tracemalloc

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/site/scripts'))


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value


def worker(root, old):
    import filename_recoveries
    # Exclude module initialization for both paths. The old alias module imports
    # saved-response helpers eagerly; the new implementation imports its index
    # lazily. Process RSS below still includes all initialization allocations.
    import filename_alias_index
    if old:
        previous_alias = load(root / 'old_aliases.py', 'old_aliases')
        previous = load(root / 'old_recoveries.py', 'old_recoveries')
        previous.catalog_aliases = previous_alias.catalog_aliases
        function = previous.index_recoveries
    else:
        function = filename_recoveries.index_recoveries
    manifest = json.loads((root / 'manifest.json').read_text())
    scans = []
    original = pq.ParquetFile
    class Counted:
        def __init__(self, *args, **kwargs): self.reader = original(*args, **kwargs)
        def __getattr__(self, name): return getattr(self.reader, name)
        def __enter__(self): return self
        def __exit__(self, *args): self.reader.close()
        def iter_batches(self, *args, **kwargs):
            scans.append(True)
            yield from self.reader.iter_batches(*args, **kwargs)
    pq.ParquetFile = Counted
    metrics = {}; gc.collect(); tracemalloc.start(); started = time.perf_counter()
    try:
        result = function(root, manifest, [], **({} if old else {'metrics': metrics}))
    finally:
        pq.ParquetFile = original
    seconds = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
    encoded = json.dumps(result, sort_keys=True, separators=(',', ':')).encode()
    if not old:
        assert metrics['exact_output_bytes'] == len(encoded)
    return dict(seconds=seconds, python_peak_bytes=peak,
                peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024),
                output_bytes=len(encoded), output_sha256=hashlib.sha256(encoded).hexdigest(),
                source_rows=manifest['info']['rows'], source_scans=len(scans), metrics=metrics)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--worker', type=Path); parser.add_argument('--old', action='store_true')
    parser.add_argument('--output', type=Path); args = parser.parse_args()
    if args.worker: print(json.dumps(worker(args.worker, args.old))); return
    with tempfile.TemporaryDirectory(prefix='alias-measure-') as folder:
        root = Path(folder); rows = []
        count = 12000
        for index in range(count):
            # Half share one retained destination; half have distinct targets.
            target = 0 if index < count // 2 else index
            rows.append(dict(source_url=f'https://old.test/{index:06}', body_key=None,
                             source_resolved_url=[f'https://new.test/{target:06}.pdf']))
        for index in [0, *range(count // 2, count)]:
            digest = hashlib.sha256(str(index).encode()).hexdigest()
            rows.append(dict(source_url=f'https://new.test/{index:06}.pdf',
                body_key=f'bodies/sha256/{digest[:2]}/{digest}.gz', source_resolved_url=None))
        path = root / 'filenames.parquet'; pq.write_table(pa.Table.from_pylist(rows), path)
        groups = root / 'groups.bin'; groups.write_bytes(b''.join(struct.pack('<I', index % 100) for index in range(len(rows))))
        files = {name: dict(path=file.name, bytes=file.stat().st_size, sha256=hashlib.sha256(file.read_bytes()).hexdigest())
                 for name, file in [('filenames', path), ('groups', groups)]}
        (root / 'manifest.json').write_text(json.dumps(dict(files=files, info=dict(rows=len(rows), entries=100, catalog_id='bounded'))))
        for name in ('aliases', 'recoveries'):
            (root / f'old_{name}.py').write_bytes(subprocess.check_output(['git', 'show', f'9a1baed:apps/site/scripts/filename_{name}.py'], cwd=ROOT))
        result = {name: json.loads(subprocess.check_output([sys.executable, __file__, '--worker', str(root), *options], text=True))
                  for name, options in [('before', ['--old']), ('after', [])]}
        assert result['before']['output_sha256'] == result['after']['output_sha256']
        result['scope'] = 'bounded offline high-cardinality/fanout fixture; no production extrapolation'
        text = json.dumps(result, indent=2) + '\n'
        if args.output: args.output.write_text(text)
        print(text)


if __name__ == '__main__': main()
