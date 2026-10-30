"""The collection job validates its installed packages, without unrelated research."""
import importlib.util
from pathlib import Path
import shutil

import yaml
import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_validation_runs_declared_offline_suite(tmp_path, monkeypatch, capfd):
    workflow = yaml.load((ROOT / '.github/workflows/update-data.yml').read_text(), Loader=yaml.BaseLoader)
    assert 'meetings' not in workflow['jobs']
    spec = importlib.util.spec_from_file_location('dev_workflow_test', ROOT / 'scripts/dev.py')
    dev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dev)
    config = dev.declaration()
    for directory in config['lanes']['production-offline']['roots']:
        path = tmp_path / directory
        path.mkdir(parents=True)
        (path / ('test_' + directory.replace('/', '_').replace('-', '_').replace('.', '') + '.py')).write_text(
            'import socket\n'
            'import pytest\n'
            'def test_offline():\n'
            '    with pytest.raises(RuntimeError, match="Network access is disabled"):\n'
            '        socket.getaddrinfo("example.invalid", 443)\n')
    unrelated = tmp_path / 'packages/document-catalog/tests'
    unrelated.mkdir(parents=True)
    (unrelated / 'test_uninstalled.py').write_text('import dependency_only_in_unrelated_package\n')
    scripts = tmp_path / '.github/scripts'
    scripts.mkdir()
    shutil.copyfile(ROOT / '.github/scripts/offline-python.py', scripts / 'offline-python.py')
    shutil.copyfile(ROOT / 'pytest.ini', tmp_path / 'pytest.ini')
    monkeypatch.setattr(dev, 'ROOT', tmp_path)
    # Preflight failure cases are checked independently in test_dev_environment.py.
    monkeypatch.setattr(dev, 'inventory', lambda config: None)
    monkeypatch.setattr(dev, 'doctor', lambda *args: None)
    monkeypatch.setenv('PYTEST_ADDOPTS', '')
    assert dev.test(config, 'production-offline', [], []) == 0
    expected = len(config['lanes']['production-offline']['roots'])
    assert f'{expected} passed' in capfd.readouterr().out


def test_meeting_validation_uses_shared_locked_setup():
    setup = yaml.load((ROOT / '.github/actions/setup-python-project/action.yml').read_text(), Loader=yaml.BaseLoader)
    commands = '\n'.join(step.get('run', '') for step in setup['runs']['steps'])
    assert 'uv sync --locked' in commands
    python_setup = next(step for step in setup['runs']['steps'] if step.get('uses', '').startswith('actions/setup-python@'))
    assert python_setup['with']['python-version-file'] == '.python-version'
    assert 'poppler-utils' in commands
    assert 'scripts/dev.py prepare-baseline' in commands


def test_b14_cutover_removes_legacy_weekly_meeting_inventory_job():
    workflow = yaml.load((ROOT / '.github/workflows/update-data.yml').read_text(), Loader=yaml.BaseLoader)
    jobs = workflow['jobs']
    assert set(jobs) == {'youtube', 'congress', 'committees'}
    assert jobs['committees']['needs'] == 'congress'
    capture = yaml.load((ROOT / '.github/workflows/capture-archive.yml').read_text(), Loader=yaml.BaseLoader)
    assert not any('--seed-inventory' in step.get('run', '') for step in capture['jobs']['capture']['steps'])


@pytest.mark.parametrize('filename,count', [('update-data.yml', 3), ('publish-explorer.yml', 1)])
def test_every_snapshot_save_also_keeps_the_snapshot_in_raw(filename, count):
    workflow = yaml.load((ROOT / '.github/workflows' / filename).read_text(), Loader=yaml.BaseLoader)
    saves = [step for job in workflow['jobs'].values() for step in job['steps']
             if '.github/scripts/save-pipeline-data.sh' in step.get('run', '')]
    assert len(saves) == count
    for step in saves:
        assert set(step['env']) == {'CLOUDFLARE_ACCOUNT_ID', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY'}
        assert step['env']['R2_ACCESS_KEY_ID'] == '${{ secrets.R2_ACCESS_KEY_ID }}'
        assert step['env']['R2_SECRET_ACCESS_KEY'] == '${{ secrets.R2_SECRET_ACCESS_KEY }}'
        assert step.get('continue-on-error', 'false') == 'false'
    for job in workflow['jobs'].values():
        for index, step in enumerate(job['steps']):
            if '.github/scripts/save-pipeline-data.sh' in step.get('run', ''):
                assert any(prior.get('uses') in {'astral-sh/setup-uv@v6',
                    './.github/actions/setup-python-project'} for prior in job['steps'][:index])
    script = (ROOT / '.github/scripts/save-pipeline-data.sh').read_text().splitlines()
    setup = next(i for i,line in enumerate(script) if 'prepare-raw-writer.sh' in line)
    preserve = next(i for i,line in enumerate(script) if 'congress_api.cli.pipeline_raw' in line)
    push = next(i for i,line in enumerate(script) if 'push -q -f origin snapshot:pipeline-data' in line)
    assert setup < preserve < push
    assert 'git -C "$application_root" rev-parse HEAD' in '\n'.join(script)
