"""A guarded viewer transfer performs one full read and preserves public probes."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
sys.path.insert(0, str(ROOT/'apps/site/scripts'))
from guarded_recovery_publication_client import GuardedPublicationClient, VerifiedTransfer

spec = importlib.util.spec_from_file_location('recovery_transfer_publisher', ROOT/'apps/site/scripts/publish-viewer-r2.py')
publisher = importlib.util.module_from_spec(spec); spec.loader.exec_module(publisher)


class Remote:
    def __init__(self):
        self.objects = {}; self.gets = Counter(); self.puts = Counter(); self.lost_ack = False
        self.barrier = None; self.active = self.peak = 0; self.lock = threading.Lock()
    def head_object(self, *, Bucket, Key):
        raw, etag = self.objects[Key]
        return dict(ETag=etag, ContentLength=len(raw))
    def get_object(self, *, Bucket, Key):
        self.gets[Key] += 1
        raw, etag = self.objects[Key]
        return dict(Body=io.BytesIO(raw), ContentLength=len(raw), ETag=etag, LastModified=datetime(2026, 10, 16, tzinfo=timezone.utc))
    def put_object(self, **kwargs):
        if self.barrier is not None:
            with self.lock:
                self.active += 1; self.peak = max(self.peak, self.active)
            self.barrier.wait(timeout=5)
        key = kwargs['Key']; body = kwargs['Body']
        raw = body if isinstance(body, bytes) else body.read()
        etag = hashlib.md5(raw).hexdigest()
        self.objects[key] = raw, etag; self.puts[key] += 1
        if self.barrier is not None:
            with self.lock: self.active -= 1
        if self.lost_ack: raise TimeoutError('Lost PUT acknowledgment')
        return {'ETag': etag}
    def download_file(self, bucket, key, filename):
        response = self.get_object(Bucket=bucket, Key=key)
        Path(filename).write_bytes(response['Body'].read())


class TransferTests(unittest.TestCase):
    def proxy(self, remote, guard=lambda: None):
        return GuardedPublicationClient(remote, guard=guard, journal=lambda *a: None, after_write=lambda *a: None)
    def test_publisher_reads_each_payload_once_even_when_put_ack_is_lost(self):
        for lost_ack in (False, True):
            with self.subTest(lost_ack=lost_ack), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); files = {}
                for name in ('one.bin', 'two.bin'):
                    files[name] = root/name; files[name].write_bytes(name.encode()*10)
                remote = Remote(); remote.lost_ack = lost_ack
                selected = {'catalog_id': 'selected'}
                remote.objects['indexes/catalog.json'] = (json.dumps(selected).encode(), 'selected-etag')
                manifest = dict(info={'catalog_id': 'selected'}, source_manifest=selected)
                probes = []
                def public_open(request):
                    probes.append('pointer')
                    return io.BytesIO(remote.objects['viewer-publications/manifest.json'][0])
                with patch.object(publisher, 'prepared_files', return_value=files), \
                     patch.object(publisher, 'recovery_for_publication', return_value=None), \
                     patch.object(publisher, 'open_public', side_effect=public_open):
                    result = publisher.upload(self.proxy(remote), root, manifest,
                        previous_etag='before', selected_etag='selected-etag',
                        probe=lambda *a: probes.append('payloads'),
                        publication_plan=dict(release='releases/'+'a'*32+'/', published_at='fixed'))
                self.assertEqual(result['status'], 'published')
                self.assertEqual(probes, ['payloads', 'pointer'])
                for name in files:
                    key = 'viewer-publications/releases/'+'a'*32+'/'+name
                    self.assertEqual(remote.gets[key], 1)
                    self.assertEqual(remote.puts[key], 1)
    def test_receipt_binds_issuing_client_exact_request_and_current_version(self):
        remote = Remote(); proxy = self.proxy(remote)
        key = 'viewer-publications/releases/x/file'
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'file'; path.write_bytes(b'bytes')
            receipt = proxy.upload_file(path, 'b', key)
            expected = dict(bucket='b', key=key, size=5, sha256=hashlib.sha256(b'bytes').hexdigest())
            forged = VerifiedTransfer(receipt.bucket, receipt.key, receipt.bytes, receipt.sha256, receipt.etag)
            self.assertFalse(proxy.confirm_transfer(forged, **expected))
            self.assertFalse(self.proxy(remote).confirm_transfer(receipt, **expected))
            remote.objects[key] = (b'bytes', 'changed-version')
            self.assertFalse(proxy.confirm_transfer(receipt, **expected))
            self.assertFalse(proxy.confirm_transfer(receipt, **expected))
    def test_six_immutable_uploads_overlap(self):
        remote = Remote(); remote.barrier = threading.Barrier(6); proxy = self.proxy(remote)
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda n: proxy.put_object(Bucket='b',
                Key=f'viewer-publications/releases/x/{n}', Body=str(n).encode(), IfNoneMatch='*'), range(6)))
        self.assertEqual(len(results), 6); self.assertEqual(remote.peak, 6)
    def test_shared_writes_use_fresh_guard_immutable_uses_cached_check(self):
        calls = []
        class Guard:
            def check(self): calls.append('check')
            def shared_commit(self): calls.append('shared')
        proxy = self.proxy(Remote(), Guard())
        proxy.put_object(Bucket='b', Key='viewer-publications/releases/x/file', Body=b'a', IfNoneMatch='*')
        proxy.put_object(Bucket='b', Key='viewer-publications/manifest.json', Body=b'b', IfMatch='old')
        proxy.put_object(Bucket='b', Key='indexes/processing/status.json', Body=b'c', IfNoneMatch='*')
        self.assertEqual(calls, ['check', 'shared', 'shared'])

if __name__ == '__main__': unittest.main()
