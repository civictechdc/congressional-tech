"""Backfill owns each process group and retains evidence on resource refusal."""
import json
from pathlib import Path
import sys

import pytest

from congress_api.lake import capture_backfill


def run(tmp_path,code,**limits):
    return capture_backfill.monitor_command([sys.executable,'-I','-c',code],work=tmp_path,**limits)


def test_success_records_own_group_and_physical_footprint(tmp_path):
    if sys.platform!='darwin':
        with pytest.raises(RuntimeError,match='macOS'):run(tmp_path,'pass')
        return
    result=run(tmp_path,"import os,time;print(os.getpid(),flush=True);time.sleep(.3)")
    assert result['returncode']==0 and result['samples']>0
    assert result['sampled_peak_tree_physical_footprint']>0
    assert result['sampled_peak_tree_rss']>0
    assert json.loads((tmp_path/'measurement.json').read_text())==result
    assert int((tmp_path/'process.log').read_text())!=result['monitor_pid']
    assert result['owned_pgid']!=result['monitor_pid']


def test_physical_limit_stops_owned_process_and_preserves_partial(tmp_path):
    if sys.platform!='darwin':
        with pytest.raises(RuntimeError,match='macOS'):run(tmp_path,'pass')
        return
    with pytest.raises(RuntimeError,match='physical'):
        run(tmp_path,'import time;time.sleep(10)',physical_limit=1)
    result=json.loads((tmp_path/'measurement.json').read_text())
    assert result['returncode']!=0 and result['failure']
    assert (tmp_path/'measurement.json.partial').is_file()


def test_failed_batch_has_no_success_result(tmp_path):
    if sys.platform!='darwin':
        with pytest.raises(RuntimeError,match='macOS'):run(tmp_path,'pass')
        return
    with pytest.raises(RuntimeError,match='exit'):
        run(tmp_path,'raise SystemExit(7)')
    assert json.loads((tmp_path/'measurement.json').read_text())['returncode']==7
