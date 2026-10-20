"""One application CAS selects closed scopes and reuses exact shared native pins."""
from copy import deepcopy

import pyarrow as pa
import pytest

from congress_api.retention.catalog_batches import CatalogComponentReader
from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.catalog_dependency_storage import CatalogDependencyStorage
from congress_api.retention.catalog_publication import read_catalog, MANIFEST_KEY
from congress_api.retention.catalog_scope import verify_catalog_scope
from congress_api.retention.catalog_selection import CatalogComponents, publish_native_catalog
from congress_api.retention.catalog_validation import catalog_reference_requirements
from congress_api.retention import document_index as index
from test_catalog_coalesced_batches import Native
from test_catalog_dependencies import source, identity
from test_catalog_scope import grouped_candidate
from test_docspec_boundary import native


def scope_for(tmp_path, store, owner, previous, rows, *, name, deletions=()):
    base = previous.selection['dependency'] if hasattr(previous, 'selection') else None
    prepared, candidate, refs = grouped_candidate(tmp_path, store, owner, base, rows,
                                                 name=name, deletions=deletions)
    return verify_catalog_scope(store, dependencies=owner, dependency_before=base, dependency_after=candidate,
        prepared=prepared, base=previous.identity,
        component_lookup=previous.component_ref if hasattr(previous, 'component_ref') else lambda _: None,
        prepared_components=refs.items(), read_component=CatalogComponentReader(store).read,
        read_new_component=CatalogComponentReader(store, requirements=catalog_reference_requirements()).read,
        rules=dict(grouping='maintained-v1'))


def owner_for(store, native, schema):
    return CatalogDependencyStorage(native=native, store=store, namespace='selection-test',
                                    source_schema=schema, max_rows=64, max_bytes=1 << 20)


def seed(tmp_path, store, native):
    rows = [source('a.pdf', 'A'), source('b.pdf', 'B'), source('a.pdf', 'B'), source('other.pdf', 'O')]
    old_rows, schema, _, _ = index.prepare_document_indexes(deepcopy(rows),
        pa.schema([*index.SOURCE_SCHEMA, ('capture_outcome', index.STRINGS)]))
    owner = owner_for(store, native, schema)
    with read_catalog(store) as empty:
        proof = scope_for(tmp_path, store, owner, empty, old_rows, name='seed')
        publish_native_catalog(store, proof, previous=empty)
    return owner, rows


def test_restart_split_reuses_shared_old_pin_without_old_payload_validation(tmp_path):
    store, native = LocalStore(tmp_path / 'store'), Native()
    owner, rows = seed(tmp_path, store, native)
    old = read_catalog(store, native=native)
    before = deepcopy(native.tables)
    proof = scope_for(tmp_path, store, owner, old, [], name='split', deletions=[identity(rows[2])])
    native.reads.clear()
    publish_native_catalog(store, proof, previous=old)
    selected = read_catalog(LocalStore(store.root), native=native)
    assert not native.reads  # Restart and publication inspect retained proofs, not old payloads.
    assert selected.selection['counts'] == dict(source_rows=3, document_rows=3)
    assert selected.schemas['filenames'].metadata[b'catalog_id'] == b'split'
    actual = pa.Table.from_batches(list(selected.table('filenames', max_ordered_bytes=1 << 20).iter_batches()))
    expected, _, _, _ = index.prepare_document_indexes(deepcopy([rows[0], rows[1], rows[3]]), owner.source_schema)
    assert sorted(actual.to_pylist(), key=identity) == sorted(
        pa.Table.from_pylist(expected, schema=actual.schema).to_pylist(), key=identity)
    assert len(native.reads) == 2  # New mixed split + old shared batch filtered to the unrelated member.
    assert old.selection['counts'] == dict(source_rows=4, document_rows=2)
    assert len(pa.Table.from_batches(list(old.table('filenames', max_ordered_bytes=1 << 20).iter_batches()))) == 4
    assert all(native.tables[key].equals(value, check_metadata=True) for key, value in before.items())
    with pytest.raises(ValueError, match='no complete-file path'):
        _ = selected.filenames_path


def test_competing_publication_keeps_winner_and_retained_snapshot(tmp_path):
    store, native = LocalStore(tmp_path / 'store'), Native()
    owner, rows = seed(tmp_path, store, native)
    first, second = read_catalog(store, native=native), read_catalog(store, native=native)
    a = scope_for(tmp_path, store, owner, first, [], name='a', deletions=[identity(rows[2])])
    b = scope_for(tmp_path, store, owner, second, [], name='b', deletions=[identity(rows[3])])
    publish_native_catalog(store, a, previous=first)
    winner = store.read(MANIFEST_KEY)
    with pytest.raises(RuntimeError, match="Concurrent catalog update"):
        publish_native_catalog(store, b, previous=second)
    assert store.read(MANIFEST_KEY) == winner
    assert len(list(first.components.items(first.selection['components']))) == 2


def test_lost_selector_acknowledgment_reads_exact_result_without_second_cas(tmp_path):
    class LostReply(LocalStore):
        calls = 0
        def put_catalog_manifest(self, data, *, expected_version):
            self.calls += 1
            super().put_catalog_manifest(data, expected_version=expected_version)
            raise OSError('lost completed selector reply')
    store, native = LostReply(tmp_path / 'store'), Native()
    seed(tmp_path, store, native)
    assert store.calls == 1
    assert read_catalog(store).selection['counts']['source_rows'] == 4


def test_bounded_component_reference_pages_bulk_seed_then_local_correction(tmp_path):
    store = LocalStore(tmp_path / 'store')
    components = CatalogComponents(store)
    def ref(name):
        return dict(component=name, page=dict(key='exact-page', sha256='identity', bytes=32))
    initial = [(f'doc-{i:04}', ref(f'doc-{i:04}')) for i in range(130)]
    root = components.apply(None, retired=[], prepared=iter(initial))
    assert dict(components.items(root)) == dict(initial)
    assert all(len(page['members']) <= 64 for _, page in components.routes.leaf_items(root))
    changed = components.apply(root, retired=[initial[0]], prepared=[('new-doc', ref('new-doc'))])
    assert components.lookup(changed, initial[0][0]) is None
    assert components.lookup(root, initial[0][0]) == initial[0][1]
    assert len(list(components.items(changed))) == 130


def test_actual_native_scope_selection_and_shared_read(native, tmp_path):
    store = LocalStore(tmp_path / 'store')
    owner, rows = seed(tmp_path, store, native)
    with read_catalog(store, native=native) as selected:
        result = pa.Table.from_batches(list(selected.table('documents', max_ordered_bytes=1 << 20).iter_batches()))
        assert len(result) == 2
        assert len(set(result['document_id'].to_pylist())) == 2


def test_validator_upgrade_keeps_old_selection_readable_and_refuses_new_reuse(tmp_path, monkeypatch):
    from congress_api.retention import catalog_selection
    store, native = LocalStore(tmp_path / 'store'), Native()
    owner, rows = seed(tmp_path, store, native)
    before = read_catalog(store, native=native)
    proof = scope_for(tmp_path, store, owner, before, [], name='upgrade', deletions=[identity(rows[2])])
    selected_bytes = store.read(MANIFEST_KEY)
    monkeypatch.setattr(catalog_selection, 'catalog_reference_requirements', lambda: {'validator': 'upgraded'})
    historical = read_catalog(LocalStore(store.root), native=native)
    assert len(pa.Table.from_batches(list(historical.table('documents', max_ordered_bytes=1 << 20).iter_batches()))) == 2
    with pytest.raises(ValueError, match='validator requirements changed'):
        publish_native_catalog(store, proof, previous=before)
    assert store.read(MANIFEST_KEY) == selected_bytes


def test_scope_cannot_publish_against_a_different_snapshot(tmp_path):
    store, native = LocalStore(tmp_path / 'store'), Native()
    owner, rows = seed(tmp_path, store, native)
    before = read_catalog(store, native=native)
    proof = scope_for(tmp_path, store, owner, before, [], name='bound', deletions=[identity(rows[2])])
    publish_native_catalog(store, proof, previous=before)
    winner = store.read(MANIFEST_KEY)
    with pytest.raises(ValueError, match='different selected base'):
        publish_native_catalog(store, proof, previous=read_catalog(store, native=native))
    assert store.read(MANIFEST_KEY) == winner
