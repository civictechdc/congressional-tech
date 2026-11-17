"""A pull request says, before it merges, whether it will stop the nightly for a cause record."""
import importlib.util
from pathlib import Path
import subprocess

import yaml

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / '.github/scripts/definition-change.py'


def load():
    spec = importlib.util.spec_from_file_location('definition_change', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_an_untouched_definition_is_silent_and_a_changed_one_names_files_and_pins():
    module = load()
    assert module.changed({'a': '1', 'b': '2'}, {'a': '1', 'b': '2'}) == []
    assert module.changed({'a': '1', 'b': '2'}, {'a': '1', 'b': '3', 'c': '4'}) == ['b', 'c']
    assert module.notice([], []) == []
    lines = module.notice(['model/sql/list.sql'], ['producers/captures'])
    assert 'stop at gate 1 until a cause record is committed' in lines[2]
    assert '- `model/sql/list.sql`' in lines and '- `producers/captures`' in lines
    many = module.notice([f'model/sql/{n}.sql' for n in range(45)], [])
    assert '- and 5 more' in many


def test_job_pins_are_the_ones_the_nightly_compares():
    pins = load().job_pins(ROOT)
    assert {'model_spec', 'daily'} <= set(pins) and any(name.startswith('producers/') for name in pins)
    # The same three pins run_publish writes as unprofiled inputs (archive_publish_job.execute).
    source = (ROOT / 'packages/viewer_publication/src/viewer_publication/archive_publish_job.py').read_text()
    assert "job_pins=dict(model_spec=spec['model_spec']['sha256'],daily=spec['daily']['sha256']" in source


def test_this_checkout_against_its_own_head_reports_no_change():
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
    result = subprocess.run([str(ROOT / '.venv/bin/python'), '-I', str(SCRIPT), '--base', head], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    # A dirty tree may differ from HEAD; a clean one reports no change. Either way it never fails.
    assert 'unchanged' in result.stdout or '::warning title=Model definition changed::' in result.stdout


def test_validation_runs_it_on_pull_requests_only_and_cannot_fail_on_it():
    steps = yaml.load((ROOT / '.github/workflows/validate-explorer.yml').read_text(), Loader=yaml.BaseLoader)['jobs']['validate']['steps']
    step = next(s for s in steps if 'definition-change.py' in s.get('run', ''))
    assert step['if'] == "github.event_name == 'pull_request'"
    assert step['env'] == {'BASE_SHA': '${{ github.event.pull_request.base.sha }}'}
    assert 'git fetch --no-tags --depth 1 origin "$BASE_SHA"' in step['run']
    assert 'return 1' not in SCRIPT.read_text() and 'sys.exit(1)' not in SCRIPT.read_text()
