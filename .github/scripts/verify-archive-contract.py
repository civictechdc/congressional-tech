"""Run the built-site contract against two committed native hand releases."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def indexed_fixture(source, target):
    """Attach an actual SQLite FTS5 asset to the shared browser fixture."""
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(source, target)
    asset = target / 'search_index.sqlite'
    with sqlite3.connect(asset) as db:
        db.execute('CREATE VIRTUAL TABLE passages USING fts5(text)')
        db.execute('INSERT INTO passages(text) VALUES (?)', ['A retained hearing passage.'])
    data = asset.read_bytes()
    manifest = json.loads((target / 'manifest.json').read_text())
    manifest['files'].append(dict(name=asset.name, sha256=sha256(data).hexdigest(), size=len(data), rows=1))
    identity = [manifest['schema_version'], [[item[key] for key in ('name', 'sha256', 'size', 'rows')] for item in manifest['files']]]
    manifest['release_id'] = sha256(json.dumps(identity, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    (target / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--browser-executable', type=Path)
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    fixture = ROOT / 'model/fixtures/archive-contract'
    current = indexed_fixture(fixture / 'current', (args.work / 'indexed-release').resolve())
    browser = ['--browser-executable', str(args.browser_executable)] if args.browser_executable else []
    subprocess.run(['npm', 'run', 'contract:archive', '--workspaces=false', '--',
        '--release', str(current), '--next-release', str(fixture / 'next'),
        '--hand', 'true', '--output', str((args.work / 'contract.json').resolve()), *browser], cwd=ROOT / 'apps/site', check=True)

    for script in ('test:archive-saved-browser', 'test:archive-heap-browser'):
        subprocess.run(['npm', 'run', script, '--workspaces=false', '--',
            '--release', str(fixture / 'current'), *browser], cwd=ROOT / 'apps/site', check=True)

    # The committed releases carry no witnesses; a copy gains witness_key_map cases (ct-kb4w).
    from viewer_publication.archive_fixture import add_witness_key_map
    witness_release = (args.work / 'witness-release').resolve()
    shutil.rmtree(witness_release, ignore_errors=True)
    shutil.copytree(fixture / 'current', witness_release)
    add_witness_key_map(witness_release)
    subprocess.run(['npm', 'run', 'test:archive-witness-browser', '--workspaces=false', '--',
        '--release', str(witness_release), *browser], cwd=ROOT / 'apps/site', check=True)


if __name__ == '__main__':
    main()
