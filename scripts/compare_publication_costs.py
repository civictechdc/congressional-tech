#!/usr/bin/env python3
"""Compare bounded publication trials with identical fixtures and measured work.

Each arm uses fresh process runs from measure_publication_control.py. This tool
checks exact payload values before reporting separate success/poll/resume costs.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from statistics import median
import pyarrow.parquet as pq


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def outputs(directory):
    root = directory / 'attempt/publication'
    if (root / 'manifest.json').stat().st_size > 4 * 1024**2:
        raise ValueError('Publication manifest exceeds comparison byte limit')
    manifest = json.loads((root / 'manifest.json').read_text())
    files = {name: (root / item['path'], item) for name, item in manifest['files'].items()}
    if not (root / manifest['ids']).resolve().is_relative_to(root.resolve()):
        raise ValueError('ID locator escapes the publication directory')
    for path in sorted((root / manifest['ids']).glob('*.bin')):
        if path.stat().st_size > 32 * 1024**2 or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('ID shard exceeds comparison bounds')
        files['ids/' + path.name] = (path, {'bytes': path.stat().st_size, 'sha256': digest(path)})
    if len([name for name in files if name.startswith('ids/')]) != 256:
        raise ValueError('Expected all 256 source-ID shards')
    for name, (path, item) in files.items():
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('Payload locator escapes the publication directory')
        if item['bytes'] > 32 * 1024**2 or path.stat().st_size != item['bytes'] or digest(path) != item['sha256']:
            raise ValueError('Bounded payload identity differs: ' + name)
    return manifest, files


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def bounded_bytes(path, directory, limit, label):
    if not path.is_file():
        raise ValueError(label + ' evidence is missing')
    if not path.resolve().is_relative_to(directory.resolve()) or path.stat().st_size > limit:
        raise ValueError(label + ' exceeds comparison bounds')
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(label + ' exceeds comparison bounds')
    return raw


def published_recovery(directory, manifest):
    pointer_raw = bounded_bytes(directory / 'published-pointer.json', directory, 4 * 1024**2, 'Published pointer')
    pointer = json.loads(pointer_raw)
    if (pointer.get('version') != 1 or pointer.get('catalog_id') != manifest['info']['catalog_id']
            or pointer.get('source_manifest') != manifest['source_manifest']):
        raise ValueError('Published pointer catalog or source identity changed')
    item = pointer.get('recovery', {})
    if (type(item.get('bytes')) is not int or not 0 < item['bytes'] <= 32 * 1024**2
            or not isinstance(item.get('sha256'), str) or not re.fullmatch('[a-f0-9]{64}', item['sha256'])
            or not isinstance(item.get('path'), str)
            or not re.fullmatch(r'releases/[a-f0-9]{32}/[a-f0-9]{32}/viewer-v2/recovery-status\.json', item['path'])):
        raise ValueError('Published recovery descriptor exceeds comparison bounds or is invalid')
    raw = bounded_bytes(directory / 'published-recovery.json', directory, 32 * 1024**2, 'Published recovery')
    if len(raw) != item['bytes'] or hashlib.sha256(raw).hexdigest() != item['sha256']:
        raise ValueError('Published recovery bytes differ from selected identity')
    value = json.loads(raw)
    expected = {name: manifest['info'][name] for name in ('catalog_id', 'rows', 'entries')}
    if value.get('version') != 1 or any(value.get(name) != expected[name] for name in expected):
        raise ValueError('Published recovery catalog identity changed')
    return raw, {'sha256': item['sha256'], 'bytes': item['bytes'],
                 'pointer_sha256': hashlib.sha256(pointer_raw).hexdigest()}


def compare_outputs(left, right, *, before_prepared_required=True, after_prepared_required=True,
                    accepted_identity=None):
    if type(before_prepared_required) is not bool or type(after_prepared_required) is not bool:
        raise ValueError('Prepared recovery capability must be explicit boolean evidence')
    accepted_identity = accepted_identity or {'present': False, 'sha256': None}
    before, old = outputs(left)
    after, new = outputs(right)
    stable = lambda manifest: {key: value for key, value in manifest.items() if key not in ('published_at', 'files')}
    if old.keys() != new.keys() or stable(before) != stable(after):
        raise ValueError('Publication routing, format, compression policy or catalog information changed')
    checks = []
    for name in old:
        path, item = old[name]; other, other_item = new[name]
        descriptor = lambda value: {key: item for key, item in value.items() if key not in ('bytes', 'sha256')}
        if item.keys() != other_item.keys() or descriptor(item) != descriptor(other_item):
            raise ValueError('Publication file descriptor changed: ' + name)
        exact_bytes = item['sha256'] == other_item['sha256'] and item['bytes'] == other_item['bytes']
        if path.suffix == '.parquet':
            a, b = pq.read_table(path), pq.read_table(other)
            if not a.schema.equals(b.schema, check_metadata=True) or not a.equals(b):
                raise ValueError('Parquet values/schema changed: ' + name)
            method = 'complete schema and ordered Arrow values'
        elif not exact_bytes:
            raise ValueError('Exact sidecar bytes changed: ' + name)
        else:
            method = 'exact complete SHA256 bytes'
        checks.append({'file': name, 'method': method, 'byte_identical': exact_bytes,
                       'before_sha256': item['sha256'], 'after_sha256': other_item['sha256']})
    binding = json.loads(new['review_binding'][0].read_text())
    published = [published_recovery(directory, manifest)
                 for directory, manifest in ((left, before), (right, after))]
    if published[0][0] != published[1][0]:
        raise ValueError('Published recovery bytes changed between comparison arms')
    recovery_checks, recovery_values = [], []
    for directory, manifest, required, (selected, _) in (
            (left, before, before_prepared_required, published[0]),
            (right, after, after_prepared_required, published[1])):
        path = directory / 'attempt/publication/recovery-prepared.json'
        if not required and not path.exists() and not path.is_symlink():
            recovery_checks.append(None); recovery_values.append(None)
            continue
        raw = bounded_bytes(path, directory, 32 * 1024**2, 'Prepared recovery')
        value = json.loads(raw)
        expected_inputs = {'version': 1, 'source_manifest': manifest['source_manifest'],
            'files': {name: manifest['files'][name] for name in ('filenames', 'groups')},
            'catalog': {name: manifest['info'][name] for name in ('catalog_id', 'rows', 'entries')},
            'accepted_present': accepted_identity['present'], 'accepted_sha256': accepted_identity['sha256']}
        if value.get('version') != 1 or value.get('inputs') != expected_inputs:
            raise ValueError('Prepared recovery inputs differ from manifest or accepted source identity')
        if encoded(value.get('value')) != selected:
            raise ValueError('Prepared recovery value differs from selected recovery bytes')
        recovery_checks.append({'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)})
        value['inputs']['files'] = {name: descriptor(item) for name, item in value['inputs']['files'].items()}
        recovery_values.append(value)
    both_prepared = all(value is not None for value in recovery_values)
    if both_prepared and recovery_values[0] != recovery_values[1]:
        raise ValueError('Prepared recovery values or input metadata changed')
    return {'files': checks, 'catalog_id': after['info']['catalog_id'],
            'published_recovery': {'before': published[0][1], 'after': published[1][1], 'byte_identical': True},
            'recovery_prepared': {'before': recovery_checks[0], 'after': recovery_checks[1],
                'before_required': before_prepared_required, 'after_required': after_prepared_required,
                'published_value_verified': True, 'exact_value_and_normalized_inputs': both_prepared},
            'review_binding': {'sha256': new['review_binding'][1]['sha256'],
                'bound': len(binding['rows']), 'withdrawn': len(binding['withdrawn']),
                'withdrawn_reasons': dict(Counter(item['reason'] for item in binding['withdrawn']))}}


def run(before_dirs, after_dirs, output):
    if len(before_dirs) != len(after_dirs) or not before_dirs:
        raise ValueError('Supply equal nonzero before/after trial counts')
    before = [json.loads((p / 'costs.json').read_text()) for p in before_dirs]
    after = [json.loads((p / 'costs.json').read_text()) for p in after_dirs]
    shared = ('source_manifest_sha256', 'source_files', 'python', 'executable',
              'maximum_source_bytes', 'controlled_request_latency_ms', 'measurement_sources',
              'command_process_model', 'runtime')
    reference = before[0]['inputs']
    for receipt in before + after:
        if type(receipt['inputs'].get('prepared_recovery_supported')) is not bool:
            raise ValueError('Prepared recovery capability must be explicit boolean evidence')
        if any(receipt['inputs'][key] != reference[key] for key in shared):
            raise ValueError('Trials differ in fixture, runtime or instrumentation')
        if 'runner_failure' in receipt['outcomes'] or receipt['sampling_errors']:
            raise ValueError('Trial has a runner or memory-sampling failure; preserve it separately')
        expected = {'accepted_preparation': 'complete', 'successful_publication': 'complete',
                    'unchanged_poll': 'complete', 'explicit_resume_failure': 'failed',
                    'explicit_resume': 'complete'}
        stages = {stage['stage']: stage['status'] for stage in receipt['stages']}
        if stages != expected or len(receipt['stages']) != len(expected):
            raise ValueError('Trial does not contain the expected five completed/failure stages')
        for name, status in {'successful_publication': 'published', 'unchanged_poll': 'unchanged',
                             'explicit_resume_failure': 'failed', 'explicit_resume': 'published'}.items():
            if receipt['outcomes'].get(name, {}).get('status') != status:
                raise ValueError('Trial outcome differs: ' + name)
        failure = receipt['outcomes']['explicit_resume_failure']
        if failure.get('error_type') != 'RuntimeError' or failure.get('error') != 'Explicit bounded fixture probe failure':
            raise ValueError('Trial failed before the intended probe operation')
    if any(receipt['inputs']['prepared_recovery_supported'] is not True for receipt in after):
        raise ValueError('Candidate must support prepared recovery verification')
    if len({r['inputs']['revision'] for r in before}) != 1 or len({r['inputs']['revision'] for r in after}) != 1:
        raise ValueError('Each comparison arm must use one pinned revision')
    for arm in (before, after):
        if any(r['inputs']['source_identity'] != arm[0]['inputs']['source_identity'] for r in arm):
            raise ValueError('Working source identity changed within a comparison arm')
        if any(r['inputs']['prepared_recovery_supported'] != arm[0]['inputs']['prepared_recovery_supported'] for r in arm):
            raise ValueError('Prepared recovery capability changed within a comparison arm')
    accepted = reference['source_files'].get('viewer-publications/recoveries/accepted.json')
    accepted_identity = {'present': accepted is not None, 'sha256': accepted['sha256'] if accepted is not None else None}
    payloads = [compare_outputs(a, b,
                    before_prepared_required=old['inputs']['prepared_recovery_supported'],
                    after_prepared_required=new['inputs']['prepared_recovery_supported'],
                    accepted_identity=accepted_identity)
                for a, b, old, new in zip(before_dirs, after_dirs, before, after, strict=True)]
    def summarize(receipts):
        result = {}
        for stage in receipts[0]['stages']:
            name = stage['stage']; rows = [next(s for s in r['stages'] if s['stage'] == name) for r in receipts]
            keys = set().union(*(r['counts'] for r in rows))
            result[name] = {'status': stage['status'], 'seconds_median': median(r['seconds'] for r in rows),
                'seconds_range': [min(r['seconds'] for r in rows), max(r['seconds'] for r in rows)],
                'maximum_sampled_process_tree_rss_bytes': max(r['sampled_process_tree_rss_peak_bytes'] for r in rows),
                'maximum_stage_end_scratch_bytes': max(r['scratch_bytes'] for r in rows),
                'median_counts': {key: median(r['counts'].get(key, 0) for r in rows) for key in sorted(keys)}}
        success = [[s for s in r['stages'] if s['stage'] in ('accepted_preparation', 'successful_publication')]
                   for r in receipts]
        totals = [sum(s['seconds'] for s in rows) for rows in success]
        count_keys = set().union(*(s['counts'] for rows in success for s in rows))
        result['complete_success_path'] = {'seconds_median': median(totals), 'seconds_range': [min(totals), max(totals)],
            'critical_path': ['accepted_preparation', 'successful_publication'],
            'maximum_sampled_process_tree_rss_bytes': max(s['sampled_process_tree_rss_peak_bytes'] for rows in success for s in rows),
            'maximum_stage_end_scratch_bytes': max(s['scratch_bytes'] for rows in success for s in rows),
            'median_total_counts': {key: median(sum(s['counts'].get(key, 0) for s in rows) for rows in success)
                                    for key in sorted(count_keys)}}
        return result
    result = {'version': 1, 'scope': 'bounded generated fixture, controlled 1ms remote request latency; local implementation only',
        'trials_per_arm': len(before), 'before_revision': before[0]['inputs']['revision'], 'after_revision': after[0]['inputs']['revision'],
        'shared_inputs': {key: reference[key] for key in shared}, 'before': summarize(before), 'after': summarize(after),
        'prepared_recovery_supported': {'before': before[0]['inputs']['prepared_recovery_supported'],
                                        'after': after[0]['inputs']['prepared_recovery_supported']},
        'exact_output_check': payloads, 'trial_receipts': {'before': [str(p / 'costs.json') for p in before_dirs], 'after': [str(p / 'costs.json') for p in after_dirs]},
        'limits': before[0]['limits'], 'interpretation': 'Do not sum stage/component percentages or infer full-catalog/workflow performance from this fixture.'}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'before_revision': result['before_revision'], 'after_revision': result['after_revision'],
        'trials': len(before), 'before_success': result['before']['complete_success_path'], 'after_success': result['after']['complete_success_path'],
        'payload_files_per_trial': len(payloads[0]['files']), 'review_binding': payloads[0]['review_binding']}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path, nargs='+', required=True)
    parser.add_argument('--after', type=Path, nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.before, args.after, args.output)
