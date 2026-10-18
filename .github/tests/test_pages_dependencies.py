"""Pages must use frozen inputs before executing the maintained reader checks."""
from pathlib import Path
import json

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_pages_uses_declared_locked_environments_and_checks_built_reader():
    workflow = yaml.load((ROOT / '.github/workflows/deploy-pages.yml').read_text(), Loader=yaml.BaseLoader)
    from fnmatch import fnmatch
    triggers = workflow['on']['push']['paths']
    assert any(fnmatch('docs/youtube-coverage/research/filename-rules.mjs', path) for path in triggers)
    steps = workflow['jobs']['build']['steps']
    assert any(step.get('uses') == './.github/actions/setup-python-project' for step in steps)
    node = next(step for step in steps if step.get('uses', '').startswith('actions/setup-node@'))
    assert node['with']['node-version-file'] == '.node-version'
    assert node['with']['cache-dependency-path'] == 'apps/site/package-lock.json'
    commands = [step.get('run', '') for step in steps]
    assert 'npm ci --workspaces=false --engine-strict --no-audit --no-fund' in commands
    package = json.loads((ROOT / 'apps/site/package.json').read_text())
    assert f"npm install --global {package['packageManager']} --ignore-scripts --no-audit --no-fund" in commands
    assert commands.index('npm run test:explorer') < commands.index('npm run build')
    assert commands.index('npm run build') < commands.index('npm run test:built-filenames')
    assert any('verify(source)' in command and 'migrate(source, target)' in command for command in commands)
    assert 'stage-document-reviews.py' in package['scripts']['build']
    lock = json.loads((ROOT / 'apps/site/package-lock.json').read_text())
    assert lock['packages']['']['dependencies'] == package['dependencies']
    assert lock['packages']['']['devDependencies'] == package['devDependencies']
