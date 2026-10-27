"""Run the built-site contract against two committed native hand releases."""
import argparse
from pathlib import Path
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


if __name__ == '__main__':
    main()
