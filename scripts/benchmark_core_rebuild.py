#!/usr/bin/env python3
"""Qualify a local retained-source rebuild against a pinned semantic reference.

Run through offline-python.py. Inputs remain read-only; all writes use an overlay.
Canonical records include every field (including JSON strings and list ordering).
Top-level schema metadata is excluded; field metadata and field types are compared exactly.
"""
import argparse
from collections import Counter
from contextlib import closing
import hashlib
import json
import logging
from pathlib import Path
import platform
import sqlite3
import sys
import os
import threading
import subprocess
import importlib.metadata
import tempfile
import time

import pyarrow.parquet as pq

from congress_api.cli.raw_progress import memory_usage
from congress_api.cli.raw_sync import seed_files
from congress_api.retention.raw_catalog import rebuild_catalog
from congress_api.retention.raw_progress import LOGGER



def process_tree_resident_bytes():
    """Sample Linux RSS for this process and all children, including filename workers."""
    if sys.platform != 'linux':
        return None
    processes = {}
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            status = dict(line.split(':', 1) for line in (entry / 'status').read_text().splitlines() if ':' in line)
            processes[int(entry.name)] = (int(status['PPid']), int(status.get('VmRSS', '0 kB').split()[0]) * 1024)
        except (OSError, KeyError, ValueError):
            continue  # Children may exit between listing and reading.
    descendants = {os.getpid()}
    while True:
        found = {pid for pid, (parent, _) in processes.items() if parent in descendants}
        if found <= descendants:
            break
        descendants.update(found)
    return sum(processes[pid][1] for pid in descendants if pid in processes)


class MemorySampler:
    def __init__(self):
        self.peak = None; self.stop = threading.Event()
        self.thread = threading.Thread(target=self.watch, daemon=True)
    def watch(self):
        while True:
            amount = process_tree_resident_bytes()
            if amount is not None:
                self.peak = max(self.peak or 0, amount)
            if self.stop.wait(0.25):
                return
    def start(self):
        self.thread.start()
    def finish(self):
        self.stop.set(); self.thread.join()


def digest_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def file_properties(path):
    return {'sha256': digest_file(path), 'bytes': path.stat().st_size}


def inventory(root):
    return {str(path.relative_to(root)): {'sha256': digest_file(path), 'bytes': path.stat().st_size}
            for path in sorted(root.rglob('*')) if path.is_file()}


def implementation_inventory(roots=None):
    roots = roots if roots is not None else (
        Path('packages/congress_api/src'), Path('packages/house-naming/src'),
        Path('packages/congress_shared/src'))
    return {str(path): digest_file(path) for base in roots
            for path in sorted(base.rglob('*'))
            if path.is_file() and path.suffix in {'.py', '.json', '.csv'}}


def canonical_record(row):
    return json.dumps(row, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def canonical_table(path, database):
    """Store fixed-size record digests and ordinals, preserving duplicate rows."""
    table = pq.ParquetFile(path)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute('PRAGMA temp_store=FILE')
        connection.execute('CREATE TABLE records (ordinal INTEGER PRIMARY KEY, digest BLOB NOT NULL)')
        ordinal = 0
        for batch in table.iter_batches(batch_size=64):
            records = []
            for row in batch.to_pylist():
                records.append((ordinal, hashlib.sha256(canonical_record(row).encode()).digest()))
                ordinal += 1
            connection.executemany('INSERT INTO records VALUES (?, ?)', records)
        connection.execute('CREATE INDEX record_digest ON records(digest)')
        digest = hashlib.sha256()
        for (value,) in connection.execute('SELECT digest FROM records ORDER BY digest'):
            digest.update(value)
        connection.commit()
    return {'rows': ordinal, 'canonical_sha256': digest.hexdigest(),
            'canonical_algorithm': 'sha256-of-sorted-record-sha256-v1',
            'schema': str(table.schema_arrow.remove_metadata()),
            'schema_sha256': hashlib.sha256(table.schema_arrow.remove_metadata().serialize().to_pybytes()).hexdigest()}


def record_example(path, ordinal, digest, count, other_count):
    """Fetch one mismatched row by its recorded Parquet ordinal, with bounded output."""
    table = pq.ParquetFile(path)
    offset = ordinal
    for group in range(table.num_row_groups):
        size = table.metadata.row_group(group).num_rows
        if offset >= size:
            offset -= size
            continue
        consumed = 0
        for batch in table.iter_batches(batch_size=1024, row_groups=[group]):
            if consumed <= offset < consumed + batch.num_rows:
                row = batch.slice(offset - consumed, 1).to_pylist()[0]
                value = canonical_record(row)
                identifiers = {key: str(row[key])[:256] for key in
                               ('document_id', 'source_id', 'body_key', 'filename', 'source_url')
                               if row.get(key) is not None}
                return {'record_sha256': digest.hex(), 'row_ordinal': ordinal,
                        'multiplicity': count, 'other_multiplicity': other_count,
                        'identifiers': identifiers, 'record_prefix': value[:2048],
                        'record_characters': len(value)}
            consumed += batch.num_rows
    raise ValueError(f'Missing Parquet row ordinal {ordinal}: {path}')


def mismatch_examples(baseline_database, candidate_database, reference, candidate):
    """Merge indexed digest groups; never sort or retain full canonical records."""
    with closing(sqlite3.connect(baseline_database)) as left, closing(sqlite3.connect(candidate_database)) as right:
        query = 'SELECT digest, COUNT(*), MIN(ordinal) FROM records GROUP BY digest ORDER BY digest'
        baseline, actual = iter(left.execute(query)), iter(right.execute(query))
        first, second = next(baseline, None), next(actual, None)
        examples = {'baseline': [], 'candidate': []}
        counts = {'distinct_record_digests_with_different_multiplicity': 0,
                  'reference_excess_rows': 0, 'candidate_excess_rows': 0}
        while first is not None or second is not None:
            if second is None or (first is not None and first[0] < second[0]):
                counts['distinct_record_digests_with_different_multiplicity'] += 1
                counts['reference_excess_rows'] += first[1]
                if len(examples['baseline']) < 2:
                    examples['baseline'].append(record_example(reference, first[2], first[0], first[1], 0))
                first = next(baseline, None)
            elif first is None or second[0] < first[0]:
                counts['distinct_record_digests_with_different_multiplicity'] += 1
                counts['candidate_excess_rows'] += second[1]
                if len(examples['candidate']) < 2:
                    examples['candidate'].append(record_example(candidate, second[2], second[0], second[1], 0))
                second = next(actual, None)
            else:
                if first[1] != second[1]:
                    counts['distinct_record_digests_with_different_multiplicity'] += 1
                    counts['reference_excess_rows'] += max(first[1] - second[1], 0)
                    counts['candidate_excess_rows'] += max(second[1] - first[1], 0)
                    for label, path, row, other in [('baseline', reference, first, second),
                                                   ('candidate', candidate, second, first)]:
                        if len(examples[label]) < 2:
                            examples[label].append(record_example(path, row[2], row[0], row[1], other[1]))
                first, second = next(baseline, None), next(actual, None)
        return examples, counts


def compare_tables(reference, candidate, directory):
    results = {}
    for name in ('document-filenames.parquet', 'documents.parquet'):
        baseline_database = directory / (name + '.baseline.sqlite')
        candidate_database = directory / (name + '.candidate.sqlite')
        print(f'comparison stage: {name} reference canonicalization', file=sys.stderr, flush=True)
        baseline = canonical_table(reference / name, baseline_database)
        print(f'comparison stage: {name} candidate canonicalization', file=sys.stderr, flush=True)
        actual = canonical_table(candidate[name], candidate_database)
        results[name] = {'reference': baseline, 'candidate': actual, 'equivalent': baseline == actual}
        if baseline != actual:
            print(f'comparison stage: {name} mismatch scan', file=sys.stderr, flush=True)
            examples, counts = mismatch_examples(baseline_database, candidate_database, reference / name, candidate[name])
            results[name]['mismatch_examples'] = examples
            results[name]['difference_counts'] = counts
    return results


def compare_only(reference, candidate_root, output, original_report):
    """Recover comparison independently without modifying or relabeling a failed run."""
    from congress_api.retention.catalog_publication import local_catalog_paths, MANIFEST_KEY
    if output.exists():
        raise ValueError('Use a new output directory for each comparison')
    if any(output.resolve().is_relative_to(root.resolve()) for root in (reference, candidate_root)):
        raise ValueError('Comparison output must be outside pinned input directories')
    original_bytes = original_report.read_bytes()
    original = json.loads(original_bytes)
    paths = local_catalog_paths(candidate_root)
    names = ('document-filenames.parquet', 'documents.parquet')
    candidate = dict(zip(names, paths))
    recorded = original.get('result', {})
    expected = tuple(candidate_root / recorded[key] for key in ('filenames_key', 'documents_key'))
    selector = candidate_root / MANIFEST_KEY
    manifest = json.loads(selector.read_bytes())
    if (paths != expected or manifest['generation'] != recorded['generation']
            or manifest['catalog_id'] != recorded['catalog_id']):
        raise ValueError('Selected candidate differs from original benchmark generation or catalog_id')
    inputs = [original_report, *(reference / name for name in names), *paths]
    if selector.is_file():
        inputs.append(selector)
    def pinned():
        return {str(path): {'sha256': digest_file(path), 'bytes': path.stat().st_size} for path in inputs}
    before = pinned()
    if before[str(original_report)]['sha256'] != hashlib.sha256(original_bytes).hexdigest():
        raise RuntimeError('Original report changed before comparison')
    expected_reference = original.get('reference_inventory', {})
    for name in names:
        if before[str(reference / name)] != expected_reference.get(name):
            raise ValueError(f'Reference differs from original benchmark: {name}')
    if local_catalog_paths(candidate_root) != paths:
        raise RuntimeError('Candidate selection changed before comparison')
    original_outputs = original.get('candidate_inventory')
    current_outputs = {name: before[str(path)] for name, path in candidate.items()}
    if original_outputs is not None and current_outputs != original_outputs:
        raise ValueError('Candidate bytes differ from original benchmark inventory')
    original_manifest = original.get('candidate_manifest_inventory')
    if original_manifest is not None and before[str(selector)] != original_manifest:
        raise ValueError('Candidate selector differs from original benchmark inventory')
    output.mkdir(parents=True)
    report = {'status': 'running', 'kind': 'comparison-only-recovery',
              'original_report': str(original_report),
              'original_report_sha256': before[str(original_report)]['sha256'],
              'original_status': original.get('status'),
              'candidate_generation': manifest['generation'], 'candidate_catalog_id': manifest['catalog_id'],
              'candidate_output_provenance': ('Original candidate byte hashes matched; current inputs pinned and rechecked'
                  if original_outputs is not None else
                  'Original report has generation keys and catalog_id but no output hashes; historical byte identity is unverified. Current bytes pinned and rechecked.'),
              'frozen_code_revision': original.get('code_revision'),
              'frozen_code_inventory': original.get('code_inventory'),
              'frozen_benchmark_sha256': original.get('benchmark_sha256'),
              'comparison_script_sha256': digest_file(Path(__file__)), 'input_inventory': before,
              'qualification_scope': 'semantic comparison only; original rebuild measurements and status unchanged'}
    started = time.monotonic()
    try:
        report['semantic_comparison'] = compare_tables(reference, candidate, output)
        report['inputs_unchanged'] = pinned() == before and local_catalog_paths(candidate_root) == paths
        if not report['inputs_unchanged'] or digest_file(Path(__file__)) != report['comparison_script_sha256']:
            raise RuntimeError('Pinned comparison input or script changed')
        report['semantic_equivalence_passed'] = all(item['equivalent'] for item in report['semantic_comparison'].values())
        report['status'] = 'semantic_equivalent' if report['semantic_equivalence_passed'] else 'semantic_mismatch'
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__)
        raise
    finally:
        report['comparison_elapsed_seconds'] = time.monotonic() - started
        (output / 'comparison.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


class StageLog(logging.Handler):
    def __init__(self):
        super().__init__(); self.stages = []; self.current = None
    def emit(self, record):
        if not hasattr(record, 'progress'):
            return
        stage = record.progress['stage']
        if self.current is None or self.current['stage'] != stage:
            self.finish()
            print(f'benchmark stage: {stage}', file=sys.stderr, flush=True)
            self.current = {'stage': stage, 'started': time.monotonic(), 'memory_start': memory_usage(),
                            'process_tree_resident_start_bytes': process_tree_resident_bytes()}
        self.current['memory_last'] = memory_usage()
    def finish(self):
        if self.current is not None:
            self.current['elapsed_seconds'] = time.monotonic() - self.current.pop('started')
            self.current['memory_end'] = memory_usage()
            self.current['process_tree_resident_end_bytes'] = process_tree_resident_bytes()
            self.stages.append(self.current); self.current = None


class MirrorOverlay:
    def __init__(self, root, output):
        self.root, self.output = root, output
        self.reads = Counter(); self.read_bytes = Counter(); self.writes = []
        self.source_inventory = {}; self.source_listings = {}; self.input_hash_seconds = 0.0
    def read(self, key):
        path = self.output / key
        from_mirror = not path.is_file()
        if from_mirror:
            path = self.root / key
        data = path.read_bytes() if path.is_file() else None
        if from_mirror:
            started = time.monotonic()
            observed = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)} if data is not None else None
            self.input_hash_seconds += time.monotonic() - started
            if key in self.source_inventory and self.source_inventory[key] != observed:
                raise RuntimeError(f'Pinned source changed during rebuild: {key}')
            self.source_inventory[key] = observed
        family = key.split('/')[0]
        self.reads[family] += 1; self.read_bytes[family] += len(data or b'')
        return data
    def keys(self, prefix):
        found = sorted(str(path.relative_to(self.root)) for path in (self.root / prefix).rglob('*') if path.is_file())
        if prefix in self.source_listings and self.source_listings[prefix] != found:
            raise RuntimeError(f'Pinned source listing changed during rebuild: {prefix}')
        self.source_listings[prefix] = found
        return sorted(set(found) | {str(path.relative_to(self.output))
                                   for path in (self.output / prefix).rglob('*') if path.is_file()})
    def version(self, key):
        data = self.read(key)
        return hashlib.sha256(data).hexdigest() if data is not None else 'missing'
    def inputs_unchanged(self):
        for key, observed in self.source_inventory.items():
            path = self.root / key
            current = {'sha256': digest_file(path), 'bytes': path.stat().st_size} if path.is_file() else None
            if current != observed:
                return False
        return all(sorted(str(path.relative_to(self.root)) for path in (self.root / prefix).rglob('*') if path.is_file()) == found
                   for prefix, found in self.source_listings.items())
    def put_catalog_manifest(self, data, *, expected_version):
        current = self.read('indexes/catalog.json')
        version = hashlib.sha256(current).hexdigest() if current is not None else None
        if version != expected_version:
            raise RuntimeError('Benchmark selection changed during rebuild')
        self.put('indexes/catalog.json', data)
    def put(self, key, body, *, immutable=False):
        path = self.output / key
        if immutable and path.exists():
            if path.read_bytes() != body:
                raise ValueError('Immutable benchmark output changed')
            return
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(body)
        self.writes.append(key)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mirror', type=Path)
    parser.add_argument('--compare-only', action='store_true')
    parser.add_argument('--candidate-root', type=Path)
    parser.add_argument('--original-report', type=Path)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seed', type=Path, action='append', default=[])
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--repair', action='store_true')
    parser.add_argument('--max-peak-gib', type=float, default=8)
    args = parser.parse_args(argv)
    if args.compare_only:
        if args.candidate_root is None or args.original_report is None:
            parser.error('--compare-only requires --candidate-root and --original-report')
        report = compare_only(args.reference, args.candidate_root, args.output, args.original_report)
        return 0 if report['semantic_equivalence_passed'] else 1
    if args.mirror is None:
        parser.error('--mirror is required for rebuild qualification')
    if args.output.resolve().is_relative_to(args.mirror.resolve()) or args.output.resolve().is_relative_to(args.reference.resolve()):
        raise SystemExit('Output must be outside pinned input directories')
    if args.output.exists():
        raise SystemExit('Use a new output directory for each pinned run')
    args.output.mkdir(parents=True)
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
    report = {'status': 'running', 'code_revision': revision, 'benchmark_sha256': digest_file(Path(__file__)),
              'code_inventory': implementation_inventory(),
              'dependencies': {name: importlib.metadata.version(name) for name in ('pyarrow', 'pydantic')}, 'platform': platform.platform(), 'python': sys.version,
              'workers': args.workers, 'repair': args.repair, 'inspect_bodies': False,
              'memory_budget_bytes': int(args.max_peak_gib * 1024**3),
              'source_inventory_scope': 'all mirror objects read, missing reads, and observed key listings; unrelated bodies excluded',
              'source_snapshot_complete': False,
              'seeds': {str(path): digest_file(path) for path in args.seed},
              'reference_inventory': inventory(args.reference)}
    report_path = args.output / 'benchmark.json'
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    store = MirrorOverlay(args.mirror, args.output / 'objects')
    stages = StageLog(); old_level = LOGGER.level
    LOGGER.setLevel(logging.INFO); LOGGER.addHandler(stages)
    sampler = MemorySampler(); sampler.start()
    started = time.monotonic()
    try:
        report['result'] = rebuild_catalog(store, seeds=seed_files(args.seed), workers=args.workers,
                                           repair=args.repair, inspect_bodies=False)
        report['rebuild_elapsed_seconds'] = time.monotonic() - started
        sampler.finish()
        report['sampled_process_tree_peak_resident_bytes'] = sampler.peak
        report['process_tree_sample_interval_seconds'] = 0.25
        stages.finish()
        report['stages'] = stages.stages
        report['storage_reads'] = dict(store.reads)
        report['storage_read_bytes'] = dict(store.read_bytes)
        report['storage_writes'] = store.writes
        report['rebuild_memory'] = memory_usage()
        report['memory_budget_basis'] = 'sampled Linux process-tree RSS' if sampler.peak is not None else 'unqualified; parent-only high-water mark available'
        report['memory_budget_passed'] = sampler.peak <= report['memory_budget_bytes'] if sampler.peak is not None else None
        def pinned_inputs_unchanged():
            return (store.inputs_unchanged()
                    and inventory(args.reference) == report['reference_inventory']
                    and {str(path): digest_file(path) for path in args.seed} == report['seeds']
                    and implementation_inventory() == report['code_inventory']
                    and digest_file(Path(__file__)) == report['benchmark_sha256'])
        report['inputs_unchanged'] = pinned_inputs_unchanged()
        if not report['inputs_unchanged']:
            raise RuntimeError('Pinned input changed during qualification')
        with tempfile.TemporaryDirectory(prefix='core-equivalence-') as temporary:
            selection = store.read('indexes/catalog.json')
            manifest = json.loads(selection) if selection is not None else None
            candidate = {}
            for name, label in [('document-filenames.parquet', 'filenames'), ('documents.parquet', 'documents')]:
                key = manifest['files'][label]['key'] if manifest else 'indexes/' + name
                path = store.output / key
                candidate[name] = path if path.is_file() else store.root / key
            report['candidate_inventory'] = {name: file_properties(path) for name, path in candidate.items()}
            report['candidate_manifest_inventory'] = ({'sha256': hashlib.sha256(selection).hexdigest(), 'bytes': len(selection)}
                                                       if selection is not None else None)
            report['semantic_comparison'] = compare_tables(args.reference, candidate, Path(temporary))
            report['inputs_unchanged'] = (pinned_inputs_unchanged()
                and {name: file_properties(path) for name, path in candidate.items()} == report['candidate_inventory']
                and store.read('indexes/catalog.json') == selection)
            if not report['inputs_unchanged']:
                raise RuntimeError('Pinned input or candidate changed during comparison')
        report['semantic_equivalence_passed'] = all(r['equivalent'] for r in report['semantic_comparison'].values())
        report['status'] = ('failed' if not report['semantic_equivalence_passed'] or report['memory_budget_passed'] is False
                            else 'passed' if report['memory_budget_passed'] else 'semantic_passed_memory_unqualified')
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__)
        raise
    finally:
        sampler.finish()
        stages.finish(); report['stages'] = stages.stages
        report.setdefault('rebuild_elapsed_seconds', time.monotonic() - started)
        report.setdefault('rebuild_memory', memory_usage())
        report.setdefault('sampled_process_tree_peak_resident_bytes', sampler.peak)
        report['storage_reads'] = dict(store.reads)
        report['storage_read_bytes'] = dict(store.read_bytes)
        report['storage_writes'] = store.writes
        report['source_inventory'] = store.source_inventory
        report['source_listings'] = store.source_listings
        report['input_hash_seconds_in_rebuild'] = store.input_hash_seconds
        LOGGER.removeHandler(stages); LOGGER.setLevel(old_level)
        report_path.write_text(json.dumps(report, indent=2) + '\n')
    return 0 if report['status'] in {'passed', 'semantic_passed_memory_unqualified'} else 1


if __name__ == '__main__':
    raise SystemExit(main())
