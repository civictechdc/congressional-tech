"""Native source assets reuse exact old routes without rebuilding full tables."""
import sys
from pathlib import Path
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tests'))

from filename_native import NativeSourceAssets, ViewerAssets
from filename_budget import DEFAULT_DECODED_POLICY
from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.catalog_publication import read_catalog
from test_catalog_coalesced_batches import Native
from test_native_catalog_selection import seed


def test_source_route_reuse_never_reopens_old_native_payloads(tmp_path):
    store, native = LocalStore(tmp_path / 'store'), Native()
    owner, rows = seed(tmp_path, store, native)
    selected = read_catalog(store, native=native)
    assets, metrics = ViewerAssets(tmp_path / 'first'), {}
    renderer = NativeSourceAssets(selected, assets, policy=DEFAULT_DECODED_POLICY, metrics=metrics)
    native.reads.clear()
    root = renderer.render(selected.selection['dependency']['source_root'])
    assert len(native.reads) == 1
    node = assets.read_node(root)
    assert node['kind'] == 'source-leaf'
    part = node['source']['files']['filenames']
    with pq.ParquetFile(assets.root / part['path']) as file:
        assert file.metadata.num_rows == 4
        assert set(file.read(columns=['source_id'])['source_id'].to_pylist()) == set(
            row['source_id'] for batch in selected.table('filenames', max_ordered_bytes=1 << 20).iter_batches()
            for row in batch.to_pylist())
    native.reads.clear()
    fresh = ViewerAssets(tmp_path / 'second', read_asset=lambda key: (assets.root / key).read_bytes())
    reused = NativeSourceAssets(selected, fresh, policy=DEFAULT_DECODED_POLICY, metrics={}).render(
        selected.selection['dependency']['source_root'], root)
    assert reused == root and not native.reads and not fresh.identities


def test_components_read_shared_new_pins_once_and_retain_unrelated_browse_members(tmp_path):
    import importlib.util
    import sqlite3
    from filename_native import NativeComponents, BrowsePages
    from test_native_catalog_selection import scope_for
    from test_catalog_dependencies import identity
    from congress_api.retention.catalog_selection import publish_native_catalog
    script = Path(__file__).resolve().parents[3] / 'docs/youtube-coverage/research/scripts/view_document_filenames.py'
    spec = importlib.util.spec_from_file_location('native_component_viewer', script)
    viewer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(viewer)
    store, native = LocalStore(tmp_path / 'store'), Native()
    owner, rows = seed(tmp_path, store, native)
    selected = read_catalog(store, native=native)
    assets = ViewerAssets(tmp_path / 'assets')
    pages = BrowsePages(assets)
    metrics = {}
    with sqlite3.connect(tmp_path / 'first.sqlite') as db:
        renderer = NativeComponents(selected, assets, pages, db, viewer=viewer, policy=DEFAULT_DECODED_POLICY, metrics=metrics)
        planned = renderer.plan(selected.selection['components'])
        native.reads.clear()
        renderer.prepare()
        assert len(native.reads) == 2
        root = renderer.finish(planned)
        browse = pages.build(renderer.ordered_records())
    assert root['stats']['entries'] == 2 and browse['rows'] == 2
    proof = scope_for(tmp_path, store, owner, selected, [], name='split', deletions=[identity(rows[2])])
    publish_native_catalog(store, proof, previous=selected)
    changed = read_catalog(store, native=native)
    with sqlite3.connect(tmp_path / 'second.sqlite') as db:
        renderer = NativeComponents(changed, assets, pages, db, viewer=viewer, policy=DEFAULT_DECODED_POLICY, metrics=metrics)
        planned = renderer.plan(changed.selection['components'], root)
        native.reads.clear()
        renderer.prepare()
        assert len(native.reads) == 2
        updated = renderer.finish(planned)
        result = pages.change(browse, remove=(__import__('json').loads(raw) for raw, in db.execute('SELECT record FROM retired')),
                              add=renderer.ordered_records())
    assert updated['stats']['entries'] == 3
    assert [row['filename'] for row in pages.page(result, offset=0, limit=10)] == ['a.pdf', 'b.pdf', 'other.pdf']
    assert [row['filename'] for row in pages.page(browse, offset=0, limit=10)] == ['b.pdf', 'other.pdf']


def test_native_builder_publishes_stable_roots_and_mapping_only_reuses_all_payloads(tmp_path):
    import importlib.util
    import json
    script = Path(__file__).resolve().parents[1] / 'scripts/publish-filename-viewer.py'
    spec = importlib.util.spec_from_file_location('native_viewer_builder', script)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    store, native = LocalStore(tmp_path / 'store'), Native()
    owner, _ = seed(tmp_path, store, native)
    selected = read_catalog(store, native=native)
    first_metrics = {}
    original = builder.publish_selected(selected, tmp_path / 'first', review_identities=None, memory_metrics=first_metrics)
    assert original['version'] == 6 and original['info']['rows'] == 4
    assert original['roots']['browse']['rows'] == 2
    assert original['inventory']['count'] > 0
    assert len(__import__('json').dumps(original)) < 16000
    assert not list((tmp_path / 'first').glob('**/groups.bin'))
    assert not list((tmp_path / 'first').glob('**/ids/*.bin'))
    native.reads.clear()
    metrics = {}
    again = builder.publish_selected(selected, tmp_path / 'again', previous=original,
        read_asset=lambda key: (tmp_path / 'first' / key).read_bytes(), review_identities=None, memory_metrics=metrics)
    assert again['roots'] == original['roots']
    assert not native.reads and again['inventory'] == dict(head=None, count=0)
    assert metrics['new_asset_bytes'] == 0
    assert set(again.identities) == {'manifest.json', again['proof']['path'], again['source_selection']['path']}
    from filename_native import validate_publication
    validate_publication(ViewerAssets(tmp_path / 'again'), again)
    assert json.loads((tmp_path / 'again/manifest.json').read_bytes()) == again


def test_native_builder_refuses_rule_upgrade_without_hidden_full_rebuild(tmp_path):
    import importlib.util
    import pytest
    script = Path(__file__).resolve().parents[1] / 'scripts/publish-filename-viewer.py'
    spec = importlib.util.spec_from_file_location('native_viewer_upgrade', script)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    store, native = LocalStore(tmp_path / 'store'), Native()
    seed(tmp_path, store, native)
    selected = read_catalog(store, native=native)
    previous = builder.publish_selected(selected, tmp_path / 'first', review_identities=None)
    previous['requirements'] = {'renderer': 'older-rules'}
    native.reads.clear()
    with pytest.raises(ValueError, match='explicit qualified upgrade'):
        builder.publish_selected(selected, tmp_path / 'upgrade', previous=previous, review_identities=None)
    assert not native.reads and not (tmp_path / 'upgrade').exists()


from test_docspec_boundary import native


def test_actual_native_builder_preserves_typed_source_assets(native, tmp_path):
    import importlib.util
    script = Path(__file__).resolve().parents[1] / 'scripts/publish-filename-viewer.py'
    spec = importlib.util.spec_from_file_location('actual_native_viewer_builder', script)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    store = LocalStore(tmp_path / 'store')
    seed(tmp_path, store, native)
    selected = read_catalog(store, native=native)
    manifest = builder.publish_selected(selected, tmp_path / 'public', review_identities=None)
    leaf = ViewerAssets(tmp_path / 'public').read_node(manifest['roots']['sources'])
    path = tmp_path / 'public' / leaf['source']['files']['filenames']['path']
    with pq.ParquetFile(path) as source:
        assert source.schema_arrow.equals(selected.schemas['filenames'], check_metadata=True)
        actual = source.read()
    expected = __import__('pyarrow').Table.from_batches(list(selected.table('filenames', max_ordered_bytes=1 << 20).iter_batches()))
    assert sorted(actual.to_pylist(), key=lambda row: row['source_id']) == sorted(expected.to_pylist(), key=lambda row: row['source_id'])
    from filename_native import public_component
    document_files = {}
    assets = ViewerAssets(tmp_path / 'public')
    for document, _ in selected.components.items(selected.selection['components']):
        entry = public_component(assets, manifest['roots']['components'], document)
        document_files[entry['document_file']['path']] = entry['document_file']
    assert len(document_files) == 1  # One shared physical document chunk, not per document.
    document = pq.read_table(assets.root / next(iter(document_files)))
    expected_documents = __import__('pyarrow').Table.from_batches(list(selected.table('documents', max_ordered_bytes=1 << 20).iter_batches()))
    assert document.schema.equals(expected_documents.schema, check_metadata=True)
    assert sorted(document.to_pylist(), key=lambda row: row['document_id']) == sorted(expected_documents.to_pylist(), key=lambda row: row['document_id'])



def test_public_lookup_returns_stable_members_and_one_bounded_source_asset(tmp_path):
    import importlib.util
    from filename_native import public_component, component_source_ids, locate_source_asset
    script = Path(__file__).resolve().parents[1] / 'scripts/publish-filename-viewer.py'
    spec = importlib.util.spec_from_file_location('lookup_native_viewer', script)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    store, native = LocalStore(tmp_path / 'store'), Native()
    seed(tmp_path, store, native)
    selected = read_catalog(store, native=native)
    manifest = builder.publish_selected(selected, tmp_path / 'public', review_identities=None)
    assets = ViewerAssets(tmp_path / 'public')
    document_id, _ = next(selected.components.items(selected.selection['components']))
    entry = public_component(assets, manifest['roots']['components'], document_id)
    members = list(component_source_ids(assets, entry))
    assert len(members) == entry['source_rows']
    part = locate_source_asset(assets, manifest, members[0])
    with pq.ParquetFile(assets.root / part['files']['filenames']['path']) as file:
        assert members[0] in file.read(columns=['source_id'])['source_id'].to_pylist()


def test_native_builder_rejects_mixed_previous_roots_before_native_reads(tmp_path):
    import importlib.util
    import copy
    import pytest
    script = Path(__file__).resolve().parents[1] / 'scripts/publish-filename-viewer.py'
    spec = importlib.util.spec_from_file_location('mixed_native_viewer', script)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    store, native = LocalStore(tmp_path / 'store'), Native()
    seed(tmp_path, store, native)
    selected = read_catalog(store, native=native)
    previous = builder.publish_selected(selected, tmp_path / 'first', review_identities=None)
    broken = copy.deepcopy(previous)
    broken['roots']['sources']['native_sha256'] = '0' * 64
    native.reads.clear()
    with pytest.raises(ValueError, match='retained selection proof'):
        builder.publish_selected(selected, tmp_path / 'second', previous=broken,
            read_asset=lambda path: (tmp_path / 'first' / path).read_bytes(), review_identities=None)
    assert not native.reads


def test_asset_inventory_pages_are_bounded_and_hash_checked(tmp_path):
    import json
    import pytest
    from filename_native import write_inventory, iterator_inventory
    assets = ViewerAssets(tmp_path / 'assets')
    for index in range(130):
        assets.put_node(dict(index=index))
    inventory = write_inventory(assets)
    refs = list(iterator_inventory(assets, inventory))
    assert inventory['count'] == 130 and len(refs) == 133
    assert {ref['path'] for ref in refs} == set(assets.identities)
    assert all(len(json.loads((assets.root / ref['path']).read_bytes())['assets']) <= 64
               for ref in refs if json.loads((assets.root / ref['path']).read_bytes()).get('kind') == 'asset-inventory')
    (assets.root / inventory['head']['path']).write_bytes(b'{}')
    with pytest.raises(ValueError, match='identity differs'):
        list(iterator_inventory(ViewerAssets(assets.root), inventory))


def test_native_publication_requires_exact_selector_byte_identity(tmp_path):
    import importlib.util
    import pytest
    from filename_native import publication_basis, validate_publication
    script = Path(__file__).resolve().parents[1] / 'scripts/publish-filename-viewer.py'
    spec = importlib.util.spec_from_file_location('selector_identity_viewer', script)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    store, native = LocalStore(tmp_path / 'store'), Native()
    seed(tmp_path, store, native)
    manifest = builder.publish_selected(read_catalog(store, native=native), tmp_path / 'public', review_identities=None)
    assets = ViewerAssets(tmp_path / 'public')
    manifest['source_identity']['selector_sha256'] = '0' * 64
    manifest['proof'] = assets.put_node(dict(version=1, kind='viewer-proof', publication=publication_basis(manifest)))
    with pytest.raises(ValueError, match='native selection identity'):
        validate_publication(assets, manifest)
