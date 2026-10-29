"""M1 calls only a pinned scratch probe, in order, and stops at the first failure."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'm1_smoke.py'
NS = 'docspec_m1_' + 'a' * 32


@pytest.fixture
def rehearsal(tmp_path):
    binary = tmp_path / 'probe'
    binary.write_text(f'#!{sys.executable}\n' + '''import json,os,pathlib,sys
args=sys.argv[1:]
action=args[args.index('--action')+1]
with open(os.environ['CALLS'],'a') as out: out.write(json.dumps(args)+'\\n')
output=pathlib.Path(args[args.index('--output')+1])
report=dict(release_build=True,table_uuid='fixture',namespace='docspec_m1_'+'a'*32,table='growth',binary_blake3='fixture')
if action=='create': report['created']='growth'
if action=='append': report['batches']=[dict(day=i,commits=1,work_list_rows=100) for i in range(3)]
if action=='observe': report.update(rows=300,rows_equal=os.environ.get('BAD_ROWS')!='1')
if action=='race': report.update(guarded_conflict=True,server_snapshot_conflict=True,duplicate_rows=0,repeat_work_list_rows=0,repeat_commits=0,retries=1)
if action=='purge': report.update(purged='growth',remaining_objects=['owned/orphan.parquet'])
output.write_text(json.dumps(report))
print('secret-must-never-appear',file=sys.stderr)
if os.environ.get('FAIL')==action: sys.exit(2)
''')
    binary.chmod(0o755)
    env = dict(os.environ, CALLS=str(tmp_path/'calls'),
        DOCSPEC_M1_BUCKET='cx-engine-first-lock-probe-smoke',
        DOCSPEC_M1_CATALOG_URI='https://catalog.invalid/cx-engine-first-lock-probe-smoke',
        DOCSPEC_M1_WAREHOUSE='fixture', DOCSPEC_M1_S3_ENDPOINT='http://127.0.0.1:1',
        DOCSPEC_M1_CATALOG_TOKEN='secret-must-never-appear',
        DOCSPEC_M1_ACCESS_KEY_ID='secret-must-never-appear',
        DOCSPEC_M1_SECRET_ACCESS_KEY='secret-must-never-appear')
    command = [sys.executable, '-I', str(SCRIPT), '--binary', str(binary),
        '--binary-sha256', hashlib.sha256(binary.read_bytes()).hexdigest(),
        '--namespace', NS, '--work', str(tmp_path/'work')]
    return command, env, tmp_path


def invoke(rehearsal, execute=True, **env_changes):
    command, env, root = rehearsal
    result = subprocess.run(command + (['--execute'] if execute else []),
        env=dict(env, **env_changes), text=True, capture_output=True)
    assert 'secret-must-never-appear' not in result.stdout + result.stderr
    calls = [json.loads(x) for x in (root/'calls').read_text().splitlines()] if (root/'calls').exists() else []
    return result, calls, root


def test_plan_never_invokes_probe(rehearsal):
    result, calls, root = invoke(rehearsal, execute=False)
    assert result.returncode == 0, result.stderr
    assert calls == []
    assert (root/'work/plan.json').is_file()


def test_execute_preserves_sequence_evidence_and_remaining_listing(rehearsal):
    result, calls, root = invoke(rehearsal)
    assert result.returncode == 0, result.stderr
    assert [args[args.index('--action')+1] for args in calls] == ['create','append','observe','race','purge']
    append = calls[1]
    assert append[append.index('--batches')+1] == '3'
    assert append[append.index('--day')+1] == '0'
    assert calls[3][calls[3].index('--day')+1] == '3'
    assert '--write-records' in calls[2]
    assert all('--allow-scratch-writes' in args for args in calls)
    summary = json.loads((root/'work/summary.json').read_text())
    assert summary['remaining_objects'] == ['owned/orphan.parquet']
    assert json.loads((root/'work/remaining.json').read_text()) == summary['remaining_objects']


@pytest.mark.parametrize('stage', ['create','append','observe','race','purge'])
def test_failure_stops_without_automatic_purge(rehearsal, stage):
    result, calls, root = invoke(rehearsal, FAIL=stage)
    assert result.returncode != 0
    order = ['create','append','observe','race','purge']
    assert [args[args.index('--action')+1] for args in calls] == order[:order.index(stage)+1]
    assert not (root/'work/summary.json').exists()


def test_bad_rows_stop_before_race(rehearsal):
    result, calls, root = invoke(rehearsal, BAD_ROWS='1')
    assert result.returncode != 0
    assert len(calls) == 3


@pytest.mark.parametrize('config', [
    {'DOCSPEC_M1_BUCKET':'congressional-tech-raw'},
    {'DOCSPEC_M1_CATALOG_URI':'https://catalog.invalid/congressional-tech-raw'},
])
def test_production_bucket_and_catalog_refuse_before_io(rehearsal, config):
    result, calls, root = invoke(rehearsal, **config)
    assert result.returncode != 0
    assert calls == []


def test_unpinned_binary_refuses_before_io(rehearsal):
    command, env, root = rehearsal
    Path(command[command.index('--binary')+1]).write_text('changed binary')
    result, calls, root = invoke(rehearsal)
    assert result.returncode != 0 and calls == []
