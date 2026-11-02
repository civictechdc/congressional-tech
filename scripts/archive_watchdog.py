#!/usr/bin/env python3
"""Run one native archive job under a process-tree RSS limit, and record its peak.

Engine pool settings do not bound process RSS: one expression reached 20.4 GiB at a
1 GiB pool, and an out-of-memory crash took down a 48 GB machine. A runaway stops with
exit 99 and a named failure on stderr; the limit is high on purpose, not a target.

    python3 scripts/archive_watchdog.py --rss-gb 40 --report peak.json -- <command> [args...]

Standard library only, so it can run before any environment is set up. --lock serializes
jobs that share a machine; hosted runners, which run one job, leave it off. Sampling is
once a second, so an allocation faster than that can pass the limit before the stop; the
machine-floor check covers what other processes use too.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

STOPPED = 99
REFUSED = 98


def tree_rss_gb(root):
    """Sum real RSS over a process and all its descendants, O(processes) per sample."""
    rows = subprocess.run(['ps', '-axo', 'pid=,ppid=,rss='], capture_output=True, text=True).stdout.splitlines()
    children, rss = {}, {}
    for row in rows:
        parts = row.split()
        if len(parts) == 3:
            pid, parent, kilobytes = map(int, parts)
            children.setdefault(parent, []).append(pid)
            rss[pid] = kilobytes
    total, stack = 0, [root]
    while stack:
        pid = stack.pop()
        total += rss.get(pid, 0)
        stack.extend(children.get(pid, []))
    return total / 1048576


def available_gb():
    """Memory the machine can still hand out, or None where that is not knowable."""
    if sys.platform == 'darwin':
        text = subprocess.run(['vm_stat'], capture_output=True, text=True).stdout
        page = int(text.split('page size of ')[1].split()[0])
        pages = sum(int(line.split(':')[1].strip().rstrip('.')) for line in text.splitlines()
                    if line.startswith(('Pages free', 'Pages inactive', 'Pages speculative', 'Pages purgeable')))
        return pages * page / 2**30
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            if line.startswith('MemAvailable:'):
                return int(line.split()[1]) / 1048576
    except OSError:
        pass
    return None


def acquire(lock, wait_seconds):
    """One job at a time across processes; a dead owner's lock is reclaimed."""
    deadline = time.time() + wait_seconds
    while True:
        try:
            lock.mkdir(parents=True)
            (lock / 'owner').write_text(f'{os.getpid()}\n')
            return True
        except FileExistsError:
            try:
                os.kill(int((lock / 'owner').read_text().split()[0]), 0)
            except (FileNotFoundError, ValueError, IndexError):
                pass  # Another process is mid-acquire.
            except ProcessLookupError:
                (lock / 'owner').unlink(missing_ok=True)
                lock.rmdir()
                continue
            if time.time() > deadline:
                return False
            time.sleep(5)


def stop(process):
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def watch(command, *, rss_gb, min_available_gb, min_disk_gb, disk_root, interval):
    """Return (exit code, peak GiB, reason). The child leads its own process group."""
    process = subprocess.Popen(command, start_new_session=True)
    peak, started = 0.0, time.monotonic()
    while process.poll() is None:
        rss = tree_rss_gb(process.pid)
        peak = max(peak, rss)
        reason = None
        if rss > rss_gb:
            reason = f'process tree RSS {rss:.1f} GiB over the {rss_gb} GiB limit'
        elif shutil.disk_usage(disk_root).free / 2**30 < min_disk_gb:
            reason = f'free disk under {min_disk_gb} GiB'
        else:
            available = available_gb()
            if available is not None and available < min_available_gb:
                reason = f'machine memory available {available:.1f} GiB under {min_available_gb} GiB'
        if reason:
            stop(process)
            return STOPPED, peak, reason, time.monotonic() - started
        time.sleep(interval)
    return process.returncode, peak, None, time.monotonic() - started


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--rss-gb', type=float, required=True, help='Stop the job above this process-tree RSS')
    parser.add_argument('--report', type=Path, help='Write command, limit, peak, seconds and outcome as JSON')
    parser.add_argument('--lock', type=Path, help='Directory lock serializing jobs on a shared machine')
    parser.add_argument('--wait-seconds', type=int, default=3600)
    parser.add_argument('--min-available-gb', type=float, default=4.0, help='Stop if the machine falls below this')
    parser.add_argument('--min-disk-gb', type=float, default=15.0, help='Stop if free disk falls below this')
    parser.add_argument('--interval', type=float, default=1.0)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('a command is required')
    if args.lock and not acquire(args.lock, args.wait_seconds):
        print('archive_watchdog: timed out waiting for the one job slot', file=sys.stderr)
        return REFUSED
    try:
        code, peak, reason, seconds = watch(command, rss_gb=args.rss_gb, min_available_gb=args.min_available_gb,
            min_disk_gb=args.min_disk_gb, disk_root=args.report.parent if args.report else Path.cwd(), interval=args.interval)
    finally:
        if args.lock:
            (args.lock / 'owner').unlink(missing_ok=True)
            args.lock.rmdir()
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(dict(command=command, rss_limit_gb=args.rss_gb, peak_rss_gb=round(peak, 3),
            seconds=round(seconds, 1), exit_code=code, stopped=reason), indent=1) + '\n')
    if reason:
        print(f'archive_watchdog: stopped; {reason}; peak {peak:.2f} GiB', file=sys.stderr)
    else:
        print(f'archive_watchdog: finished rc={code}; peak {peak:.2f} GiB in {seconds:.0f} s', file=sys.stderr)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
