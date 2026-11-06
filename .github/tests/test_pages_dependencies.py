"""Pages checks the shared reader without staging the retired publication."""
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
    assert any(fnmatch('apps/site/src/components/explorer/reader/archive.ts', path) for path in triggers)
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
    assert package['scripts']['build'] == 'astro build'
    lock = json.loads((ROOT / 'apps/site/package-lock.json').read_text())
    assert lock['packages']['']['dependencies'] == package['dependencies']
    # ct-3vub: one exact playwright pin, installed by the lock and read by the browser action.
    pin = package['devDependencies']['playwright']
    assert pin.count('.') == 2 and pin.replace('.', '').isdigit()
    assert lock['packages']['node_modules/playwright']['version'] == pin
    browser = yaml.load((ROOT / '.github/actions/setup-publication-browser/action.yml').read_text(), Loader=yaml.BaseLoader)
    script = '\n'.join(step.get('run', '') for step in browser['runs']['steps'])
    assert 'apps/site/node_modules/playwright/cli.js' in script and 'playwright@' not in script
    assert lock['packages']['']['devDependencies'] == package['devDependencies']


def test_archive_contract_gates_the_pages_upload_without_the_legacy_filename_worker():
    # The archive pointer switch made the legacy filename worker unable to load
    # the live pointer, so its live checks were removed; the archive contract
    # (and the publisher's live canary) cover the reader that replaced it.
    workflow = yaml.load((ROOT / '.github/workflows/deploy-pages.yml').read_text(), Loader=yaml.BaseLoader)
    build = workflow['jobs']['build']['steps']
    gate = next(i for i, step in enumerate(build) if step.get('name', '').startswith('Require the archive contract'))
    upload = next(i for i, step in enumerate(build) if step.get('uses') == 'actions/upload-pages-artifact@v3')
    assert gate < upload
    assert 'verify-archive-contract.py' in build[gate]['run']
    assert any(step.get('uses') == './.github/actions/setup-publication-browser' for step in build[:gate])
    deploy = workflow['jobs']['deploy']['steps']
    assert any(step.get('id') == 'deployment' for step in deploy)
    runs = '\n'.join(step.get('run', '') for job in workflow['jobs'].values() for step in job.get('steps', []))
    assert 'verify-built-filename-worker' not in runs and 'verify-live-publication' not in runs
    assert not (ROOT / '.github/scripts/verify-built-filename-worker.sh').exists()


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


def test_pages_checks_out_only_its_own_application_revision():
    workflow = yaml.load((ROOT / '.github/workflows/deploy-pages.yml').read_text(), Loader=yaml.BaseLoader)
    assert workflow['on']['workflow_dispatch'] == {}
    assert set(workflow['jobs']) == {'build', 'deploy'}
    for job in workflow['jobs'].values():
        checkouts = [step for step in job['steps'] if step.get('uses', '').startswith('actions/checkout@')]
        assert len(checkouts) == 1
        assert checkouts[0]['with'] == {'ref': '${{ github.sha }}'}
    assert workflow['jobs']['deploy']['needs'] == 'build'


def test_no_workflow_stages_or_builds_the_retired_explorer_publication():
    for directory in ('workflows', 'scripts'):
        for path in sorted((ROOT / '.github' / directory).iterdir()):
            if path.suffix in {'.yml', '.yaml', '.py', '.sh'}:
                text = path.read_text()
                for retired in ('committee-explorer/public', 'committee_explorer', 'data/explorer', 'explorer-attempts.py'):
                    assert retired not in text, (path, retired)
    assert not (ROOT / '.github/workflows/publish-explorer.yml').exists()
    assert not (ROOT / '.github/scripts/explorer-attempts.py').exists()
    # Keep old reader libraries available for retained fixtures, but never mount
    # their second pointer in a public page again.
    for path in (ROOT / 'apps/site/src/pages').rglob('*.astro'):
        text = path.read_text()
        assert 'data/explorer' not in text, path
        assert 'components/explorer/Explorer' not in text, path
