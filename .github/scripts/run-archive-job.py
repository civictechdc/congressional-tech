"""Run the declared owner CLI once, under the archive watchdog. Pending job specs refuse before any import.

An active binding carries its measured process-tree limit, rss_gb; without one it refuses,
because engine pool settings do not bound process RSS (scripts/archive_watchdog.py).
"""
import argparse
import json
import os
from pathlib import Path
import resource
import runpy
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FILE_LIMIT = 65536


def raise_file_limit(target=FILE_LIMIT):
    """Raise the soft open-file limit to `target` (or the hard limit, if lower); children inherit it."""
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    wanted = target if hard == resource.RLIM_INFINITY else min(target, hard)
    if soft != resource.RLIM_INFINITY and soft < wanted:
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (wanted, hard))
        except (ValueError, OSError):
            resource.setrlimit(resource.RLIMIT_NOFILE, (min(wanted, 10240), hard))
    return soft, resource.getrlimit(resource.RLIMIT_NOFILE)[0]


def binding_command(binding, spec):
    if binding.get('argv') != ['--execute']:
        raise ValueError('active job needs explicit --execute arguments')
    rss_gb = binding.get('rss_gb')
    if isinstance(rss_gb, bool) or not isinstance(rss_gb, (int, float)) or not rss_gb > 0:
        raise ValueError('active job has no measured rss_gb')
    return [sys.executable, '-I', '-m', binding['module'], '--spec', str(spec), *binding['argv']]


def watched_command(command, binding, operation, temp, *, lock_fd=None, env=None):
    """The owner command under the watchdog, with its report and timeline in the runner's temp."""
    active_env = os.environ if env is None else env
    hosted_args = ['--min-available-gb', '0'] if active_env.get('GITHUB_ACTIONS') == 'true' else []
    lock_args = [] if lock_fd is None else ['--hold-fd', str(lock_fd)]
    return [sys.executable, '-I', str(ROOT / 'scripts/archive_watchdog.py'), '--rss-gb', str(binding['rss_gb']),
            '--report', str(Path(temp) / f'{operation}-watchdog.json'), '--timeline', '--min-disk-gb', '15',
            *hosted_args, *lock_args, '--', *command]


def _daily_work_dir(spec_path):
    spec_path = Path(spec_path).resolve()
    spec_value = json.loads(spec_path.read_text())
    daily_entry = spec_value.get('daily')
    if not isinstance(daily_entry, dict) or not isinstance(daily_entry.get('path'), str):
        return None
    daily_spec_path = (spec_path.parent / daily_entry['path']).resolve()
    daily_spec = json.loads(daily_spec_path.read_text())
    return (daily_spec_path.parent / daily_spec['work']).resolve()


def daily_backfill_required(spec_path):
    """Return True when the daily producer wrote a `backfill_required` summary."""
    try:
        daily_work = _daily_work_dir(spec_path)
        if daily_work is None:
            return False
        summary = daily_work / 'daily-summary.json'
        if not summary.is_file() or summary.is_symlink():
            return False
        value = json.loads(summary.read_text())
        return isinstance(value, dict) and value.get('status') == 'backfill_required'
    except (OSError, ValueError, KeyError, TypeError):
        return False


def retire_for_backfill(spec_path, archive_dir, *, backfill_spec_path=None):
    """Move prior publish/daily/backfill directories aside so backfill and retry start fresh."""
    spec_path = Path(spec_path).resolve()
    spec_value = json.loads(spec_path.read_text())
    targets = [
        (spec_path.parent / spec_value['work']).resolve(),
        (ROOT / 'output/archive-backfill').resolve(),
    ]
    model_entry = spec_value.get('model_spec')
    if isinstance(model_entry, dict) and isinstance(model_entry.get('path'), str):
        model_path = (spec_path.parent / model_entry['path']).resolve()
        model_value = json.loads(model_path.read_text())
        targets.extend([
            (model_path.parent / model_value['output']).resolve(),
            (model_path.parent / model_value['scratch']).resolve(),
        ])
    daily_work = _daily_work_dir(spec_path)
    if daily_work is not None:
        targets.extend([daily_work, daily_work.with_name(daily_work.name + '-provenance')])
    if backfill_spec_path is not None:
        bf_path = Path(backfill_spec_path).resolve()
        bf_value = json.loads(bf_path.read_text())
        if isinstance(bf_value.get('work'), str):
            targets.append((bf_path.parent / bf_value['work']).resolve())

    archive_dir = Path(archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)
    seen = set()
    for target in targets:
        if target in seen:
            continue
        seen.add(target)
        if target.is_symlink():
            raise ValueError(f'Refusing to move symlinked work directory before backfill: {target}')
        if target.exists():
            destination = archive_dir / target.name
            if destination.exists() or destination.is_symlink():
                shutil.rmtree(destination)
            shutil.move(str(target), str(destination))


def check_publisher_plan(command, output):
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
        if output is not None:
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
    parser.add_argument('--nightly-work', type=Path, help='Retain the scheduled Mac candidate here')
    parser.add_argument('--nightly-lock-fd', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--check-disk', action='store_true', help='Report disk admission without launching the owner')
    parser.add_argument('--keep-candidate', action='store_true',
                        help='Resume the publish candidate an earlier hosted run kept, when it is this run\'s (ct-31qi)')
    args = parser.parse_args()
    if args.check_disk and args.check_binding:
        parser.error('--check-disk and --check-binding are separate checks')
    if args.nightly_work is not None and (args.operation != 'publish' or args.check_binding):
        parser.error('--nightly-work requires a publish execution')
    if args.keep_candidate and (args.operation != 'publish' or args.check_binding or args.nightly_work is not None):
        parser.error('--keep-candidate requires a hosted publish execution')
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
        return check_publisher_plan(command, args.github_output) if args.operation == 'publish' else 0
    if args.nightly_work is not None:
        command.extend(['--nightly-work', str(args.nightly_work.resolve())])
    if args.keep_candidate:
        command.append('--keep-candidate')
    temp = os.environ.get('RUNNER_TEMP') or tempfile.gettempdir()
    disk = runpy.run_path(str(ROOT / 'scripts/archive_disk.py'))
    admission = disk['job_admission'](ROOT, args.operation, spec, temp=temp, nightly_work=args.nightly_work)
    print(json.dumps(dict(disk_admission=admission), sort_keys=True), flush=True)
    if not args.check_disk:
        report = Path(temp) / f'{args.operation}-disk-admission.json'
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(admission, indent=2) + '\n')
    if admission['status'] != 'admitted':
        return 2
    if args.check_disk:
        return 0
    raise_file_limit()
    pass_fds = () if args.nightly_lock_fd is None else (args.nightly_lock_fd,)
    watched = watched_command(command, binding, args.operation, temp, lock_fd=args.nightly_lock_fd)
    code = subprocess.run(watched, cwd=ROOT, pass_fds=pass_fds).returncode
    if code != 0 and args.operation == 'publish' and args.nightly_work is None and daily_backfill_required(spec):
        bindings = json.loads((ROOT / '.github/archive-jobs.json').read_text())
        backfill_binding = bindings['backfill']
        backfill_spec = ROOT / backfill_binding['spec']
        backfill_value = json.loads(backfill_spec.read_text())
        if backfill_value.get('status') == 'blocked':
            print('Archive job refused: ' + backfill_value['reason'], file=sys.stderr)
            return 2
        if not backfill_binding['module']:
            print('Archive job refused: owner CLI is not bound', file=sys.stderr)
            return 2
        try:
            backfill_cmd = binding_command(backfill_binding, backfill_spec)
        except ValueError as error:
            print('Archive job refused: ' + str(error), file=sys.stderr)
            return 2
        bf_admission = disk['job_admission'](ROOT, 'backfill', backfill_spec, temp=temp)
        print(json.dumps(dict(disk_admission=bf_admission), sort_keys=True), flush=True)
        (Path(temp) / 'backfill-disk-admission.json').write_text(json.dumps(bf_admission, indent=2) + '\n')
        if bf_admission['status'] != 'admitted':
            return 2
        retire_for_backfill(spec, Path(temp) / 'before-backfill', backfill_spec_path=backfill_spec)
        backfill_code = subprocess.run(watched_command(backfill_cmd, backfill_binding, 'backfill', temp), cwd=ROOT).returncode
        if backfill_code != 0:
            return backfill_code
        retry_admission = disk['job_admission'](ROOT, 'publish', spec, temp=temp)
        print(json.dumps(dict(disk_admission=retry_admission), sort_keys=True), flush=True)
        (Path(temp) / 'publish-after-backfill-disk-admission.json').write_text(json.dumps(retry_admission, indent=2) + '\n')
        if retry_admission['status'] != 'admitted':
            return 2
        code = subprocess.run(watched_command(command, binding, 'publish-after-backfill', temp), cwd=ROOT).returncode
        if code == 0 and daily_backfill_required(spec):
            return 2
    return code


if __name__ == '__main__':
    raise SystemExit(main())
