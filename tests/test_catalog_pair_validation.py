"""Shared pair validation avoids rescans and rejects changed content or validators."""
import copy
import hashlib
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import pyarrow as pa
import pyarrow.parquet as pq
from congress_api.retention.catalog_validation import validate_catalog_pair

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'apps/site/scripts'))
spec = importlib.util.spec_from_file_location('validated_pair_builder', ROOT/'apps/site/scripts/publish-filename-viewer.py')
builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)


class PairValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = dict(version=1, generation='a'*32, catalog_id='paired', files={})
        for label, filename in [('filenames','document-filenames.parquet'), ('documents','documents.parquet')]:
            key = 'catalog-generations/'+'a'*32+'/'+filename
            path = self.root/key; path.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(pa.table({'body_key': ['body']}).replace_schema_metadata({b'catalog_id': b'paired'}), path)
            self.manifest['files'][label] = dict(key=key, bytes=path.stat().st_size, rows=1,
                                               sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        self.validations = []
        self.validator = lambda *paths: self.validations.append(paths)
    def validate(self):
        return validate_catalog_pair(self.root, self.manifest, validator=self.validator, expected_bodies={'body'})
    def test_dispatch_and_builder_share_two_hashes_and_one_pair_validation(self):
        with patch('hashlib.file_digest', wraps=hashlib.file_digest) as hashes:
            proof = self.validate()
            for _ in range(3):
                proof.require(self.root, self.manifest, validator=self.validator, expected_bodies={'body'})
                builder.verify(self.root, self.manifest, validation=proof)
            self.assertEqual(hashes.call_count, 2)
        self.assertEqual(len(self.validations), 1)
    def test_changed_file_identity_rejects_equal_size_bytes_with_restored_mtime(self):
        proof = self.validate(); path = self.root/self.manifest['files']['filenames']['key']
        before = path.stat(); raw = path.read_bytes()
        path.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        with self.assertRaisesRegex(ValueError, 'no longer applies'): builder.verify(self.root, self.manifest, validation=proof)
    def test_manifest_expected_inputs_validator_and_root_are_bound(self):
        proof = self.validate(); changed = copy.deepcopy(self.manifest); changed['catalog_id'] = 'other'
        for root, manifest, options in [(self.root, changed, {}), (self.root/'other', self.manifest, {}),
                (self.root, self.manifest, {'validator': lambda *_: None}),
                (self.root, self.manifest, {'expected_bodies': {'another'}})]:
            with self.assertRaisesRegex(ValueError, 'no longer applies'): proof.require(root, manifest, **options)
    def test_validator_code_replacement_invalidates_reuse(self):
        def original(*paths): return None
        def changed(*paths): return False
        proof = validate_catalog_pair(self.root, self.manifest, validator=original)
        original.__code__ = changed.__code__
        with self.assertRaisesRegex(ValueError, 'no longer applies'): proof.require(self.root, self.manifest)
    def test_corrupt_bytes_missing_bodies_and_failed_pair_validation_do_not_issue_proof(self):
        with self.assertRaisesRegex(ValueError, 'absent'):
            validate_catalog_pair(self.root, self.manifest, validator=self.validator, expected_bodies={'missing'})
        def reject(*paths): raise ValueError('Pair invalid')
        with self.assertRaisesRegex(ValueError, 'Pair invalid'):
            validate_catalog_pair(self.root, self.manifest, validator=reject)
        path = self.root/self.manifest['files']['documents']['key']; path.write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError, 'bytes differ'): self.validate()

if __name__ == '__main__': unittest.main()
