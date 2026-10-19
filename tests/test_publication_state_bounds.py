"""Untrusted continuation/journal input fails before checkpoint or mutation."""
import hashlib
import io
import json
from pathlib import Path
import pytest
import recovery_publication_continuation as state
from botocore.exceptions import ClientError

class Remote:
    def __init__(self):
        self.objects = {}; self.puts = 0; self.bodies = []
    def get_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject')
        raw = self.objects[Key]; body = io.BytesIO(raw); self.bodies.append(body)
        return {'Body': body, 'ContentLength': len(raw), 'ETag': hashlib.sha256(raw).hexdigest()}
    def put_object(self, **kw):
        assert kw['IfNoneMatch'] == '*'
        if kw['Key'] in self.objects:
            raise ClientError({'Error': {'Code': 'PreconditionFailed'}}, 'PutObject')
        self.objects[kw['Key']] = kw['Body']; self.puts += 1
        return {'ETag': hashlib.sha256(kw['Body']).hexdigest()}
    def get_paginator(self, name):
        remote = self
        class Pages:
            def paginate(self, **kw):
                yield {'Contents': [{'Key': key} for key in remote.objects if key.startswith(kw['Prefix'])]}
        return Pages()

@pytest.fixture
def journal(tmp_path):
    continuation = state.Continuation(tmp_path / 'attempt', {'fixture': True})
    remote = Remote()
    return state.DurableJournal(remote, 'bucket', continuation, 'test-attempt', {'prepared': True}), continuation, remote


def test_saved_names_refuse_escape_absolute_and_external_symlink(tmp_path):
    c = state.Continuation(tmp_path / 'attempt', {})
    for name in ('../escape', '/absolute', './noncanonical', 'nested/../escape', ''):
        with pytest.raises(ValueError, match='saved name'):
            c.save(name, b'no')
    (c.root / 'outside').symlink_to(tmp_path)
    with pytest.raises(ValueError, match='escapes'):
        c.save('outside/escaped', b'no')
    assert not (tmp_path / 'escaped').exists()

@pytest.mark.parametrize('change,diagnostic', [
    (lambda v: v.update(version=2), 'version'),
    (lambda v: v.update(writes=[]), 'fields'),
    (lambda v: v['phases'].update(bad={'files': {'../escape': 'a'*64}, 'result': {}}), 'saved name'),
    (lambda v: v['writes'].update(bad={'key': 'bad', 'verified': True}), 'write identity'),
])
def test_persisted_shape_is_validated_before_resume(tmp_path, change, diagnostic):
    c = state.Continuation(tmp_path / 'attempt', {})
    change(c.value); c.path.write_text(json.dumps(c.value))
    with pytest.raises(ValueError, match=diagnostic):
        state.Continuation(c.root, {}, resume=True)


def test_illegal_write_transitions_do_not_append_remote_events(journal):
    log, continuation, remote = journal
    before = remote.puts
    verified = {'key': 'viewer-publications/releases/x/file', 'bytes': 1, 'sha256': 'a'*64, 'etag': 'v'}
    with pytest.raises(ValueError, match='transition'):
        log.record('publication_write_verified', verified)
    assert remote.puts == before
    log.record('publication_write_intent', dict(verified, etag=None, if_none_match='*'))
    with pytest.raises(ValueError, match='differs from intent'):
        log.record('publication_write_verified', dict(verified, bytes=2))


def test_restore_validates_entire_prefix_before_any_checkpoint(journal):
    log, continuation, remote = journal
    log.record('informational_progress', {'completed': 1})
    saved = continuation.path.read_bytes()
    key = log.prefix + '00000001.json'
    event = json.loads(remote.objects[key]); event['version'] = 2
    remote.objects[key] = json.dumps(event).encode()
    with pytest.raises(ValueError, match='journal version'):
        state.DurableJournal(remote, 'bucket', continuation, 'test-attempt', {'prepared': True}, resume=True)
    assert continuation.path.read_bytes() == saved
    assert all(body.closed for body in remote.bodies)

@pytest.mark.parametrize('limit,value,diagnostic', [
    ('MAX_EVENTS', 1, 'event count'), ('MAX_EVENT_BYTES', 1, 'event byte'),
    ('MAX_JOURNAL_BYTES', 1, 'total byte'),
])
def test_restore_limits_fail_before_checkpoint(journal, monkeypatch, limit, value, diagnostic):
    log, continuation, remote = journal
    log.record('informational_progress', {})
    saved = continuation.path.read_bytes()
    monkeypatch.setattr(state, limit, value)
    with pytest.raises(ValueError, match=diagnostic):
        state.DurableJournal(remote, 'bucket', continuation, 'test-attempt', {'prepared': True}, resume=True)
    assert continuation.path.read_bytes() == saved
    assert all(body.closed for body in remote.bodies)


def test_restore_has_one_checkpoint_for_complete_validated_prefix(journal, monkeypatch):
    log, continuation, remote = journal
    key = 'viewer-publications/releases/x/file'
    value = {'key': key, 'bytes': 1, 'sha256': 'a'*64, 'if_none_match': '*'}
    log.record('publication_write_intent', value)
    log.record('publication_write_verified', dict(value, etag='v'))
    checkpoints = []
    original = continuation.flush
    monkeypatch.setattr(continuation, 'flush', lambda: checkpoints.append(True) or original())
    restored = state.DurableJournal(remote, 'bucket', continuation, 'test-attempt', {'prepared': True}, resume=True)
    assert checkpoints == [True]
    assert restored.sequence == 3
    assert continuation.value['writes'][key]['verified'] is True


@pytest.mark.parametrize('limit,value', [('MAX_PHASES', 0), ('MAX_PHASE_FILES', 0)])
def test_new_phase_capacity_refuses_before_accepting_checkpoint(tmp_path, monkeypatch, limit, value):
    c = state.Continuation(tmp_path / 'attempt', {})
    path = c.root / 'file'; path.write_bytes(b'complete')
    before = c.path.read_bytes()
    monkeypatch.setattr(state, limit, value)
    with pytest.raises(ValueError, match='phase.*limit'):
        c.phase('prepared', lambda: {}, files=lambda: [path])
    assert c.value['phases'] == {} and c.path.read_bytes() == before


def test_new_phase_rejects_symlink_escape_without_accepting_state(tmp_path):
    c = state.Continuation(tmp_path / 'attempt', {})
    outside = tmp_path / 'outside'; outside.write_bytes(b'outside')
    link = c.root / 'link'; link.symlink_to(outside)
    before = c.path.read_bytes()
    with pytest.raises(ValueError, match='escapes'):
        c.phase('prepared', lambda: {}, files=lambda: [link])
    assert c.value['phases'] == {} and c.path.read_bytes() == before


@pytest.mark.parametrize('escape', ['file', 'parent'])
def test_restored_phase_refuses_same_byte_symlink_escape_before_hashing(tmp_path, monkeypatch, escape):
    c = state.Continuation(tmp_path / 'attempt', {})
    path = c.root / 'prepared' / 'file'
    path.parent.mkdir(); path.write_bytes(b'accepted')
    c.phase('prepared', lambda: {'accepted': True}, files=lambda: [path])
    outside = tmp_path / 'outside'; outside.mkdir()
    (outside / 'file').write_bytes(b'accepted')
    path.unlink()
    if escape == 'file':
        path.symlink_to(outside / 'file')
    else:
        path.parent.rmdir(); path.parent.symlink_to(outside, target_is_directory=True)
    restored = state.Continuation(c.root, {}, resume=True)
    before = restored.path.read_bytes()
    monkeypatch.setattr(state, 'sha256', lambda *_: pytest.fail('Escaping saved file was hashed'))
    with pytest.raises(ValueError, match='phase path escapes root'):
        restored.phase('prepared', lambda: pytest.fail('Accepted phase rebuilt'), files=lambda: [])
    assert restored.path.read_bytes() == before
    assert (outside / 'file').read_bytes() == b'accepted'


def test_restored_phase_accepts_matching_owned_file_and_still_checks_digest(tmp_path):
    c = state.Continuation(tmp_path / 'attempt', {})
    path = c.root / 'file'; path.write_bytes(b'accepted')
    result = c.phase('prepared', lambda: {'accepted': True}, files=lambda: [path])
    restored = state.Continuation(c.root, {}, resume=True)
    assert restored.phase('prepared', lambda: pytest.fail('Accepted phase rebuilt'), files=lambda: []) == result
    path.write_bytes(b'different')
    with pytest.raises(ValueError, match='phase changed'):
        restored.phase('prepared', lambda: pytest.fail('Accepted phase rebuilt'), files=lambda: [])
