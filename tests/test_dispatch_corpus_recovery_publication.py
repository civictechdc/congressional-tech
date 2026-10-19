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

def verify_coverage(root,manifest,expected):
    from congress_api.retention.catalog_validation import validate_catalog_pair
    return validate_catalog_pair(root,manifest,validator=lambda *_:None,expected_bodies=expected).coverage


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.manifest=dict(version=1,generation='a'*32,catalog_id='paired',files={})
        for label,name in [('filenames','document-filenames.parquet'),('documents','documents.parquet')]:
            key=f"catalog-generations/{self.manifest['generation']}/{name}";p=self.root/key;p.parent.mkdir(parents=True,exist_ok=True)
            table=pa.table({'body_key':['pdf','zip-member']}).replace_schema_metadata({b'catalog_id':b'paired'})
            pq.write_table(table,p);self.manifest['files'][label]=dict(key=key,bytes=p.stat().st_size,sha256=module.digest(p),rows=2)
    def test_all_imported_bodies_required(self):
        result=verify_coverage(self.root,self.manifest,{'pdf','zip-member'})
        self.assertEqual(result['missing_bodies'],0)
        with self.assertRaisesRegex(ValueError,'absent'):
            verify_coverage(self.root,self.manifest,{'pdf','missing-member'})
    def test_corrupt_pair_refused(self):
        p=self.root/self.manifest['files']['documents']['key'];p.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'bytes differ'):
            verify_coverage(self.root,self.manifest,{'pdf'})
    def test_mixed_identity_refused(self):
        self.manifest['catalog_id']='other'
        with self.assertRaisesRegex(ValueError,'identity differs'):
            verify_coverage(self.root,self.manifest,{'pdf'})
    def test_bad_path_refused(self):
        self.manifest['files']['documents']['key']='../elsewhere'
        with self.assertRaisesRegex(ValueError,'path'):
            verify_coverage(self.root,self.manifest,{'pdf'})
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
            from congress_api.retention.raw_catalog import rebuild_catalog_in_directory
            self.assertEqual(rebuild_catalog_in_directory(store, working=working, root=root), [])


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
                             'recovery_publication_continuation.py', 'recovery_guards.py', 'publication_import_evidence.py'):
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
                    def put_object(self, **kwargs): raise AssertionError('Unexpected fixture mutation')
                calls = dict(catalog=0, mappings=0, prepared=0, publication=0)
                def catalog(store, **kwargs):
                    calls['catalog'] += 1
                    if failed_phase == 'incomplete_catalog':
                        (kwargs['root']/'diagnostic.txt').write_text('Preserve incomplete build evidence')
                        raise RuntimeError('Injected incomplete catalog failure')
                    from congress_api.retention.catalog_publication import read_catalog
                    with read_catalog(store) as snapshot:
                        self.assertTrue(snapshot.filenames_path.is_file())
                        self.assertTrue(snapshot.documents_path.is_file())
                    return {'unchanged': True}
                def mapping(*args, **kwargs): calls['mappings'] += 1; return {'complete': True}
                def prepare(source, target, modified=None, *, validation=None):
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
                    return SimpleNamespace(publish=prepare) if 'builder' in name else SimpleNamespace(upload=publish)
                original = Continuation.phase
                def fail_after_accept(continuation, name, *args, **kwargs):
                    result = original(continuation, name, *args, **kwargs)
                    if name == failed_phase: raise RuntimeError('Injected after accepted phase')
                    return result
                args = SimpleNamespace(batch=batch, imported=imported, runtime=root/'runtime', baseline=baseline,
                                       config=config, destination=root/'publication', execute=True, resume=False)
                with patch.object(module, 'ROOT', repo), patch.object(module, 'verify_import', return_value={'complete': True}), \
                     patch.object(module, 'cloud_clear'), patch('congress_api.retention.raw_catalog.rebuild_catalog_in_directory', side_effect=catalog), \
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


def sealed_import_fixture(tmp_path):
    batch = tmp_path / 'batch'; batch.mkdir()
    imported = tmp_path / 'imported'; (imported / 'payloads').mkdir(parents=True)
    capture = dict(captures=[dict(body_key='body')])
    (batch / 'prepared-source-records.json').write_text(json.dumps([capture]))
    (batch / 'zip-receipts.json').write_text('[]')
    files = {name: module.digest(batch / name) for name in ('prepared-source-records.json', 'zip-receipts.json')}
    (batch / 'manifest.json').write_text(json.dumps(dict(files=files)))
    (batch / 'source-record-preparation.json').write_text(json.dumps(dict(unresolved=[], batch_manifest_sha256=module.digest(batch / 'manifest.json'))))
    (batch / 'import-readiness.json').write_text(json.dumps(dict(files=files, capture_rows=1, distinct_capture_bodykeys=1)))
    result = dict(complete=True, added_capture_rows=1, distinct_bodies=1)
    (imported / 'payloads/import-complete.json').write_text(json.dumps(result))
    pins = {str(path): module.digest(path) for path in (batch / 'manifest.json', batch / 'prepared-source-records.json', batch / 'import-readiness.json')}
    events = [dict(event='pins', value=pins), dict(event='import_complete', value=result)]
    (imported / 'events.jsonl').write_text('\n'.join(map(json.dumps, events)))
    return batch, imported, events


def test_bounded_import_evidence_names_malformed_fields_and_keeps_primary_error(tmp_path, monkeypatch):
    import publication_import_evidence as evidence
    import pytest
    batch, imported, _ = sealed_import_fixture(tmp_path)
    assert module.verify_import(batch, imported)['complete']
    path = batch / 'import-readiness.json'
    original = path.read_bytes()
    path.write_text('{broken')
    with pytest.raises(ValueError, match='import-readiness.json.*invalid JSON') as caught:
        module.verify_import(batch, imported)
    assert isinstance(caught.value.__cause__, json.JSONDecodeError)
    path.write_text('{"files":[]}')
    with pytest.raises(ValueError, match='import-readiness.json.*files'):
        module.verify_import(batch, imported)
    path.write_bytes(original)
    monkeypatch.setattr(evidence, 'JSON_BYTES', 4)
    with pytest.raises(ValueError, match='manifest.json.*byte budget'):
        module.verify_import(batch, imported)


@__import__('pytest').mark.parametrize('damage', ['duplicate', 'pins', 'wrong_batch', 'count', 'hash', 'event_size', 'event_count'])
def test_import_evidence_rejects_wrong_or_unbounded_completion_before_dispatch(tmp_path, monkeypatch, damage):
    import publication_import_evidence as evidence
    import pytest
    batch, imported, events = sealed_import_fixture(tmp_path)
    if damage == 'duplicate': events.append(events[-1])
    elif damage == 'pins': events.pop(0)
    elif damage == 'wrong_batch': events[0]['value'][str(batch / 'manifest.json')] = 'f' * 64
    elif damage == 'count':
        path = batch / 'import-readiness.json'; value = json.loads(path.read_text()); value['capture_rows'] = 2
        path.write_text(json.dumps(value))
    elif damage == 'hash': (batch / 'zip-receipts.json').write_text('[{}]')
    elif damage == 'event_size': monkeypatch.setattr(evidence, 'EVENT_BYTES', 10)
    elif damage == 'event_count': monkeypatch.setattr(evidence, 'EVENT_COUNT', 1)
    (imported / 'events.jsonl').write_text('\n'.join(map(json.dumps, events)))
    with pytest.raises(ValueError):
        module.verify_import(batch, imported)


def test_local_publication_keeps_original_conditions_after_own_selector_advance(tmp_path):
    from recovery_publication_continuation import Continuation
    continuation=Continuation(tmp_path/'attempt',{})
    continuation.value['versions'].update({'viewer-publications/manifest.json':'before-viewer','indexes/catalog.json':'selected-source'})
    original=module.publication_conditions(continuation)
    continuation.value['versions']['viewer-publications/manifest.json']='our-selected-pointer'
    continuation.flush()
    restored=Continuation(continuation.root,{},resume=True)
    assert module.publication_conditions(restored)==original=={'previous_etag':'before-viewer','selected_etag':'selected-source'}


@__import__('pytest').mark.parametrize('outcome', ['refused', 'uncommitted', 'readback_failed', 'success', 'lost_ack'])
def test_local_selector_receipt_advances_only_after_guarded_verification(tmp_path, monkeypatch, outcome):
    import hashlib
    import io
    import shutil
    from types import SimpleNamespace
    import pytest
    from botocore.exceptions import ClientError
    import congress_api.retention.raw_catalog as catalog_module
    import congress_api.retention.r2 as storage

    control = tmp_path / 'control'; (control / '.cache').mkdir(parents=True)
    (control / 'scripts').mkdir()
    for name in ('dispatch_corpus_recovery_publication.py', 'guarded_recovery_publication_client.py',
                 'recovery_publication_continuation.py', 'recovery_guards.py', 'publication_import_evidence.py'):
        shutil.copyfile(module.ROOT / 'scripts' / name, control / 'scripts' / name)
    batch = tmp_path / 'batch'; batch.mkdir(); (batch / 'bodies.json').write_text('[]')
    imported = tmp_path / 'imported'; (imported / 'payloads/indexes').mkdir(parents=True)
    for name in ('captures.parquet', 'download-state.parquet'):
        (imported / 'payloads/indexes' / name).write_bytes(b'imported')
    (imported / 'payloads/import-complete.json').write_text('{}')
    (imported / 'events.jsonl').write_text('')
    baseline = tmp_path / 'baseline.json'; baseline.write_text('{}')
    config = tmp_path / 'config.ini'
    config.write_text('[congressionalraw]\nendpoint=https://invalid.test\naccess_key_id=fake\nsecret_access_key=fake\n')
    destination = tmp_path / 'attempt'
    selector = 'indexes/catalog.json'
    before, proposed = b'{"catalog_id":"before"}', b'{"catalog_id":"proposed"}'
    selected_path, proposed_path = destination / 'source' / selector, destination / 'proposed' / selector
    objects = {selector: before, 'indexes/captures.parquet': b'imported', 'indexes/download-state.parquet': b'imported',
               'viewer-publications/recoveries/accepted.json': b'{}', 'viewer-publications/manifest.json': b'{}'}
    etag = lambda raw: hashlib.md5(raw).hexdigest()
    class Client:
        meta = SimpleNamespace(config=SimpleNamespace(retries={'total_max_attempts': 1}))
        puts = 0
        readbacks = 0
        def get_object(self, *, Bucket, Key):
            if Key == selector and self.puts:
                self.readbacks += 1
                assert selected_path.read_bytes() == before
                assert proposed_path.read_bytes() == proposed
                if outcome == 'readback_failed':
                    raise OSError('readback unavailable')
            raw = objects[Key]
            return dict(Body=io.BytesIO(raw), ContentLength=len(raw), ETag=etag(raw))
        def head_object(self, *, Bucket, Key):
            return {'ETag': etag(objects[Key]), 'ContentLength': len(objects[Key])}
        def put_object(self, **kwargs):
            self.puts += 1
            assert kwargs['Key'] == selector and kwargs['IfMatch'] == etag(before)
            assert selected_path.read_bytes() == before and proposed_path.read_bytes() == proposed
            if outcome == 'refused':
                raise ClientError({'Error': {'Code': 'PreconditionFailed'}}, 'PutObject')
            if outcome == 'uncommitted':
                raise TimeoutError('commit unknown')
            objects[selector] = kwargs['Body']
            if outcome == 'lost_ack':
                raise TimeoutError('committed acknowledgment lost')
            return {'ETag': etag(objects[selector])}
    client = Client()
    class StoppedAfterSelection(RuntimeError):
        pass
    def build(store, **kwargs):
        assert store.read(selector) == before
        assert store.put(selector, proposed)
        assert selected_path.read_bytes() == proposed
        raise StoppedAfterSelection('verified selector installed')
    monkeypatch.setattr(module, 'ROOT', control)
    monkeypatch.setattr(module, 'verify_import', lambda *a, **kw: {})
    monkeypatch.setattr(module, 'cloud_clear', lambda: None)
    monkeypatch.setattr(module.shutil, 'disk_usage', lambda *_: SimpleNamespace(free=100 * 1024**3))
    monkeypatch.setattr(storage, '_configure_retries', lambda *_: None)
    monkeypatch.setattr(catalog_module, 'rebuild_catalog_in_directory', build)
    monkeypatch.setattr('boto3.client', lambda *a, **kw: client)
    args = SimpleNamespace(batch=batch, imported=imported, runtime=tmp_path / 'runtime', execute=True,
        destination=destination, baseline=baseline, config=config, resume=False)
    if outcome in ('success', 'lost_ack'):
        with pytest.raises(StoppedAfterSelection):
            module.run(args)
        assert selected_path.read_bytes() == proposed
    else:
        with pytest.raises((RuntimeError, OSError)):
            module.run(args)
        assert selected_path.read_bytes() == before
    assert proposed_path.read_bytes() == proposed
    assert client.puts == 1 and client.readbacks == 1
