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


def test_actual_viewer_materialization_accepts_the_shared_pair_proof(tmp_path):
    from congress_api.retention import document_index as index
    from congress_api.retention.catalog_cache import LocalStore
    from congress_api.retention.catalog_publication import publish_catalog, read_catalog
    import json
    root = tmp_path/'source'; (root/'indexes').mkdir(parents=True)
    source = root/'indexes/document-filenames.parquet'
    schema = index.SOURCE_SCHEMA.append(pa.field('source_occurrences', index.metadata_type('source_occurrences')))
    index.write_document_indexes(source, [dict(body_key=None, filename='probe.pdf',
        source_url='https://example.test/probe.pdf', source_occurrences=[])], schema)
    store = LocalStore(root)
    publish_catalog(store, source, source.with_name('documents.parquet'), previous=read_catalog(store))
    manifest = json.loads((root/'indexes/catalog.json').read_text())
    proof = validate_catalog_pair(root, manifest, validator=index.validate_document_indexes)
    result = builder.publish(root, tmp_path/'prepared', validation=proof)
    assert result['info']['catalog_id'] == manifest['catalog_id']
    assert result['info']['rows'] == 1
    assert result['info']['video_reference_groups'] == 0
    assert all((tmp_path/'prepared'/item['path']).is_file() for item in result['files'].values())


def test_direct_build_refuses_existing_publication_before_reading_inputs(tmp_path):
    target = tmp_path / 'published'; target.mkdir()
    original = b'{"previous":true}\n'
    (target / 'manifest.json').write_bytes(original)
    with __import__('pytest').raises(ValueError, match='fresh empty directory'):
        builder.publish(tmp_path / 'missing-source', target)
    assert (target / 'manifest.json').read_bytes() == original
    assert list(target.iterdir()) == [target / 'manifest.json']


def test_normal_catalog_rebuild_checks_references_once_and_fresh_process_has_no_proof(tmp_path, monkeypatch):
    from congress_api.retention import document_index as index
    from congress_api.retention.raw_catalog import rebuild_catalog
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
    paths[0].write_bytes(paths[0].read_bytes())
    with pytest.raises(ValueError, match='no longer applies'):
        reference.require(*paths, validator=validator)


@__import__('pytest').mark.parametrize('damage', ['interrupt', 'corrupt', 'manifest', 'success'])
def test_fetch_stages_complete_pair_before_replacing_prior_selection(tmp_path, damage):
    from congress_api.retention.catalog_cache import LocalStore
    from congress_api.retention.catalog_publication import publish_catalog, read_catalog
    from test_catalog_publication import pair
    from datetime import datetime, timezone
    import io
    import json
    import pytest
    remote = tmp_path / 'remote'; remote.mkdir()
    store = LocalStore(remote)
    publish_catalog(store, *pair(tmp_path / 'new', 'new'), previous=read_catalog(store))
    manifest = json.loads((remote / 'indexes/catalog.json').read_text())
    root = tmp_path / 'local'; (root / 'indexes').mkdir(parents=True)
    original = b'{"prior":"selected"}'
    (root / 'indexes/catalog.json').write_bytes(original)
    body = io.BytesIO(b'{}' if damage == 'manifest' else json.dumps(manifest).encode())
    class Client:
        def get_object(self, **kwargs): return dict(Body=body, LastModified=datetime.now(timezone.utc))
        def download_file(self, bucket, key, path):
            Path(path).write_bytes(b'partial' if damage == 'corrupt' else (remote / key).read_bytes())
            if damage == 'interrupt': raise OSError('injected interrupted download')
    if damage == 'success':
        builder.fetch(root, client=Client())
        builder.verify(root, json.loads((root / 'indexes/catalog.json').read_text()))
    else:
        with pytest.raises((ValueError, OSError)):
            builder.fetch(root, client=Client())
        assert (root / 'indexes/catalog.json').read_bytes() == original
    assert body.closed
