"""Release identity imports share one implementation and bind its source."""
import hashlib
from pathlib import Path
import subprocess
import sys

import pytest

from viewer_publication.release_identity import source_files

ROOT = Path(__file__).resolve().parents[3]
IMPLEMENTATION = 'packages/viewer_publication/src/viewer_publication/release_identity.py'


@pytest.mark.parametrize('order', ['package-first', 'shim-first'])
def test_release_identity_import_orders_share_the_maintained_functions(order):
    code = r"""
from importlib import import_module
from pathlib import Path
import sys
root, order = Path(sys.argv[1]), sys.argv[2]
sys.path[:0] = [str(root / 'packages/viewer_publication/src'), str(root / 'scripts')]
names = ['viewer_publication.release_identity', 'viewer_release_identity']
if order == 'shim-first':
    names.reverse()
for name in names:
    import_module(name)
current = sys.modules['viewer_publication.release_identity']
shim = sys.modules['viewer_release_identity']
assert Path(current.__file__).resolve() == root / 'packages/viewer_publication/src/viewer_publication/release_identity.py'
assert Path(shim.__file__).resolve() == root / 'scripts/viewer_release_identity.py'
for name in ('source_files', 'encoded', 'installed_runtime', 'locked_runtime'):
    assert getattr(shim, name) is getattr(current, name), name
assert shim.source_files(root) == current.source_files(root)
"""
    result = subprocess.run([sys.executable, '-I', '-S', '-c', code, str(ROOT), order],
                            cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('relative', [
    IMPLEMENTATION,
    'packages/viewer_publication/src/viewer_publication/publish_viewer_r2.py',
    'packages/viewer_publication/src/viewer_publication/publish_filename_viewer.py',
    'packages/viewer_publication/src/viewer_publication/constants.py',
    'packages/docspec_client/src/docspec_client/client.py',
    'packages/docspec_client/src/docspec_client/host.py',
])
def test_source_identity_includes_its_maintained_implementation(tmp_path, relative):
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text('VALUE = 1\n')
    before = source_files(tmp_path)
    assert before[relative] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert source_files(tmp_path) == before
    path.write_text('VALUE = 2\n')
    after = source_files(tmp_path)
    assert after[relative] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert after != before


@pytest.mark.parametrize('relative', [
    'packages/congress_api/src/congress_api/retention/helper.py',
    'packages/viewer_publication/src/viewer_publication/plan.py',
    'packages/viewer_publication/src/viewer_publication/reconciliation.py',
    'packages/viewer_publication/src/viewer_publication/local.py',
    '.python-version',
])
def test_source_identity_rereads_changed_bytes_with_identical_metadata(tmp_path, monkeypatch, relative):
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('VALUE = 1\n')
    custody = path.stat()
    original_stat = Path.stat
    def same_tick(candidate, *args, **kwargs):
        return custody if candidate == path else original_stat(candidate, *args, **kwargs)
    monkeypatch.setattr(Path, 'stat', same_tick)
    before = source_files(tmp_path)
    path.write_text('VALUE = 2\n')
    assert path.stat() == custody
    after = source_files(tmp_path)
    assert after[relative] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert after != before


def test_source_identity_refuses_changes_during_hashing(tmp_path, monkeypatch):
    from viewer_publication import release_identity as identity
    path = tmp_path / 'packages/congress_api/src/congress_api/retention/helper.py'
    path.parent.mkdir(parents=True)
    path.write_text('VALUE = 1\n')
    original_digest = hashlib.file_digest
    def change_after_read(stream, *args, **kwargs):
        result = original_digest(stream, *args, **kwargs)
        path.write_text('VALUE = 1\n# changed while hashing\n')
        return result
    monkeypatch.setattr(identity.hashlib, 'file_digest', change_after_read)
    with pytest.raises(ValueError, match='Release source changed during hashing'):
        source_files(tmp_path)
