"""main requires one check, the merge gate; it always runs and mirrors the other workflow runs."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('merge_gate', ROOT / '.github/scripts/merge-gate.py')
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)
OWN = 7


def run(name, status, conclusion=None, number=1):
    return dict(databaseId=number, workflowName=name, status=status, conclusion=conclusion, url=f'https://x/{number}')


GATE = run('Merge gate', 'in_progress', number=OWN)


@pytest.mark.parametrize('others,expected', [
    ([], 'pass'),
    ([run('Validate Committee Explorer', 'completed', 'success')], 'pass'),
    ([run('Validate Committee Explorer', 'completed', 'skipped')], 'pass'),
    ([run('Validate Committee Explorer', 'queued')], 'wait'),
    ([run('Validate Committee Explorer', 'completed', 'success'), run('Validate Congress MCP', 'in_progress', number=2)], 'wait'),
    ([run('Validate Committee Explorer', 'completed', 'failure')], 'fail'),
    ([run('Validate Committee Explorer', 'completed', 'cancelled')], 'fail'),
    ([run('Validate Committee Explorer', 'completed', 'timed_out')], 'fail'),
    # One failure decides at once, whatever is still running.
    ([run('Validate Committee Explorer', 'in_progress'), run('Validate Congress MCP', 'completed', 'failure', number=2)], 'fail'),
])
def test_the_gate_mirrors_the_other_runs_and_never_judges_itself(others, expected):
    state, lines = gate.verdict([GATE, *others], OWN)
    assert state == expected
    assert not any('Merge gate' in line for line in lines)


def poll(sequence, monkeypatch=None):
    """Drive main() over successive run listings with a clock that advances by each sleep."""
    listings, now, slept = iter(sequence), [0.0], []

    def sleep(seconds):
        slept.append(seconds)
        now[0] += seconds
    code = gate.main({'HEAD_SHA': 'a' * 40, 'GITHUB_RUN_ID': str(OWN)}, read=lambda sha: next(listings),
                     sleep=sleep, clock=lambda: now[0])
    return code, slept


def test_a_pull_request_that_starts_no_other_workflow_passes_only_after_the_settling_wait():
    code, slept = poll([[GATE]] * 10)
    assert code == 0 and sum(slept) >= gate.SETTLE_SECONDS
    # A run that registers late is still waited for: an early empty list is not a pass.
    late = run('Validate Committee Explorer', 'queued')
    code, slept = poll([[GATE], [GATE, late], [GATE, late], [GATE, dict(late, status='completed', conclusion='failure')]])
    assert code == 1


def test_the_gate_waits_through_a_long_validation_then_passes(capsys):
    validation = run('Validate Committee Explorer', 'in_progress')
    code, slept = poll([[GATE, validation]] * 40 + [[GATE, dict(validation, status='completed', conclusion='success')]])
    assert code == 0 and len(slept) == 40
    assert 'Waiting for 1' in capsys.readouterr().out


def test_script_runs_on_the_runner_python_without_project_packages():
    result = subprocess.run([sys.executable, '-I', '-c', f'import runpy; runpy.run_path({str(ROOT / ".github/scripts/merge-gate.py")!r})'],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_the_gate_runs_on_every_pull_request_and_is_the_check_main_requires():
    workflow = yaml.load((ROOT / '.github/workflows/merge-gate.yml').read_text(), Loader=yaml.BaseLoader)
    # A path or branch filter would leave the required check pending forever on a skipped pull request.
    assert workflow['on'] == {'pull_request': ''}
    assert workflow['permissions'] == {'actions': 'read', 'contents': 'read'}
    assert list(workflow['jobs']) == ['merge-gate'] and 'if' not in workflow['jobs']['merge-gate']
    # Outlasts the validation it waits for.
    shards = yaml.load((ROOT / '.github/workflows/validate-explorer.yml').read_text(), Loader=yaml.BaseLoader)['jobs']
    slowest = max(int(job['timeout-minutes']) for job in shards.values())
    assert int(workflow['jobs']['merge-gate']['timeout-minutes']) > 2 * slowest
    rules = json.loads((ROOT / '.github/rulesets/main.json').read_text())
    assert rules['enforcement'] == 'active' and rules['conditions']['ref_name']['include'] == ['~DEFAULT_BRANCH']
    [rule] = rules['rules']
    assert rule['type'] == 'required_status_checks'
    assert rule['parameters']['required_status_checks'] == [{'context': 'merge-gate'}]
    # Repository admins only (role 5): GitHub refuses its Actions app as a bypass actor, so the
    # data jobs mark their own commits instead (.github/scripts/commit-and-push.sh).
    assert rules['bypass_actors'] == [{'actor_id': 5, 'actor_type': 'RepositoryRole', 'bypass_mode': 'always'}]
