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
from viewer_publication.local import LocalContinuation
from viewer_publication.client import ContinuedPublicationClient
from corpus_recovery.publication import prepare_viewer

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'apps/site/scripts'))
sys.path.insert(0, str(ROOT / 'tests'))

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
    from congress_api.retention.catalog_cache import LocalStore
    from congress_api.retention.catalog_publication import read_catalog
    from test_catalog_coalesced_batches import Native
    from test_native_catalog_selection import seed
    store, native = LocalStore(root), Native()
    seed(root / 'work', store, native)
    return SimpleNamespace(root=root, native=native, snapshot=read_catalog(store, native=native))


def local(source, destination):
    remote = remote_fixture.Remote(source.root)
    remote.meta = SimpleNamespace(config=SimpleNamespace(retries={'total_max_attempts': 1}))
    continuation = LocalContinuation(destination, dict(pins={'source': 'fixture-source-pin'}))
    continuation.value['versions'] = {key: remote.versions.get(key) for key in (
        'indexes/catalog.json', publisher.ACCEPTED_KEY, publisher.PREFIX + 'manifest.json')}
    continuation.flush()
    def prepare(run=continuation):
        return prepare_viewer(publisher, builder, remote, run, source.snapshot, control.publication_conditions)
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


def test_real_local_preparation_upload_reuses_native_inventory_and_status(source, tmp_path, monkeypatch):
    remote, run, prepare = local(source, tmp_path / 'local')
    calls = Counter()
    import filename_native_recoveries
    original = filename_native_recoveries.index_catalog_recoveries
    original_files = publisher.prepared_files
    def prepared_files(*args, **kwargs):
        calls['prepared_file_admissions'] += 1
        return original_files(*args, **kwargs)
    monkeypatch.setattr(publisher, 'prepared_files', prepared_files)
    def counted(*args, **kwargs):
        calls['recovery_scans'] += 1
        return original(*args, **kwargs)
    monkeypatch.setattr(filename_native_recoveries, 'index_catalog_recoveries', counted)
    plan = prepare()
    assert plan.source_pins == run.value['binding']['pins']
    assert plan.conditions == run.value['publication_inputs']
    assert plan.release_plan == run.value['release_plan']
    assert calls['recovery_scans'] == calls['prepared_file_admissions'] == 1
    assert len(plan.validation.files) == len(plan.files) + 2  # Manifest and accepted status.
    # These functions must not execute during transfer: the real guarded client
    # and real uploader consume issued file proofs and accepted status instead.
    monkeypatch.setattr(publisher, 'index_recoveries', lambda *a, **k: pytest.fail('Second recovery scan'))
    monkeypatch.setattr(filename_native_recoveries, 'index_catalog_recoveries', lambda *a, **k: pytest.fail('Second native recovery scan'))
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
    for name, path in plan.files.items():
        raw = remote.objects[publisher.PREFIX + name]
        assert hashlib.sha256(raw).hexdigest() == hashlib.sha256(path.read_bytes()).hexdigest()


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
    file = next(path for path in accepted.files.values() if path.stat().st_size)
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
    monkeypatch.setattr(builder, 'publish_selected', lambda *a, **k: pytest.fail('Builder called on restore'))
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
plan=prepare_viewer(publisher,None,None,run,None,control.publication_conditions)
print(json.dumps(dict(hashes=len(hashes),unique=len(set(hashes)),files=len(plan.validation.files),conditions=plan.conditions,release=plan.release_plan)))
'''
    def restore():
        return subprocess.run([sys.executable, '-c', script, str(run.root), str(ROOT)], capture_output=True, text=True)
    result = restore()
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value['hashes'] == value['unique'] == value['files'] == len(plan.validation.files)
    assert value['conditions'] == plan.conditions and value['release'] == plan.release_plan
    shard = next(p for p in plan.root.rglob('*.parquet') if p.stat().st_size)
    data = shard.read_bytes(); shard.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
    result = restore()
    assert result.returncode != 0 and 'Prepared publication file changed' in result.stderr


def test_real_domain_entry_preserves_native_coverage_and_publication(source, tmp_path, monkeypatch):
    from corpus_recovery.publication import publish_imported
    from congress_api.retention.catalog_publication import read_catalog
    remote, run, _ = local(source, tmp_path / 'domain')
    accepted = dict(version=1, recoveries=[])
    remote.objects[publisher.ACCEPTED_KEY] = publisher.encoded(accepted)
    remote.versions[publisher.ACCEPTED_KEY] = 'accepted-v0'
    run.value['versions'][publisher.ACCEPTED_KEY] = 'accepted-v0'; run.flush()
    batch = tmp_path / 'batch'; batch.mkdir()
    manifest = source.snapshot.manifest
    bodies = {body for chunk in source.snapshot.table('filenames', max_ordered_bytes=1 << 20).iter_batches()
              for body in chunk.column(chunk.schema.get_field_index('body_key')).to_pylist() if body}
    (batch / 'bodies.json').write_text(json.dumps(sorted(bodies)))
    (batch / 'accepted.json').write_text(json.dumps(accepted))
    baseline = tmp_path / 'baseline.json'; baseline.write_text(json.dumps(accepted))
    # Catalog mutation has its own receipt-derived tests. This boundary starts
    # with that accepted selection; the real native reader, builder and uploader
    # execute here through the maintained recovery entry point.
    raw = SimpleNamespace(snapshot=lambda: SimpleNamespace(identity='raw-fixture'))
    def catalog(store, **kwargs):
        assert kwargs['raw_storage'] is raw and kwargs['expected_bodies'] == bodies
        with read_catalog(store, native=source.native) as snapshot:
            assert snapshot.identity == source.snapshot.identity
        return dict(unchanged=True, selected_identity=source.snapshot.identity,
                    body_coverage=dict(expected_bodies=len(bodies), missing_bodies=0))
    monkeypatch.setattr('congress_api.retention.raw_catalog.update_from_raw', catalog)
    monkeypatch.setattr('congress_api.retention.raw_storage.RawStorage.open', lambda *a: raw)
    monkeypatch.setattr('congress_api.retention.r2._configure_retries', lambda *args: None)
    public_transport(monkeypatch, remote)
    guard = SimpleNamespace(boundary=lambda: None, check=lambda: None, shared_commit=lambda: None)
    proxy = ContinuedPublicationClient(remote, continuation=run, guard=guard,
        journal=run.record, after_write=lambda *args: None)
    result = publish_imported(client=remote, proxy=proxy, guard=guard, continuation=run,
        destination=run.root, batch=batch, baseline=baseline, bucket=publisher.BUCKET,
        imported=dict(complete=True, raw_identity='raw-fixture'), builder=builder, publisher=publisher,
        publication_conditions=control.publication_conditions, native=source.native)
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


def test_local_renderer_upgrade_resumes_before_accepting_prepared_output(source,tmp_path,monkeypatch):
    import filename_native
    remote,run,prepare=local(source,tmp_path/'first')
    plan=prepare();public_transport(monkeypatch,remote)
    assert upload(remote,run,plan)['status']=='published'
    remote.puts.clear()
    target=tmp_path/'upgrade'
    binding=dict(pins={'source':'fixture-source-pin'},renderer_upgrade=True)
    continuation=LocalContinuation(target,binding)
    continuation.value['versions']={key:remote.versions.get(key) for key in (
        'indexes/catalog.json',publisher.ACCEPTED_KEY,publisher.PREFIX+'manifest.json')}
    continuation.flush()
    previous=remote.objects[publisher.PREFIX+'manifest.json']
    original_requirements=filename_native.native_requirements
    monkeypatch.setattr(filename_native,'native_requirements',lambda *a,**k:
        {**original_requirements(*a,**k),'renderer':'fixture-local-upgrade'})
    original=filename_native.publish_selected;completed=[]
    def stop(value):
        if value['event']=='renderer_task_completed' and value.get('task','').startswith('component-chunk:'):
            completed.extend(source.native.reads);raise RuntimeError('worker stopped')
    def interrupted(*args,**options):
        return original(*args,**dict(options,stage_event=stop))
    monkeypatch.setattr(filename_native,'publish_selected',interrupted)
    source.native.reads.clear()
    with pytest.raises(RuntimeError,match='worker stopped'):
        prepare_viewer(publisher,builder,remote,continuation,source.snapshot,control.publication_conditions,
            renderer_upgrade=True)
    assert not continuation.value['phases'] and not remote.puts
    monkeypatch.setattr(filename_native,'publish_selected',original);source.native.reads.clear()
    resumed=LocalContinuation(target,binding,resume=True)
    result=prepare_viewer(publisher,builder,remote,resumed,source.snapshot,control.publication_conditions,
        renderer_upgrade=True,resume_upgrade=True)
    assert not set(completed)&set(source.native.reads)
    assert result.manifest['requirements']['renderer']=='fixture-local-upgrade'
    assert result.conditions==resumed.value['publication_inputs'] and not remote.puts
    assert remote.objects[publisher.PREFIX+'manifest.json']==previous
    source.native.reads.clear()
    again=prepare_viewer(publisher,None,remote,resumed,None,control.publication_conditions,
        renderer_upgrade=True,resume_upgrade=True)
    assert again.manifest==result.manifest and not source.native.reads
