"""Run the declared owner CLI once. Pending job specs refuse before any import."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def binding_command(binding, spec):
    if binding.get('argv') != ['--execute']:
        raise ValueError('active job needs explicit --execute arguments')
    return [sys.executable, '-I', '-m', binding['module'], '--spec', str(spec), *binding['argv']]


def export_publisher_work(command, output):
    result = subprocess.run([*command[:-1], '--plan'], cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        print(result.stderr or 'Archive job refused: owner publish plan refused', file=sys.stderr)
        return result.returncode
    try:
        plan = json.loads(result.stdout)
        work = plan.get('work') if isinstance(plan, dict) else None
        if (not isinstance(plan, dict) or plan.get('status') != 'planned' or plan.get('executed') is not False
                or not isinstance(work, str) or not work or not Path(work).is_absolute()
                or any(char in work for char in '\r\n\0')):
            raise ValueError('Owner publish plan did not supply safe work metadata')
        with output.open('a') as destination:
            destination.write('publisher_work=' + work + '\n')
    except (ValueError, OSError) as error:
        print('Archive job refused: ' + str(error), file=sys.stderr)
        return 2
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['publish', 'backfill', 'maintenance'])
    parser.add_argument('--check-binding', action='store_true', help='Refuse pending specs before runtime or storage setup')
    parser.add_argument('--github-output', type=Path, help='Export owner-planned publisher work during binding admission')
    args = parser.parse_args()
    if args.github_output is not None and (not args.check_binding or args.operation != 'publish'):
        parser.error('--github-output requires publish --check-binding')
    binding = json.loads((ROOT / '.github/archive-jobs.json').read_text())[args.operation]
    spec = ROOT / binding['spec']
    value = json.loads(spec.read_text())
    if value.get('status') == 'blocked':
        print('Archive job refused: ' + value['reason'], file=sys.stderr)
        return 2
    if not binding['module']:
        print('Archive job refused: owner CLI is not bound', file=sys.stderr)
        return 2
    try:
        command = binding_command(binding, spec)
    except ValueError as error:
        print('Archive job refused: ' + str(error), file=sys.stderr)
        return 2
    if args.check_binding:
        return export_publisher_work(command, args.github_output) if args.github_output is not None else 0
    return subprocess.run(command, cwd=ROOT).returncode


if __name__ == '__main__':
    raise SystemExit(main())
