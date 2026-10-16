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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import dispatch_corpus_recovery_import as module
import test_import_corpus_recovery_batch as fixtures
from botocore.exceptions import ClientError
from congress_api.retention.raw_archive import encode_table


class ConditionalClient:
    def __init__(self, change_capture_after_state=False):
        self.data = {
            module.CAPTURES_KEY: encode_table(fixtures.pa.Table.from_pylist([], schema=fixtures.CAPTURE_SCHEMA)),
            module.STATE_KEY: encode_table(fixtures.pa.Table.from_pylist([], schema=fixtures.STATE_SCHEMA)),
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
        if Key == module.STATE_KEY and self.change_capture_after_state:
            self.data[module.CAPTURES_KEY] = b'competing update'
        return self.head_object(Bucket=Bucket, Key=Key)


class DispatchTests(unittest.TestCase):
    def exercise_dispatch(self, client):
        fixture = fixtures.ImportTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        root = Path(fixture.temp.name)
        (root / '.cache').mkdir()
        (root / 'scripts').mkdir()
        for name in ['dispatch_corpus_recovery_import.py', 'import_corpus_recovery_batch.py',
                     'assemble_corpus_recovery_import.py']:
            shutil.copyfile(ROOT / 'scripts' / name, root / 'scripts' / name)
        batch = root / 'batch'
        batch.mkdir()
        (batch / 'prepared-source-records.json').write_text('[]')
        (batch / 'zip-receipts.json').write_text(json.dumps(fixture.prepared))
        (batch / 'bodies.json').write_text(json.dumps({k: {'path': str(v)} for k, v in fixture.paths.items()}))
        files = {p.name: module.digest(p) for p in batch.iterdir()}
        (batch / 'manifest.json').write_text(json.dumps(dict(files=files)))
        (batch / 'source-record-preparation.json').write_text(json.dumps(
            dict(unresolved=[], batch_manifest_sha256=module.digest(batch / 'manifest.json'))))
        (batch / 'import-readiness.json').write_text(json.dumps(dict(files={
            p.name: module.digest(p) for p in batch.iterdir()})))
        config = root / 'credentials.ini'
        config.write_text('[congressionalraw]\nendpoint=https://invalid.example\naccess_key_id=fixture\nsecret_access_key=fixture\n')
        args = SimpleNamespace(batch=batch, execute=True, destination=root / 'dispatch', config=config)
        self.destination = args.destination
        with patch.object(module, 'ROOT', root), patch.object(module, 'cloud_clear'), patch('boto3.client', return_value=client):
            return module.run(args)

    def test_full_dispatch_uses_conditional_versions(self):
        client = ConditionalClient()
        result = self.exercise_dispatch(client)
        self.assertTrue(result['complete'])
        self.assertEqual(result['added_capture_rows'], 2)
        for key, options in client.writes:
            self.assertIn('IfMatch' if key.startswith('indexes/') else 'IfNoneMatch', options)
        self.assertTrue((self.destination / 'payloads/import-complete.json').exists())

    def test_competing_update_stops_dispatch_before_capture_write(self):
        client = ConditionalClient(change_capture_after_state=True)
        with self.assertRaisesRegex(RuntimeError, 'Protected input changed'):
            self.exercise_dispatch(client)
        self.assertNotIn(module.CAPTURES_KEY, [key for key, _ in client.writes])
        self.assertFalse((self.destination / 'payloads/import-complete.json').exists())
        self.assertIn('failed_requires_reconciliation', (self.destination / 'events.jsonl').read_text())

    def test_active_writer_on_later_page_blocks(self):
        pages = [dict(workflow_runs=[]), dict(workflow_runs=[
            dict(id=123, event='workflow_dispatch', status='in_progress')])]
        with patch.object(module.subprocess, 'check_output', return_value=json.dumps(pages)):
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
