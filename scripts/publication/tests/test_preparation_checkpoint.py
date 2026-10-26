"""Interrupted work has separate custody and never authorizes publication."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import time

import pytest

from viewer_publication import resume
from test_workflow_resume import execute, workflow

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


def fake_child(tmp_path, monkeypatch, *, ignore_interrupt=False, fail=False):
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
    db=sqlite3.connect(root/'publication.renderer-upgrade/checkpoint.sqlite')
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
state_dir=root/'publication.renderer-upgrade'
state_dir.mkdir()
db=sqlite3.connect(state_dir/'checkpoint.sqlite')
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
        .replace('IGNORE', repr(ignore_interrupt)).replace('FAIL', repr(fail)))
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
    assert 'publication.renderer-upgrade/checkpoint.sqlite' in receipt['files']
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


def test_workflow_checkpoints_before_failure_and_cannot_publish_partial_work():
    job = workflow()['jobs']['publish']
    steps = job['steps']
    prepare = next(i for i, s in enumerate(steps) if s.get('id') == 'prepare')
    checkpoint = next(i for i, s in enumerate(steps) if s.get('id') == 'checkpoint')
    marker = next(i for i, s in enumerate(steps) if s.get('name', '').startswith('Require an explicit new run'))
    accepted = next(i for i, s in enumerate(steps) if s.get('id') == 'accepted')
    restore = next(i for i, s in enumerate(steps) if s.get('name') == 'Restore explicitly selected incomplete preparation')
    assert restore < prepare < checkpoint < marker < accepted
    assert job['timeout-minutes'] == '180'
    assert steps[checkpoint]['if'] == "steps.prepare.outputs.status == 'preparation_checkpoint'"
    assert steps[checkpoint]['with']['path'] == 'viewer-preparation/'
    assert steps[checkpoint]['with']['include-hidden-files'] == 'true'
    assert steps[accepted]['if'] == "steps.prepare.outputs.status == 'prepared'"
    for name in ('Verify complete preparation inventory', 'Publish accepted preparation'):
        step = next(s for s in steps if s.get('name') == name)
        assert step['if'] == "steps.prepare.outputs.status == 'prepared' || steps.resume.outputs.resume == 'true'"


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
