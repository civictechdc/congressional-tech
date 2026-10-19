#!/usr/bin/env python3
"""Measure the maintained complete viewer builder without acquiring source data.

Every trial gets a new output directory. Failed logs, outputs and receipts remain.
The source manifest and both tables are fully verified before timed preparation.
Browser receipts are supplied by the maintained-loader browser runner separately;
missing browser or Linux evidence always leaves the adoption gate unqualified.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import time
import traceback

from process_rss import resident_tree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/site/scripts'))


def load_builder():
    spec = importlib.util.spec_from_file_location('viewer_benchmark_builder', ROOT / 'apps/site/scripts/publish-filename-viewer.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def save(path, value):
    temporary = path.with_suffix('.partial')
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')
    temporary.replace(path)


def worker(args):
    import pyarrow as pa
    pa.set_cpu_count(1); pa.set_io_thread_count(1)
    builder = load_builder()
    result = {'status': 'running', 'policy': builder.DEFAULT_COMPRESSION_POLICY._replace(level=args.level)._asdict(),
              'runtime': {'python': platform.python_version(), 'pyarrow': pa.__version__,
                          'platform': platform.platform(), 'machine': platform.machine()}, 'timings': {}}
    save(args.output / 'worker.json', result)
    def progress(event):
        with (args.output / 'stages.jsonl').open('a') as stream:
            stream.write(json.dumps(dict(event, monotonic=time.monotonic()), sort_keys=True) + '\n')
            stream.flush(); os.fsync(stream.fileno())
    try:
        result['manifest'] = builder.publish(args.source, args.output / 'publication',
            review_identities=args.review_identities,
            compression_policy=builder.DEFAULT_COMPRESSION_POLICY._replace(level=args.level),
            stage_timings=result['timings'], stage_event=progress)
        result['inventory'] = {str(path.relative_to(args.output / 'publication')):
                              {'bytes': path.stat().st_size, 'sha256': builder.digest(path)}
                              for path in sorted((args.output / 'publication').rglob('*')) if path.is_file()}
        result['status'] = 'complete'
    except BaseException as error:
        result.update(status='failed', error=str(error), traceback=traceback.format_exc())
        raise
    finally:
        save(args.output / 'worker.json', result)



def compare_outputs(reference, candidate):
    """Only reencoded filename bytes may differ; the document archive is exact."""
    left, right = reference['worker'], candidate['worker']
    changed_allowed = {left['manifest']['files']['filenames']['path']}
    changed_allowed.add('manifest.json')
    return (left['manifest']['source_manifest'] == right['manifest']['source_manifest']
            and {name: item for name, item in left['inventory'].items() if name not in changed_allowed}
            == {name: item for name, item in right['inventory'].items() if name not in changed_allowed})


def exact_table_verification(worker):
    """Distinguish complete archive byte identity from filename Arrow equality."""
    manifest, timings = worker['manifest'], worker['timings']
    archive = manifest['files']['documents']
    source = manifest['source_manifest']['files']['documents']
    copy = timings.get('documents_copy', {})
    inventory = worker.get('inventory', {}).get(archive['path'], {})
    return (timings.get('filenames_repack', {}).get('exact_equal') is True
            and copy.get('verification_method') == 'complete_sha256_bytes'
            and archive.get('encoding') == dict(mode='source_passthrough', source_sha256=source['sha256'])
            and all(copy.get(key) == archive.get(key) == source[key] for key in ('bytes', 'sha256', 'rows'))
            and all(inventory.get(key) == source[key] for key in ('bytes', 'sha256')))


def compare_browser(reference, candidate):
    """Require identical pinned cases/results before comparing individual p95s."""
    if not reference or not candidate or reference.get('status') != 'complete' or candidate.get('status') != 'complete':
        return {'qualified': False, 'reason': 'missing_complete_browser_receipt'}
    names = ('catalog_id', 'source_manifest', 'review_identity_sha256', 'review_descriptor',
             'review_data_sha256', 'accepted_sha256', 'recovery_sha256', 'cases_sha256', 'cases', 'expected')
    identities = all(reference['inputs'].get(name) == candidate['inputs'].get(name) for name in names)
    identities &= all(reference.get(name) == candidate.get(name) for name in ('runtime', 'loader_hashes', 'bundle_sha256', 'cache_condition'))
    if not identities:
        return {'qualified': False, 'reason': 'browser_inputs_runtime_or_cases_differ'}
    def cases(receipt):
        grouped = {}
        for sample in receipt['samples']:
            grouped.setdefault(sample['case_id'], []).append(sample)
        return grouped
    before, after = cases(reference), cases(candidate)
    if before.keys() != after.keys():
        return {'qualified': False, 'reason': 'browser_case_inventory_differs'}
    measurements = {}
    for name in before:
        a, b = before[name], after[name]
        if ({sample['result_sha256'] for sample in a} != {sample['result_sha256'] for sample in b}
                or len({sample['result_sha256'] for sample in a + b}) != 1):
            return {'qualified': False, 'reason': 'browser_result_values_differ', 'case': name}
        def p95(values):
            import math
            values = sorted(sample['milliseconds'] for sample in values)
            return values[math.ceil(.95 * len(values)) - 1]
        previous, current = p95(a), p95(b)
        measurements[name] = {'baseline_p95_ms': previous, 'candidate_p95_ms': current,
                              'ratio': current / previous if previous else (1 if not current else float('inf'))}
    enough = min(reference['repetitions'], candidate['repetitions']) >= 5
    return {'qualified': enough and all(item['ratio'] <= 1.1 for item in measurements.values()),
            'exact_result_equality': True, 'repetitions_sufficient': enough, 'cases': measurements}


def browser_trial(args, trial, cases):
    command = [args.node, str(ROOT / 'scripts/benchmark_viewer_browser.mjs'),
               '--publication', str((trial / 'publication').resolve()), '--output', str((trial / 'browser').resolve()),
               '--review-data', str(args.review_data.resolve()), '--review-descriptor', str(args.review_descriptor.resolve()),
               '--review-identities', str(args.review_identities.resolve()), '--repeats', str(args.browser_repeats),
               '--python', sys.executable]
    if args.accepted:
        command += ['--accepted', str(args.accepted.resolve())]
    if args.browser_executable:
        command += ['--browser-executable', str(args.browser_executable.resolve())]
    if cases:
        command += ['--cases', str(cases.resolve())]
    with (trial / 'browser-stdout.log').open('wb') as stdout, (trial / 'browser-stderr.log').open('wb') as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            code = process.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, 15)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, 9); process.wait()
            raise
        if code:
            raise subprocess.CalledProcessError(code, command)
    value = json.loads((trial / 'browser/browser-receipt.json').read_text())
    if value['inputs']['manifest_sha256'] != load_builder().digest(trial / 'publication/manifest.json'):
        raise ValueError('Browser receipt does not bind this preparation')
    return value, trial / 'browser/cases.json'

def main(args):
    builder = load_builder()
    args.output.mkdir(parents=True, exist_ok=False)
    selected = json.loads((args.source / 'indexes/catalog.json').read_text())
    builder.verify(args.source, selected)
    review_hash = builder.digest(args.review_identities) if args.review_identities else None
    binding = {'scope': args.scope, 'source_manifest': selected, 'source_manifest_sha256': builder.digest(args.source / 'indexes/catalog.json'),
               'review_identity_sha256': review_hash,
               'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
               'builder_sha256': builder.digest(ROOT / 'apps/site/scripts/publish-filename-viewer.py'),
               'cache_condition': 'warm filesystem; no privileged cache flush; fresh process per trial',
               'limits': {'process_tree_rss_bytes': args.max_rss_bytes, 'seconds_per_trial': args.timeout,
                          'minimum_free_bytes': args.minimum_free_bytes},
               'order': [level for round_index in range(args.repeats)
                         for level in (args.levels if round_index % 2 == 0 else list(reversed(args.levels)))]}
    save(args.output / 'inputs.json', binding)
    results = []
    cases = args.browser_cases
    for index, level in enumerate(binding['order']):
        trial = args.output / f'trial-{index + 1:02d}-level-{level}'
        trial.mkdir()
        report = {'level': level, 'status': 'running', 'peak_process_tree_rss_bytes': 0}
        if shutil.disk_usage(args.output).free < args.minimum_free_bytes:
            report.update(status='blocked', reason='scratch_free_space_below_declared_floor')
            save(trial / 'result.json', report); results.append(report); break
        command = [sys.executable, str(Path(__file__).resolve()), '--worker', '--source', str(args.source),
                   '--output', str(trial), '--level', str(level)]
        if args.review_identities:
            command += ['--review-identities', str(args.review_identities)]
        started = time.monotonic()
        with (trial / 'stdout.log').open('wb') as stdout, (trial / 'stderr.log').open('wb') as stderr:
            process = subprocess.Popen(command, stdout=stdout, stderr=stderr, start_new_session=True)
            while process.poll() is None:
                try:
                    report['peak_process_tree_rss_bytes'] = max(report['peak_process_tree_rss_bytes'], resident_tree(process.pid))
                except (OSError, ValueError, subprocess.SubprocessError) as error:
                    report['memory_sampling_error'] = str(error)
                reason = ('memory_bound' if report['peak_process_tree_rss_bytes'] > args.max_rss_bytes else
                          'time_bound' if time.monotonic() - started > args.timeout else
                          'scratch_free_space_below_declared_floor' if shutil.disk_usage(args.output).free < args.minimum_free_bytes else None)
                if reason:
                    report['reason'] = reason
                    os.killpg(process.pid, 15)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, 9)
                    break
                time.sleep(0.25)
            report['exit_code'] = process.wait()
        report['elapsed_seconds'] = time.monotonic() - started
        report['scratch_bytes'] = sum(path.stat().st_size for path in trial.rglob('*') if path.is_file())
        if (trial / 'worker.json').exists():
            report['worker'] = json.loads((trial / 'worker.json').read_text())
        report['status'] = 'complete' if report['exit_code'] == 0 and report.get('worker', {}).get('status') == 'complete' else 'failed'
        if report['status'] == 'complete' and args.review_data:
            try:
                report['browser'], cases = browser_trial(args, trial, cases)
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                report['status'] = 'failed'
                report['browser_error'] = str(error)
        save(trial / 'result.json', report); results.append(report)
        save(args.output / 'results.json', {'inputs': binding, 'trials': results, 'adoption': 'unqualified'})
        if report['status'] != 'complete':
            break  # Preserve failure; a later attempt requires an explicit new invocation.
    summary = {'inputs': binding, 'trials': results, 'adoption': 'unqualified', 'gates': {}}
    arms = {level: [r for r in results if r['level'] == level and r['status'] == 'complete'] for level in args.levels}
    for level, trials in arms.items():
        if len(trials) == args.repeats:
            summary['gates'][str(level)] = {'median_preparation_seconds': statistics.median(r['worker']['timings']['total_seconds'] for r in trials),
                'median_output_bytes': statistics.median(sum(v['bytes'] for v in r['worker']['inventory'].values()) for r in trials),
                'exact_filename_values_and_archive_bytes': all(exact_table_verification(r['worker']) for r in trials),
                'compression_policy_applies_to': ['filenames'], 'document_encoding': 'source_passthrough'}
    if 19 in arms and len(arms[19]) == args.repeats:
        baseline = summary['gates']['19']
        for level in args.levels:
            if level == 19 or str(level) not in summary['gates']:
                continue
            gate = summary['gates'][str(level)]
            gate['preparation_reduction'] = 1 - gate['median_preparation_seconds'] / baseline['median_preparation_seconds']
            gate['output_growth'] = gate['median_output_bytes'] / baseline['median_output_bytes'] - 1
            gate['timing_and_size_pass'] = gate['preparation_reduction'] >= .25 and gate['output_growth'] <= .15
            reference = arms[19][0]
            gate['exact_derived_id_review_equality'] = all(compare_outputs(reference, trial) for trial in arms[19] + arms[level])
            gate['browser'] = [compare_browser(reference.get('browser'), trial.get('browser')) for trial in arms[level]]
            gate['linux_preparation'] = all(trial['worker']['runtime']['platform'].startswith('Linux-') for trial in arms[19] + arms[level])
            gate['linux_browser'] = all(trial.get('browser', {}).get('runtime', {}).get('platform') == 'linux' for trial in arms[19] + arms[level])
            gate['qualified'] = (args.scope == 'complete-catalog' and args.repeats >= 3 and gate['timing_and_size_pass'] and gate['exact_filename_values_and_archive_bytes']
                                 and gate['exact_derived_id_review_equality'] and gate['linux_preparation'] and gate['linux_browser']
                                 and all(item['qualified'] for item in gate['browser']))
    qualified = [int(level) for level, gate in summary['gates'].items() if gate.get('qualified')]
    summary['adoption'] = ('qualified_candidate' if qualified else 'unqualified')
    if qualified:
        summary['recommended_level'] = min(qualified, key=lambda level: summary['gates'][str(level)]['median_output_bytes'])
    summary['remaining_gates'] = ([] if qualified else [
        'three complete Linux measurements per arm', 'exact derived IDs, review pins and fixed browser results',
        'complete preparation reduction >=25%, output growth <=15%, every browser case p95 regression <=10%'])
    save(args.output / 'results.json', summary)
    print(json.dumps({'output': str(args.output), 'statuses': [r['status'] for r in results], 'adoption': summary['adoption']}))
    return 1 if any(r['status'] != 'complete' for r in results) else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', choices=('fixture', 'complete-catalog'), default='fixture')
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--review-identities', type=Path, default=ROOT / 'apps/site/document-review-identities.json')
    parser.add_argument('--review-data', type=Path, help='Pinned local review data enables the real browser gate')
    parser.add_argument('--review-descriptor', type=Path, default=ROOT / 'apps/site/document-review-publication.json')
    parser.add_argument('--accepted', type=Path)
    parser.add_argument('--browser-cases', type=Path)
    parser.add_argument('--browser-repeats', type=int, default=5)
    parser.add_argument('--browser-executable', type=Path)
    parser.add_argument('--node', default='node')
    parser.add_argument('--levels', type=int, nargs='+', choices=(19, 9, 3), default=[19, 9, 3])
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--max-rss-bytes', type=int, default=3 * 1024**3)
    parser.add_argument('--minimum-free-bytes', type=int, default=12 * 1024**3)
    parser.add_argument('--timeout', type=float, default=5400)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--level', type=int, choices=(19, 9, 3), default=19)
    options = parser.parse_args()
    if options.repeats < 1 or options.max_rss_bytes < 1:
        parser.error('repeat and memory bounds must be positive')
    if options.worker:
        worker(options)
    else:
        raise SystemExit(main(options))
