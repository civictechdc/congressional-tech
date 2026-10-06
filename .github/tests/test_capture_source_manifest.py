import importlib.util
from pathlib import Path
import subprocess

SCRIPT = Path(__file__).parents[1] / 'scripts/capture-source-manifest.py'
spec = importlib.util.spec_from_file_location('capture_source_manifest', SCRIPT)
source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source)


def test_package_rule_data_affects_parity_but_bytecode_does_not(tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    for package in ('congress_api', 'congress_shared', 'committee_meeting', 'house-naming'):
        path = tmp_path / 'packages' / package
        (path / 'src').mkdir(parents=True)
        (path / 'pyproject.toml').write_text('')
    for filename in ('main.rs', 'Cargo.toml', 'Cargo.lock'):
        path = tmp_path / 'packages/source-fetch' / filename
        path.parent.mkdir(exist_ok=True)
        path.write_text('')
    subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.org',
                    'commit', '--allow-empty', '-qm', 'fixture'], cwd=tmp_path, check=True)
    guide = tmp_path / 'packages/house-naming/src/house_naming/data/guide.json'
    guide.parent.mkdir(parents=True)
    guide.write_text('{}')
    before = source.manifest(tmp_path)
    guide.write_text('{"changed":true}')
    after = source.manifest(tmp_path)
    assert before['source_digest'] != after['source_digest']
    assert str(guide.relative_to(tmp_path)) in after['source_sha256']
    cache = guide.parent / '__pycache__/module.pyc'
    cache.parent.mkdir()
    cache.write_bytes(b'generated')
    metadata = tmp_path / 'packages/house-naming/src/house_naming.egg-info/PKG-INFO'
    metadata.parent.mkdir()
    metadata.write_text('generated installation metadata')
    assert source.manifest(tmp_path) == after
