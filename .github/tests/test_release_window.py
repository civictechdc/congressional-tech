"""The lead window stops before unsafe effects and watches the new exact run."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
WINDOW = ROOT / 'codex-release2/window.md'


def blocks():
    return re.findall(r'```sh\n(.*?)\n```', WINDOW.read_text(), re.S)


def test_all_operator_blocks_have_valid_shell_syntax():
    assert len(blocks()) == 3
    for block in blocks():
        result = subprocess.run(['/bin/bash', '-n'], input=block, text=True, capture_output=True)
        assert result.returncode == 0, result.stderr


def test_readiness_precedes_every_effect_and_requires_complete_pins():
    forward = blocks()[0]
    prefix = forward.split('export REPO=', 1)[0]
    result = subprocess.run(['/bin/bash'], input=prefix, text=True)
    ready = re.search(r'^WINDOW_READY=([01])$', prefix, re.M)
    assert ready is not None
    if ready[1] == '0':
        assert result.returncode != 0
    else:
        assert result.returncode == 0
        assert not re.search(r'@[A-Z_]+@', WINDOW.read_text())


@pytest.fixture
def dispatcher(tmp_path):
    source = re.search(r'dispatch_and_watch\(\) \{\n.*?\n\}', blocks()[0], re.S)
    assert source is not None
    tools = tmp_path / 'bin'; tools.mkdir()
    fake = tools / 'gh'
    fake.write_text('#!' + sys.executable + '\n' + r'''
import json,os,sys
a=sys.argv[1:]; scenario=os.environ['SCENARIO']; expected='a'*40
with open(os.environ['GH_CALLS'],'a') as out:out.write(json.dumps(a)+'\n')
if a[0]=='api':
    print('b'*40 if scenario=='advanced_before_dispatch' else expected)
elif a[:2]==['workflow','run']:
    if scenario=='missing_url':print('Created workflow_dispatch event')
    elif scenario=='wrong_url':print('https://github.com/elsewhere/repo/actions/runs/7')
    else:print('https://github.com/civictechdc/congressional-tech/actions/runs/42')
elif a[:2]==['run','view']:
    assert a[2]=='42',a
    if '--log' in a:
        print('retained hosted logs');sys.exit(0)
    fields=a[a.index('--json')+1]
    if fields=='headSha,event':
        print(json.dumps(dict(headSha='b'*40 if scenario=='wrong_head' else expected,
            event='workflow_run' if scenario=='wrong_event' else 'workflow_dispatch')))
    elif fields=='conclusion':print(json.dumps(dict(conclusion='cancelled' if scenario=='cancelled' else 'success')))
    elif fields=='headSha,event,status,conclusion,jobs':
        print(json.dumps(dict(headSha=expected,event='workflow_dispatch',status='completed',conclusion='failure',jobs=[])))
    else:raise AssertionError(a)
elif a[:2]==['run','watch']:
    assert a[2]=='42',a
    if scenario=='watch_failure':sys.exit(9)
elif a[:2]==['run','list']:
    print(json.dumps([dict(databaseId=7,url='https://github.com/civictechdc/congressional-tech/actions/runs/7')]))
else:raise AssertionError(a)
''')
    fake.chmod(0o755)
    calls = tmp_path / 'calls.jsonl'
    work = tmp_path / 'window'; work.mkdir()
    landing = tmp_path / 'landing'; (landing / '.venv/bin').mkdir(parents=True)
    baseline = landing / '.venv/bin/python'
    baseline.write_text('#!' + sys.executable + '\n' + '''
import json,os,sys
with open(os.environ['GH_CALLS'],'a') as out:out.write(json.dumps(['baseline_verify',*sys.argv[1:]])+'\\n')
raise SystemExit(1 if os.environ['SCENARIO']=='baseline_rejected' else 0)
''')
    baseline.chmod(0o755)
    def run(scenario, *, baseline_mode=False, workflow='validate-explorer.yml'):
        result = subprocess.run(['/bin/bash'], input='set -euo pipefail\n' + source[0] +
            '\ndispatch_and_watch ' + workflow + (' --baseline-validation' if baseline_mode else '') + '\n', text=True, capture_output=True,
            env={**os.environ, 'PATH': str(tools) + os.pathsep + os.environ['PATH'],
                 'REPO': 'civictechdc/congressional-tech', 'WINDOW': str(work),
                 'LANDED_APPLICATION': 'a'*40, 'SCENARIO': scenario, 'GH_CALLS': str(calls),
                 'LANDING': str(landing)})
        invoked = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
        return result, invoked, work
    return run


def test_dispatch_watches_only_the_authoritative_new_run(dispatcher):
    result, calls, work = dispatcher('success')
    assert result.returncode == 0, result.stderr
    assert calls[0][0] == 'api'
    assert sum(c[:2] == ['workflow','run'] for c in calls) == 1
    assert any(c[:3] == ['run','watch','42'] for c in calls)
    assert not any(c[:3] == ['run','watch','7'] for c in calls)
    assert (work / 'run-validate-explorer-id.txt').read_text().strip() == '42'


@pytest.mark.parametrize('scenario', ['missing_url','wrong_url','wrong_head','wrong_event',
                                     'watch_failure','cancelled','advanced_before_dispatch'])
def test_dispatch_refuses_stale_heads_missing_identity_and_non_success(dispatcher, scenario):
    result, calls, _ = dispatcher(scenario)
    assert result.returncode != 0
    assert sum(c[:2] == ['workflow','run'] for c in calls) <= 1
    assert not any(c[:3] == ['run','watch','7'] for c in calls)
    if scenario == 'advanced_before_dispatch':
        assert not any(c[:2] == ['workflow','run'] for c in calls)
    elif scenario in ('missing_url','wrong_url','wrong_head','wrong_event'):
        assert not any(c[:2] == ['run','watch'] for c in calls)


def test_pre_switch_rollback_stops_before_changes_after_publication_attempt(tmp_path):
    rollback = blocks()[2]
    assert rollback.index('test ! -e "$WINDOW/data-activation-started"') < rollback.index('gh variable set')
    (tmp_path / 'previous-application-commit.txt').write_text('a'*40)
    (tmp_path / 'landed-application-commit.txt').write_text('b'*40)
    (tmp_path / 'data-activation-started').touch()
    prefix = rollback.split('test -z', 1)[0]
    result = subprocess.run(['/bin/bash'], input=prefix, text=True,
                            env={**os.environ, 'WINDOW': str(tmp_path)})
    assert result.returncode != 0


def test_upload_is_bound_to_approved_bytes_and_the_guarded_checkout():
    forward = blocks()[0]
    assert 'cd "$CI"' not in forward
    assert forward.index('cd "$LANDING"') < forward.index('--upload --bucket')
    assert '--expected-descriptor "$RUNTIME_PACKET/runtime-artifact.json"' in forward


def test_rollback_is_prepared_locally_before_remote_variables_change():
    rollback = blocks()[2]
    assert rollback.index('git -C "$LANDING" commit') < rollback.index('gh variable set')


@pytest.mark.parametrize('status,expected', [(0,1),(1,0),(2,1)])
def test_local_v6_publisher_gate_drains_and_refuses_probe_errors(tmp_path, status, expected):
    forward = blocks()[0]
    gate = re.search(r'# Local v6 publishers[^\n]*\n(.*?)\n# 1\. Private', forward, re.S)
    assert gate is not None
    assert forward.index(gate[0]) < forward.index('--upload --bucket')
    tool = tmp_path / 'pgrep'
    tool.write_text('#!/bin/bash\nif test "$PGREP_STATUS" = 0; then echo 123; fi\nexit "$PGREP_STATUS"\n')
    tool.chmod(0o755)
    result = subprocess.run(['/bin/bash'], input='set -euo pipefail\n' + gate[1], text=True,
        env={**os.environ, 'PATH': str(tmp_path) + os.pathsep + os.environ['PATH'],
             'WINDOW': str(tmp_path), 'PGREP_STATUS': str(status)}, capture_output=True)
    assert (result.returncode == 0) == (expected == 0)


def test_seed_switch_preserves_old_capture_until_raw_rebuild():
    phase = blocks()[1]
    assert 'seed: v5 catalog 596f08fa' in WINDOW.read_text()
    assert 'accepted seed' in WINDOW.read_text()
    assert 'accepted full D1/model/E4' not in WINDOW.read_text()
    assert 'gh workflow enable capture-raw-sources.yml --repo "$REPO"' in phase
    assert 'gh workflow enable update-data.yml --repo "$REPO"' in phase
    assert 'gh workflow enable capture-archive.yml' not in phase
    assert 'gh workflow disable archive-jobs.yml --repo "$REPO"' in phase
    assert phase.index('dispatch_and_watch deploy-pages.yml') < phase.index('gh workflow enable capture-raw-sources.yml')


def test_hosted_baseline_mode_records_visible_failure_then_checks_evidence(dispatcher):
    result, calls, work = dispatcher('success', baseline_mode=True)
    assert result.returncode == 0, result.stderr
    assert any(call[:3] == ['run','watch','42'] and '--exit-status' not in call for call in calls)
    checks = [call for call in calls if call[0] == 'baseline_verify']
    assert len(checks) == 1
    assert '--expected-head' in checks[0] and 'a'*40 in checks[0]
    assert '--baseline-validation' not in next(call for call in calls if call[:2] == ['workflow','run'])
    assert (work / 'hosted-validation.log').read_text().strip() == 'retained hosted logs'


def test_hosted_baseline_rejection_stops_the_window(dispatcher):
    result, calls, _ = dispatcher('baseline_rejected', baseline_mode=True)
    assert result.returncode != 0
    assert any(call[0] == 'baseline_verify' for call in calls)


def test_baseline_mode_cannot_relax_the_publish_gate(dispatcher):
    result, calls, _ = dispatcher('success', baseline_mode=True, workflow='archive-jobs.yml')
    assert result.returncode != 0
    assert calls == []


def test_window_selects_only_the_lead_approved_hosted_baseline_gate():
    assert 'dispatch_and_watch validate-explorer.yml --baseline-validation' in blocks()[1]
    assert 'a real hosted green' not in WINDOW.read_text()
