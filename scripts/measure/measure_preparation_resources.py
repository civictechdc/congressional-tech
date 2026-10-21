"""Compare publication-only Catalog state and exact navigation buffers offline.

The preparation-readers receipt is
docs/experiments/publication-remediation/preparation-readers.md and
docs/experiments/publication-remediation/evidence/preparation-memory.json.
Pass --revision to select the baseline files.
"""
import argparse
import gc
import hashlib
import importlib.util
import json
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
import time
import tracemalloc

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


def catalog(path, minimal):
    from viewer_publication import filename_viewer as viewer
    gc.collect(); before = pa.total_allocated_bytes(); tracemalloc.start(); started = time.perf_counter()
    with viewer.Catalog(path, search_indexes=not minimal) as value:
        seconds = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        result = dict(seconds=seconds, python_peak_bytes=peak, arrow_retained_bytes=pa.total_allocated_bytes()-before,
                      filter_bytes=sum(column.nbytes for column in value.filter_text.values()),
                      source_rows=len(value.table), documents=len(value.documents),
                      peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--worker', type=Path)
    parser.add_argument('--minimal', action='store_true'); parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(catalog(args.worker, args.minimal))); return
    with tempfile.TemporaryDirectory(prefix='preparation-measure-') as folder:
        folder = Path(folder); rows = []
        for index in range(25000):
            entry = index // 5
            rows.append(dict(source_id=hashlib.sha256(str(index).encode()).hexdigest(),
                document_id=hashlib.sha256(f'doc-{entry}'.encode()).hexdigest(), filename=f'file-{entry}.pdf',
                source_url=f'https://example.test/doc-{entry}', body_key=None,
                format=['pdf'], record_role=['document'], congress=['119'],
                document_kind=['hearing'], document_family=['congressional_proceeding']))
        sources = folder / 'sources.parquet'
        table = pa.Table.from_pylist(rows).replace_schema_metadata({b'catalog_id': b'bounded-memory'})
        pq.write_table(table, sources)
        pq.write_table(table.take(pa.array(range(0, len(rows), 5))), folder / 'documents.parquet')
        measured = {}
        for name, options in [('search', []), ('preparation', ['--minimal'])]:
            measured[name] = json.loads(subprocess.check_output(
                [sys.executable, __file__, '--revision', args.revision, '--worker', str(sources), *options], text=True))
        old_path = folder / 'old_navigation.py'
        old_path.write_bytes(subprocess.check_output(['git', 'show', f'{args.revision}:apps/site/scripts/filename_navigation.py'], cwd=ROOT))
        functions = [('before', load(old_path, 'old_navigation').publish_navigation),
                     ('after', load(ROOT / 'packages/viewer_publication/src/viewer_publication/filename_navigation.py', 'new_navigation').publish_navigation)]
        navigation = {}
        groups = [i // 20 for i in range(200000)]; preferred = list(range(0, len(groups), 20))
        for name, function in functions:
            output = folder / name; output.mkdir(); gc.collect(); tracemalloc.start(); tracemalloc.reset_peak()
            started = time.perf_counter(); files = function(groups, preferred, output)
            seconds = time.perf_counter() - started; _, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
            navigation[name] = dict(seconds=seconds, python_peak_bytes=peak,
                hashes={key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in files.items()})
        assert navigation['before']['hashes'] == navigation['after']['hashes']
        result = dict(catalog=measured, navigation=navigation, scope='bounded offline fixtures; no production extrapolation')
        text = json.dumps(result, indent=2) + '\n'
        if args.output: args.output.write_text(text)
        print(text)


if __name__ == '__main__': main()
