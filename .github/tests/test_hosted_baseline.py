"""The lead records red CI honestly and admits only complete, unchanged failures."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / '.github/ci-baseline-failures-20261027.json'
HEAD = 'a' * 40


@pytest.fixture
def verifier():
    spec = importlib.util.spec_from_file_location('hosted_baseline', ROOT / '.github/scripts/verify-hosted-baseline.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def evidence():
    baseline = json.loads(BASELINE.read_text())
    assert len(baseline) == len(set(baseline)) == 36
    jobs = []
    lines = []
    for index in range(6):
        name = f'Offline regressions ({index + 1}/6)'
        cases = baseline[index::6]
        jobs.append(dict(name=name, databaseId=index + 1, status='completed', conclusion='failure',
                         startedAt='2026-10-28T10:00:00Z', completedAt='2026-10-28T10:05:00Z'))
        prefix = name + '\tUNKNOWN STEP\t2026-10-28T10:04:59.1234567Z '
        lines.extend(prefix + case + ' - fixture failure' for case in cases)
        failed = sum(case.startswith(('FAILED ', 'SUBFAILED(')) for case in cases)
        errors = sum(case.startswith('ERROR ') for case in cases)
        lines.append(prefix + f'{failed} failed, 100 passed, {errors} errors, 5 skipped in 299.00s')
    run = dict(headSha=HEAD, event='workflow_dispatch', status='completed', conclusion='failure', jobs=jobs)
    return run, lines, baseline


def test_exact_six_shards_remain_red_and_retain_both_sets(verifier, evidence):
    run, lines, baseline = evidence
    result = verifier.verify(run, lines, baseline, HEAD)
    assert result['accepted'] is True
    assert result['new'] == result['missing'] == []
    assert result['baseline'] == result['observed'] == sorted(baseline)
    assert len(result['shards']) == 6
    assert result['hosted_status'] == 'red on the 36 pre-existing baseline failures, no new failures'


@pytest.mark.parametrize('change', ['head', 'event', 'run_cancelled', 'missing_shard', 'duplicate_shard',
    'timed_out', 'over_budget', 'not_finished', 'bad_clock', 'missing_summary', 'extra_failure',
    'missing_failure', 'wrong_counts', 'infrastructure_failure', 'duplicate_summary', 'empty_baseline'])
def test_partial_stale_changed_or_infrastructure_failures_never_pass(verifier, evidence, change):
    run, lines, baseline = copy.deepcopy(evidence)
    if change == 'head': run['headSha'] = 'b' * 40
    elif change == 'event': run['event'] = 'pull_request'
    elif change == 'run_cancelled': run['conclusion'] = 'cancelled'
    elif change == 'missing_shard': run['jobs'].pop()
    elif change == 'duplicate_shard': run['jobs'].append(copy.deepcopy(run['jobs'][0]))
    elif change == 'timed_out': run['jobs'][0]['conclusion'] = 'timed_out'
    elif change == 'over_budget': run['jobs'][0]['completedAt'] = '2026-10-28T10:30:01Z'
    elif change == 'not_finished': run['jobs'][0]['status'] = 'in_progress'
    elif change == 'bad_clock': run['jobs'][0]['completedAt'] = '2026-10-28T09:59:00Z'
    elif change == 'missing_summary': lines = [line for line in lines if not (line.startswith('Offline regressions (1/6)') and '100 passed' in line)]
    elif change == 'extra_failure':
        lines.insert(0, lines[0].split('Z ', 1)[0] + 'Z FAILED packages/new.py::test_new - new')
    elif change == 'missing_failure': lines.pop(0)
    elif change == 'wrong_counts': lines = [line.replace('100 passed', '100 passed, 1 failed') for line in lines]
    elif change == 'infrastructure_failure':
        run['jobs'][0]['conclusion'] = 'success'
    elif change == 'duplicate_summary': lines.append(lines[6])
    elif change == 'empty_baseline': baseline = []
    assert verifier.verify(run, lines, baseline, HEAD)['accepted'] is False


def test_cli_retains_comparison_and_returns_failure_for_changed_failures(tmp_path, verifier, evidence):
    run, lines, baseline = evidence
    lines.pop(0)
    metadata = tmp_path / 'run.json'; metadata.write_text(json.dumps(run))
    log = tmp_path / 'run.log'; log.write_text('\n'.join(lines))
    output = tmp_path / 'comparison.json'
    result = subprocess.run([sys.executable, '-I', str(ROOT / '.github/scripts/verify-hosted-baseline.py'),
        '--run', str(metadata), '--log', str(log), '--baseline', str(BASELINE),
        '--expected-head', HEAD, '--output', str(output)], capture_output=True, text=True)
    assert result.returncode == 1
    recorded = json.loads(output.read_text())
    assert recorded['accepted'] is False
    assert recorded['missing'] == [baseline[0]]
    assert len(recorded['baseline_sha256']) == 64


def test_added_failure_is_retained_even_with_matching_summary_counts(verifier, evidence):
    run, lines, baseline = evidence
    prefix = lines[0].split('Z ', 1)[0] + 'Z '
    lines.insert(0, prefix + 'FAILED packages/new.py::test_new - new')
    for index, line in enumerate(lines):
        if line.startswith('Offline regressions (1/6)') and '100 passed' in line:
            before, tail = line.rsplit('Z ', 1)
            number, rest = tail.split(' ', 1)
            lines[index] = before + 'Z ' + str(int(number) + 1) + ' ' + rest
    result = verifier.verify(run, lines, baseline, HEAD)
    assert result['accepted'] is False
    assert result['new'] == ['FAILED packages/new.py::test_new']
    assert result['missing'] == []


def test_successful_shard_cannot_hide_an_infrastructure_failure(verifier, evidence):
    run, lines, baseline = evidence
    last = 'Offline regressions (6/6)'
    lines = [line for line in lines if not line.startswith(last)]
    first = 'Offline regressions (1/6)'
    prefix = first + '\tUNKNOWN STEP\t2026-10-28T10:04:59Z '
    lines.extend(prefix + case + ' - fixture failure' for case in baseline[5::6])
    lines = [line for line in lines if not (line.startswith(first) and '100 passed' in line)]
    cases = baseline[::6] + baseline[5::6]
    failed = sum(case.startswith(('FAILED ', 'SUBFAILED(')) for case in cases)
    errors = sum(case.startswith('ERROR ') for case in cases)
    lines.append(prefix + f'{failed} failed, 100 passed, {errors} errors in 299.00s')
    lines.append(last + '\tUNKNOWN STEP\t2026-10-28T10:04:59Z 100 passed in 299.00s')
    run['jobs'][5]['conclusion'] = 'success'
    assert verifier.verify(run, lines, baseline, HEAD)['accepted'] is True
    run['jobs'][5]['conclusion'] = 'failure'
    assert verifier.verify(run, lines, baseline, HEAD)['accepted'] is False
