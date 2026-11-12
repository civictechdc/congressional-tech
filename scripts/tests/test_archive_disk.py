"""Whole-operation admission and spill lifetimes, using only private fixtures."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


disk = load('archive_disk')
nightly = load('nightly_publish')


def budget(tmp_path, roots=('work',), **changes):
    entry = dict(revision='a' * 40, measurement='owned fixture; not a production measurement',
                 workload='bounded fixture', filesystems=[dict(roots=list(roots), peak_additional_bytes=40,
                                                             headroom_bytes=20)])
    entry.update(changes)
    path = tmp_path / 'budgets.json'
    path.write_text(json.dumps(dict(version=1, operations={'fixture': entry})))
    return path


def test_admission_requires_the_complete_peak_plus_headroom_on_actual_volume(tmp_path, monkeypatch):
    roots = dict(work=tmp_path / 'not-created/work', spill=tmp_path / 'not-created/spill')
    path = budget(tmp_path, roots)
    monkeypatch.setattr(disk.shutil, 'disk_usage', lambda _: SimpleNamespace(free=59))
    result = disk.admit(path, 'fixture', roots, commit='a' * 40, floor=20)
    assert result['status'] == 'refused' and result['filesystems'][0]['required_bytes'] == 60
    assert not (tmp_path / 'not-created').exists()
    monkeypatch.setattr(disk.shutil, 'disk_usage', lambda _: SimpleNamespace(free=60))
    assert disk.admit(path, 'fixture', roots, commit='a' * 40, floor=20)['status'] == 'admitted'


@pytest.mark.parametrize('change,match', [
    ({'revision': 'b' * 40}, 'revision'), ({'measurement': ''}, 'measurement'),
    ({'filesystems': []}, 'filesystems'),
    ({'filesystems': [dict(roots=['work'], peak_additional_bytes=True, headroom_bytes=20)]}, 'measured'),
    ({'filesystems': [dict(roots=['work'], peak_additional_bytes=40, headroom_bytes=19)]}, 'headroom'),
])
def test_unknown_stale_or_unbounded_budget_refuses(tmp_path, change, match):
    with pytest.raises(ValueError, match=match):
        disk.admit(budget(tmp_path, **change), 'fixture', dict(work=tmp_path), commit='a' * 40, floor=20)


def test_budget_carries_to_descendants_that_keep_resource_pins(tmp_path, monkeypatch):
    """Every ticket push used to refuse the nightly; only resource pins should."""
    repo = tmp_path / 'repo'; repo.mkdir()
    def git(*args):
        return subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', *args], cwd=repo,
                              check=True, capture_output=True, text=True).stdout.strip()
    def commit(path, text):
        (repo / path).parent.mkdir(parents=True, exist_ok=True); (repo / path).write_text(text)
        git('add', '-A'); git('commit', '-qm', path)
        return git('rev-parse', 'HEAD')
    git('init', '-q')
    measured = commit('uv.lock', 'v1')
    ticket = commit('.tickets/t.md', 'note')
    lock = commit('uv.lock', 'v2')
    git('checkout', '-q', '-b', 'side', measured)
    side = commit('docs/x.md', 'side')
    monkeypatch.setattr(disk.shutil, 'disk_usage', lambda _: SimpleNamespace(free=60))
    path = budget(tmp_path, revision=measured)
    roots = dict(work=tmp_path)
    result = disk.admit(path, 'fixture', roots, commit=ticket, floor=20, root=repo)
    assert result['status'] == 'admitted' and result['budget_revision'] == measured
    assert disk.admit(path, 'fixture', roots, commit=side, floor=20, root=repo)['status'] == 'admitted'
    with pytest.raises(ValueError, match='revision differs'):
        disk.admit(path, 'fixture', roots, commit=lock, floor=20, root=repo)
    with pytest.raises(ValueError, match='revision differs'):  # no checkout to compare
        disk.admit(path, 'fixture', roots, commit=ticket, floor=20)
    with pytest.raises(ValueError, match='revision differs'):  # not a descendant
        disk.admit(budget(tmp_path, revision=ticket), 'fixture', roots, commit=side, floor=20, root=repo)


def test_missing_operation_or_writing_root_refuses(tmp_path):
    path = budget(tmp_path)
    with pytest.raises(ValueError, match='unavailable'):
        disk.admit(path, 'resume', dict(work=tmp_path), commit='a' * 40)
    with pytest.raises(ValueError, match='every writing root'):
        disk.admit(path, 'fixture', dict(work=tmp_path, extra=tmp_path), commit='a' * 40, floor=20)


def test_each_filesystem_has_its_own_qualified_peak(tmp_path, monkeypatch):
    other = tmp_path / 'other'; other.mkdir()
    roots = dict(work=tmp_path, spill=other)
    # Replace only the filesystem probe, retaining real path existence checks.
    class Probe:
        def __init__(self, name): self.name = name
        def stat(self): return SimpleNamespace(st_dev=2 if self.name == 'other' else 1)
        def __str__(self): return self.name
    monkeypatch.setattr(disk, 'existing_parent', lambda path: Probe(Path(path).name))
    monkeypatch.setattr(disk.shutil, 'disk_usage', lambda path: SimpleNamespace(free=59 if str(path) == 'other' else 100))
    path = budget(tmp_path, roots)
    with pytest.raises(ValueError, match='actual filesystem'):
        disk.admit(path, 'fixture', roots, commit='a' * 40, floor=20)
    groups = [dict(roots=[name], peak_additional_bytes=40, headroom_bytes=20) for name in roots]
    path = budget(tmp_path, filesystems=groups)
    result = disk.admit(path, 'fixture', roots, commit='a' * 40, floor=20)
    assert result['status'] == 'refused' and len(result['filesystems']) == 2
    monkeypatch.setattr(disk, 'existing_parent', lambda _: Probe('same'))
    with pytest.raises(ValueError, match='exactly once'):
        disk.admit(path, 'fixture', roots, commit='a' * 40, floor=20)


def test_python_temporary_files_need_capacity_separate_from_runner_reports(tmp_path, monkeypatch):
    report_temp = tmp_path / 'runner-temp'
    python_temp = tmp_path / 'python-temp'
    spec = tmp_path / 'backfill.json'
    spec.write_text(json.dumps(dict(work=str(tmp_path / 'work'))))
    monkeypatch.setattr(disk.tempfile, 'gettempdir', lambda: str(python_temp))
    mode, roots = disk.job_roots('backfill', spec, temp=report_temp, env={})
    assert mode == 'backfill' and roots['temp'] == report_temp and roots['python_temp'] == python_temp

    class Probe:
        def __init__(self, path): self.python_temp = path == python_temp
        def stat(self): return SimpleNamespace(st_dev=2 if self.python_temp else 1)
    monkeypatch.setattr(disk, 'existing_parent', lambda path: Probe(path))
    monkeypatch.setattr(disk.shutil, 'disk_usage', lambda path: SimpleNamespace(free=59 if path.python_temp else 100))
    groups = [dict(roots=['work', 'temp'], peak_additional_bytes=40, headroom_bytes=20)]
    with pytest.raises(ValueError, match='every writing root: python_temp'):
        disk.admit(budget(tmp_path, filesystems=groups), 'fixture', roots, commit='a' * 40, floor=20)
    groups.append(dict(roots=['python_temp'], peak_additional_bytes=40, headroom_bytes=20))
    result = disk.admit(budget(tmp_path, filesystems=groups), 'fixture', roots, commit='a' * 40, floor=20)
    assert result['status'] == 'refused' and result['filesystems'][1]['free_bytes'] == 59
    monkeypatch.setattr(disk.shutil, 'disk_usage', lambda _: SimpleNamespace(free=60))
    assert disk.admit(budget(tmp_path, filesystems=groups), 'fixture', roots, commit='a' * 40, floor=20)['status'] == 'admitted'


def candidate(tmp_path):
    root = tmp_path / '.cache/archive-release/nightly/candidate'
    scratch = root / 'archive-publish/model-attempts/attempt-fixture/scratch'
    spill = scratch / 'native'; spill.mkdir(parents=True)
    (spill / 'abandoned-run.arrow').write_bytes(b'disposable')
    inputs = scratch / 'prepared.parquet'; inputs.write_bytes(b'expensive input')
    result = scratch / 'result.json'; result.write_bytes(b'expensive result')
    release = scratch.parent / 'release'; release.mkdir()
    manifest = release / 'manifest.json'; manifest.write_bytes(b'expensive manifest')
    job = scratch / 'job.json'
    job.write_text(json.dumps(dict(scratch=str(spill), inputs=[dict(path=str(inputs))],
                                  outputs=[dict(path=str(release / 'documents.parquet'))])))
    checkpoint = root / 'archive-publish/completed-model.json'
    checkpoint.write_text(json.dumps(dict(stage=dict(scratch=str(scratch), output=str(release)),
                                          result_pin=dict(path=str(result)), manifest_pin=dict(path=str(manifest)))))
    return root, spill, job, [inputs, result, manifest, checkpoint]


def test_locked_cleanup_retires_only_declared_spill_and_preserves_resume_inputs(tmp_path):
    root, spill, job, protected = candidate(tmp_path)
    before = {path: path.read_bytes() for path in protected}
    unrelated = root / 'unregistered/native'; unrelated.mkdir(parents=True)
    (unrelated / 'keep').write_bytes(b'unknown ownership')
    report = nightly.clean_native_spill(tmp_path)
    assert report == dict(status='dry-run', paths=[str(spill)]) and spill.exists()
    assert nightly.clean_native_spill(tmp_path, execute=True)['status'] == 'retired'
    assert not spill.exists() and unrelated.exists() and job.exists()
    assert {path: path.read_bytes() for path in protected} == before


@pytest.mark.parametrize('unsafe', ['alias', 'escape', 'input', 'relative-input', 'output', 'checkpoint', 'spill-alias'])
def test_unknown_or_referenced_spill_is_retained(tmp_path, unsafe):
    root, spill, job, protected = candidate(tmp_path)
    value = json.loads(job.read_text())
    if unsafe == 'alias':
        spill.rename(spill.with_name('other')); spill.symlink_to(spill.with_name('other'))
    elif unsafe == 'escape': value['scratch'] = str(tmp_path / 'native')
    elif unsafe == 'spill-alias': (spill / 'alias').symlink_to(protected[0])
    elif unsafe == 'checkpoint':
        saved = json.loads(protected[-1].read_text()); saved['result_pin']['path'] = str(spill / 'result.json')
        protected[-1].write_text(json.dumps(saved))
    else:
        field = 'outputs' if unsafe == 'output' else 'inputs'
        value[field] = [dict(path='native/retained.parquet' if unsafe == 'relative-input' else str(spill / 'retained.parquet'))]
    job.write_text(json.dumps(value))
    with pytest.raises(ValueError): nightly.clean_native_spill(tmp_path, execute=True)
    assert spill.exists() and all(path.exists() for path in protected)


def test_a_child_holding_the_nightly_lock_prevents_cleanup(tmp_path):
    root, spill, _, _ = candidate(tmp_path)
    lock = root.parent / 'lock'
    child = subprocess.Popen([sys.executable, '-I', '-c',
        'import fcntl,sys; f=open(sys.argv[1],"a"); fcntl.flock(f,fcntl.LOCK_EX); print("ready",flush=True); sys.stdin.read()',
        str(lock)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == 'ready'
        with pytest.raises(ValueError, match='holds the lock'):
            nightly.clean_native_spill(tmp_path, execute=True)
        assert spill.exists()
    finally:
        child.communicate('', timeout=10)
    nightly.clean_native_spill(tmp_path, execute=True)
    assert not spill.exists()


def test_budget_failure_does_not_launch_setup_or_retire_a_candidate(tmp_path, monkeypatch):
    root, spill, _, protected = candidate(tmp_path)
    before = {path: path.read_bytes() for path in protected}
    monkeypatch.setattr(nightly, 'main_checkout', lambda _: tmp_path)
    monkeypatch.setattr(nightly, 'git', lambda *args, **kwargs: 'a' * 40)
    monkeypatch.setattr(nightly, 'publish_env', lambda *_: {})
    monkeypatch.setattr(nightly, 'setup_roots', lambda *_: dict(work=tmp_path))
    monkeypatch.setattr(nightly, 'step', lambda *args, **kwargs: pytest.fail('must refuse before setup'))
    assert nightly.run(ROOT, False) == 2
    assert spill.exists() and {path: path.read_bytes() for path in protected} == before


def test_common_job_wrapper_refuses_before_launch_and_check_disk_writes_nothing(tmp_path, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location('archive_runner', ROOT / '.github/scripts/run-archive-job.py')
    runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)
    monkeypatch.setenv('ARCHIVE_DISK_BUDGETS', str(tmp_path / 'missing.json'))
    monkeypatch.setenv('RUNNER_TEMP', str(tmp_path / 'uncreated'))
    monkeypatch.setattr(runner, 'subprocess', SimpleNamespace(run=lambda *args, **kwargs: pytest.fail('owner launched')))
    monkeypatch.setattr(sys, 'argv', ['run-archive-job.py', 'publish', '--check-disk'])
    assert runner.main() == 2
    result = json.loads(capsys.readouterr().out)['disk_admission']
    assert 'budget unavailable' in result['reason'] and 'model_scratch' in result['roots']
    assert not (tmp_path / 'uncreated').exists()


def test_fresh_budget_failure_preserves_an_older_completed_candidate(tmp_path, monkeypatch):
    _, spill, _, protected = candidate(tmp_path)
    before = {path: path.read_bytes() for path in protected}
    monkeypatch.setattr(nightly, 'main_checkout', lambda _: tmp_path)
    monkeypatch.setattr(nightly, 'git', lambda *args, **kwargs: 'a' * 40 if args[0] == 'rev-parse' else '')
    monkeypatch.setattr(nightly, 'publish_env', lambda *_: dict(ARCHIVE_DISK_BUDGETS=str(tmp_path / 'missing.json')))
    monkeypatch.setattr(nightly, 'setup_roots', lambda *_: dict(work=tmp_path))
    monkeypatch.setitem(nightly.DISK, 'admit', lambda *args, **kwargs: dict(status='admitted'))
    monkeypatch.setattr(nightly, 'step', lambda *args, **kwargs: None)
    assert nightly.run(ROOT, False) == 2
    assert spill.exists() and {path: path.read_bytes() for path in protected} == before
    assert not list((tmp_path / '.cache/archive-release/nightly').glob('*/previous-candidate*'))


def test_backfill_keeps_prior_work_and_retires_only_new_native_spill(tmp_path, monkeypatch):
    import fcntl
    worktree = tmp_path / 'checkout'
    config = worktree / '.github/archive-jobs.json'; config.parent.mkdir(parents=True)
    config.write_text(json.dumps({name: dict(spec='unused.json') for name in ('publish', 'backfill')}))
    old = worktree / 'output/archive-backfill'
    old.mkdir(parents=True)
    (old / 'completed.parquet').write_bytes(b'expensive prior backfill')
    env = dict(ARCHIVE_DISK_BUDGETS=str(budget(tmp_path)))
    # Admission behavior is covered above; this fixture follows the wrapper's
    # backfill branch with no external dependency setup or acquisition.
    monkeypatch.setitem(nightly.DISK, 'admit', lambda *args, **kwargs: dict(status='admitted'))
    monkeypatch.setitem(nightly.DISK, 'job_admission', lambda *args, **kwargs: dict(status='admitted'))
    monkeypatch.setattr(nightly, 'main_checkout', lambda _: tmp_path)
    monkeypatch.setattr(nightly, 'git', lambda *args, **kwargs: 'a' * 40 if args[0] == 'rev-parse' else '')
    monkeypatch.setattr(nightly, 'publish_env', lambda *_: env)
    monkeypatch.setattr(nightly, 'setup_roots', lambda *_: dict(work=tmp_path))
    candidate = tmp_path / '.cache/archive-release/nightly/candidate'
    def step(name, command, **kwargs):
        if name == 'publish':
            daily = candidate / 'archive-daily/daily-summary.json'; daily.parent.mkdir()
            daily.write_text(json.dumps(dict(status='backfill_required')))
            raise nightly.StepFailed(name, 2)
        if name == 'backfill':
            assert not old.exists()
            old.mkdir()
            native = old / 'native'; native.mkdir()
            (native / 'orphan.arrow').write_bytes(b'spill')
            (old / 'job.json').write_text(json.dumps(dict(scratch=str(native), inputs=[], outputs=[])))
            (old / 'result.json').write_bytes(b'completed expensive phase')
            raise nightly.StepFailed(name, 2)
    monkeypatch.setattr(nightly, 'step', step)
    lock = tmp_path / 'lock'
    with lock.open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        assert nightly.run(worktree, False, lock_fd=stream.fileno()) == 2
    [held] = (tmp_path / '.cache/archive-release/nightly').glob('*/previous-backfill/completed.parquet')
    assert held.read_bytes() == b'expensive prior backfill'
    assert (old / 'result.json').read_bytes() == b'completed expensive phase'
    assert not (old / 'native').exists()


def test_a_previous_attempt_that_is_not_resumed_leaves_its_engine_logs_and_a_published_one_does_not(tmp_path, monkeypatch):
    """Only the driver's retirement of a failed candidate keeps engine logs (ct-zlj6)."""
    worktree = tmp_path / 'checkout'
    config = worktree / '.github/archive-jobs.json'; config.parent.mkdir(parents=True)
    config.write_text(json.dumps(dict(publish=dict(spec='unused.json'))))
    nightly_work = tmp_path / '.cache/archive-release/nightly'
    failed = nightly_work / 'candidate/producer-proof/captures/q/engine.log'
    failed.parent.mkdir(parents=True)
    failed.write_bytes(b'Error: query: source open failed\n')
    (nightly_work / 'candidate/commit').write_text('b' * 40 + '\n')  # another commit and no completed model: not resumed

    def step(name, command, **_):
        if name == 'publish':  # the fresh attempt's job writes its own log, then the night succeeds
            (nightly_work / 'candidate/job').mkdir()
            (nightly_work / 'candidate/job/engine.log').write_bytes(b'[docspec-metric] {"event":"step"}\n')
    monkeypatch.setitem(nightly.DISK, 'admit', lambda *args, **kwargs: dict(status='admitted'))
    monkeypatch.setitem(nightly.DISK, 'job_admission', lambda *args, **kwargs: dict(status='admitted'))
    monkeypatch.setattr(nightly, 'main_checkout', lambda _: tmp_path)
    monkeypatch.setattr(nightly, 'git', lambda *args, **kwargs: 'a' * 40 if args[0] == 'rev-parse' else '')
    monkeypatch.setattr(nightly, 'publish_env', lambda *_: {})
    monkeypatch.setattr(nightly, 'setup_roots', lambda *_: dict(work=tmp_path))
    monkeypatch.setattr(nightly, 'step', step)
    assert nightly.run(worktree, False) == 0
    assert not (nightly_work / 'candidate').exists()
    kept = {path.relative_to(nightly_work).parts[1:]: path.read_bytes() for path in nightly_work.rglob('engine.log')}
    assert kept == {('previous-candidate', 'producer-proof', 'captures', 'q', 'engine.log'): b'Error: query: source open failed\n'}


def _model_only_build(tmp_path):
    arm = tmp_path / 'build-arm'
    (arm / 'archive-release').mkdir(parents=True)
    (arm / 'archive-model/evidence').mkdir(parents=True)
    (arm / 'workspace').mkdir()
    (arm / 'ledger').mkdir()
    (arm / 'model-spec.json').write_text(json.dumps(dict(
        output=str(arm / 'archive-release'),
        scratch=str(arm / 'archive-model'),
        engine_config=str(arm / 'runtime.json'),
    )))
    (arm / 'runtime.json').write_text(json.dumps(dict(workspace=str(arm / 'workspace'))))
    (arm / 'watchdog.json').write_text(json.dumps(dict(status='completed')))
    (arm / 'comparison.json').write_text(json.dumps(dict(verdict='PASS')))
    (arm / 'archive-release/manifest.json').write_text(json.dumps(dict(release_id='ab' * 16)))
    (arm / 'archive-release/list.parquet').write_bytes(b'parquet-release-bytes')
    (arm / 'archive-model/evidence/captures.parquet').write_bytes(b'evidence-parquet-bytes')
    (arm / 'archive-model/job.json').write_text(json.dumps(dict(steps=[])))
    (arm / 'archive-model/result.json').write_text(json.dumps(dict(ok=True)))
    (arm / 'archive-model/steps.jsonl').write_text('{"event":"step","name":"captures","rows":5}\n')
    (arm / 'ledger/prior_links.parquet').write_bytes(b'ledger-bytes')
    return arm


def test_retire_model_build_records_digests_and_removes_heavy_folders_only_on_execute(tmp_path):
    """Model-only build retirement keeps spec, runtime, logs, steps and sha256 digests while removing output/scratch (ct-arlk)."""
    from hashlib import sha256

    arm = _model_only_build(tmp_path)
    plan = disk.retire_model_build(arm, execute=False)
    assert plan['status'] == 'dry-run'
    assert plan['release_id'] == 'ab' * 16
    assert set(plan['paths']) == {
        str(arm / 'archive-model'),
        str(arm / 'archive-release'),
        str(arm / 'ledger'),
        str(arm / 'workspace'),
    }
    assert plan['reclaimable_bytes'] > 0
    assert (arm / 'archive-release').exists() and not (arm / 'retired-build-digests.json').exists()

    retired = disk.retire_model_build(arm, execute=True)
    assert retired['status'] == 'retired'
    assert not (arm / 'archive-model').exists()
    assert not (arm / 'archive-release').exists()
    assert not (arm / 'workspace').exists()
    assert not (arm / 'ledger').exists()
    assert (arm / 'model-spec.json').is_file()
    assert (arm / 'runtime.json').is_file()
    assert (arm / 'watchdog.json').is_file()
    assert (arm / 'comparison.json').is_file()
    assert (arm / 'steps.jsonl').read_text() == '{"event":"step","name":"captures","rows":5}\n'
    digests = json.loads((arm / 'retired-build-digests.json').read_text())
    assert digests['release_id'] == 'ab' * 16
    assert digests['archive_release']['list.parquet']['sha256'] == sha256(b'parquet-release-bytes').hexdigest()
    assert digests['evidence']['captures.parquet']['sha256'] == sha256(b'evidence-parquet-bytes').hexdigest()
    assert digests['artifacts']['result.json']['bytes'] > 0

    again = disk.retire_model_build(arm, execute=True)
    assert again['status'] == 'retired' and again['paths'] == [] and again['reclaimable_bytes'] == 0
    assert json.loads((arm / 'retired-build-digests.json').read_text()) == digests


def test_retire_model_build_refuses_publish_candidates_and_symlinks(tmp_path):
    """retire_model_build must never touch a publish/daily candidate or follow symlinks (ct-arlk)."""
    cand = _model_only_build(tmp_path)
    (cand / 'archive-publish').mkdir()
    with pytest.raises(ValueError, match='publish|candidate'):
        disk.retire_model_build(cand, execute=True)
    assert (cand / 'archive-release').exists()

    arm = _model_only_build(tmp_path / 'sub')
    outside = tmp_path / 'outside.parquet'
    outside.write_bytes(b'secret')
    (arm / 'archive-model/evidence/link.parquet').symlink_to(outside)
    with pytest.raises(ValueError, match='symlink'):
        disk.retire_model_build(arm, execute=True)
    assert (arm / 'archive-model').exists() and outside.exists()


