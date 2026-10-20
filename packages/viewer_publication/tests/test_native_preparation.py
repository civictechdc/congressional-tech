"""Local and hosted preparation share exact native reuse and input admission."""
from copy import deepcopy
from functools import partial
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'apps/site/scripts'), str(ROOT / 'tests')]
from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.catalog_publication import read_catalog
from congress_api.retention.viewer_inventory import issue_inventory
from test_catalog_coalesced_batches import Native
from test_native_catalog_selection import seed
from viewer_publication.native import prepare_native_output


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


publisher = load('native_preparation_publisher', ROOT / 'apps/site/scripts/publish-viewer-r2.py')
builder = load('native_preparation_builder', ROOT / 'apps/site/scripts/publish-filename-viewer.py')
# The synthetic catalog is independent of the live review corpus.
fixture_builder = SimpleNamespace(publish_selected=partial(builder.publish_selected, review_identities=None))
ABSENT = (None, None, None, None)


class Remote:
    def __init__(self):
        self.objects, self.reads = {}, []

    def get_object(self, *, Bucket, Key):
        self.reads.append(Key)
        raw = self.objects[Key]
        return dict(Body=io.BytesIO(raw), ContentLength=len(raw))


def first(tmp_path):
    store, native, remote = LocalStore(tmp_path / 'store'), Native(), Remote()
    seed(tmp_path, store, native)
    snapshot = read_catalog(store, native=native)
    root = tmp_path / 'first'
    manifest, recovery = prepare_native_output(publisher, fixture_builder, remote, snapshot, root,
        accepted_record=ABSENT, viewer_record=ABSENT)
    issue_inventory(root, manifest.identities, context={})
    assert not remote.reads
    for path in root.rglob('*'):
        if path.is_file():
            remote.objects[publisher.PREFIX + str(path.relative_to(root))] = path.read_bytes()
    descriptor = dict(path='releases/' + 'a' * 32 + '/recovery.json')
    raw = publisher.encoded(recovery)
    descriptor.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    remote.objects[publisher.PREFIX + descriptor['path']] = raw
    path = 'releases/' + 'a' * 32 + '/manifest.json'
    raw = publisher.encoded(manifest)
    remote.objects[publisher.PREFIX + path] = raw
    pointer = dict(manifest=path, catalog_id=manifest['info']['catalog_id'],
        source_manifest=snapshot.manifest, source_identity=snapshot.identity, recovery=descriptor,
        recovery_inputs=dict(viewer_manifest_sha256=hashlib.sha256(raw).hexdigest()))
    return snapshot, native, remote, manifest, recovery, (pointer, 'old-viewer', None, None)


def test_same_native_selection_reuses_payloads_and_exact_recovery_without_source_reads(tmp_path):
    snapshot, native, remote, old, recovery, previous = first(tmp_path)
    native.reads.clear()
    root = tmp_path / 'second'
    manifest, status = prepare_native_output(publisher, fixture_builder, remote, snapshot, root,
        accepted_record=ABSENT, viewer_record=previous)
    issue_inventory(root, manifest.identities, context={})
    assert manifest['roots'] == old['roots'] and status == recovery
    assert manifest['inventory'] == dict(head=None, count=0)
    assert not native.reads
    assert not list(root.rglob('*.parquet'))


def test_recovery_only_preserves_exact_release_without_builder_or_payload_reads(tmp_path):
    snapshot, native, remote, old, recovery, previous = first(tmp_path)
    native.reads.clear()
    remote.reads.clear()
    root = tmp_path / 'recovery-only'
    manifest, status = prepare_native_output(publisher, None, remote, snapshot, root,
        accepted_record=ABSENT, viewer_record=previous, recovery_only=True)
    assert manifest == old and status == recovery
    assert (root / 'manifest.json').read_bytes() == remote.objects[publisher.PREFIX + previous[0]['manifest']]
    assert set(manifest.identities) == {'manifest.json', old['proof']['path'], old['source_selection']['path']}
    issue_inventory(root, manifest.identities, context={})
    publisher.validate_prepared_output(root, manifest)
    assert not native.reads and not list(root.rglob('*.parquet'))
    assert len(remote.reads) == 4  # Exact manifest/status and two bounded controls.


@pytest.mark.parametrize('missing', [False, True])
def test_recovery_only_requires_same_native_selection_before_output(tmp_path, missing):
    snapshot, native, remote, _, _, previous = first(tmp_path)
    if missing:
        previous = ABSENT
    else:
        snapshot.identity = dict(snapshot.identity, selector_sha256='0' * 64)
    native.reads.clear()
    with pytest.raises(ValueError, match='same selected native catalog'):
        prepare_native_output(publisher, None, remote, snapshot, tmp_path / 'refused',
            accepted_record=ABSENT, viewer_record=previous, recovery_only=True)
    assert not native.reads and not (tmp_path / 'refused').exists()


def test_recovery_only_preserves_unaccepted_existing_output(tmp_path):
    snapshot, native, remote, _, _, previous = first(tmp_path)
    root = tmp_path / 'occupied'
    root.mkdir()
    retained = root / 'manifest.json'
    retained.write_bytes(b'unaccepted retained evidence')
    native.reads.clear()
    with pytest.raises(ValueError, match='fresh empty directory'):
        prepare_native_output(publisher, None, remote, snapshot, root,
            accepted_record=ABSENT, viewer_record=previous, recovery_only=True)
    assert retained.read_bytes() == b'unaccepted retained evidence'
    assert list(root.iterdir()) == [retained] and not native.reads


@pytest.mark.parametrize('which', ['manifest', 'recovery', 'source_identity'])
def test_prior_input_corruption_refuses_before_native_reads_or_output(tmp_path, which):
    snapshot, native, remote, _, _, previous = first(tmp_path)
    pointer = deepcopy(previous[0])
    if which == 'source_identity':
        pointer['source_identity']['selector_sha256'] = '0' * 64
    else:
        path = pointer['manifest'] if which == 'manifest' else pointer['recovery']['path']
        remote.objects[publisher.PREFIX + path] += b' '
    native.reads.clear()
    with pytest.raises(ValueError, match='identity|length|response'):
        prepare_native_output(publisher, fixture_builder, remote, snapshot, tmp_path / 'refused',
            accepted_record=ABSENT, viewer_record=(pointer, *previous[1:]))
    assert not native.reads and not (tmp_path / 'refused').exists()


def test_no_implicit_file_catalog_build(tmp_path):
    remote = Remote()
    with pytest.raises(ValueError, match='explicitly adopted'):
        prepare_native_output(publisher, fixture_builder, remote, read_catalog(LocalStore(tmp_path / 'empty')),
            tmp_path / 'refused', accepted_record=ABSENT, viewer_record=ABSENT)
    assert not remote.reads and not (tmp_path / 'refused').exists()


def test_initial_native_serving_adoption_keeps_historical_withdrawal_reason(tmp_path):
    import filename_review_binding as binding
    from filename_native import ViewerAssets
    snapshot, _, remote, _, _, _ = first(tmp_path)
    identities = binding.load_identities()
    row = identities['rows'][0]
    prior = dict(version=1, catalog_id='historical', review_sha256=identities['review_sha256'],
        rows=[], withdrawn=[dict(index=row['index'], document_id=row['document_id'], reason='body_changed')])
    release = 'releases/' + 'b' * 32 + '/'
    raw = publisher.encoded(prior)
    descriptor = dict(path='generations/previous/viewer-v2/review-binding.json',
                      bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    remote.objects[publisher.PREFIX + release + descriptor['path']] = raw
    old = dict(version=5, info=dict(catalog_id='historical'), source_manifest=dict(version=1, old=True),
               files=dict(review_binding=descriptor))
    raw = publisher.encoded(old)
    remote.objects[publisher.PREFIX + release + 'manifest.json'] = raw
    pointer = dict(manifest=release + 'manifest.json', catalog_id='historical', source_manifest=old['source_manifest'],
                   recovery_inputs=dict(viewer_manifest_sha256=hashlib.sha256(raw).hexdigest()))
    target = tmp_path / 'adopted'
    manifest, _ = prepare_native_output(publisher, builder, remote, snapshot, target,
        accepted_record=ABSENT, viewer_record=(pointer, 'historical-version', None, None))
    placed = ViewerAssets(target).read_node(manifest['files']['review_binding'])
    preserved = next(item for item in placed['withdrawn'] if item['index'] == row['index'])
    assert preserved == dict(prior['withdrawn'][0], source_ids=row['source_ids'])
