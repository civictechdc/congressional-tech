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
    assert len(blocks()) == 4
    for block in blocks():
        result = subprocess.run(['/bin/bash', '-n'], input=block, text=True, capture_output=True)
        assert result.returncode == 0, result.stderr


def test_readiness_precedes_every_effect_and_requires_complete_pins():
    forward = blocks()[0]
    prefix = forward.split('export REPO=', 1)[0]
    result = subprocess.run(['/bin/bash'], input=prefix, text=True)
    ready = re.search(r'^WINDOW_A_READY=([01])$', prefix, re.M)
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
    assert 'dispatch_and_watch validate-explorer.yml --baseline-validation' in blocks()[0]
    assert 'dispatch_and_watch validate-explorer.yml' not in blocks()[1]
    assert 'a real hosted green' not in WINDOW.read_text()


def test_window_a_finishes_hosted_gate_before_its_durable_completion_marker():
    forward = blocks()[0]
    assert 'WINDOW_A_READY=0' in forward or 'WINDOW_A_READY=1' in forward
    assert 'WINDOW_B_READY' not in forward
    assert forward.index('dispatch_and_watch validate-explorer.yml --baseline-validation') < forward.index('touch "$WINDOW/window-a-complete"')
    assert 'operation=publish' not in forward
    assert 'dispatch_and_watch deploy-pages.yml' not in forward


def test_window_b_requires_acceptance_and_successful_window_a_before_publication(tmp_path):
    phase = blocks()[1]
    assert 'WINDOW_B_READY=0' in phase
    gate = 'test -e "$WINDOW/window-a-complete"'
    assert phase.index(gate) < phase.index('--check-binding')
    assert phase.index(gate) < phase.index('gh workflow enable archive-jobs.yml')
    prefix = phase.split('cd "$LANDING"', 1)[0].replace('WINDOW_B_READY=0', 'WINDOW_B_READY=1')
    result = subprocess.run(['/bin/bash'], input=prefix, text=True, capture_output=True,
        env={**os.environ,'WINDOW':str(tmp_path)})
    assert result.returncode != 0
    assert not (tmp_path / 'data-activation-started').exists()


def test_window_a_records_pre_window_pipeline_and_pointer_before_live_effects():
    forward=blocks()[0]
    assert forward.index('previous-pipeline-revision.txt') < forward.index('gh workflow disable')
    assert forward.index("evidence=w/'before-A-pointer.json'") < forward.index('gh workflow disable')
    assert 'before-A-pointer.etag.json' in forward


@pytest.mark.parametrize('scenario', ['success','cas409','cas412','lost_ack','status_failure','wrong_seed','wrong_status','missing_saved','bad_contract','wrong_binding'])
def test_after_data_rollback_uses_exact_saved_bytes_and_stops_on_uncertainty(tmp_path, monkeypatch, scenario):
    import types
    import hashlib
    source=re.search(r"<<'PY_ROLLBACK'\n(.*?)\nPY_ROLLBACK",blocks()[3],re.S)
    assert source is not None
    seed='a'*64
    (tmp_path/'accepted-seed-manifest.json').write_text(json.dumps(dict(release_id=seed,origin=dict(kind='seed_v5',display_only=True))))
    (tmp_path/'accepted-publish-spec.json').write_text(json.dumps(dict(bucket='congressional-tech-raw',model_kind='raw' if scenario=='wrong_binding' else 'seed_v5')))
    work=tmp_path/'post-data-rollback';evidence=work/'publish-evidence';evidence.mkdir(parents=True)
    for name in ('contract','canary'):
        (evidence/(name+'.json')).write_text(json.dumps(dict(status='failed' if scenario=='bad_contract' else 'passed',releaseId=seed,targets='provisional-emulated')))
    saved=b'{ "version":1, "publisher_version":10, "catalog_id":"prior", "manifest":"old.json" }\n'
    if scenario!='missing_saved':(evidence/'outgoing-pointer.json').write_bytes(saved)
    calls=[]
    client=object()
    def connect_r2(**kwargs):
        assert kwargs==dict(bucket='congressional-tech-raw',retries={'total_max_attempts':1});return client
    def read_pointer(got,**kwargs):
        assert got is client;calls.append('read_pointer');return dict(release_id='b'*64 if scenario=='wrong_seed' else seed,previous_release_id=None),'current-etag'
    status=dict(status='published',release_id=seed,live_release=seed,live_release_basis='conditional_flip_acknowledged',input_kind='seed_v5',display_only=True)
    if scenario=='wrong_status':status['status']='failed'
    def publish(got,**kwargs):
        assert got is client
        assert kwargs==dict(bucket='congressional-tech-raw',pointer=saved,expected_etag='current-etag')
        calls.append('pointer_put')
        if scenario in ('cas409','cas412','lost_ack'):raise RuntimeError(scenario)
        return types.SimpleNamespace(etag='restored-etag',sha256=hashlib.sha256(saved).hexdigest(),bytes=len(saved))
    def write_status(got,**kwargs):
        assert got is client
        assert (work/'pointer-restore-ack.json').is_file()
        ack=json.loads((work/'pointer-restore-ack.json').read_text())
        assert ack['saved_pointer_sha256']==hashlib.sha256(saved).hexdigest()
        calls.append('status_put')
        if scenario=='status_failure':raise RuntimeError(scenario)
    storage=types.ModuleType('congress_shared.storage');storage.connect_r2=connect_r2
    archive=types.ModuleType('viewer_publication.archive_publish')
    archive.CONTROL_BYTES=1<<20;archive.STATUS='status';archive._sha=lambda value:value
    archive._read=lambda *args:(json.dumps(status).encode(),'status-etag')
    archive.read_pointer=read_pointer;archive.write_status=write_status
    writer=types.ModuleType('viewer_publication.client');writer.publish_manifest_pointer=publish
    for name,module in [('congress_shared.storage',storage),('viewer_publication.archive_publish',archive),('viewer_publication.client',writer)]:monkeypatch.setitem(sys.modules,name,module)
    monkeypatch.setenv('ROLLBACK_WINDOW',str(tmp_path))
    if scenario=='success':exec(compile(source[1],str(WINDOW),'exec'),{})
    else:
        with pytest.raises((RuntimeError,ValueError,FileNotFoundError)):exec(compile(source[1],str(WINDOW),'exec'),{})
    assert calls.count('pointer_put') <= 1
    if scenario in ('cas409','cas412','lost_ack'):
        assert calls==['read_pointer','pointer_put'];assert not (work/'pointer-restore-ack.json').exists()
    elif scenario=='status_failure':
        assert calls==['read_pointer','pointer_put','status_put'];assert (work/'pointer-restore-ack.json').is_file();assert not (work/'status-restored.json').exists()
    elif scenario=='success':
        assert calls==['read_pointer','pointer_put','status_put'];assert (work/'status-restored.json').is_file()
    else:assert 'pointer_put' not in calls


def test_after_data_rollback_restores_pair_before_prior_pages_and_workflow_states():
    rollback=blocks()[3]
    assert rollback.index('publish_manifest_pointer(client') < rollback.index('pointer-restore-ack.json')
    assert rollback.index('git -C "$LANDING" push origin') < rollback.index('dispatch_and_watch deploy-pages.yml')
    assert rollback.index('dispatch_and_watch deploy-pages.yml') < rollback.index('done < <(jq')
    assert 'previous-pipeline-revision.txt' in rollback
    assert 'archive-publish-evidence-$PUBLISH_RUN_ID-$PUBLISH_ATTEMPT' in rollback


@pytest.mark.parametrize('scenario',['advanced_main','dirty_checkout','wrong_local_head'])
def test_after_data_rollback_refuses_changed_source_before_any_write(tmp_path,scenario):
    rollback=blocks()[3]
    guard='test "$(gh api "repos/$REPO/git/ref/heads/main" --jq .object.sha)" = "$LANDED_APPLICATION"'
    assert rollback.index(guard) < rollback.index("<<'PY_ROLLBACK'")
    assert rollback.index('test -z "$(git -C "$LANDING" status --porcelain)"') < rollback.index("<<'PY_ROLLBACK'")
    assert 'test "$(git -C "$LANDING" rev-parse HEAD)" = "$LANDED_APPLICATION"' in rollback
    (tmp_path/'landed-application-commit.txt').write_text('a'*40)
    tools=tmp_path/'bin';tools.mkdir()
    calls=tmp_path/'calls.jsonl'
    for name in ('git','gh'):
        tool=tools/name
        tool.write_text('#!'+sys.executable+'\n'+r'''
import json,os,sys
name=os.path.basename(sys.argv[0]);args=sys.argv[1:]
with open(os.environ['CALLS'],'a') as f:f.write(json.dumps([name,*args])+'\n')
scenario=os.environ['SCENARIO']
if name=='git' and args[-2:]==['status','--porcelain']:
    print(' M changed.py' if scenario=='dirty_checkout' else '')
elif name=='git' and args[-2:]==['rev-parse','HEAD']:
    print(('b' if scenario=='wrong_local_head' else 'a')*40)
elif name=='gh' and args[0]=='api':print('b'*40)
else:raise AssertionError('Unexpected effect: '+repr(args))
''');tool.chmod(0o755)
    prefix=rollback.split(".venv/bin/python -I - <<'PY_ROLLBACK'",1)[0]
    result=subprocess.run(['/bin/bash'],input=prefix,text=True,capture_output=True,
        env={**os.environ,'PATH':str(tools)+os.pathsep+os.environ['PATH'],'WINDOW':str(tmp_path),
            'LANDING':str(tmp_path),'REPO':'civictechdc/congressional-tech','SCENARIO':scenario,'CALLS':str(calls)})
    assert result.returncode != 0
    invoked=[json.loads(line) for line in calls.read_text().splitlines()]
    assert all(call[0]=='git' or call[1]=='api' for call in invoked)
    assert not (tmp_path/'post-data-rollback').exists()
