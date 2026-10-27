"""B6: receipt identity comes only from a clean repository and its locked dependencies."""
import hashlib
from pathlib import Path
import subprocess

import pytest

from congress_api.retention.writer_identity import writer_identity
from congress_api.cli import pipeline_raw as cli


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), '-c', 'user.name=Test',
                                   '-c', 'user.email=test@example.invalid', *args], text=True).strip()


def repository(root):
    root.mkdir()
    git(root, 'init', '-q')
    (root / '.gitignore').write_text('output/\n')
    (root / 'uv.lock').write_bytes(b'locked dependencies\n')
    (root / 'application.py').write_text('initial = True\n')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'fixture')
    return root


def test_identity_is_exact_clean_head_and_lock_bytes(tmp_path):
    root = repository(tmp_path / 'repo')
    assert writer_identity(root, 'capture') == dict(job='capture', commit=git(root, 'rev-parse', 'HEAD'),
        lockfile_digest=hashlib.sha256((root / 'uv.lock').read_bytes()).hexdigest())
    before = writer_identity(root, 'capture')
    (root / 'uv.lock').write_bytes(b'new locked dependencies\n')
    git(root, 'add', 'uv.lock')
    git(root, 'commit', '-qm', 'new lock')
    after = writer_identity(root, 'capture')
    assert before['commit'] != after['commit']
    assert before['lockfile_digest'] != after['lockfile_digest']


@pytest.mark.parametrize('change', ['modified', 'staged', 'untracked'])
def test_dirty_code_refused(tmp_path, change):
    root = repository(tmp_path / 'repo')
    path = root / ('new.py' if change == 'untracked' else 'application.py')
    path.write_text('changed = True\n')
    if change == 'staged':
        git(root, 'add', path.name)
    with pytest.raises(ValueError, match='clean'):
        writer_identity(root, 'capture')


def test_ignored_output_does_not_change_identity(tmp_path):
    root = repository(tmp_path / 'repo')
    before = writer_identity(root, 'capture')
    (root / 'output').mkdir()
    (root / 'output/result.json').write_text('{}')
    assert writer_identity(root, 'capture') == before


def test_missing_lock_refused(tmp_path):
    root = repository(tmp_path / 'repo')
    (root / 'uv.lock').unlink()
    git(root, 'add', 'uv.lock')
    git(root, 'commit', '-qm', 'remove lock')
    with pytest.raises(FileNotFoundError):
        writer_identity(root, 'capture')


def test_unborn_repository_refused(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    git(root, 'init', '-q')
    with pytest.raises(subprocess.CalledProcessError):
        writer_identity(root, 'capture')


def test_pipeline_dirty_code_refused_before_connection(tmp_path, monkeypatch):
    root = repository(tmp_path / 'repo')
    snapshot = repository(tmp_path / 'snapshot')
    (root / 'application.py').write_text('dirty = True\n')
    calls = []
    monkeypatch.setattr(cli, 'ROOT', root)
    monkeypatch.setattr('congress_shared.storage.connect_r2', lambda **kwargs: calls.append(kwargs))
    with pytest.raises(ValueError, match='clean'):
        cli.main(['--snapshot', str(snapshot)])
    assert calls == []
