"""Dependabot raises one weekly PR for every action the workflows and composite actions use."""
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
