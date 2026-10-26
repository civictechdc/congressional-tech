"""Run status reports evidence without promoting exit zero into publication."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('pipeline_status', ROOT / 'scripts/publication/pipeline_status.py')
status = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(status)
NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
REVISION = 'a' * 40


def github(conclusion=None):
    return {'id': 123, 'run_attempt': 2, 'head_sha': REVISION,
            'status': 'completed' if conclusion else 'in_progress', 'conclusion': conclusion}


def progress(**changes):
    return dict(github_run_id='123', github_run_attempt='2', code_revision=REVISION,
                status='running', stage='read_sources', completed=4, total=20, unit='rows',
                updated_at='2026-10-18T11:59:30Z', heartbeat_expires_at='2026-10-18T12:01:00Z',
                elapsed_seconds=30, stage_elapsed_seconds=10, counters={'bytes_read': 100}, **changes)


def write(path, value):
    path.write_text(json.dumps(value))
    return path


def receipt(tmp_path):
    return write(tmp_path / 'continuation.json', {
        'binding': {'run_id': '123', 'run_attempt': '2', 'code_runtime': {'revision': REVISION}},
        'phases': {'prepared': {'result': {'status': 'prepared'}, 'files': {'publication/data.parquet': '0' * 64}}}})


def test_stage_counts_are_not_an_overall_percentage():
    result = status.summarize('123', github(), progress(), now=NOW)
    assert result['heartbeat']['completed'] == 4
    assert result['heartbeat']['total'] == 20
    assert result['heartbeat']['monotonicity'] == 'not_checked_without_previous_snapshot'
    assert 'percent' not in json.dumps(result)
    assert result['public_readback'] == 'not_checked'


def test_expired_heartbeat_does_not_override_github_failure():
    value = progress()
    value['heartbeat_expires_at'] = '2026-10-18T11:59:59Z'
    result = status.summarize('123', github('failure'), value, now=NOW)
    assert result['state'] == 'failure'
    assert result['heartbeat']['state'] == 'stale'
    assert 'reconciliation' in result['next_action']


@pytest.mark.parametrize(('key', 'value'), [('github_run_id', '124'), ('github_run_attempt', '1'), ('code_revision', 'b' * 40)])
def test_wrong_identity_never_attributes_heartbeat(key, value):
    saved = progress(); saved[key] = value
    result = status.summarize('123', github(), saved, now=NOW)
    assert result['heartbeat']['state'] == 'unbound'
    assert 'stage' not in result['heartbeat']


def test_failed_child_preserves_recorded_accepted_preparation(tmp_path):
    result = status.summarize('123', github('failure'), progress(), now=NOW, receipt=receipt(tmp_path))
    assert result['state'] == 'failure'
    assert result['accepted_outputs'] == [{'phase': 'prepared', 'recorded_files': 1, 'integrity_rechecked': False}]
    assert result['public_readback'] == 'not_checked'
    assert result['continuation']['recorded_publication_status'] is None


def test_successful_child_without_public_readback_stays_unverified():
    saved = progress(); saved['status'] = 'completed'; saved['heartbeat_expires_at'] = None
    result = status.summarize('123', github('success'), saved, now=NOW)
    assert result['state'] == 'success'
    assert result['public_readback'] == 'not_checked'
    assert result['pending'] == ['Current public publication readback has not been checked']


@pytest.mark.parametrize('change', ['counter', 'elapsed', 'stage', 'time'])
def test_decreasing_monotonic_values_are_reported(change):
    before = progress(); after = deepcopy(before)
    after['updated_at'] = '2026-10-18T11:59:40Z'
    if change == 'counter':
        after['counters']['bytes_read'] -= 1
    elif change == 'elapsed':
        after['elapsed_seconds'] -= 1
    elif change == 'stage':
        after['completed'] -= 1
    else:
        after['updated_at'] = '2026-10-18T11:59:20Z'
    result = status.summarize('123', github(), after, now=NOW, previous=before)
    assert result['heartbeat']['state'] == 'invalid'
    assert result['heartbeat']['monotonicity'] == 'failed'


def test_stage_transition_may_restart_stage_counts():
    before = progress(); after = deepcopy(before)
    after.update(stage='write_tables', completed=0, stage_elapsed_seconds=0, elapsed_seconds=31,
                 updated_at='2026-10-18T11:59:40Z')
    result = status.summarize('123', github(), after, now=NOW, previous=before)
    assert result['heartbeat']['state'] == 'running'
    assert result['heartbeat']['monotonicity'] == 'checked'


def test_legacy_unbound_receipt_is_not_attributed_to_run(tmp_path):
    path = receipt(tmp_path)
    value = json.loads(path.read_text()); value['binding'] = {'runtime': '/old/local/run'}; write(path, value)
    result = status.summarize('123', github(), progress(), now=NOW, receipt=path)
    assert result['continuation']['state'] == 'unbound'
    assert result['accepted_outputs'] == []


def test_bound_publication_journal_is_recorded_but_not_current_readback(tmp_path):
    path = receipt(tmp_path)
    value = json.loads(path.read_text())
    preparation = write(tmp_path / 'preparation.json', {'binding': value['binding']})
    journal = tmp_path / 'journal'; journal.mkdir()
    first = write(journal / '00000000.json', {'sequence': 0, 'previous': None, 'event': 'attempt_started',
        'value': {'binding': {'preparation_sha256': sha256(preparation.read_bytes()).hexdigest()}}})
    write(journal / '00000001.json', {'sequence': 1, 'previous': sha256(first.read_bytes()).hexdigest(),
                                    'event': 'publication_completed', 'value': {'status': 'published'}})
    result = status.summarize('123', github('success'), progress(), now=NOW, receipt=path)
    assert result['continuation']['recorded_publication_status'] == 'published'
    assert result['public_readback'] == 'not_checked'
    first.write_text(first.read_text() + ' ')
    invalid = status.summarize('123', github('success'), progress(), now=NOW, receipt=path)
    assert invalid['accepted_outputs'] == []
    assert any('journal chain differs' in issue for issue in invalid['issues'])


def test_offline_command_reads_only_supplied_json_and_writes_nothing(tmp_path, monkeypatch, capsys):
    run_path = write(tmp_path / 'run.json', github('success'))
    heartbeat_path = write(tmp_path / 'progress.json', progress())
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    monkeypatch.setattr(status.subprocess, 'run', lambda *a, **kw: pytest.fail('Unexpected subprocess'))
    monkeypatch.setattr(status.urllib.request, 'urlopen', lambda *a, **kw: pytest.fail('Unexpected network'))
    assert status.main(['--run', '123', '--github-json', str(run_path), '--progress', str(heartbeat_path), '--json']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['state'] == 'success'
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_missing_or_foreign_github_run_leaves_everything_unattributed(tmp_path):
    other = github(); other['id'] = 999
    result = status.summarize('123', other, progress(), now=NOW, receipt=receipt(tmp_path))
    assert result['state'] == 'unknown'
    assert result['heartbeat'] is None
    assert result['accepted_outputs'] == []


def test_current_provenance_revision_and_incomplete_reconciliation_are_visible(tmp_path):
    path=receipt(tmp_path);value=json.loads(path.read_text())
    value['binding']['provenance_revision']=REVISION;value['binding']['code_runtime']={'implementation':'selective'}
    value['writes']={'viewer-publications/manifest.json':{'verified':False},'viewer-publications/releases/x/file':{'verified':True}}
    write(path,value)
    observed=status.continuation(path,('123','2',REVISION))
    local=observed['local_phase_observation']
    assert observed['state']=='bound' and local['next_incomplete_phase']=='publication'
    assert local['uncertain_writes']==['viewer-publications/manifest.json']
    assert local['recorded_verified_writes']==1 and local['remote_reconciliation']=='not_performed'


def test_unbound_local_recovery_phases_are_inspectable_without_run_attribution(tmp_path):
    path=receipt(tmp_path);value=json.loads(path.read_text())
    value['binding']={'batch':'local'};value['phases']={'catalog':{'files':{},'result':{}}}
    value['writes'] = {'viewer-publications/manifest.json': {'verified': False},
                       'viewer-publications/releases/x/file': {'verified': True}}
    write(path,value)
    observed=status.continuation(path,('123','2',REVISION))
    assert observed['state']=='unbound' and observed['accepted_outputs']==[]
    assert observed['local_phase_observation']['next_incomplete_phase']=='mappings'
    local = observed['local_phase_observation']
    assert local['recorded_writes'] == 2 and local['recorded_verified_writes'] == 1
    assert local['uncertain_writes'] == ['viewer-publications/manifest.json']
    assert local['remote_reconciliation'] == 'not_performed' and not local['integrity_rechecked']
    assert observed['public_readback'] == 'not_checked'


def test_incomplete_catalog_status_names_retained_evidence_without_mutation(tmp_path):
    path = receipt(tmp_path); value = json.loads(path.read_text())
    value.update(binding={'batch': 'local'}, phases={})
    write(path, value)
    build = tmp_path / 'build'; build.mkdir()
    (build / 'working.sqlite').write_bytes(b'retained incomplete SQLite')
    before = {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    observed = status.continuation(path, ('123', '2', REVISION))
    local = observed['local_phase_observation']
    assert local['next_incomplete_phase'] == 'catalog'
    assert local['catalog_build']['last_recorded_accepted_phase'] is None
    assert local['catalog_build']['retained_build_path'] == str(build)
    assert observed['state'] == 'unbound' and observed['accepted_outputs'] == []
    summary = status.summarize('123', github('failure'), progress(), now=NOW, receipt=path)
    assert str(build / 'working.sqlite') in status.format_status(summary)
    assert 'Last recorded accepted phase: none' in status.format_status(summary)
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


@pytest.mark.parametrize('bound', [False, True])
@pytest.mark.parametrize('writes', [[], {'key': None}, {'key': {}}, {'key': {'verified': 'false'}},
    {'key': {'verified': 0}}, {'': {'verified': False}}, {'x' * 2049: {'verified': False}}])
def test_continuation_rejects_malformed_or_excessive_local_writes_before_attribution(tmp_path, bound, writes):
    path = receipt(tmp_path); value = json.loads(path.read_text())
    if not bound:
        value['binding'] = {'batch': 'local'}
    value['writes'] = writes
    write(path, value)
    before = path.read_bytes()
    with pytest.raises(ValueError, match='writes malformed or exceeds inspection limit'):
        status.continuation(path, ('123', '2', REVISION))
    assert path.read_bytes() == before


def test_continuation_inspects_large_receipt_without_granting_readback(tmp_path):
    path = receipt(tmp_path); value = json.loads(path.read_text())
    value['writes'] = {str(i): {'verified': True, 'detail': 'x' * 200} for i in range(12000)}
    write(path, value)
    before = path.read_bytes()
    assert len(before) > status.MAX_JSON_BYTES
    result = status.continuation(path, ('123', '2', REVISION))
    assert result['local_phase_observation']['recorded_verified_writes'] == 12000
    assert result['public_readback'] == 'not_checked'
    assert path.read_bytes() == before


def test_continuation_enforces_shared_write_count_budget(tmp_path, monkeypatch):
    from viewer_publication import continuation as state
    monkeypatch.setattr(state, 'MAX_WRITES', 2)
    path = receipt(tmp_path); value = json.loads(path.read_text())
    value['writes'] = {str(i): {'verified': False} for i in range(3)}
    write(path, value)
    with pytest.raises(ValueError, match='writes malformed or exceeds inspection limit'):
        status.continuation(path, ('123', '2', REVISION))


def test_read_only_publication_command_emits_durable_pending_receipt(tmp_path,monkeypatch,capsys):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts/publication'))
    import viewer_publication.verify as publication_verification
    run_path=write(tmp_path/'run.json',github('success'))
    heartbeat_path=write(tmp_path/'heartbeat.json',progress())
    raw_path=write(tmp_path/'raw.json',{'catalog_id':'raw'})
    receipt_path=tmp_path/'verification.json'
    def live_observation(viewer_url, pages_url, descriptor, *, root):
        assert root == ROOT
        assert descriptor == ROOT / 'apps/site/document-review-publication.json'
        return {'fixture': True}
    monkeypatch.setattr(publication_verification,'live_observation',live_observation)
    monkeypatch.setattr(publication_verification,'verify',lambda *a,**kw:{'version':1,'status':'pending','checks':[{'check':'live_worker','state':'pending','detail':'fixture'}],'read_only':True})
    assert status.main(['--run','123','--github-json',str(run_path),'--progress',str(heartbeat_path),'--verify-publication','--raw-manifest',str(raw_path),'--verification-receipt',str(receipt_path),'--json'])==0
    durable=json.loads(receipt_path.read_text())
    assert durable['status']=='pending' and durable['read_only'] is True
    assert json.loads(capsys.readouterr().out)['publication_verification']['status']=='pending'


def test_local_event_status_reads_new_intent_without_mutation_or_checkpoint(tmp_path, monkeypatch):
    from viewer_publication.local import LocalContinuation
    run = LocalContinuation(tmp_path / 'attempt', {'batch': 'local'})
    key = 'viewer-publications/manifest.json'
    run.record('publication_write_intent', dict(key=key, bytes=3, sha256='a' * 64, if_none_match='*'))
    assert json.loads(run.path.read_bytes())['writes'] == {}
    before = {str(p): p.read_bytes() for p in run.root.iterdir()}
    monkeypatch.setattr(LocalContinuation, '__init__', lambda *args, **kwargs: pytest.fail('Status constructed mutable continuation'))
    observed = status.continuation(run.path, ('123', '2', REVISION))
    local = observed['local_phase_observation']
    assert local['uncertain_writes'] == [key] and local['recorded_writes'] == 1
    assert local['write_observation']['source'] == 'validated_local_events'
    assert local['write_observation']['recorded_events'] == 2
    assert local['remote_reconciliation'] == 'not_performed'
    assert observed['public_readback'] == 'not_checked' and observed['accepted_outputs'] == []
    assert before == {str(p): p.read_bytes() for p in run.root.iterdir()}
    run.path.unlink()
    assert status.continuation(run.path, ('123', '2', REVISION)) == observed
    with run.journal_path.open('ab') as stream: stream.write(b'partial')
    with pytest.raises(ValueError, match='Incomplete'):
        status.continuation(run.path, ('123', '2', REVISION))


@pytest.mark.parametrize('legacy_events', [False, True])
def test_local_checkpoint_status_explicitly_marks_latest_event_state_unknown(tmp_path, legacy_events):
    path = receipt(tmp_path); value = json.loads(path.read_text())
    value['binding'] = {'batch': 'local'}
    write(path, value)
    if legacy_events:
        (tmp_path / 'events.jsonl').write_text(json.dumps({'event': 'failed', 'value': {}}) + '\n')
    observed = status.continuation(path, ('123', '2', REVISION))
    source = observed['local_phase_observation']['write_observation']
    assert source['source'] == 'checkpoint_only'
    assert 'unknown' in source['latest_event_state'] and 'stale' in source['latest_event_state']
    summary = status.summarize('123', github('failure'), progress(), now=NOW, receipt=path)
    assert 'checkpoint write counts may be stale' in status.format_status(summary)


def test_reconciliation_status_remains_observation_without_mutation_or_public_proof(tmp_path):
    from viewer_publication.continuation import Continuation
    from viewer_publication.reconciliation import ReconciliationProgress, NEXT_CHECK
    run = Continuation(tmp_path / 'attempt', {'batch': 'local'})
    observer = ReconciliationProgress(run.root, run.value['binding'])
    observer(dict(state='reading', next_check=NEXT_CHECK['reading'], key='viewer-publications/object',
        object_index=1, total_objects=2, checked_objects=0, bytes_read=4, declared_bytes=8))
    before = {str(p): p.read_bytes() for p in run.root.iterdir()}
    result = status.continuation(run.path, ('123', '2', REVISION))
    last = result['local_phase_observation']['last_reconciliation_observation']
    assert last['state'] == 'reading' and last['bytes_read'] == 4
    assert not last['resume_authorized'] and not last['current_readback_proof']
    assert result['public_readback'] == 'not_checked' and result['accepted_outputs'] == []
    summary = status.summarize('123', github('failure'), progress(), now=NOW, receipt=run.path)
    assert 'Last recorded reconciliation observation: reading' in status.format_status(summary)
    assert NEXT_CHECK['reading'] in status.format_status(summary)
    assert before == {str(p): p.read_bytes() for p in run.root.iterdir()}
    path = run.root / 'reconciliation-progress.json'
    value = json.loads(path.read_bytes()); value['binding_sha256'] = '0' * 64
    path.write_text(json.dumps(value))
    invalid = status.continuation(run.path, ('123', '2', REVISION))
    assert invalid['local_phase_observation']['last_reconciliation_observation']['state'] == 'unavailable'
    assert invalid['public_readback'] == 'not_checked'
