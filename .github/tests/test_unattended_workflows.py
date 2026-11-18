"""Unattended jobs end in bounded time on a pinned image, and a rejected push fails the job."""
import os
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
COMMIT_AND_PUSH = ROOT / '.github/scripts/commit-and-push.sh'


def workflow(name):
    return yaml.load((ROOT / '.github/workflows' / name).read_text(), Loader=yaml.BaseLoader)


@pytest.mark.parametrize('path', sorted((ROOT / '.github/workflows').glob('*.yml')), ids=lambda path: path.name)
def test_every_job_has_a_time_limit_and_a_pinned_runner(path):
    for name, job in workflow(path.name)['jobs'].items():
        assert int(job['timeout-minutes']) > 0, name
        assert 'latest' not in job['runs-on'], name


def test_raw_source_mirror_holders_are_bounded_near_their_measured_runs():
    # Longest observed runs (Nov 2026): capture 23 minutes, update-data jobs 40.
    assert workflow('capture-archive.yml')['jobs']['capture']['timeout-minutes'] == '120'
    assert {job['timeout-minutes'] for job in workflow('update-data.yml')['jobs'].values()} == {'90'}


def test_cpi_update_pins_its_environment_and_pushes_through_the_shared_script():
    value = workflow('bls-cpi-update.yml')
    assert value['permissions'] == {'contents': 'write', 'statuses': 'write'}
    job = value['jobs']['update-cpi']
    assert job['timeout-minutes'] == '10'
    python = next(step for step in job['steps'] if step.get('uses', '').startswith('actions/setup-python@'))
    assert python['with'] == {'python-version-file': '.python-version'}
    commands = '\n'.join(step.get('run', '') for step in job['steps'])
    assert 'uv sync --locked --no-dev --package inflation-gsheets' in commands and 'pip install' not in commands
    assert '.github/scripts/commit-and-push.sh' in commands and 'git push' not in commands


def git(*args, cwd, env):
    return subprocess.run(['git', *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def checkout(tmp_path):
    """A main-branch clone of a bare remote, isolated from the user's git configuration."""
    env = {'PATH': os.defpath + os.pathsep + '/usr/bin:/bin', 'HOME': str(tmp_path),
           'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1',
           'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.invalid',
           'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@example.invalid'}
    remote, work = tmp_path / 'remote.git', tmp_path / 'work'
    git('init', '-q', '--bare', '--initial-branch=main', str(remote), cwd=tmp_path, env=env)
    git('clone', '-q', str(remote), str(work), cwd=tmp_path, env=env)
    git('symbolic-ref', 'HEAD', 'refs/heads/main', cwd=work, env=env)
    (work / 'data.csv').write_text('a\n')
    git('add', 'data.csv', cwd=work, env=env)
    git('commit', '-q', '-m', 'seed', cwd=work, env=env)
    git('push', '-q', 'origin', 'main', cwd=work, env=env)
    return work, remote, env


def commit_and_push(work, env, *files):
    return subprocess.run([str(COMMIT_AND_PUSH), 'update', *files], cwd=work, env=env,
                          capture_output=True, text=True, timeout=60)


def test_commit_and_push_rebases_over_a_concurrent_push(checkout, tmp_path):
    work, remote, env = checkout
    other = tmp_path / 'other'
    git('clone', '-q', str(remote), str(other), cwd=tmp_path, env=env)
    (other / 'other.csv').write_text('b\n')
    git('add', 'other.csv', cwd=other, env=env)
    git('commit', '-q', '-m', 'concurrent', cwd=other, env=env)
    git('push', '-q', 'origin', 'main', cwd=other, env=env)
    (work / 'data.csv').write_text('a\nc\n')
    result = commit_and_push(work, env, 'data.csv')
    assert result.returncode == 0, result.stderr
    assert git('log', '--format=%s', 'main', cwd=remote, env=env).split() == ['update', 'concurrent', 'seed']


def test_commit_and_push_fails_when_every_push_is_rejected(checkout):
    work, remote, env = checkout
    hook = remote / 'hooks/pre-receive'
    hook.write_text('#!/bin/sh\nexit 1\n')
    hook.chmod(0o755)
    (work / 'data.csv').write_text('a\nc\n')
    result = commit_and_push(work, env, 'data.csv')
    assert result.returncode != 0
    assert result.stdout.count('push rejected') == 3
    assert git('log', '--format=%s', 'main', cwd=remote, env=env).split() == ['seed']


def test_commit_and_push_without_changes_pushes_nothing(checkout):
    work, remote, env = checkout
    result = commit_and_push(work, env, 'data.csv')
    assert result.returncode == 0 and 'No changes' in result.stdout


@pytest.mark.parametrize('name', ['bls-cpi-update.yml', 'update-data.yml'])
def test_workflows_that_push_to_main_can_mark_their_commits(name):
    value = workflow(name)
    assert value['permissions'] == {'contents': 'write', 'statuses': 'write'}
    assert value['env']['GH_TOKEN'] == '${{ github.token }}'


def actions(checkout, tmp_path, *, fail_first_push=False):
    """The checkout as a GitHub Actions job sees it, with a gh that records each status it is asked to post."""
    work, remote, env = checkout
    tools = tmp_path / 'tools'
    tools.mkdir()
    calls = tmp_path / 'gh-calls'
    (tools / 'gh').write_text(f'#!/bin/sh\necho "$@" >> {calls}\n')
    (tools / 'gh').chmod(0o755)
    env = dict(env, PATH=f"{tools}{os.pathsep}{env['PATH']}", GITHUB_ACTIONS='true', GITHUB_REPOSITORY='o/r',
               GITHUB_RUN_ID='42', GITHUB_RUN_ATTEMPT='1', GITHUB_JOB='update-cpi', GITHUB_WORKFLOW='CPI',
               GITHUB_SERVER_URL='https://github.com')
    return work, remote, env, calls


def test_in_actions_a_data_commit_is_marked_on_a_side_branch_before_it_reaches_main(checkout, tmp_path):
    work, remote, env, calls = actions(checkout, tmp_path)
    # main accepts only a commit the side branch already holds: marked first, moved second.
    hook = remote / 'hooks/pre-receive'
    hook.write_text('#!/bin/sh\nwhile read old new ref; do\n  if [ "$ref" = refs/heads/main ]; then\n'
                    '    [ "$(git rev-parse refs/heads/data-commit/42-1-update-cpi 2>/dev/null)" = "$new" ] || exit 1\n  fi\ndone\n')
    hook.chmod(0o755)
    (work / 'data.csv').write_text('a\nc\n')
    result = commit_and_push(work, env, 'data.csv')
    assert result.returncode == 0, result.stdout + result.stderr
    head = git('rev-parse', 'main', cwd=remote, env=env).strip()
    assert git('log', '--format=%s', 'main', cwd=remote, env=env).split() == ['update', 'seed']
    [call] = calls.read_text().splitlines()
    assert f'repos/o/r/statuses/{head}' in call and 'state=success' in call and 'context=merge-gate' in call
    # The side branch is gone once the commit is on main.
    assert git('branch', '--list', 'data-commit/*', cwd=remote, env=env).strip() == ''


def test_a_rebased_data_commit_is_marked_again_under_its_new_identity(checkout, tmp_path):
    work, remote, env, calls = actions(checkout, tmp_path)
    other = tmp_path / 'other'
    git('clone', '-q', str(remote), str(other), cwd=tmp_path, env=env)
    (other / 'other.csv').write_text('b\n')
    git('add', 'other.csv', cwd=other, env=env)
    git('commit', '-q', '-m', 'concurrent', cwd=other, env=env)
    git('push', '-q', 'origin', 'main', cwd=other, env=env)
    (work / 'data.csv').write_text('a\nc\n')
    result = commit_and_push(work, env, 'data.csv')
    assert result.returncode == 0, result.stdout + result.stderr
    head = git('rev-parse', 'main', cwd=remote, env=env).strip()
    marked = [line.split('statuses/')[1].split()[0] for line in calls.read_text().splitlines()]
    assert len(marked) == 2 and marked[0] != head and marked[1] == head
    assert git('branch', '--list', 'data-commit/*', cwd=remote, env=env).strip() == ''


def test_outside_actions_nothing_is_marked_and_no_side_branch_is_made(checkout, tmp_path):
    work, remote, env, calls = actions(checkout, tmp_path)
    env = {key: value for key, value in env.items() if key != 'GITHUB_ACTIONS'}
    (work / 'data.csv').write_text('a\nc\n')
    assert commit_and_push(work, env, 'data.csv').returncode == 0
    assert not calls.exists() and git('branch', '--list', 'data-commit/*', cwd=remote, env=env).strip() == ''
