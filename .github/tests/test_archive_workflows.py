"""F1 workflow admission, one writer group, and a refusing model binding."""
from pathlib import Path
import json
import os
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).parents[2]


def workflow(name):
    return yaml.load((ROOT / '.github/workflows' / name).read_text(), Loader=yaml.BaseLoader)


def publisher_index(steps):
    """The one hosted publisher step; it resumes a kept candidate when it is this run's (ct-31qi)."""
    return next(i for i, step in enumerate(steps) if step.get('run', '').endswith('run-archive-job.py publish --keep-candidate'))


def assert_site_browser_pin(steps, consumer):
    """ct-3vub: Chromium follows the site lock's playwright; nothing overrides it."""
    uses = [step.get('uses') for step in steps[:consumer]]
    browser = uses.index('./.github/actions/setup-publication-browser')
    assert './.github/actions/setup-node-project' in uses[:browser]
    assert all('VIEWER_BENCHMARK_MODULES' not in step.get('env', {}) for step in steps)


def test_publish_backfill_maintenance_share_one_non_canceling_group():
    value = workflow('archive-jobs.yml')
    for name in ['archive-jobs.yml','update-data.yml']:
        assert workflow(name)['concurrency'] == {'group': 'raw-source-mirror', 'cancel-in-progress': 'false', 'queue': 'max'}
    assert set(value['jobs']) == {'publish', 'backfill', 'maintenance'}
    assert value['permissions'] == {'contents': 'read', 'actions': 'read'}  # actions: the validated-commit lookup
    for operation, job in value['jobs'].items():
        commands = '\n'.join(step.get('run', '') for step in job['steps'])
        assert f'run-archive-job.py {operation}' in commands
        assert 'gh ' not in commands and 'git push' not in commands
        assert 'github.ref' in job['if'] or 'head_branch' in job['if']
    steps = value['jobs']['publish']['steps']
    invocation = steps[publisher_index(steps)]
    assert 'canary:' not in invocation['run'] and 'contract:' not in invocation['run'], 'Publisher owns stages once'
    assert_site_browser_pin(steps, steps.index(invocation))


def test_new_capture_uses_scheduler_and_common_lock_with_explicit_switch():
    value = workflow('capture-archive.yml')
    assert value['concurrency'] == {'group': 'raw-source-mirror', 'cancel-in-progress': 'false', 'queue': 'max'}
    job = value['jobs']['capture']
    assert "vars.ARCHIVE_CAPTURE_ENABLED == 'true'" in job['if']
    assert value['permissions'] == {'contents': 'read', 'actions': 'read'}  # actions: the validated-commit lookup
    command = '\n'.join(step.get('run', '') for step in job['steps'])
    assert 'congress_api.cli.capture_schedule' in command
    assert '--seed-inventory' not in command
    assert all(arg in command for arg in ['--request-budget', '--byte-budget', '--spool-budget'])
    assert '--max-file-mib' not in command and '--replay' not in command and 'raw-source-sync' not in command
    preflight = next(i for i, step in enumerate(job['steps']) if step.get('uses') == './.github/actions/setup-local-job-runtime')
    effect = next(i for i, step in enumerate(job['steps']) if 'capture_schedule' in step.get('run', ''))
    assert preflight < effect and 'env' not in job['steps'][preflight]
    assert 'doctor' in (ROOT / '.github/scripts/setup-local-job-runtime.py').read_text()
    assert job['steps'][effect]['env']['DATA_GOV_API_KEY'] == '${{ secrets.DATA_GOV_API_KEY }}'
    publisher = workflow('archive-jobs.yml')
    assert publisher['on']['workflow_run'] == {
        'workflows': ['Capture archive sources'],
        'types': ['completed'],
        'branches': ['main'],
    }
    publish_if = publisher['jobs']['publish']['if']
    assert "github.ref == 'refs/heads/main'" in publish_if
    assert "github.event.workflow_run.head_branch == 'main'" in publish_if
    assert "github.event.workflow_run.conclusion != 'cancelled'" in publish_if
    assert "github.event.workflow_run.conclusion != 'skipped'" in publish_if
    assert "vars.ARCHIVE_NIGHTLY_DISABLED != 'true'" in publish_if


def test_obsolete_viewer_workflow_and_thirty_minute_cron_are_absent():
    assert not (ROOT / '.github/workflows/publish-filename-viewer.yml').exists()
    assert not any('11,41 * * * *' in path.read_text() for path in (ROOT / '.github/workflows').glob('*.yml'))


def test_pending_model_spec_refuses_before_importing_publisher_or_accessing_storage(tmp_path):
    root = tmp_path / 'pending-repo'
    scripts = root / '.github/scripts'
    scripts.mkdir(parents=True)
    runner = scripts / 'run-archive-job.py'
    runner.write_bytes((ROOT / '.github/scripts/run-archive-job.py').read_bytes())
    jobs = root / 'model/jobs'
    jobs.mkdir(parents=True)
    (jobs / 'publish.pending.json').write_text(json.dumps({
        'status': 'blocked',
        'reason': 'Track E model job and engine publisher spec are not bound; publication refused before storage access.',
    }))
    (root / '.github/archive-jobs.json').write_text(json.dumps({
        'publish': {'module': 'viewer_publication.archive_publish_job', 'spec': 'model/jobs/publish.pending.json'},
    }))
    work = tmp_path / 'work'
    work.mkdir()
    result = subprocess.run([sys.executable, '-I', str(runner), 'publish'],
        cwd=work, capture_output=True, text=True, timeout=10, env={'PATH': '/usr/bin:/bin'})
    assert result.returncode != 0
    assert 'Track E' in result.stderr and 'refused' in result.stderr
    assert not list(work.iterdir())
    config = json.loads((ROOT / '.github/archive-jobs.json').read_text())
    measured = {name: config[name].pop('rss_gb', None) for name in config}
    assert config['publish'] == {
        'module': 'viewer_publication.archive_publish_job',
        'spec': 'model/jobs/publish.json',
        'argv': ['--execute'],
    }
    assert config['backfill'] == {
        'module': 'viewer_publication.archive_backfill_job',
        'spec': 'model/jobs/backfill.json',
        'argv': ['--execute'],
    }
    assert config['maintenance'] == {
        'module': 'viewer_publication.archive_maintenance',
        'spec': 'model/jobs/maintenance.json',
        'argv': ['--execute'],
    }
    for name in ('publish', 'backfill', 'maintenance'):
        assert (ROOT / config[name]['spec']).is_file()
        assert not (ROOT / f'model/jobs/{name}.pending.json').exists()
        check = subprocess.run([sys.executable, '-I', str(ROOT / '.github/scripts/run-archive-job.py'), name, '--check-binding'],
            cwd=tmp_path, capture_output=True, text=True, timeout=15)
        if measured[name] is None:  # Set from a measured peak; until then the job refuses.
            assert check.returncode == 2 and 'no measured rss_gb' in check.stderr
        else:
            assert check.returncode == 0, check.stderr


def test_every_new_r2_writer_has_an_explicit_endpoint_source():
    for name in ['archive-jobs.yml', 'capture-archive.yml']:
        for job in workflow(name)['jobs'].values():
            for step in job['steps']:
                env = step.get('env', {})
                if 'R2_ACCESS_KEY_ID' in env:
                    assert env['CLOUDFLARE_ACCOUNT_ID'] == '${{ vars.CLOUDFLARE_ACCOUNT_ID }}'


def test_capture_shell_passes_budgets_and_only_existing_weekly_seeds(tmp_path):
    tools = tmp_path / '.venv/bin'
    tools.mkdir(parents=True)
    interpreter = tools / 'python'
    interpreter.write_text(f'#!{sys.executable}\nimport json, pathlib, sys\npathlib.Path("invocation.json").write_text(json.dumps(sys.argv[1:]))\n')
    interpreter.chmod(0o755)
    inventory = tmp_path / 'pipeline-data/meeting-inventory/house.json.gz'
    inventory.parent.mkdir(parents=True)
    inventory.write_bytes(b'fixture')
    step = next(step for step in workflow('capture-archive.yml')['jobs']['capture']['steps']
                if 'capture_schedule' in step.get('run', ''))
    env = dict(PATH=os.defpath, RUNNER_TEMP=str(tmp_path), ARCHIVE_POINTER='https://public.test/manifest.json',
               REQUEST_BUDGET='19', BYTE_BUDGET='2048', SPOOL_BUDGET='1024', REVIEWED_CUTOFF_URLS='')
    result = subprocess.run(['bash', '-eo', 'pipefail', '-c', step['run']], cwd=tmp_path,
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads((tmp_path / 'invocation.json').read_text()) == [
        '-I', '-m', 'congress_api.cli.capture_schedule', '--pointer', env['ARCHIVE_POINTER'],
        '--request-budget', '19', '--byte-budget', '2048', '--spool-budget', '1024',
        '--work', str(tmp_path / 'archive-capture'), '--apply']
    (tmp_path / 'invocation.json').unlink()
    env['REQUEST_BUDGET'] = '0'
    result = subprocess.run(['bash', '-eo', 'pipefail', '-c', step['run']], cwd=tmp_path,
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert not (tmp_path / 'invocation.json').exists()


def test_capture_relists_recent_meetings_before_the_budgeted_capture(tmp_path):
    """ct-q4e2: new hearings are relisted each run; a relist failure does not skip capture."""
    steps = workflow('capture-archive.yml')['jobs']['capture']['steps']
    runtime = next(i for i, step in enumerate(steps) if step.get('uses') == './.github/actions/setup-local-job-runtime')
    meetings = next(i for i, step in enumerate(steps) if 'congress_api.cli.fetch_meetings' in step.get('run', ''))
    capture = next(i for i, step in enumerate(steps) if 'capture_schedule' in step.get('run', ''))
    assert runtime < meetings < capture and steps[runtime]['id'] == 'runtime'
    assert steps[capture]['if'] == "${{ !cancelled() && steps.runtime.outcome == 'success' }}"
    env = steps[meetings]['env']
    assert env['DATA_GOV_API_KEY'] == '${{ secrets.DATA_GOV_API_KEY }}' and 'ZYTE_TOKEN' not in env
    assert env['R2_ACCESS_KEY_ID'] == steps[capture]['env']['R2_ACCESS_KEY_ID']
    assert '${{ runner.temp }}/archive-meetings/summary.json' in steps[-1]['with']['path']
    tools = tmp_path / '.venv/bin'
    tools.mkdir(parents=True)
    interpreter = tools / 'python'
    interpreter.write_text(f'#!{sys.executable}\nimport json, sys\nprint(json.dumps(sys.argv[1:]))\n')
    interpreter.chmod(0o755)
    result = subprocess.run(['bash', '-eo', 'pipefail', '-c', steps[meetings]['run']], cwd=tmp_path,
                            env=dict(PATH=os.defpath, RUNNER_TEMP=str(tmp_path)), capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads((tmp_path / 'archive-meetings/summary.json').read_text()) == [
        '-I', '-m', 'congress_api.cli.fetch_meetings', '--since-days', '7',
        '--user-agent', 'congressional-tech-research/1.0', '--apply']


def test_deploy_and_validation_add_local_archive_contract_before_upload():
    for name, job in [('deploy-pages.yml', 'build'), ('validate-explorer.yml', 'validate')]:
        steps = workflow(name)['jobs'][job]['steps']
        contract = next(i for i, step in enumerate(steps) if 'verify-archive-contract.py' in step.get('run', ''))
        build = next(i for i, step in enumerate(steps) if step.get('name') in {'Build Astro site', 'Build the static site'})
        assert contract > build
        assert_site_browser_pin(steps, contract)
        if name == 'deploy-pages.yml':
            upload = next(i for i, step in enumerate(steps) if step.get('uses', '').startswith('actions/upload-pages-artifact@'))
            assert contract < upload


def test_active_workflow_binding_requires_explicit_execute_before_preflight(tmp_path):
    cases=[(None,2),([],2),(['--plan'],2),('--execute',2),(['--execute'],0)]
    for index,(argv,expected) in enumerate(cases):
        root=tmp_path/str(index)
        root.mkdir()
        script=active_publisher_fixture(root)
        bindings=root/'.github/archive-jobs.json'
        value=json.loads(bindings.read_bytes())
        if argv is None:del value['publish']['argv']
        else:value['publish']['argv']=argv
        bindings.write_text(json.dumps(value))
        result=subprocess.run([sys.executable,'-I',str(script),'publish','--check-binding'],
            cwd=root,capture_output=True,text=True,timeout=10,env={'PATH':os.environ['PATH']})
        assert result.returncode==expected,result.stderr
        if expected:assert 'explicit --execute' in result.stderr


def test_workflow_command_invokes_the_owner_module_once_in_execute_mode():
    import importlib.util
    spec=importlib.util.spec_from_file_location('archive_job',ROOT/'.github/scripts/run-archive-job.py')
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    binding=dict(module='viewer_publication.archive_publish_job',argv=['--execute'],rss_gb=12)
    path=Path('/local/owner-job.json')
    owner=[sys.executable,'-I','-m','viewer_publication.archive_publish_job','--spec',str(path),'--execute']
    assert runner.binding_command(binding,path)==owner
    assert runner.watched_command(owner, binding, 'publish', '/runner-temp', env={}) == [
        sys.executable, '-I', str(ROOT / 'scripts/archive_watchdog.py'),
        '--rss-gb', '12', '--report', '/runner-temp/publish-watchdog.json', '--timeline', '--min-disk-gb', '15',
        '--', *owner]
    assert runner.watched_command(owner, binding, 'publish', '/runner-temp', env={'GITHUB_ACTIONS': 'true'}) == [
        sys.executable, '-I', str(ROOT / 'scripts/archive_watchdog.py'),
        '--rss-gb', '12', '--report', '/runner-temp/publish-watchdog.json', '--timeline', '--min-disk-gb', '15',
        '--min-available-gb', '0', '--', *owner]


def test_hosted_publish_runs_backfill_once_when_daily_reports_backfill_required(tmp_path, monkeypatch):
    import importlib.util
    from types import SimpleNamespace

    spec = importlib.util.spec_from_file_location('archive_job', ROOT / '.github/scripts/run-archive-job.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    root = tmp_path / 'repo'
    jobs_dir = root / 'model/jobs'
    jobs_dir.mkdir(parents=True)
    (root / '.github').mkdir()
    (root / 'scripts').mkdir()
    (root / 'scripts/archive_disk.py').write_bytes((ROOT / 'scripts/archive_disk.py').read_bytes())

    (jobs_dir / 'publish-model.json').write_text(json.dumps({
        'output': '../../output/archive-release',
        'scratch': '../../output/archive-model',
    }))
    (jobs_dir / 'publish-daily.json').write_text(json.dumps({'work': '../../output/archive-daily'}))
    (jobs_dir / 'publish.json').write_text(json.dumps({
        'work': '../../output/archive-publish',
        'model_spec': {'path': 'publish-model.json'},
        'daily': {'path': 'publish-daily.json'},
    }))
    (jobs_dir / 'backfill.json').write_text(json.dumps({'work': '../../output/archive-backfill'}))
    (root / '.github/archive-jobs.json').write_text(json.dumps({
        'publish': {'module': 'viewer_publication.archive_publish_job', 'spec': 'model/jobs/publish.json', 'argv': ['--execute'], 'rss_gb': 14},
        'backfill': {'module': 'viewer_publication.archive_backfill_job', 'spec': 'model/jobs/backfill.json', 'argv': ['--execute'], 'rss_gb': 12},
    }))

    monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    monkeypatch.delenv('ARCHIVE_DISK_BUDGETS', raising=False)
    monkeypatch.setenv('RUNNER_TEMP', str(tmp_path / 'runner-temp'))

    import shutil

    monkeypatch.setattr(runner, 'ROOT', root)
    rlimit_calls = []
    monkeypatch.setattr(runner, 'raise_file_limit', lambda: rlimit_calls.append(True) or (256, 65536))
    monkeypatch.setattr(shutil, 'disk_usage', lambda _: SimpleNamespace(free=80 * 2**30))
    orig_run_path = runner.runpy.run_path
    def fake_run_path(path):
        mod = orig_run_path(path)
        mod['job_admission'].__globals__['revision'] = lambda _: 'a' * 40
        return mod
    monkeypatch.setattr(runner.runpy, 'run_path', fake_run_path)

    invocations = []
    def fake_run(cmd, cwd=None, pass_fds=()):
        assert '--min-available-gb' in cmd and cmd[cmd.index('--min-available-gb') + 1] == '0'
        report_idx = cmd.index('--report') + 1
        report_name = Path(cmd[report_idx]).name
        invocations.append(report_name)
        # The hosted flag reaches the publisher on both attempts; backfill never sees it.
        assert (cmd[-1] == '--keep-candidate') == report_name.startswith('publish')
        daily_dir = root / 'output/archive-daily'
        pub_dir = root / 'output/archive-publish'
        if report_name == 'publish-watchdog.json':
            daily_dir.mkdir(parents=True)
            pub_dir.mkdir(parents=True)
            (daily_dir / 'daily-summary.json').write_text(json.dumps({'status': 'backfill_required'}))
            return SimpleNamespace(returncode=2)
        if report_name == 'backfill-watchdog.json':
            assert not pub_dir.exists() and not daily_dir.exists()
            assert (tmp_path / 'runner-temp/before-backfill/archive-daily/daily-summary.json').is_file()
            return SimpleNamespace(returncode=0)
        if report_name == 'publish-after-backfill-watchdog.json':
            daily_dir.mkdir(parents=True)
            (daily_dir / 'daily-summary.json').write_text(json.dumps({'status': 'completed'}))
            return SimpleNamespace(returncode=0)
        raise AssertionError(f'Unexpected invocation: {cmd}')

    monkeypatch.setattr(runner.subprocess, 'run', fake_run)
    monkeypatch.setattr(sys, 'argv', ['run-archive-job.py', 'publish', '--keep-candidate'])
    assert runner.main() == 0
    assert rlimit_calls == [True]
    assert invocations == ['publish-watchdog.json', 'backfill-watchdog.json', 'publish-after-backfill-watchdog.json']
    assert (tmp_path / 'runner-temp/backfill-disk-admission.json').is_file()
    assert (tmp_path / 'runner-temp/publish-after-backfill-disk-admission.json').is_file()


def test_an_active_binding_without_a_measured_rss_limit_refuses():
    import importlib.util
    import pytest
    spec=importlib.util.spec_from_file_location('archive_job',ROOT/'.github/scripts/run-archive-job.py')
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    for rss_gb in (None,'12',0,True):
        binding=dict(module='viewer_publication.archive_publish_job',argv=['--execute'])
        if rss_gb is not None:binding['rss_gb']=rss_gb
        with pytest.raises(ValueError,match='no measured rss_gb'):runner.binding_command(binding,Path('/local/job.json'))


def active_publisher_fixture(tmp_path,work='private-evidence'):
    import importlib.util
    from congress_api.retention.provenance import file_pin
    helper=ROOT/'packages/viewer_publication/tests/archive_job_fixture.py'
    spec=importlib.util.spec_from_file_location('archive_job_fixture',helper)
    fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
    scripts=tmp_path/'.github/scripts';scripts.mkdir(parents=True)
    runner=scripts/'run-archive-job.py';runner.write_bytes((ROOT/'.github/scripts/run-archive-job.py').read_bytes())
    model=tmp_path/'model.json';model.write_text(json.dumps(fixtures.model_spec(tmp_path)))
    value=dict(version=1,model_spec=dict(path=str(model),**file_pin(model)),bucket='derived-fixture',work=work,
        public_origin='https://archive.fixture.test',receipt_keys=['receipts/documents/fixture.jsonl.gz'],
        provenance=[],run={'id':'fixture'},contract_next_release=str(tmp_path/'next'),
        targets=dict(path=str(tmp_path/'unopened-targets.json'),sha256='a'*64,size=17))
    (tmp_path/'publish.json').write_text(json.dumps(value))
    (tmp_path/'.github/archive-jobs.json').write_text(json.dumps(dict(publish=dict(
        module='viewer_publication.archive_publish_job',spec='publish.json',argv=['--execute'],rss_gb=8))))
    return runner


def test_github_output_uses_the_owner_plan_without_running_or_opening_runtime(tmp_path):
    runner=active_publisher_fixture(tmp_path);output=tmp_path/'github-output'
    output.write_text('existing=value\n')
    result=subprocess.run([sys.executable,'-I',str(runner),'publish','--check-binding','--github-output',str(output)],
        cwd=tmp_path,capture_output=True,text=True,timeout=15,env={'PATH':os.environ['PATH']})
    assert result.returncode==0,result.stderr
    assert output.read_text()=='existing=value\npublisher_work='+str(tmp_path/'private-evidence')+'\n'
    assert result.stdout==''
    for name in ['private-evidence','model','release','unopened-runtime.json','unopened-targets.json']:
        assert not (tmp_path/name).exists()


def test_pending_binding_exports_no_github_metadata(tmp_path):
    root=tmp_path/'pending'
    scripts=root/'.github/scripts';scripts.mkdir(parents=True)
    runner=scripts/'run-archive-job.py';runner.write_bytes((ROOT/'.github/scripts/run-archive-job.py').read_bytes())
    (root/'publish.pending.json').write_text(json.dumps({'status':'blocked','reason':'Track E blocked'}))
    (root/'.github/archive-jobs.json').write_text(json.dumps({'publish':{'module':'viewer_publication.archive_publish_job','spec':'publish.pending.json'}}))
    output=tmp_path/'github-output'
    result=subprocess.run([sys.executable,'-I',str(runner),'publish',
        '--check-binding','--github-output',str(output)],cwd=tmp_path,capture_output=True,text=True,timeout=10,env={'PATH':'/usr/bin:/bin'})
    assert result.returncode==2 and 'Track E' in result.stderr
    assert not output.exists()


def test_control_characters_in_planned_work_never_reach_github_output(tmp_path):
    for index,character in enumerate(['\n','\r','\0']):
        root=tmp_path/str(index);root.mkdir();runner=active_publisher_fixture(root,work='private'+character+'evidence')
        output=root/'github-output'
        result=subprocess.run([sys.executable,'-I',str(runner),'publish','--check-binding','--github-output',str(output)],
            cwd=root,capture_output=True,text=True,timeout=15,env={'PATH':os.environ['PATH']})
        assert result.returncode!=0
        assert not output.exists()


def test_publish_builds_once_after_node_and_before_the_single_publisher():
    steps=workflow('archive-jobs.yml')['jobs']['publish']['steps']
    admission=next(step for step in steps if '--check-binding' in step.get('run',''))
    assert admission['id']=='publisher_binding' and '--github-output "$GITHUB_OUTPUT"' in admission['run']
    builds=[i for i,step in enumerate(steps) if step.get('run','').strip()=='npm run build']
    assert len(builds)==1
    node=next(i for i,step in enumerate(steps) if step.get('uses')=='./.github/actions/setup-node-project')
    assert node<builds[0]<publisher_index(steps)
    assert steps[builds[0]]['working-directory']=='apps/site' and 'env' not in steps[builds[0]]


def test_publish_retains_only_named_run_evidence_on_success_or_failure():
    steps=workflow('archive-jobs.yml')['jobs']['publish']['steps']
    uploads=[step for step in steps if step.get('uses','').startswith('actions/upload-artifact@')]
    assert len(uploads)==1
    evidence=uploads[0]
    assert evidence['name']=='Retain run evidence (access follows repository)'
    assert evidence['if']=="${{ always() && steps.publisher_binding.outputs.publisher_work != '' }}"
    assert evidence['with']['if-no-files-found']=='ignore'
    assert evidence['with']['path'].splitlines()==[
        *[
            '${{ steps.publisher_binding.outputs.publisher_work }}/'+name
            for name in [
                'outgoing-pointer.json',
                'outgoing-pointer.response.json',
                'contract.json',
                'canary.json',
                'completed-model.json',
                'model-intent.json',
                'candidate-*/release-gate.json',
                'candidate-*/automatic/automatic-trace.json',
                'candidate-*/data-only-night.json',
                'candidate-*/meeting-updates.*',
            ]
        ],
        'output/archive-daily/daily-summary.json',
        'output/archive-release/manifest.json',
        '${{ runner.temp }}/*-disk-admission.json',
        '${{ runner.temp }}/*-watchdog.json',
        '${{ runner.temp }}/*-watchdog.timeline.jsonl',
    ]
    assert 'env' not in evidence
    assert steps.index(evidence)>publisher_index(steps)


def test_publish_ends_by_checking_the_hosted_mcp_against_the_pointer():
    """ct-pz32: nothing redeploys the hosted MCP per release, so each run proves it followed."""
    steps=workflow('archive-jobs.yml')['jobs']['publish']['steps']
    check=steps[-1]
    assert check['name']=='Confirm the hosted MCP serves the selected release' and 'if' not in check
    assert check['env']=={'ARCHIVE_POINTER_URL':'${{ vars.ARCHIVE_POINTER_URL }}',
        'MCP_READY_URL':'https://congress-explorer-mcp.mdeeb.workers.dev/ready'}
    assert '"$served" = "$release"' in check['run'] and check['run'].rstrip().endswith('exit 1')
    wrangler=(ROOT/'apps/explorer_mcp/cloudflare/wrangler.jsonc').read_text()
    assert '"ARCHIVE_POINTER": "https://congressional-data.spicygov.ai/viewer-publications/manifest.json"' in wrangler
    assert '/releases/' not in wrangler, 'the Worker follows the pointer; no release is pinned by hand'


def test_publish_installs_the_local_job_runtime_before_the_publisher():
    """Gate 3 needs DOCSPEC_JOB_CONFIG (local-only) when the publisher starts."""
    steps = workflow('archive-jobs.yml')['jobs']['publish']['steps']
    local = next(i for i, step in enumerate(steps) if step.get('uses') == './.github/actions/setup-local-job-runtime')
    assert local < publisher_index(steps)
    assert steps[local]['with']['credentials'] == '${{ secrets.DOCSPEC_ENGINE_CREDENTIALS }}'


def test_publish_keeps_its_built_candidate_for_a_rerun():
    """ct-31qi: the newest kept candidate is restored just before the publisher, which decides whether
    it is this run's, and the built one is saved just after it, above all when the gates stopped it."""
    from viewer_publication.archive_publish_job import kept_candidate_paths
    steps = workflow('archive-jobs.yml')['jobs']['publish']['steps']
    publisher = publisher_index(steps)
    restore, save = steps[publisher - 1], steps[publisher + 1]
    assert restore['uses'] == 'actions/cache/restore@v6' and save['uses'] == 'actions/cache/save@v6'
    assert steps[publisher - 2]['uses'] == './.github/actions/setup-local-job-runtime'
    # No saved key equals or begins with the restore key: GitHub falls back to the newest by prefix.
    assert restore['with']['key'] == 'archive-publish-candidate-run-${{ github.run_id }}-${{ github.run_attempt }}'
    assert restore['with']['restore-keys'] == 'archive-publish-candidate-'
    checkpoint = "hashFiles('output/archive-publish/completed-model.json')"
    assert save['if'] == "${{ always() && " + checkpoint + " != '' }}"
    assert save['with']['key'] == 'archive-publish-candidate-${{ ' + checkpoint + ' }}'
    assert save['continue-on-error'] == 'true'
    # A different path list is a different cache version: restore and save name the same paths,
    # the ones the publisher reads on a resume, from the shipped specs.
    assert restore['with']['path'] == save['with']['path']
    jobs = ROOT.resolve() / 'model/jobs'
    spec = json.loads((jobs / 'publish.json').read_text())
    model = json.loads((jobs / spec['model_spec']['path']).read_text())
    model = {name: (jobs / model[name]).resolve() for name in ('output', 'scratch')}
    kept = [path.relative_to(ROOT.resolve()).as_posix() for path in kept_candidate_paths((jobs / spec['work']).resolve(), model)]
    assert save['with']['path'].splitlines() == kept and kept[0] in checkpoint


def test_keep_candidate_is_a_hosted_publish_execution_only(tmp_path):
    for args in (['backfill', '--keep-candidate'], ['publish', '--check-binding', '--keep-candidate'],
                 ['publish', '--keep-candidate', '--nightly-work', str(tmp_path)]):
        result = subprocess.run([sys.executable, '-I', str(ROOT / '.github/scripts/run-archive-job.py'), *args],
            cwd=tmp_path, capture_output=True, text=True, timeout=15)
        assert result.returncode == 2 and '--keep-candidate requires a hosted publish execution' in result.stderr


def test_production_jobs_run_the_newest_validated_commit_of_main_and_never_the_tip():
    """Owner decision 2026-11-17: capture, publish, backfill and maintenance check out the newest
    commit whose push validation passed. One identical lookup, placed before the checkout."""
    jobs = {**{f'archive-jobs:{name}': job for name, job in workflow('archive-jobs.yml')['jobs'].items()},
            'capture': workflow('capture-archive.yml')['jobs']['capture']}
    lookups = set()
    for name, job in jobs.items():
        steps = job['steps']
        select = next(i for i, step in enumerate(steps) if step.get('id') == 'validated')
        checkouts = [i for i, step in enumerate(steps) if step.get('uses', '').startswith('actions/checkout@')]
        assert checkouts == [select + 1], name
        assert steps[checkouts[0]]['with']['ref'] == '${{ steps.validated.outputs.sha }}', name
        assert steps[select]['env'] == {'GH_TOKEN': '${{ github.token }}'}
        lookups.add(steps[select]['run'])
    assert len(lookups) == 1
    run = lookups.pop()
    assert 'actions/workflows/validate-explorer.yml/runs?branch=main&event=push&status=success&per_page=1' in run
    assert "jq -er '.workflow_runs[0].head_sha'" in run and 'echo "sha=$sha" >> "$GITHUB_OUTPUT"' in run
    # The lookup fails closed: with no validated run jq exits non-zero under bash -e, before any checkout.
    result = subprocess.run(['/bin/bash', '-eo', 'pipefail', '-c', "echo '{\"workflow_runs\": []}' | jq -er '.workflow_runs[0].head_sha'"],
                            capture_output=True, text=True)
    assert result.returncode != 0
    # Main's tip stands in for the validated commit only when everything since it is a path validation
    # skips. The filter is validate-explorer's own push filter, restated once: keep the two together.
    assert workflow('validate-explorer.yml')['on']['push']['paths'] == ['**', '!.tickets/*.md']
    script = run.split("tip=$(jq -er '", 1)[1].split("' <<<", 1)[0]
    def tip(files, status='ahead', behind=0):
        files = [dict(filename=f, status='modified') if isinstance(f, str) else f for f in files]
        data = dict(files=files, commits=[dict(sha='tip')], status=status, behind_by=behind)
        return subprocess.run(['jq', '-er', script], input=json.dumps(data), capture_output=True, text=True).stdout.strip()
    tickets = ['.tickets/ct-pz32.md']
    assert tip(tickets) == 'tip'
    for status, behind in [('diverged', 1), ('behind', 1), ('ahead', 1), ('identical', 0)]:
        assert not tip(tickets, status, behind)
    assert not tip([]) and not tip([f'.tickets/{n}.md' for n in range(300)])
    for covered in ('src/tool.py', 'docs/notes.md', 'AGENTS.md', 'docs/data/file.json', '.tickets/a/b.md',
                    'model/jobs/publish.json', 'model/jobs/release-causes/cause.json', '.tickets/file.md\n'):
        assert not tip([*tickets, covered])
        assert not tip([dict(filename=tickets[0], status='modified', previous_filename=covered)])
    for status in ('renamed', 'removed'):
        assert not tip([dict(filename=tickets[0], status=status, previous_filename=tickets[0])])


@pytest.mark.parametrize('old_mode,new_mode,expected', [('100644', '100644', 'new'), ('100755', '100644', 'old'),
                                                        ('100644', '120000', 'old'), ('100644', '100755', 'old')])
def test_selector_checks_ticket_modes_on_both_commits(tmp_path, old_mode, new_mode, expected):
    run = next(s['run'] for s in workflow('archive-jobs.yml')['jobs']['publish']['steps'] if s.get('id') == 'validated')
    responses = {
        'runs': {'workflow_runs': [{'head_sha': 'old'}]},
        'old...main': dict(status='ahead', behind_by=0, files=[dict(status='modified', filename='.tickets/a.md')],
                           base_commit=dict(commit=dict(tree=dict(sha='r1'))),
                           commits=[dict(sha='new', commit=dict(tree=dict(sha='r2')))]),
    }
    for tree, mode in [('r1', old_mode), ('r2', new_mode)]:
        responses[tree] = dict(truncated=False, tree=[dict(path='.tickets', type='tree', sha=tree + '-tickets')])
        responses[tree + '-tickets'] = dict(truncated=False, tree=[dict(path='a.md', mode=mode)])
    for name, response in responses.items():
        (tmp_path / name).write_text(json.dumps(response))
    curl = tmp_path / 'curl'
    curl.write_text('#!/bin/bash\nurl=${!#}\np=${url%%\\?*}\ncat "${p##*/}"\n')
    curl.chmod(0o755)
    output = tmp_path / 'output'
    env = dict(os.environ, PATH=str(tmp_path) + os.pathsep + os.environ['PATH'], GH_TOKEN='fixture',
               GITHUB_REPOSITORY='f/r', GITHUB_API_URL='https://fixture', GITHUB_OUTPUT=str(output),
               GITHUB_STEP_SUMMARY=str(tmp_path / 'summary'))
    subprocess.run(['/bin/bash', '-eo', 'pipefail', '-c', run], cwd=tmp_path, env=env, check=True)
    assert output.read_text().strip() == 'sha=' + expected


def test_publish_checks_out_full_history_for_producer_commits():
    """Gate 5: a shallow checkout cannot answer whether a producing commit is reachable."""
    steps = workflow('archive-jobs.yml')['jobs']['publish']['steps']
    checkout = next(step for step in steps if step.get('uses', '').startswith('actions/checkout'))
    assert checkout['with']['fetch-depth'] == '0'


def test_daily_publish_spec_explains_new_receipt_additions_unattended():
    """ct-ud0b: the bound daily publish spec turns on automatic causes; nothing else does."""
    binding = json.loads((ROOT / '.github/archive-jobs.json').read_text())['publish']
    spec = json.loads((ROOT / binding['spec']).read_text())
    assert 'daily' in spec and spec['automatic_causes'] is True


CAUSE_CLASSIFIER = ROOT / '.github/scripts/cause-record-changes.py'


def classified(base, head, repo=ROOT):
    result = subprocess.run([sys.executable, '-I', str(CAUSE_CLASSIFIER), base, head], cwd=repo,
                            check=True, capture_output=True, text=True)
    return result.stdout.strip() == 'true'


def test_real_tier_one_cause_commit_uses_the_fast_path():
    assert classified('fff9e04d~1', 'fff9e04d')


def test_cause_diff_classifier_uses_committed_trees_and_only_the_release_pin(tmp_path):
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=tmp_path, text=True).strip()

    git('init', '-q')
    git('config', 'user.name', 'Fixture')
    git('config', 'user.email', 'fixture@example.org')
    spec = tmp_path / 'model/jobs/publish.json'
    record = spec.parent / 'release-causes/night.json'
    record.parent.mkdir(parents=True)
    record.write_text('{}')
    original = dict(version=1, model_spec=dict(path='model.json', sha256='a' * 64), daily=dict(size=5))
    spec.write_text(json.dumps(original))
    git('add', '.')
    git('commit', '-qm', 'base')
    base = git('rev-parse', 'HEAD')
    # Each diff starts at the same base. Write an actual tree without changing the checkout's branch.
    def check(expected):
        git('add', '-A')
        tree = git('write-tree')
        assert classified(base, tree, tmp_path) is expected

    pin = dict(path='release-causes/night.json', sha256='b' * 64, size=3)
    updated = dict(original, release_causes=pin)
    spec.write_text(json.dumps(updated))
    record.write_text('{"night": true}')
    check(True)
    note = tmp_path / '.tickets/note.md'
    note.parent.mkdir()
    note.write_text('Reviewed the night.')
    check(True)
    for protected in ('docs/notes.md', 'docs/youtube-coverage/research/scripts/tool.py', 'docs/data/map.json',
                      'docs/experiments/study.md', 'docs/measurements/pin.json', '.tickets/a.json', '.tickets/sub/a.md'):
        extra = tmp_path / protected
        extra.parent.mkdir(exist_ok=True, parents=True)
        extra.write_text('{}')
        check(False)
        extra.unlink()
    note.chmod(0o755)
    check(False)
    note.chmod(0o644)
    for path in ('model/jobs/release-causes/evidence/night.json',):
        extra = tmp_path / path
        extra.parent.mkdir(parents=True, exist_ok=True)
        extra.write_text('{}')
    check(True)
    for other in (dict(model_spec=dict(path='other')), dict(daily=dict(size=6)), dict(version=True), dict(extra=None)):
        spec.write_text(json.dumps(dict(updated, **other)))
        check(False)
    spec.write_text('{"version":2,"version":1}')
    check(False)
    spec.write_text(json.dumps(original))  # A record + ticket without a pin edit also qualifies.
    check(True)
    record.write_text('{"truncated"')
    check(False)
    record.unlink()
    check(False)
    record.write_text('{}')
    sql = tmp_path / 'model/sql/list.sql'
    sql.parent.mkdir()
    sql.write_text('select 1')
    check(False)
    sql.unlink()
    active = tmp_path / 'docs/experiments/test_input.py'
    active.parent.mkdir(exist_ok=True)
    active.write_text('assert False')
    check(False)
    active.unlink()
    (tmp_path / 'model/jobs/release-causes/evidence/night.json').unlink()
    check(False)  # Only docs and a ticket differ from base.
    git('commit', '-qm', 'ticket')
    base = git('rev-parse', 'HEAD')
    record.write_text('{"updated": true}')
    note.rename(note.with_name('renamed.md'))
    check(False)
    note.with_name('renamed.md').unlink()
    check(False)
    assert not classified('missing-base', 'HEAD', tmp_path)


def test_checked_binding_refuses_wrong_cause_schema_record_hash_and_evidence_hash(tmp_path):
    from hashlib import sha256
    runner = active_publisher_fixture(tmp_path)
    spec = tmp_path / 'publish.json'
    cause = tmp_path / 'night.json'
    evidence = tmp_path / 'evidence.json'
    evidence.write_text('{}')

    def pin(path):
        data = path.read_bytes()
        return dict(path=path.name, sha256=sha256(data).hexdigest(), size=len(data))

    group = dict(id='f|group|detail', count=2, disposition='explained', cause='Measured', evidence=[pin(evidence)])
    def bind(record):
        cause.write_text(json.dumps(record))
        spec.write_text(json.dumps(dict(json.loads(spec.read_bytes()), release_causes=pin(cause))))

    def check():
        return subprocess.run([sys.executable, '-I', str(runner), 'publish', '--check-binding'],
                              cwd=tmp_path, capture_output=True, text=True, timeout=10).returncode

    record = dict(version=1, base_release_id='a' * 64, candidate_release_id='b' * 64, groups=[group])
    bind(record)
    assert check() == 0
    cause.write_text(json.dumps(dict(record, version=2)))  # Same size, different bytes.
    assert check() != 0
    for invalid in (dict(record, groups=[dict(group, count=True)]), dict(record, version=True),
                    dict(record, groups=[dict(group, evidence=[dict(pin(evidence), sha256=None)])])):
        bind(invalid)
        assert check() != 0
    bind(record)
    evidence.write_text('[]')
    assert check() != 0


@pytest.mark.parametrize('absolute', [False, True])
def test_cause_validation_checks_an_unbound_record_and_every_changed_evidence_pin(tmp_path, absolute):
    import shutil
    def git(*args):
        return subprocess.run(['git', *args], cwd=tmp_path, check=True, capture_output=True)
    git('init', '-q')
    git('config', 'user.name', 'Fixture')
    git('config', 'user.email', 'fixture@example.org')
    history = Path('model/jobs/release-causes')
    # This cause has portable evidence and existing tickets. Use its real, checked bytes.
    record = history / 'ab0192939dfd-0e7084cde775.json'
    evidence = history / 'evidence' / record.name
    (tmp_path / evidence.parent).mkdir(parents=True)
    for path in (record, evidence):
        shutil.copyfile(ROOT / path, tmp_path / path)
    git('add', '.')
    git('commit', '-qm', 'base')
    def verify():
        git('add', '-A')
        git('commit', '-qm', 'changed records')
        return subprocess.run([sys.executable, '-I', str(CAUSE_CLASSIFIER), '--verify', 'HEAD~1', 'HEAD'],
                              cwd=tmp_path, capture_output=True, text=True)
    outside = Path('docs/measurements') / evidence.name
    (tmp_path / outside).parent.mkdir(parents=True)
    (tmp_path / evidence).rename(tmp_path / outside)
    path = tmp_path / record
    # Both relative and absolute pins into this checkout name files in the Git diff.
    path.write_text(path.read_text().replace(str(evidence), str(tmp_path / outside if absolute else outside)))
    assert verify().returncode == 0
    evidence = outside
    (tmp_path / evidence).write_text('{}')
    assert verify().returncode != 0
    bad = tmp_path / history / 'unbound.json'
    bad.write_text('{"groups":[]}')
    assert verify().returncode != 0
    bad.unlink()
    shutil.copyfile(ROOT / history / 'evidence' / record.name, tmp_path / evidence)
    assert verify().returncode == 0
    def full():
        return subprocess.run([sys.executable, '-I', str(CAUSE_CLASSIFIER), '--verify'], cwd=tmp_path, capture_output=True)
    assert full().returncode == 0
    (tmp_path / evidence).write_text('[]')
    assert full().returncode != 0
    shutil.copyfile(ROOT / history / 'evidence' / record.name, tmp_path / evidence)
    bad.write_text('{"groups":[],"version":1,"version":1}')
    assert full().returncode != 0


def test_cause_only_ci_runs_doctor_and_binding_and_preserves_the_merge_gate():
    jobs = workflow('validate-explorer.yml')['jobs']
    changes = jobs['changes']
    steps = changes['steps']
    classifier = next(s for s in steps if s.get('id') == 'scope')
    assert classifier['env']['BASE'] == '${{ github.event.pull_request.base.sha || github.event.before }}'
    assert 'git merge-base --is-ancestor "$validated" "$BASE"' in classifier['run']
    assert changes['outputs']['cause_record_only'] == '${{ steps.scope.outputs.cause_record_only }}'
    check = next(s for s in steps if 'publish --check-binding' in s.get('run', ''))
    setup = next(s for s in steps if s.get('uses') == './.github/actions/setup-python-project')
    assert 'if' not in setup and 'if' not in check
    assert steps.index(classifier) < steps.index(setup) < steps.index(check)
    assert 'cause-record-changes.py --verify "${range[@]}"' in check['run']
    assert 'continue-on-error' not in check and 'continue-on-error' not in changes
    assert jobs['offline']['needs'] == 'changes' and jobs['validate']['needs'] == ['changes', 'offline']
    for name in ('offline', 'validate'):
        assert "needs.changes.outputs.cause_record_only != 'true'" in jobs[name]['if']
    gate = workflow('merge-gate.yml')
    assert gate['on'] == {'pull_request': ''} and 'if' not in gate['jobs']['merge-gate']


def test_push_scope_inherits_only_code_that_already_passed(tmp_path):
    import shutil
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=tmp_path, text=True).strip()
    git('init', '-q')
    git('config', 'user.name', 'Fixture')
    git('config', 'user.email', 'fixture@example.org')
    helper = tmp_path / '.github/scripts' / CAUSE_CLASSIFIER.name
    helper.parent.mkdir(parents=True)
    shutil.copyfile(CAUSE_CLASSIFIER, helper)
    def commit(message):
        git('add', '.')
        git('commit', '-qm', message)
        return git('rev-parse', 'HEAD')
    older = commit('validated code')
    (tmp_path / 'code.py').write_text('print(1)')
    before = commit('intervening code')
    record = tmp_path / 'model/jobs/release-causes/night.json'
    record.parent.mkdir(parents=True)
    record.write_text('{}')
    commit('cause only')
    # Execute the Actions step with a local stand-in for the read-only run lookup.
    gh = tmp_path / 'gh'
    gh.write_text('#!/bin/sh\necho "$VALIDATED"\n')
    gh.chmod(0o755)
    job = workflow('validate-explorer.yml')['jobs']['changes']
    shell = next(s['run'] for s in job['steps'] if s.get('id') == 'scope')
    branch = git('branch', '--show-current')
    # Same tree as HEAD, but a separate root that lost the validated commit's history.
    rewritten = git('commit-tree', 'HEAD^{tree}', '-m', 'rewritten root')
    for base, validated, event, fast, head in (
            (before, before, 'push', 'true', branch), (before, older, 'push', 'false', branch),
            (before, '', 'push', 'false', branch), (before, older, 'pull_request', 'true', branch),
            (before, before, 'push', 'false', rewritten), ('0' * 40, before, 'push', 'false', branch),
            ('f' * 40, before, 'push', 'false', branch)):
        git('checkout', '-q', head)
        output = tmp_path / 'job-output'
        output.write_text('')
        env = dict(os.environ, PATH=str(tmp_path) + os.pathsep + os.environ['PATH'], VALIDATED=validated,
                   BASE=base, GITHUB_EVENT_NAME=event, GITHUB_REPOSITORY='fixture/repo', GITHUB_OUTPUT=str(output))
        subprocess.run(['/bin/bash', '-eo', 'pipefail', '-c', shell], cwd=tmp_path, check=True, env=env)
        values = dict(line.split('=', 1) for line in output.read_text().splitlines())
        assert values['cause_record_only'] == fast
        if base in ('0' * 40, 'f' * 40):
            assert values['base'] == ''
