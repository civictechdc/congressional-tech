"""Interrupted work has separate custody and never authorizes publication."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import time

import pytest

from viewer_publication import resume
from test_workflow_resume import execute

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('workflow_preparation',
    ROOT / 'scripts/publication/prepare_workflow_resume.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
REVISION = 'a' * 40


def binding():
    return dict(provenance_revision=REVISION, code_runtime={'sha256': 'b' * 64},
        source={'value': {'generation': 'fixture'}, 'etag': 'source-etag'},
        viewer={'value': None}, accepted={'value': None}, native_execution={'fixture': {'sha256': 'c' * 64}},
        run_id='11', run_attempt='1')


def partial(root):
    root.mkdir()
    (root / 'continuation.json').write_text(json.dumps(dict(version=1, binding=binding(),
        phases={}, writes={}, versions={})))
    (root / 'publication').mkdir()
    (root / 'publication' / 'output.partial').write_bytes(b'not accepted output')
    (root / 'publication.renderer-upgrade').mkdir()
    (root / 'publication.renderer-upgrade' / 'stages.sqlite').write_bytes(b'renderer state')
    (root / 'publication.renderer-upgrade' / 'checkpoint.sqlite-wal').write_bytes(b'journal')
    (root / '.hidden').write_bytes(b'retained hidden state')
    return root


def select(root):
    result = resume.save_preparation_checkpoint(root, revision=REVISION,
        run_id='22', run_attempt='2', repository='fixture/repo')
    descriptor = resume.preparation_checkpoint_descriptor(root, artifact_id='456', artifact_digest='sha256:' + 'd' * 64)
    assert result['checkpoint_artifact_name'] == descriptor['artifact_name']
    return descriptor


def evidence(descriptor):
    metadata = dict(id=456, expired=False, name=descriptor['artifact_name'], digest='sha256:' + 'd' * 64,
        workflow_run={'id': int(descriptor['run_id'])})
    run = dict(id=int(descriptor['run_id']), head_sha=descriptor['workflow_revision'], head_repository={'full_name': 'fixture/repo'})
    return dict(metadata=metadata, run=run, revision=REVISION)


def test_checkpoint_admission_preserves_distinct_origin_and_artifact_producer(tmp_path):
    root = partial(tmp_path / 'work')
    descriptor = select(root)
    receipt = resume.verify_preparation_checkpoint(root, descriptor, **evidence(descriptor))
    assert descriptor['run_id'] == '22' and descriptor['run_attempt'] == '2'
    assert descriptor['original_run_id'] == '11' and descriptor['original_run_attempt'] == '1'
    assert receipt['status'] == 'incomplete_preparation'
    result, output = execute(tmp_path, json.dumps(descriptor))
    assert result.returncode == 0, result.stderr
    assert output.read_text().splitlines() == ['resume=false', 'preparation_resume=true',
        'revision=' + REVISION, 'run_id=22', 'artifact_id=456']
    assert not (root / 'preparation.json').exists()
    assert not (root / 'prepared-result.json').exists()
    with pytest.raises(ValueError, match='preparation-only'):
        resume.parse_resume_descriptor(json.dumps(descriptor).encode())
    assert resume.parse_resume_descriptor(json.dumps(descriptor).encode(), allow_preparation=True) == descriptor


def test_publication_cli_refuses_preparation_descriptor_before_client_creation(tmp_path, monkeypatch):
    from viewer_publication import publication_cli
    root = partial(tmp_path / 'work')
    descriptor = select(root)
    path = tmp_path / 'descriptor.json'
    path.write_text(json.dumps(descriptor))
    def forbidden_client():
        raise AssertionError('Preparation-only descriptor reached a publication client')
    monkeypatch.setattr(publication_cli, 'make_client', forbidden_client)
    with pytest.raises(ValueError, match='preparation-only'):
        publication_cli.main(object(), ['publish', '--directory', str(root), '--resume',
            '--resume-descriptor', str(path)])


@pytest.mark.parametrize('change', ['artifact-id', 'artifact-name', 'artifact-digest', 'artifact-run',
    'expired', 'run-id', 'run-revision', 'run-repository', 'checkout-revision', 'origin', 'bytes', 'extra-file', 'missing-file'])
def test_checkpoint_rejects_changed_custody_origin_and_saved_bytes(tmp_path, change):
    root = partial(tmp_path / 'work')
    descriptor = select(root)
    options = evidence(descriptor)
    if change.startswith('artifact-'):
        key = {'artifact-id': 'id', 'artifact-name': 'name', 'artifact-digest': 'digest', 'artifact-run': 'workflow_run'}[change]
        options['metadata'][key] = {'id': 99} if key == 'workflow_run' else 'different'
    elif change == 'expired': options['metadata']['expired'] = True
    elif change == 'run-id': options['run']['id'] = 99
    elif change == 'run-revision': options['run']['head_sha'] = 'f' * 40
    elif change == 'run-repository': options['run']['head_repository']['full_name'] = 'other/repo'
    elif change == 'checkout-revision': options['revision'] = 'f' * 40
    elif change == 'origin': descriptor['original_run_id'] = '999'
    elif change == 'bytes': (root / 'publication' / 'output.partial').write_bytes(b'changed')
    elif change == 'extra-file': (root / 'extra').write_text('unexpected')
    elif change == 'missing-file': (root / 'publication.renderer-upgrade' / 'checkpoint.sqlite-wal').unlink()
    with pytest.raises(ValueError):
        resume.verify_preparation_checkpoint(root, descriptor, **options)


def test_checkpoint_rejects_symlinks_and_publication_writes(tmp_path):
    root = partial(tmp_path / 'work')
    (root / 'link').symlink_to(root / 'continuation.json')
    with pytest.raises(ValueError, match='symbolic'):
        select(root)
    (root / 'link').unlink()
    path = root / 'continuation.json'
    state = json.loads(path.read_bytes())
    state['writes']['unexpected'] = {}
    path.write_text(json.dumps(state))
    with pytest.raises(ValueError, match='publication writes'):
        select(root)


def fake_child(tmp_path, monkeypatch, *, ignore_interrupt=False, fail=False, before_state=False):
    checkout = tmp_path / 'checkout'
    script = checkout / 'scripts/publication/publish-viewer-r2.py'
    script.parent.mkdir(parents=True)
    script.write_text('''import json, os, signal, sqlite3, sys, time
from pathlib import Path
args=sys.argv
root=Path(args[args.index('--directory')+1])
report=Path(args[args.index('--report')+1])
if '--resume-preparation' in args:
    state=json.loads((root/'continuation.json').read_bytes())
    assert state['binding']['run_id']=='11'
    db=sqlite3.connect(root/'publication.renderer-upgrade/stages.sqlite')
    assert db.execute('select value from work').fetchone()==('saved unit',)
    db.close()
    if os.environ.get('STOP_AGAIN')=='true':
        try:
            while True: time.sleep(.01)
        except KeyboardInterrupt:
            sys.exit(130)
    result={'status':'prepared','artifact_name':'viewer-prepared-'+os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT']+'-'+'e'*64}
    report.write_text(json.dumps(result))
    sys.exit(0)
root.mkdir()
(root/'continuation.json').write_text(json.dumps(STATE))
(root/'publication').mkdir()
(root/'publication/unit.partial').write_bytes(b'saved partial')
if BEFORE_RENDERER:
    try:
        while True: time.sleep(.01)
    except KeyboardInterrupt:
        sys.exit(130)
state_dir=root/'publication.renderer-upgrade'
state_dir.mkdir()
db=sqlite3.connect(state_dir/'stages.sqlite')
db.execute('pragma journal_mode=WAL')
db.execute('create table work(value text)')
db.execute("insert into work values ('saved unit')")
db.commit()
if IGNORE: signal.signal(signal.SIGINT,signal.SIG_IGN)
if FAIL: sys.exit(7)
try:
    while True: time.sleep(.01)
except KeyboardInterrupt:
    pass
finally:
    db.close()
sys.exit(130)
'''.replace('STATE', repr(dict(version=1, binding=binding(), phases={}, writes={}, versions={})))
        .replace('IGNORE', repr(ignore_interrupt)).replace('FAIL', repr(fail))
        .replace('BEFORE_RENDERER', repr(before_state)))
    monkeypatch.setattr(runner, 'ROOT', checkout)
    monkeypatch.setattr(runner, 'revision', lambda: REVISION)
    (tmp_path / 'publication-job-start.json').write_text(json.dumps({'time': time.time()}))
    environment = dict(os.environ, RUNNER_TEMP=str(tmp_path), DOCSPEC_RUNTIME_CONFIG='fixture-config',
        GITHUB_RUN_ID='22', GITHUB_RUN_ATTEMPT='2', GITHUB_REPOSITORY='fixture/repo', GITHUB_SHA=REVISION)
    return environment


def test_real_subprocess_stop_artifact_round_trip_and_explicit_restore(tmp_path, monkeypatch):
    environment = fake_child(tmp_path, monkeypatch)
    root, report = tmp_path / 'work', tmp_path / 'report.json'
    result = runner.run_preparation(root, report, environment=environment, deadline_seconds=1, grace_seconds=3)
    assert result['status'] == 'preparation_checkpoint'
    descriptor = resume.preparation_checkpoint_descriptor(root, artifact_id='456', artifact_digest='d' * 64)
    archive = shutil.make_archive(str(tmp_path / 'artifact'), 'zip', root_dir=root)
    restored = tmp_path / 'restored'
    shutil.unpack_archive(archive, restored)
    receipt = resume.verify_preparation_checkpoint(restored, descriptor, **evidence(descriptor))
    assert 'publication.renderer-upgrade/stages.sqlite' in receipt['files']
    assert 'publication/unit.partial' in receipt['files']
    (tmp_path / 'viewer-resume.json').write_text(json.dumps(descriptor))
    monkeypatch.setattr(runner, 'github_json', lambda route:
        evidence(descriptor)['metadata' if '/artifacts/' in route else 'run'])
    environment.update(PREPARATION_RESUME='true', GITHUB_RUN_ID='33', GITHUB_RUN_ATTEMPT='1')
    environment['STOP_AGAIN']='true'
    (tmp_path / 'publication-job-start.json').write_text(json.dumps({'time': time.time()}))
    second = runner.run_preparation(restored, report, environment=environment, deadline_seconds=1, grace_seconds=3)
    assert second['status'] == 'preparation_checkpoint'
    second_descriptor = resume.preparation_checkpoint_descriptor(restored, artifact_id='789', artifact_digest='e' * 64)
    assert second_descriptor['original_run_id'] == '11' and second_descriptor['run_id'] == '33'
    second_evidence = evidence(second_descriptor)
    second_evidence['metadata'].update(id=789, digest='e' * 64)
    resume.verify_preparation_checkpoint(restored, second_descriptor, **second_evidence)
    (tmp_path / 'viewer-resume.json').write_text(json.dumps(second_descriptor))
    monkeypatch.setattr(runner, 'github_json', lambda route:
        second_evidence['metadata' if '/artifacts/' in route else 'run'])
    environment.update(STOP_AGAIN='false', GITHUB_RUN_ID='44')
    result = runner.run_preparation(restored, report, environment=environment, deadline_seconds=10)
    assert result['status'] == 'prepared'
    assert result['artifact_name'].startswith('viewer-prepared-44-1-')


@pytest.mark.parametrize('ignore_interrupt,fail', [(True, False), (False, True)])
def test_forced_stop_or_ordinary_failure_cannot_create_checkpoint(tmp_path, monkeypatch, ignore_interrupt, fail):
    environment = fake_child(tmp_path, monkeypatch, ignore_interrupt=ignore_interrupt, fail=fail)
    root = tmp_path / 'work'
    with pytest.raises(ValueError, match='did not stop gracefully|failed before'):
        runner.run_preparation(root, tmp_path / 'report', environment=environment,
            deadline_seconds=1, grace_seconds=.1)
    assert not (root / resume.CHECKPOINT_FILE).exists()


def boundary_child(tmp_path, monkeypatch):
    environment = fake_child(tmp_path, monkeypatch)
    (runner.ROOT / 'scripts/publication/publish-viewer-r2.py').write_text('''
import hashlib, json, os, signal, sys, time
from pathlib import Path
args=sys.argv
root=Path(args[args.index('--directory')+1])
report=Path(args[args.index('--report')+1])
if args[1]=='verify-prepared':
    (Path(__file__).parents[2]/'verified-boundary').touch()
    receipt=json.loads((root/'preparation.json').read_bytes())
    assert hashlib.sha256((root/'payload').read_bytes()).hexdigest()==receipt['payload_sha256']
    result=json.loads((root/'prepared-result.json').read_bytes())
    report.write_text(json.dumps(dict(result,status='verified_prepared')))
    sys.exit(0)
root.mkdir()
(root/'payload').write_bytes(b'completed output')
def completed(*_):
    producer={'run_id':os.environ['GITHUB_RUN_ID'],'run_attempt':os.environ['GITHUB_RUN_ATTEMPT']}
    if os.environ.get('OLD_PRODUCER')=='true': producer={'run_id':'11','run_attempt':'1'}
    receipt={'binding':BINDING,'artifact_producer':producer,'payload_sha256':hashlib.sha256((root/'payload').read_bytes()).hexdigest()}
    raw=json.dumps(receipt).encode()
    (root/'preparation.json').write_bytes(raw)
    suffix=producer['run_id']+'-'+producer['run_attempt']+'-'+hashlib.sha256(raw).hexdigest()
    result={'status':'prepared','artifact_name':'viewer-prepared-'+suffix,'attempt':suffix}
    (root/'prepared-result.json').write_text(json.dumps(result))
    report.write_text(json.dumps({'status':'failed','error':'interrupt after result'}))
    if os.environ.get('CORRUPT')=='true': (root/'payload').write_bytes(b'altered output')
    sys.exit(int(os.environ.get('EXIT_CODE','130')))
signal.signal(signal.SIGINT,completed)
while True: time.sleep(.01)
'''.replace('BINDING', repr(binding())))
    return environment


@pytest.mark.parametrize('exit_code', ['0', '130'])
def test_completed_pair_at_bounded_stop_uses_complete_verifier_and_current_producer(tmp_path, monkeypatch, exit_code):
    environment = boundary_child(tmp_path, monkeypatch)
    environment['EXIT_CODE'] = exit_code
    root, report = tmp_path / 'work', tmp_path / 'report.json'
    result = runner.run_preparation(root, report, environment=environment, deadline_seconds=1, grace_seconds=3)
    assert result['status'] == 'prepared'
    assert result['artifact_name'].startswith('viewer-prepared-22-2-')
    assert json.loads(report.read_bytes()) == result
    assert (runner.ROOT / 'verified-boundary').is_file()
    assert not (root / resume.CHECKPOINT_FILE).exists()


@pytest.mark.parametrize('problem', ['OLD_PRODUCER', 'CORRUPT'])
def test_completed_pair_at_stop_cannot_hide_old_custody_or_failed_verification(tmp_path, monkeypatch, problem):
    environment = boundary_child(tmp_path, monkeypatch)
    environment[problem] = 'true'
    root = tmp_path / 'work'
    with pytest.raises((ValueError, runner.subprocess.CalledProcessError)):
        runner.run_preparation(root, tmp_path / 'report', environment=environment, deadline_seconds=1, grace_seconds=3)
    assert not (root / resume.CHECKPOINT_FILE).exists()


def test_exit_between_timeout_and_signal_still_verifies_complete_pair(tmp_path, monkeypatch):
    environment = boundary_child(tmp_path, monkeypatch)
    root = tmp_path / 'work'
    root.mkdir()
    (root / 'payload').write_bytes(b'completed output')
    receipt = dict(binding=binding(), artifact_producer={'run_id':'22','run_attempt':'2'},
        payload_sha256=resume.file_digest(root / 'payload'))
    (root / 'preparation.json').write_text(json.dumps(receipt))
    (root / 'prepared-result.json').write_text(json.dumps(dict(status='prepared', artifact_name='viewer-prepared-22-2-' + 'e' * 64)))
    real_popen = runner.subprocess.Popen
    class JustCompleted:
        pid = 987654321
        returncode = 0
        first_wait = True
        def wait(self, timeout):
            if self.first_wait:
                self.first_wait = False
                raise runner.subprocess.TimeoutExpired('prepare', timeout)
            return 0
    monkeypatch.setattr(runner.subprocess, 'Popen', lambda command, **kwargs:
        JustCompleted() if command[2] == 'prepare' else real_popen(command, **kwargs))
    def vanished(*_): raise ProcessLookupError()
    monkeypatch.setattr(runner.os, 'killpg', vanished)
    result = runner.run_preparation(root, tmp_path / 'report', environment=environment)
    assert result['status'] == 'prepared'
    assert (runner.ROOT / 'verified-boundary').is_file()
    assert not (root / resume.CHECKPOINT_FILE).exists()


def test_stop_before_renderer_initialization_is_diagnostic_only(tmp_path, monkeypatch):
    environment = fake_child(tmp_path, monkeypatch, before_state=True)
    root = tmp_path / 'work'
    with pytest.raises(ValueError, match='Diagnostic-only stop'):
        runner.run_preparation(root, tmp_path / 'report', environment=environment, deadline_seconds=1, grace_seconds=3)
    assert (root / 'continuation.json').is_file()
    assert not (root / resume.CHECKPOINT_FILE).exists()


def test_complete_pairs_cannot_be_saved_or_restored_as_partial_checkpoints(tmp_path):
    root = partial(tmp_path / 'work')
    descriptor = select(root)
    for name in ('preparation.json', 'prepared-result.json'):
        (root / name).write_text('{}')
    with pytest.raises(ValueError, match='Complete preparation'):
        select(root)
    with pytest.raises(ValueError, match='Complete preparation'):
        resume.verify_preparation_checkpoint(root, descriptor, **evidence(descriptor))


def test_verified_prepared_phase_can_resume_without_renderer_state(tmp_path):
    root = partial(tmp_path / 'work')
    (root / 'publication.renderer-upgrade/stages.sqlite').unlink()
    path = root / 'continuation.json'
    state = json.loads(path.read_bytes())
    state['phases']['prepared'] = {'files': {}, 'result': {}}
    path.write_text(json.dumps(state))
    descriptor = select(root)
    assert resume.verify_preparation_checkpoint(root, descriptor, **evidence(descriptor))


def test_checkpoint_bounds_admit_large_binding_and_auxiliary_files(tmp_path):
    assert resume.MAX_CHECKPOINT_BYTES == 128 * 1024**2
    assert resume.MAX_CHECKPOINT_FILES > 131072
    path = tmp_path / 'large-binding.json'
    path.write_text(json.dumps({'binding': 'x' * (33 * 1024**2)}))
    assert len(resume.read_checkpoint_json(path)['binding']) == 33 * 1024**2


@pytest.mark.parametrize('restore_seconds', [70, 110])
def test_checkpoint_verification_consumes_the_elapsed_job_budget(tmp_path, monkeypatch, restore_seconds):
    from types import SimpleNamespace
    environment = fake_child(tmp_path, monkeypatch)
    environment['PREPARATION_RESUME'] = 'true'
    clock = SimpleNamespace(now=100)
    monkeypatch.setattr(runner, 'time', SimpleNamespace(time=lambda: clock.now))
    (tmp_path / 'publication-job-start.json').write_text(json.dumps({'time': clock.now}))
    def restore(*_):
        clock.now += restore_seconds
    monkeypatch.setattr(runner, 'verify_checkpoint', restore)
    waits, launches = [], []
    class Process:
        pid = 987654321
        returncode = 0
        def wait(self, timeout): waits.append(timeout)
    def launch(*args, **kwargs):
        launches.append(args)
        return Process()
    monkeypatch.setattr(runner.subprocess, 'Popen', launch)
    def vanished(*_): raise ProcessLookupError()
    monkeypatch.setattr(runner.os, 'killpg', vanished)
    report = tmp_path / 'report'
    report.write_text(json.dumps({'status': 'prepared'}))
    if restore_seconds > 100:
        with pytest.raises(ValueError, match='budget exhausted'):
            runner.run_preparation(tmp_path / 'work', report, environment=environment, deadline_seconds=100)
        assert not launches
    else:
        runner.run_preparation(tmp_path / 'work', report, environment=environment, deadline_seconds=100)
        assert waits == [100 - restore_seconds]






def test_original_code_checkout_can_differ_from_new_dispatch_workflow_head(tmp_path):
    root = partial(tmp_path / 'work')
    workflow_revision = 'e' * 40
    resume.save_preparation_checkpoint(root, revision=REVISION, run_id='22', run_attempt='2',
        repository='fixture/repo', workflow_revision=workflow_revision)
    descriptor = resume.preparation_checkpoint_descriptor(root, artifact_id='456', artifact_digest='d' * 64)
    options = evidence(descriptor)
    options['run']['head_sha'] = workflow_revision
    assert resume.verify_preparation_checkpoint(root, descriptor, **options)['binding']['provenance_revision'] == REVISION
    # Receipt custody can represent this case, but workflow admission refuses
    # producing accepted output under a different head until v1 discovery can
    # identify an effective checkout revision independently of run.head_sha.
    result, output = execute(tmp_path, json.dumps(descriptor), workflow_revision=workflow_revision)
    assert result.returncode != 0 and 'Dispatch preparation resume at the original code revision' in result.stderr
    assert not output.exists()


@pytest.mark.parametrize('field,value', [('kind', 'accepted'), ('version', 3), ('original_run_id', 'bad'),
    ('original_run_attempt', None), ('run_attempt', '3')])
def test_invalid_partial_descriptors_never_authorize_checkout(tmp_path, field, value):
    root = partial(tmp_path / 'work')
    descriptor = select(root)
    descriptor[field] = value
    result, output = execute(tmp_path, json.dumps(descriptor))
    assert result.returncode != 0
    assert not output.exists()


def test_retired_checkpoint_workflow_has_no_restore_or_publish_path():
    import yaml
    assert not (ROOT / '.github/workflows/publish-filename-viewer.yml').exists()
    value = yaml.load((ROOT / '.github/workflows/archive-jobs.yml').read_text(), Loader=yaml.BaseLoader)
    steps = value['jobs']['publish']['steps']
    assert not any(step.get('uses', '').startswith('actions/download-artifact') for step in steps)
    assert 'resume_descriptor' not in json.dumps(value)
    assert not any('prepare_workflow_resume.py' in step.get('run', '') for step in steps)


@pytest.mark.parametrize('resume_publication', [False, True])
def test_publish_rejects_partial_preparation_before_artifact_or_remote_access(tmp_path, resume_publication):
    from viewer_publication import attempt

    root = partial(tmp_path / 'incomplete')

    def forbidden_artifact(*args):
        pytest.fail('Incomplete preparation reached artifact admission')

    # Both workflow publish branches enter this maintained function. Its full
    # prepared-inventory check must run before any remote or artifact operation.
    with pytest.raises(FileNotFoundError) as error:
        attempt.publish(object(), object(), root, artifact={}, public_url='unused',
            resume=resume_publication, attempt='original' if resume_publication else None,
            verify_artifact=forbidden_artifact)
    assert Path(error.value.filename) == root / 'preparation.json'

