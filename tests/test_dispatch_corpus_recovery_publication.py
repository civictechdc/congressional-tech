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
        self.root=Path(self.temp.name);self.manifest=dict(version=1,generation='a'*32,catalog_id='paired',files={})
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

class SharedControlTests(unittest.TestCase):
    def test_isolated_publication_obeys_existing_shared_lock(self):
        import fcntl
        from types import SimpleNamespace
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve(); (root/'.cache').mkdir()
            args=SimpleNamespace(batch=root, imported=root, runtime=root, execute=True, control_root=root)
            with (root/'.cache/local-recovery.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with patch.object(module,'verify_import',return_value={}),patch.object(module,'cloud_clear'):
                    with self.assertRaises(BlockingIOError):module.run(args)


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


class DispatcherContinuationTests(unittest.TestCase):
    setUp = CoverageTests.setUp
    def test_unchanged_catalog_and_failures_after_each_accepted_phase(self):
        import io
        import shutil
        import sys
        from types import SimpleNamespace
        from unittest.mock import patch
        from recovery_publication_continuation import Continuation
        scripts = Path(__file__).resolve().parents[1]/'scripts'
        sys.path.insert(0, str(scripts))
        for failed_phase in ('catalog', 'mappings', 'prepared', 'publication', 'incomplete_catalog'):
            with self.subTest(phase=failed_phase), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); repo = root/'repo'; (repo/'.cache').mkdir(parents=True)
                (repo/'scripts').mkdir()
                for name in ('dispatch_corpus_recovery_publication.py', 'guarded_recovery_publication_client.py',
                             'recovery_publication_continuation.py', 'recovery_guards.py'):
                    shutil.copyfile(scripts/name, repo/'scripts'/name)
                batch = root/'batch'; batch.mkdir()
                (batch/'bodies.json').write_text('["pdf", "zip-member"]')
                (batch/'accepted.json').write_text('[]')
                imported = root/'imported'; (imported/'payloads/indexes').mkdir(parents=True)
                for name in ('captures.parquet', 'download-state.parquet'):
                    (imported/'payloads/indexes'/name).write_bytes(b'imported')
                (imported/'payloads/import-complete.json').write_text('{}')
                (imported/'events.jsonl').write_text('')
                baseline = root/'baseline.json'; baseline.write_text('{}')
                config = root/'r2.conf'; config.write_text('[congressionalraw]\nendpoint=https://invalid.test\naccess_key_id=fake\nsecret_access_key=fake\n')
                remote = {'indexes/catalog.json': json.dumps(self.manifest).encode(),
                          'indexes/captures.parquet': b'imported', 'indexes/download-state.parquet': b'imported',
                          'viewer-publications/recoveries/accepted.json': b'{}',
                          'viewer-publications/manifest.json': b'{}'}
                remote.update({item['key']: (self.root/item['key']).read_bytes() for item in self.manifest['files'].values()})
                class Client:
                    meta = SimpleNamespace(config=SimpleNamespace(retries={'total_max_attempts': 1}))
                    def get_object(self, *, Bucket, Key):
                        return dict(Body=io.BytesIO(remote[Key]), ContentLength=len(remote[Key]), ETag='fixed')
                    def head_object(self, **kwargs): return {'ETag': 'fixed'}
                calls = dict(catalog=0, mappings=0, prepared=0, publication=0)
                def catalog(store, **kwargs):
                    calls['catalog'] += 1
                    if failed_phase == 'incomplete_catalog':
                        (kwargs['root']/'diagnostic.txt').write_text('Preserve incomplete build evidence')
                        raise RuntimeError('Injected incomplete catalog failure')
                    store.read('indexes/catalog.json')
                    for item in self.manifest['files'].values(): store.read(item['key'])
                    return {'unchanged': True}
                def mapping(*args, **kwargs): calls['mappings'] += 1; return {'complete': True}
                def prepare(source, target, *, validation=None):
                    self.assertIsNotNone(validation)
                    calls['prepared'] += 1
                    self.assertEqual(json.loads((source/'indexes/catalog.json').read_text()), self.manifest)
                    for item in self.manifest['files'].values(): self.assertTrue((source/item['key']).is_file())
                    target.mkdir(); (target/'manifest.json').write_text('{}')
                    return {'prepared': True}
                def publish(*args, **kwargs):
                    calls['publication'] += 1
                    self.assertTrue(kwargs['publication_plan']['release'].startswith('releases/'))
                    return {'status': 'published'}
                def load(path, name):
                    return SimpleNamespace(publish=prepare) if 'builder' in name else SimpleNamespace(run=publish)
                original = Continuation.phase
                def fail_after_accept(continuation, name, *args, **kwargs):
                    result = original(continuation, name, *args, **kwargs)
                    if name == failed_phase: raise RuntimeError('Injected after accepted phase')
                    return result
                args = SimpleNamespace(batch=batch, imported=imported, runtime=root/'runtime', baseline=baseline,
                                       config=config, destination=root/'publication', execute=True, resume=False)
                with patch.object(module, 'ROOT', repo), patch.object(module, 'verify_import', return_value={'complete': True}), \
                     patch.object(module, 'cloud_clear'), patch.object(module, 'rebuild_retained_catalog', side_effect=catalog), \
                     patch.object(module, 'load', side_effect=load), patch('boto3.client', return_value=Client()), \
                     patch('congress_api.retention.r2._configure_retries'), \
                     patch('congress_api.retention.document_index.validate_document_indexes'), \
                     patch('publish_corpus_recovery_mappings.publish_mappings', side_effect=mapping), \
                     patch.dict(sys.modules, filename_recoveries=SimpleNamespace(accepted_rows=lambda rows: rows)):
                    with patch.object(Continuation, 'phase', fail_after_accept):
                        with self.assertRaisesRegex(RuntimeError, 'Injected'): module.run(args)
                    args.resume = True
                    if failed_phase == 'incomplete_catalog':
                        with self.assertRaisesRegex(RuntimeError, 'Incomplete catalog build retained'):
                            module.run(args)
                        self.assertEqual((args.destination/'build/diagnostic.txt').read_text(), 'Preserve incomplete build evidence')
                    else:
                        self.assertEqual(module.run(args), {'status': 'published'})
                expected_calls = (dict(catalog=1, mappings=0, prepared=0, publication=0)
                                  if failed_phase == 'incomplete_catalog'
                                  else dict(catalog=1, mappings=1, prepared=1, publication=1))
                self.assertEqual(calls, expected_calls)


class ExternalReadinessTests(unittest.TestCase):
    def test_publication_uses_import_pinned_external_readiness_and_remote_proof(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve(); batch = root/'batch'; batch.mkdir()
            imported = root/'imported'; (imported/'payloads').mkdir(parents=True)
            reconciled = root/'reconciled'; reconciled.mkdir()
            capture = dict(captures=[dict(body_key='body')])
            (batch/'prepared-source-records.json').write_text(json.dumps([capture]))
            (batch/'zip-receipts.json').write_text('[]')
            manifest = dict(files={name: module.digest(batch/name) for name in
                                  ('prepared-source-records.json', 'zip-receipts.json')})
            (batch/'manifest.json').write_text(json.dumps(manifest))
            manifest_sha = module.digest(batch/'manifest.json')
            (batch/'source-record-preparation.json').write_text(json.dumps(dict(unresolved=[], batch_manifest_sha256=manifest_sha)))
            readback = reconciled/'remote-body-readback.json'
            readback.write_text(json.dumps(dict(batch_manifest_sha256=manifest_sha)))
            ready = reconciled/'import-readiness.json'
            ready.write_text(json.dumps(dict(files=manifest['files'], capture_rows=1,
                remote_body_readback_sha256=module.digest(readback))))
            result = dict(complete=True, added_capture_rows=1, distinct_bodies=1)
            (imported/'payloads/import-complete.json').write_text(json.dumps(result))
            pins = {str(path): module.digest(path) for path in (batch/'manifest.json', batch/'prepared-source-records.json', ready)}
            (imported/'events.jsonl').write_text('\n'.join(json.dumps(event) for event in
                [dict(event='pins', value=pins), dict(event='import_complete', value=result)]))
            self.assertEqual(module.verify_import(batch, imported, readiness=ready), result)
            readback.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'evidence changed'):
                module.verify_import(batch, imported, readiness=ready)


if __name__ == '__main__': unittest.main()
