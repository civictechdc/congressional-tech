"""Maintained native update runs grouping, retained proof and one selector CAS."""
import pyarrow as pa
import pytest

from test_catalog_coalesced_batches import Native
from test_native_catalog_selection import seed
from test_catalog_dependencies import identity
from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.catalog_publication import read_catalog, MANIFEST_KEY
from congress_api.retention import catalog_updates as updates


def test_native_caller_bridge_split_resumes_prepared_proof_without_native_rework(tmp_path, monkeypatch):
    store, native = LocalStore(tmp_path / 'store'), Native()
    owner, rows = seed(tmp_path, store, native)
    previous = read_catalog(store, native=native)
    arguments = dict(native=native, previous=previous, dependencies=owner,
        deletions=[identity(rows[2])], candidate='caller-split', directory=tmp_path / 'update',
        max_chunk_rows=64, max_chunk_bytes=1 << 20, rules=dict(grouping='maintained-v1'))
    publish = updates.publish_native_catalog
    monkeypatch.setattr(updates, 'publish_native_catalog',
                        lambda *a, **k: (_ for _ in ()).throw(OSError('worker stopped before selector')))
    original_selector = store.read(MANIFEST_KEY)
    with pytest.raises(OSError, match='worker stopped'):
        updates.update_native_catalog(store, **arguments)
    assert store.read(MANIFEST_KEY) == original_selector
    assert (tmp_path / 'update' / 'prepared-scope.json').exists()
    monkeypatch.setattr(updates, 'publish_native_catalog', publish)
    monkeypatch.setattr(native, 'run_table', lambda *a, **k: (_ for _ in ()).throw(AssertionError('Prepared work repeated')))
    result = updates.update_native_catalog(store, **arguments)
    current = read_catalog(store, native=native)
    assert result['counts'] == dict(source_rows=3, document_rows=3)
    assert result['scope_reference'] == current.selection['scope']
    actual = pa.Table.from_batches(list(current.table('filenames', max_ordered_bytes=1 << 20).iter_batches())).to_pylist()
    assert {identity(row) for row in actual} == {identity(row) for row in [rows[0], rows[1], rows[3]]}
    assert updates.update_native_catalog(store, **{**arguments, 'previous': current})['unchanged']
    with pytest.raises(ValueError, match='continuation inputs differ'):
        updates.update_native_catalog(store, **{**arguments, 'candidate': 'other'})


def test_mid_native_chunk_failure_replays_same_completed_immutable_inputs(tmp_path, monkeypatch):
    store, native = LocalStore(tmp_path / 'store'), Native()
    owner, rows = seed(tmp_path, store, native)
    previous = read_catalog(store, native=native)
    original = native.run_table
    completed, attempts = {}, []
    def interrupted(table, **request):
        if request['dataset'].startswith('catalog-filenames-'):
            attempts.append(request['dataset'])
            if len(attempts) == 2:
                raise OSError('worker lost midway through output chunks')
            completed[request['dataset']] = table
        return original(table, **request)
    monkeypatch.setattr(native, 'run_table', interrupted)
    arguments = dict(native=native, previous=previous, dependencies=owner,
        deletions=[identity(rows[2])], candidate='midchunk-split', directory=tmp_path / 'update',
        max_chunk_rows=1, max_chunk_bytes=1 << 20, rules=dict(grouping='maintained-v1'))
    selector = store.read(MANIFEST_KEY)
    with pytest.raises(OSError, match='midway'):
        updates.update_native_catalog(store, **arguments)
    assert store.read(MANIFEST_KEY) == selector
    assert not (tmp_path / 'update' / 'prepared-scope.json').exists()
    def replay(table, **request):
        if request['dataset'] in completed:
            assert table.equals(completed[request['dataset']], check_metadata=True)
        return original(table, **request)
    monkeypatch.setattr(native, 'run_table', replay)
    assert updates.update_native_catalog(store, **arguments)['counts'] == dict(source_rows=3, document_rows=3)
    assert all(native.tables[key].equals(table, check_metadata=True) for key, table in completed.items())


from test_docspec_boundary import native


def test_actual_native_caller_changes_only_closed_document_scope(tmp_path, native):
    from copy import deepcopy
    from congress_api.retention import document_index as index
    store = LocalStore(tmp_path / 'store')
    owner, rows = seed(tmp_path, store, native)
    previous = read_catalog(store, native=native)
    result = updates.update_native_catalog(store, native=native, previous=previous, dependencies=owner,
        deletions=[identity(rows[2])], candidate='actual-caller-split', directory=tmp_path / 'update',
        max_chunk_rows=64, max_chunk_bytes=1 << 20, rules=dict(grouping='maintained-v1'))
    current = read_catalog(LocalStore(store.root), native=native)
    actual = pa.Table.from_batches(list(current.table('filenames', max_ordered_bytes=1 << 20).iter_batches()))
    expected, _, documents, _ = index.prepare_document_indexes(deepcopy([rows[0], rows[1], rows[3]]), owner.source_schema)
    assert sorted(actual.to_pylist(), key=identity) == sorted(pa.Table.from_pylist(expected, schema=actual.schema).to_pylist(), key=identity)
    actual_docs = pa.Table.from_batches(list(current.table('documents', max_ordered_bytes=1 << 20).iter_batches()))
    assert sorted(actual_docs.to_pylist(), key=lambda row: row['document_id']) == sorted(
        pa.Table.from_pylist(documents, schema=actual_docs.schema).to_pylist(), key=lambda row: row['document_id'])
    assert result['scope_reference'] == current.selection['scope']


def test_scope_cursor_reads_exact_old_new_sources_without_selected_corpus_scan(tmp_path):
    store, native = LocalStore(tmp_path / 'store'), Native()
    owner, rows = seed(tmp_path, store, native)
    previous = read_catalog(store, native=native)
    result = updates.update_native_catalog(store, native=native, previous=previous, dependencies=owner,
        deletions=[identity(rows[2])], candidate='cursor-split', directory=tmp_path / 'update',
        max_chunk_rows=64, max_chunk_bytes=1 << 20, rules=dict(grouping='maintained-v1'))
    current = read_catalog(LocalStore(store.root), native=native)
    native.reads.clear()
    changes = list(current.changes_since(previous.identity))
    assert len(changes) == 1 and not native.reads
    assert changes[0]['before'] == previous.identity and changes[0]['after'] == current.identity
    assert changes[0]['scope_reference'] == result['scope_reference']
    old = pa.Table.from_batches(list(current.changed_sources(changes[0], which='retired', max_ordered_bytes=1 << 20).iter_batches()))
    new = pa.Table.from_batches(list(current.changed_sources(changes[0], max_ordered_bytes=1 << 20).iter_batches()))
    assert {identity(row) for row in old.to_pylist()} == {identity(row) for row in rows[:3]}
    assert {identity(row) for row in new.to_pylist()} == {identity(row) for row in rows[:2]}
    assert list(current.changes_since(current.identity)) == []
    with pytest.raises(ValueError, match='not an ancestor'):
        list(current.changes_since(dict(selector_sha256='unknown', selected_ref=None)))


def test_scope_cursor_orders_multiple_changes_and_rejects_unrelated_identity(tmp_path):
    store, native = LocalStore(tmp_path / 'store'), Native()
    owner, rows = seed(tmp_path, store, native)
    first = read_catalog(store, native=native)
    options = dict(native=native, dependencies=owner, max_chunk_rows=64,
                   max_chunk_bytes=1 << 20, rules=dict(grouping='maintained-v1'))
    updates.update_native_catalog(store, previous=first, deletions=[identity(rows[2])],
        candidate='first-change', directory=tmp_path / 'first', **options)
    second = read_catalog(store, native=native)
    updates.update_native_catalog(store, previous=second, deletions=[identity(rows[3])],
        candidate='second-change', directory=tmp_path / 'second', **options)
    third = read_catalog(store, native=native)
    native.reads.clear()
    chain = list(third.changes_since(first.identity))
    assert [change['scope']['candidate'] for change in chain] == ['first-change', 'second-change']
    assert chain[0]['after'] == chain[1]['before'] == second.identity
    assert not native.reads
    with pytest.raises(ValueError, match='not an ancestor'):
        list(third.changes_since(dict(selector_sha256='other-file-basis', selected_ref=None)))
