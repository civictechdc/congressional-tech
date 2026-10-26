"""Local events retain acknowledged writes and resolve uncertain upload outcomes."""
import hashlib
import io
import json

import pytest

from viewer_publication import continuation as state
from viewer_publication import local
from viewer_publication.client import ContinuedPublicationClient


def intent(key='indexes/catalog.json', body=b'accepted bytes'):
    return dict(key=key, bytes=len(body), sha256=hashlib.sha256(body).hexdigest(), if_none_match='*')


def test_each_accepted_phase_restores_from_events_without_checkpoint(tmp_path):
    root = tmp_path / 'attempt'
    run = local.LocalContinuation(root, {'input': 'pinned'})
    calls = []
    for name in ('catalog', 'mappings', 'prepared', 'publication'):
        path = root / (name + '.json')
        def build():
            calls.append(name); path.write_text(name)
            return {'accepted': name}
        run.phase(name, build, files=lambda: [path])
        run.path.write_text('broken derived checkpoint')
        run = local.LocalContinuation(root, {'input': 'pinned'}, resume=True)
        assert run.phase(name, lambda: pytest.fail('accepted phase reran'), files=lambda: []) == {'accepted': name}
    assert calls == ['catalog', 'mappings', 'prepared', 'publication']
    run.path.unlink()
    restored = local.LocalContinuation(root, {'input': 'pinned'}, resume=True)
    assert set(restored.value['phases']) == set(calls)
    with pytest.raises(ValueError, match='inputs changed'):
        local.LocalContinuation(root, {'input': 'changed'}, resume=True)
    path.write_text('changed')
    with pytest.raises(ValueError, match='phase changed'):
        restored.phase('publication', lambda: None, files=lambda: [])


@pytest.mark.parametrize('boundary', ['intent', 'committed', 'verified'])
def test_uncertain_write_restore_requires_current_body_without_duplicate_put(tmp_path, boundary):
    run = local.LocalContinuation(tmp_path / 'attempt', {})
    payload = b'accepted bytes'
    detail = intent(body=payload)
    run.value['versions'][detail['key']] = None
    run.flush()
    run.record('publication_write_intent', detail)
    class Remote:
        puts = 0
        reads = 0
        body = payload
        def get_object(self, **options):
            self.reads += 1
            return dict(Body=io.BytesIO(self.body), ContentLength=len(self.body), ETag='committed')
        def head_object(self, **options):
            return dict(ETag='committed', ContentLength=len(self.body))
        def put_object(self, **options):
            self.puts += 1
            self.body = options['Body']
            return {'ETag': 'committed'}
    remote = Remote()
    if boundary == 'verified':
        run.record('publication_write_verified', dict(detail, etag='committed'))
    # Intent-only may represent an uncommitted write or an uncertain committed
    # request; both must be reconciled from current bytes on explicit resume.
    run.path.unlink()
    restored = local.LocalContinuation(run.root, {}, resume=True)
    if boundary == 'intent':
        from botocore.exceptions import ClientError
        original = remote.get_object
        remote.get_object = lambda **options: (_ for _ in ()).throw(ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject'))
        restored.reconcile(remote, 'bucket')
        assert not restored.value['writes'][detail['key']]['verified']
        remote.get_object = original
        proxy = ContinuedPublicationClient(remote, continuation=restored, guard=lambda: None,
            journal=restored.record, after_write=lambda *args: None)
        assert proxy.put_object(Bucket='bucket', Key=detail['key'], Body=payload, IfNoneMatch='*')['ETag'] == 'committed'
        assert remote.puts == 1
    else:
        restored.reconcile(remote, 'bucket')
        assert restored.replay(remote, 'bucket', detail['key'], payload) == {'ETag': 'committed'}
        assert remote.reads == (0 if boundary == 'verified' else 1) and remote.puts == 0
        assert restored.value['versions'][detail['key']] == 'committed'
    fresh = local.LocalContinuation(run.root, {}, resume=True)
    remote.body = b'changed'
    before = remote.reads
    fresh.reconcile(remote, 'bucket')
    assert remote.reads == before  # Accepted uploads are not routinely read again.


def test_event_size_accounting_and_failure_history_are_exact(tmp_path):
    run = local.LocalContinuation(tmp_path / 'attempt', {'unicode': '雪'})
    for number in range(10):
        detail = intent('viewer-publications/雪' + str(number))
        run.record('publication_write_intent', detail)
        assert run._state_bytes == len(local.encoded(run.value)) + 1
        if number % 2:
            run.record('publication_write_verified', dict(detail, etag='\"雪\"'))
        else:
            run.record('publication_write_refused', {'key': detail['key']})
        assert run._state_bytes == len(local.encoded(run.value)) + 1
    run.record('failed', {'error': 'retained failure class'})
    run.record('failed', {'error': 'another attempt failure'})
    before = run.journal_path.read_bytes()
    restored = local.LocalContinuation(run.root, {'unicode': '雪'}, resume=True)
    assert restored.value == run.value
    assert restored.journal_path.read_bytes() == before
    records = [json.loads(line) for line in before.splitlines()]
    assert [record['value']['error'] for record in records if record['event'] == 'failed'] == ['retained failure class', 'another attempt failure']
    with pytest.raises(ValueError, match='Illegal'):
        run.record('publication_write_verified', dict(intent('unknown'), etag='x'))
    assert run.journal_path.read_bytes() == before
    with pytest.raises(ValueError, match='Reserved'):
        run.record('local_checkpoint', run.value)


@pytest.mark.parametrize('damage', ['partial', 'middle', 'empty', 'snapshot', 'sequence'])
def test_corrupt_history_refuses_before_touching_derived_checkpoint(tmp_path, damage):
    run = local.LocalContinuation(tmp_path / 'attempt', {})
    run.record('publication_write_intent', intent())
    run.record('failed', {'error': 'retained'})
    lines = run.journal_path.read_bytes().splitlines(keepends=True)
    if damage == 'partial': lines[-1] = lines[-1][:-2]
    elif damage == 'middle': del lines[1]
    elif damage == 'empty': lines = []
    elif damage == 'snapshot':
        value = json.loads(lines[0]); value['value']['writes'] = []
        lines[0] = local.encoded(value) + b'\n'
    else:
        value = json.loads(lines[0]); value['sequence'] = True
        lines[0] = local.encoded(value) + b'\n'
    run.journal_path.write_bytes(b''.join(lines))
    checkpoint = run.path.read_bytes()
    with pytest.raises((ValueError, TypeError)):
        local.LocalContinuation(run.root, {}, resume=True)
    assert run.path.read_bytes() == checkpoint


def test_limits_and_failed_sync_block_further_operations(tmp_path, monkeypatch):
    run = local.LocalContinuation(tmp_path / 'attempt', {})
    before = run.journal_path.read_bytes()
    monkeypatch.setattr(local, 'MAX_LOCAL_EVENTS', run.sequence)
    with pytest.raises(ValueError, match='journal exceeds limit'):
        run.record('failed', {})
    assert run.journal_path.read_bytes() == before
    monkeypatch.setattr(local, 'MAX_LOCAL_EVENTS', 65536)
    monkeypatch.setattr(state, 'MAX_STATE_BYTES', run._state_bytes)
    with pytest.raises(ValueError, match='state byte limit'):
        run.record('publication_write_intent', intent())
    assert run.journal_path.read_bytes() == before
    monkeypatch.setattr(state, 'MAX_STATE_BYTES', 32 * 1024**2)
    monkeypatch.setattr(local.os, 'fsync', lambda fd: (_ for _ in ()).throw(OSError('sync failure')))
    with pytest.raises(OSError, match='sync failure'):
        run.record('publication_write_intent', intent())
    assert not run.value['writes']
    with pytest.raises(ValueError, match='explicit resume'):
        run.record('failed', {})


def test_derived_checkpoint_failure_preserves_accepted_event(tmp_path, monkeypatch):
    run = local.LocalContinuation(tmp_path / 'attempt', {})
    monkeypatch.setattr(state.Continuation, 'flush', lambda self: (_ for _ in ()).throw(OSError('checkpoint failure')))
    with pytest.raises(OSError, match='checkpoint failure'):
        run.phase('catalog', lambda: {'ok': True}, files=lambda: [])
    restored = local.LocalContinuation(run.root, {}, resume=True)
    assert restored.phase('catalog', lambda: pytest.fail('reran'), files=lambda: []) == {'ok': True}


def test_write_event_sync_precedes_put_and_guard_versions_keep_identity(tmp_path, monkeypatch):
    run = local.LocalContinuation(tmp_path / 'attempt', {})
    key = intent()['key']
    versions = run.value['versions']
    versions[key] = None
    run.flush()
    calls = []
    class Remote:
        def put_object(self, **options): calls.append('put'); return {'ETag': 'new'}
        def get_object(self, **options):
            payload = b'accepted bytes'
            return dict(Body=io.BytesIO(payload), ContentLength=len(payload), ETag='new')
    original = local.os.fsync
    monkeypatch.setattr(local.os, 'fsync', lambda fd: calls.append('sync') or original(fd))
    proxy = ContinuedPublicationClient(Remote(), continuation=run, guard=lambda: None,
        journal=run.record, after_write=lambda *args: None)
    proxy.put_object(Bucket='bucket', Key=key, Body=b'accepted bytes', IfNoneMatch='*')
    assert calls == ['sync', 'put', 'sync']
    assert run.value['versions'] is versions and versions[key] == 'new'
    monkeypatch.setattr(local.os, 'fsync', lambda fd: (_ for _ in ()).throw(OSError('sync failure')))
    with pytest.raises(OSError, match='sync failure'):
        proxy.put_object(Bucket='bucket', Key='viewer-publications/another.json', Body=b'new', IfNoneMatch='*')
    assert calls == ['sync', 'put', 'sync']


def test_record_and_restore_enforce_event_and_history_byte_limits(tmp_path, monkeypatch):
    run = local.LocalContinuation(tmp_path / 'attempt', {})
    before = run.journal_path.read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(state, 'MAX_EVENT_BYTES', 128)
        with pytest.raises(ValueError, match='journal exceeds limit'):
            run.record('failed', {'error': 'x' * 129})
    with monkeypatch.context() as patch:
        patch.setattr(local, 'MAX_LOCAL_JOURNAL_BYTES', len(before))
        with pytest.raises(ValueError, match='journal exceeds limit'):
            run.record('failed', {})
    assert run.journal_path.read_bytes() == before
    with monkeypatch.context() as patch:
        patch.setattr(local, 'MAX_LOCAL_JOURNAL_BYTES', len(before) - 1)
        with pytest.raises(ValueError, match='oversized'):
            local.LocalContinuation(run.root, {}, resume=True)
    with monkeypatch.context() as patch:
        patch.setattr(local, 'MAX_LOCAL_RECORD_BYTES', len(before) - 1)
        with pytest.raises(ValueError, match='oversized'):
            local.LocalContinuation(run.root, {}, resume=True)


def test_event_application_never_clears_guard_versions_or_unrelated_writes(tmp_path):
    run = local.LocalContinuation(tmp_path / 'attempt', {})
    protected = intent()['key']
    class ObservedVersions(dict):
        assignments = []
        def clear(self): pytest.fail('Shared guard versions were transiently cleared')
        def update(self, *args, **kwargs): pytest.fail('Shared guard versions were repopulated')
        def __setitem__(self, key, value):
            assert protected in self and self[protected] == 'old'
            self.assignments.append((key, value))
            return super().__setitem__(key, value)
    versions = ObservedVersions({protected: 'old'})
    run.value['versions'] = versions
    run.flush()
    run.record('failed', {'error': 'retained'})
    immutable = intent('viewer-publications/immutable')
    run.record('publication_write_intent', immutable)
    run.record('publication_write_verified', dict(immutable, etag='immutable'))
    unchanged_write = run.value['writes'][immutable['key']]
    detail = intent(); detail.pop('if_none_match'); detail['expected_etag'] = 'old'
    run.record('publication_write_intent', detail)
    assert versions.assignments == []
    run.record('publication_write_verified', dict(detail, etag='new'))
    assert versions.assignments == [(protected, 'new')]
    assert run.value['versions'] is versions
    assert run.value['writes'][immutable['key']] is unchanged_write
    assert versions[protected] == 'new'
    assert run._state_bytes == len(local.encoded(run.value)) + 1
