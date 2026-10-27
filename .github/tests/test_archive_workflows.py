"""F1 workflow admission, one writer group, and a refusing model binding."""
from pathlib import Path
import json
import subprocess
import sys

import yaml

ROOT = Path(__file__).parents[2]


def workflow(name):
    return yaml.load((ROOT / '.github/workflows' / name).read_text(), Loader=yaml.BaseLoader)


def test_publish_backfill_maintenance_share_one_non_canceling_group():
    value = workflow('archive-jobs.yml')
    assert value['concurrency'] == {'group': 'archive-lake-and-publication', 'cancel-in-progress': 'false', 'queue': 'max'}
    assert set(value['jobs']) == {'publish', 'backfill', 'maintenance'}
    assert value['permissions'] == {'contents': 'read'}
    for operation, job in value['jobs'].items():
        commands = '\n'.join(step.get('run', '') for step in job['steps'])
        assert f'run-archive-job.py {operation}' in commands
        assert 'gh ' not in commands and 'git push' not in commands
        assert 'github.ref' in job['if'] or 'head_branch' in job['if']
    steps = value['jobs']['publish']['steps']
    invocation = next(step for step in steps if step.get('run', '').endswith('run-archive-job.py publish'))
    assert 'canary:' not in invocation['run'] and 'contract:' not in invocation['run'], 'Publisher owns stages once'
    assert invocation['env']['VIEWER_BENCHMARK_MODULES'] == '${{ env.PUBLICATION_BROWSER_MODULES }}'


def test_new_capture_uses_scheduler_and_separate_lock_with_explicit_switch():
    value = workflow('capture-archive.yml')
    assert value['concurrency']['group'] == 'archive-capture'
    assert value['concurrency']['cancel-in-progress'] == 'false'
    job = value['jobs']['capture']
    assert "vars.ARCHIVE_CAPTURE_ENABLED == 'true'" in job['if']
    assert value['permissions'] == {'contents': 'read'}
    command = '\n'.join(step.get('run', '') for step in job['steps'])
    assert 'congress_api.cli.capture_schedule' in command
    assert '--seed-inventory' in command
    assert all(arg in command for arg in ['--request-budget', '--byte-budget', '--spool-budget'])
    assert '--max-file-mib' not in command and '--replay' not in command and 'raw-source-sync' not in command
    publisher = workflow('archive-jobs.yml')
    assert publisher['on']['workflow_run']['workflows'] == [value['name']]


def test_obsolete_viewer_workflow_and_thirty_minute_cron_are_absent():
    assert not (ROOT / '.github/workflows/publish-filename-viewer.yml').exists()
    assert not any('11,41 * * * *' in path.read_text() for path in (ROOT / '.github/workflows').glob('*.yml'))


def test_pending_model_spec_refuses_before_importing_publisher_or_accessing_storage(tmp_path):
    result = subprocess.run([sys.executable, '-I', str(ROOT / '.github/scripts/run-archive-job.py'), 'publish'],
        cwd=tmp_path, capture_output=True, text=True, timeout=10, env={'PATH': '/usr/bin:/bin'})
    assert result.returncode != 0
    assert 'Track E' in result.stderr and 'refused' in result.stderr
    assert not list(tmp_path.iterdir())
    config = json.loads((ROOT / '.github/archive-jobs.json').read_text())
    assert config['publish']['module'] == 'viewer_publication.archive_publish'
    assert config['publish']['spec'] == 'model/jobs/publish.pending.json'


def test_every_new_r2_writer_has_an_explicit_endpoint_source():
    for name in ['archive-jobs.yml', 'capture-archive.yml']:
        for job in workflow(name)['jobs'].values():
            for step in job['steps']:
                env = step.get('env', {})
                if 'R2_ACCESS_KEY_ID' in env:
                    assert env['CLOUDFLARE_ACCOUNT_ID'] == '${{ vars.CLOUDFLARE_ACCOUNT_ID }}'


def test_deploy_and_validation_add_local_archive_contract_before_upload():
    for name, job in [('deploy-pages.yml', 'build'), ('validate-explorer.yml', 'validate')]:
        steps = workflow(name)['jobs'][job]['steps']
        contract = next(i for i, step in enumerate(steps) if 'verify-archive-contract.py' in step.get('run', ''))
        build = next(i for i, step in enumerate(steps) if step.get('name') in {'Build Astro site', 'Build the static site'})
        assert contract > build
        assert any(step.get('uses') == './.github/actions/setup-publication-browser' for step in steps[:contract])
        assert steps[contract]['env']['VIEWER_BENCHMARK_MODULES'] == '${{ env.PUBLICATION_BROWSER_MODULES }}'
        if name == 'deploy-pages.yml':
            upload = next(i for i, step in enumerate(steps) if step.get('uses') == 'actions/upload-pages-artifact@v3')
            assert contract < upload
