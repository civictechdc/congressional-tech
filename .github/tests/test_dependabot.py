"""Action updates arrive as one weekly Dependabot PR, and no setup step leans on a default a major can flip."""
from fnmatch import fnmatch
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_one_grouped_weekly_update_covers_workflows_and_composite_actions():
    config = yaml.load((ROOT / '.github/dependabot.yml').read_text(), Loader=yaml.BaseLoader)
    [update] = config['updates']
    assert update['package-ecosystem'] == 'github-actions' and update['schedule'] == {'interval': 'weekly'}
    assert update['groups'] == {'github-actions': {'patterns': ['*']}}
    assert '/' in update['directories']  # .github/workflows
    composite = ['/' + str(path.parent.relative_to(ROOT)) for path in (ROOT / '.github/actions').glob('*/action.yml')]
    assert composite and all(any(fnmatch(name, pattern) for pattern in update['directories']) for name in composite)


def steps(path):
    document = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    if 'runs' in document:
        return document['runs']['steps']
    return [step for job in document['jobs'].values() for step in job.get('steps', [])]


def test_every_setup_node_states_its_cache_choice():
    """setup-node v5+ caches npm by default when package.json names npm, and the root has no lock file."""
    paths = [*(ROOT / '.github/workflows').glob('*.yml'), *(ROOT / '.github/actions').glob('*/action.yml')]
    nodes = [step for path in paths for step in steps(path) if step.get('uses', '').startswith('actions/setup-node@')]
    assert nodes
    for step in nodes:
        assert 'cache' in step['with'] or step['with'].get('package-manager-cache') == 'false', step
