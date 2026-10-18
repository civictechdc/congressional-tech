"""The publisher must not bypass guards through managed file uploads."""
import io
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from guarded_recovery_publication_client import GuardedPublicationClient


class Client:
    def __init__(self):
        self.calls = []; self.raw = b''; self.lose_ack = False
    def put_object(self, **kwargs):
        self.calls.append(kwargs)
        body = kwargs['Body']
        self.raw = body if isinstance(body, bytes) else body.read()
        if self.lose_ack:
            raise TimeoutError()
        return {'ETag': 'new'}
    def get_object(self, **kwargs):
        return dict(Body=io.BytesIO(self.raw), ContentLength=len(self.raw), ETag='new')


class GuardTests(unittest.TestCase):
    def make(self, client, guard=lambda: None):
        self.updated = []
        return GuardedPublicationClient(client, guard=guard,
            journal=lambda event, value: None,
            after_write=lambda key, etag: self.updated.append((key, etag)))

    def test_file_transfer_is_conditional_and_guarded(self):
        client = Client(); checks = []
        proxy = self.make(client, lambda: checks.append(True))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'file'; path.write_bytes(b'full bytes')
            proxy.upload_file(path, 'bucket', 'viewer-publications/releases/x/file')
        self.assertEqual(checks, [True])
        self.assertEqual(client.raw, b'full bytes')
        self.assertEqual(client.calls[0]['IfNoneMatch'], '*')
        self.assertEqual(len(self.updated), 1)

    def test_raw_index_and_unconditional_writes_blocked(self):
        client = Client(); proxy = self.make(client)
        for kwargs in [dict(Key='indexes/captures.parquet', IfMatch='old'),
                       dict(Key='indexes/catalog.json')]:
            with self.assertRaises(ValueError):
                proxy.put_object(Bucket='bucket', Body=b'x', **kwargs)
        self.assertFalse(client.calls)

    def test_guard_failure_stops_file_upload(self):
        def refuse(): raise RuntimeError('Competing writer')
        client = Client(); proxy = self.make(client, refuse)
        with self.assertRaises(RuntimeError):
            proxy.put_object(Bucket='b', Key='indexes/catalog.json', Body=b'x', IfMatch='old')
        self.assertFalse(client.calls)

    def test_lost_ack_does_not_repeat_write(self):
        client = Client(); client.lose_ack = True; proxy = self.make(client)
        proxy.put_object(Bucket='b', Key='indexes/catalog.json', Body=b'x', IfMatch='old')
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(len(self.updated), 1)


if __name__ == '__main__': unittest.main()


def test_upload_and_reconciliation_errors_are_both_preserved_without_resend():
    request = TimeoutError('original PUT')
    readback = OSError('GET failed')
    client = Client()
    def put(**kwargs):
        client.calls.append(kwargs)
        raise request
    def get(**kwargs):
        raise readback
    client.put_object = put; client.get_object = get
    events = []
    proxy = GuardedPublicationClient(client, guard=lambda: None, journal=lambda e, v: events.append(e), after_write=lambda *a: None)
    import pytest
    with pytest.raises(RuntimeError, match='outcome is uncertain') as caught:
        proxy.put_object(Bucket='bucket', Key='viewer-publications/releases/x/file', Body=b'raw', IfNoneMatch='*')
    assert caught.value.__cause__ is request
    assert caught.value.request_error is request
    assert caught.value.reconciliation_error is readback
    assert len(client.calls) == 1
    assert events == ['publication_write_intent']
    assert not proxy._receipts and not proxy._key_locks


def test_ignored_receipts_and_completed_key_locks_have_no_retained_owner():
    client = Client()
    proxy = GuardedPublicationClient(client, guard=lambda: None, journal=lambda *a: None, after_write=lambda *a: None)
    for i in range(50):
        proxy.put_object(Bucket='bucket', Key=f'viewer-publications/releases/x/{i}', Body=b'raw', IfNoneMatch='*')
    assert not proxy._receipts
    assert not proxy._key_locks


def test_same_key_lock_cleanup_keeps_all_waiters_excluded():
    from concurrent.futures import ThreadPoolExecutor
    import threading
    import time
    active = 0
    peak = 0
    lock = threading.Lock()
    client = Client()
    original = client.put_object
    def slow(**kwargs):
        nonlocal active, peak
        with lock:
            active += 1; peak = max(peak, active)
        try:
            time.sleep(.002)
            return original(**kwargs)
        finally:
            with lock:
                active -= 1
    client.put_object = slow
    proxy = GuardedPublicationClient(client, guard=lambda: None, journal=lambda *a: None, after_write=lambda *a: None)
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda _: proxy.put_object(Bucket='bucket', Key='viewer-publications/releases/x/same', Body=b'raw', IfNoneMatch='*'), range(24)))
    assert peak == 1
    assert not proxy._key_locks
    assert not proxy._receipts


def test_invalid_guard_client_and_sdk_retry_policy_fail_before_any_write():
    import pytest
    from types import SimpleNamespace
    options=dict(journal=lambda *a:None,after_write=lambda *a:None)
    with pytest.raises(TypeError,match='conditional put_object'):
        GuardedPublicationClient(SimpleNamespace(get_object=lambda **k:None),guard=lambda:None,**options)
    client=Client()
    with pytest.raises(TypeError,match='check and shared_commit'):
        GuardedPublicationClient(client,guard=SimpleNamespace(check=lambda:None),**options)
    client.meta=SimpleNamespace(config=SimpleNamespace(retries={'total_max_attempts':2}))
    with pytest.raises(ValueError,match='retries must be disabled'):
        GuardedPublicationClient(client,guard=lambda:None,**options)
    assert client.calls==[]


def test_shared_continuation_client_refuses_changed_original_write_condition(tmp_path):
    import pytest
    from guarded_recovery_publication_client import ContinuedPublicationClient
    from recovery_publication_continuation import Continuation
    state=Continuation(tmp_path/'attempt',{})
    client=Client()
    proxy=ContinuedPublicationClient(client,continuation=state,guard=lambda:None,journal=state.record,after_write=lambda *a:None)
    proxy.put_object(Bucket='bucket',Key='indexes/catalog.json',Body=b'raw',IfMatch='original')
    with pytest.raises(ValueError,match='conditions differ'):
        proxy.put_object(Bucket='bucket',Key='indexes/catalog.json',Body=b'raw',IfMatch='changed')
    assert len(client.calls)==1
