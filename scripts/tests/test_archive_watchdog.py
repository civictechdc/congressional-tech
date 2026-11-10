"""The watchdog admits on measured free memory, stops a real runaway by its real RSS, kills descendants,
and records the peak."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).parents[2]
WATCHDOG = ROOT / 'scripts/archive_watchdog.py'
SPEC = importlib.util.spec_from_file_location('archive_watchdog_contract', WATCHDOG)
watchdog = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watchdog)


STARTED = []
# Each one the watchdog handles; left at its default, any of them would end it with no report.
SIGNALS = pytest.mark.parametrize('number', [signal.SIGTERM, signal.SIGINT, signal.SIGHUP], ids=lambda number: number.name)


@pytest.fixture(autouse=True)
def private_state(tmp_path, monkeypatch):
    """Every watchdog these tests start shares a private admission state, never the machine's."""
    monkeypatch.setenv('ARCHIVE_WATCHDOG_STATE', str(tmp_path / 'state'))
    return tmp_path / 'state'


@pytest.fixture(autouse=True)
def no_watchdog_outlives_its_test():
    """A failing test used to leave its watchdog running: one hung on a signal and was found two and a half hours
    later (ct-psb5). Killed, a watchdog's job goes with it: the owned group's leader sees its starter die."""
    yield
    while STARTED:
        reap(STARTED.pop())


def reap(process, seconds=15):
    """Kill a started process and collect it without ever waiting longer than `seconds`: its pipes stay open for
    as long as any descendant holds them, so an unbounded read here could hang the whole test run."""
    if process.poll() is None:
        process.kill()
    try:
        process.communicate(timeout=seconds)
    except subprocess.TimeoutExpired:
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        process.wait(timeout=seconds)
HOLD = "import time\nb=bytearray({size}*1024*1024)\nfor i in range(0,len(b),4096):b[i]=1\ntime.sleep(60)\n"


def run(tmp_path, *flags, command):
    return subprocess.run([sys.executable, str(WATCHDOG), '--min-disk-gb', '0', '--min-available-gb', '0', '--interval', '0.1',
        '--report', str(tmp_path / 'report.json'), *flags, '--', *command], capture_output=True, text=True, timeout=120)


def test_teardown_does_not_wait_on_pipes_a_descendant_still_holds(tmp_path):
    marker = tmp_path / 'grandchild.pid'
    parent = (f"import subprocess,sys,time\nsubprocess.Popen([sys.executable,'-c',{sleeper(marker)!r}])\ntime.sleep(60)\n")
    process = subprocess.Popen([sys.executable, '-c', parent], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    grandchild = wait_for(marker)
    try:
        began = time.monotonic()
        reap(process, seconds=0.5)
        assert process.returncode == -9 and time.monotonic() - began < 20, 'teardown waited for the grandchild'
    finally:
        os.kill(grandchild, 9)


def test_a_clean_job_keeps_its_exit_code_and_records_a_peak(tmp_path):
    result = run(tmp_path, '--rss-gb', '4', command=[sys.executable, '-c', 'import sys,time;time.sleep(0.5);sys.exit(7)'])
    report = json.loads((tmp_path / 'report.json').read_text())
    assert result.returncode == 7 and report['exit_code'] == 7 and report['stopped'] is None
    assert 0 < report['peak_rss_gb'] < 4


def test_a_runaway_descendant_stops_the_tree_with_a_named_failure(tmp_path):
    marker = tmp_path / 'child.pid'
    child = f"import os,pathlib;pathlib.Path({str(marker)!r}).write_text(str(os.getpid()))\n" + HOLD.format(size=400)
    parent = f"import subprocess,sys;subprocess.run([sys.executable,'-c',{child!r}])"
    started = time.monotonic()
    result = run(tmp_path, '--rss-gb', '0.2', command=[sys.executable, '-c', parent])
    assert result.returncode == 99 and time.monotonic() - started < 30
    assert 'RSS' in result.stderr and 'over the 0.2 GiB limit' in result.stderr
    report = json.loads((tmp_path / 'report.json').read_text())
    assert report['exit_code'] == 99 and 'RSS' in report['stopped']
    assert max(report['peak_rss_gb'], report['peak_physical_gb']) > 0.2
    pid = int(marker.read_text())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    raise AssertionError('the runaway child outlived the watchdog')


@pytest.mark.parametrize('total, free', [(16, 14.2), (48, 30.0)], ids=['16-GiB-runner', '48-GiB-mac'])
def test_admission_is_refused_on_measured_free_memory_with_a_named_reason(monkeypatch, capsys, tmp_path,
                                                                           private_state, total, free):
    """A job that cannot fit waits, then refuses with exit 98; it never starts and leaves no state.

    The readings are injected: derived from the real host, the expected peak exceeded a
    16 GiB Linux runner outright and took the other refusal (docspec-rs run 41506139189).
    """
    monkeypatch.setattr(watchdog, 'total_gb', lambda: total)
    monkeypatch.setattr(watchdog, 'available_gb', lambda: free)
    marker = tmp_path / 'ran'
    code = watchdog.main(['--rss-gb', '4', '--expect-gb', str(free + 1), '--wait-seconds', '0', '--',
                          sys.executable, '-c', f'import pathlib;pathlib.Path({str(marker)!r}).touch()'])
    assert code == 98 and 'measured free memory' in capsys.readouterr().err and not marker.exists()
    assert list(private_state.glob('*.json')) == []
    assert watchdog.main(['--rss-gb', '4', '--expect-gb', str(total + 1), '--wait-seconds', '0', '--', 'true']) == 98
    assert 'exceeds this machine' in capsys.readouterr().err


def test_admission_waits_out_a_reader_that_fails_and_refuses_by_name_if_it_never_answers(monkeypatch, capsys, tmp_path,
                                                                                         private_state):
    """A reader past its time limit means no room is known yet, not that the watchdog must die: one slow `vm_stat`
    or `ps` used to be waited out, and on a loaded machine the unattended nightly must still start."""
    import types

    clock, naps = [0.0], []
    monkeypatch.setattr(watchdog, 'time', types.SimpleNamespace(
        monotonic=lambda: clock[0], time=time.time, sleep=lambda seconds: (naps.append(seconds), clock.__setitem__(0, clock[0] + seconds))))
    real_start_times = watchdog.start_times

    def failing(reader, times, answer):
        calls = []

        def read(*args):
            calls.append(1)
            if len(calls) <= times:
                raise watchdog.ReadingFailed(f'{reader}: TimeoutExpired')
            return answer(*args)
        return read

    def admission(*, wait_seconds, free=lambda: 30.0, processes=real_start_times):
        registry = watchdog.Registry(private_state)
        me = dict(pid=os.getpid(), started=None, queued=time.time(), admitted=None, expect_gb=1.0, command=['job'])
        monkeypatch.setattr(watchdog, 'available_gb', free)
        monkeypatch.setattr(watchdog, 'start_times', processes)
        del naps[:]
        try:
            return watchdog.admit(registry, me, headroom=1.0, wait_seconds=wait_seconds), list(naps), registry.live()
        finally:
            registry.drop(os.getpid())

    refused, waits, entries = admission(wait_seconds=60)
    assert (refused, waits) == (None, []), 'a healthy machine admits at once'
    assert [(e['pid'], e['started'], e['admitted'] is not None) for e in entries] == [
        (os.getpid(), real_start_times([os.getpid()])[os.getpid()], True)]
    for slow in (dict(free=failing('vm_stat', 1, lambda: 30.0)), dict(processes=failing('ps', 1, real_start_times))):
        refused, waits, entries = admission(wait_seconds=60, **slow)
        assert (refused, waits, len(entries)) == (None, [2], 1), 'one slow reader, then the job is admitted at the next tick'
    refused, waits, entries = admission(wait_seconds=5, free=failing('vm_stat', 99, None))
    assert waits == [2, 2, 2] and entries == [], 'it tries at every tick until the deadline'
    assert 'refused to start' in refused and 'vm_stat: TimeoutExpired 4 times' in refused
    # Through main(): the refusal code and one line, no traceback, nothing left behind.
    monkeypatch.setattr(watchdog, 'available_gb', failing('vm_stat', 99, None))
    monkeypatch.setattr(watchdog, 'start_times', real_start_times)
    marker = tmp_path / 'ran'
    code = watchdog.main(['--rss-gb', '4', '--expect-gb', '1', '--wait-seconds', '0', '--',
                          sys.executable, '-c', f'import pathlib;pathlib.Path({str(marker)!r}).touch()'])
    printed = capsys.readouterr().err
    assert code == 98 and 'vm_stat: TimeoutExpired 1 time' in printed and printed.count('\n') == 1
    assert not marker.exists() and list(private_state.glob('*.json')) == []


def test_only_a_reader_that_fails_is_waited_out_in_admission_the_registry_and_the_arithmetic_fail_at_once(monkeypatch, tmp_path,
                                                                                                           private_state):
    """As on main: an unwritable state folder or a malformed entry is an error to show now, not an hour of retries
    ending in a refusal that blames the free-memory reader."""
    import types

    registry = watchdog.Registry(private_state)
    me = dict(pid=os.getpid(), started=None, queued=time.time(), admitted=None, expect_gb=1.0, command=['job'])
    other = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(60)'])
    try:
        with monkeypatch.context() as patched:  # undone before the real watchdog below, which needs the real ones
            patched.setattr(watchdog, 'available_gb', lambda: 30.0)
            # A stand-in for the watchdog's own `time`, never the real module: the interpreter's wait for a `ps`
            # sleeps through that one too (subprocess.py:2046), and a patch there would fail this test falsely.
            patched.setattr(watchdog, 'time', types.SimpleNamespace(monotonic=time.monotonic, time=time.time, sleep=lambda seconds: (
                pytest.fail('admission waited on an error that is not a reading'))))
            with monkeypatch.context() as unwritable:
                unwritable.setattr(registry, 'put', lambda entry: (_ for _ in ()).throw(PermissionError(13, 'Permission denied')))
                with pytest.raises(PermissionError):
                    watchdog.admit(registry, dict(me), headroom=1.0, wait_seconds=60)
            # Another session's entry with no expect_gb: admissible() cannot add it up.
            registry.put(dict(pid=other.pid, started=watchdog.start_times([other.pid])[other.pid], queued=0, admitted=time.time()))
            with pytest.raises(KeyError):
                watchdog.admit(registry, dict(me), headroom=1.0, wait_seconds=60)
    finally:
        other.kill()
        other.wait()
        registry.drop(other.pid)
    if os.geteuid() == 0:
        return  # root writes where it likes: there is no unwritable folder to try
    private_state.chmod(0o500)
    try:
        result = run(tmp_path, '--rss-gb', '4', '--wait-seconds', '4', command=[sys.executable, '-c', 'pass'])
    finally:
        private_state.chmod(0o700)
    assert result.returncode == 1 and 'PermissionError' in result.stderr and 'refused to start' not in result.stderr


def test_a_high_kill_limit_does_not_delay_a_small_job(tmp_path):
    """The kill limit bounds a runaway; it is not the job's need (declared limits ran 5-10x real use)."""
    result = run(tmp_path, '--rss-gb', '100000', '--expect-gb', '0.1', '--wait-seconds', '0',
                 command=[sys.executable, '-c', 'pass'])
    assert result.returncode == 0, result.stderr


def entry(pid, queued, expect, admitted=None):
    return dict(pid=pid, queued=queued, admitted=admitted, expect_gb=expect, command=[])


def test_admission_counts_measured_memory_plus_only_promises_not_yet_visible():
    now = 10_000.0
    me = entry(9, now - 1, 4)
    # A job past its ramp is already inside measured free memory: it reserves nothing more.
    settled = entry(1, now - 900, 20, admitted=now - 800)
    assert watchdog.admissible(me, [me, settled], available=10, headroom=6, now=now)
    # A job still ramping reserves its expected peak, which measured memory cannot show yet.
    ramping = entry(2, now - 30, 3, admitted=now - 20)
    assert not watchdog.admissible(me, [me, ramping], available=10, headroom=6, now=now)
    assert watchdog.admissible(me, [me, ramping], available=13, headroom=6, now=now)


def test_the_oldest_waiter_is_reserved_and_smaller_jobs_backfill_beside_it():
    now = 10_000.0
    head, small = entry(1, now - 600, 20), entry(2, now - 10, 2)
    assert not watchdog.admissible(head, [head, small], available=25, headroom=6, now=now)
    assert not watchdog.admissible(small, [head, small], available=25, headroom=6, now=now)  # Would take the head's room.
    assert watchdog.admissible(small, [head, small], available=29, headroom=6, now=now)
    assert watchdog.admissible(head, [head, small], available=26, headroom=6, now=now)


def test_below_the_machine_floor_the_youngest_running_job_stops_first(tmp_path, private_state):
    """One squeeze stops one job, the one with the least work to lose, not every job at once."""
    assert watchdog.floor_victim([entry(1, 0, 4, admitted=100), entry(2, 0, 4, admitted=300), entry(3, 400, 4)]) == 2
    assert watchdog.floor_victim([entry(3, 400, 4)]) is None
    younger = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(60)'])
    try:
        private_state.mkdir()
        (private_state / f'{younger.pid}.json').write_text(json.dumps(dict(entry(younger.pid, time.time(), 1,
            admitted=time.time() + 3600), started=watchdog.start_times([younger.pid])[younger.pid])))
        always_short = ['--rss-gb', '4', '--min-available-gb', '1000000']
        older = run(tmp_path, *always_short, command=[sys.executable, '-c', 'import time;time.sleep(1)'])
        assert older.returncode == 0, older.stderr  # A younger job is running, so this one is kept.
    finally:
        younger.kill()
        younger.wait()
    alone = run(tmp_path, *always_short, command=[sys.executable, '-c', 'import time;time.sleep(60)'])
    assert alone.returncode == 99 and 'youngest running job stops first' in alone.stderr


def test_a_floor_breach_stops_the_job(tmp_path):
    result = subprocess.run([sys.executable, str(WATCHDOG), '--rss-gb', '4', '--min-disk-gb', '1000000', '--interval', '0.1', '--',
        sys.executable, '-c', 'import time;time.sleep(60)'], capture_output=True, text=True, timeout=60, cwd=tmp_path)
    assert result.returncode == 99 and 'free disk' in result.stderr


def gone(pid, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.1)
    return False


def wait_for(path, seconds=20):
    deadline = time.monotonic() + seconds
    while not (path.exists() and path.read_text()):
        assert time.monotonic() < deadline, f'{path.name} never appeared'
        time.sleep(0.05)
    return int(path.read_text())


def sleeper(marker, *, ignore_term=False):
    head = 'import signal;signal.signal(signal.SIGTERM,signal.SIG_IGN)\n' if ignore_term else ''
    return head + f"import os,pathlib,time;pathlib.Path({str(marker)!r}).write_text(str(os.getpid()));time.sleep(60)"


def start(tmp_path, command, *flags, pass_fds=(), plant=(), own_group=False):
    process = subprocess.Popen([sys.executable, *(('-c', PLANT, *plant) if plant else ()), str(WATCHDOG),
        '--rss-gb', '4', '--min-disk-gb', '0', '--min-available-gb', '0',
        '--interval', '0.1', '--report', str(tmp_path / 'report.json'), *flags, '--', *command],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, pass_fds=pass_fds, start_new_session=own_group)
    STARTED.append(process)
    return process


@SIGNALS
def test_a_signal_to_the_watchdog_stops_the_job(tmp_path, number):
    marker = tmp_path / 'job.pid'
    watchdog = start(tmp_path, [sys.executable, '-c', sleeper(marker)])
    pid = wait_for(marker)
    watchdog.send_signal(number)
    _, stderr = watchdog.communicate(timeout=30)
    assert gone(pid), 'the job outlived a TERM to its watchdog'
    report = json.loads((tmp_path / 'report.json').read_text())
    assert watchdog.returncode == 99 and 'signal' in report['stopped'] and 'signal' in stderr


def test_a_signal_during_a_long_wait_between_passes_stops_the_job_long_before_the_wait_would_end(tmp_path):
    """The same bound on a real clock and a real signal, loosely: the job's marker appears while the watchdog is in
    its first ten-second wait, and a sleep that ran to its end would hold the stop for the rest of it."""
    marker = tmp_path / 'job.pid'
    watchdog = start(tmp_path, [sys.executable, '-c', sleeper(marker)], '--interval', '10')
    pid = wait_for(marker)
    watchdog.terminate()
    watchdog.communicate(timeout=30)
    report = json.loads((tmp_path / 'report.json').read_text())
    assert gone(pid) and watchdog.returncode == 99 and 'signal 15' in report['stopped']
    assert report['seconds'] < 5, 'the stop waited for the ten-second sleep to end'


# A watchdog made to receive a signal at one chosen instruction. Popen._wait(timeout) and Popen._internal_poll take
# the child's _waitpid_lock with acquire(False) and only afterwards enter their try (CPython 3.12 subprocess.py:2032
# and :1983; 3.15 has the same shape), so an exception a signal handler raises right there leaves the lock held, and
# the next blocking wait on that child never returns. This stand-in lock sends the signal from inside that acquire:
# `sampler` in the first timed wait for a `ps` once the job runs, `cleanup` in the poll that opens stop_owned.
# `group` is the other way a signal arrives, a Ctrl-C or a stop aimed at the whole process group: it is sent to
# the watchdog's group as soon as the free-memory reader has started, so that reader dies of it as well.
PLANT = r'''
import importlib.util, os, pathlib, signal, subprocess, sys
site, number, marker, fired, script = sys.argv[1:6]

def due(child):
    if os.path.exists(fired):
        return False
    if site == 'sampler':
        return child.args[0] == 'ps' and os.path.exists(marker)
    frame = sys._getframe(2)
    while frame is not None and frame.f_code.co_name != '_cleanup_child':
        frame = frame.f_back
    return frame is not None

class Signalling:
    def __init__(self, child, lock):
        self.child, self.lock = child, lock
    def acquire(self, blocking=True, timeout=-1):
        held = self.lock.acquire(blocking, timeout)
        if held and not blocking and due(self.child):
            self.child._waitpid_lock = self.lock
            pathlib.Path(fired).write_text(site)
            os.kill(os.getpid(), int(number))
        return held
    def release(self):
        self.lock.release()
    __enter__ = acquire
    def __exit__(self, *_):
        self.lock.release()

class Planted(subprocess.Popen):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._waitpid_lock = Signalling(self, self._waitpid_lock)
        reader = 'vm_stat' if sys.platform == 'darwin' else 'ps'
        if site == 'group' and self.args[0] == reader and os.path.exists(marker) and not os.path.exists(fired):
            assert os.getpgrp() == os.getpid(), 'this watchdog must lead its own group, or the signal reaches pytest'
            pathlib.Path(fired).write_text(site)
            os.killpg(os.getpgrp(), int(number))

spec = importlib.util.spec_from_file_location('planted_watchdog', script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
subprocess.Popen = Planted
raise SystemExit(module.main(sys.argv[6:]))
'''


@SIGNALS
@pytest.mark.parametrize('site', ['sampler', 'cleanup', 'group'])
def test_a_planted_signal_still_stops_the_job_and_the_report_names_it(tmp_path, private_state, site, number):
    """ct-psb5. `sampler`: the handler used to raise into the sampler's `ps` wait, and the watchdog blocked for ever
    on that child's lock: job not stopped, no report, registry entry kept. `cleanup`: a second signal as the stop
    began used to abort it: exit 1 with a traceback and no report. Recorded and read by the loop, both are harmless.
    `group`: the pass that received the signal also lost its free-memory reader to it, and the report must still
    give the signal as the reason, not the reader's failure. A pass of `group` is not proof of that: the reader can
    finish before the signal reaches it, and then nothing in the pass fails. The proof is the in-process case with a
    failing sampler in test_the_stop_begins_within_a_twentieth_of_a_second_of_the_signal_whatever_the_interval."""
    marker, fired = tmp_path / 'job.pid', tmp_path / 'fired'
    watchdog = start(tmp_path, [sys.executable, '-c', sleeper(marker)], plant=(site, str(int(number)), str(marker), str(fired)),
                     own_group=site == 'group')
    pid = wait_for(marker)
    if site == 'cleanup':
        watchdog.send_signal(number)
    try:
        _, stderr = watchdog.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        pytest.fail(f'the watchdog had not exited 30 s after its signal; planted: {fired.exists()}')
    assert fired.read_text() == site, 'the signal was never planted, so this run proved nothing'
    assert gone(pid), 'the job outlived a TERM to its watchdog'
    assert watchdog.returncode == 99, stderr
    named = f'signal {int(number)}'
    assert named in json.loads((tmp_path / 'report.json').read_text())['stopped'] and named in stderr
    assert list(private_state.glob('*.json')) == [], 'the stopped watchdog left its admission entry behind'


@SIGNALS
@pytest.mark.parametrize('interval', [0.2, 1, 60])
def test_the_stop_begins_within_a_twentieth_of_a_second_of_the_signal_whatever_the_interval(monkeypatch, tmp_path, number,
                                                                                            interval):
    """A sleep resumes after a handler that returns, so one sleep per pass would hold a recorded signal for the rest
    of the interval. Here the signal is the installed handler, called from a stand-in sampler, sleep or stop on a
    clock only the sleep advances, so every case is exact: no real signal, no process, no timing."""
    import types

    def watched(signal_during, *, after=0.0, failing=False, passes=2, free=lambda: None, youngest=lambda: True):
        events, clock, slept, at = [], [0.0], [], {}

        class Job:
            pid, returncode = 1, 7

            def poll(self):
                events.append('poll')
                return None if events.count('poll') <= passes else 7

        def passing(through):
            if events[-1] != through:
                events.append(through)
            at.setdefault(through, clock[0])
            if through == signal_during and clock[0] >= after and 'signal' not in events:
                events.append('signal')
                at['signal'] = clock[0]
                handler = signal.getsignal(number)
                # Never call the handler pytest runs under: for SIGINT that would abort the whole session.
                assert handler is not before[number], 'watch() does not handle this signal'
                handler(int(number), None)

        class Readings:
            def __init__(self, _sampler):
                pass

            def sample(self, _pid):
                passing('sample')
                if failing:
                    raise RuntimeError('the signal took the sampler too')
                return 2**30, 2**30

        def sleep(seconds):
            passing('sleep')  # the signal, when due, lands as this sleep starts; the sleep still runs to its end
            slept.append(seconds)
            clock[0] += seconds

        monkeypatch.setattr(watchdog, 'available_gb', free)
        monkeypatch.setattr(watchdog, 'time', types.SimpleNamespace(monotonic=lambda: clock[0], sleep=sleep))
        monkeypatch.setattr(watchdog, 'sampler', types.SimpleNamespace(
            MemorySamples=Readings, start_owned=lambda command, **_: Job(), stop_owned=lambda _process: passing('stop')))
        before = {each: signal.getsignal(each) for each in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
        try:
            code, _, _, reason, _ = watchdog.watch(['job'], rss_gb=4, min_available_gb=1, min_disk_gb=0,
                                                   disk_root=tmp_path, interval=interval, youngest=youngest)
            assert {each: signal.getsignal(each) for each in before} == before, 'watch() kept its handlers'
        finally:  # a watch() that raises must not leave this pytest process with its handlers
            for each, handler in before.items():
                signal.signal(each, handler)
        return (code, reason, events), at, slept

    stopped = f'Interrupted: watchdog received signal {int(number)}'
    assert watched('sample')[0] == (99, stopped, ['poll', 'sample', 'signal', 'stop']), 'it slept on a signal it already had'
    assert watched('sample', failing=True)[0] == (99, stopped, ['poll', 'sample', 'signal', 'stop']), 'the signal is the reason'
    assert watched(None, failing=True)[0] == (99, 'RuntimeError: the signal took the sampler too', ['poll', 'sample', 'stop'])
    for after in (0.0, interval / 2):  # as the wait begins, and half way through it
        outcome, at, _ = watched('sleep', after=after)
        assert outcome == (99, stopped, ['poll', 'sample', 'sleep', 'signal', 'stop']), 'it sampled again first'
        assert 0 < at['stop'] - at['signal'] <= 0.05 + 1e-9, 'the stop waited out the interval'
    quiet = ['poll', 'sample', 'sleep', 'poll', 'sample', 'sleep', 'poll', 'stop']
    outcome, _, slept = watched(None)
    assert outcome == (7, None, quiet) and sum(slept) == pytest.approx(2 * interval), 'an undisturbed wait is one interval'
    assert watched('stop')[0] == (7, None, [*quiet, 'signal']), 'a signal during the stop changed the outcome'

    def reading(pattern, then=None):
        """One reading per pass: `x` fails, as a reader past its time limit does; anything else answers `then`."""
        passes = iter(pattern)

        def read():
            if next(passes, '.') == 'x':
                raise watchdog.ReadingFailed('vm_stat: TimeoutExpired')
            return then
        return read

    blind = 'RuntimeError: Three consecutive readings of free memory failed, the last vm_stat: TimeoutExpired'
    assert watched(None, free=reading('xx'), passes=3)[0] == (7, None, [*quiet[:-1], 'sample', 'sleep', 'poll', 'stop']), (
        'two passes without the reading are gaps, like two failed samples')
    assert watched(None, free=reading('xx.xx'), passes=6)[0][:2] == (7, None), 'a reading in between starts the count again'
    assert watched(None, free=reading('xxx'), passes=4)[0][:2] == (99, blind), 'the third in a row stops the job'
    assert watched(None, free=lambda: 0.5, youngest=reading('xxx', True), passes=4)[0][:2] == (99, blind), (
        'so does not knowing who is youngest')


def test_sigkill_to_the_watchdog_keeps_the_lock_until_the_job_stops(tmp_path):
    import fcntl

    marker = tmp_path / 'job.pid'
    lock = tmp_path / 'lock'
    with lock.open('a') as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fd = held.fileno()
        watchdog = start(tmp_path, [sys.executable, '-c', sleeper(marker, ignore_term=True)],
                         '--hold-fd', str(fd), pass_fds=(fd,))
    try:
        pid = wait_for(marker)
    finally:
        watchdog.kill()
        watchdog.wait(timeout=10)
    with lock.open('a') as retry:
        with pytest.raises(BlockingIOError):
            fcntl.flock(retry, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert gone(pid), 'the job outlived its SIGKILLed watchdog'
        fcntl.flock(retry, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_nightly_setup_keeps_the_lock_until_an_unlocked_grandchild_stops(tmp_path):
    import fcntl
    import signal

    lock = tmp_path / 'lock'
    setup_pid = tmp_path / 'setup.pid'
    grandchild_pid = tmp_path / 'grandchild.pid'
    launcher = ROOT / 'scripts/nightly_publish.py'
    # Match npm's child launch: the writer gets no inherited lock descriptor.
    setup = f'''
import os,pathlib,subprocess,sys,time
subprocess.Popen([sys.executable,'-c',{sleeper(grandchild_pid, ignore_term=True)!r}], close_fds=True)
pathlib.Path({str(setup_pid)!r}).write_text(str(os.getpid()))
time.sleep(60)
'''
    driver = f'''
import fcntl,os,runpy,sys
from pathlib import Path
step=runpy.run_path({str(launcher)!r})['step']
with open({str(lock)!r},'a') as held, open(os.devnull,'w') as log:
    fcntl.flock(held,fcntl.LOCK_EX | fcntl.LOCK_NB)
    step('setup',[sys.executable,'-c',{setup!r}],cwd=Path({str(tmp_path)!r}),
         env=os.environ,log=log,pass_fds=(held.fileno(),))
'''
    process = subprocess.Popen([sys.executable,'-c',driver], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        child = wait_for(setup_pid)
        grandchild = wait_for(grandchild_pid)
        os.kill(child, signal.SIGKILL)
        process.kill()
        process.wait(timeout=5)
        with lock.open('a') as retry:
            with pytest.raises(BlockingIOError):
                fcntl.flock(retry, fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert gone(grandchild), 'the unlocked setup grandchild outlived the owner'
            fcntl.flock(retry, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_a_missing_report_parent_is_created_and_the_exit_code_kept(tmp_path):
    marker = tmp_path / 'job.pid'
    report = tmp_path / 'a/b/r.json'
    code = f"import os,pathlib,sys,time;pathlib.Path({str(marker)!r}).write_text(str(os.getpid()));time.sleep(0.5);sys.exit(7)"
    began = time.time()
    result = subprocess.run([sys.executable, str(WATCHDOG), '--rss-gb', '4', '--min-disk-gb', '0', '--min-available-gb', '0',
        '--interval', '0.1', '--report', str(report), '--timeline', '--', sys.executable, '-c', code],
        capture_output=True, text=True, timeout=60)
    assert result.returncode == 7, result.stderr
    assert gone(int(marker.read_text()))
    value = json.loads(report.read_text())
    assert value['exit_code'] == 7 and value['stopped'] is None and value['peak_physical_gb'] > 0
    samples = [json.loads(line) for line in report.with_suffix('.timeline.jsonl').read_text().splitlines()]
    assert samples and set(samples[0]) == {'seconds', 'epoch', 'read_seconds', 'rss_gb', 'physical_gb', 'free_disk_gb'}
    # The wall clock at which each reading ended, on the clock engine step events carry, and how long the reading
    # took: scripts/measure/step_memory.py gives a sample only to a statement that spans its whole reading.
    assert all(0 < sample['read_seconds'] <= sample['seconds'] for sample in samples)
    assert began <= samples[0]['epoch'] <= samples[-1]['epoch'] <= time.time()
    started = [sample['epoch'] - sample['seconds'] for sample in samples]
    assert max(started) - min(started) < 0.05


def test_a_term_ignoring_grandchild_is_killed(tmp_path):
    marker = tmp_path / 'grandchild.pid'
    leader = (f"import pathlib,subprocess,sys,time\nsubprocess.Popen([sys.executable,'-c',{sleeper(marker, ignore_term=True)!r}])\n"
              f"p=pathlib.Path({str(marker)!r})\nwhile not (p.exists() and p.read_text()):time.sleep(0.05)\n")
    result = subprocess.run([sys.executable, str(WATCHDOG), '--rss-gb', '4', '--min-disk-gb', '0', '--min-available-gb', '0',
        '--interval', '0.1', '--', sys.executable, '-c', leader], capture_output=True, text=True, timeout=60, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert gone(int(marker.read_text()), seconds=5), 'a TERM-ignoring grandchild outlived the job'


def test_too_little_memory_at_start_refuses_before_the_job_runs(tmp_path):
    marker = tmp_path / 'job.pid'
    result = run(tmp_path, '--rss-gb', '4', '--start-available-gb', '1000000',
                 command=[sys.executable, '-c', sleeper(marker)])
    assert result.returncode == 98 and 'refused to start' in result.stderr and not marker.exists()


def test_stopping_an_owned_job_gives_its_term_handler_the_grace_period(tmp_path):
    # Red-e2: the owner leader died on the group TERM, so stop_owned's 5 s wait ended at once
    # and the KILL landed before the job's own TERM handler could finish.
    import importlib.util
    spec = importlib.util.spec_from_file_location('process_rss', ROOT / 'scripts/measure/process_rss.py')
    process_rss = importlib.util.module_from_spec(spec); spec.loader.exec_module(process_rss)
    ready, done = tmp_path / 'ready', tmp_path / 'done'
    job = (f"import pathlib,signal,sys,time\n"
           f"def stop(*_):\n time.sleep(1.5);pathlib.Path({str(done)!r}).write_text('clean');sys.exit(0)\n"
           f"signal.signal(signal.SIGTERM,stop)\npathlib.Path({str(ready)!r}).write_text('1')\ntime.sleep(60)\n")
    child = process_rss.start_owned([sys.executable, '-c', job])
    deadline = time.monotonic() + 20
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert ready.exists()
    process_rss.stop_owned(child)
    assert done.read_text() == 'clean', "the job's TERM handler was cut off by the group KILL"


def shim(tmp_path, monkeypatch, name, body):
    """Put a stand-in for one system reader first on PATH."""
    (tmp_path / 'bin').mkdir(exist_ok=True)
    (tmp_path / 'bin' / name).write_text(f'#!/bin/sh\n{body}\n')
    (tmp_path / 'bin' / name).chmod(0o755)
    monkeypatch.setenv('PATH', f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")


@pytest.mark.parametrize('reader', ['vm_stat', 'ps'])
def test_a_reader_that_does_not_answer_is_abandoned_at_its_time_limit(tmp_path, monkeypatch, reader):
    """Both ran with no limit. A handler that raised used to break a stuck one; now only this limit does."""
    if reader == 'vm_stat' and sys.platform != 'darwin':
        pytest.skip('free memory comes from /proc/meminfo here, with no reader to wait for')
    shim(tmp_path, monkeypatch, reader, 'exec sleep 8')
    monkeypatch.setattr(watchdog, 'READER_SECONDS', 0.3, raising=False)
    began = time.monotonic()
    with pytest.raises(watchdog.ReadingFailed, match=f'^{reader}: TimeoutExpired$'):
        watchdog.available_gb() if reader == 'vm_stat' else watchdog.start_times([os.getpid()])
    assert time.monotonic() - began < 5


def test_a_ps_that_died_is_a_failed_reading_not_a_finding_that_every_job_is_dead(tmp_path, monkeypatch):
    """A signal to the whole group kills the `ps` the registry has running. Its empty output read as `no such
    process` would delete every other job's admission entry; a PID that is really gone still reads as gone."""
    ended = subprocess.Popen([sys.executable, '-c', 'pass'])
    ended.wait()
    assert watchdog.start_times([ended.pid]) == {}
    registry = watchdog.Registry(tmp_path / 'state')
    registry.put(dict(entry(os.getpid(), 0, 1, admitted=time.time()), started=watchdog.start_times([os.getpid()])[os.getpid()]))
    shim(tmp_path, monkeypatch, 'ps', 'kill -INT $$')
    with pytest.raises(watchdog.ReadingFailed, match='^ps: CalledProcessError$'):
        registry.live()
    assert [path.name for path in (tmp_path / 'state').glob('*.json')] == [f'{os.getpid()}.json']


def test_jobs_from_every_worktree_share_one_admission_state(monkeypatch):
    """The default state sits in the main checkout's .cache, which every worktree of the clone sees."""
    monkeypatch.delenv('ARCHIVE_WATCHDOG_STATE')
    common = subprocess.run(['git', 'rev-parse', '--path-format=absolute', '--git-common-dir'], cwd=ROOT,
                            check=True, capture_output=True, text=True).stdout.strip()
    assert watchdog.default_state() == Path(common).parent / '.cache/watchdog'


def test_an_entry_whose_pid_now_names_another_process_is_dropped(tmp_path):
    """green-rca: a dead watchdog's PID can be reused; its entry must not count as a running job,
    or the floor would pick a victim that is no watchdog and no live job would stop."""
    stranger = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(60)'])
    try:
        registry = watchdog.Registry(tmp_path / 'state')
        started = watchdog.start_times([stranger.pid])[stranger.pid]
        registry.put(dict(entry(stranger.pid, 0, 1, admitted=time.time()), started=started))
        assert [e['pid'] for e in registry.live()] == [stranger.pid]
        registry.put(dict(entry(stranger.pid, 0, 1, admitted=time.time()), started='Thu Jan  1 00:00:00 1970'))
        assert registry.live() == [] and list((tmp_path / 'state').glob('*.json')) == []
    finally:
        stranger.kill()
        stranger.wait()
