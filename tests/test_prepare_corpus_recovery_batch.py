"""Checks for local batch integrity before remote publication is possible."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('prepare_batch', Path(__file__).resolve().parents[1] / 'scripts/prepare_corpus_recovery_batch.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        raw = b'previously validated fixture bytes'
        digest = hashlib.sha256(raw).hexdigest()
        self.key = f'bodies/sha256/{digest[:2]}/{digest}.gz'
        self.body = self.root / 'body'
        self.body.write_bytes(raw)
        self.row = dict(original_url='https://example.org/file.pdf', body_key=self.key,
                        body_path=str(self.body), bytes=len(raw), validated=True)
        self.write('recovered-files.json', [self.row])
        self.write('prepared-zip-receipts.json', [])
        self.write('zip-member-reconciliation.json', [])
        self.write('deferred.json', [])
        self.write('prepared-accepted.json', {'recoveries': [self.row]})

    def write(self, name, value):
        (self.root / name).write_text(json.dumps(value))

    def prepare(self):
        return module.prepare(self.root, self.root / 'deferred.json', self.root / 'sealed')

    def test_valid_batch_and_immutable_destination(self):
        result = self.prepare()
        self.assertEqual(result['recovered_urls'], 1)
        self.assertEqual(result['distinct_bodies'], 1)
        with self.assertRaises(FileExistsError):
            self.prepare()

    def test_corrupt_body_refused_before_snapshot(self):
        self.body.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse((self.root / 'sealed').exists())

    def test_deferred_url_refused(self):
        self.write('deferred.json', [{'url': self.row['original_url']}])
        with self.assertRaises(ValueError):
            self.prepare()

    def test_missing_mapping_refused(self):
        self.write('prepared-accepted.json', {'recoveries': []})
        with self.assertRaises(ValueError):
            self.prepare()

    def test_unassociated_zip_member_refused(self):
        self.write('zip-member-reconciliation.json', [{'body_key': self.key, 'validated': True}])
        with self.assertRaises(ValueError):
            self.prepare()


if __name__ == '__main__':
    unittest.main()
