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
