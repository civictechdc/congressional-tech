"""Check dispatch refusal and sealed input validation without network writes."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import shutil
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts/corpus_recovery'))
import dispatch_corpus_recovery_import as module
import test_import_corpus_recovery_batch as fixtures
from botocore.exceptions import ClientError
from congress_api.retention.raw_archive import encode_table
from congress_api.retention.raw_storage import RawStorage
from congress_api.retention.immutable_metadata import encoded
from native_memory_helpers import MemoryNative


class ConditionalClient:
    def __init__(self, change_capture_after_state=False):
        self.data = {
            module.RAW_KEY: encoded(RawStorage(None, MemoryNative())._empty()),
            'indexes/catalog.json': b'{}', 'viewer-publications/recoveries/accepted.json': b'{}',
        }
        self.meta = SimpleNamespace(config=SimpleNamespace(retries={'total_max_attempts': 1}), events=Mock())
        self.change_capture_after_state = change_capture_after_state
        self.writes = []

    def head_object(self, *, Bucket, Key):
        if Key not in self.data:
            raise ClientError({'Error': {'Code': 'NoSuchKey'}}, 'HeadObject')
        raw = self.data[Key]
        return dict(ETag='"' + hashlib.md5(raw).hexdigest() + '"', ContentLength=len(raw))

    def get_object(self, *, Bucket, Key):
        return dict(self.head_object(Bucket=Bucket, Key=Key), Body=io.BytesIO(self.data[Key]))

    def put_object(self, *, Bucket, Key, Body, **options):
        if (options.get('IfNoneMatch') == '*' and Key in self.data
                or 'IfMatch' in options and options['IfMatch'] != self.head_object(Bucket=Bucket, Key=Key)['ETag']):
            raise ClientError({'Error': {'Code': 'PreconditionFailed'}}, 'PutObject')
        self.data[Key] = Body
        self.writes.append((Key, options))
        if Key.startswith('indexes/native-manifests/') and self.change_capture_after_state:
            self.data[module.RAW_KEY] = b'competing update'
        return self.head_object(Bucket=Bucket, Key=Key)


class DispatchTests(unittest.TestCase):
    def exercise_dispatch(self, client, external=False, control_root=None, native=None):
        fixture = fixtures.ImportTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        root = Path(fixture.temp.name).resolve()
        (root / '.cache').mkdir()
        scripts = root / 'scripts/corpus_recovery'
        scripts.mkdir(parents=True)
        for name in ['dispatch_corpus_recovery_import.py', 'reconcile_corpus_recovery_bodies.py']:
            shutil.copyfile(ROOT / 'scripts/corpus_recovery' / name, scripts / name)
        batch = root / 'batch'
        batch.mkdir()
        (batch / 'prepared-source-records.json').write_text('[]')
        (batch / 'zip-receipts.json').write_text(json.dumps(fixture.prepared))
        (batch / 'bodies.json').write_text(json.dumps({k: {'path': str(v), 'sha256': hashlib.sha256(v.read_bytes()).hexdigest(), 'bytes': v.stat().st_size} for k, v in fixture.paths.items()}))
        files = {p.name: module.digest(p) for p in batch.iterdir()}
        (batch / 'manifest.json').write_text(json.dumps(dict(files=files)))
        (batch / 'source-record-preparation.json').write_text(json.dumps(
            dict(unresolved=[], batch_manifest_sha256=module.digest(batch / 'manifest.json'))))
        (batch / 'import-readiness.json').write_text(json.dumps(dict(files={
            p.name: module.digest(p) for p in batch.iterdir()})))
        config = root / 'credentials.ini'
        config.write_text('[congressionalraw]\nendpoint=https://invalid.example\naccess_key_id=fixture\nsecret_access_key=fixture\n')
        args = SimpleNamespace(batch=batch, execute=True, destination=root / 'dispatch', config=config, connect_timeout=15, control_root=control_root)
        self.destination = args.destination
        self.batch = batch
        if external:
            import corpus_recovery.inventory as reconciliation
            reconcile_args = SimpleNamespace(batch=batch, destination=root/'reconciliation',
                prior=None, prior_sha256=None, config=config)
            with patch('boto3.client', return_value=client):
                ready = reconciliation.run(reconcile_args)
            self.assertTrue(ready['ready'])
            args.readiness = root/'reconciliation/import-readiness.json'
            self.readiness_path = args.readiness
        with patch.object(module, 'ROOT', root), patch.object(module, 'cloud_clear'), patch('boto3.client', return_value=client):
            return module.run(args, native=native or MemoryNative())

    def test_full_dispatch_uses_conditional_versions(self):
        client = ConditionalClient()
        result = self.exercise_dispatch(client)
        self.assertTrue(result['complete'])
        self.assertEqual(result['added_capture_rows'], 2)
        for key, options in client.writes:
            self.assertIn('IfMatch' if key == module.RAW_KEY else 'IfNoneMatch', options)
        self.assertTrue((self.destination / 'payloads/import-complete.json').exists())

    def test_maintained_reconciliation_to_raw_import_admission(self):
        client = ConditionalClient()
        result = self.exercise_dispatch(client, external=True)
        self.assertTrue(result['complete'])
        from corpus_recovery import admission
        verified = admission.verify_import(self.batch, self.destination, readiness=self.readiness_path)
        self.assertEqual(verified, result)
        events = [json.loads(row) for row in (self.destination/'events.jsonl').read_text().splitlines()]
        pins = next(row['value'] for row in events if row['event']=='pins')
        import corpus_recovery
        self.assertIn(str(Path(corpus_recovery.__file__).resolve()), pins)
        import corpus_recovery.acknowledge as acknowledgment
        self.assertIn(str(Path(acknowledgment.__file__).resolve()), pins)
        self.assertIn(str(self.readiness_path), pins)
        self.assertIn(str(self.readiness_path.with_name('remote-body-readback.json')), pins)
        self.readiness_path.with_name('remote-body-readback.json').write_text('{}')
        with self.assertRaises(ValueError):admission.verify_import(self.batch,self.destination,readiness=self.readiness_path)

    def test_isolated_runtime_uses_shared_control_lock(self):
        import fcntl
        with tempfile.TemporaryDirectory() as folder:
            control = Path(folder).resolve(); (control/'.cache').mkdir()
            with (control/'.cache/local-recovery.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                client=ConditionalClient()
                with self.assertRaises(BlockingIOError):self.exercise_dispatch(client,control_root=control)
                self.assertEqual(client.writes,[])

    def test_competing_update_stops_dispatch_before_capture_write(self):
        client = ConditionalClient(change_capture_after_state=True)
        with self.assertRaisesRegex(RuntimeError, 'Protected input changed'):
            self.exercise_dispatch(client)
        self.assertNotIn(module.RAW_KEY, [key for key, _ in client.writes])
        self.assertFalse((self.destination / 'payloads/import-complete.json').exists())
        self.assertIn('failed_requires_reconciliation', (self.destination / 'events.jsonl').read_text())

    def test_changed_native_execution_file_blocks_before_raw_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / 'docspec'
            executable.write_bytes(b'original-executable')
            class ChangingNative(MemoryNative):
                def execution_files(self):
                    return (executable,)
                def run_table(self, table, **kwargs):
                    pin = super().run_table(table, **kwargs)
                    executable.write_bytes(b'changed-executable')
                    return pin
            client = ConditionalClient()
            with self.assertRaisesRegex(RuntimeError, 'Pinned input changed'):
                self.exercise_dispatch(client, native=ChangingNative())
            self.assertNotIn(module.RAW_KEY, [key for key, _ in client.writes])
            pins = next(json.loads(line)['value'] for line in (self.destination/'events.jsonl').read_text().splitlines()
                        if json.loads(line)['event'] == 'pins')
            self.assertEqual(pins[str(executable)], hashlib.sha256(b'original-executable').hexdigest())

    def test_active_writer_on_later_page_blocks(self):
        response = dict(total_count=1, workflow_runs=[
            dict(id=123, event='workflow_dispatch', status='in_progress')])
        with patch.object(module.subprocess, 'check_output', return_value=json.dumps(response)):
            with self.assertRaisesRegex(RuntimeError, '123'):
                module.cloud_clear()

    def test_unknown_cloud_status_fails_closed(self):
        with patch.object(module.subprocess, 'check_output', side_effect=subprocess.TimeoutExpired('gh', 60)):
            with self.assertRaises(subprocess.TimeoutExpired):
                module.cloud_clear()

    def test_preflight_creates_no_dispatch_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(batch=Path(directory), execute=False,
                                   destination=Path(directory) / 'dispatch')
            (Path(directory) / 'import-readiness.json').write_text('{}')
            with patch.object(module, 'verify_batch', return_value={}), patch.object(module, 'cloud_clear'):
                result = module.run(args)
            self.assertFalse(result['writes'])
            self.assertFalse(args.destination.exists())

    def test_sealed_source_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            batch = Path(directory)
            (batch / 'recoveries.json').write_text('[]')
            digest = hashlib.sha256(b'[]').hexdigest()
            (batch / 'manifest.json').write_text(json.dumps(dict(files={'recoveries.json': digest})))
            manifest_hash = module.digest(batch / 'manifest.json')
            (batch / 'source-record-preparation.json').write_text(json.dumps(
                dict(unresolved=[], batch_manifest_sha256=manifest_hash)))
            (batch / 'import-readiness.json').write_text(json.dumps(dict(files={
                'manifest.json': manifest_hash,
                'source-record-preparation.json': module.digest(batch / 'source-record-preparation.json')})))
            module.verify_batch(batch)
            (batch / 'recoveries.json').write_text('[1]')
            with self.assertRaisesRegex(ValueError, 'Batch changed'):
                module.verify_batch(batch)


if __name__ == '__main__':
    unittest.main()
