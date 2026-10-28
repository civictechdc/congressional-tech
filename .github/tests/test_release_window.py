"""The lead window stops before unsafe effects and watches the new exact run."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

from congress_shared.custody import write_atomic_json

ROOT = Path(__file__).resolve().parents[2]
WINDOW = ROOT / 'codex-release2/window.md'


def blocks():
    return re.findall(r'```sh\n(.*?)\n```', WINDOW.read_text(), re.S)


def test_all_operator_blocks_have_valid_shell_syntax():
    assert len(blocks()) == 6
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
    rollback = blocks()[3]
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
    rollback = blocks()[3]
    assert rollback.index('git -C "$LANDING" commit') < rollback.index('gh variable set')


@pytest.mark.parametrize('status,expected', [(0,1),(1,0),(2,1)])
def test_local_v6_publisher_gate_drains_and_refuses_probe_errors(tmp_path, status, expected):
    forward = blocks()[0]
    gate = re.search(r'assert_no_local_publishers\(\) \{\n.*?\n\}', forward, re.S)
    assert gate is not None
    assert forward.index(gate[0]) < forward.index('--upload --bucket')
    tool = tmp_path / 'pgrep'
    tool.write_text('#!/bin/bash\nif test "$PGREP_STATUS" = 0; then echo 123; fi\nexit "$PGREP_STATUS"\n')
    tool.chmod(0o755)
    result = subprocess.run(['/bin/bash'], input='set -euo pipefail\n' + gate[0] + '\nassert_no_local_publishers test\n', text=True,
        env={**os.environ, 'PATH': str(tmp_path) + os.pathsep + os.environ['PATH'],
             'WINDOW': str(tmp_path), 'PGREP_STATUS': str(status)}, capture_output=True)
    assert (result.returncode == 0) == (expected == 0)


def test_seed_switch_preserves_old_capture_until_raw_rebuild():
    phase = blocks()[1] + blocks()[2]
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
    assert 'dispatch_and_watch validate-explorer.yml --baseline-validation' in blocks()[5]
    assert 'dispatch_and_watch validate-explorer.yml' not in blocks()[1]
    assert 'a real hosted green' not in WINDOW.read_text()


def test_window_a_finishes_its_local_gate_without_hosted_validation():
    forward = blocks()[0]
    assert 'WINDOW_A_READY=0' in forward or 'WINDOW_A_READY=1' in forward
    assert 'WINDOW_B_READY' not in forward
    assert 'dispatch_and_watch validate-explorer.yml' not in forward
    assert 'touch "$WINDOW/window-a-complete"' in forward
    assert 'operation=publish' not in forward
    assert 'dispatch_and_watch deploy-pages.yml' not in forward


def test_window_b_requires_acceptance_and_successful_window_a_before_publication(tmp_path):
    phase = blocks()[1] + blocks()[2]
    assert 'WINDOW_B_READY=0' in phase
    gate = 'test -e "$WINDOW/window-a-complete"'
    assert phase.index(gate) < phase.index('--execute')
    assert phase.index(gate) < phase.index('pause_and_drain')
    prefix = phase.split('cd "$LANDING"', 1)[0].replace('WINDOW_B_READY=0', 'WINDOW_B_READY=1')
    result = subprocess.run(['/bin/bash'], input=prefix, text=True, capture_output=True,
        env={**os.environ,'WINDOW':str(tmp_path)})
    assert result.returncode != 0
    assert not (tmp_path / 'data-activation-started').exists()


def test_window_a_records_pre_window_pipeline_and_pointer_before_live_effects():
    forward=blocks()[0]
    assert forward.index('previous-pipeline-revision.txt') < forward.index('pause_and_drain "$PREVIOUS_APPLICATION" before-A')
    assert forward.index("evidence=w/'before-A-pointer.json'") < forward.index('pause_and_drain "$PREVIOUS_APPLICATION" before-A')
    assert 'before-A-pointer.etag.json' in forward


@pytest.mark.parametrize('scenario', ['success','cas409','cas412','lost_ack','status_failure','wrong_seed','wrong_status','missing_saved','bad_contract','wrong_binding','bad_response','bad_binding_hash','missing_local_acceptance'])
def test_after_data_rollback_uses_exact_saved_bytes_and_stops_on_uncertainty(tmp_path, monkeypatch, scenario):
    import types
    import hashlib
    source=re.search(r"<<'PY_ROLLBACK'\n(.*?)\nPY_ROLLBACK",blocks()[4],re.S)
    assert source is not None
    seed='a'*64
    (tmp_path/'accepted-seed-manifest.json').write_text(json.dumps(dict(release_id=seed,origin=dict(kind='seed_v5',display_only=True))))
    (tmp_path/'accepted-publish-spec.json').write_text(json.dumps(dict(bucket='congressional-tech-raw',model_kind='raw' if scenario=='wrong_binding' else 'seed_v5',work=str(tmp_path/'controller-work'))))
    work=tmp_path/'post-data-rollback';work.mkdir();evidence=tmp_path/'controller-work';evidence.mkdir()
    (tmp_path/'landed-application-commit.txt').write_text('c'*40)
    local=tmp_path/'local-publish';local.mkdir()
    binding=dict(landed_application='c'*40,release_id=seed,work=str(evidence),
        manifest_sha256=hashlib.sha256((tmp_path/'accepted-seed-manifest.json').read_bytes()).hexdigest(),
        spec_sha256=hashlib.sha256((tmp_path/'accepted-publish-spec.json').read_bytes()).hexdigest())
    if scenario=='bad_binding_hash':binding['manifest_sha256']='0'*64
    (local/'binding.json').write_text(json.dumps(binding))
    if scenario!='missing_local_acceptance':(local/'accepted.json').write_text(json.dumps(dict(binding,observed_pointer_etag='seed-etag',status='published')))
    for name in ('contract','canary'):
        (evidence/(name+'.json')).write_text(json.dumps(dict(status='failed' if scenario=='bad_contract' else 'passed',releaseId=seed,targets='provisional-emulated')))
    saved=b'{ "version":1, "publisher_version":10, "catalog_id":"prior", "manifest":"old.json" }\n'
    if scenario!='missing_saved':(evidence/'outgoing-pointer.json').write_bytes(saved)
    (evidence/'outgoing-pointer.response.json').write_text(json.dumps(dict(etag='opaque-original-etag',bytes=len(saved),sha256='0'*64 if scenario=='bad_response' else hashlib.sha256(saved).hexdigest())))
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
    rollback=blocks()[4]
    assert rollback.index('publish_manifest_pointer(client') < rollback.index('pointer-restore-ack.json')
    assert rollback.index('git -C "$LANDING" push origin') < rollback.index('dispatch_and_watch deploy-pages.yml')
    assert rollback.index('dispatch_and_watch deploy-pages.yml') < rollback.index('done < <(jq')
    assert 'previous-pipeline-revision.txt' in rollback
    assert 'local-publish/binding.json' in rollback
    assert 'gh run download' not in rollback


@pytest.mark.parametrize('scenario',['advanced_main','dirty_checkout','wrong_local_head'])
def test_after_data_rollback_refuses_changed_source_before_any_write(tmp_path,scenario):
    rollback=blocks()[4]
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


def test_hosted_ci_health_is_separate_and_requires_actual_green_with_zero_failures():
    health=blocks()[5]
    assert 'test -e "$WINDOW/window-a-complete"' in health
    assert 'dispatch_and_watch validate-explorer.yml --baseline-validation' in health
    assert '.observed == [] and .new == []' in health
    assert 'hosted-validation-run.json' in health
    assert '= success' in health


def test_seed_publication_uses_only_the_local_existing_controller():
    phase=blocks()[1] + blocks()[2]
    assert 'viewer_publication.archive_publish_job' in phase
    assert '--execute' in phase
    assert 'dispatch_and_watch archive-jobs.yml' not in phase
    assert 'gh workflow enable archive-jobs.yml' not in phase
    assert phase.index('pause_and_drain') < phase.index('--execute')
    assert phase.index('local-publish/accepted.json') < phase.index('dispatch_and_watch deploy-pages.yml')


@pytest.mark.parametrize('scenario',['idle','queued','in_progress','waiting','api_error','missing_revision'])
def test_shared_pause_and_drain_uses_current_source_and_stops_before_publication(tmp_path,scenario):
    source=re.search(r'pause_and_drain\(\) \{\n.*?\n\}',blocks()[0],re.S)
    assert source is not None
    tools=tmp_path/'bin';tools.mkdir();calls=tmp_path/'calls.jsonl'
    (tmp_path/'managed-workflows-before.json').write_text(json.dumps([
        dict(id=7,path='.github/workflows/kept.yml',state='active'),
        dict(id=8,path='.github/workflows/retired.yml',state='active')]))
    for name in ('git','gh'):
        p=tools/name
        p.write_text('#!'+sys.executable+'\n'+r'''
import json,os,sys
name=os.path.basename(sys.argv[0]);a=sys.argv[1:];scenario=os.environ['SCENARIO']
with open(os.environ['CALLS'],'a') as f:f.write(json.dumps([name,*a])+'\n')
if name=='git':
    if 'cat-file' in a:raise SystemExit(8 if scenario=='missing_revision' else 0)
    if 'ls-tree' in a:print('.github/workflows/kept.yml')
    else:raise AssertionError(a)
elif a[:2]==['workflow','list']:
    print(json.dumps([dict(id=7,path='.github/workflows/kept.yml',state='active')]))
elif a[:2]==['workflow','disable']:assert a[2]=='7'
elif a[:2]==['run','list']:
    if scenario=='api_error':raise SystemExit(9)
    status=a[a.index('--status')+1]
    print(json.dumps([dict(databaseId=99,status=status)] if scenario==status else []))
else:raise AssertionError(a)
''');p.chmod(0o755)
    result=subprocess.run(['/bin/bash'],input='set -euo pipefail\n'+source[0]+
        '\npause_and_drain '+('a'*40)+' test\ntouch "$WINDOW/controller-started"\n',
        text=True,capture_output=True,env={**os.environ,'PATH':str(tools)+os.pathsep+os.environ['PATH'],
        'WINDOW':str(tmp_path),'LANDING':str(tmp_path),'REPO':'fixture/repo','SCENARIO':scenario,'CALLS':str(calls)})
    assert (result.returncode==0)==(scenario=='idle'),result.stderr
    assert (tmp_path/'controller-started').exists()==(scenario=='idle')
    invoked=[json.loads(line) for line in calls.read_text().splitlines()]
    assert not any(row[:3]==['gh','workflow','disable'] and row[3]=='8' for row in invoked)
    if scenario=='missing_revision':assert not any(row[0]=='gh' for row in invoked)


@pytest.mark.parametrize('state',['running','accepted','failed','missing_pid'])
def test_local_publish_poll_never_restarts_uncertain_controller(tmp_path,monkeypatch,state):
    source=re.search(r"<<'PY_POLL'\n(.*?)\nPY_POLL",blocks()[2],re.S)
    assert source is not None
    local=tmp_path/'local-publish';local.mkdir()
    binding=dict(release_id='a'*64,landed_application='b'*40)
    (local/'binding.json').write_text(json.dumps(binding))
    if state!='missing_pid':(tmp_path/'local-publish-launcher.json').write_text(json.dumps(dict(pid=123,pgid=123)))
    if state=='accepted':(local/'accepted.json').write_text(json.dumps(dict(binding,status='published',observed_pointer_etag='opaque')))
    if state=='failed':(local/'exit.json').write_text(json.dumps(dict(returncode=9)))
    monkeypatch.setenv('LOCAL_PUBLISH_WINDOW',str(tmp_path))
    def kill(pid,sig):
        assert (pid,sig)==(123,0)
        if state in ('failed','accepted'):raise ProcessLookupError()
    monkeypatch.setattr(os,'kill',kill)
    if state=='accepted':exec(compile(source[1],str(WINDOW),'exec'),{})
    else:
        with pytest.raises((SystemExit,FileNotFoundError)):exec(compile(source[1],str(WINDOW),'exec'),{})
    assert not (tmp_path/'pages-started').exists()


def test_local_publish_launcher_is_persisted_detached_and_single_attempt():
    phase=blocks()[1]
    source=re.search(r"<<'PY_LAUNCH'\n(.*?)\nPY_LAUNCH",phase,re.S)
    assert source is not None
    body=source[1]
    for token in ('start_new_session=True','stdin=subprocess.DEVNULL','/usr/bin/nohup',
                  'local-publish-launcher.json','os.fsync','pid=process.pid','pgid=process.pid'):
        assert token in body
    assert body.index('local-publish-launcher.json') < body.index('subprocess.Popen(')
    assert 'local-publish-runner.py' in phase
    assert phase.index('data-activation-started') < phase.index("<<'PY_LAUNCH'")
    assert 'dispatch_and_watch deploy-pages.yml' not in phase
    assert 'local-publish/accepted.json' in blocks()[2]


@pytest.mark.parametrize('scenario',['success','controller_failure','wrong_result','changed_manifest','bad_response','bad_pointer','bad_status','existing_work','dirty_source'])
def test_local_publish_records_binding_and_requires_controller_and_readback(tmp_path,monkeypatch,scenario):
    import hashlib,types
    source=re.search(r"<<'PY_LOCAL_PUBLISH'\n(.*?)\nPY_LOCAL_PUBLISH",blocks()[1],re.S)
    assert source is not None
    seed='a'*64;landed='b'*40
    (tmp_path/'landed-application-commit.txt').write_text(landed)
    manifest_raw=json.dumps(dict(release_id=seed,origin=dict(kind='seed_v5',display_only=True))).encode()
    manifest_path=tmp_path/'accepted-seed-manifest.json';manifest_path.write_bytes(manifest_raw)
    spec_path=tmp_path/'accepted-publish-spec.json';spec_path.write_text('{}')
    work=tmp_path/'controller-work';output=tmp_path/'model-output';output.mkdir()
    spec=dict(model_kind='seed_v5',bucket='congressional-tech-raw',work=str(work),_model=dict(output=str(output),scratch=str(tmp_path/'model-scratch')))
    if scenario=='existing_work':work.mkdir()
    calls=[]
    def checked(args,**kwargs):
        if args==['git','rev-parse','HEAD']:return landed+'\n'
        if args==['git','status','--porcelain']:return ' M source.py' if scenario=='dirty_source' else ''
        raise AssertionError(args)
    def run(args,**kwargs):
        calls.append('controller')
        assert (tmp_path/'local-publish/binding.json').exists()
        assert args==['.venv/bin/python','-I','-m','viewer_publication.archive_publish_job','--spec',str(spec_path),'--execute']
        work.mkdir()
        for name in ('contract','canary'):(work/(name+'.json')).write_text(json.dumps(dict(status='passed',releaseId=seed,targets='provisional-emulated')))
        outgoing=b'{"version":1}'
        (work/'outgoing-pointer.json').write_bytes(outgoing)
        (work/'outgoing-pointer.response.json').write_text(json.dumps(dict(etag='opaque',bytes=len(outgoing),sha256='0'*64 if scenario=='bad_response' else hashlib.sha256(outgoing).hexdigest())))
        (output/'manifest.json').write_bytes(manifest_raw)
        if scenario=='changed_manifest':manifest_path.write_bytes(b'{}')
        kwargs['stdout'].write(json.dumps(dict(status='failed' if scenario=='wrong_result' else 'published',release_id=seed,live_release=seed,live_release_basis='conditional_flip_acknowledged')).encode())
        return types.SimpleNamespace(returncode=9 if scenario=='controller_failure' else 0)
    monkeypatch.setattr(subprocess,'check_output',checked);monkeypatch.setattr(subprocess,'run',run)
    client=object()
    storage=types.ModuleType('congress_shared.storage')
    def connect(**kwargs):
        calls.append('readback');assert kwargs==dict(bucket='congressional-tech-raw',retries={'total_max_attempts':1});return client
    storage.connect_r2=connect
    archive=types.ModuleType('viewer_publication.archive_publish');archive.STATUS='status'
    archive.read_pointer=lambda *a,**kw:(dict(release_id='c'*64 if scenario=='bad_pointer' else seed,previous_release_id=None),'new-etag')
    archive._read=lambda *a:(json.dumps(dict(status='failed' if scenario=='bad_status' else 'published',release_id=seed,live_release=seed,live_release_basis='conditional_flip_acknowledged',input_kind='seed_v5',display_only=True)).encode(),'status-etag')
    job=types.ModuleType('viewer_publication.archive_publish_job');job.load_spec=lambda path:spec
    gate=types.ModuleType('viewer_publication.archive_gate')
    def validate(value,**kwargs):assert value['status']=='passed' and value['releaseId']==kwargs['release_id']
    gate.validate_receipt=validate
    for name,module in [('congress_shared.storage',storage),('viewer_publication.archive_publish',archive),('viewer_publication.archive_publish_job',job),('viewer_publication.archive_gate',gate)]:monkeypatch.setitem(sys.modules,name,module)
    monkeypatch.setenv('LOCAL_PUBLISH_WINDOW',str(tmp_path))
    if scenario=='success':exec(compile(source[1],str(WINDOW),'exec'),{})
    else:
        with pytest.raises((ValueError,SystemExit)):exec(compile(source[1],str(WINDOW),'exec'),{})
    accepted=tmp_path/'local-publish/accepted.json'
    assert accepted.exists()==(scenario=='success')
    assert calls.count('controller')==(0 if scenario in ('existing_work','dirty_source') else 1)
    if scenario not in ('existing_work','dirty_source'):
        assert json.loads((tmp_path/'local-publish/exit.json').read_text())['returncode']==(9 if scenario=='controller_failure' else 0)


@pytest.mark.parametrize('existing',[False,True])
def test_detached_launcher_records_owned_pid_and_refuses_repeat(tmp_path,monkeypatch,existing):
    import types
    source=re.search(r"<<'PY_LAUNCH'\n(.*?)\nPY_LAUNCH",blocks()[1],re.S)
    assert source is not None
    (tmp_path/'local-publish-runner.py').write_text('pass\n')
    record=tmp_path/'local-publish-launcher.json'
    if existing:record.write_text('{}')
    calls=[]
    def launch(args,**kwargs):
        calls.append(args)
        assert args[0]=='/usr/bin/nohup' and args[2:] == ['-I',str(tmp_path/'local-publish-runner.py')]
        assert kwargs['start_new_session'] is True and kwargs['stdin']==subprocess.DEVNULL
        assert kwargs['stdout'].name==str(tmp_path/'local-publish-driver.stdout.log')
        assert kwargs['stderr'].name==str(tmp_path/'local-publish-driver.stderr.log')
        return types.SimpleNamespace(pid=123)
    monkeypatch.setattr(subprocess,'Popen',launch)
    monkeypatch.setenv('LOCAL_PUBLISH_WINDOW',str(tmp_path))
    if existing:
        with pytest.raises(ValueError):exec(compile(source[1],str(WINDOW),'exec'),{})
        assert calls==[]
    else:
        exec(compile(source[1],str(WINDOW),'exec'),{})
        value=json.loads(record.read_text())
        assert value['pid']==value['pgid']==123 and len(value['script_sha256'])==64
        assert len(calls)==1
