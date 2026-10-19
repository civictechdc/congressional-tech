"""Progress observes complete current reads; it cannot supply replay proof."""
import hashlib
import io
import json

import pytest
from botocore.exceptions import ClientError

from viewer_publication import continuation as state
from viewer_publication import reconciliation as observation


def prepared(tmp_path, payload=b'accepted', *, verified=False):
    run = state.Continuation(tmp_path / 'attempt', {'fixture': 'pinned'})
    key = 'viewer-publications/fixture.json'
    detail = dict(key=key, bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest(), if_none_match='*')
    run.record('publication_write_intent', detail)
    if verified: run.record('publication_write_verified', dict(detail, etag='current'))
    return run, key


class Remote:
    def __init__(self, payload=b'accepted'):
        self.payload = payload
        self.gets = 0
    def get_object(self, **options):
        self.gets += 1
        return dict(Body=io.BytesIO(self.payload), ContentLength=len(self.payload), ETag='current')


def test_complete_follows_full_read_proof_and_checkpoint(tmp_path, monkeypatch):
    run, key = prepared(tmp_path)
    events = []
    checkpointed = []
    remote = Remote()
    original = run.flush
    def flush():
        original(); checkpointed.append(True)
    monkeypatch.setattr(run, 'flush', flush)
    def observe(value):
        if value['state'] == 'reading': assert not run._reconciled
        if value['state'] == 'reconciled':
            assert (id(remote), 'fixture', key) in run._reconciled and not checkpointed
        if value['state'] == 'complete': assert checkpointed == [True]
        events.append(value)
    run.reconcile(remote, 'fixture', progress=observe)
    assert [value['state'] for value in events] == ['starting', 'reading', 'reading', 'reading', 'reconciled', 'complete']
    assert events[-1]['checked_objects'] == 1 and events[-1]['bytes_read'] == 8
    assert all(value['observation_only'] and not value['resume_authorized'] and not value['current_readback_proof'] for value in events)
    assert all(value['public_readback'] == 'not_checked' for value in events)
    assert not any('etag' in value or 'sha256' in value for value in events)


@pytest.mark.parametrize('kind', ['partial', 'transport', 'checkpoint'])
def test_partial_read_and_failures_never_report_success_or_error_transport_text(tmp_path, monkeypatch, kind):
    run, key = prepared(tmp_path)
    body = io.BytesIO(b'part')
    class FailedRemote:
        def get_object(self, **options):
            if kind == 'transport':
                class Broken(io.BytesIO):
                    def read(self, size=-1):
                        if self.tell(): raise OSError('secret-access-key https://private-endpoint/')
                        return super().read(4)
                return dict(Body=Broken(b'accepted'), ContentLength=8, ETag='current')
            return dict(Body=body, ContentLength=8, ETag='current')
    if kind == 'checkpoint':
        remote = Remote()
        monkeypatch.setattr(run, 'flush', lambda: (_ for _ in ()).throw(OSError('secret-access-key https://private-endpoint/')))
    else: remote = FailedRemote()
    with pytest.raises((ValueError, OSError)):
        run.reconcile(remote, 'fixture')
    value = observation.read_progress(run.root / 'reconciliation-progress.json', binding=run.value['binding'])
    assert value['state'] == 'failed' and value['key'] == key
    assert value['bytes_read'] == (8 if kind == 'checkpoint' else 4)
    assert 'secret-access-key' not in json.dumps(value) and 'private-endpoint' not in json.dumps(value)
    if kind != 'checkpoint': assert not run._reconciled
    if kind == 'partial': assert body.closed


@pytest.mark.parametrize('outcome', ['committed', 'missing', 'original', 'conflict', 'verified_conflict'])
def test_exact_outcomes_and_next_checks_remain_read_only(tmp_path, outcome):
    run, key = prepared(tmp_path, verified=outcome == 'verified_conflict')
    remote = Remote(b'conflicting' if outcome in ('conflict', 'original', 'verified_conflict') else b'accepted')
    if outcome == 'missing':
        def missing(**options): raise ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject')
        remote.get_object = missing
    if outcome == 'original':
        run.value['writes'][key].update(if_none_match=None, expected_etag='current')
    events = []
    if 'conflict' in outcome:
        with pytest.raises(ValueError): run.reconcile(remote, 'fixture', progress=events.append)
        assert events[-1]['state'] == 'conflict' and not run._reconciled
    else:
        run.reconcile(remote, 'fixture', progress=events.append)
        assert events[-2]['state'] == ('reconciled' if outcome == 'committed' else 'uncommitted')
        assert events[-1]['state'] == 'complete'
    assert all(event['next_check'] == observation.NEXT_CHECK[event['state']] for event in events)
    assert all(not event['resume_authorized'] and event['public_readback'] == 'not_checked' for event in events)


def test_latest_file_is_bound_bounded_and_never_reused_as_proof(tmp_path):
    run, key = prepared(tmp_path, verified=True)
    remote = Remote()
    run.reconcile(remote, 'fixture')
    path = run.root / 'reconciliation-progress.json'
    progress = observation.read_progress(path, binding=run.value['binding'])
    assert progress['state'] == 'complete' and path.stat().st_size < observation.MAX_PROGRESS_BYTES
    before = path.read_bytes()
    fresh = state.Continuation(run.root, run.value['binding'], resume=True)
    assert not fresh._reconciled
    assert fresh.replay(remote, 'fixture', key, b'accepted') == {'ETag': 'current'}
    assert remote.gets == 2  # Full-read fallback despite recorded completed scan.
    other = Remote()
    assert run.replay(other, 'fixture', key, b'accepted') == {'ETag': 'current'}
    assert other.gets == 1  # Current proof is also client-bound.
    with pytest.raises(ValueError, match='different inputs'):
        observation.read_progress(path, binding={'fixture': 'changed'})
    assert path.read_bytes() == before
    path.write_bytes(b'x' * (observation.MAX_PROGRESS_BYTES + 1))
    with pytest.raises(ValueError, match='byte limit'):
        observation.read_progress(path, binding=run.value['binding'])


def test_progress_failure_does_not_replace_read_result_or_original_exception(tmp_path):
    run, key = prepared(tmp_path)
    def failing_observer(value): raise PermissionError('private observer details')
    run.reconcile(Remote(), 'fixture', progress=failing_observer)
    assert run.value['writes'][key]['verified']
    original = OSError('primary read failure')
    class Failed:
        def get_object(self, **options): raise original
    failed = Failed()
    with pytest.raises(OSError) as caught:
        run.reconcile(failed, 'fixture', progress=failing_observer)
    assert caught.value is original
    assert (id(failed), 'fixture', key) not in run._reconciled


def test_read_progress_is_bounded_even_if_declared_size_is_wrong():
    class Body:
        offset = 0
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size):
            self.offset += 1
            return b'x' * 1024**2 if self.offset <= 64 else b''
    class Remote:
        def get_object(self, **options): return dict(Body=Body(), ContentLength=1, ETag='current')
    updates = []
    with pytest.raises(ValueError, match='Incomplete'):
        state.Continuation.read(Remote(), 'fixture', 'key', progress=lambda size, total: updates.append((size, total)))
    assert len(updates) <= observation.MAX_READ_UPDATES + 2
    assert updates[-1] == (64 * 1024**2, 1)
    assert all(a[0] < b[0] for a, b in zip(updates, updates[1:]))


def test_zero_object_scan_completes_only_after_checkpoint(tmp_path):
    run = state.Continuation(tmp_path / 'empty', {})
    run.reconcile(Remote(), 'fixture')
    value = observation.read_progress(run.root / 'reconciliation-progress.json', binding={})
    assert value['state'] == 'complete' and value['total_objects'] == 0 and value['key'] is None


@pytest.mark.parametrize('declared', [-1, None, '8', True])
def test_invalid_content_length_closes_body_and_reports_failure(tmp_path, declared):
    run, _ = prepared(tmp_path)
    body = io.BytesIO(b'accepted')
    class Invalid:
        def get_object(self, **options): return dict(Body=body, ContentLength=declared, ETag='current')
    with pytest.raises(ValueError, match='Invalid reconciliation ContentLength'):
        run.reconcile(Invalid(), 'fixture')
    assert body.closed and not run._reconciled
    value = observation.read_progress(run.root / 'reconciliation-progress.json', binding=run.value['binding'])
    assert value['state'] == 'failed' and value['declared_bytes'] is None and value['bytes_read'] == 0


def test_observation_file_failure_cannot_mask_current_read_or_checkpoint(tmp_path, monkeypatch):
    from pathlib import Path
    run, key = prepared(tmp_path)
    original = Path.replace
    def replace(path, destination):
        if path.name == 'reconciliation-progress.tmp': raise PermissionError('private filesystem detail')
        return original(path, destination)
    monkeypatch.setattr(Path, 'replace', replace)
    run.reconcile(Remote(), 'fixture')
    assert json.loads(run.path.read_bytes())['writes'][key]['verified']
    assert run.replay(Remote(), 'fixture', key, b'accepted') == {'ETag': 'current'}
