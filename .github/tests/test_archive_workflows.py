"""F1 workflow admission, one writer group, and a refusing model binding."""
from pathlib import Path
import json
import os
import subprocess
import sys

import yaml

ROOT = Path(__file__).parents[2]


def workflow(name):
    return yaml.load((ROOT / '.github/workflows' / name).read_text(), Loader=yaml.BaseLoader)


def test_publish_backfill_maintenance_share_one_non_canceling_group():
    value = workflow('archive-jobs.yml')
    for name in ['archive-jobs.yml','update-data.yml','publish-explorer.yml']:
        assert workflow(name)['concurrency'] == {'group': 'raw-source-mirror', 'cancel-in-progress': 'false', 'queue': 'max'}
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


def test_new_capture_uses_scheduler_and_common_lock_with_explicit_switch():
    value = workflow('capture-archive.yml')
    assert value['concurrency'] == {'group': 'raw-source-mirror', 'cancel-in-progress': 'false', 'queue': 'max'}
    job = value['jobs']['capture']
    assert "vars.ARCHIVE_CAPTURE_ENABLED == 'true'" in job['if']
    assert value['permissions'] == {'contents': 'read'}
    command = '\n'.join(step.get('run', '') for step in job['steps'])
    assert 'congress_api.cli.capture_schedule' in command
    assert '--seed-inventory' in command
    assert all(arg in command for arg in ['--request-budget', '--byte-budget', '--spool-budget'])
    assert '--max-file-mib' not in command and '--replay' not in command and 'raw-source-sync' not in command
    preflight = next(i for i, step in enumerate(job['steps']) if step.get('uses') == './.github/actions/setup-local-job-runtime')
    effect = next(i for i, step in enumerate(job['steps']) if 'capture_schedule' in step.get('run', ''))
    assert preflight < effect and 'env' not in job['steps'][preflight]
    assert 'doctor' in (ROOT / '.github/scripts/setup-local-job-runtime.py').read_text()
    assert job['steps'][effect]['env']['DATA_GOV_API_KEY'] == '${{ secrets.DATA_GOV_API_KEY }}'
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
    assert config['publish']['module'] == 'viewer_publication.archive_publish_job'
    assert config['publish']['spec'] == 'model/jobs/publish.pending.json'


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
               REQUEST_BUDGET='19', BYTE_BUDGET='2048', SPOOL_BUDGET='1024')
    result = subprocess.run(['bash', '-eo', 'pipefail', '-c', step['run']], cwd=tmp_path,
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads((tmp_path / 'invocation.json').read_text()) == [
        '-I', '-m', 'congress_api.cli.capture_schedule', '--pointer', env['ARCHIVE_POINTER'],
        '--request-budget', '19', '--byte-budget', '2048', '--spool-budget', '1024',
        '--work', str(tmp_path / 'archive-capture'), '--apply',
        '--seed-inventory', 'pipeline-data/meeting-inventory/house.json.gz']
    (tmp_path / 'invocation.json').unlink()
    env['REQUEST_BUDGET'] = '0'
    result = subprocess.run(['bash', '-eo', 'pipefail', '-c', step['run']], cwd=tmp_path,
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert not (tmp_path / 'invocation.json').exists()


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


def test_active_workflow_binding_requires_explicit_execute_before_preflight(tmp_path):
    cases=[(None,2),([],2),(['--plan'],2),('--execute',2),(['--execute'],0)]
    for index,(argv,expected) in enumerate(cases):
        root=tmp_path/str(index);scripts=root/'.github/scripts';scripts.mkdir(parents=True)
        script=scripts/'run-archive-job.py';script.write_bytes((ROOT/'.github/scripts/run-archive-job.py').read_bytes())
        spec=root/'owner-job.json';spec.write_text(json.dumps({'version':1}))
        binding=dict(module='viewer_publication.archive_publish',spec='owner-job.json')
        if argv is not None:binding['argv']=argv
        (root/'.github/archive-jobs.json').write_text(json.dumps({'publish':binding}))
        result=subprocess.run([sys.executable,'-I',str(script),'publish','--check-binding'],
            cwd=tmp_path,capture_output=True,text=True,timeout=10,env={'PATH':'/usr/bin:/bin'})
        assert result.returncode==expected,result.stderr
        if expected:assert 'explicit --execute' in result.stderr


def test_workflow_command_invokes_the_owner_module_once_in_execute_mode():
    import importlib.util
    spec=importlib.util.spec_from_file_location('archive_job',ROOT/'.github/scripts/run-archive-job.py')
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    binding=dict(module='viewer_publication.archive_publish_job',argv=['--execute'])
    path=Path('/local/owner-job.json')
    assert runner.binding_command(binding,path)==[sys.executable,'-I','-m','viewer_publication.archive_publish_job','--spec',str(path),'--execute']


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
        module='viewer_publication.archive_publish_job',spec='publish.json',argv=['--execute']))))
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
    output=tmp_path/'github-output'
    result=subprocess.run([sys.executable,'-I',str(ROOT/'.github/scripts/run-archive-job.py'),'publish',
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
    publish=next(i for i,step in enumerate(steps) if step.get('run','').endswith('run-archive-job.py publish'))
    assert node<builds[0]<publish
    assert steps[builds[0]]['working-directory']=='apps/site' and 'env' not in steps[builds[0]]


def test_publish_retains_only_named_run_evidence_on_success_or_failure():
    steps=workflow('archive-jobs.yml')['jobs']['publish']['steps']
    uploads=[step for step in steps if step.get('uses')=='actions/upload-artifact@v4']
    assert len(uploads)==1
    evidence=uploads[0]
    assert evidence['name']=='Retain run evidence (access follows repository)'
    assert evidence['if']=="${{ always() && steps.publisher_binding.outputs.publisher_work != '' }}"
    assert evidence['with']['if-no-files-found']=='ignore'
    assert evidence['with']['path'].splitlines()==[
        '${{ steps.publisher_binding.outputs.publisher_work }}/'+name
        for name in ['outgoing-pointer.json','outgoing-pointer.response.json','contract.json','canary.json']]
    assert 'env' not in evidence
    assert steps.index(evidence)>next(i for i,step in enumerate(steps)
        if step.get('run','').endswith('run-archive-job.py publish'))
