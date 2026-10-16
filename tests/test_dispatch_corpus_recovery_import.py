"""Check dispatch refusal and sealed input validation without network writes."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import dispatch_corpus_recovery_import as module


class DispatchTests(unittest.TestCase):
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
