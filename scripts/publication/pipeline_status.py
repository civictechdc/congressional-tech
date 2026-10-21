#!/usr/bin/env python3
"""Read existing run evidence without writing status, resuming or publishing."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import subprocess
import urllib.request

DEFAULT_PROGRESS = 'https://pub-1b36ca710ab14e7f8e65813c41761724.r2.dev/status/raw-source-sync.json'
MAX_JSON_BYTES = 2 * 1024 * 1024


def json_bytes(raw):
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError('Status input exceeds 2 MiB')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('Status input must be a JSON object')
    return value


def read_json(location):
    if str(location).startswith(('https://', 'http://')):
        request = urllib.request.Request(str(location), headers={
            'User-Agent': 'congressional-tech-pipeline-status/1.0', 'Cache-Control': 'no-cache'})
        with urllib.request.urlopen(request, timeout=10) as response:
            return json_bytes(response.read(MAX_JSON_BYTES + 1))
    with Path(location).open('rb') as stream:
        return json_bytes(stream.read(MAX_JSON_BYTES + 1))


def github_run(run_id, repository):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Repository must be owner/name')
    result = subprocess.run(['gh', 'api', f'repos/{repository}/actions/runs/{run_id}'],
                            check=True, capture_output=True, timeout=20)
    return json_bytes(result.stdout)


def instant(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Timestamp has no time zone')
    return parsed


def identity(value):
    return (str(value.get('github_run_id', '')), str(value.get('github_run_attempt', '')),
            value.get('code_revision'))


def heartbeat(value, expected, now, previous=None):
    problems = []
    result = {'identity_matches': identity(value) == expected,
              'monotonicity': 'not_checked_without_previous_snapshot'}
    if not result['identity_matches']:
        return dict(result, state='unbound', issues=['Heartbeat run, attempt or revision differs from GitHub'])
    for key in ('elapsed_seconds', 'stage_elapsed_seconds', 'seconds_since_progress', 'completed', 'total'):
        number = value.get(key)
        if number is not None and (type(number) not in (int, float) or not math.isfinite(number) or number < 0):
            problems.append(f'Invalid {key}')
    counters = value.get('counters', {})
    if not isinstance(counters, dict) or any(type(n) is not int or n < 0 for n in counters.values()):
        problems.append('Invalid cumulative counters')
    if problems:
        return dict(result, state='invalid', issues=problems)
    completed, total = value.get('completed'), value.get('total')
    if completed is not None and total is not None and completed > total:
        problems.append('Stage completed count exceeds its total')
    updated = instant(value['updated_at'])
    if updated > now:
        problems.append('Heartbeat timestamp is in the future')
    stale = False
    if value.get('status') == 'running':
        expiry = value.get('heartbeat_expires_at')
        stale = not expiry or instant(expiry) <= now
        if expiry and instant(expiry) <= updated:
            problems.append('Heartbeat expiration does not follow its update')
    if previous is not None:
        if identity(previous) != expected:
            problems.append('Previous heartbeat belongs to another run, attempt or revision')
        else:
            before = heartbeat(previous, expected, now)
            if before['state'] in {'invalid', 'unbound'}:
                problems.append('Previous heartbeat is invalid')
            else:
                if updated < instant(previous['updated_at']):
                    problems.append('Heartbeat update moved backwards')
                for key in ('elapsed_seconds',):
                    if value.get(key, 0) < previous.get(key, 0):
                        problems.append(f'{key} moved backwards')
                for key, count in previous.get('counters', {}).items():
                    if counters.get(key, -1) < count:
                        problems.append(f'Cumulative counter moved backwards: {key}')
                if value.get('stage') == previous.get('stage'):
                    old, new = previous.get('completed'), value.get('completed')
                    if old is not None and (new is None or new < old):
                        problems.append('Current stage completed count moved backwards')
                result['monotonicity'] = 'checked' if not problems else 'failed'
    return dict(result, state='invalid' if problems else 'stale' if stale else value.get('status', 'unknown'),
                updated_at=value['updated_at'], age_seconds=round(max(0, (now - updated).total_seconds()), 1),
                stage=value.get('stage'), completed=completed, total=total, unit=value.get('unit'),
                elapsed_seconds=value.get('elapsed_seconds'), stage_elapsed_seconds=value.get('stage_elapsed_seconds'),
                counters=counters, issues=problems)


def continuation(path, expected):
    """Report recorded acceptance; do not hash large prepared outputs or reuse them."""
    path = Path(path)
    event_source = None
    journal_path = path.parent / 'events.jsonl'
    if journal_path.exists():
        from viewer_publication.local import LegacyLocalJournal, read_local_journal
        try:
            value, inspection = read_local_journal(journal_path)
            event_source = dict(source='validated_local_events', path=str(journal_path),
                                recorded_events=inspection['events'], inspected_bytes=inspection['bytes'])
        except LegacyLocalJournal:
            value = read_json(path)
    else:
        value = read_json(path)
    binding = value.get('binding', {})
    observed = (str(binding.get('run_id', binding.get('github_run_id', ''))),
                str(binding.get('run_attempt', binding.get('github_run_attempt', ''))),
                binding.get('provenance_revision', binding.get('code_runtime', {}).get('revision', binding.get('code_revision'))))
    phases = value.get('phases', {})
    if not isinstance(phases, dict):
        raise ValueError('Continuation phases must be an object')
    local_recovery = 'batch' in binding or any(name in phases for name in ('catalog', 'mappings'))
    order = ('catalog', 'mappings', 'prepared', 'publication') if local_recovery else ('prepared','publication')
    local_state = {'recorded_phases': list(phases), 'next_incomplete_phase': next((name for name in order if name not in phases), None),
                   'integrity_rechecked': False, 'remote_reconciliation': 'not_performed'}
    if event_source or local_recovery:
        local_state['write_observation'] = event_source or dict(source='checkpoint_only', path=str(path),
            latest_event_state='unknown; checkpoint write counts may be stale',
            next_check='Inspect the retained local events.jsonl before any explicit reconciliation')
    progress_path = path.parent / 'reconciliation-progress.json'
    if progress_path.exists():
        from viewer_publication.reconciliation import read_progress
        try:
            local_state['last_reconciliation_observation'] = read_progress(progress_path, binding=binding)
        except (OSError, ValueError, KeyError, TypeError):
            local_state['last_reconciliation_observation'] = dict(state='unavailable', observation_only=True,
                next_check='Inspect the retained observation file; it is invalid, unreadable or belongs to different inputs.')
    if local_recovery:
        from corpus_recovery.diagnostics import catalog_build_observation
        if observation := catalog_build_observation(path.parent, phases):
            local_state['catalog_build'] = observation
    writes = value.get('writes', {})
    if (not isinstance(writes, dict) or len(writes) > 8192
            or any(not isinstance(key, str) or not key or len(key) > 2048
                   or not isinstance(item, dict) or type(item.get('verified')) is not bool
                   for key, item in writes.items())):
        raise ValueError('Continuation writes malformed or exceeds inspection limit')
    local_state.update(recorded_writes=len(writes), uncertain_writes=[key for key, item in writes.items() if not item['verified']],
                       recorded_verified_writes=sum(item['verified'] for item in writes.values()))
    if observed != expected:
        return {'state': 'unbound', 'local_phase_observation': local_state, 'issues': ['Continuation lacks matching run, attempt and revision'],
                'accepted_outputs': [], 'public_readback': 'not_checked'}
    phases = value.get('phases', {})
    outputs = [{'phase': name, 'recorded_files': len(phase.get('files', {})), 'integrity_rechecked': False}
               for name, phase in phases.items()]
    publication = phases.get('publication', {}).get('result', {}).get('status')
    # The new viewer journal binds its first event to the exact preparation.
    # Read only these small records; Continuation's mutating resume is not used.
    journal = sorted((path.parent / 'journal').glob('*.json'))
    if journal:
        if len(journal) > 4096:
            raise ValueError('Publication journal exceeds the bounded status inspection')
        preparation_path = path.parent / 'preparation.json'
        with preparation_path.open('rb') as stream:
            raw = stream.read(MAX_JSON_BYTES + 1)
        preparation = json_bytes(raw)
        if preparation.get('binding') != binding:
            raise ValueError('Preparation and continuation bindings differ')
        digest, total = None, 0
        for index, event_path in enumerate(journal):
            if event_path.name != f'{index:08d}.json':
                raise ValueError('Publication journal has missing or foreign entries')
            with event_path.open('rb') as stream:
                event_raw = stream.read(MAX_JSON_BYTES + 1)
            total += len(event_raw)
            if total > 32 * 1024 * 1024:
                raise ValueError('Publication journal exceeds 32 MiB status inspection')
            event = json_bytes(event_raw)
            if event.get('sequence') != index or event.get('previous') != digest:
                raise ValueError('Publication journal chain differs')
            if index == 0 and (event.get('event') != 'attempt_started'
                              or event.get('value', {}).get('binding', {}).get('preparation_sha256') != sha256(raw).hexdigest()):
                raise ValueError('Publication journal is not bound to this preparation')
            if event.get('event') == 'publication_completed':
                publication = event['value'].get('status')
            elif event.get('event') == 'publication_failed':
                publication = 'failed'
            digest = sha256(event_raw).hexdigest()
    if publication in ('published', 'recovery_updated'):
        local_state['next_incomplete_phase'] = None
    return {'state': 'bound', 'accepted_outputs': outputs, 'local_phase_observation': local_state, 'recorded_publication_status': publication,
            'public_readback': 'not_checked',
            'issues': [], 'pending': ['Prepared output integrity has not been rechecked',
                                      'Current public publication readback has not been checked']}


def summarize(run_id, github, progress, *, now=None, previous=None, receipt=None, errors=()):
    now = now or datetime.now(timezone.utc)
    result = {'run_id': str(run_id), 'observed_at': now.isoformat(), 'issues': list(errors),
              'public_readback': 'not_checked', 'accepted_outputs': []}
    if not github or str(github.get('id')) != str(run_id):
        result.update(state='unknown', github=None, heartbeat=None,
                      next_action='Read the requested GitHub run before attributing progress or accepted outputs')
        result['issues'].append('GitHub run unavailable or has a different identity')
        return result
    expected = (str(run_id), str(github.get('run_attempt', '')), github.get('head_sha'))
    if not expected[1] or not expected[2]:
        raise ValueError('GitHub run is missing attempt or revision')
    result['github'] = {key: github.get(key) for key in ('status', 'conclusion', 'run_attempt', 'head_sha', 'html_url')}
    result['state'] = (github.get('conclusion') or 'unknown') if github.get('status') == 'completed' else github.get('status', 'unknown')
    result['heartbeat'] = heartbeat(progress, expected, now, previous) if progress else None
    if result['heartbeat']:
        result['issues'].extend(result['heartbeat']['issues'])
        if result['heartbeat']['state'] == 'stale':
            result['issues'].append('Running heartbeat expired; GitHub terminal status takes precedence')
    if receipt:
        try:
            result['continuation'] = continuation(receipt, expected)
            result['accepted_outputs'] = result['continuation']['accepted_outputs']
            result['issues'].extend(result['continuation']['issues'])
        except (OSError, ValueError, KeyError, TypeError) as error:
            result['issues'].append(f'Continuation unavailable or invalid: {error}')
    result['pending'] = ['Current public publication readback has not been checked']
    if github.get('status') != 'completed':
        result['next_action'] = 'Inspect the job log and heartbeat; wait while the run remains active'
    elif github.get('conclusion') != 'success':
        result['next_action'] = 'Inspect the failed job and retained receipts; any resume requires explicit reconciliation'
    else:
        result['next_action'] = 'Inspect accepted outputs and public verification before declaring publication complete'
    return result


def format_status(value):
    lines = [f"Run {value['run_id']}: {value['state']}"]
    if github := value.get('github'):
        lines.append(f"Attempt {github['run_attempt']}; revision {github['head_sha']}")
    if progress := value.get('heartbeat'):
        lines.append('Heartbeat: ' + progress['state'])
        if progress.get('stage'):
            count = f"{progress.get('completed')} / {progress.get('total')} {progress.get('unit') or ''}"
            lines.append(f"Stage: {progress['stage']} ({count.strip()}); elapsed {progress.get('elapsed_seconds')} s")
            lines.append('Cumulative counters: ' + json.dumps(progress['counters'], sort_keys=True))
    else:
        lines.append('Heartbeat: unavailable')
    for output in value['accepted_outputs']:
        lines.append(f"Recorded accepted output: {output['phase']} ({output['recorded_files']} files; integrity not rechecked)")
    if publication := value.get('continuation', {}).get('recorded_publication_status'):
        lines.append('Recorded publisher result: ' + publication)
    if observation := value.get('continuation', {}).get('local_phase_observation', {}).get('write_observation'):
        lines.append('Local write observation: ' + observation['source'] + ': ' + observation['path'])
        if observation.get('latest_event_state'):
            lines.append('Local write state: ' + observation['latest_event_state'])
    if reconciliation := value.get('continuation', {}).get('local_phase_observation', {}).get('last_reconciliation_observation'):
        lines.append('Last recorded reconciliation observation: ' + reconciliation['state'] + ' at ' + reconciliation.get('updated_at', 'unknown'))
        if reconciliation.get('key'):
            lines.append('Object: ' + json.dumps(reconciliation['key']) + '; bytes read: ' + str(reconciliation['bytes_read']))
        lines.append('Next read-only check: ' + reconciliation['next_check'])
    if build := value.get('continuation', {}).get('local_phase_observation', {}).get('catalog_build'):
        lines.append('Retained catalog build: ' + build['retained_build_path'])
        lines.append('Last recorded accepted phase: ' + (build['last_recorded_accepted_phase'] or 'none'))
        lines += ['Read-only check: ' + item['path'] + ': ' + item['check'] for item in build['next_read_only_checks']]
    lines.append('Current public readback: not checked')
    if verification := value.get('publication_verification'):
        lines.append('Read-only publication verification: ' + verification['status'])
        for check in verification['checks']:
            lines.append(check['check'] + ': ' + check['state'])
    lines += ['Attention: ' + issue for issue in value['issues']]
    lines.append('Next: ' + value['next_action'])
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, help='GitHub workflow run ID')
    parser.add_argument('--repo', default='civictechdc/congressional-tech')
    parser.add_argument('--progress', default=DEFAULT_PROGRESS, help='Existing heartbeat URL or saved JSON path')
    parser.add_argument('--github-json', type=Path, help='Saved GitHub REST run response for offline inspection')
    parser.add_argument('--previous-progress', type=Path, help='Earlier saved heartbeat; enables monotonicity checks')
    parser.add_argument('--continuation', type=Path, help='Existing continuation.json; attribution requires run/attempt/revision')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--verify-publication', action='store_true')
    parser.add_argument('--raw-manifest', help='Current raw selector URL or explicitly saved raw selector')
    parser.add_argument('--expected-raw-manifest-sha256', help='Exact raw selector SHA256 retained as output of this run')
    parser.add_argument('--viewer-pointer', default='https://congressional-viewer-data.mdeeb.workers.dev/manifest.json')
    parser.add_argument('--pages-url', default='https://civictechdc.github.io/congressional-tech/dashboard/')
    parser.add_argument('--review-descriptor', type=Path, default=Path(__file__).resolve().parents[2]/'apps/site/document-review-publication.json')
    parser.add_argument('--verification-receipt', type=Path)
    args = parser.parse_args(argv)
    if not args.run.isdigit():
        parser.error('--run must be a numeric GitHub run ID')
    if args.verify_publication and (not args.raw_manifest or not args.verification_receipt):
        parser.error('--verify-publication requires --raw-manifest and --verification-receipt')
    evidence, errors = {}, []
    for name, read in [('github', lambda: read_json(args.github_json) if args.github_json else github_run(args.run, args.repo)),
                       ('progress', lambda: read_json(args.progress)),
                       ('previous', lambda: read_json(args.previous_progress) if args.previous_progress else None)]:
        try:
            evidence[name] = read()
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            errors.append(f'{name} unavailable: {type(error).__name__}')
            evidence[name] = None
    try:
        result = summarize(args.run, evidence['github'], evidence['progress'], previous=evidence['previous'],
                           receipt=args.continuation, errors=errors)
    except (ValueError, KeyError, TypeError) as error:
        parser.exit(1, f'Invalid status evidence: {error}\n')
    if args.verify_publication:
        # Native readback reuses the same file/route owners as the publisher.
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/publication'))
        from viewer_publication import verify as publication_verification
        control, live_observation, verify = (
            publication_verification.control,
            publication_verification.live_observation,
            publication_verification.verify,
        )
        from publication_cli import save_report
        try:
            raw_bytes = control(args.raw_manifest)
            raw_manifest = json.loads(raw_bytes)
            observed = live_observation(args.viewer_pointer, args.pages_url, args.review_descriptor,
                                        root=Path(__file__).resolve().parents[2])
            verification = verify(raw_manifest, observed, current_raw=str(args.raw_manifest).startswith(('http://','https://')),
                raw_digest=sha256(raw_bytes).hexdigest(), expected_raw_digest=args.expected_raw_manifest_sha256)
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
            verification = {'version':1, 'status':'failed', 'read_only':True, 'checks':[
                {'check':'publication_verification', 'state':'failed', 'detail':type(error).__name__}],
                'observed_at':datetime.now(timezone.utc).isoformat()}
        verification['run'] = dict(result['github'],run_id=args.run) if result.get('github') else {'run_id':args.run, 'state':'unattributed'}
        if not result.get('github'):
            verification['checks'].append({'check':'github_run_binding','state':'pending','detail':'Requested GitHub run unavailable'})
            if verification['status']=='verified':
                verification['status']='pending'
        save_report(args.verification_receipt, verification)
        result['publication_verification'] = verification
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else format_status(result))
    return 1 if args.verify_publication and result['publication_verification']['status']=='failed' else 0


if __name__ == '__main__':
    raise SystemExit(main())
