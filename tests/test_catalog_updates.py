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
            pytest.fail('A completed native chunk was submitted again')
        return original(table, **request)
    monkeypatch.setattr(native, 'run_table', replay)
    assert updates.update_native_catalog(store, **arguments)['counts'] == dict(source_rows=3, document_rows=3)
    assert all(native.tables[key].equals(table, check_metadata=True) for key, table in completed.items())


@pytest.mark.parametrize('damage', ['changed-input', 'corrupt-chunk'])
def test_interrupted_native_preparation_refuses_changed_or_corrupt_resume(tmp_path, monkeypatch, damage):
    import json
    store, native = LocalStore(tmp_path / 'store'), Native()
    owner, rows = seed(tmp_path, store, native)
    previous = read_catalog(store, native=native)
    original, calls = native.run_table, []
    def interrupted(table, **request):
        if request['dataset'].startswith('catalog-filenames-'):
            calls.append(request['dataset'])
            if len(calls) == 2:
                raise OSError('interrupted')
        return original(table, **request)
    monkeypatch.setattr(native, 'run_table', interrupted)
    arguments = dict(native=native, previous=previous, dependencies=owner,
        deletions=[identity(rows[2])], candidate='bound-resume', directory=tmp_path / 'update',
        max_chunk_rows=1, max_chunk_bytes=1 << 20, rules=dict(grouping='maintained-v1'))
    selector = store.read(MANIFEST_KEY)
    with pytest.raises(OSError, match='interrupted'):
        updates.update_native_catalog(store, **arguments)
    if damage == 'changed-input':
        arguments['deletions'] = [identity(rows[3])]
        message = 'continuation inputs'
    else:
        checkpoint, = (tmp_path / 'update' / 'prepared-chunks').glob('*.json')
        saved = json.loads(checkpoint.read_bytes())
        saved['release']['dataset']['dataset'] = 'unrelated'
        checkpoint.write_text(json.dumps(saved))
        message = 'chunk differs'
    with pytest.raises(ValueError, match=message):
        updates.update_native_catalog(store, **arguments)
    assert store.read(MANIFEST_KEY) == selector


def test_runtime_change_during_first_preparation_cannot_select_catalog(tmp_path, monkeypatch):
    store, native = LocalStore(tmp_path / 'store'), Native()
    owner, rows = seed(tmp_path, store, native)
    previous = read_catalog(store, native=native)
    runtime = tmp_path / 'runtime'
    runtime.write_bytes(b'qualified-runtime')
    monkeypatch.setattr(native, 'execution_files', lambda: (runtime,), raising=False)
    original = native.run_table
    def changed(table, **request):
        runtime.write_bytes(b'changed-runtime')
        return original(table, **request)
    monkeypatch.setattr(native, 'run_table', changed)
    selector = store.read(MANIFEST_KEY)
    with pytest.raises(ValueError, match='custody changed'):
        updates.update_native_catalog(store, native=native, previous=previous, dependencies=owner,
            deletions=[identity(rows[2])], candidate='changed-runtime', directory=tmp_path / 'update',
            max_chunk_rows=64, max_chunk_bytes=1 << 20, rules=dict(grouping='maintained-v1'))
    assert store.read(MANIFEST_KEY) == selector


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


def test_explicit_known_empty_catalog_identity_seeds_initial_scope_without_full_scan(tmp_path):
    from copy import deepcopy
    from congress_api.retention import document_index as index
    from congress_api.retention.catalog_dependency_storage import CatalogDependencyStorage
    from test_catalog_dependencies import source
    store, native = LocalStore(tmp_path / 'store'), Native()
    empty = read_catalog(store)
    rows, schema, _, _ = index.prepare_document_indexes([source('first.pdf', 'A')],
        pa.schema([*index.SOURCE_SCHEMA, ('capture_outcome', index.STRINGS)]))
    owner = CatalogDependencyStorage(native=native, store=store, namespace='known-empty',
                                     source_schema=schema, max_rows=64, max_bytes=1 << 20)
    assert empty.identity == dict(selector_sha256=None, selected_ref=None)
    updates.update_native_catalog(store, native=native, previous=empty, dependencies=owner,
        replacements=rows, candidate='first', directory=tmp_path / 'first',
        max_chunk_rows=64, max_chunk_bytes=1 << 20, rules=dict(grouping='maintained-v1'))
    current = read_catalog(store, native=native)
    native.reads.clear()
    change, = current.changes_since(empty.identity)
    assert not native.reads
    assert change['scope']['counts']['prepared_source_rows'] == 1
    assert change['scope']['dependency_before'] is None
    with pytest.raises(ValueError, match='not an ancestor'):
        list(current.changes_since(None))


def test_folded_source_changes_exclude_created_then_removed_components(tmp_path):
    from test_catalog_dependencies import source
    store, native = LocalStore(tmp_path / 'store'), Native()
    owner, rows = seed(tmp_path, store, native)
    old = read_catalog(store, native=native)
    added = source('temporary.pdf', 'temporary')
    # Supply all declared fields as complete source values, including nulls.
    added = pa.Table.from_pylist([added], schema=owner.source_schema).to_pylist()[0]
    options = dict(native=native, dependencies=owner, max_chunk_rows=64,
                   max_chunk_bytes=1 << 20, rules=dict(grouping='maintained-v1'))
    updates.update_native_catalog(store, previous=old, replacements=[added], candidate='add-temporary',
        directory=tmp_path / 'add', **options)
    middle = read_catalog(store, native=native)
    updates.update_native_catalog(store, previous=middle, deletions=[identity(added)], candidate='remove-temporary',
        directory=tmp_path / 'remove', **options)
    current = read_catalog(store, native=native)
    native.reads.clear()
    changed = current.changed_sources_since(old.identity, max_ordered_bytes=1 << 20)
    assert changed.rows == 0 and list(changed.iter_batches()) == []
    assert not native.reads


@pytest.mark.parametrize('actual_native', [False, True])
def test_fresh_dependency_owner_restores_exact_selected_lookup_schema(tmp_path, actual_native, native):
    from congress_api.retention.catalog_dependency_storage import CatalogDependencyStorage
    selected_native = native if actual_native else Native()
    store = LocalStore(tmp_path / 'store')
    owner, rows = seed(tmp_path, store, selected_native)
    snapshot = read_catalog(store, native=selected_native)
    # Arrow may compare equal while emitting different serialized bytes after
    # a Parquet/grouping round trip. Restore the exact saved lookup schema.
    restored = CatalogDependencyStorage.for_snapshot(snapshot)
    assert restored.schema_hash == owner.schema_hash
    assert {row['source_id'] for row in restored.sources_at_url(
        snapshot.selection['dependency'], rows[0]['source_url'])} == {identity(rows[0]), identity(rows[2])}


def test_completion_receipt_binds_affected_body_coverage_before_selection(tmp_path):
    from hashlib import sha256
    from congress_api.retention.immutable_metadata import encoded
    from congress_api.retention.catalog_scope import read_catalog_scope
    store, native = LocalStore(tmp_path / 'store'), Native()
    owner, rows = seed(tmp_path, store, native)
    previous = read_catalog(store, native=native)
    options = dict(native=native, previous=previous, dependencies=owner,
        deletions=[identity(rows[2])], candidate='covered', directory=tmp_path / 'update',
        max_chunk_rows=64, max_chunk_bytes=1 << 20, rules=dict(grouping='maintained-v1'))
    selector = store.read(MANIFEST_KEY)
    with pytest.raises(ValueError, match='expected retained body'):
        updates.update_native_catalog(store, expected_bodies=['missing-body'], **options)
    assert store.read(MANIFEST_KEY) == selector
    result = updates.update_native_catalog(store, expected_bodies=['A', 'B'], **options)
    selected = read_catalog(store, native=native)
    assert result['selected_identity'] == selected.identity
    assert result['body_coverage'] == read_catalog_scope(store, result['scope_reference'])['body_coverage']
    assert result['body_coverage']['expected_count'] == 2
    assert result['body_coverage']['expected_sha256'] == sha256(encoded(['A', 'B'])).hexdigest()


def test_unchanged_expected_body_coverage_reads_only_body_lookup_and_never_writes(tmp_path):
    store, native = LocalStore(tmp_path / 'store'), Native()
    owner, rows = seed(tmp_path, store, native)
    previous = read_catalog(store, native=native)
    before = {p: p.read_bytes() for p in store.root.rglob('*') if p.is_file()}
    native.reads.clear()
    result = updates.update_native_catalog(store, native=native, previous=previous, dependencies=owner,
        expected_bodies=['A'], candidate='already-selected', directory=tmp_path / 'unused',
        max_chunk_rows=64, max_chunk_bytes=1 << 20, rules=dict(grouping='maintained-v1'))
    assert result['unchanged'] and result['selected_identity'] == previous.identity
    assert result['body_coverage']['expected_count'] == 1
    assert all(not key.startswith(('catalog-filenames-', 'catalog-documents-')) for key in native.reads)
    assert {p: p.read_bytes() for p in store.root.rglob('*') if p.is_file()} == before
    with pytest.raises(ValueError, match='expected retained body'):
        updates.update_native_catalog(store, native=native, previous=previous, dependencies=owner,
            expected_bodies=['missing'], candidate='missing', directory=tmp_path / 'unused',
            max_chunk_rows=64, max_chunk_bytes=1 << 20, rules=dict(grouping='maintained-v1'))
