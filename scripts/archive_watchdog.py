#!/usr/bin/env python3
"""Run one heavy job when measured free memory admits it, under a process-tree limit, and record its peak.

Engine pool settings do not bound process RSS: one expression reached 20.4 GiB at a
1 GiB pool, and an out-of-memory crash took down a 48 GB machine. A runaway stops with
exit 99 and a named failure on stderr; the limit is high on purpose, not a target.

    python3 scripts/archive_watchdog.py --rss-gb 40 --expect-gb 6 --start-available-gb 6 \
        --report peak.json -- <command> [args...]

Admission reads measured free memory, never declared limits: a kill limit is a runaway
bound and ran 5-10x real use, so a budget of declared limits (the 2026-11-02 session
guard) queued 15 jobs and held one 27 minutes beside 25 GiB free. A job starts once
free memory covers its --expect-gb (a measured peak from an earlier report) plus
--start-available-gb, beside what is promised but not yet visible: the expected peak of
jobs that started under two minutes ago, and of the earliest waiter ahead of it that
can fit (or would fit once bypassing jobs drain), which smaller jobs may backfill beside
without starving behind an unfittable head. Jobs share that state under --state (default
<main checkout>/.cache/watchdog). Below --min-available-gb only the youngest running
job stops, so one squeeze does not kill every job. Hosted runners, which run one job,
pass neither. Standard library only, so it can run before any environment is set up.
Sampling is once a second by default, so an allocation faster than --interval can pass
the limit before the stop; the machine-floor check covers what other processes use too.

The job runs under the shared owned-process trampoline (scripts/measure/process_rss.py):
TERM/INT/HUP to the watchdog stop the job, and if the watchdog itself is killed the
job's group leader notices and kills the group. --timeline writes one JSON line per
sample (seconds, RSS, physical, free disk, and the wall-clock epoch at which the reading
ended with how long it took) to <report>.timeline.jsonl; scripts/measure/step_memory.py
joins that to the engine's step log.
"""
import argparse
from contextlib import contextmanager
import fcntl
import functools
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

STOPPED = 99
REFUSED = 98
RAMP_SECONDS = 120
# How long this file waits for vm_stat or ps to answer: the limit the sampler gives its own ps calls.
READER_SECONDS = 5
HERE = Path(__file__).resolve().parent


def _load(name, path):
    """Shared stdlib modules, loaded by path like the capture monitor does."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sampler = _load('archive_watchdog_sampler', HERE / 'measure/process_rss.py')
SignalRecorder = sampler.SignalRecorder
WAKE_SECONDS = sampler.WAKE_SECONDS


class ReadingFailed(Exception):
    """`vm_stat: TimeoutExpired`: a reader died, did not answer in READER_SECONDS or answered nonsense.

    No reading is not a reading. Admission skips a round on it and the loop a pass; nothing else
    that goes wrong there, the registry's files or the arithmetic, is ever taken for one.
    """


def reads(reader):
    """Mark a function that asks `reader`: whatever fails inside it leaves as ReadingFailed."""
    def marked(ask):
        @functools.wraps(ask)
        def asking(*args):
            try:
                return ask(*args)
            except (OSError, subprocess.SubprocessError, LookupError, ValueError) as error:
                raise ReadingFailed(f'{reader}: {type(error).__name__}') from error
        return asking
    return marked


@reads('vm_stat' if sys.platform == 'darwin' else '/proc/meminfo')
def available_gb():
    """Memory the machine can still hand out, or None where that is not knowable."""
    if sys.platform == 'darwin':
        text = subprocess.run(['vm_stat'], capture_output=True, text=True, check=True, timeout=READER_SECONDS).stdout
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


def admissible(me, entries, *, available, headroom, now):
    """Whether `me` fits in measured free memory beside what is promised but not yet visible.

    An earlier waiter reserves its expected peak once free memory (or draining jobs that
    bypassed it) covers its need, or once earlier running jobs have finished and it has
    waited RAMP_SECONDS for bypassers to drain; an unfittable waiter never blocks fitting
    jobs indefinitely (ct-j2qx).
    """
    others = [entry for entry in entries if entry['pid'] != me['pid']]
    ramping = sum(entry['expect_gb'] for entry in others
                  if entry['admitted'] is not None and now - entry['admitted'] < RAMP_SECONDS)
    ahead = sorted((entry for entry in others
                    if entry['admitted'] is None and (entry['queued'], entry['pid']) < (me['queued'], me['pid'])),
                   key=lambda entry: (entry['queued'], entry['pid']))
    head = 0.0
    for waiter in ahead:
        need = waiter['expect_gb'] + headroom
        older = [entry for entry in others
                 if entry['admitted'] is not None and entry['admitted'] < waiter['queued']]
        bypass = [entry for entry in others
                  if entry['admitted'] is not None and entry['admitted'] >= waiter['queued']]
        older_ramping = sum(entry['expect_gb'] for entry in older if now - entry['admitted'] < RAMP_SECONDS)
        bypass_settled = sum(entry['expect_gb'] for entry in bypass if now - entry['admitted'] >= RAMP_SECONDS)
        bypass_ceiling = sum(max(entry['expect_gb'], entry.get('rss_gb', entry['expect_gb'])) for entry in bypass)
        without_bypass = available - older_ramping + bypass_settled
        draining_bypass = (
            not older and bool(bypass) and now - waiter['queued'] >= RAMP_SECONDS
            and available + bypass_ceiling >= need
        )
        if without_bypass >= need or draining_bypass:
            head = waiter['expect_gb']
            break
    return available - ramping - head >= me['expect_gb'] + headroom


def floor_victim(entries):
    """The youngest running job stops first when the machine runs short: it loses the least work."""
    running = [entry for entry in entries if entry['admitted'] is not None]
    return max(running, key=lambda entry: (entry['admitted'], entry['pid']))['pid'] if running else None


@reads('ps')
def start_times(pids):
    """Each live process's start time as ps prints it; a PID absent from the result is dead.

    A PID alone is not an identity: once a watchdog dies its number can name another
    process, so an entry counts only while its PID still has the start time it recorded.
    A ps that died is a failed reading: read as "none of them is alive", it would have
    every entry in the registry deleted.
    """
    if not pids:
        return {}
    listed = subprocess.run(['ps', '-o', 'pid=,lstart=', '-p', ','.join(map(str, pids))],
                            capture_output=True, text=True, timeout=READER_SECONDS)
    if listed.returncode not in (0, 1):  # 1 is its answer when none of the PIDs exists
        raise subprocess.CalledProcessError(listed.returncode, listed.args, listed.stdout, listed.stderr)
    return {int(row.split(None, 1)[0]): ' '.join(row.split()[1:]) for row in listed.stdout.splitlines() if row.strip()}


class Registry:
    """One JSON file per waiting or running job, read and decided under one file lock."""

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def locked(self):
        with (self.root / '.lock').open('a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield self.live()

    def live(self):
        found = {}
        for path in self.root.glob('*.json'):
            try:
                found[path] = json.loads(path.read_text())
            except (OSError, ValueError):
                path.unlink(missing_ok=True)
        started = start_times([entry['pid'] for entry in found.values() if isinstance(entry.get('pid'), int)])
        entries = []
        for path, entry in found.items():
            if entry.get('started') is not None and started.get(entry.get('pid')) == entry['started']:
                entries.append(entry)
            else:
                path.unlink(missing_ok=True)  # Its watchdog died; the PID may now name another process.
        return entries

    def put(self, entry):
        staged = self.root / f'.{entry["pid"]}.tmp'
        staged.write_text(json.dumps(entry))
        staged.replace(self.root / f'{entry["pid"]}.json')

    def drop(self, pid):
        (self.root / f'{pid}.json').unlink(missing_ok=True)


def default_state():
    """<main checkout>/.cache/watchdog, shared by every worktree; this checkout's .cache without git."""
    if location := os.environ.get('ARCHIVE_WATCHDOG_STATE'):
        return Path(location)
    try:
        return _load('archive_watchdog_dev', HERE / 'dev.py').shared_cache() / 'watchdog'
    except (OSError, subprocess.SubprocessError):
        return HERE.parent / '.cache/watchdog'


def total_gb():
    """Physical memory of this machine."""
    return os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES') / 2**30


def admit(registry, me, *, headroom, wait_seconds):
    """Wait for room; return None once admitted, else why the job was not started.

    A reading that fails (vm_stat or ps slow, dead or unreadable) means no room is known yet,
    not that the watchdog must end: the round is tried again at the next tick, and a job whose
    readings still fail at the deadline is refused like any other. `me` gets its start time
    here, by the first ps that answers.
    """
    total = total_gb()
    if me['expect_gb'] + headroom > total:
        return (f'{me["expect_gb"]} GiB expected plus {headroom} GiB left free exceeds this machine '
                f'({total:.0f} GiB); refused to start')
    deadline = time.monotonic() + wait_seconds
    failed = {}
    while True:
        try:
            if me['started'] is None:
                me['started'] = start_times([me['pid']])[me['pid']]
            with registry.locked() as entries:
                available = available_gb()
                if available is None or admissible(me, entries, available=available, headroom=headroom, now=time.time()):
                    registry.put({**me, 'admitted': time.time()})
                    return None
                registry.put(me)
            refusal = (f'refused to start; measured free memory {available:.1f} GiB, less what started jobs and earlier '
                       f'waiters still need, did not cover {me["expect_gb"]} GiB plus {headroom} GiB')
        except ReadingFailed as error:  # only that: a registry or arithmetic error shows at once, as it always did
            failed[str(error)] = failed.get(str(error), 0) + 1
            refusal = 'refused to start; free memory could not be read: ' + ', '.join(
                f'{what} {count} {"time" if count == 1 else "times"}' for what, count in failed.items())
        if time.monotonic() >= deadline:
            return refusal
        time.sleep(2)


def watch(command, *, rss_gb, min_available_gb, min_disk_gb, disk_root, interval, timeline=None,
          youngest=lambda: True, hold_fd=None):
    """Return (exit code, peak resident GiB, peak physical GiB, reason, seconds).

    The limit applies to max(resident, physical): macOS charged footprint also counts
    compressed memory that RSS misses. Below the machine floor the job stops only when
    youngest() says it is the youngest running job. The owned group is always stopped
    on the way out: a breach, a signal to the watchdog, or any error inside this loop.

    The handler only records the signal; the loop reads the record between passes and
    every WAKE_SECONDS of its wait, so the stop begins that soon after a signal, or when
    the pass the signal landed in ends. A handler that raises does so at
    whatever instruction the main thread has reached, and inside the interpreter's own
    timed wait for a child that left the child's lock held: the next wait on it never
    returned, so the watchdog hung with its job running and no report (ct-psb5). A
    signal during the stop itself is recorded and changes nothing.
    """
    with SignalRecorder(clock=time, wake_seconds=WAKE_SECONDS) as signals:
        def signalled():
            return f'Interrupted: watchdog received signal {signals.first}' if signals.received else None

        memory = sampler.MemorySamples(sampler)
        blind = 0  # passes in a row without a free-memory reading
        peak = physical_peak = 0.0
        started = time.monotonic()
        process = None
        try:
            # The owned group holds this descriptor until parent-death cleanup ends.
            pass_fds = () if hold_fd is None else (hold_fd,)
            process = sampler.start_owned(command, pass_fds=pass_fds)
            while process.poll() is None:
                reading = time.monotonic()
                observed = memory.sample(process.pid)
                rss, physical = (value / 2**30 for value in observed) if observed else (0.0, 0.0)
                peak, physical_peak = max(peak, rss), max(physical_peak, physical)
                free_disk = shutil.disk_usage(disk_root).free / 2**30
                if timeline is not None:
                    now = time.monotonic()
                    timeline.write(json.dumps(dict(seconds=round(now - started, 3), epoch=round(time.time(), 3),
                        read_seconds=round(now - reading, 3), rss_gb=round(rss, 3), physical_gb=round(physical, 3),
                        free_disk_gb=round(free_disk, 1))) + '\n')
                    timeline.flush()
                reason = None
                if max(rss, physical) > rss_gb:
                    reason = f'process tree RSS {rss:.1f} GiB / physical {physical:.1f} GiB over the {rss_gb} GiB limit'
                elif free_disk < min_disk_gb:
                    reason = f'free disk under {min_disk_gb} GiB'
                else:
                    try:
                        available = available_gb()
                        squeezed = available is not None and available < min_available_gb and youngest()
                        blind = 0
                    except ReadingFailed as error:
                        # A gap for this pass, as sampler.MemorySamples treats a failed sample; the third in a row stops the job.
                        blind += 1
                        if blind >= 3:
                            raise RuntimeError(f'Three consecutive readings of free memory failed, the last {error}') from error
                        squeezed = False
                    if squeezed:
                        reason = (f'machine memory available {available:.1f} GiB under {min_available_gb} GiB; '
                                  'the youngest running job stops first')
                if reason:
                    return STOPPED, peak, physical_peak, reason, time.monotonic() - started
                if signals.sleep(interval):
                    return STOPPED, peak, physical_peak, signalled(), time.monotonic() - started
            return process.returncode, peak, physical_peak, None, time.monotonic() - started
        except Exception as error:  # the finally stops the job
            # A signal to the whole group also kills the reader this pass had running; the signal is the reason.
            return STOPPED, peak, physical_peak, signalled() or f'{type(error).__name__}: {error}', time.monotonic() - started
        finally:
            if process is not None:
                sampler.stop_owned(process)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--rss-gb', type=float, required=True, help='Stop the job above this process-tree RSS')
    parser.add_argument('--report', type=Path, help='Write command, limit, peak, seconds and outcome as JSON')
    parser.add_argument('--expect-gb', type=float, default=0.0, help='Measured peak the job needs to start')
    parser.add_argument('--start-available-gb', type=float, default=0.0,
                        help='Free memory that must remain beside the expected peak before the job starts')
    parser.add_argument('--wait-seconds', type=int, default=3600, help='Refuse after waiting this long to start')
    parser.add_argument('--state', type=Path, help='Admission state shared by jobs (default: <main checkout>/.cache/watchdog)')
    parser.add_argument('--min-available-gb', type=float, default=4.0,
                        help='Stop the youngest running job if the machine falls below this')
    parser.add_argument('--timeline', action='store_true', help='Write one JSON line per sample next to --report')
    parser.add_argument('--min-disk-gb', type=float, default=15.0, help='Stop if free disk falls below this')
    parser.add_argument('--interval', type=float, default=1.0)
    parser.add_argument('--hold-fd', type=int, help=argparse.SUPPRESS)
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
    registry = Registry(args.state or default_state())
    me = dict(pid=os.getpid(), started=None, queued=time.time(), admitted=None,  # admit() reads the start time
              expect_gb=args.expect_gb, rss_gb=args.rss_gb, command=command[:8])

    def youngest():
        with registry.locked() as entries:
            return floor_victim(entries) == me['pid']

    timeline = None
    began = time.monotonic()
    try:
        if refused := admit(registry, me, headroom=args.start_available_gb, wait_seconds=args.wait_seconds):
            print(f'archive_watchdog: {refused}', file=sys.stderr)
            return REFUSED
        waited = time.monotonic() - began
        if args.timeline:
            timeline = args.report.with_suffix('.timeline.jsonl').open('w')
        code, peak, physical_peak, reason, seconds = watch(command, rss_gb=args.rss_gb,
            min_available_gb=args.min_available_gb, min_disk_gb=args.min_disk_gb,
            disk_root=args.report.parent if args.report else Path.cwd(), interval=args.interval, timeline=timeline,
            youngest=youngest, hold_fd=args.hold_fd)
    finally:
        if timeline is not None:
            timeline.close()
        registry.drop(me['pid'])
    if args.report:
        args.report.write_text(json.dumps(dict(command=command, rss_limit_gb=args.rss_gb, expect_gb=args.expect_gb,
            peak_rss_gb=round(peak, 3), peak_physical_gb=round(physical_peak, 3), waited_seconds=round(waited, 1),
            seconds=round(seconds, 1), exit_code=code, stopped=reason), indent=1) + '\n')
    if reason:
        print(f'archive_watchdog: stopped; {reason}; peak {peak:.2f} GiB RSS, {physical_peak:.2f} GiB physical', file=sys.stderr)
    else:
        print(f'archive_watchdog: finished rc={code}; peak {peak:.2f} GiB RSS, {physical_peak:.2f} GiB physical '
              f'in {seconds:.0f} s after {waited:.0f} s waiting', file=sys.stderr)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
