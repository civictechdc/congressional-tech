"""Offline decoded preparation fixture with a sampled worker RSS ceiling.

No network, production catalog reads, publishing, or workflow dispatches.
"""
import argparse
from contextlib import nullcontext
from dataclasses import asdict, replace
import gc
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
import time
import tracemalloc

ROOT = Path(__file__).resolve().parents[2]
import ijson
import pyarrow as pa
import pyarrow.parquet as pq
from viewer_publication.filename_budget import DEFAULT_DECODED_POLICY, DecodedBudgetExceeded, bounded_batches, json_chunks
from viewer_publication.filename_json_stream import ObservationCounts
import viewer_publication.filename_observations as observations
import viewer_publication.filename_details as details

spec = importlib.util.spec_from_file_location('measured_publisher', ROOT / 'scripts/publication/publish-filename-viewer.py')
publisher = importlib.util.module_from_spec(spec); spec.loader.exec_module(publisher)


def sha(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def fixture(folder):
    # One 6 MiB Arrow row exceeds the ordinary 4 MiB batch budget. A 10,000
    # observation row exercises fanout; 12,000 other rows exercise unique IDs.
    text = 'é🏛️\n' * (3 * 1024**2 // len('é🏛️\n'.encode()))
    schema = pa.schema([('filename', pa.string()), ('body_key', pa.string()),
        ('state_checked_at', pa.list_(pa.string())), ('source_page_title', pa.list_(pa.string())),
        ('source_occurrences', pa.list_(pa.struct([('label', pa.list_(pa.string()))])))],
        metadata={b'catalog_id': b'decoded-ceiling-fixture'})
    rows = [dict(filename=text, state_checked_at=['2026-10-14T09:00:00.123999-04:00'],
                 source_occurrences=[{'label': [text, '', text[:20]]}, None, {'label': []}]),
            dict(filename='fanout', source_occurrences=[{'label': [str(i), 'é', str(i)]} for i in range(10000)]),
            dict(filename='null', source_occurrences=None), dict(filename='empty', source_occurrences=[])]
    rows.extend(dict(filename=f'file-{i} José 🏛️', source_occurrences=[{'label': [f'unique-{i}', 'x' * 100]},
                    {'label': ['same', 'same']}, {'label': [f'unique-{i}', 'x' * 100]}]) for i in range(12000))
    path = folder / 'source.parquet'
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path, row_group_size=128, compression='zstd')
    # A tiny dictionary-encoded page can expand to a much larger Arrow batch.
    # Measure this separately; footer bytes are not a native decode RSS bound.
    pq.write_table(pa.table({'value': ['é' * 32768] * 1024}), folder / 'dictionary-expanded.parquet',
                   row_group_size=1024, use_dictionary=True, compression='zstd')
    return path


def peak_rss():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if sys.platform == 'darwin' else value * 1024


def worker(source_path, output, refusal):
    output.mkdir()
    original = sha(source_path); metrics = {}; stages = {}
    policy = replace(DEFAULT_DECODED_POLICY, logical_json_bytes=1024**2) if refusal else DEFAULT_DECODED_POLICY
    def stage(name, operation):
        gc.collect(); tracemalloc.reset_peak(); started = time.perf_counter()
        result = operation()
        stages[name] = dict(seconds=time.perf_counter()-started, python_peak_bytes=tracemalloc.get_traced_memory()[1],
                            arrow_retained_bytes=pa.total_allocated_bytes(), process_high_water_rss_bytes=peak_rss())
        return result
    tracemalloc.start()
    try:
        stage('repack_and_full_arrow_equality', lambda: publisher.repack_and_verify(source_path, output / 'sources.parquet',
            decoded_policy=policy, metrics=metrics))
        with pq.ParquetFile(source_path) as source, ObservationCounts(source) as counts:
            index = stage('observations_and_full_value_verification', lambda: observations.publish_observations(
                source, output, counts=counts, policy=policy, metrics=metrics))
            stage('details_and_full_emitted_value_verification', lambda: details.publish_details(
                source, output / 'details.parquet', observation_counts=counts, policy=policy, metrics=metrics))
        expanded = source_path.with_name('dictionary-expanded.parquet')
        stage('dictionary_expansion_and_full_arrow_equality', lambda: publisher.repack_and_verify(
            expanded, output / 'dictionary-expanded.parquet', decoded_policy=policy, metrics=metrics))
        converted = 0
        try:
            with pq.ParquetFile(expanded) as dictionary_source:
                for batch in bounded_batches(dictionary_source, policy=replace(policy, row_arrow_bytes=1024)):
                    converted += len(batch.to_pylist())
            raise AssertionError('Dictionary expansion should have refused')
        except DecodedBudgetExceeded:
            assert converted == 0
        stages['dictionary_row_refusal_before_python'] = {'converted_rows': converted, 'refused': True}
        with pq.ParquetFile(output / 'details.parquet') as detail_file:
            stages['detail_layout'] = dict(rows=detail_file.metadata.num_rows, row_groups=detail_file.metadata.num_row_groups,
                max_group_rows=max(detail_file.metadata.row_group(i).num_rows for i in range(detail_file.metadata.num_row_groups)),
                bytes=(output / 'details.parquet').stat().st_size)
        status = 'accepted'
    except DecodedBudgetExceeded:
        if not refusal: raise
        status = 'refused'
        receipt = json.loads((output / 'preparation-memory-failure.json').read_text())
        assert not (output / 'observation-index.json').exists() and not receipt['partial_publication_accepted']
    assert sha(source_path) == original
    result = dict(status=status, source_sha256=original, source_preserved=True, stages=stages, metrics=metrics,
        policy=asdict(policy), peak_rss_bytes=peak_rss(), output_files={p.name: dict(bytes=p.stat().st_size, sha256=sha(p)) for p in output.iterdir()})
    if not refusal:
        result['parts'] = sum(len(b['parts']) for name in ('observations', 'references') for b in index[name]['blocks'])
        assert metrics['decoded_parts'] == result['parts']
    print(json.dumps(result))


def ceiling_run(source, output, refusal, ceiling):
    command = [sys.executable, __file__, '--worker', str(source), '--worker-output', str(output)]
    if refusal: command.append('--refusal')
    with tempfile.TemporaryFile(mode='w+') as stdout, tempfile.TemporaryFile(mode='w+') as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr)
        maximum = 0
        try:
            while process.poll() is None:
                sample = subprocess.run(['ps', '-o', 'rss=', '-p', str(process.pid)], text=True, capture_output=True)
                if sample.returncode == 0 and sample.stdout.strip():
                    maximum = max(maximum, int(sample.stdout.strip()) * 1024)
                    if maximum > ceiling:
                        process.kill(); raise RuntimeError(f'Fixture worker exceeded RSS ceiling: {maximum} > {ceiling}')
                time.sleep(.05)
        finally:
            if process.poll() is None: process.kill()
            process.wait()
        stdout.seek(0); stderr.seek(0)
        if process.returncode: raise RuntimeError(stderr.read())
        result = json.loads(stdout.read().splitlines()[-1])
        assert result['peak_rss_bytes'] <= ceiling, result['peak_rss_bytes']
        result.update(ceiling_bytes=ceiling, sampled_peak_rss_bytes=maximum, ceiling_passed=True,
                      ceiling_method='50 ms ps watchdog plus process lifetime ru_maxrss; fixture verification, not OS allocation quota')
        return result


def encoder_comparison():
    # Isolate the allocation removed from detail verification: the old complete
    # batch Python list/JSON string/UTF-8 bytes versus one row and encoded piece.
    table = pa.table({'label': ['José 🏛️' * 100 for _ in range(4000)],
                      'values': [['é', '', 'é']] * 4000})
    result = {}
    for name in ('whole_batch', 'streamed_rows'):
        gc.collect(); tracemalloc.start(); started = time.perf_counter(); digest = hashlib.sha256()
        if name == 'whole_batch':
            digest.update(json.dumps(table.to_pylist(), ensure_ascii=False, separators=(',', ':')).encode())
        else:
            digest.update(b'[')
            for index, scalar in enumerate(table.to_struct_array()):
                if index: digest.update(b',')
                for piece in json_chunks(scalar.as_py()): digest.update(piece)
            digest.update(b']')
        _, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
        result[name] = dict(python_peak_bytes=peak, seconds=time.perf_counter()-started, sha256=digest.hexdigest())
    assert result['whole_batch']['sha256'] == result['streamed_rows']['sha256']
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=Path); parser.add_argument('--worker-output', type=Path)
    parser.add_argument('--refusal', action='store_true'); parser.add_argument('--output', type=Path)
    parser.add_argument('--ceiling-mib', type=int, default=512)
    parser.add_argument('--artifacts', type=Path, help='Fresh directory retaining fixture and refused outputs for inspection')
    args = parser.parse_args()
    if args.worker: worker(args.worker, args.worker_output, args.refusal); return
    if args.artifacts:
        args.artifacts.mkdir(parents=True, exist_ok=False)
    storage = nullcontext(args.artifacts) if args.artifacts else tempfile.TemporaryDirectory(prefix='preparation-decoded-')
    with storage as folder:
        folder = Path(folder); source = fixture(folder)
        with pq.ParquetFile(source) as file:
            metadata = dict(rows=file.metadata.num_rows, row_groups=file.metadata.num_row_groups,
                max_physical_group_bytes=max(sum(g.column(i).total_uncompressed_size for i in range(g.num_columns))
                    for g in (file.metadata.row_group(n) for n in range(file.metadata.num_row_groups))))
        result = dict(scope='bounded offline adversarial fixtures, not full-catalog qualification',
            runtime=dict(python=sys.version.split()[0], pyarrow=pa.__version__, ijson=ijson.__version__, ijson_backend=ijson.backend),
            source=metadata, artifacts_retained=bool(args.artifacts), accepted=ceiling_run(source, folder / 'accepted', False, args.ceiling_mib * 1024**2),
            refused=ceiling_run(source, folder / 'refused', True, args.ceiling_mib * 1024**2),
            detail_encoder=encoder_comparison())
        text = json.dumps(result, indent=2) + '\n'
        if args.output: args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(text)
        print(text)


if __name__ == '__main__': main()
