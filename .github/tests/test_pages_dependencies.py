"""Pages must use frozen inputs before executing the maintained reader checks."""
from pathlib import Path
import json
import os
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_pages_uses_declared_locked_environments_and_checks_built_reader():
    workflow = yaml.load((ROOT / '.github/workflows/deploy-pages.yml').read_text(), Loader=yaml.BaseLoader)
    from fnmatch import fnmatch
    triggers = workflow['on']['push']['paths']
    assert any(fnmatch('apps/site/src/components/explorer/browse/filename-rules.ts', path) for path in triggers)
    steps = workflow['jobs']['build']['steps']
    assert any(step.get('uses') == './.github/actions/setup-python-project' for step in steps)
    shared = './.github/actions/setup-node-project'
    assert any(step.get('uses') == shared for step in steps)
    action = yaml.load((ROOT / '.github/actions/setup-node-project/action.yml').read_text(), Loader=yaml.BaseLoader)
    setup = action['runs']['steps']
    node = next(step for step in setup if step.get('uses', '').startswith('actions/setup-node@'))
    assert node['with']['node-version-file'] == '.node-version'
    assert node['with']['cache-dependency-path'] == 'apps/site/package-lock.json'
    commands = [step.get('run', '') for step in steps]
    install = setup[-1]
    assert install['working-directory'] == 'apps/site'
    assert install['run'] == 'npm ci --workspaces=false --engine-strict --no-audit --no-fund'
    package = json.loads((ROOT / 'apps/site/package.json').read_text())
    validation = yaml.load((ROOT / '.github/workflows/validate-explorer.yml').read_text(), Loader=yaml.BaseLoader)
    validation_steps = validation['jobs']['validate']['steps']
    assert any(step.get('uses') == shared for step in validation_steps)
    assert '.node-version' in validation['on']['pull_request']['paths']
    assert '.github/actions/**' in validation['on']['pull_request']['paths']
    assert '.github/actions/setup-node-project/**' in triggers
    assert commands.index('npm run test:explorer') > next(i for i, step in enumerate(steps) if step.get('uses') == shared)
    assert commands.index('npm run test:explorer') < commands.index('npm run build')
    assert commands.index('npm run build') < commands.index('npm run test:built-filenames')
    assert any('verify(source)' in command and 'shutil.copytree(source, target, dirs_exist_ok=True)' in command for command in commands)
    assert 'stage-document-reviews.py' in package['scripts']['build']
    lock = json.loads((ROOT / 'apps/site/package-lock.json').read_text())
    assert lock['packages']['']['dependencies'] == package['dependencies']
    assert lock['packages']['']['devDependencies'] == package['devDependencies']


def bootstrap(tmp_path, *, node_version='22.22.2', package_manager='npm@11.19.1', installed_version='11.19.1', fail=False):
    project = tmp_path / 'checkout'; (project / 'apps/site').mkdir(parents=True)
    (project / '.node-version').write_text('22.22.2\n')
    (project / 'apps/site/package.json').write_text(json.dumps({'packageManager': package_manager}))
    tools = tmp_path / 'bootstrap-bin'; tools.mkdir()
    temporary = tmp_path / 'runner-temp'; temporary.mkdir()
    github_path = tmp_path / 'github-path'; github_path.write_text('')
    log = tmp_path / 'install.json'
    node = tools / 'node'
    node.write_text(f'#!{sys.executable}\n' + '''import json, os, pathlib, sys
if sys.argv[1:] == ['-p', 'process.versions.node']:
    print(os.environ['TEST_NODE_VERSION'])
elif sys.argv[1:2] == ['-p']:
    print(json.loads(pathlib.Path('apps/site/package.json').read_text())['packageManager'])
elif sys.argv[1:] == ['--version']:
    print('v' + os.environ['TEST_NODE_VERSION'])
else:
    raise AssertionError(sys.argv)
''')
    npm = tools / 'npm'
    npm.write_text(f'#!{sys.executable}\n' + '''import json, os, pathlib, sys
args = sys.argv[1:]
assert args[:2] == ['install', '--global'] and '--prefix' in args
prefix = pathlib.Path(args[args.index('--prefix') + 1])
assert prefix.parent.resolve() == pathlib.Path(os.environ['RUNNER_TEMP']).resolve()
assert prefix.is_dir() and not list(prefix.iterdir())
pathlib.Path(os.environ['TEST_INSTALL_LOG']).write_text(json.dumps({'args':args, 'prefix':str(prefix)}))
if os.environ['TEST_INSTALL_FAIL'] == 'true':
    sys.exit(42)
(prefix / 'bin').mkdir()
runtime = prefix / 'bin/npm'
runtime.write_text('#!' + sys.executable + '\\nprint(' + repr(os.environ['TEST_INSTALLED_VERSION']) + ')\\n')
runtime.chmod(0o755)
''')
    node.chmod(0o755); npm.chmod(0o755)
    action = yaml.load((ROOT / '.github/actions/setup-node-project/action.yml').read_text(), Loader=yaml.BaseLoader)
    script = action['runs']['steps'][1]['run']
    env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ['PATH'], RUNNER_TEMP=str(temporary),
        GITHUB_PATH=str(github_path), TEST_NODE_VERSION=node_version, TEST_INSTALLED_VERSION=installed_version,
        TEST_INSTALL_LOG=str(log), TEST_INSTALL_FAIL=str(fail).lower())
    result = subprocess.run(['bash', '-c', script], cwd=project, env=env, capture_output=True, text=True, timeout=15)
    return result, github_path.read_text(), json.loads(log.read_text()) if log.exists() else None


def test_npm_bootstrap_installs_into_fresh_owned_prefix_then_activates(tmp_path):
    result, activated, install = bootstrap(tmp_path)
    assert result.returncode == 0, result.stderr
    assert activated.strip() == str(Path(install['prefix']) / 'bin')
    assert install['args'] == ['install', '--global', '--prefix', install['prefix'],
                               'npm@11.19.1', '--ignore-scripts', '--no-audit', '--no-fund']
    assert install['prefix'] not in os.environ.get('PATH', '')
    assert '11.19.1' in result.stdout


@pytest.mark.parametrize('settings', [
    {'node_version': '22.0.0'}, {'package_manager': 'npm@latest'},
    {'installed_version': '11.18.0'}, {'fail': True},
])
def test_failed_or_mismatched_bootstrap_never_activates_runtime(tmp_path, settings):
    result, activated, _ = bootstrap(tmp_path, **settings)
    assert result.returncode != 0
    assert activated == ''


def test_dispatched_site_revision_must_match_workflow_before_checkout(tmp_path):
    workflow = yaml.load((ROOT / '.github/workflows/deploy-pages.yml').read_text(), Loader=yaml.BaseLoader)
    jobs = workflow['jobs']
    # Admission belongs on the job, before a mismatched checkout can execute
    # local actions. Matching dispatches and main pushes use the workflow SHA.
    assert jobs['build']['if'] == "github.event_name != 'workflow_dispatch' || inputs.code_revision == github.sha"
    assert jobs['build']['steps'][0]['with']['ref'] == '${{ github.sha }}'
    assert jobs['build']['steps'][1]['with']['ref'] == "${{ inputs.pipeline_revision || 'pipeline-data' }}"
    assert jobs['deploy']['needs'] == 'build'
    mismatch = jobs['revision-mismatch']
    assert mismatch['if'] == "github.event_name == 'workflow_dispatch' && inputs.code_revision != github.sha"
    assert len(mismatch['steps']) == 1 and 'uses' not in mismatch['steps'][0]
    step = mismatch['steps'][0]
    assert step['env'] == {'SITE_REVISION': '${{ inputs.code_revision }}',
                           'WORKFLOW_REVISION': '${{ github.sha }}',
                           'PIPELINE_REVISION': '${{ inputs.pipeline_revision }}'}
    summary = tmp_path / 'summary.md'
    env = dict(os.environ, SITE_REVISION='dbfe389bb7e68fca10b3ba8fd2f0f9a33a44f5f9',
               WORKFLOW_REVISION='c326ce24c9b4f0f9ebc8deec6d5d16b9a42c350e',
               PIPELINE_REVISION='a' * 40, GITHUB_STEP_SUMMARY=str(summary))
    result = subprocess.run(['bash', '-c', step['run']], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=10, check=True)
    receipt = json.loads(result.stdout)
    assert receipt == {'status': 'skipped', 'reason': 'site_and_workflow_revisions_differ',
                       'site_revision': env['SITE_REVISION'], 'workflow_revision': env['WORKFLOW_REVISION'],
                       'pipeline_revision': env['PIPELINE_REVISION']}
    assert 'verified pipeline snapshot remains retained' in summary.read_text()
    assert list(tmp_path.iterdir()) == [summary]
