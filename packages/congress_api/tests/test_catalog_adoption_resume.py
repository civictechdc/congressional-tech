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
from testing_fakes import Native


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
    publish = adoption.publish_native_catalog
    monkeypatch.setattr(adoption, 'publish_native_catalog',
        lambda *a, **k: (_ for _ in ()).throw(OSError('stopped before selection')))
    before = store.read(MANIFEST_KEY)
    with pytest.raises(OSError, match='before selection'):
        adoption.adopt_native_catalog(store, **options)
    assert store.read(MANIFEST_KEY) == before
    assert (options['directory'] / 'qualified-adoption.json').exists()
    monkeypatch.setattr(adoption, 'publish_native_catalog', publish)
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


def test_dependency_interruption_reuses_typed_preparation_with_fresh_owner(tmp_path, monkeypatch):
    store,native,options,_=setup_adoption(tmp_path,monkeypatch)
    original=native.run_table
    writes=[]
    def interrupted(table,**request):
        if request['dataset'].startswith('catalog-dep-'):
            if writes:
                raise OSError('dependency worker stopped')
            writes.append(request['dataset'])
        return original(table,**request)
    monkeypatch.setattr(native,'run_table',interrupted)
    before=store.read(MANIFEST_KEY)
    with pytest.raises(OSError,match='dependency worker stopped'):
        adoption.adopt_native_catalog(store,**options)
    cache=options['directory']/'dependency-preparation'
    assert (cache/'complete.json').exists()
    assert store.read(MANIFEST_KEY)==before
    expected={label:pq.read_table(getattr(options['previous'],label+'_path')) for label in ('filenames','documents')}
    # A fresh process reconstructs disposable key indexes from checked Parquet,
    # then asks the native owner to recover deterministic completed Runs.
    old_owner=options['dependencies']
    options['dependencies']=CatalogDependencyStorage(native=native,store=store,namespace=old_owner.namespace,
        source_schema=old_owner.source_schema,max_rows=old_owner.max_rows,max_bytes=old_owner.max_bytes)
    old_ordered=adoption.ordered_chunks
    def no_dependency_inputs(*args,**kwargs):
        if 'start_row' in kwargs:
            pytest.fail('Completed dependency preparation reread selected source payloads')
        return old_ordered(*args,**kwargs)
    monkeypatch.setattr(adoption,'ordered_chunks',no_dependency_inputs)
    monkeypatch.setattr(native,'run_table',original)
    adoption.adopt_native_catalog(store,**options)
    with read_catalog(store,native=native) as selected:
        for label,table in expected.items():
            actual=pa.Table.from_batches(list(selected.table(label,max_ordered_bytes=1<<20).iter_batches()))
            assert actual.equals(table,check_metadata=True)
            assert actual.select(['source_id','document_id'] if label=='filenames' else ['document_id']).equals(
                table.select(['source_id','document_id'] if label=='filenames' else ['document_id']),check_metadata=True)


def test_ordered_chunks_resume_skips_completed_row_groups_and_preserves_orders(tmp_path):
    table=pa.table({'source_id':['a','b','c','d','e'],'filename':['a','b','c','d','e']})
    path=tmp_path/'source.parquet';pq.write_table(table,path,row_group_size=2)
    class TracedFile:
        def __init__(self,file):self.file=file;self.groups=[]
        def __getattr__(self,name):return getattr(self.file,name)
        def iter_batches(self,**options):
            self.groups.extend(options['row_groups'])
            return self.file.iter_batches(**options)
    with pq.ParquetFile(path) as file:
        traced=TracedFile(file)
        actual=pa.concat_tables(list(adoption.ordered_chunks(traced,max_rows=2,max_bytes=1<<20,start_row=3)))
    assert traced.groups==[1,2]
    assert actual['_catalog_order'].to_pylist()==[3,4]
    assert actual.drop(['_catalog_order']).equals(table.slice(3),check_metadata=True)


def test_capacity_refusal_precedes_preparation_and_native_work(tmp_path, monkeypatch):
    from congress_api.retention import native_capacity
    store, native, options, _ = setup_adoption(tmp_path, monkeypatch)
    native.workspace = tmp_path / 'native'
    monkeypatch.setattr(native_capacity, '_filesystem', lambda path: (1, str(path), 1))
    monkeypatch.setattr(adoption, 'ordered_chunks',
                        lambda *a, **k: pytest.fail('Insufficient capacity decoded source rows'))
    monkeypatch.setattr(native, 'run_table',
                        lambda *a, **k: pytest.fail('Insufficient capacity reached native work'))
    before = store.read(MANIFEST_KEY)
    with pytest.raises(native_capacity.AdoptionCapacityError) as caught:
        adoption.adopt_native_catalog(store, **options)
    assert caught.value.receipt['native_scratch_bytes'] == 32 << 30
    assert caught.value.receipt['staging_budget_bytes'] > 0
    assert not options['directory'].exists()
    assert store.read(MANIFEST_KEY) == before


def test_capacity_budget_is_enforced_and_progress_retains_admission(tmp_path, monkeypatch):
    from congress_api.retention import native_capacity
    store, native, options, _ = setup_adoption(tmp_path, monkeypatch)
    native.workspace = tmp_path / 'native'
    monkeypatch.setattr(native_capacity, '_filesystem',
                        lambda path: (1, str(path), 100 << 30))
    events = []
    options['on_progress'] = events.append
    adopt = options['dependencies'].adopt
    budgets = []
    def prepared(*args, **kwargs):
        budgets.append(kwargs.get('staging_byte_budget'))
        return adopt(*args, **kwargs)
    monkeypatch.setattr(options['dependencies'], 'adopt', prepared)
    result = adoption.adopt_native_catalog(store, **options)
    assert budgets and budgets[0] > 0
    admission = json.loads((options['directory'] / 'capacity.json').read_bytes())
    assert admission['staging_budget_bytes'] == budgets[0]
    assert events[0] == dict(phase='capacity-admitted', **admission)
    assert result['scope_reference']


def test_completed_adoption_does_not_require_new_preparation_capacity(tmp_path, monkeypatch):
    from congress_api.retention import native_capacity
    store, native, options, _ = setup_adoption(tmp_path, monkeypatch)
    native.workspace = tmp_path / 'native'
    monkeypatch.setattr(native_capacity, '_filesystem',
                        lambda path: (1, str(path), 100 << 30))
    adoption.adopt_native_catalog(store, **options)
    monkeypatch.setattr(native_capacity, '_filesystem',
                        lambda path: pytest.fail('Completed adoption requested fresh capacity'))
    with read_catalog(store, native=native) as selected:
        assert adoption.adopt_native_catalog(
            store, **{**options, 'previous': selected})['unchanged']


def test_lost_headroom_stops_at_preparation_boundary_and_keeps_completed_files(tmp_path, monkeypatch):
    from congress_api.retention import native_capacity
    store, native, options, _ = setup_adoption(tmp_path, monkeypatch)
    native.workspace = tmp_path / 'native'
    free = [100 << 30]
    monkeypatch.setattr(native_capacity, '_filesystem',
                        lambda path: (1, str(path), free[0]))
    def progress(event):
        if event['phase'] == 'prepared':
            free[0] = 1
    options['on_progress'] = progress
    before = store.read(MANIFEST_KEY)
    with pytest.raises(native_capacity.AdoptionCapacityError):
        adoption.adopt_native_catalog(store, **options)
    assert list((options['directory'] / 'dependency-preparation').glob('part-*.parquet'))
    assert not native.tables
    assert store.read(MANIFEST_KEY) == before
