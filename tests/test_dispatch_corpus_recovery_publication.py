"""Publication cannot select an incomplete or mismatched catalog pair."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import pyarrow as pa
import pyarrow.parquet as pq

spec=importlib.util.spec_from_file_location('publication_dispatch',Path(__file__).resolve().parents[1]/'scripts/dispatch_corpus_recovery_publication.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.manifest=dict(generation='a'*32,catalog_id='paired',files={})
        for label,name in [('filenames','document-filenames.parquet'),('documents','documents.parquet')]:
            key=f"catalog-generations/{self.manifest['generation']}/{name}";p=self.root/key;p.parent.mkdir(parents=True,exist_ok=True)
            table=pa.table({'body_key':['pdf','zip-member']}).replace_schema_metadata({b'catalog_id':b'paired'})
            pq.write_table(table,p);self.manifest['files'][label]=dict(key=key,bytes=p.stat().st_size,sha256=module.digest(p),rows=2)
    def test_all_imported_bodies_required(self):
        result=module.verify_coverage(self.root,self.manifest,{'pdf','zip-member'})
        self.assertEqual(result['missing_bodies'],0)
        with self.assertRaisesRegex(ValueError,'absent'):
            module.verify_coverage(self.root,self.manifest,{'pdf','missing-member'})
    def test_corrupt_pair_refused(self):
        p=self.root/self.manifest['files']['documents']['key'];p.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'bytes differ'):
            module.verify_coverage(self.root,self.manifest,{'pdf'})
    def test_mixed_identity_refused(self):
        self.manifest['catalog_id']='other'
        with self.assertRaisesRegex(ValueError,'identity differs'):
            module.verify_coverage(self.root,self.manifest,{'pdf'})
    def test_bad_path_refused(self):
        self.manifest['files']['documents']['key']='../elsewhere'
        with self.assertRaisesRegex(ValueError,'path'):
            module.verify_coverage(self.root,self.manifest,{'pdf'})
    def test_missing_import_cannot_dispatch(self):
        with self.assertRaises(FileNotFoundError):
            module.verify_import(self.root,self.root/'absent-import')

class BuilderBoundaryTests(unittest.TestCase):
    def test_durable_builder_receives_normalized_readings(self):
        from unittest.mock import patch
        store, working, root = object(), object(), Path('durable-build')
        def internal(received_store, captures, **kwargs):
            self.assertIs(received_store, store)
            self.assertIsNone(captures)
            self.assertIs(kwargs['working'], working)
            self.assertEqual(kwargs['root'], root)
            self.assertFalse(kwargs['repair'])
            self.assertFalse(kwargs['inspect_bodies'])
            # The real builder consumes values after expensive receipt recovery.
            return list(kwargs['body_readings'].values())
        with patch('congress_api.retention.raw_catalog._rebuild_catalog', side_effect=internal):
            self.assertEqual(module.rebuild_retained_catalog(store, working=working, root=root), [])

if __name__=='__main__':unittest.main()
