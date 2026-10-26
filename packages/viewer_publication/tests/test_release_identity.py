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


def test_source_identity_includes_its_maintained_implementation(tmp_path):
    path = tmp_path / IMPLEMENTATION
    path.parent.mkdir(parents=True)
    path.write_text('VALUE = 1\n')
    before = source_files(tmp_path)
    assert before[IMPLEMENTATION] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert source_files(tmp_path) == before
    path.write_text('VALUE = 2\n')
    after = source_files(tmp_path)
    assert after[IMPLEMENTATION] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert after != before
