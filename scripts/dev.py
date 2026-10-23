#!/usr/bin/env python3
"""Shared local/CI prerequisites, test selection and coverage inventory."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def declaration():
    return tomllib.loads((ROOT / 'test-suites.toml').read_text())


def run(command, *, timeout=15):
    return subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True, timeout=timeout)


def baseline(config, *, fetch=False):
    """Setup may fetch the exact object; test preflight only verifies local data."""
    spec = config['baseline']
    freeze = json.loads((ROOT / spec['freeze']).read_text())
    commit = spec['commit']
    if not commit.startswith(freeze['baseline_commit']):
        raise ValueError('Declared baseline commit does not match the freeze')
    try:
        run(['git', 'cat-file', '-e', commit + '^{commit}'])
    except subprocess.CalledProcessError:
        if not fetch:
            raise ValueError('Historical baseline unavailable; run python scripts/dev.py prepare-baseline before tests') from None
        run(['git', 'fetch', '--no-tags', '--depth=1', 'origin', commit], timeout=120)
    source = subprocess.run(['git', 'show', commit + ':' + spec['parser']], cwd=ROOT,
                            check=True, capture_output=True, timeout=15).stdout
    expected = freeze['development_summary']['baseline_parser_sha256']
    actual = sha256(source).hexdigest()
    if actual != expected:
        raise ValueError(f'Baseline parser hash differs: expected {expected}, got {actual}')
    # The existing worker test reads the freeze's abbreviated identity.
    if run(['git', 'rev-parse', freeze['baseline_commit'] + '^{commit}']).stdout.strip() != commit:
        raise ValueError('Frozen baseline abbreviation resolves to a different commit')
    return f'{commit} parser sha256={actual}'


def inventory(config):
    """Include untracked, nonignored tests so new files cannot evade enrollment."""
    names = run(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z']).stdout.split('\0')
    tests = {name for name in names if Path(name).name.startswith('test_') and name.endswith('.py')}
    assigned = set()
    errors = []
    for name, lane in config['lanes'].items():
        covered = set()
        for root in lane['roots']:
            if not (ROOT / root).exists():
                errors.append(f'{name}: missing suite root {root}')
            covered |= {path for path in tests if path == root or path.startswith(root.rstrip('/') + '/')}
        assigned |= covered
        print(f'{name}: {len(covered)} files; {lane["purpose"]}')
        if not lane['roots'] and not all(lane.get(key) for key in ('owner', 'rationale')):
            errors.append(f'{name}: an empty/retained lane needs an owner and rationale')
    errors += [f'Unassigned test: {path}' for path in sorted(tests - assigned)]
    if errors:
        raise ValueError('\n'.join(errors))
    print(f'Inventory complete: {len(tests)} test files assigned (marker lanes may share files).')


def doctor(config, lane_name=None):
    errors = []
    version_file = config['environment']['python_version_file']
    expected_python = (ROOT / version_file).read_text().strip()
    if sys.version_info[:3] != tuple(map(int, expected_python.split('.'))):
        errors.append(f'Python {expected_python} required by {version_file}; '
                      f'got {sys.version.split()[0]}; run uv sync --locked')
    print(f'Python {sys.version.split()[0]}: {sys.executable}')
    # Import in a bounded subprocess: a broken native module cannot hang doctor.
    for name, source in config['environment']['imports'].items():
        try:
            result = run([sys.executable, '-c',
                          'import importlib,sys; from pathlib import Path; '
                          'm=importlib.import_module(sys.argv[1]); print(Path(m.__file__).resolve())', name])
            path = Path(result.stdout.strip())
            if not path.is_relative_to((ROOT / source).resolve()):
                raise ValueError(f'import resolves outside this checkout: {path}')
            print(f'{name}: {path}')
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            errors.append(f'{name}: {error}; run uv sync --locked in this checkout')
    try:
        version = run([sys.executable, '-c', 'import pyarrow; print(pyarrow.__version__)']).stdout.strip()
        lock = tomllib.loads((ROOT / 'uv.lock').read_text())
        expected = next(package['version'] for package in lock['package'] if package['name'] == 'pyarrow')
        if version != expected:
            raise ValueError(f'expected locked {expected}, got {version}')
        print(f'PyArrow: {version}')
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        errors.append(f'PyArrow: {error}; run uv sync --locked')
    for command, native in config['environment']['native'].items():
        remedy = native['macos_remedy' if sys.platform == 'darwin' else 'linux_remedy']
        executable = shutil.which(command)
        if not executable:
            errors.append(f'Missing {command}; remedy: {remedy}')
            continue
        try:
            result = run([executable, *(arg.replace('{pid}', str(os.getpid())) for arg in native['arguments'])])
            print(f'{command}: {(result.stdout or result.stderr).splitlines()[0]}')
        except (OSError, subprocess.SubprocessError) as error:
            errors.append(f'{command}: {error}; remedy: {remedy}')
    lane = config['lanes'].get(lane_name, {})
    if variable := lane.get('required_binary_env'):
        binary = os.environ.get(variable)
        if not binary or not Path(binary).is_file() or not os.access(binary, os.X_OK):
            errors.append(f'{variable} must name an executable source-fetch binary for native qualification; see docs/development.md')
    if lane.get('requires_baseline'):
        try:
            print('Baseline: ' + baseline(config))
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            errors.append(str(error))
    if errors:
        raise ValueError('\n'.join(errors))
    print('Doctor passed.')


def test(config, name, paths, pytest_args):
    lane = config['lanes'][name]
    if not lane['roots']:
        raise ValueError(f'{name}: {lane["rationale"]} Requirements: {lane["requirements"]}')
    inventory(config)
    doctor(config, name)
    selected = paths or lane['roots']
    for path in selected:
        resolved = (ROOT / path.split('::', 1)[0]).resolve()
        if not any(resolved == (ROOT / root).resolve() or resolved.is_relative_to((ROOT / root).resolve())
                   for root in lane['roots']):
            raise ValueError(f'{path} is outside the {name} suite roots')
    command = [sys.executable]
    if lane['offline']:
        command += [str(ROOT / '.github/scripts/offline-python.py')]
    command += ['-m', 'pytest', '-c', str(ROOT / 'pytest.ini'), '-q']
    if marker := lane.get('marker'):
        command += ['-m', marker]
    command += selected + pytest_args
    print(f'Running {name}: {lane["purpose"]}', flush=True)
    result = subprocess.run(command, cwd=ROOT)
    if name == 'native-loopback':
        print('Native qualification requires reviewing the -ra summary: skipped checks are unqualified.', flush=True)
    return result.returncode


def main(argv=None):
    config = declaration()
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    check = sub.add_parser('doctor')
    check.add_argument('--lane', choices=config['lanes'])
    chk = sub.add_parser('check', help='Run doctor environment checks followed by test inventory')
    chk.add_argument('--lane', choices=config['lanes'])
    sub.add_parser('inventory')
    sub.add_parser('prepare-baseline', help='Fetch only the exact historical parser commit when absent, then verify its hash')
    tests = sub.add_parser('test')
    tests.add_argument('lane', choices=config['lanes'], nargs='?', default='production-offline')
    tests.add_argument('--path', action='append', default=[], help='Restrict to a path or node within this lane (repeatable)')
    values = list(sys.argv[1:] if argv is None else argv)
    extra = []
    if '--' in values:
        split = values.index('--')
        values, extra = values[:split], values[split + 1:]
    args = parser.parse_args(values)
    try:
        if args.command == 'doctor':
            doctor(config, args.lane)
        elif args.command == 'inventory':
            inventory(config)
        elif args.command == 'check':
            doctor(config, getattr(args, 'lane', None))
            inventory(config)
        elif args.command == 'prepare-baseline':
            print('Baseline verified: ' + baseline(config, fetch=True))
        else:
            return test(config, args.lane, args.path, extra)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
