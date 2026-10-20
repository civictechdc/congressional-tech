"""Interrupted catalog adoption reuses completed preparation without reselection."""
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.retention import catalog_adoption as adoption
from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.catalog_dependency_storage import CatalogDependencyStorage
from congress_api.retention.catalog_publication import MANIFEST_KEY, read_catalog
from test_catalog_adoption import existing
from test_catalog_coalesced_batches import Native


def setup_adoption(tmp_path, monkeypatch):
    store, native = LocalStore(tmp_path / 'store'), Native()
    existing(tmp_path, store)
    previous = read_catalog(store)
    with pq.ParquetFile(previous.filenames_path) as file:
        owner = CatalogDependencyStorage(native=native, store=store, namespace='adopt',
            source_schema=file.schema_arrow, max_rows=64, max_bytes=1 << 20)
    runtime = tmp_path / 'runtime.json'
    runtime.write_bytes(b'qualified-runtime')
    monkeypatch.setattr(native, 'execution_files', lambda: (runtime,), raising=False)
    options = dict(native=native, previous=previous, dependencies=owner,
        candidate='resume-adoption', directory=tmp_path / 'adopt',
        max_chunk_rows=1, max_chunk_bytes=1 << 20,
        rules=dict(interpretation='preserved-exact-values-v1'))
    return store, native, options, runtime


def interrupt_chunks(native, monkeypatch):
    original, completed = native.run_table, {}
    def interrupted(table, **request):
        if request['dataset'].startswith('catalog-filenames-'):
            if completed:
                raise OSError('worker lost midway through chunks')
            completed[request['dataset']] = table
        return original(table, **request)
    monkeypatch.setattr(native, 'run_table', interrupted)
    return original, completed


def test_mid_chunk_continuation_skips_dependencies_and_completed_native_chunks(tmp_path, monkeypatch):
    store, native, options, _ = setup_adoption(tmp_path, monkeypatch)
    original, completed = interrupt_chunks(native, monkeypatch)
    before = store.read(MANIFEST_KEY)
    with pytest.raises(OSError, match='worker lost'):
        adoption.adopt_native_catalog(store, **options)
    assert store.read(MANIFEST_KEY) == before
    assert not (options['directory'] / 'qualified-adoption.json').exists()
    def continued(table, **request):
        if request['dataset'] in completed or request['dataset'].startswith('catalog-dep-'):
            pytest.fail('Completed native preparation was submitted again')
        return original(table, **request)
    monkeypatch.setattr(native, 'run_table', continued)
    monkeypatch.setattr(options['dependencies'], 'adopt',
        lambda *a, **k: pytest.fail('Completed dependency import was repeated'))
    expected = {label: pq.read_table(getattr(options['previous'], label + '_path'))
                for label in ('filenames', 'documents')}
    # Reopening the old snapshot gives new owned paths and file-custody objects.
    with read_catalog(store) as previous:
        result = adoption.adopt_native_catalog(store, **{**options, 'previous': previous})
    with read_catalog(store, native=native) as selected:
        for label in expected:
            actual = pa.Table.from_batches(list(selected.table(label, max_ordered_bytes=1 << 20).iter_batches()))
            assert actual.equals(expected[label], check_metadata=True)
        assert selected.selection['adoption'] == result['adoption_reference']


@pytest.mark.parametrize('change', ['candidate', 'rules', 'chunk-budget', 'dependency-budget',
                                   'base', 'file', 'schema', 'runtime', 'requirements'])
def test_interrupted_adoption_refuses_changed_basis_before_native_work(tmp_path, monkeypatch, change):
    store, native, options, runtime = setup_adoption(tmp_path, monkeypatch)
    interrupt_chunks(native, monkeypatch)
    with pytest.raises(OSError, match='worker lost'):
        adoption.adopt_native_catalog(store, **options)
    before = store.read(MANIFEST_KEY)
    if change == 'candidate':
        options['candidate'] = 'another-operation'
    elif change == 'rules':
        options['rules'] = dict(interpretation='changed')
    elif change == 'chunk-budget':
        options['max_chunk_rows'] = 2
    elif change == 'dependency-budget':
        options['dependencies'].max_rows = 32
    elif change == 'base':
        options['previous'].identity = dict(selector_sha256='f' * 64, selected_ref=None)
    elif change == 'file':
        path = options['previous'].filenames_path
        table = pq.read_table(path)
        pq.write_table(table, path, compression='NONE')
    elif change == 'schema':
        options['dependencies'].source_schema = options['dependencies'].source_schema.with_metadata({b'catalog_id': b'changed'})
    elif change == 'runtime':
        runtime.write_bytes(b'changed-runtime')
    else:
        monkeypatch.setattr(adoption, 'adoption_requirements', lambda: dict(validator='changed'))
    monkeypatch.setattr(native, 'run_table', lambda *a, **k: pytest.fail('Native work preceded changed-basis refusal'))
    with pytest.raises(ValueError, match='continuation|custody|schema'):
        adoption.adopt_native_catalog(store, **options)
    assert store.read(MANIFEST_KEY) == before


def test_runtime_change_during_dependency_import_cannot_be_checkpointed_or_selected(tmp_path, monkeypatch):
    store, native, options, runtime = setup_adoption(tmp_path, monkeypatch)
    original = options['dependencies'].adopt
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        runtime.write_bytes(b'changed-runtime')
        return result
    monkeypatch.setattr(options['dependencies'], 'adopt', changed)
    before = store.read(MANIFEST_KEY)
    with pytest.raises(ValueError, match='custody changed'):
        adoption.adopt_native_catalog(store, **options)
    assert store.read(MANIFEST_KEY) == before
    assert not (options['directory'] / 'qualified-adoption.json').exists()


def test_corrupt_dependency_completion_refuses_before_native_work(tmp_path, monkeypatch):
    store, native, options, _ = setup_adoption(tmp_path, monkeypatch)
    interrupt_chunks(native, monkeypatch)
    with pytest.raises(OSError, match='worker lost'):
        adoption.adopt_native_catalog(store, **options)
    checkpoint = options['directory'] / 'preparation-request.json'
    saved = json.loads(checkpoint.read_bytes())
    saved['dependency']['next_source_order'] += 1
    checkpoint.write_text(json.dumps(saved))
    before = store.read(MANIFEST_KEY)
    monkeypatch.setattr(native, 'run_table', lambda *a, **k: pytest.fail('Corrupt completion was used'))
    with pytest.raises(ValueError, match='continuation'):
        adoption.adopt_native_catalog(store, **options)
    assert store.read(MANIFEST_KEY) == before


@pytest.mark.parametrize('change', ['none', 'runtime', 'file', 'workspace'])
def test_qualified_checkpoint_reuses_import_but_refuses_changed_runtime_or_input(tmp_path, monkeypatch, change):
    from congress_api.retention import catalog_selection
    store, native, options, runtime = setup_adoption(tmp_path, monkeypatch)
    publish = catalog_selection.publish_native_catalog
    monkeypatch.setattr(catalog_selection, 'publish_native_catalog',
        lambda *a, **k: (_ for _ in ()).throw(OSError('stopped before selection')))
    before = store.read(MANIFEST_KEY)
    with pytest.raises(OSError, match='before selection'):
        adoption.adopt_native_catalog(store, **options)
    assert store.read(MANIFEST_KEY) == before
    assert (options['directory'] / 'qualified-adoption.json').exists()
    monkeypatch.setattr(catalog_selection, 'publish_native_catalog', publish)
    monkeypatch.setattr(native, 'run_table', lambda *a, **k: pytest.fail('Qualified native import was repeated'))
    if change == 'runtime':
        runtime.write_bytes(b'changed-runtime')
    elif change == 'file':
        path = options['previous'].documents_path
        pq.write_table(pq.read_table(path), path, compression='NONE')
    elif change == 'workspace':
        monkeypatch.setattr(native, 'workspace', tmp_path / 'different-workspace', raising=False)
    if change != 'none':
        with pytest.raises(ValueError, match='continuation|custody'):
            adoption.adopt_native_catalog(store, **options)
        assert store.read(MANIFEST_KEY) == before
    else:
        result = adoption.adopt_native_catalog(store, **options)
        with read_catalog(store, native=native) as selected:
            assert selected.selection['adoption'] == result['adoption_reference']
            assert adoption.adopt_native_catalog(store, **{**options, 'previous': selected})['unchanged']


@pytest.mark.parametrize('change', ['runtime-file', 'runtime-path', 'input-file', 'hardlinked-input'])
def test_change_during_readback_cannot_select_or_save_qualified_proof(tmp_path, monkeypatch, change):
    store, native, options, runtime = setup_adoption(tmp_path, monkeypatch)
    retained = tmp_path / 'retained-documents.parquet'
    if change == 'hardlinked-input':
        from congress_api.retention.derived_files import retain_verified_file
        source = options['previous'].documents_path
        retain_verified_file(source, retained, expected=options['previous'].files['documents'], key='documents')
        assert retained.stat().st_ino == source.stat().st_ino
    readback = adoption.qualify_adoption_readback
    def changed(*args, **kwargs):
        result = readback(*args, **kwargs)
        if change == 'runtime-file':
            runtime.write_bytes(b'changed-runtime')
        elif change == 'runtime-path':
            monkeypatch.setattr(native, 'execution_files', lambda: (), raising=False)
        else:
            path = retained if change == 'hardlinked-input' else options['previous'].documents_path
            pq.write_table(pq.read_table(path), path, compression='NONE')
        return result
    monkeypatch.setattr(adoption, 'qualify_adoption_readback', changed)
    before = store.read(MANIFEST_KEY)
    with pytest.raises(ValueError, match='continuation|custody'):
        adoption.adopt_native_catalog(store, **options)
    assert store.read(MANIFEST_KEY) == before
    assert not (options['directory'] / 'qualified-adoption.json').exists()
