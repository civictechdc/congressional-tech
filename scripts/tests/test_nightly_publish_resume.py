"""A candidate survives a commit that only records its reviewed release cause, and nothing else."""
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location('nightly_publish_contract', ROOT / 'scripts/nightly_publish.py')
nightly = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(nightly)


def commit(repo, files):
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    subprocess.run(['git', 'add', '-A'], cwd=repo, check=True)
    subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', 'commit', '-qm', 'x'],
                   cwd=repo, check=True)
    return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    base = commit(tmp_path, {'model/jobs/publish.json': json.dumps(dict(version=1, bucket='b')),
                             'model/sql/a.sql': 'SELECT 1'})
    return tmp_path, base


CAUSE = {'model/jobs/release-causes/a-b.json': '{}', '.tickets/ct-x.md': 'note', 'docs/releases/r.md': 'r',
         'model/jobs/publish.json': json.dumps(dict(version=1, bucket='b', release_causes=dict(path='release-causes/a-b.json')))}


def test_a_cause_record_commit_keeps_the_candidate(repo):
    path, base = repo
    assert nightly.only_cause_records(path, base, commit(path, CAUSE))


@pytest.mark.parametrize('extra', [
    {'model/sql/a.sql': 'SELECT 2'},
    {'scripts/nightly_publish.py': 'pass'},
    {'model/jobs/publish.json': json.dumps(dict(version=1, bucket='other', release_causes=dict(path='x')))},
    {'model/jobs/publish-model.json': '{}'},
])
def test_any_other_change_discards_it(repo, extra):
    path, base = repo
    assert not nightly.only_cause_records(path, base, commit(path, dict(CAUSE, **extra)))


def test_an_unknown_or_malformed_commit_discards_it(repo):
    path, base = repo
    head = commit(path, CAUSE)
    assert not nightly.only_cause_records(path, '0' * 40, head)
    assert not nightly.only_cause_records(path, 'HEAD~1', head)
    assert not nightly.only_cause_records(path, head, head)
