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
    """Load and parse the project test-suites.toml configuration."""
    return tomllib.loads((ROOT / 'test-suites.toml').read_text())


def run(command, *, timeout=15):
    """Execute a subprocess command in the project root with standard timeouts."""
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
    tests = {name for name in names if Path(name).match('test_*.py') or Path(name).match('*_test.py')}
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
    return tests


def doctor(config, lane_name=None):
    """Verify local runtime prerequisites, Python version, native CLI dependencies, and imports."""
    errors = []
    try:
        import_timeout = int(os.environ.get('CT_PREREQUISITE_TIMEOUT_SECONDS', '15'))
    except ValueError:
        raise ValueError('CT_PREREQUISITE_TIMEOUT_SECONDS must be an integer from 1 to 120') from None
    if not 1 <= import_timeout <= 120:
        raise ValueError('CT_PREREQUISITE_TIMEOUT_SECONDS must be an integer from 1 to 120')
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
                          'm=importlib.import_module(sys.argv[1]); print(Path(m.__file__).resolve())', name], timeout=import_timeout)
            path = Path(result.stdout.strip())
            if not path.is_relative_to((ROOT / source).resolve()):
                raise ValueError(f'import resolves outside this checkout: {path}')
            print(f'{name}: {path}')
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            errors.append(f'{name}: {error}; run uv sync --locked in this checkout')
    try:
        version = run([sys.executable, '-c', 'import pyarrow; print(pyarrow.__version__)'], timeout=import_timeout).stdout.strip()
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
    job_runtime(config, lane_name)
    print('Doctor passed.')


def job_runtime(config, lane_name):
    """Verify explicit local native-job setup without executing or loading secrets."""
    variable = config['lanes'].get(lane_name, {}).get('required_job_config_env')
    if not variable:
        return
    remedy = f'{variable} must name an explicit pinned local runtime; see docs/development.md'
    location = os.environ.get(variable)
    if not location:
        raise ValueError(remedy)
    try:
        settings = json.loads(Path(location).read_text())
        if (not isinstance(settings, dict) or 'remote' in settings or 'credentials' in settings
                or not all(settings.get(key) for key in ('limits', 'source_revision',
                                                         'binary_sha256', 'platform', 'build_features'))):
            raise ValueError('local job pins and limits are required; remote/credentials are forbidden')
        from docspec_client import NativeDatasets
        with NativeDatasets.from_config(location) as native:
            if native.limits is None or not native.limits.is_file():
                raise ValueError('configured limits file is unavailable')
            native.verify_runtime()
    except (OSError, ValueError, TypeError) as error:
        raise ValueError(f'{remedy}: {error}') from None


def parse_shard(value):
    """Parse a one-based INDEX/COUNT without starting prerequisites or tests."""
    try:
        index, count = map(int, value.split('/'))
        if not 1 <= index <= count:
            raise ValueError
    except ValueError:
        raise argparse.ArgumentTypeError('shard must be INDEX/COUNT with 1 <= INDEX <= COUNT') from None
    return index, count


def shard_files(files, roots, shard):
    """Sort T enrolled files in O(T log T), retaining the lane's pytest filters."""
    index, count = shard
    if not 1 <= index <= count:
        raise ValueError('shard must satisfy 1 <= INDEX <= COUNT')
    candidates = sorted({path for path in files if any(
        path == root or path.startswith(root.rstrip('/') + '/') for root in roots)})
    selected = candidates[index - 1::count]
    if not selected:
        raise ValueError(f'shard {index}/{count} is empty; no tests were started')
    return selected


def test(config, name, paths, pytest_args, *, shard=None):
    """Execute pytest against the selected test lane with environment tripwires."""
    lane = config['lanes'][name]
    if not lane['roots']:
        raise ValueError(f'{name}: {lane["rationale"]} Requirements: {lane["requirements"]}')
    if shard is not None and paths:
        raise ValueError('--path and --shard cannot be combined')
    files = inventory(config)
    selected = shard_files(files, lane['roots'], shard) if shard is not None else paths or lane['roots']
    for path in selected:
        resolved = (ROOT / path.split('::', 1)[0]).resolve()
        if not any(resolved == (ROOT / root).resolve() or resolved.is_relative_to((ROOT / root).resolve())
                   for root in lane['roots']):
            raise ValueError(f'{path} is outside the {name} suite roots')
    if runner := lane.get('runner'):
        paths = [str(ROOT / path) for path in selected]
        return subprocess.run([str(ROOT / runner[0]), str(ROOT / runner[1]), *runner[2:], *paths, *pytest_args], cwd=ROOT).returncode
    doctor(config, name)
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


def clean(*, dry_run=True):
    """Scan and reclaim stale build directories, egg-info, and bytecode caches."""
    targets = []
    # Find build/ and *.egg-info in packages and apps (excluding cargo target/ and node_modules/)
    for parent in [ROOT / 'packages', ROOT / 'apps']:
        if parent.exists():
            for p in parent.rglob('build'):
                if p.is_dir() and 'target' not in p.parts and 'node_modules' not in p.parts:
                    targets.append(p)
            for p in parent.rglob('*.egg-info'):
                if p.is_dir():
                    targets.append(p)
    # Find __pycache__ and .pytest_cache (excluding .venv, node_modules, output, and .cache)
    for p in ROOT.rglob('__pycache__'):
        if p.is_dir() and not any(part in p.parts for part in ('.venv', 'node_modules', 'output', '.cache')):
            targets.append(p)
    pytest_cache = ROOT / '.pytest_cache'
    if pytest_cache.is_dir():
        targets.append(pytest_cache)

    total_bytes = 0
    for target in sorted(set(targets)):
        size = 0
        if target.is_dir():
            for f in target.rglob('*'):
                if f.is_file():
                    size += f.stat().st_size
        elif target.is_file():
            size = target.stat().st_size
        total_bytes += size
        action_prefix = '[DRY-RUN] Would remove' if dry_run else 'Removing'
        try:
            rel = target.relative_to(ROOT)
        except ValueError:
            rel = target
        print(f'{action_prefix}: {rel} ({size:,} bytes)')
        if not dry_run:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()

    # Report cache/output retention status without deleting them
    cache_dir = ROOT / '.cache'
    output_dir = ROOT / 'output'
    print('\n--- Cache & Output Retention Status ---')
    if cache_dir.exists():
        print('Preserving .cache/ (retention rule: data preservation active)')
    if output_dir.exists():
        print('Preserving output/ (retention rule: data preservation active)')
    print(f'Total reclaimable space in scanned targets: {total_bytes:,} bytes')
    if dry_run:
        print('Dry-run complete. No files were deleted. Pass --execute to remove scanned build artifacts.')


def main(argv=None):
    """Main CLI entrypoint for scripts/dev.py."""
    config = declaration()
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    check = sub.add_parser('doctor')
    check.add_argument('--lane', choices=config['lanes'])
    chk = sub.add_parser('check', help='Run doctor environment checks followed by test inventory')
    chk.add_argument('--lane', choices=config['lanes'])
    sub.add_parser('inventory')
    sub.add_parser('prepare-baseline', help='Fetch only the exact historical parser commit when absent, then verify its hash')
    clean_p = sub.add_parser('clean', help='Scan and reclaim stale build, egg-info, and cache artifacts')
    clean_p.add_argument('--execute', action='store_true', help='Execute deletion of stale artifacts (default is dry-run)')
    clean_p.add_argument('--dry-run', action='store_true', default=True, help='Simulate cleanup without deleting (default)')
    tests = sub.add_parser('test')
    tests.add_argument('lane', choices=config['lanes'], nargs='?', default='production-offline')
    tests.add_argument('--path', action='append', default=[], help='Restrict to a path or node within this lane (repeatable)')
    tests.add_argument('--shard', type=parse_shard, metavar='INDEX/COUNT',
                       help='Run one disjoint partition of the full lane (one-based; cannot combine with --path)')
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
        elif args.command == 'clean':
            is_dry_run = not getattr(args, 'execute', False)
            clean(dry_run=is_dry_run)
        elif args.command == 'prepare-baseline':
            print('Baseline verified: ' + baseline(config, fetch=True))
        else:
            return test(config, args.lane, args.path, extra, shard=args.shard)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
