"""Stable viewer artifacts preserve custody and upload only newly issued assets."""
import importlib.util
import io
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'tests'),
                str(ROOT / 'packages/viewer_publication/tests')]
from viewer_publication.filename_native import ViewerAssets, validate_publication
from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.catalog_publication import read_catalog
from congress_api.retention.viewer_inventory import issue_inventory
from test_catalog_coalesced_batches import Native
from test_native_catalog_selection import seed
from test_recovery_viewer_transfers import Remote
from viewer_publication.client import GuardedPublicationClient
from viewer_publication import publish_filename_viewer as builder
from viewer_publication import publish_viewer_r2 as publisher


def prepared(tmp_path):
    store, native = LocalStore(tmp_path / 'store'), Native()
    seed(tmp_path, store, native)
    selected = read_catalog(store, native=native)
    manifest = builder.publish_selected(selected, tmp_path / 'first', review_identities=None)
    return selected, manifest


def test_native_inventory_accepts_new_assets_and_keeps_reused_controls_offline(tmp_path):
    selected, manifest = prepared(tmp_path)
    root = tmp_path / 'first'
    publisher.validate_prepared_output(root, manifest)
    validation = issue_inventory(root, manifest.identities, context=manifest)
    files = publisher.prepared_files(root, manifest, validation=validation)
    assert set(files) == set(manifest.identities) - {'manifest.json'}
    again = builder.publish_selected(selected, tmp_path / 'again', previous=manifest,
        read_asset=lambda key: (root / key).read_bytes(), review_identities=None)
    publisher.validate_prepared_output(tmp_path / 'again', again)
    assert publisher.prepared_files(tmp_path / 'again', again) == {}
    assert set(again.identities) == {'manifest.json', again['proof']['path'], again['source_selection']['path']}
    item = next(path for path in files if path.endswith('.parquet'))
    (root / item).write_bytes(b'broken')
    with pytest.raises(ValueError, match='differs from its inventory'):
        publisher.prepared_files(root, manifest)


def test_native_upload_uses_shared_hash_paths_and_exact_pointer_identity(tmp_path, monkeypatch):
    selected, manifest = prepared(tmp_path)
    root, remote = tmp_path / 'first', Remote()
    remote.objects['indexes/catalog.json'] = (json.dumps(selected.manifest).encode(), 'selected')
    files = publisher.prepared_files(root, manifest)
    existing = next(iter(files))
    remote.objects[publisher.PREFIX + existing] = (files[existing].read_bytes(), 'retained-object')
    proxy = GuardedPublicationClient(remote, guard=lambda: None, journal=lambda *args: None, after_write=lambda *args: None)
    monkeypatch.setattr(publisher, 'recovery_for_publication', lambda *args, **kwargs: ({'path':'status'}, (None,None,None,None)))
    monkeypatch.setattr(publisher, 'recovery_inputs', lambda *args, **kwargs: {})
    monkeypatch.setattr(publisher, 'open_public', lambda request: io.BytesIO(remote.objects[publisher.PREFIX + 'manifest.json'][0]))
    result = publisher.upload(proxy, root, manifest, previous_etag=None, selected_etag='selected', probe=lambda *args: None,
        publication_plan=dict(release='releases/' + 'a' * 32 + '/', published_at='fixed'))
    assert result['status'] == 'published'
    pointer = json.loads(remote.objects[publisher.PREFIX + 'manifest.json'][0])
    assert pointer['source_identity'] == manifest['source_identity']
    for path in files:
        assert publisher.PREFIX + path in remote.objects
        assert remote.gets[publisher.PREFIX + path] == (1 if path == existing else 0)
        assert remote.puts[publisher.PREFIX + path] == (0 if path == existing else 1)
    assert not any(key.startswith(publisher.PREFIX + 'releases/' + 'a' * 32 + '/releases/') for key in remote.objects)
