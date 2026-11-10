"""The watchdog admits on measured free memory, stops a real runaway by its real RSS, kills descendants,
and records the peak."""
import importlib.util
import json
import os
from pathlib import Path
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
        process = STARTED.pop()
        if process.poll() is None:
            process.kill()
        process.communicate()
HOLD = "import time\nb=bytearray({size}*1024*1024)\nfor i in range(0,len(b),4096):b[i]=1\ntime.sleep(60)\n"


def run(tmp_path, *flags, command):
    return subprocess.run([sys.executable, str(WATCHDOG), '--min-disk-gb', '0', '--min-available-gb', '0', '--interval', '0.1',
        '--report', str(tmp_path / 'report.json'), *flags, '--', *command], capture_output=True, text=True, timeout=120)


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


def start(tmp_path, command, *flags, pass_fds=(), plant=()):
    process = subprocess.Popen([sys.executable, *(('-c', PLANT, *plant) if plant else ()), str(WATCHDOG),
        '--rss-gb', '4', '--min-disk-gb', '0', '--min-available-gb', '0',
        '--interval', '0.1', '--report', str(tmp_path / 'report.json'), *flags, '--', *command],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, pass_fds=pass_fds)
    STARTED.append(process)
    return process


def test_sigterm_to_the_watchdog_stops_the_job(tmp_path):
    marker = tmp_path / 'job.pid'
    watchdog = start(tmp_path, [sys.executable, '-c', sleeper(marker)])
    pid = wait_for(marker)
    watchdog.terminate()
    _, stderr = watchdog.communicate(timeout=30)
    assert gone(pid), 'the job outlived a TERM to its watchdog'
    report = json.loads((tmp_path / 'report.json').read_text())
    assert watchdog.returncode == 99 and 'signal' in report['stopped'] and 'signal' in stderr


# A watchdog made to receive SIGTERM at one chosen instruction. Popen._wait(timeout) and Popen._internal_poll take
# the child's _waitpid_lock with acquire(False) and only afterwards enter their try (CPython 3.12 subprocess.py:2032
# and :1983; 3.15 has the same shape), so an exception a signal handler raises right there leaves the lock held, and
# the next blocking wait on that child never returns. This stand-in lock sends the signal from inside that acquire:
# `sampler` in the first timed wait for a `ps` once the job runs, `cleanup` in the poll that opens stop_owned.
PLANT = r'''
import importlib.util, os, pathlib, signal, subprocess, sys
site, marker, fired, script = sys.argv[1:5]

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
            os.kill(os.getpid(), signal.SIGTERM)
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

spec = importlib.util.spec_from_file_location('planted_watchdog', script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
subprocess.Popen = Planted
raise SystemExit(module.main(sys.argv[5:]))
'''


@pytest.mark.parametrize('site', ['sampler', 'cleanup'])
def test_a_signal_at_the_instruction_that_holds_a_childs_wait_lock_still_stops_the_job_and_exits(tmp_path, private_state, site):
    """ct-psb5. `sampler`: the handler used to raise into the sampler's `ps` wait, and the watchdog blocked for ever
    on that child's lock: job not stopped, no report, registry entry kept. `cleanup`: a second signal as the stop
    began used to abort it: exit 1 with a traceback and no report. Recorded and read by the loop, both are harmless."""
    marker, fired = tmp_path / 'job.pid', tmp_path / 'fired'
    watchdog = start(tmp_path, [sys.executable, '-c', sleeper(marker)], plant=(site, str(marker), str(fired)))
    pid = wait_for(marker)
    if site == 'cleanup':
        watchdog.terminate()
    try:
        _, stderr = watchdog.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        pytest.fail(f'the watchdog had not exited 30 s after its signal; planted: {fired.exists()}')
    assert fired.read_text() == site, 'the signal was never planted, so this run proved nothing'
    assert gone(pid), 'the job outlived a TERM to its watchdog'
    assert watchdog.returncode == 99, stderr
    assert 'signal 15' in json.loads((tmp_path / 'report.json').read_text())['stopped'] and 'signal 15' in stderr
    assert list(private_state.glob('*.json')) == [], 'the stopped watchdog left its admission entry behind'


def test_a_recorded_signal_stops_the_job_within_one_interval_and_changes_nothing_once_the_stop_has_begun(monkeypatch, tmp_path):
    """The loop reads the record once per pass, right after its sleep. Here the signal is the installed handler
    called from a stand-in sampler, sleep or stop, so each case is exact: no real signal, no process, no timing."""
    import signal
    import types

    def watched(signal_during):
        events = []

        class Job:
            pid, returncode = 1, 7

            def poll(self):
                events.append('poll')
                return None if events.count('poll') <= 2 else 7

        def passing(through):
            events.append(through)
            if through == signal_during and 'signal' not in events:
                events.append('signal')
                signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)

        class Readings:
            def __init__(self, _sampler):
                pass

            def sample(self, _pid):
                passing('sample')
                return 2**30, 2**30

        monkeypatch.setattr(watchdog, 'available_gb', lambda: None)
        monkeypatch.setattr(watchdog, 'time', types.SimpleNamespace(monotonic=lambda: 0.0, sleep=lambda _seconds: passing('sleep')))
        monkeypatch.setattr(watchdog, 'sampler', types.SimpleNamespace(
            MemorySamples=Readings, start_owned=lambda command, **_: Job(), stop_owned=lambda _process: passing('stop')))
        before = {number: signal.getsignal(number) for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
        try:
            code, _, _, reason, _ = watchdog.watch(['job'], rss_gb=4, min_available_gb=0, min_disk_gb=0,
                                                   disk_root=tmp_path, interval=1)
            assert {number: signal.getsignal(number) for number in before} == before, 'watch() kept its handlers'
        finally:  # a watch() that raises must not leave this pytest process with its handlers
            for number, handler in before.items():
                signal.signal(number, handler)
        return code, reason, events

    stopped = 'Interrupted: watchdog received signal 15'
    assert watched('sample') == (99, stopped, ['poll', 'sample', 'signal', 'stop']), 'it slept on a signal it already had'
    assert watched('sleep') == (99, stopped, ['poll', 'sample', 'sleep', 'signal', 'stop']), 'it sampled again first'
    quiet = ['poll', 'sample', 'sleep', 'poll', 'sample', 'sleep', 'poll', 'stop']
    assert watched(None) == (7, None, quiet)
    assert watched('stop') == (7, None, [*quiet, 'signal']), 'a signal during the stop changed the outcome'


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
    result = subprocess.run([sys.executable, str(WATCHDOG), '--rss-gb', '4', '--min-disk-gb', '0', '--min-available-gb', '0',
        '--interval', '0.1', '--report', str(report), '--timeline', '--', sys.executable, '-c', code],
        capture_output=True, text=True, timeout=60)
    assert result.returncode == 7, result.stderr
    assert gone(int(marker.read_text()))
    value = json.loads(report.read_text())
    assert value['exit_code'] == 7 and value['stopped'] is None and value['peak_physical_gb'] > 0
    samples = [json.loads(line) for line in report.with_suffix('.timeline.jsonl').read_text().splitlines()]
    assert samples and set(samples[0]) == {'seconds', 'rss_gb', 'physical_gb', 'free_disk_gb'}


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
