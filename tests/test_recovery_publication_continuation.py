"""Explicit continuation reuses accepted phases and reconciles exact remote bytes."""
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from recovery_publication_continuation import Continuation
from guarded_recovery_publication_client import GuardedPublicationClient


class Remote:
    def __init__(self):
        self.objects = {}; self.puts = 0; self.lost_ack = False
    def get_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject')
        raw, version = self.objects[Key]
        return dict(Body=io.BytesIO(raw), ContentLength=len(raw), ETag=version)
    def put_object(self, **kwargs):
        key, body = kwargs['Key'], kwargs['Body']
        if key in self.objects and kwargs.get('IfNoneMatch') == '*':
            raise AssertionError('Duplicate immutable write')
        self.puts += 1
        self.objects[key] = (body, 'v'+str(self.puts))
        if self.lost_ack: raise TimeoutError('Lost acknowledgment')
        return {'ETag': self.objects[key][1]}


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'run'
        self.binding = {'batch_sha256': 'sealed', 'runtime_sha256': 'pinned'}
        self.c = Continuation(self.root, self.binding)
    def resume(self):
        return Continuation(self.root, self.binding, resume=True)
    def intent(self, key, raw, **condition):
        value = dict(key=key, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                     expected_etag=condition.get('IfMatch'), if_none_match=condition.get('IfNoneMatch'))
        self.c.record('publication_write_intent', value)
    def test_failure_after_every_accepted_phase_skips_prior_work(self):
        calls = []
        for name in ('catalog', 'mappings', 'prepared', 'publication'):
            self.c.phase(name, lambda n=name: calls.append(n) or {'accepted': n}, files=lambda: [])
            self.c = self.resume()  # The next invocation explicitly resumes.
            for accepted in list(calls):
                self.assertEqual(self.c.phase(accepted, lambda: self.fail('Repeated phase'), files=lambda: []),
                                 {'accepted': accepted})
        self.assertEqual(calls, ['catalog', 'mappings', 'prepared', 'publication'])
    def test_phase_files_and_binding_must_remain_exact(self):
        self.c.save('output', b'checked')
        self.c.phase('catalog', lambda: {}, files=lambda: [self.root/'output'])
        (self.root/'output').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'phase changed'):
            self.resume().phase('catalog', lambda: {}, files=lambda: [])
        with self.assertRaisesRegex(ValueError, 'inputs changed'):
            Continuation(self.root, {'other': 'batch'}, resume=True)
    def test_uncertain_committed_write_reconciles_without_put(self):
        remote = Remote(); key = 'indexes/catalog.json'; raw = b'new catalog'
        self.c.value['versions'][key] = 'old'; self.intent(key, raw, IfMatch='old')
        remote.objects[key] = (raw, 'committed')
        continued = self.resume(); continued.reconcile(remote, 'b')
        self.assertEqual(continued.value['versions'][key], 'committed')
        self.assertEqual(continued.replay(remote, 'b', key, raw), {'ETag': 'committed'})
        self.assertEqual(remote.puts, 0)
    def test_uncertain_uncommitted_request_allows_explicit_later_write(self):
        remote = Remote(); key = 'viewer-publications/releases/x/file'
        self.intent(key, b'file', IfNoneMatch='*')
        continued = self.resume(); continued.reconcile(remote, 'b')
        self.assertIsNone(continued.replay(remote, 'b', key, b'file'))
        self.assertEqual(remote.puts, 0)
    def test_stale_generation_and_changed_verified_version_refused(self):
        remote = Remote(); key = 'indexes/catalog.json'
        self.intent(key, b'ours', IfMatch='old'); remote.objects[key] = (b'newer catalog', 'newer')
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            self.resume().reconcile(remote, 'b')
        remote.objects[key] = (b'ours', 'ours'); self.c.reconcile(remote, 'b')
        remote.objects[key] = (b'ours', 'rewritten')
        with self.assertRaisesRegex(ValueError, 'version changed'):
            self.resume().reconcile(remote, 'b')
    def test_lost_ack_then_process_restart_never_duplicates_write(self):
        remote = Remote(); remote.lost_ack = True
        proxy = GuardedPublicationClient(remote, guard=lambda: None,
            journal=self.c.record, after_write=lambda key, version: None)
        key = 'viewer-publications/releases/x/file'
        proxy.put_object(Bucket='b', Key=key, Body=b'full bytes', IfNoneMatch='*')
        continued = self.resume(); continued.reconcile(remote, 'b')
        self.assertEqual(continued.replay(remote, 'b', key, b'full bytes'), {'ETag': 'v1'})
        self.assertEqual(remote.puts, 1)
    def test_definite_immutable_locator_refusal_does_not_block_later_resume(self):
        remote = Remote(); key = 'viewer-publications/catalogs/existing.json'
        remote.objects[key] = (b'old locator', 'old')
        def refuse(**kwargs):
            raise ClientError({'Error': {'Code': 'PreconditionFailed'}}, 'PutObject')
        remote.put_object = refuse
        proxy = GuardedPublicationClient(remote, guard=lambda: None,
            journal=self.c.record, after_write=lambda *a: None)
        with self.assertRaises(ClientError):
            proxy.put_object(Bucket='b', Key=key, Body=b'new locator', IfNoneMatch='*')
        self.assertNotIn(key, self.c.value['writes'])
        self.resume().reconcile(remote, 'b')
    def test_different_replay_payload_is_refused(self):
        remote = Remote(); key = 'viewer-publications/releases/x/file'
        self.intent(key, b'exact', IfNoneMatch='*'); remote.objects[key] = (b'exact', 'v1')
        self.c.reconcile(remote, 'b')
        with self.assertRaisesRegex(ValueError, 'write differs'):
            self.c.replay(remote, 'b', key, b'changed')

if __name__ == '__main__': unittest.main()
