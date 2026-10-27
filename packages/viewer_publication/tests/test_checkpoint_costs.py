"""One durable checkpoint owns verified write facts and protected versions."""
import hashlib
import io
import json

import pytest

from viewer_publication.client import GuardedPublicationClient
from viewer_publication import continuation as state


def test_verified_event_advances_protected_version_in_its_single_checkpoint(tmp_path, monkeypatch):
    continuation = state.Continuation(tmp_path / 'run', {})
    key = 'indexes/catalog.json'
    continuation.value['versions'][key] = 'old'
    intent = dict(key=key, bytes=3, sha256='a' * 64, expected_etag='old')
    continuation.record('publication_write_intent', intent)
    checkpoints = []
    original = continuation.flush
    monkeypatch.setattr(continuation, 'flush', lambda: checkpoints.append(True) or original())
    continuation.record('publication_write_verified', dict(intent, etag='new'))
    saved = json.loads(continuation.path.read_bytes())
    assert checkpoints == [True]
    assert saved['writes'][key]['verified'] and saved['versions'][key] == 'new'
    assert saved['writes'][key]['expected_etag'] == 'old'


def test_failed_verified_checkpoint_reconciles_committed_bytes_without_second_put(tmp_path, monkeypatch):
    continuation = state.Continuation(tmp_path / 'run', {})
    key, payload = 'indexes/catalog.json', b'accepted bytes'
    continuation.value['versions'][key] = None

    class Remote:
        puts = 0
        def put_object(self, **options):
            assert options['IfNoneMatch'] == '*'
            self.puts += 1
            self.body = options['Body']
            return {'ETag': 'committed'}
        def get_object(self, **options):
            return dict(Body=io.BytesIO(self.body), ContentLength=len(self.body), ETag='committed')

    remote = Remote()
    original = continuation.flush
    def interrupted():
        if continuation.value['writes'][key]['verified']:
            raise KeyboardInterrupt('after acknowledgment before checkpoint replacement')
        original()
    monkeypatch.setattr(continuation, 'flush', interrupted)
    proxy = GuardedPublicationClient(remote, guard=lambda: None, journal=continuation.record,
                                     after_write=lambda *args: None)
    with pytest.raises(KeyboardInterrupt, match='after acknowledgment'):
        proxy.put_object(Bucket='bucket', Key=key, Body=payload, IfNoneMatch='*')
    saved = json.loads(continuation.path.read_bytes())
    assert saved['versions'][key] is None and not saved['writes'][key]['verified']
    restored = state.Continuation(continuation.root, {}, resume=True)
    restored.reconcile(remote, 'bucket')
    assert restored.value['versions'][key] == 'committed'
    assert restored.value['writes'][key]['if_none_match'] == '*'
    assert restored.replay(remote, 'bucket', key, payload) == {'ETag': 'committed'}
    assert remote.puts == 1


def test_compact_checkpoint_preserves_values_durability_and_byte_admission(tmp_path, monkeypatch):
    continuation = state.Continuation(tmp_path / 'run', {'unicode': 'José 雪', 'empty': []})
    syncs = []
    original = state.os.fsync
    monkeypatch.setattr(state.os, 'fsync', lambda fd: syncs.append(True) or original(fd))
    continuation.flush()
    saved = continuation.path.read_bytes()
    assert json.loads(saved) == continuation.value
    assert syncs == [True, True]  # Complete file, then containing directory.
    assert len(saved) < len(json.dumps(continuation.value, sort_keys=True, indent=2).encode())
    monkeypatch.setattr(state, 'MAX_STATE_BYTES', len(saved) - 1)
    with pytest.raises(ValueError, match='state byte limit'):
        continuation.flush()
    assert continuation.path.read_bytes() == saved
    assert not continuation.path.with_suffix('.tmp').exists()
    assert syncs == [True, True]
