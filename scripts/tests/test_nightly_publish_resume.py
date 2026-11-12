"""A candidate survives a commit that only records its reviewed release cause, and nothing else.

A failed candidate that is retired leaves its jobs' engine logs with the run's evidence.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location('nightly_publish_contract', ROOT / 'scripts/nightly_publish.py')
nightly = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(nightly)


def commit(repo, files):
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    subprocess.run(['git', 'add', '-A'], cwd=repo, check=True)
    subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', 'commit', '-qm', 'x'],
                   cwd=repo, check=True)
    return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    base = commit(tmp_path, {'model/jobs/publish.json': json.dumps(dict(version=1, bucket='b')),
                             'model/sql/a.sql': 'SELECT 1'})
    return tmp_path, base


CAUSE = {'model/jobs/release-causes/a-b.json': '{}', '.tickets/ct-x.md': 'note', 'docs/releases/r.md': 'r',
         'model/jobs/publish.json': json.dumps(dict(version=1, bucket='b', release_causes=dict(path='release-causes/a-b.json')))}


def test_a_cause_record_commit_keeps_the_candidate(repo):
    path, base = repo
    assert nightly.only_cause_records(path, base, commit(path, CAUSE))


@pytest.mark.parametrize('extra', [
    {'model/sql/a.sql': 'SELECT 2'},
    {'scripts/nightly_publish.py': 'pass'},
    {'model/jobs/publish.json': json.dumps(dict(version=1, bucket='other', release_causes=dict(path='x')))},
    {'model/jobs/publish-model.json': '{}'},
])
def test_any_other_change_discards_it(repo, extra):
    path, base = repo
    assert not nightly.only_cause_records(path, base, commit(path, dict(CAUSE, **extra)))


def test_an_unknown_or_malformed_commit_discards_it(repo):
    path, base = repo
    head = commit(path, CAUSE)
    assert not nightly.only_cause_records(path, '0' * 40, head)
    assert not nightly.only_cause_records(path, 'HEAD~1', head)
    assert not nightly.only_cause_records(path, head, head)


def candidate(root, logs):
    """A candidate under `root` whose engine logs, given oldest first, are each a second newer than the last."""
    made, run = root / 'candidate', root / 'run'
    run.mkdir(parents=True)
    for age, (name, data) in enumerate(logs.items()):
        path = made / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        os.utime(path, (1_000_000 + age, 1_000_000 + age))
    (made / 'commit').write_text('abc\n')
    return made, run


def files(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob('*') if path.is_file()}


ERROR = b'Error: query: source open failed\n'


def test_only_a_failed_candidate_keeps_its_engine_logs(tmp_path):
    """Retirement deletes the candidate, and a failed job's engine.log is wanted exactly then (ct-zlj6)."""
    logs = {'producer-proof/captures/q/engine.log': ERROR, 'producer-proof/captures/q/other.log': b'not an engine log\n'}
    published, run = candidate(tmp_path / 'published', logs)
    nightly.archive_candidate(published, run / 'candidate')
    assert files(run) == {'candidate/commit': b'abc\n'} and not published.exists()  # a successful night keeps what it kept before
    failed, run = candidate(tmp_path / 'failed', logs)
    nightly.archive_candidate(failed, run / 'previous-candidate', failed=True)
    assert not failed.exists() and files(run) == {
        'previous-candidate/commit': b'abc\n', 'previous-candidate/producer-proof/captures/q/engine.log': ERROR,
        'previous-candidate/engine-logs.txt': b'[nightly] engine logs: 1 kept, 0 not kept; 0 bytes not kept\n'}


def test_engine_logs_are_kept_newest_first_within_one_total_bound(tmp_path, monkeypatch):
    oldest, older, cut, newest = b'o' * 300, b'p' * 40, b'm' * 200 + b'Error: earlier\n', b'[docspec-metric] {"event":"step"}\n' + ERROR
    monkeypatch.setattr(nightly, 'EVIDENCE_MAX_BYTES', len(newest) + len(nightly.ENGINE_LOG_CUT) + 20)
    failed, run = candidate(tmp_path, {'a/engine.log': oldest, 'b/engine.log': older, 'c/engine.log': cut, 'd/engine.log': newest})
    nightly.archive_candidate(failed, run / 'previous-candidate', failed=True)
    kept = files(run / 'previous-candidate')
    logs = {name: data for name, data in kept.items() if name.endswith('/engine.log')}
    # The failed job's log is whole; the next keeps its tail, error last; the bound is then spent and nothing older is kept.
    assert logs == {'d/engine.log': newest, 'c/engine.log': nightly.ENGINE_LOG_CUT + cut[-20:]}
    assert sum(map(len, logs.values())) == nightly.EVIDENCE_MAX_BYTES
    assert kept['engine-logs.txt'].decode().splitlines() == [
        f'[nightly] engine logs: 2 kept, 2 not kept; {len(cut) - 20 + len(older) + len(oldest)} bytes not kept',
        f'cut: c/engine.log: the last 20 of {len(cut)} bytes kept']


def test_a_log_that_cannot_be_kept_never_stops_the_retirement(tmp_path, monkeypatch):
    """An unreadable log, and one that goes between the listing and the copy: both are noted, neither raises."""
    if os.geteuid() == 0:
        pytest.skip('root reads a file whatever its mode')
    failed, run = candidate(tmp_path, {'gone/engine.log': b'gone\n', 'locked/engine.log': b'locked\n', 'good/engine.log': ERROR})
    (failed / 'locked/engine.log').chmod(0)
    copy = shutil.copy2

    def copy_after_it_went(source, target):
        if Path(source).parent.name == 'gone':
            Path(source).unlink()
        return copy(source, target)
    monkeypatch.setattr(nightly.shutil, 'copy2', copy_after_it_went)
    nightly.archive_candidate(failed, run / 'previous-candidate', failed=True)
    assert not failed.exists() and not (run / 'previous-candidate-retiring').exists()
    kept = files(run / 'previous-candidate')
    assert {name: data for name, data in kept.items() if name != 'engine-logs.txt'} == {'commit': b'abc\n', 'good/engine.log': ERROR}
    assert kept['engine-logs.txt'].decode().splitlines() == [
        '[nightly] engine logs: 1 kept, 2 not kept; 12 bytes not kept',
        'not kept: locked/engine.log: PermissionError: Permission denied',
        'not kept: gone/engine.log: FileNotFoundError: No such file or directory']


def test_the_morning_report_is_kept_and_its_line_goes_in_the_summary(tmp_path):
    """ct-rhqw: the gate writes the Congress.gov meeting update report beside its gate report; the
    run keeps both files with its evidence and puts the report's line in summary.json."""
    report = {'archive-publish/candidate-x/meeting-updates.json':
              json.dumps(dict(line='1 Congress.gov meeting updated: 118340 (title)', meetings=[])).encode(),
              'archive-publish/candidate-x/meeting-updates.txt': b'118340 Hearing (2026-11-12)\n  title: A -> B\n'}
    published, run = candidate(tmp_path / 'published', report)
    summary = {}
    nightly.record_meeting_updates(summary, published)
    assert summary == {'meeting_updates': '1 Congress.gov meeting updated: 118340 (title)'}
    nightly.archive_candidate(published, run / 'candidate')
    assert files(run) == {'candidate/commit': b'abc\n', **{f'candidate/{name}': body for name, body in report.items()}}
    quiet = {}
    nightly.record_meeting_updates(quiet, candidate(tmp_path / 'quiet', {'archive-daily/daily-summary.json': b'{}'})[0])
    assert quiet == {}


def test_resumed_candidate_records_the_newest_morning_report_not_the_largest_uuid(tmp_path):
    import os
    resumed, _ = candidate(tmp_path / 'resumed', {
        'archive-publish/candidate-fff000/meeting-updates.json': json.dumps(dict(line='STOPPED old attempt', meetings=[])).encode(),
        'archive-publish/candidate-111000/meeting-updates.json': json.dumps(dict(line='Cleared the release check', meetings=[])).encode()})
    old = resumed / 'archive-publish/candidate-fff000/meeting-updates.json'
    new = resumed / 'archive-publish/candidate-111000/meeting-updates.json'
    os.utime(old, ns=(1_000_000_000, 1_000_000_000))
    os.utime(new, ns=(2_000_000_000, 2_000_000_000))
    summary = {}
    nightly.record_meeting_updates(summary, resumed)
    assert summary == {'meeting_updates': 'Cleared the release check'}

