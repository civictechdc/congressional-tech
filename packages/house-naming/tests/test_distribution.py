"""Exercise the development archive and bundled wheel runtime."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile

import pytest


@pytest.fixture
def source_tree(tmp_path):
    source = Path(__file__).resolve().parents[1]
    checkout = tmp_path / 'checkout'
    shutil.copytree(source, checkout, ignore=shutil.ignore_patterns(
        '.venv', 'build', 'dist', '*.egg-info', '__pycache__', '.pytest_cache'))
    return checkout


def test_source_archive_contains_a_working_development_tree(tmp_path, source_tree):
    checkout = source_tree
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
    for path in ['tests/records.json', 'tests/fixtures/verified_local_conventions.json',
                 'examples/witness.json', 'tools/build.py',
                 'tools/check_ecmascript.mjs', 'FILENAME_PATTERNS.md',
                 'tests/compare_filename_extraction.py', 'tests/audit_filename_extraction.py',
                 'tests/audit_filename_token_boundaries.py', 'tools/compare_filename_families.py',
                 'notes/house-naming-extraction.md', 'notes/filename-engine-comparison.md']:
        assert (root / path).is_file(), path
    env = dict(os.environ, PYTHONPATH=str(root / 'src'), PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
    pytest_probe = r'''
import importlib.abc
from pathlib import Path
import sys

class RejectApplicationImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'congress_api' or fullname.startswith('congress_api.'):
            raise AssertionError('Standalone naming development imported application code: ' + fullname)
sys.meta_path.insert(0, RejectApplicationImports())
import house_naming
assert Path(house_naming.__file__).resolve().is_relative_to(Path.cwd() / 'src')
import pytest
raise SystemExit(pytest.main(sys.argv[1:]))
'''
    for args in [
        ['tools/build.py', '--check'],
        ['-c', pytest_probe, '--collect-only', '-q', 'tests'],
        ['-c', pytest_probe, '-q', 'tests/test_research_note_paths.py',
         'tests/test_filename_extraction_comparison.py', 'tests/test_filename_native_audit.py',
         'tests/test_filename_token_boundaries.py'],
        ['-m', 'house_naming', 'render', 'examples/witness.json', '--plain'],
    ]:
        run = subprocess.run([sys.executable, *args], cwd=root, env=env,
                             capture_output=True, text=True, timeout=30)
        assert run.returncode == 0, run.stdout + run.stderr


def test_wheel_contains_a_self_contained_core_runtime(tmp_path, source_tree):
    dist = tmp_path / 'dist'
    build = subprocess.run([sys.executable, '-c',
        'from setuptools.build_meta import build_wheel; import sys; build_wheel(sys.argv[1])', str(dist)],
        cwd=source_tree, capture_output=True, text=True, timeout=30)
    assert build.returncode == 0, build.stdout + build.stderr
    wheel, = dist.glob('*.whl')
    unpacked = tmp_path / 'wheel-runtime'
    with zipfile.ZipFile(wheel) as archive:
        for path in (source_tree / 'src' / 'house_naming').rglob('*'):
            if path.suffix in {'.py', '.json'} or path.name == 'py.typed':
                assert archive.read(path.relative_to(source_tree / 'src').as_posix()) == path.read_bytes()
        for name in ['LICENSE', 'NOTICE']:
            member, = [p for p in archive.namelist() if p.endswith('/licenses/' + name)]
            assert archive.read(member) == (source_tree / name).read_bytes()
        archive.extractall(unpacked)  # Wheel was just built from our own source copy.
    probe = r'''
import importlib.abc
import importlib.metadata
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
assert not {'congress_api', 'pydantic', 'pyarrow'}.intersection(sys.modules)
class RejectOptionalDependencies(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'congress_api', 'pydantic', 'pyarrow'}:
            raise AssertionError('Core runtime imported optional dependency: ' + fullname)
sys.meta_path.insert(0, RejectOptionalDependencies())

import house_naming
assert Path(house_naming.__file__).resolve().is_relative_to(root)
distribution = importlib.metadata.distribution('house-naming-guide')
assert Path(distribution.locate_file('')).resolve() == root
assert distribution.version == house_naming.__version__ == house_naming.load_guide()['catalog_version']
scripts = {entry.name: entry for entry in distribution.entry_points if entry.group == 'console_scripts'}
assert scripts['house-naming'].load()(['check']) == 0
assert scripts['house-naming-corpus'].value == 'house_naming.filename_corpus:main'
engine = house_naming.Engine()
for name, host, kind in [
    ('PLAW-115publ401.pdf', 'www.govinfo.gov', 'public-law'),
    ('h2001_rh_xml.pdf', 'docs.house.gov', 'legislative-text'),
    ('H5109_SUS_xml.pdf', 'docs.house.gov', 'legislative-text'),
    ('112-12.pdf', 'financialservices.house.gov', 'published-hearing'),
]:
    result = engine.extract(name, source_url=f'https://{host}/{name}')
    assert result['metadata']['document_kind'] == [kind]
    assert ''.join(piece['raw'] for piece in result['pieces']) == name
assert 'public-law' not in engine.extract('PLAW-115publ401.pdf', source_url='https://example.org/PLAW-115publ401.pdf')['metadata'].get('document_kind', [])
assert house_naming.document_families(['public-law']) == ['legislation']
'''
    run = subprocess.run([sys.executable, '-I', '-c', probe, str(unpacked)],
                         cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr
