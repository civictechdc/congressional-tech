#!/usr/bin/env python3
"""Run production-offline as six shards, then storage-loopback, for one worktree; detached.

    python3 scripts/run_lanes.py <worktree> <log dir> [--take-lock]

Each shard runs under scripts/archive_watchdog.py with its own local runtime file
(<worktree>/.cache/local-runtime/shard-N/runtime.json, written beforehand). The result is
<log dir>/driver.log: one line per lane with its exit code, then DONE. Tested means all six
`(shard i/6): exit 0` and `storage-loopback (full lane): exit 0`.

--take-lock waits for and holds <main>/.cache/archive-release/heavy-slot.lock for the run.
"""
import datetime
import os
import pathlib
import shutil
import subprocess
import sys
import time


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def default_lock_path(worktree: pathlib.Path) -> pathlib.Path:
    common = subprocess.run(
        ['git', 'rev-parse', '--path-format=absolute', '--git-common-dir'],
        cwd=worktree, capture_output=True, text=True, check=False,
    ).stdout.strip()
    main = pathlib.Path(common).parent if common else worktree.resolve()
    return main / '.cache/archive-release/heavy-slot.lock'


def lane(worktree: pathlib.Path, logs: pathlib.Path, name: str, args: list[str], runtime: pathlib.Path):
    env = dict(os.environ, DOCSPEC_JOB_CONFIG=str(runtime))
    python = str(worktree / '.venv/bin/python')
    command = [python, 'scripts/archive_watchdog.py', '--rss-gb', '8', '--expect-gb', '2',
               '--start-available-gb', '6', '--interval', '0.2', '--report', str(logs / f'{name}.watchdog.json'), '--',
               python, 'scripts/dev.py', 'test', *args]
    with (logs / f'{name}.log').open('w') as out:
        return subprocess.Popen(command, cwd=worktree, env=env, stdout=out, stderr=subprocess.STDOUT)


def run_driver(worktree: pathlib.Path, logs: pathlib.Path, *, take_lock: bool) -> int:
    logs.mkdir(parents=True, exist_ok=True)
    lock = default_lock_path(worktree)
    with (logs / 'driver.log').open('a', buffering=1) as log:
        tip = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=worktree, capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(['git', 'status', '--short'], cwd=worktree, capture_output=True, text=True).stdout.strip()
        log.write(f'{stamp()} tip {tip}, {len(dirty.splitlines())} uncommitted paths\n')
        if take_lock:
            lock.parent.mkdir(parents=True, exist_ok=True)
            while True:
                try:
                    lock.mkdir()
                    break
                except FileExistsError:
                    time.sleep(20)
            (lock / 'owner').write_text(f'lanes for {worktree.name} at {tip}, pid {os.getpid()}, since {stamp()}\n')
            log.write(f'{stamp()} lock taken\n')
        try:
            runtimes = [worktree / f'.cache/local-runtime/shard-{i}/runtime.json' for i in range(1, 7)]
            missing = [str(path) for path in runtimes if not path.exists()]
            if missing:
                log.write(f'{stamp()} failed: missing runtime files {missing}\n')
                return 2
            log.write(f'{stamp()} shards start\n')
            shards = [(i, lane(worktree, logs, f'shard-{i}', ['production-offline', '--shard', f'{i}/6'], runtimes[i - 1]))
                      for i in range(1, 7)]
            for i, process in shards:
                code = process.wait()
                log.write(f'{stamp()} production-offline (shard {i}/6): exit {code}\n')
            log.write(f'{stamp()} production-offline (shard 6/6) done; storage-loopback start\n')
            loopback = lane(worktree, logs, 'storage-loopback', ['storage-loopback'], runtimes[0])
            loopback_code = loopback.wait()
            log.write(f'{stamp()} storage-loopback (full lane): exit {loopback_code}\n')
        finally:
            if take_lock:
                shutil.rmtree(lock, ignore_errors=True)
                log.write(f'{stamp()} lock released\n')
            log.write(f'{stamp()} DONE\n')
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    worktree, logs = pathlib.Path(argv[0]).resolve(), pathlib.Path(argv[1]).resolve()
    if not worktree.is_dir():
        raise ValueError(f'Worktree directory does not exist: {worktree}')
    take_lock = '--take-lock' in argv
    if os.fork():
        return 0
    os.setsid()
    devnull = os.open(os.devnull, os.O_RDWR)
    for target in (0, 1, 2):
        os.dup2(devnull, target)
    if devnull > 2:
        os.close(devnull)
    return run_driver(worktree, logs, take_lock=take_lock)


if __name__ == '__main__':
    sys.exit(main())
