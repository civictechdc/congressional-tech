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


def build_evidence(remaining=None):
    baseline = json.loads(BASELINE.read_text())
    assert len(baseline) == len(set(baseline)) == 36
    keep = set(baseline) if remaining is None else set(remaining)
    jobs = []
    lines = []
    for index in range(6):
        name = f'Offline regressions ({index + 1}/6)'
        cases = [case for case in baseline[index::6] if case in keep]
        conclusion = 'failure' if cases else 'success'
        jobs.append(dict(name=name, databaseId=index + 1, status='completed', conclusion=conclusion,
                         startedAt='2026-10-28T10:00:00Z', completedAt='2026-10-28T10:05:00Z',
                         steps=[dict(name=name, status='completed', conclusion=conclusion) for name,conclusion in
                                [('Set up job','success'), ('Test the complete offline partition',conclusion),
                                 ('Run actions/upload-artifact@v4','success'), ('Post actions/checkout@v5','success')]]))
        prefix = name + '\tUNKNOWN STEP\t2026-10-28T10:04:59.1234567Z '
        lines.extend(prefix + case + ' - fixture failure' for case in cases)
        failed = sum(case.startswith(('FAILED ', 'SUBFAILED(')) for case in cases)
        errors = sum(case.startswith('ERROR ') for case in cases)
        lines.append(prefix + f'{failed} failed, 100 passed, {errors} errors, 5 skipped in 299.00s')
        selected = 105 + failed + errors - sum(case.startswith('SUBFAILED(') for case in cases)
        lines.append(prefix + f'collected {selected} items')
        lines.append(prefix + ('CT_OFFLINE_EXIT_STATUS=1' if cases else 'CT_OFFLINE_EXIT_STATUS=0'))
    run = dict(headSha=HEAD, event='workflow_dispatch', status='completed', conclusion='failure' if keep else 'success', jobs=jobs)
    return run, lines, baseline


@pytest.fixture
def evidence():
    return build_evidence()


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
        elif line.startswith('Offline regressions (1/6)') and 'collected ' in line:
            before, tail = line.rsplit('collected ', 1)
            number, rest = tail.split(' ', 1)
            lines[index] = before + 'collected ' + str(int(number) + 1) + ' ' + rest
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
    selected = 100 + failed + errors - sum(case.startswith('SUBFAILED(') for case in cases)
    lines = [line for line in lines if not (line.startswith(first) and 'collected ' in line)]
    lines.append(prefix + f'collected {selected} items')
    lines.append(last + '\tUNKNOWN STEP\t2026-10-28T10:04:59Z collected 100 items')
    lines.append(last + '\tUNKNOWN STEP\t2026-10-28T10:04:59Z CT_OFFLINE_EXIT_STATUS=0')
    run['jobs'][5]['steps'][1]['conclusion'] = 'success'
    run['jobs'][5]['conclusion'] = 'success'
    assert verifier.verify(run, lines, baseline, HEAD)['accepted'] is True
    run['jobs'][5]['conclusion'] = 'failure'
    assert verifier.verify(run, lines, baseline, HEAD)['accepted'] is False


@pytest.mark.parametrize('change', ['interrupted', 'partial_exit_one', 'missing_exit', 'duplicate_exit',
    'missing_collection', 'artifact_failure', 'post_failure', 'missing_test_step', 'wrong_test_step_result'])
def test_matching_baseline_cannot_hide_incomplete_or_broken_steps(verifier, evidence, change):
    run, lines, baseline = evidence
    first = 'Offline regressions (1/6)'
    if change == 'interrupted':
        lines = [line.replace('CT_OFFLINE_EXIT_STATUS=1', 'CT_OFFLINE_EXIT_STATUS=2') if line.startswith(first) else line for line in lines]
        lines.append(first + '\tUNKNOWN STEP\t2026-10-28T10:04:59Z ! KeyboardInterrupt !')
    elif change == 'partial_exit_one':
        for index,line in enumerate(lines):
            if line.startswith(first) and 'collected ' in line:
                before, tail = line.rsplit('collected ', 1)
                number, rest = tail.split(' ', 1)
                lines[index] = before + 'collected ' + str(int(number) + 1) + ' ' + rest
    elif change == 'missing_exit':
        lines = [line for line in lines if not (line.startswith(first) and 'CT_OFFLINE_EXIT_STATUS=' in line)]
    elif change == 'duplicate_exit':
        lines.append(next(line for line in lines if line.startswith(first) and 'CT_OFFLINE_EXIT_STATUS=' in line))
    elif change == 'missing_collection':
        lines = [line for line in lines if not (line.startswith(first) and 'collected ' in line)]
    elif change == 'artifact_failure': run['jobs'][0]['steps'][2]['conclusion'] = 'failure'
    elif change == 'post_failure': run['jobs'][0]['steps'][3]['conclusion'] = 'failure'
    elif change == 'missing_test_step': run['jobs'][0]['steps'].pop(1)
    elif change == 'wrong_test_step_result': run['jobs'][0]['steps'][1]['conclusion'] = 'success'
    result = verifier.verify(run, lines, baseline, HEAD)
    assert result['baseline'] == result['observed'] == sorted(baseline)
    assert result['accepted'] is False


def test_standard_pytest_banners_and_selected_collection_are_accepted(verifier, evidence):
    run, lines, baseline = evidence
    decorated = []
    for line in lines:
        before, payload = line.split('Z ', 1)
        if '100 passed' in payload:
            payload = '\x1b[31m================ ' + payload + ' ================\x1b[0m'
        elif payload.startswith('collected '):
            selected = int(payload.split()[1])
            payload = f'collected {selected + 2} items / 2 deselected / {selected} selected'
        decorated.append(before + 'Z ' + payload)
    assert verifier.verify(run, decorated, baseline, HEAD)['accepted'] is True


def test_resolved_baseline_identities_are_retained_and_allowed(verifier):
    baseline = json.loads(BASELINE.read_text())
    resolved = {case for case in baseline if case.startswith('SUBFAILED(')}
    assert len(resolved) == 5
    run, lines, _ = build_evidence(set(baseline) - resolved)
    result = verifier.verify(run, lines, baseline, HEAD)
    assert result['accepted'] is True
    assert result['new'] == []
    assert result['missing'] == result['resolved'] == sorted(resolved)
    assert result['hosted_status'] == 'red on 31 pre-existing baseline failures, no new failures; 5 resolved'


def test_all_resolved_requires_actual_workflow_success(verifier):
    run, lines, baseline = build_evidence(set())
    result = verifier.verify(run, lines, baseline, HEAD)
    assert result['accepted'] is True
    assert result['observed'] == result['new'] == []
    assert result['resolved'] == sorted(baseline)
    assert result['hosted_status'] == 'green: no failures; 36 baseline identities resolved'
    run['conclusion'] = 'failure'
    assert verifier.verify(run, lines, baseline, HEAD)['accepted'] is False
