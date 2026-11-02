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

The job runs under the shared owned-process trampoline (scripts/measure/process_rss.py):
TERM/INT/HUP to the watchdog stop the job, and if the watchdog itself is killed the
job's group leader notices and kills the group. --timeline writes one JSON line per
sample (seconds, RSS, physical, free disk) to <report>.timeline.jsonl.
"""
import argparse
import importlib.util
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


def _load_sampler():
    """The shared stdlib sampler and process owner, loaded by path like the capture monitor does."""
    path = Path(__file__).resolve().parent / 'measure/process_rss.py'
    spec = importlib.util.spec_from_file_location('archive_watchdog_sampler', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sampler = _load_sampler()


class Interrupted(Exception):
    """A signal to the watchdog; the finally clause then stops the owned job."""


def _interrupted(number, _frame):
    raise Interrupted(f'watchdog received signal {number}')


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


def watch(command, *, rss_gb, min_available_gb, min_disk_gb, disk_root, interval, timeline=None):
    """Return (exit code, peak resident GiB, peak physical GiB, reason, seconds).

    The limit applies to max(resident, physical): macOS charged footprint also counts
    compressed memory that RSS misses. The owned group is always stopped on the way out:
    a breach, a signal to the watchdog, or any error inside this loop.
    """
    old = {number: signal.signal(number, _interrupted) for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
    memory = sampler.MemorySamples(sampler)
    peak = physical_peak = 0.0
    started = time.monotonic()
    process = None
    try:
        process = sampler.start_owned(command)
        while process.poll() is None:
            observed = memory.sample(process.pid)
            rss, physical = (value / 2**30 for value in observed) if observed else (0.0, 0.0)
            peak, physical_peak = max(peak, rss), max(physical_peak, physical)
            free_disk = shutil.disk_usage(disk_root).free / 2**30
            if timeline is not None:
                timeline.write(json.dumps(dict(seconds=round(time.monotonic() - started, 3), rss_gb=round(rss, 3),
                    physical_gb=round(physical, 3), free_disk_gb=round(free_disk, 1))) + '\n')
                timeline.flush()
            reason = None
            if max(rss, physical) > rss_gb:
                reason = f'process tree RSS {rss:.1f} GiB / physical {physical:.1f} GiB over the {rss_gb} GiB limit'
            elif free_disk < min_disk_gb:
                reason = f'free disk under {min_disk_gb} GiB'
            else:
                available = available_gb()
                if available is not None and available < min_available_gb:
                    reason = f'machine memory available {available:.1f} GiB under {min_available_gb} GiB'
            if reason:
                return STOPPED, peak, physical_peak, reason, time.monotonic() - started
            time.sleep(interval)
        return process.returncode, peak, physical_peak, None, time.monotonic() - started
    except Exception as error:  # Interrupted included: the finally stops the job
        return STOPPED, peak, physical_peak, f'{type(error).__name__}: {error}', time.monotonic() - started
    finally:
        if process is not None:
            sampler.stop_owned(process)
        for number, handler in old.items():
            signal.signal(number, handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--rss-gb', type=float, required=True, help='Stop the job above this process-tree RSS')
    parser.add_argument('--report', type=Path, help='Write command, limit, peak, seconds and outcome as JSON')
    parser.add_argument('--lock', type=Path, help='Directory lock serializing jobs on a shared machine')
    parser.add_argument('--wait-seconds', type=int, default=3600)
    parser.add_argument('--min-available-gb', type=float, default=4.0, help='Stop if the machine falls below this')
    parser.add_argument('--start-available-gb', type=float, default=0.0, help='Refuse to start below this much available memory')
    parser.add_argument('--timeline', action='store_true', help='Write one JSON line per sample next to --report')
    parser.add_argument('--min-disk-gb', type=float, default=15.0, help='Stop if free disk falls below this')
    parser.add_argument('--interval', type=float, default=1.0)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('a command is required')
    if args.timeline and not args.report:
        parser.error('--timeline needs --report')
    if args.report:
        try:
            args.report.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            print(f'archive_watchdog: cannot create the report directory: {error}', file=sys.stderr)
            return REFUSED
    if args.lock and not acquire(args.lock, args.wait_seconds):
        print('archive_watchdog: timed out waiting for the one job slot', file=sys.stderr)
        return REFUSED
    timeline = None
    try:
        available = available_gb()
        if available is not None and available < args.start_available_gb:
            print(f'archive_watchdog: refused to start; machine memory available {available:.1f} GiB '
                  f'under {args.start_available_gb} GiB', file=sys.stderr)
            return REFUSED
        if args.timeline:
            timeline = args.report.with_suffix('.timeline.jsonl').open('w')
        code, peak, physical_peak, reason, seconds = watch(command, rss_gb=args.rss_gb,
            min_available_gb=args.min_available_gb, min_disk_gb=args.min_disk_gb,
            disk_root=args.report.parent if args.report else Path.cwd(), interval=args.interval, timeline=timeline)
    finally:
        if timeline is not None:
            timeline.close()
        if args.lock:
            (args.lock / 'owner').unlink(missing_ok=True)
            args.lock.rmdir()
    if args.report:
        args.report.write_text(json.dumps(dict(command=command, rss_limit_gb=args.rss_gb, peak_rss_gb=round(peak, 3),
            peak_physical_gb=round(physical_peak, 3), seconds=round(seconds, 1), exit_code=code, stopped=reason),
            indent=1) + '\n')
    if reason:
        print(f'archive_watchdog: stopped; {reason}; peak {peak:.2f} GiB RSS, {physical_peak:.2f} GiB physical', file=sys.stderr)
    else:
        print(f'archive_watchdog: finished rc={code}; peak {peak:.2f} GiB RSS, {physical_peak:.2f} GiB physical '
              f'in {seconds:.0f} s', file=sys.stderr)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
