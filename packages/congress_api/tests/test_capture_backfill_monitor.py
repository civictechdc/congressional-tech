"""Backfill owns each process group and retains evidence on resource refusal."""
import json
from pathlib import Path
import sys

import pytest

from congress_api.lake import capture_backfill


def run(tmp_path,code,**limits):
    return capture_backfill.monitor_command([sys.executable,'-I','-c',code],work=tmp_path,**limits)


def test_success_records_own_group_and_physical_footprint(tmp_path):
    if sys.platform not in {'darwin','linux'}:
        with pytest.raises(RuntimeError,match='macOS or Linux'):run(tmp_path,'pass')
        return
    result=run(tmp_path,"import os,time;print(os.getpid(),flush=True);time.sleep(.3)")
    assert result['returncode']==0 and result['samples']>0
    assert result['sampled_peak_tree_physical_footprint']>0
    assert result['sampled_peak_tree_rss']>0
    assert result['physical_basis']==('macOS charged physical footprint' if sys.platform=='darwin'
        else 'Linux RSS plus swap conservative proxy')
    assert json.loads((tmp_path/'measurement.json').read_text())==result
    assert int((tmp_path/'process.log').read_text())!=result['monitor_pid']
    assert result['owned_pgid']!=result['monitor_pid']


def test_physical_limit_stops_owned_process_and_preserves_partial(tmp_path):
    if sys.platform not in {'darwin','linux'}:
        with pytest.raises(RuntimeError,match='macOS or Linux'):run(tmp_path,'pass')
        return
    with pytest.raises(RuntimeError,match='physical'):
        run(tmp_path,'import time;time.sleep(10)',physical_limit=1)
    result=json.loads((tmp_path/'measurement.json').read_text())
    assert result['returncode']!=0 and result['failure']
    assert (tmp_path/'measurement.json.partial').is_file()


def test_failed_batch_has_no_success_result(tmp_path):
    if sys.platform not in {'darwin','linux'}:
        with pytest.raises(RuntimeError,match='macOS or Linux'):run(tmp_path,'pass')
        return
    with pytest.raises(RuntimeError,match='exit'):
        run(tmp_path,'raise SystemExit(7)')
    assert json.loads((tmp_path/'measurement.json').read_text())['returncode']==7


def _live_group(group):
    import subprocess
    output=subprocess.run(['ps','-axo','pgid=,stat='],capture_output=True,text=True,check=True).stdout
    return any(int(parts[0])==group and not parts[1].startswith('Z')
        for line in output.splitlines() if len(parts:=line.split())==2)


def test_rejection_kills_descendant_even_after_watchdog_exits(tmp_path):
    if sys.platform not in {'darwin','linux'}:pytest.skip('Supported process accounting platform')
    code='import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print("ready",flush=True);time.sleep(60)'
    with pytest.raises(RuntimeError,match='time limit'):
        run(tmp_path,code,timeout=1)
    result=json.loads((tmp_path/'measurement.json').read_text())
    assert 'ready' in (tmp_path/'process.log').read_text()
    try:assert not _live_group(result['owned_pgid'])
    finally:
        import os
        import signal
        try:os.killpg(result['owned_pgid'],signal.SIGKILL)
        except ProcessLookupError:pass


def test_lost_monitor_watchdog_kills_a_term_ignoring_command(tmp_path):
    import os
    import signal
    import subprocess
    import time
    if sys.platform not in {'darwin','linux'}:pytest.skip('Supported process accounting platform')
    work=tmp_path/'monitor'
    code='import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print("ready",flush=True);time.sleep(60)'
    wrapper='from congress_api.lake.capture_backfill import monitor_command;import sys;monitor_command([sys.executable,"-I","-c",sys.argv[2]],work=sys.argv[1])'
    process=subprocess.Popen([sys.executable,'-I','-c',wrapper,str(work),code])
    group=None
    try:
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            if (work/'measurement.json.partial').exists() and 'ready' in (work/'process.log').read_text():
                group=json.loads((work/'measurement.json.partial').read_text())['owned_pgid'];break
            time.sleep(.05)
        assert group is not None,'The owned command did not become ready'
        process.kill();process.wait(timeout=5)
        deadline=time.monotonic()+5
        while _live_group(group) and time.monotonic()<deadline:time.sleep(.05)
        assert not _live_group(group)
    finally:
        if process.poll() is None:process.kill();process.wait(timeout=5)
        if group is not None:
            try:os.killpg(group,signal.SIGKILL)
            except ProcessLookupError:pass


def test_status_log_appends_owner_fields_without_replacing_prior_events(tmp_path):
    path=tmp_path/'rebuild-status.jsonl'
    from congress_api.lake.capture_backfill import log_status
    first=dict(step='d1',batch=1,of=2,receipts=1,rows=2,secs=1.2,peak_phys_gb=.1,status='ok',note='complete')
    log_status(path,**first);log_status(path,**dict(first,batch=2,status='running'))
    rows=[json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows)==2
    assert all(set(row)==set(first)|{'ts'} for row in rows)
    assert rows[0].items()>=first.items() and rows[1]['batch']==2
    assert rows[0]['ts'].endswith('Z')
    with pytest.raises(ValueError):log_status(path,**dict(first,status='accepted'))
    assert len(path.read_text().splitlines())==2


def test_whole_tree_sample_requires_three_consecutive_failures_and_resets():
    import errno
    from congress_api.lake.capture_backfill import _MemorySamples
    class Sampler:
        remaining=2
        def resident_tree(self,_pid):return 7
        def physical_tree(self,_pid):
            if self.remaining:
                self.remaining-=1;raise PermissionError(errno.EPERM,'sampling gap')
            return 11
    fake=Sampler();samples=_MemorySamples(fake)
    assert samples.sample(1) is None and samples.sample(1) is None
    assert samples.sample(1)==(7,11) and samples.consecutive_failures==0
    fake.remaining=3
    assert samples.sample(1) is None and samples.sample(1) is None
    with pytest.raises(RuntimeError,match='Three consecutive'):samples.sample(1)
