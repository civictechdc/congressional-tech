"""Bounded 32/64 MiB writer comparison; source decoding policy stays unchanged."""
import argparse
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'apps/site/scripts'))
import pyarrow as pa
import pyarrow.parquet as pq
from filename_budget import ArrowStager, DEFAULT_DECODED_POLICY, bounded_batches, open_parquet
from congress_api.retention.derived_files import custody_identity


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


class Selected:
    def __init__(self, source, groups):
        self.source, self.groups = source, groups
        self.metadata = self
        self.num_row_groups = len(groups)
    def row_group(self, index): return self.source.metadata.row_group(self.groups[index])
    def iter_batches(self, *, row_groups, **kwargs):
        return self.source.iter_batches(row_groups=[self.groups[index] for index in row_groups], **kwargs)


def batches(source, metrics):
    return bounded_batches(source, python_values=False, metrics=metrics)


def exact(source, output):
    left, right = iter(batches(source, {})), iter(batches(output, {}))
    a, b = next(left, None), next(right, None)
    ai = bi = rows = 0
    while a is not None and b is not None:
        count = min(len(a) - ai, len(b) - bi)
        if not a.slice(ai, count).equals(b.slice(bi, count), check_metadata=True):
            raise ValueError('Ordered Arrow values or schema changed')
        rows += count; ai += count; bi += count
        if ai == len(a): a, ai = next(left, None), 0
        if bi == len(b): b, bi = next(right, None), 0
    if a is not None or b is not None: raise ValueError('Row count changed')
    return rows


def worker(args):
    source_path = args.source
    if source_path is None:
        source_path = args.output / 'synthetic.parquet'
        table = pa.table({'value': pa.repeat(pa.scalar('é' * 3500), 8192),
                          'nested': pa.array([[None, '', 'é', 'é']] * 8192)})
        table = table.replace_schema_metadata({b'catalog_id': b'writer-fixture'})
        pq.write_table(table, source_path, row_group_size=1024, compression='zstd', use_dictionary=False)
        del table
    before = custody_identity(source_path)
    report = {'scope': 'bounded selected source groups; not complete catalog qualification',
              'source': str(source_path), 'policy': asdict(DEFAULT_DECODED_POLICY),
              'runtime': {'python': sys.version, 'pyarrow': pa.__version__}, 'arms': {}}
    try:
        with open_parquet(source_path) as source:
            sizes = [sum(source.metadata.row_group(g).column(c).total_uncompressed_size
                     for c in range(source.metadata.num_columns)) for g in range(source.metadata.num_row_groups)]
            largest = max(range(len(sizes)), key=sizes.__getitem__)
            groups = [largest]; rows = source.metadata.row_group(largest).num_rows
            if rows > 8192: raise ValueError('Largest source group exceeds declared 8192-row experiment')
            # Choose a contiguous window deterministically before any value read.
            for candidate in list(range(largest + 1, len(sizes))) + list(range(largest - 1, -1, -1)):
                count = source.metadata.row_group(candidate).num_rows
                if rows + count > 8192: break
                groups.append(candidate); rows += count
                if rows == 8192: break
            groups.sort()
            report['selection'] = {'largest_group': largest, 'physical_bytes_proxy': sizes[largest],
                'groups': groups, 'rows': rows, 'declared_before_decode': True,
                'selection_basis': 'maximum aggregate uncompressed physical chunks; not actual decoded bytes'}
            save(args.output / 'selection.json', report)
            selected = Selected(source, groups)
            native = {}; stages = []; writers = []
            try:
                for mib in (32, 64):
                    path = args.output / f'writer-{mib}.parquet'; metrics = {}
                    writer = pq.ParquetWriter(path, source.schema_arrow, compression='zstd', compression_level=9)
                    writers.append(writer)
                    stage = ArrowStager(writer, source.schema_arrow,
                        policy=replace(DEFAULT_DECODED_POLICY, writer_buffer_bytes=mib * 1024**2), metrics=metrics)
                    stages.append(stage); report['arms'][str(mib)] = {'metrics': metrics}
                started = time.perf_counter()
                for batch in batches(selected, native):
                    for stage in stages: stage.append(batch)
                for stage in stages: stage.flush()
                report['both_writes_seconds'] = time.perf_counter() - started
            finally:
                for writer in writers: writer.close()
            report['native_admission'] = native
            for mib in (32, 64):
                path = args.output / f'writer-{mib}.parquet'
                with open_parquet(path) as output:
                    count = exact(selected, output)
                    footer = path.open('rb')
                    with footer:
                        footer.seek(-8, 2); length = int.from_bytes(footer.read(4), 'little')
                    report['arms'][str(mib)].update(rows=count, exact_equal=True, bytes=path.stat().st_size,
                        row_groups=output.metadata.num_row_groups, footer_bytes=length,
                        max_group_rows=max(output.metadata.row_group(g).num_rows for g in range(output.metadata.num_row_groups)))
            if custody_identity(source_path) != before: raise ValueError('Source custody changed')
        report['status'] = 'complete'
    except BaseException as error:
        report.update(status='failed', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        report['source_preserved'] = custody_identity(source_path) == before
        report['peak_rss_bytes'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024)
        save(args.output / 'worker.json', report)


def main(args):
    if args.worker: return worker(args)
    args.output.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, __file__, '--worker', '--output', str(args.output)]
    if args.source: command += ['--source', str(args.source)]
    started = time.monotonic(); peak = 0; reason = None
    with (args.output / 'stdout.log').open('w') as out, (args.output / 'stderr.log').open('w') as err:
        process = subprocess.Popen(command, stdout=out, stderr=err, start_new_session=True)
        while process.poll() is None:
            result = subprocess.run(['ps', '-o', 'rss=', '-p', str(process.pid)], capture_output=True, text=True)
            if result.stdout.strip(): peak = max(peak, int(result.stdout.strip()) * 1024)
            if peak > args.max_rss_bytes or time.monotonic() - started > args.timeout:
                reason = 'memory' if peak > args.max_rss_bytes else 'time'
                os.killpg(process.pid, 9); break
            time.sleep(.05)
        code = process.wait()
    receipt = {'exit_code': code, 'sampled_peak_rss_bytes': peak, 'ceiling_bytes': args.max_rss_bytes,
               'timeout_seconds': args.timeout, 'seconds': time.monotonic() - started, 'killed': reason}
    if (args.output / 'worker.json').is_file():
        value = json.loads((args.output / 'worker.json').read_text())
        receipt['highwater_peak_rss_bytes'] = value['peak_rss_bytes']
        if value['peak_rss_bytes'] > args.max_rss_bytes: receipt['highwater_exceeded'] = True
    save(args.output / 'watchdog.json', receipt)
    if code or reason or receipt.get('highwater_exceeded'): raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--max-rss-bytes', type=int, default=512 * 1024**2)
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--worker', action='store_true')
    main(parser.parse_args())
