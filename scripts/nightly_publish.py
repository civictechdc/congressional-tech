#!/usr/bin/env python3
"""Prepare the dedicated nightly checkout; external publication is unavailable.

Native input custody, producer prerequisite admission and frozen publication
intent must be qualified before scheduled activation can resume. Existing
candidate trees are preserved. This command no longer imports or retires the
removed application model journals.

    python3 scripts/nightly_publish.py --prepare
"""
import argparse
import datetime
import fcntl
import importlib.util
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

LABEL = 'ai.spicygov.archive-nightly'
PUBLICATION_UNAVAILABLE = ('Nightly publication is unavailable until the native runtime supports '
                          'exact input custody, producer prerequisites and frozen publication intent; '
                          'existing candidates remain retained.')


def run_owned(command, **options):
    ownership = importlib.util.spec_from_file_location(
        'nightly_process_owner', Path(__file__).with_name('measure') / 'process_rss.py')
    owner = importlib.util.module_from_spec(ownership)
    ownership.loader.exec_module(owner)
    process = owner.start_owned(command, **options)
    try:
        stdout, stderr = process.communicate()
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    finally:
        owner.stop_owned(process)


def git(*args, cwd, capture=True, pass_fds=()):
    run = run_owned if pass_fds else subprocess.run
    result = run(['git', *args], cwd=cwd, text=True, pass_fds=pass_fds,
                 stdout=subprocess.PIPE if capture else None)
    result.check_returncode()
    return result.stdout.strip() if capture else ''


def main_checkout(start):
    common = Path(git('rev-parse', '--path-format=absolute', '--git-common-dir', cwd=start))
    return common.parent


def update_worktree(main, worktree, *, pass_fds):
    git('fetch', '--quiet', 'origin', 'main', cwd=main, pass_fds=pass_fds)
    target = git('rev-parse', 'FETCH_HEAD', cwd=main)
    if not (worktree / '.git').exists():
        git('worktree', 'add', '--detach', str(worktree), target, cwd=main, capture=False, pass_fds=pass_fds)
        return target
    dirty = git('--no-optional-locks', 'status', '--porcelain', cwd=worktree)
    if dirty:
        raise SystemExit(f'nightly refused: {worktree} has local changes:\n{dirty}')
    git('checkout', '--quiet', '--detach', target, cwd=worktree, pass_fds=pass_fds)
    return target


def step(name, command, *, cwd, env, log, pass_fds=()):
    started = time.monotonic()
    print(f'== {name}: {" ".join(map(str, command))}', file=log, flush=True)
    code = run_owned(list(map(str, command)), cwd=cwd, env=env, stdout=log,
                     stderr=subprocess.STDOUT, pass_fds=pass_fds).returncode
    print(f'== {name}: exit {code} in {time.monotonic() - started:.0f}s', file=log, flush=True)
    if code:
        raise StepFailed(name, code)


class StepFailed(Exception):
    def __init__(self, name, code):
        super().__init__(f'{name} exited {code}')
        self.name, self.code = name, code


def publish_env(main, worktree):
    remote_runtime = main / '.cache/archive-release/remote-runtime'
    credentials = json.loads((remote_runtime / 'credentials.json').read_text())
    remote = json.loads((remote_runtime / 'remote.json').read_text())
    account = re.fullmatch(r'https://([a-f0-9]{32})\.r2\.cloudflarestorage\.com',
                           remote['properties']['s3.endpoint']).group(1)
    env = dict(os.environ)
    for name in ('PYTHONPATH', 'VIRTUAL_ENV', 'DOCSPEC_JOB_CONFIG', 'DOCSPEC_RUNTIME_CONFIG'):
        env.pop(name, None)
    env.update(
        CLOUDFLARE_ACCOUNT_ID=account,
        R2_ACCESS_KEY_ID=credentials['DOCSPEC_S3_ACCESS_KEY_ID'],
        R2_SECRET_ACCESS_KEY=credentials['DOCSPEC_S3_SECRET_ACCESS_KEY'],
        DOCSPEC_RUNTIME_CONFIG=str(remote_runtime / 'runtime.json'),
        DOCSPEC_JOB_CONFIG=str(worktree / '.cache/local-runtime/runtime.json'),
    )
    return env


def run(worktree, prepare_only, *, lock_fd=None):
    if not prepare_only:
        print(PUBLICATION_UNAVAILABLE,file=sys.stderr)
        return 2
    main = main_checkout(worktree)
    nightly = main / '.cache/archive-release/nightly'
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    evidence = nightly / stamp
    evidence.mkdir(parents=True)
    head = git('rev-parse', 'HEAD', cwd=worktree)
    env = publish_env(main, worktree)
    env['RUNNER_TEMP'] = str(evidence)
    python = worktree / '.venv/bin/python'
    summary = dict(started=stamp, commit=head, worktree=str(worktree))
    pass_fds = () if lock_fd is None else (lock_fd,)
    with (evidence / 'log.txt').open('w') as log:
        def run_step(name, command, *, step_env=env):
            step(name, command, cwd=worktree, env=step_env, log=log, pass_fds=pass_fds)

        try:
            run_step('uv sync', ['uv', 'sync', '--frozen'])
            run_step('catalog install', [python, 'scripts/dev.py', 'install-catalog'])
            run_step('npm ci', ['npm', '--prefix', 'apps/site', 'ci'])
            run_step('browser', ['node', 'apps/site/node_modules/playwright/cli.js', 'install', '--only-shell', 'chromium'])
            run_step('local runtime', [python, 'scripts/dev.py', 'write-local-runtime', '--limits',
                                   '.github/docspec-local-limits.json', '--out', '.cache/local-runtime/runtime.json'])
            run_step('doctor', [python, 'scripts/dev.py', 'doctor'])
            run_step('spicy-regs', [python, '-I', '-m', 'viewer_publication.spicy_regs_inputs',
                                '--model-spec', 'model/jobs/publish-model.json'])
            run_step('site build', ['npm', '--prefix', 'apps/site', 'run', 'build'])
            dirty = git('--no-optional-locks', 'status', '--porcelain', cwd=worktree)
            if dirty:
                print(f'== setup left the worktree dirty, which gate 5 refuses:\n{dirty}', file=log, flush=True)
                raise StepFailed('clean tree', 1)
            summary.update(status='prepared', exit=0)
        except StepFailed as failure:
            summary.update(status='failed', step=failure.name, exit=failure.code)
        finally:
            summary['finished'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            (evidence / 'summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n')
    print(json.dumps(summary, sort_keys=True))
    return summary['exit']


def real_tool(name):
    found = shutil.which(name)
    if found and '/.pyenv/shims/' in found:
        found = subprocess.run(['pyenv', 'which', name], text=True, stdout=subprocess.PIPE, check=True).stdout.strip()
    return found


def install(main, hour, minute):
    names = ('pdfinfo', 'uv', 'node', 'git')
    tools = [real_tool(name) for name in names]
    if not all(tools):
        raise SystemExit('nightly install refused: ' + ', '.join(names) + ' must be on PATH')
    path = list(dict.fromkeys([str(Path(tool).parent) for tool in tools] + ['/usr/bin', '/bin', '/usr/sbin', '/sbin']))
    logs = main / '.cache/archive-release/nightly'
    logs.mkdir(parents=True, exist_ok=True)
    agent = dict(
        Label=LABEL,
        ProgramArguments=['/usr/bin/python3', str(main / 'scripts/nightly_publish.py')],
        WorkingDirectory=str(main),
        EnvironmentVariables=dict(PATH=':'.join(path), HOME=str(Path.home())),
        StartCalendarInterval=dict(Hour=hour, Minute=minute),
        StandardOutPath=str(logs / 'launchd.out.log'),
        StandardErrorPath=str(logs / 'launchd.err.log'),
        ProcessType='Background',
    )
    target = Path.home() / 'Library/LaunchAgents' / f'{LABEL}.plist'
    target.write_bytes(plistlib.dumps(agent))
    domain = f'gui/{os.getuid()}'
    subprocess.run(['launchctl', 'bootout', f'{domain}/{LABEL}'], stderr=subprocess.DEVNULL)
    subprocess.run(['launchctl', 'bootstrap', domain, str(target)], check=True)
    print(json.dumps(dict(installed=str(target), schedule=f'{hour:02d}:{minute:02d} local', path=agent['EnvironmentVariables']['PATH'])))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--install', action='store_true', help='Write and load the launchd agent, then exit')
    parser.add_argument('--hour', type=int, default=5)
    parser.add_argument('--minute', type=int, default=30)
    parser.add_argument('--prepare', action='store_true', help='Run every setup step but not the publish')
    parser.add_argument('--in-worktree', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--lock-fd', type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not args.prepare and not args.install:
        print(PUBLICATION_UNAVAILABLE,file=sys.stderr)
        return 2
    here = Path(__file__).resolve().parents[1]
    main_root = main_checkout(here)
    if args.install:
        return install(main_root, args.hour, args.minute)
    worktree = main_root / '.claude/worktrees/nightly'
    lock_path = main_root / '.cache/archive-release/nightly/lock'
    if args.lock_fd is not None:
        if not args.in_worktree or not os.path.samestat(os.fstat(args.lock_fd), lock_path.stat()):
            parser.error('expected the inherited nightly lock')
        return run(here, args.prepare, lock_fd=args.lock_fd)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('nightly refused: another run holds the lock', file=sys.stderr)
            return 3
        if args.in_worktree:
            return run(here, args.prepare, lock_fd=lock.fileno())
        update_worktree(main_root, worktree, pass_fds=(lock.fileno(),))
        # The publishing child and watchdog keep the lock if their launcher exits first.
        return subprocess.run([sys.executable, str(worktree / 'scripts/nightly_publish.py'), '--in-worktree',
                               '--lock-fd', str(lock.fileno()), *(['--prepare'] if args.prepare else [])],
                              cwd=worktree, pass_fds=(lock.fileno(),)).returncode


if __name__ == '__main__':
    raise SystemExit(main())
