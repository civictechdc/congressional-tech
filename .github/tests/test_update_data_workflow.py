"""The collection job validates its installed packages, without unrelated research."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_validation_runs_offline_and_excludes_uninstalled_packages(tmp_path):
    workflow = yaml.load((ROOT / '.github/workflows/update-data.yml').read_text(), Loader=yaml.BaseLoader)
    steps = workflow['jobs']['meetings']['steps']
    command = next(step['run'] for step in steps if step.get('name') == 'Test source parsing and refresh decisions')
    for directory in ('tests', 'packages/committee_meeting/tests', 'packages/house-naming/tests', '.github/tests'):
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
    result = subprocess.run(['bash', '-eo', 'pipefail', '-c', command], cwd=tmp_path,
                            env={**os.environ, 'PATH': f'{Path(sys.executable).parent}:{os.defpath}',
                                 'PYTEST_ADDOPTS': ''}, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '4 passed' in result.stdout


def test_meeting_validation_installs_its_archive_and_filename_test_dependencies():
    workflow = yaml.load((ROOT / '.github/workflows/update-data.yml').read_text(), Loader=yaml.BaseLoader)
    install = next(step['run'] for step in workflow['jobs']['meetings']['steps']
                   if step.get('name') == 'Install packages')
    assert 'packages/congress_api[archive,test]' in install
    assert 'packages/house-naming[test]' in install
    assert 'PyYAML' in install


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
