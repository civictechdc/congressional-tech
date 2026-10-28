"""Raw writer execution stays pinned even when the job's data checkout is dirty."""
import json
import os
import pytest
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
    validation = next(step for step in steps if step.get('name')=='Identify installed validation environment')
    assert steps.index(prepare)<steps.index(validation)<steps.index(runtime)<steps.index(manifest)<steps.index(capture)
    assert 'uv pip freeze --python "$RAW_WRITER_ROOT/.venv/bin/python"' in validation['run']
    assert '"$RUNNER_TEMP/raw-writer/.venv/bin" >> "$GITHUB_PATH"' in prepare['run']
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
    assert script.index('git commit -q') < script.index('prepare-raw-writer.sh') < script.index('congress_api.cli.pipeline_raw') < script.index('push -q -f origin snapshot:pipeline-data')
    assert 'git -C "$application_root" rev-parse HEAD' in script
    assert '"$writer_root/.venv/bin/python" -I -m congress_api.cli.pipeline_raw --snapshot "$snapshot_root"' in script
    assert 'cd "$writer_root"' not in script
    workflow = yaml.load((ROOT/'.github/workflows/update-data.yml').read_text(),Loader=yaml.BaseLoader)
    for job in workflow['jobs'].values():
        assert any(step.get('uses')=='astral-sh/setup-uv@v6' or
                   step.get('uses')=='./.github/actions/setup-python-project' for step in job['steps'])


@pytest.mark.parametrize('workflow_name', ['update-data.yml', 'publish-explorer.yml'])
@pytest.mark.parametrize('failure', [None, 'setup', 'body', 'receipt', 'push'])
def test_weekly_snapshot_preserves_raw_before_publishing(tmp_path, failure, workflow_name):
    original = tmp_path/'job'
    application(original)
    scripts = original/'.github/scripts'
    scripts.mkdir(parents=True)
    for name in ('save-pipeline-data.sh','prepare-raw-writer.sh'):
        shutil.copy(ROOT/'.github/scripts'/name,scripts/name)
    git(original,'add','.')
    git(original,'commit','-qm','snapshot tools')
    revision = git(original,'rev-parse','HEAD')
    snapshot = original/'pipeline-data'
    application(snapshot)
    remote = tmp_path/'snapshot-origin.git'
    subprocess.run(['git','init','--bare','-q',str(remote)],check=True)
    git(snapshot,'remote','add','origin',str(remote))
    git(snapshot,'push','-q','origin','HEAD:pipeline-data')
    old_remote = git(snapshot,'rev-parse','HEAD')
    (original/'application.py').write_text('dirty derived data\n')
    (original/'report.json').write_text('{}')
    env = tools(tmp_path)
    probe = tmp_path/'writer-python'
    probe.write_text(f'#!{sys.executable}\n' +
        "import hashlib,io,json,os,pathlib,subprocess,sys\n"
        "root=pathlib.Path(__file__).resolve().parents[2]\n"
        "assert sys.argv[1:4]==['-I','-m','congress_api.cli.pipeline_raw']\n"
        "snapshot=pathlib.Path(sys.argv[sys.argv.index('--snapshot')+1])\n"
        "assert snapshot.is_absolute() and not snapshot.is_relative_to(root)\n"
        "status=subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True)\n"
        "assert status==''\n"
        "value=dict(root=str(root),snapshot=str(snapshot),commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),application=(root/'application.py').read_text(),lockfile_digest=hashlib.sha256((root/'uv.lock').read_bytes()).hexdigest())\n"
        "pathlib.Path(os.environ['WRITER_EXECUTION']).write_text(json.dumps(value))\n"
        "from congress_api.retention import pipeline_raw\n"
        "from congress_api.retention.body_store import BodyStore,LocalAdapter,create_stored\n"
        "from congress_api.retention.writer_identity import writer_identity\n"
        "def event(name):\n"
        "    with open(os.environ['EVENTS'],'a') as log: log.write(name+'\\n')\n"
        "class Adapter(LocalAdapter):\n"
        "    def create(self,key,source,**facts):\n"
        "        kind='body' if key.startswith('bodies/') else 'receipt'\n"
        "        if os.environ['FAILURE']==kind: raise OSError('fixture '+kind+' failure')\n"
        "        created=super().create(key,source,**facts)\n"
        "        event(kind)\n"
        "        return created\n"
        "class Store:\n"
        "    def __init__(self):\n"
        "        self.adapter=Adapter(os.environ['RAW_ROOT']); self.raw=BodyStore(self.adapter)\n"
        "    def put(self,key,payload,*,immutable):\n"
        "        assert immutable\n"
        "        return create_stored(self.adapter,key,io.BytesIO(payload),'application/x-ndjson')\n"
        "pipeline_raw.archive(Store(),pipeline_raw.checkout_files(snapshot),writer=writer_identity(root,'test'))\n"
        "event('preserved')\n")
    probe.chmod(0o755)
    uv = Path(env['PATH'].split(os.pathsep)[0])/'uv'
    uv.write_text(f'#!{sys.executable}\n' +
        "import os,pathlib,shutil,subprocess,sys\n"
        "assert sys.argv[1:3]==['sync','--locked']\n"
        "root=pathlib.Path(sys.argv[sys.argv.index('--project')+1])\n"
        "snapshot=pathlib.Path(os.environ['SNAPSHOT'])\n"
        "assert subprocess.check_output(['git','-C',str(snapshot),'show','-s','--format=%s'],text=True).startswith('Pipeline data snapshot:')\n"
        "with open(os.environ['EVENTS'],'a') as log: log.write('setup\\n')\n"
        "if os.environ['FAILURE']=='setup': sys.exit(71)\n"
        "(root/'.venv/bin').mkdir(parents=True)\n"
        "shutil.copy(os.environ['WRITER_PROBE'],root/'.venv/bin/python')\n")
    temporary = tmp_path/'temporary'
    temporary.mkdir()
    real_git = shutil.which('git')
    wrapper = uv.parent/'git'
    wrapper.write_text(f'#!{sys.executable}\n' +
        "import os,subprocess,sys\n"
        "if 'push' in sys.argv[1:]:\n"
        "    with open(os.environ['EVENTS'],'a') as log: log.write('push\\n')\n"
        "    assert subprocess.check_output([os.environ['REAL_GIT'],'-C',os.environ['SNAPSHOT'],'remote','get-url','origin'],text=True).strip()==os.environ['BARE_REMOTE']\n"
        "    if os.environ['FAILURE']=='push': sys.exit(72)\n"
        "os.execv(os.environ['REAL_GIT'],[os.environ['REAL_GIT'],*sys.argv[1:]])\n")
    wrapper.chmod(0o755)
    env.update(RUNNER_TEMP=str(temporary),WRITER_EXECUTION=str(tmp_path/'execution.json'),
        WRITER_PROBE=str(probe),FAILURE=failure or '',EVENTS=str(tmp_path/'events'),
        RAW_ROOT=str(tmp_path/'raw'),SNAPSHOT=str(snapshot),REAL_GIT=real_git,BARE_REMOTE=str(remote))
    workflow = yaml.load((ROOT/'.github/workflows'/workflow_name).read_text(), Loader=yaml.BaseLoader)
    commands = [step['run'] for job in workflow['jobs'].values() for step in job['steps']
                if '.github/scripts/save-pipeline-data.sh' in step.get('run', '')]
    assert commands
    result = subprocess.run(['bash', '-e', '-c', commands[0]], cwd=original,
                            env=env,capture_output=True,text=True)
    events = (tmp_path/'events').read_text().splitlines()
    remote_head = subprocess.check_output(['git','--git-dir',str(remote),'rev-parse','pipeline-data'],text=True).strip()
    if failure:
        assert result.returncode != 0
        assert remote_head == old_remote
        assert events.count('push') == (1 if failure == 'push' else 0)
        if failure == 'setup':
            assert events == ['setup'] and not (tmp_path/'execution.json').exists()
        elif failure == 'body':
            assert events == ['setup'] and not list((tmp_path/'raw').rglob('*.jsonl.gz'))
        elif failure == 'receipt':
            assert 'body' in events and 'receipt' not in events
            assert any((tmp_path/'raw/bodies').rglob('*'))
        else:
            assert events.index('receipt') < events.index('preserved') < events.index('push')
        return
    assert result.returncode == 0,result.stderr
    assert events[0] == 'setup' and events[-2:] == ['preserved','push']
    assert events.index('body') < events.index('receipt') < events.index('preserved')
    assert events.count('push') == 1
    executed = json.loads(Path(env['WRITER_EXECUTION']).read_text())
    assert executed['commit']==revision
    assert executed['application']=='committed application\n'
    assert executed['lockfile_digest']==__import__('hashlib').sha256((original/'uv.lock').read_bytes()).hexdigest()
    assert executed['snapshot']==str(snapshot)
    assert not Path(executed['root']).is_relative_to(original)
    assert git(snapshot,'rev-parse','HEAD')==subprocess.check_output(
        ['git','--git-dir',str(remote),'rev-parse','pipeline-data'],text=True).strip()
    assert (original/'application.py').read_text()=='dirty derived data\n'
