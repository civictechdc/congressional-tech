"""Prerequisite failures must stop before tests; inventory covers new files."""
import importlib.util
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('development_tools', ROOT / 'scripts/dev.py')
dev = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dev)


def test_runtime_and_dependency_pins_trigger_validation():
    workflow = yaml.load((ROOT / '.github/workflows/validate-explorer.yml').read_text(), Loader=yaml.BaseLoader)
    paths = set(workflow['on']['pull_request']['paths'])
    assert {'.python-version', 'pyproject.toml', 'uv.lock', 'test-suites.toml'} <= paths
    config = dev.declaration()
    for import_root in config['environment']['imports'].values():
        pkg_glob = '/'.join(Path(import_root).parts[:2]) + '/**'
        assert pkg_glob in paths, f'{pkg_glob} missing from validate-explorer.yml pull_request.paths'


def test_inventory_rejects_new_unassigned_test(monkeypatch):
    monkeypatch.setattr(dev, 'run', lambda *a, **kw: SimpleNamespace(stdout='docs/experiments/new/test_new.py\0'))
    with pytest.raises(ValueError, match='Unassigned test: docs/experiments/new/test_new.py'):
        dev.inventory(dev.declaration())


def test_all_fourteen_experiment_files_are_explicit_active_regressions():
    config = dev.declaration()
    declared = set(config['lanes']['active-experiment-regression']['roots'])
    existing = {str(path.relative_to(ROOT)) for path in (ROOT / 'docs/experiments').rglob('test_*.py')}
    assert declared == existing
    assert len(declared) == 10
    assert not config['lanes']['frozen-reproduction']['roots']


@pytest.mark.parametrize('failure', ['missing_poppler', 'missing_ps', 'wrong_checkout', 'wrong_pyarrow', 'wrong_python'])
def test_doctor_fails_before_pytest_with_actionable_reason(monkeypatch, failure):
    config = dev.declaration()
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[0].startswith('/bin/'):
            return SimpleNamespace(stdout='poppler test', stderr='')
        if 'import pyarrow' in command[2]:
            return SimpleNamespace(stdout='0.0' if failure == 'wrong_pyarrow' else '25.0.1')
        name = command[-1]
        source = '/different-checkout' if failure == 'wrong_checkout' else str(ROOT / config['environment']['imports'][name])
        return SimpleNamespace(stdout=source + '/' + name + '/__init__.py')

    monkeypatch.setattr(dev, 'run', run)
    if failure == 'wrong_python':
        monkeypatch.setattr(dev.sys, 'version_info', (3, 12, 99))
    monkeypatch.setattr(dev.shutil, 'which', lambda command: None
                        if failure == 'missing_poppler' or (failure == 'missing_ps' and command == 'ps')
                        else '/bin/' + command)
    monkeypatch.setattr(dev, 'inventory', lambda config: None)
    expected = {'missing_poppler': 'Missing pdfinfo; remedy:', 'missing_ps': 'Missing ps; remedy:',
                'wrong_checkout': 'outside this checkout', 'wrong_pyarrow': 'expected locked 25.0.1',
                'wrong_python': 'Python 3.12.13 required by .python-version'}
    with pytest.raises(ValueError, match=expected[failure]):
        dev.test(config, 'production-offline', [], [])
    assert not any('pytest' in command for command in calls)


def test_missing_baseline_never_fetches_during_test_preflight(monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(dev, 'run', run)
    with pytest.raises(ValueError, match='prepare-baseline before tests'):
        dev.baseline(dev.declaration())
    assert calls == [['git', 'cat-file', '-e', dev.declaration()['baseline']['commit'] + '^{commit}']]


def test_wrong_historical_parser_hash_fails(monkeypatch):
    monkeypatch.setattr(dev, 'run', lambda *a, **kw: SimpleNamespace(stdout=''))
    monkeypatch.setattr(dev.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout=b'wrong parser'))
    with pytest.raises(ValueError, match='Baseline parser hash differs'):
        dev.baseline(dev.declaration())


def test_frozen_reproduction_requires_separate_runtime():
    with pytest.raises(ValueError, match='separately frozen runtime'):
        dev.test(dev.declaration(), 'frozen-reproduction', [], [])


def test_setup_fetches_only_declared_commit_then_verifies_parser(monkeypatch):
    config = dev.declaration()
    commit = config['baseline']['commit']
    parser = config['baseline']['parser']
    source = subprocess.run(['git', 'show', commit + ':' + parser], cwd=ROOT,
                            check=True, capture_output=True).stdout
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[1] == 'cat-file':
            raise subprocess.CalledProcessError(1, command)
        return SimpleNamespace(stdout=commit)

    monkeypatch.setattr(dev, 'run', run)
    monkeypatch.setattr(dev.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout=source))
    assert commit in dev.baseline(config, fetch=True)
    assert ['git', 'fetch', '--no-tags', '--depth=1', 'origin', commit] in calls


def test_native_lane_requires_one_explicit_local_runtime_before_pytest(monkeypatch):
    monkeypatch.delenv('DOCSPEC_JOB_CONFIG', raising=False)
    assert dev.declaration()['lanes']['production-offline']['required_job_config_env'] == 'DOCSPEC_JOB_CONFIG'
    with pytest.raises(ValueError, match='DOCSPEC_JOB_CONFIG.*explicit.*runtime'):
        dev.job_runtime(dev.declaration(), 'production-offline')


@pytest.mark.parametrize('settings', [{}, {'version': 1, 'remote': 'not-to-be-opened'},
                                     {'version': 1, 'credentials': 'not-to-be-opened'}])
def test_native_runtime_refuses_bad_shape_and_credentials_without_loading_them(tmp_path, monkeypatch, settings):
    import json
    from docspec_client import NativeDatasets
    config = tmp_path / 'runtime.json'
    config.write_text(json.dumps(settings))
    monkeypatch.setenv('DOCSPEC_JOB_CONFIG', str(config))
    def forbidden(*args, **kwargs):
        pytest.fail('configuration must refuse before credential-aware loader')
    monkeypatch.setattr(NativeDatasets, 'from_config', forbidden)
    with pytest.raises(ValueError, match='DOCSPEC_JOB_CONFIG'):
        dev.job_runtime(dev.declaration(), 'production-offline')


def test_native_runtime_verifies_pins_without_starting_engine(tmp_path, monkeypatch):
    import json
    from hashlib import sha256
    binary = tmp_path / 'engine'
    binary.write_bytes(b'\xcf\xfa\xed\xfeauthored fixture')
    binary.chmod(0o755)
    limits = tmp_path / 'limits.json'
    limits.write_text('{}')
    config = tmp_path / 'runtime.json'
    settings = dict(version=1, binary=str(binary), workspace=str(tmp_path / 'workspace'), limits=str(limits),
                    source_revision='1' * 40, binary_sha256=sha256(binary.read_bytes()).hexdigest(),
                    platform='darwin-arm64', build_features=['remote'])
    config.write_text(json.dumps(settings))
    monkeypatch.setenv('DOCSPEC_JOB_CONFIG', str(config))
    def forbidden(*args, **kwargs):
        pytest.fail('preflight must not execute native code')
    monkeypatch.setattr(dev.subprocess, 'run', forbidden)
    dev.job_runtime(dev.declaration(), 'production-offline')
    assert not (tmp_path / 'workspace').exists()
    binary.write_bytes(b'changed')
    with pytest.raises(ValueError, match='DOCSPEC_JOB_CONFIG.*approved SHA-256'):
        dev.job_runtime(dev.declaration(), 'production-offline')
