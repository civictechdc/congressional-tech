"""Run the declared owner CLI once. Pending job specs refuse before any import."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['publish', 'backfill', 'maintenance'])
    parser.add_argument('--check-binding', action='store_true', help='Refuse pending specs before runtime or storage setup')
    args = parser.parse_args()
    binding = json.loads((ROOT / '.github/archive-jobs.json').read_text())[args.operation]
    spec = ROOT / binding['spec']
    value = json.loads(spec.read_text())
    if value.get('status') == 'blocked':
        print('Archive job refused: ' + value['reason'], file=sys.stderr)
        return 2
    if not binding['module']:
        print('Archive job refused: owner CLI is not bound', file=sys.stderr)
        return 2
    if args.check_binding:
        return 0
    return subprocess.run([sys.executable, '-I', '-m', binding['module'], '--spec', str(spec)], cwd=ROOT).returncode


if __name__ == '__main__':
    raise SystemExit(main())
