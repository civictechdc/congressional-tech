"""Exercise the documented development workflow from an actual source archive."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile


def test_source_archive_contains_a_working_development_tree(tmp_path):
    source = Path(__file__).resolve().parents[1]
    checkout = tmp_path / 'checkout'
    shutil.copytree(source, checkout, ignore=shutil.ignore_patterns(
        '.venv', 'build', 'dist', '*.egg-info', '__pycache__', '.pytest_cache'))
    dist = tmp_path / 'dist'
    build = subprocess.run([sys.executable, '-c',
        'from setuptools.build_meta import build_sdist; import sys; build_sdist(sys.argv[1])', str(dist)],
        cwd=checkout, capture_output=True, text=True, timeout=30)
    assert build.returncode == 0, build.stdout + build.stderr
    unpacked = tmp_path / 'unpacked'
    with tarfile.open(next(dist.glob('*.tar.gz'))) as archive:
        # This archive was just built from the test's own local source copy.
        archive.extractall(unpacked, **({'filter': 'data'} if hasattr(tarfile, 'data_filter') else {}))
    root, = unpacked.iterdir()
    for path in ['tests/records.json', 'examples/witness.json', 'tools/build.py',
                 'tools/check_ecmascript.mjs', 'FILENAME_PATTERNS.md']:
        assert (root / path).is_file(), path
    env = dict(os.environ, PYTHONPATH=str(root / 'src'))
    for args in [
        ['tools/build.py', '--check'],
        ['-m', 'pytest', '--collect-only', '-q', 'tests/test_runtime.py'],
        ['-m', 'house_naming', 'render', 'examples/witness.json', '--plain'],
    ]:
        run = subprocess.run([sys.executable, *args], cwd=root, env=env,
                             capture_output=True, text=True, timeout=30)
        assert run.returncode == 0, run.stdout + run.stderr
