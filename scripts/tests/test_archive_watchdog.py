"""The watchdog stops a real runaway by its real RSS, kills descendants, and records the peak."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).parents[2]
WATCHDOG = ROOT / 'scripts/archive_watchdog.py'
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
    assert report['exit_code'] == 99 and report['peak_rss_gb'] > 0.2 and 'RSS' in report['stopped']
    pid = int(marker.read_text())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    raise AssertionError('the runaway child outlived the watchdog')


def test_a_held_lock_refuses_after_its_wait_and_a_dead_owner_is_reclaimed(tmp_path):
    lock = tmp_path / 'lock'
    lock.mkdir()
    (lock / 'owner').write_text(f'{os.getpid()}\n')
    held = run(tmp_path, '--rss-gb', '4', '--lock', str(lock), '--wait-seconds', '0', command=[sys.executable, '-c', 'pass'])
    assert held.returncode == 98 and 'job slot' in held.stderr
    finished = subprocess.run([sys.executable, '-c', 'import os;print(os.getpid())'], capture_output=True, text=True)
    (lock / 'owner').write_text(finished.stdout)
    assert run(tmp_path, '--rss-gb', '4', '--lock', str(lock), command=[sys.executable, '-c', 'pass']).returncode == 0
    assert not lock.exists()


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


def start(tmp_path, command, *flags):
    return subprocess.Popen([sys.executable, str(WATCHDOG), '--rss-gb', '4', '--min-disk-gb', '0', '--min-available-gb', '0',
        '--interval', '0.1', '--report', str(tmp_path / 'report.json'), *flags, '--', *command],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def test_sigterm_to_the_watchdog_stops_the_job(tmp_path):
    marker = tmp_path / 'job.pid'
    watchdog = start(tmp_path, [sys.executable, '-c', sleeper(marker)])
    pid = wait_for(marker)
    watchdog.terminate()
    _, stderr = watchdog.communicate(timeout=30)
    assert gone(pid), 'the job outlived a TERM to its watchdog'
    report = json.loads((tmp_path / 'report.json').read_text())
    assert watchdog.returncode == 99 and 'signal' in report['stopped'] and 'signal' in stderr


def test_sigkill_to_the_watchdog_still_stops_the_job(tmp_path):
    marker = tmp_path / 'job.pid'
    watchdog = start(tmp_path, [sys.executable, '-c', sleeper(marker)])
    pid = wait_for(marker)
    watchdog.kill()
    watchdog.wait(timeout=10)
    assert gone(pid), 'the job outlived its SIGKILLed watchdog'


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
