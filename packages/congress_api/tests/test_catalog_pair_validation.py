"""Shared pair validation avoids rescans and rejects changed content or validators."""
import copy
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pyarrow as pa
import pyarrow.parquet as pq
from congress_api.retention.catalog_validation import validate_catalog_pair

def replace_with_identical_bytes(path):
    """Change custody deterministically, even within one filesystem clock tick."""
    before = path.stat()
    replacement = path.with_suffix('.replacement')
    replacement.write_bytes(path.read_bytes())
    os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
    replacement.replace(path)
    assert path.stat().st_ino != before.st_ino


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
    def test_reused_pair_proof_needs_two_hashes_and_one_validation(self):
        with patch('hashlib.file_digest', wraps=hashlib.file_digest) as hashes:
            proof = self.validate()
            for _ in range(3):
                proof.require(self.root, self.manifest, validator=self.validator, expected_bodies={'body'})
            self.assertEqual(hashes.call_count, 2)
        self.assertEqual(len(self.validations), 1)
    def test_changed_file_identity_rejects_equal_size_bytes_with_restored_mtime(self):
        proof = self.validate(); path = self.root/self.manifest['files']['filenames']['key']
        before = path.stat(); raw = path.read_bytes()
        path.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        with self.assertRaisesRegex(ValueError, 'no longer applies'): proof.require(self.root, self.manifest)
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


def test_normal_catalog_rebuild_checks_references_once_and_fresh_process_has_no_proof(tmp_path, monkeypatch):
    from congress_api.retention import document_index as index
    from historical_raw_catalog import rebuild_catalog
    from test_raw_catalog import initialize
    store = initialize(tmp_path)
    original, calls = index.validate_document_indexes, []
    def counted(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)
    monkeypatch.setattr(index, 'validate_document_indexes', counted)
    result = rebuild_catalog(store, workers=1, repair=True)
    assert len(calls) == 1
    assert __import__('json').loads(__import__('json').dumps(result))['catalog_id'] == result['catalog_id']


def test_direct_local_catalog_build_carries_its_reference_proof_to_selection(tmp_path, monkeypatch):
    from congress_api.retention import document_index as index
    from congress_api.retention.catalog_publication import local_catalog_paths
    calls = []
    original = index.validate_document_indexes
    def counted(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)
    monkeypatch.setattr(index, 'validate_document_indexes', counted)
    result = index.write_filename_metadata(tmp_path, [dict(filename='probe.pdf',
        source_url='https://example.test/probe.pdf', body_key=None)], workers=1)
    assert len(calls) == 1
    assert result['rows'] == result['document_rows'] == 1
    paths = local_catalog_paths(tmp_path)
    assert (result['output'], result['documents_output']) == tuple(str(path) for path in paths)


@__import__('pytest').mark.parametrize('proof_kind', ['serialized', 'changed'])
def test_local_catalog_handoff_does_not_trust_restored_or_changed_proofs(tmp_path, monkeypatch, proof_kind):
    from congress_api.retention import document_index as index
    from congress_api.retention.catalog_cache import LocalStore
    from congress_api.retention.catalog_publication import read_catalog
    from congress_api.retention.catalog_validation import CatalogBuildResult, validate_references
    from test_catalog_publication import pair
    import pytest
    paths = pair(tmp_path / 'build')
    calls = []
    original = index.validate_document_indexes
    def counted(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)
    monkeypatch.setattr(index, 'validate_document_indexes', counted)
    proof = validate_references(*paths, validator=counted)
    result = CatalogBuildResult(rows=1, document_rows=1, validation=proof)
    if proof_kind == 'serialized':
        result = __import__('json').loads(__import__('json').dumps(result))
    else:
        replace_with_identical_bytes(paths[0])
    with read_catalog(LocalStore(tmp_path)) as snapshot:
        if proof_kind == 'changed':
            with pytest.raises(ValueError, match='no longer applies'):
                index.publish_local_result(tmp_path, paths[0], result, snapshot)
            assert not (tmp_path / 'indexes/catalog.json').exists()
        else:
            assert index.publish_local_result(tmp_path, paths[0], result, snapshot)['rows'] == 1
    assert len(calls) == (2 if proof_kind == 'serialized' else 1)


def test_reference_content_proof_reuses_one_scan_across_owned_copy_and_rejects_forgery(tmp_path):
    from congress_api.retention.catalog_validation import validate_references, validate_catalog_pair
    from congress_api.retention.catalog_publication import _properties
    from test_catalog_publication import pair
    from types import SimpleNamespace
    import shutil
    import pytest
    paths = pair(tmp_path / 'build')
    calls = []
    def validator(*args, **kwargs): calls.append(args)
    reference = validate_references(*paths, validator=validator)
    properties = {label: _properties(path) for label, path in zip(('filenames', 'documents'), paths)}
    content = reference.content(properties)
    root = tmp_path / 'retained'; generation = 'a' * 32
    manifest = dict(version=1, generation=generation, catalog_id='one', files={})
    for label, source in zip(('filenames', 'documents'), paths):
        key = f'catalog-generations/{generation}/{source.name}'
        path = root / key; path.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source, path)
        manifest['files'][label] = dict(key=key, **{k: v for k, v in properties[label].items() if k != 'catalog_id'})
    proof = validate_catalog_pair(root, manifest, validator=validator, references=content)
    proof.require(root, manifest)
    assert len(calls) == 1
    with pytest.raises(ValueError, match='no longer applies'):
        copy.copy(proof).require(root, manifest)
    with pytest.raises(ValueError, match='no longer applies'):
        copy.copy(content).require(manifest, validator=validator)
    with pytest.raises(ValueError, match='no longer applies'):
        reference.require(*paths, validator=lambda *_: None)
    replace_with_identical_bytes(paths[0])
    with pytest.raises(ValueError, match='no longer applies'):
        reference.require(*paths, validator=validator)
