"""CI partitions the complete lane; every shard keeps its original checks."""
import importlib.util
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('sharded_development_tools', ROOT / 'scripts/dev.py')
dev = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dev)


def test_shards_cover_every_enrolled_file_once_in_stable_order():
    files = {f'tests/test_case_{i:03}.py' for i in range(47)} | {
        'packages/example/tests/test_nested.py', 'elsewhere/test_not_in_lane.py'}
    roots = ['tests', 'packages/example/tests']
    parts = [dev.shard_files(files, roots, (i, 6)) for i in range(1, 7)]
    expected = files - {'elsewhere/test_not_in_lane.py'}
    assert set().union(*map(set, parts)) == expected
    assert sum(map(len, parts)) == len(expected)
    assert max(map(len, parts)) - min(map(len, parts)) <= 1
    assert parts == [dev.shard_files(reversed(sorted(files)), roots, (i, 6)) for i in range(1, 7)]


def test_cli_passes_valid_shard_and_pytest_arguments_to_the_same_runner(monkeypatch):
    calls = []
    def execute(config, name, paths, extra, **options):
        calls.append((name, paths, extra, options))
        return 17
    monkeypatch.setattr(dev, 'test', execute)
    assert dev.main(['test', 'production-offline', '--shard', '2/6', '--', '--collect-only']) == 17
    assert calls == [('production-offline', [], ['--collect-only'], {'shard': (2, 6)})]


@pytest.mark.parametrize('value', ['0/6', '7/6', '1/0', 'one/6', '1', '1/2/3', '-1/6'])
def test_invalid_shard_refuses_before_inventory_or_runtime(monkeypatch, value):
    monkeypatch.setattr(dev, 'inventory', lambda *_: pytest.fail('inventory started'))
    monkeypatch.setattr(dev, 'doctor', lambda *_: pytest.fail('runtime started'))
    with pytest.raises(SystemExit) as error:
        dev.main(['test', 'production-offline', '--shard', value])
    assert error.value.code == 2


def test_empty_shard_refuses_instead_of_collecting_the_default_suite():
    with pytest.raises(ValueError, match='empty'):
        dev.shard_files({'tests/test_one.py'}, ['tests'], (2, 2))


def test_explicit_path_and_shard_cannot_silently_change_the_partition(monkeypatch):
    monkeypatch.setattr(dev, 'inventory', lambda *_: pytest.fail('inventory started'))
    monkeypatch.setattr(dev, 'doctor', lambda *_: pytest.fail('runtime started'))
    with pytest.raises(ValueError, match='--path.*--shard|--shard.*--path'):
        dev.test(dev.declaration(), 'production-offline', ['tests/test_one.py'], [], shard=(1, 6))


def test_sharded_runner_keeps_offline_wrapper_marker_and_exit_code(monkeypatch):
    files = {f'tests/test_case_{i}.py' for i in range(12)}
    monkeypatch.setattr(dev, 'inventory', lambda *_: files)
    calls = []
    monkeypatch.setattr(dev, 'doctor', lambda *_: calls.append('doctor'))
    def execute(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=17)
    monkeypatch.setattr(dev.subprocess, 'run', execute)
    assert dev.test(dev.declaration(), 'production-offline', [], ['--collect-only'], shard=(2, 6)) == 17
    assert calls[0] == 'doctor'
    command = calls[1]
    assert command[1] == str(ROOT / '.github/scripts/offline-python.py')
    assert command[command.index('-m') + 1] == 'pytest'
    marker = command.index('not loopback')
    assert command[marker - 1] == '-m'
    assert command[marker + 1:-1] == dev.shard_files(files, ['tests'], (2, 6))
    assert command[-1] == '--collect-only'


def test_inventory_enrolls_both_pytest_filename_forms(monkeypatch):
    monkeypatch.setattr(dev, 'run', lambda *_a, **_k: SimpleNamespace(
        stdout='tests/test_first.py\0tests/second_test.py\0tests/conftest.py\0'))
    assert dev.inventory(dev.declaration()) == {'tests/test_first.py', 'tests/second_test.py'}


def workflow(name):
    return yaml.load((ROOT / '.github/workflows' / name).read_text(), Loader=yaml.BaseLoader)


def test_six_offline_jobs_keep_runtime_and_node_before_full_partition():
    value = workflow('validate-explorer.yml')
    offline = value['jobs']['offline']
    assert offline['strategy']['fail-fast'] == 'false'
    assert offline['strategy']['matrix']['shard'] == ['1', '2', '3', '4', '5', '6']
    assert offline['timeout-minutes'] == '30'
    steps = offline['steps']
    runtime = next(i for i, s in enumerate(steps) if s.get('uses') == './.github/actions/setup-local-job-runtime')
    node = next(i for i, s in enumerate(steps) if s.get('uses') == './.github/actions/setup-node-project')
    consumer = next(i for i, s in enumerate(steps) if 'production-offline' in s.get('run', ''))
    assert runtime < consumer and node < consumer
    assert '--shard ${{ matrix.shard }}/6' in steps[consumer]['run']
    assert '--path' not in steps[consumer]['run'] and 'continue-on-error' not in offline
    assert 'continue-on-error' not in steps[consumer]
    setup = steps[runtime]
    assert setup['if'] == "github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository"
    assert setup['with']['artifact'] == '${{ vars.DOCSPEC_RUNTIME_ARTIFACT }}'


def test_required_validate_fails_if_any_offline_job_failed_or_was_cancelled():
    validate = workflow('validate-explorer.yml')['jobs']['validate']
    assert validate['needs'] == 'offline'
    assert validate['if'] == 'always()'
    first = validate['steps'][0]
    assert first['env']['OFFLINE_RESULT'] == '${{ needs.offline.result }}'
    assert first['run'] == 'test "$OFFLINE_RESULT" = success'
    assert not any('production-offline' in step.get('run', '') for step in validate['steps'])
    # Other lanes still receive the same native runtime; their skips cannot grow.
    assert any(s.get('uses') == './.github/actions/setup-local-job-runtime' for s in validate['steps'])
    assert any('native-loopback' in s.get('run', '') for s in validate['steps'])


@pytest.mark.parametrize('status,expected', [('success', 0), ('failure', 1), ('cancelled', 1), ('skipped', 1)])
def test_actual_required_gate_propagates_every_matrix_result(status, expected):
    first = workflow('validate-explorer.yml')['jobs']['validate']['steps'][0]
    assert 'OFFLINE_RESULT' in first['env']
    result = subprocess.run(['/bin/bash', '-c', first['run']],
                            env={**os.environ, 'OFFLINE_RESULT': status})
    assert result.returncode == expected


def test_update_data_installs_node_before_python_reader_regressions():
    assert 'meetings' not in workflow('update-data.yml')['jobs']
    steps = workflow('validate-explorer.yml')['jobs']['offline']['steps']
    node = next(i for i, s in enumerate(steps) if s.get('uses') == './.github/actions/setup-node-project')
    consumer = next(i for i, s in enumerate(steps) if 'production-offline' in s.get('run', ''))
    assert node < consumer


@pytest.mark.parametrize('status', range(6))
def test_actual_shard_shell_records_and_preserves_the_runner_exit(tmp_path, status):
    steps = workflow('validate-explorer.yml')['jobs']['offline']['steps']
    shell = next(step['run'] for step in steps if step.get('name') == 'Test the complete offline partition')
    shell = shell.replace('${{ matrix.shard }}', '1').replace('${{ runner.temp }}', str(tmp_path))
    binary = tmp_path / '.venv/bin/python'; binary.parent.mkdir(parents=True)
    binary.write_text('#!/bin/bash\nprintf "%s\\n" "$@" > "$CALLS"\nexit "$RUNNER_EXIT"\n')
    binary.chmod(0o755)
    calls = tmp_path / 'calls.txt'
    result = subprocess.run(['/bin/bash', '-e', '-o', 'pipefail', '-c', shell], cwd=tmp_path,
        env={**os.environ, 'RUNNER_EXIT': str(status), 'CALLS': str(calls)}, capture_output=True, text=True)
    assert result.returncode == status
    assert result.stdout.splitlines() == [f'CT_OFFLINE_EXIT_STATUS={status}']
    assert calls.read_text().splitlines()[:6] == ['scripts/dev.py', 'test', 'production-offline', '--shard', '1/6', '--']
    assert '-v' in calls.read_text().splitlines()
