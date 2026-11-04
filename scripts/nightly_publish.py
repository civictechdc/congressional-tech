#!/usr/bin/env python3
"""Run the committed archive publish once on this Mac, from a clean checkout of origin/main.

The nightly publish runs here on a launchd schedule, not on a hosted runner (owner decision
2026-11-04, ct-ud0b). Each run updates one dedicated detached worktree to origin/main and
re-executes that worktree's copy of this script, so the code that publishes is always a pushed
commit (gate 5) in a tree with no other work. It then prepares what the hosted job's setup steps
prepare and runs `.github/scripts/run-archive-job.py publish` under its watchdog, with this
Mac's remote runtime and its credentials from `<main>/.cache/archive-release/remote-runtime/`.

Each run keeps its log, watchdog report and the small JSON files the job wrote under
`<main>/.cache/archive-release/nightly/<UTC stamp>/`. `output/` in the worktree is
rebuildable and is removed before each run, because the daily step refuses an existing
work directory.

    python3 scripts/nightly_publish.py --install   # write and load the launchd agent
    python3 scripts/nightly_publish.py              # one run now (what launchd calls)
"""
import argparse
import datetime
import fcntl
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
EVIDENCE_MAX_BYTES = 5 * 1024 * 1024


def git(*args, cwd, capture=True):
    result = subprocess.run(['git', *args], cwd=cwd, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else ''


def main_checkout(start):
    common = Path(git('rev-parse', '--path-format=absolute', '--git-common-dir', cwd=start))
    return common.parent


def update_worktree(main, worktree):
    git('fetch', '--quiet', 'origin', 'main', cwd=main)
    target = git('rev-parse', 'FETCH_HEAD', cwd=main)
    if not (worktree / '.git').exists():
        git('worktree', 'add', '--detach', str(worktree), target, cwd=main, capture=False)
        return target
    dirty = git('status', '--porcelain', cwd=worktree)
    if dirty:
        raise SystemExit(f'nightly refused: {worktree} has local changes:\n{dirty}')
    git('checkout', '--quiet', '--detach', target, cwd=worktree)
    return target


def step(name, command, *, cwd, env, log):
    started = time.monotonic()
    print(f'== {name}: {" ".join(map(str, command))}', file=log, flush=True)
    code = subprocess.run(list(map(str, command)), cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
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


def keep_evidence(worktree, evidence):
    output = worktree / 'output'
    if not output.is_dir():
        return
    for path in output.rglob('*.json'):
        if path.is_file() and path.stat().st_size <= EVIDENCE_MAX_BYTES:
            target = evidence / 'output' / path.relative_to(output)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def run(worktree, prepare_only):
    main = main_checkout(worktree)
    nightly = main / '.cache/archive-release/nightly'
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    evidence = nightly / stamp
    evidence.mkdir(parents=True)
    head = git('rev-parse', 'HEAD', cwd=worktree)
    env = publish_env(main, worktree)
    env['RUNNER_TEMP'] = str(evidence)
    python = worktree / '.venv/bin/python'
    summary = dict(started=stamp, commit=head, worktree=str(worktree))
    with (evidence / 'log.txt').open('w') as log:
        try:
            shutil.rmtree(worktree / 'output', ignore_errors=True)
            step('uv sync', ['uv', 'sync', '--frozen'], cwd=worktree, env=env, log=log)
            step('npm ci', ['npm', '--prefix', 'apps/site', 'ci'], cwd=worktree, env=env, log=log)
            step('browser', ['node', 'apps/site/node_modules/playwright/cli.js', 'install', '--only-shell', 'chromium'],
                 cwd=worktree, env=env, log=log)
            step('local runtime', [python, 'scripts/dev.py', 'write-local-runtime', '--limits',
                                   '.github/docspec-local-limits.json', '--out', '.cache/local-runtime/runtime.json'],
                 cwd=worktree, env=env, log=log)
            step('doctor', [python, 'scripts/dev.py', 'doctor'], cwd=worktree, env=env, log=log)
            step('spicy-regs', [python, '-I', '-m', 'viewer_publication.spicy_regs_inputs',
                                '--model-spec', 'model/jobs/publish-model.json'], cwd=worktree, env=env, log=log)
            step('site build', ['npm', '--prefix', 'apps/site', 'run', 'build'], cwd=worktree, env=env, log=log)
            if not prepare_only:
                step('publish', [python, '-I', '.github/scripts/run-archive-job.py', 'publish'],
                     cwd=worktree, env=env, log=log)
            summary.update(status='prepared' if prepare_only else 'ok', exit=0)
        except StepFailed as failure:
            summary.update(status='failed', step=failure.name, exit=failure.code)
        finally:
            keep_evidence(worktree, evidence)
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
    args = parser.parse_args(argv)
    here = Path(__file__).resolve().parents[1]
    main_root = main_checkout(here)
    if args.install:
        return install(main_root, args.hour, args.minute)
    worktree = main_root / '.claude/worktrees/nightly'
    if args.in_worktree:
        return run(here, args.prepare)
    lock_path = main_root / '.cache/archive-release/nightly/lock'
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('nightly refused: another run holds the lock', file=sys.stderr)
            return 3
        update_worktree(main_root, worktree)
        return subprocess.run([sys.executable, str(worktree / 'scripts/nightly_publish.py'), '--in-worktree',
                               *(['--prepare'] if args.prepare else [])], cwd=worktree).returncode


if __name__ == '__main__':
    raise SystemExit(main())
