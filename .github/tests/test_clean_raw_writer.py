"""Raw writer execution stays pinned even when the job's data checkout is dirty."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / '.github/scripts/prepare-raw-writer.sh'


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), '-c', 'user.name=Test',
        '-c', 'user.email=test@example.invalid', *args], text=True).strip()


def application(root):
    root.mkdir()
    git(root, 'init', '-q')
    (root / '.gitignore').write_text('.venv/\n')
    (root / 'uv.lock').write_text('locked dependencies\n')
    (root / 'application.py').write_text('committed application\n')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'application')
    return git(root, 'rev-parse', 'HEAD')


def tools(tmp_path):
    directory = tmp_path / 'bin'
    directory.mkdir()
    uv = directory / 'uv'
    uv.write_text(f'#!{sys.executable}\n' +
        "import json,os,pathlib,sys\n"
        "assert sys.argv[1:3]==['sync','--locked']\n"
        "root=pathlib.Path(sys.argv[sys.argv.index('--project')+1])\n"
        "(root/'.venv/bin').mkdir(parents=True)\n"
        "(root/'.venv/bin/python').symlink_to(sys.executable)\n"
        "pathlib.Path(os.environ['UV_INVOCATION']).write_text(json.dumps(sys.argv[1:]))\n")
    uv.chmod(0o755)
    return dict(os.environ, PATH=str(directory)+os.pathsep+os.defpath,
                UV_INVOCATION=str(tmp_path/'uv-invocation.json'))


def test_clean_writer_uses_committed_application_and_locked_environment(tmp_path):
    original = tmp_path/'job'
    revision = application(original)
    (original/'application.py').write_text('dirty application must not execute\n')
    (original/'report.json').write_text('{}')
    inventory = original/'pipeline-data'
    inventory.mkdir()
    (inventory/'records.json').write_text('{"record":1}')
    target = tmp_path/'writer'
    env = tools(tmp_path)
    result = subprocess.run(['bash',str(HELPER),str(original),str(target),revision],
                            env=env,capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
    assert (target/'application.py').read_text() == 'committed application\n'
    assert git(target,'rev-parse','HEAD') == revision
    assert git(target,'status','--porcelain') == ''
    assert not (target/'report.json').exists() and not (target/'pipeline-data').exists()
    assert json.loads(Path(env['UV_INVOCATION']).read_text()) == ['sync','--locked','--project',str(target)]
    assert (target/'.venv/bin/python').resolve() == Path(sys.executable).resolve()
    assert (original/'application.py').read_text() == 'dirty application must not execute\n'


def test_writer_checkout_refuses_missing_revision_and_nested_destination(tmp_path):
    original = tmp_path/'job'
    application(original)
    env = tools(tmp_path)
    for destination,revision in [(tmp_path/'absent','f'*40),(original/'writer',git(original,'rev-parse','HEAD'))]:
        result = subprocess.run(['bash',str(HELPER),str(original),str(destination),revision],
                                env=env,capture_output=True,text=True)
        assert result.returncode != 0
        assert not destination.exists()
    assert not Path(env['UV_INVOCATION']).exists()


def test_capture_executes_from_isolated_application_and_keeps_artifacts_external():
    workflow = yaml.load((ROOT/'.github/workflows/capture-raw-sources.yml').read_text(),Loader=yaml.BaseLoader)
    steps = workflow['jobs']['capture']['steps']
    prepare = next(step for step in steps if step.get('name')=='Prepare isolated raw writer')
    runtime = next(step for step in steps if step.get('name')=='Require an approved native runtime before archive access')
    manifest = next(step for step in steps if step.get('name')=='Record and check capture source revision')
    capture = next(step for step in steps if step.get('id')=='sync')
    assert steps.index(prepare)<steps.index(runtime)<steps.index(manifest)<steps.index(capture)
    assert '${{ github.sha }}' in prepare['env'].values()
    assert 'prepare-raw-writer.sh' in prepare['run'] and 'RAW_WRITER_ROOT=' in prepare['run']
    assert '$RAW_WRITER_ROOT/.venv/bin/python' in manifest['run']
    assert '--root "$RAW_WRITER_ROOT"' in manifest['run']
    assert '--output "$GITHUB_WORKSPACE/raw-capture-source-manifest.json"' in manifest['run']
    assert '--native-binary "$GITHUB_WORKSPACE/packages/source-fetch/target/release/source-fetch"' in manifest['run']
    assert '$RAW_WRITER_ROOT/.venv/bin/raw-source-sync' in capture['run']
    assert '$RAW_WRITER_ROOT/.github/scripts/capture-memory-guard.py' in capture['run']
    assert 'cd "$RAW_WRITER_ROOT"' not in capture['run']
    assert '--directory "$RUNNER_TEMP/docspec-runtime"' in runtime['run']


def test_weekly_writer_uses_pinned_clean_python_after_snapshot_save():
    script = (ROOT/'.github/scripts/save-pipeline-data.sh').read_text()
    assert script.index('git push -q -f origin snapshot:pipeline-data') < script.index('prepare-raw-writer.sh')
    assert 'git -C "$application_root" rev-parse HEAD' in script
    assert '"$writer_root/.venv/bin/python" -I -m congress_api.cli.pipeline_raw --snapshot "$snapshot_root"' in script
    assert 'cd "$writer_root"' not in script
    workflow = yaml.load((ROOT/'.github/workflows/update-data.yml').read_text(),Loader=yaml.BaseLoader)
    for job in workflow['jobs'].values():
        assert any(step.get('uses')=='astral-sh/setup-uv@v6' or
                   step.get('uses')=='./.github/actions/setup-python-project' for step in job['steps'])
