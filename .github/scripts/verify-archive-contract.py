"""Run the built-site contract against two committed native hand releases."""
import argparse
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--browser-executable', type=Path)
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    fixture = ROOT / 'model/fixtures/archive-contract'
    browser = ['--browser-executable', str(args.browser_executable)] if args.browser_executable else []
    subprocess.run(['npm', 'run', 'contract:archive', '--workspaces=false', '--',
        '--release', str(fixture / 'current'), '--next-release', str(fixture / 'next'),
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
