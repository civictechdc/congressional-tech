"""The collection job validates its installed packages, without unrelated research."""
import importlib.util
from pathlib import Path
import shutil

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_validation_runs_declared_offline_suite(tmp_path, monkeypatch, capfd):
    workflow = yaml.load((ROOT / '.github/workflows/update-data.yml').read_text(), Loader=yaml.BaseLoader)
    steps = workflow['jobs']['meetings']['steps']
    command = next(step['run'] for step in steps if step.get('name') == 'Test source parsing and refresh decisions')
    assert command == 'python scripts/dev.py test production-offline'
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
    workflow = yaml.load((ROOT / '.github/workflows/update-data.yml').read_text(), Loader=yaml.BaseLoader)
    steps = workflow['jobs']['meetings']['steps']
    assert any(step.get('uses') == './.github/actions/setup-python-project' for step in steps)
    setup = yaml.load((ROOT / '.github/actions/setup-python-project/action.yml').read_text(), Loader=yaml.BaseLoader)
    commands = '\n'.join(step.get('run', '') for step in setup['runs']['steps'])
    assert 'uv sync --locked' in commands
    python_setup = next(step for step in setup['runs']['steps'] if step.get('uses', '').startswith('actions/setup-python@'))
    assert python_setup['with']['python-version-file'] == '.python-version'
    assert 'poppler-utils' in commands
    assert 'scripts/dev.py prepare-baseline' in commands
    assert any(step.get('run') == 'python scripts/dev.py test active-experiment-regression' for step in steps)


def test_house_directory_and_site_pages_precede_xml_fallback_and_save_partial_progress():
    workflow = yaml.load((ROOT / '.github/workflows/update-data.yml').read_text(), Loader=yaml.BaseLoader)
    jobs = workflow['jobs']
    assert jobs['committees']['needs'] == 'congress'
    assert 'committees' in jobs['meetings']['needs']
    steps = jobs['meetings']['steps']
    sites = next(step for step in steps if step.get('id') == 'house_sites')
    house = next(step for step in steps if step.get('id') == 'house_records')
    assert steps.index(sites) < steps.index(house)
    assert '--committees pipeline-data/congress_committees.jsonl.gz' in sites['run']
    assert '--limit 3000' in sites['run'] and '--since' not in sites['run']
    assert "steps.house_sites.outcome == 'failure'" in house['if']
    save = next(step for step in steps if step.get('name') == 'Save pipeline data snapshot')
    assert "steps.house_records.outcome == 'failure'" in save['if']
    raw = yaml.load((ROOT / '.github/workflows/capture-raw-sources.yml').read_text(), Loader=yaml.BaseLoader)
    assert any('pipeline-data/meeting-inventory/house-sites.json.gz' in step.get('run', '')
               for step in raw['jobs']['capture']['steps'])


def test_every_snapshot_save_also_keeps_the_snapshot_in_raw():
    workflow = yaml.load((ROOT / '.github/workflows/update-data.yml').read_text(), Loader=yaml.BaseLoader)
    saves = [step for job in workflow['jobs'].values() for step in job['steps']
             if '.github/scripts/save-pipeline-data.sh' in step.get('run', '')]
    assert len(saves) == 4
    for step in saves:
        assert set(step['env']) == {'CLOUDFLARE_ACCOUNT_ID', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY'}
        assert step['env']['R2_ACCESS_KEY_ID'] == '${{ secrets.R2_ACCESS_KEY_ID }}'
    script = (ROOT / '.github/scripts/save-pipeline-data.sh').read_text().splitlines()
    push = script.index('git push -q -f origin snapshot:pipeline-data')
    tail = '\n'.join(script[push + 1:])
    assert 'prepare-raw-writer.sh' in tail
    assert '"$writer_root/.venv/bin/python" -I -m congress_api.cli.pipeline_raw --snapshot "$snapshot_root"' in tail
    assert 'git -C "$application_root" rev-parse HEAD' in '\n'.join(script)
