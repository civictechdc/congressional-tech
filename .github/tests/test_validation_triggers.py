"""The Explorer and MCP workflows cover code pushes and their respective documentation inputs."""
from pathlib import Path
import re

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
VALIDATIONS = ['validate-explorer.yml', 'validate-congress-mcp.yml']
CODE = ['model/sql/meetings.sql', 'model/jobs/publish.json', 'packages/congress_api/src/a.py',
        'packages/not_yet_written/src/a.py', '.github/workflows/archive-jobs.yml', '.github/archive-jobs.json',
        'scripts/dev.py', 'scripts/new_tool/a.py', 'tests/test_a.py', 'pyproject.toml', 'uv.lock']
DOCUMENTATION = [['.tickets/ct-abcd.md'], ['docs/plans/a.md'], ['docs/data/a.json'], ['README.md'],
         ['packages/congress_api/README.md'], ['.tickets/ct-abcd.md', 'docs/reviews/a.json', 'apps/site/README.md']]


def workflow(name):
    return yaml.load((ROOT / '.github/workflows' / name).read_text(), Loader=yaml.BaseLoader)


def matches(pattern, path):
    """GitHub's filter cheat sheet: `*` stops at `/`, `**` does not, `**/` may match no directory."""
    regex = ''
    for token in re.findall(r'\*\*/|\*\*|\*|[^*]+', pattern):
        assert not set(token) & set('?+[]'), f'{pattern}: extend the matcher before using {token}'
        regex += {'**/': '(?:.*/)?', '**': '.*', '*': '[^/]*'}.get(token, re.escape(token))
    return re.fullmatch(regex, path) is not None


def triggers(patterns, changed):
    """Patterns apply in order; a later negation excludes and a later positive re-includes."""
    def included(path):
        keep = False
        for pattern in patterns:
            if matches(pattern.removeprefix('!'), path):
                keep = not pattern.startswith('!')
        return keep
    return any(included(path) for path in changed)


def test_matcher_agrees_with_githubs_documented_examples():
    assert matches('**/README.md', 'README.md') and matches('**/README.md', 'js/README.md')
    assert matches('docs/**/*.md', 'docs/README.md') and matches('docs/**/*.md', 'docs/a/markdown/file.md')
    assert matches('*', 'README.md') and not matches('*', 'docs/README.md')
    assert matches('**', 'all/the/files.md')
    assert triggers(['*.md', '!README.md', 'README*'], ['README.md'])
    assert not triggers(['*.md', '!README.md'], ['README.md'])


@pytest.mark.parametrize('name', VALIDATIONS)
def test_push_to_main_validates_code_and_the_workflows_documentation_inputs(name):
    value = workflow(name)
    push = value['on']['push']
    assert push['branches'] == ['main']
    for path in CODE:
        assert triggers(push['paths'], [path]), path
    for changed in DOCUMENTATION:
        expected = name == 'validate-explorer.yml' and any(not matches('.tickets/*.md', p) for p in changed)
        assert triggers(push['paths'], changed) == expected, changed
    # Every non-Markdown input that validates a PR also validates a push.
    for pattern in value['on']['pull_request']['paths']:
        sample = pattern.replace('**', 'a/b.py')
        if not sample.endswith('.md'):
            assert triggers(push['paths'], [sample]), pattern


def test_each_validation_also_reads_the_inputs_it_checks_under_docs_or_markdown():
    explorer = workflow('validate-explorer.yml')['on']
    assert triggers(explorer['push']['paths'], ['docs/experiments/filename-patterns-20261015/test_rule_review.py'])
    # 38 viewer_publication test files read model/sql or model/jobs.
    assert 'model/**' in explorer['pull_request']['paths']
    mcp = workflow('validate-congress-mcp.yml')['on']['push']['paths']
    assert triggers(mcp, ['apps/explorer_mcp/README.md'])  # twine check --strict reads it
    assert triggers(mcp, ['apps/explorer_mcp/skills/explore-congress/SKILL.md'])  # plugin validate --strict


@pytest.mark.parametrize('name', VALIDATIONS)
def test_newer_run_supersedes_the_older_one_for_the_same_event_and_ref(name):
    assert workflow(name)['concurrency'] == {
        'group': '${{ github.workflow }}-${{ github.event_name }}-${{ github.ref }}',
        'cancel-in-progress': 'true',
    }


@pytest.mark.parametrize('name', VALIDATIONS)
def test_pull_request_conditions_hold_for_pushes(name):
    jobs = workflow(name)['jobs'].values()
    conditions = [item['if'] for job in jobs for item in [job, *job['steps']] if 'if' in item]
    for condition in conditions:
        if 'github.event.pull_request' in condition:
            assert condition.startswith("github.event_name != 'pull_request' || "), condition
