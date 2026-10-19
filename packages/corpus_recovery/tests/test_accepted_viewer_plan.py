"""Real local builder/upload acceptance; cloud custody stays in its own route."""
from collections import Counter
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
import pyarrow.parquet as pq
from congress_api.retention.catalog_validation import validate_catalog_pair
from congress_api.retention.document_index import validate_document_indexes
from viewer_publication.local import LocalContinuation
from viewer_publication.client import ContinuedPublicationClient
from corpus_recovery.publication import prepare_viewer

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'apps/site/scripts'))

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value

builder = module('plan_fixture_builder', ROOT / 'apps/site/scripts/publish-filename-viewer.py')
publisher = module('plan_fixture_publisher', ROOT / 'apps/site/scripts/publish-viewer-r2.py')
control = module('plan_fixture_control', ROOT / 'scripts/corpus_recovery/dispatch_corpus_recovery_publication.py')
remote_fixture = module('plan_fixture_remote', ROOT / 'packages/viewer_publication/tests/test_viewer_publication_attempt.py')


@pytest.fixture(scope='module')
def source(tmp_path_factory):
    root = tmp_path_factory.mktemp('accepted-plan-source')
    subprocess.run([sys.executable, str(ROOT / 'apps/site/scripts/filename-test-fixture.py'), str(root)],
                   check=True, capture_output=True)
    return root


def local(source, destination):
    remote = remote_fixture.Remote(source)
    remote.meta = SimpleNamespace(config=SimpleNamespace(retries={'total_max_attempts': 1}))
    continuation = LocalContinuation(destination, dict(pins={'source': 'fixture-source-pin'}))
    continuation.value['versions'] = {key: remote.versions.get(key) for key in (
        'indexes/catalog.json', publisher.ACCEPTED_KEY, publisher.PREFIX + 'manifest.json')}
    continuation.flush()
    manifest = json.loads((source / 'indexes/catalog.json').read_bytes())
    bodies = {body for body in pq.read_table(source / manifest['files']['filenames']['key'], columns=['body_key']).column(0).to_pylist() if body}
    pair = validate_catalog_pair(source, manifest, validator=validate_document_indexes, expected_bodies=bodies)
    def prepare(run=continuation):
        return prepare_viewer(publisher, builder, remote, run, source,
            lambda value: pair.require(source, value, validator=validate_document_indexes, expected_bodies=bodies),
            lambda: pair, control.publication_conditions)
    return remote, continuation, prepare


def public_transport(monkeypatch, remote):
    class Public(io.BytesIO):
        def __init__(self, raw, request):
            partial = request.get_header('Range') == 'bytes=0-3'
            self.status = 206 if partial else 200
            self.headers = {'Access-Control-Allow-Origin': '*', 'Content-Length': str(4 if partial else len(raw)),
                'Access-Control-Expose-Headers': 'Content-Range'}
            if partial:
                self.headers['Content-Range'] = f'bytes 0-3/{len(raw)}'
            super().__init__(raw[:4] if partial else b'' if request.get_method() == 'HEAD' else raw)
    monkeypatch.setattr(publisher, 'open_public', lambda request, **kw: Public(
        remote.objects[publisher.PREFIX + request.full_url.removeprefix(publisher.PUBLIC_URL)], request))


def upload(remote, continuation, plan, probe=lambda *args: None):
    proxy = ContinuedPublicationClient(remote, continuation=continuation, guard=lambda: None,
        journal=continuation.record, after_write=lambda *args: None)
    return publisher.upload(proxy, plan.root, plan.manifest, **plan.conditions,
        publication_plan=plan.release_plan, plan=plan, probe=probe)


def test_real_local_preparation_upload_reuses_pair_inventory_and_status(source, tmp_path, monkeypatch):
    remote, run, prepare = local(source, tmp_path / 'local')
    calls = Counter()
    original = publisher.index_recoveries
    original_files = publisher.prepared_files
    def prepared_files(*args, **kwargs):
        calls['prepared_file_admissions'] += 1
        return original_files(*args, **kwargs)
    monkeypatch.setattr(publisher, 'prepared_files', prepared_files)
    def counted(*args, **kwargs):
        calls['recovery_scans'] += 1
        return original(*args, **kwargs)
    monkeypatch.setattr(publisher, 'index_recoveries', counted)
    plan = prepare()
    assert plan.source_pins == run.value['binding']['pins']
    assert plan.conditions == run.value['publication_inputs']
    assert plan.release_plan == run.value['release_plan']
    assert calls['recovery_scans'] == calls['prepared_file_admissions'] == 1
    assert len(plan.validation.files) == 271  # 269 payloads, manifest and accepted status.
    # These functions must not execute during transfer: the real guarded client
    # and real uploader consume issued file proofs and accepted status instead.
    monkeypatch.setattr(publisher, 'index_recoveries', lambda *a, **k: pytest.fail('Second recovery scan'))
    monkeypatch.setattr(publisher, 'digest', lambda *a, **k: pytest.fail('Repeated output hash'))
    public_transport(monkeypatch, remote)
    result = upload(remote, run, plan)
    assert result['status'] == 'published'
    assert calls['prepared_file_admissions'] == 1
    assert remote.puts[-1][0] == publisher.PREFIX + 'manifest.json'
    assert remote.puts[-1][2] == '*'
    # The original complete accepted recovery result reaches the immutable sidecar.
    pointer = json.loads(remote.objects[publisher.PREFIX + 'manifest.json'])
    assert json.loads(remote.objects[publisher.PREFIX + pointer['recovery']['path']]) == plan.recovery
    for name, item in plan.manifest['files'].items():
        raw = remote.objects[publisher.PREFIX + plan.release_plan['release'] + item['path']]
        assert hashlib.sha256(raw).hexdigest() == item['sha256']


def test_restore_verifies_once_and_plan_refuses_changed_custody_or_conditions(source, tmp_path, monkeypatch):
    from congress_api.retention import viewer_inventory
    from copy import copy
    remote, run, prepare = local(source, tmp_path / 'local')
    plan = prepare()
    hashes = []
    original = viewer_inventory.file_identity
    monkeypatch.setattr(viewer_inventory, 'file_identity', lambda path: hashes.append(str(path)) or original(path))
    restored = LocalContinuation(run.root, run.value['binding'], resume=True)
    accepted = prepare(restored)
    assert len(hashes) == len(accepted.validation.files) == len(set(hashes))
    accepted.require(accepted.root, accepted.manifest)
    assert len(hashes) == len(accepted.validation.files)
    # JSON file facts or a copy-constructed inventory are never authority.
    with pytest.raises(ValueError, match='proof no longer applies'):
        copy(accepted.validation).require(run.root)
    with pytest.raises(ValueError, match='original viewer plan'):
        publisher.upload(remote, accepted.root, accepted.manifest, selected_etag='wrong',
            previous_etag=None, publication_plan=accepted.release_plan, plan=accepted)
    assert not remote.puts
    file = next(accepted.root / item['path'] for item in accepted.manifest['files'].values() if item['bytes'])
    raw = file.read_bytes(); file.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
    with pytest.raises(ValueError, match='custody'):
        accepted.require(accepted.root, accepted.manifest)
    with pytest.raises(ValueError, match='file changed'):
        prepare(restored)


def test_real_local_probe_failure_resumes_original_plan_without_rebuild(source, tmp_path, monkeypatch):
    remote, run, prepare = local(source, tmp_path / 'local')
    plan = prepare(); public_transport(monkeypatch, remote)
    with pytest.raises(RuntimeError, match='probe failed'):
        upload(remote, run, plan, probe=lambda *args: (_ for _ in ()).throw(RuntimeError('probe failed')))
    before = list(remote.puts)
    restored = LocalContinuation(run.root, run.value['binding'], resume=True)
    restored.reconcile(remote, publisher.BUCKET)
    monkeypatch.setattr(builder, 'publish', lambda *a, **k: pytest.fail('Builder called on restore'))
    monkeypatch.setattr(publisher, 'index_recoveries', lambda *a, **k: pytest.fail('Status scan on restore'))
    accepted = prepare(restored)
    assert accepted.conditions == plan.conditions and accepted.release_plan == plan.release_plan
    assert upload(remote, restored, accepted)['status'] == 'published'
    payloads_before = Counter(key for key, _, _ in before if '/releases/' in key)
    payloads_after = Counter(key for key, _, _ in remote.puts if '/releases/' in key)
    assert payloads_after == payloads_before


def test_fresh_process_restore_hashes_complete_inventory_and_refuses_corruption(source, tmp_path):
    remote, run, prepare = local(source, tmp_path / 'local')
    plan = prepare()
    script = '''
import importlib.util, json, pathlib, sys
from viewer_publication.local import LocalContinuation
from viewer_publication.continuation import bounded_json
from congress_api.retention import viewer_inventory
from corpus_recovery.publication import prepare_viewer
root, checkout = map(pathlib.Path, sys.argv[1:])
sys.path.insert(0, str(checkout/'apps/site/scripts'))
def load(name, path):
 spec=importlib.util.spec_from_file_location(name,path); module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
publisher=load('restored_plan_publisher',checkout/'apps/site/scripts/publish-viewer-r2.py')
control=load('restored_plan_control',checkout/'scripts/corpus_recovery/dispatch_corpus_recovery_publication.py')
state=bounded_json(root/'continuation.json')
run=LocalContinuation(root,state['binding'],resume=True)
hashes=[];original=viewer_inventory.file_identity
viewer_inventory.file_identity=lambda path: hashes.append(str(path)) or original(path)
def forbidden(*args,**kwargs):raise AssertionError('Restore rebuilt or contacted external client')
plan=prepare_viewer(publisher,None,None,run,root/'source',forbidden,forbidden,control.publication_conditions)
print(json.dumps(dict(hashes=len(hashes),unique=len(set(hashes)),files=len(plan.validation.files),conditions=plan.conditions,release=plan.release_plan)))
'''
    def restore():
        return subprocess.run([sys.executable, '-c', script, str(run.root), str(ROOT)], capture_output=True, text=True)
    result = restore()
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value['hashes'] == value['unique'] == value['files'] == len(plan.validation.files)
    assert value['conditions'] == plan.conditions and value['release'] == plan.release_plan
    shard = next(p for p in plan.root.rglob('*.bin') if '/ids/' in str(p) and p.stat().st_size)
    data = shard.read_bytes(); shard.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
    result = restore()
    assert result.returncode != 0 and 'Prepared publication file changed' in result.stderr


def test_real_domain_entry_preserves_coverage_pair_proof_and_publication(source, tmp_path, monkeypatch):
    from corpus_recovery.publication import publish_imported
    from congress_api.retention.catalog_publication import read_catalog
    remote, run, _ = local(source, tmp_path / 'domain')
    accepted = dict(version=1, recoveries=[])
    remote.objects[publisher.ACCEPTED_KEY] = publisher.encoded(accepted)
    remote.versions[publisher.ACCEPTED_KEY] = 'accepted-v0'
    run.value['versions'][publisher.ACCEPTED_KEY] = 'accepted-v0'; run.flush()
    batch = tmp_path / 'batch'; batch.mkdir()
    manifest = json.loads((source / 'indexes/catalog.json').read_bytes())
    bodies = {body for body in pq.read_table(source / manifest['files']['filenames']['key'], columns=['body_key']).column(0).to_pylist() if body}
    (batch / 'bodies.json').write_text(json.dumps(sorted(bodies)))
    (batch / 'accepted.json').write_text(json.dumps(accepted))
    baseline = tmp_path / 'baseline.json'; baseline.write_text(json.dumps(accepted))
    # This boundary represents the already completed import/catalog selection.
    # The maintained Store adapter still retains/validates the real pair, and
    # everything from pair verification through builder/upload runs unchanged.
    def catalog(store, **kwargs):
        with read_catalog(store):
            pass
        return dict(unchanged=True)
    monkeypatch.setattr('congress_api.retention.raw_catalog.rebuild_catalog_in_directory', catalog)
    monkeypatch.setattr('congress_api.retention.r2._configure_retries', lambda *args: None)
    public_transport(monkeypatch, remote)
    guard = SimpleNamespace(boundary=lambda: None, check=lambda: None, shared_commit=lambda: None)
    proxy = ContinuedPublicationClient(remote, continuation=run, guard=guard,
        journal=run.record, after_write=lambda *args: None)
    result = publish_imported(client=remote, proxy=proxy, guard=guard, continuation=run,
        destination=run.root, batch=batch, baseline=baseline, bucket=publisher.BUCKET,
        imported=dict(complete=True), builder=builder, publisher=publisher,
        publication_conditions=control.publication_conditions)
    assert result['status'] == 'published'
    assert set(run.value['phases']) == {'catalog', 'mappings', 'prepared', 'publication'}
    coverage = json.loads((run.root / 'coverage.json').read_bytes())
    assert coverage['expected_bodies'] == len(bodies) and coverage['missing_bodies'] == 0
    assert json.loads((run.root / 'source/indexes/catalog.json').read_bytes()) == manifest
    assert json.loads((run.root / 'complete.json').read_bytes())['complete']
    assert all(key.startswith('viewer-publications/') for key, _, _ in remote.puts)


def test_plan_context_cannot_change_protected_inputs_or_status(source, tmp_path):
    remote, run, prepare = local(source, tmp_path / 'local')
    plan = prepare()
    plan.recovery['catalog_id'] = 'not-the-accepted-catalog'
    with pytest.raises(ValueError, match='proof no longer applies'):
        plan.require(plan.root, plan.manifest)
    assert not remote.puts


def test_recovery_plan_cannot_enter_full_upload_before_any_put(source, tmp_path):
    from viewer_publication.plan import accept_viewer_plan
    remote, run, prepare = local(source, tmp_path / 'local')
    full = prepare()
    recovery = accept_viewer_plan(publisher, full.root, full.manifest, validation=full.validation,
        context=full.context(), protected=full.protected, source_pins=full.source_pins,
        release_plan=full.release_plan, conditions=full.conditions, mode='recovery')
    with pytest.raises(ValueError, match='requires an accepted full viewer plan'):
        upload(remote, run, recovery)
    assert not remote.puts
