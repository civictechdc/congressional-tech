"""Typed adoption staging preserves values and resumes checked preparation."""
import json

import pyarrow as pa
import pytest

from congress_api.retention import document_index as index
from congress_api.retention import catalog_dependency_storage as storage
from congress_api.retention.catalog_dependencies import dependency_tables
from test_catalog_dependency_storage import MemoryNative
from test_raw_source_sync import MemoryStore


OCC = pa.list_(pa.struct([('labels', pa.list_(pa.string())), ('bytes', pa.binary())]))
SCHEMA = pa.schema([
    ('source_id', pa.string()), ('document_id', pa.string()), ('filename', pa.string()),
    ('source_url', pa.string()), ('body_key', pa.string()),
    ('media_type', pa.list_(pa.string())), ('http_status', pa.list_(pa.string())),
    ('capture_outcome', pa.list_(pa.string())), ('source_resolved_url', pa.list_(pa.string())),
    pa.field('evidence', pa.struct([pa.field('maximum', pa.uint64()), pa.field('bytes', pa.binary())]),
             metadata={b'reading': b'original'}),
    ('source_occurrences', OCC),
], metadata={b'catalog_id': b'preserve-every-value'})


def values():
    rows=[]
    repeated=dict(labels=['é', 'é', None], bytes=b'\0\xff' * 1024)
    for i, occurrences in enumerate([None, [], [None, dict(labels=None, bytes=None), repeated, repeated],
                                     [repeated] * 2400, [repeated] * 2500, [repeated]]):
        row=dict(filename=f'{i}.pdf', source_url=f'https://example.gov/{i}.pdf', body_key=f'body-{i//2}',
            document_id=f'doc-{i//2}', media_type=['application/pdf'], http_status=['200'],
            capture_outcome=['saved'], source_resolved_url=[None, 'https://example.gov/resolved.pdf'],
            evidence=dict(maximum=2**64-1, bytes=b'\0\xff'), source_occurrences=occurrences)
        row['source_id']=index.source_identity(row)
        rows.append(row)
    return pa.Table.from_pylist(rows, schema=SCHEMA)


def owner(native=None, store=None, *, rows=4, size=1<<20):
    return storage.CatalogDependencyStorage(native=native or MemoryNative(), store=store or MemoryStore(),
        namespace='typed-prepare', source_schema=SCHEMA, max_rows=rows, max_bytes=size)


def assert_exact(selected_owner, selection, expected, orders):
    selected=selected_owner.selected(selection)
    try:
        for row in expected.to_pylist():
            key=row['source_id']
            assert selected.source(key) == row
            assert selected.order(key) == orders[key]
            assert ('component', row['document_id']) in selected.aliases(key)
            assert key in selected.members(('component', row['document_id']))
            assert key in {item['source_id'] for item in selected_owner.sources_at_url(selection, row['source_url'])}
            assert key in {item['source_id'] for item in selected_owner.originals_targeting(selection, None)}
    finally:
        selected.close()


def test_adoption_keeps_typed_payloads_and_exact_large_occurrences(monkeypatch):
    table=values(); native=MemoryNative(); prepared=owner(native)
    orders={key:position*3 for position,key in enumerate(table['source_id'].to_pylist())}
    def no_pickle(*args, **kwargs):
        pytest.fail('Adoption serialized source payloads through pickle')
    with monkeypatch.context() as patch:
        patch.setattr(storage.pickle, 'dumps', no_pickle)
        selection=prepared.adopt([table], source_orders=orders, first_unused_order=40)
    assert selection['next_source_order']==40
    assert_exact(prepared, selection, table, orders)
    assert all(len(part)<=4 and part.nbytes<=1<<20 for part in native.tables.values())
    assert any('-occ-' in name for name in native.tables)


def test_typed_dependency_tables_equal_existing_full_values():
    table=values()
    expected=dependency_tables(table.to_pylist(), SCHEMA, first_order=7)
    actual=dependency_tables(table, SCHEMA, first_order=7)
    assert all(left.equals(right, check_metadata=True) for left,right in zip(expected,actual))
    original=table['source_occurrences'].chunk(0)
    prepared=actual[0]['source_values'].chunk(0).field('source_occurrences')
    assert [buffer.address if buffer else None for buffer in prepared.buffers()]==[
        buffer.address if buffer else None for buffer in original.buffers()]


def test_interrupted_typed_chunks_resume_without_reading_completed_input(tmp_path):
    table=values(); native=MemoryNative(); store=MemoryStore(); prepared=owner(native,store)
    directory=tmp_path/'preparation'
    def interrupted(start):
        assert start==0
        yield table.slice(0,2)
        raise OSError('lost input worker')
    with pytest.raises(OSError,match='lost input worker'):
        prepared.adopt(interrupted, checkpoint_directory=directory, preparation_key='exact-input-receipt')
    receipts=list(directory.glob('part-*.json'))
    assert receipts
    starts=[]
    def continued(start):
        starts.append(start)
        yield table.slice(start)
    selection=owner(native,store).adopt(continued, checkpoint_directory=directory, preparation_key='exact-input-receipt')
    assert starts==[2]
    assert_exact(prepared,selection,table,{key:i for i,key in enumerate(table['source_id'].to_pylist())})
    def no_inputs(start):
        pytest.fail('Completed typed preparation reread selected inputs')
    writes=len(native.writes)
    assert owner(native,store).adopt(no_inputs,checkpoint_directory=directory,preparation_key='exact-input-receipt')==selection
    assert len(native.writes)==writes


@pytest.mark.parametrize('damage',['input','schema','budget','part-bytes','receipt'])
def test_checked_preparation_refuses_changed_basis_or_cached_values(tmp_path,damage):
    table=values().slice(0,2); native=MemoryNative();store=MemoryStore();prepared=owner(native,store)
    directory=tmp_path/'preparation'
    prepared.adopt([table],checkpoint_directory=directory,preparation_key='exact-input-receipt')
    options=dict(checkpoint_directory=directory,preparation_key='exact-input-receipt')
    if damage=='input':options['preparation_key']='changed-input-receipt'
    elif damage=='schema':prepared.source_schema=SCHEMA.with_metadata({b'changed':b'yes'})
    elif damage=='budget':prepared.max_rows=3
    elif damage=='part-bytes':
        path=next(directory.glob('part-*.parquet'));path.write_bytes(path.read_bytes()+b'changed')
    else:
        path=next(directory.glob('part-*.json'));saved=json.loads(path.read_bytes());saved['rows']+=1
        path.write_text(json.dumps(saved))
    before=len(native.calls)
    with pytest.raises(ValueError,match='preparation|checksum|schema'):
        prepared.adopt([],**options)
    assert len(native.calls)==before


def test_duplicate_sources_and_ordinals_across_typed_chunks_refuse_before_native():
    table=values().slice(0,2);prepared=owner()
    with pytest.raises(ValueError,match='Repeated selected source'):
        prepared.adopt([table.slice(0,1),table.slice(0,1)])
    assert not prepared.native.calls
    with pytest.raises(ValueError,match='Repeated selected source'):
        prepared.adopt([table.slice(0,1),table.slice(1,1)],source_orders={key:0 for key in table['source_id'].to_pylist()})
    assert not prepared.native.calls


def test_preparation_enforces_aggregate_disk_budget_before_native(tmp_path):
    prepared=owner()
    with pytest.raises(OSError,match='preparation.*budget'):
        prepared.adopt([values()],checkpoint_directory=tmp_path/'stage',preparation_key='input',staging_byte_budget=2048)
    assert not prepared.native.calls


def test_native_acknowledgment_loss_replays_through_native_owner(tmp_path):
    table=values();native=MemoryNative();store=MemoryStore();prepared=owner(native,store)
    original=native.run_table
    completed=[]
    def lost_ack(table,**request):
        result=original(table,**request)
        completed.append(request['dataset'])
        raise OSError('native completed but acknowledgment lost')
    native.run_table=lost_ack
    directory=tmp_path/'stage'
    with pytest.raises(OSError,match='acknowledgment lost'):
        prepared.adopt([table],checkpoint_directory=directory,preparation_key='exact-input')
    assert (directory/'complete.json').exists()
    before=len(native.writes)
    native.run_table=original
    def no_inputs(start):
        pytest.fail('Completed typed staging reread its original inputs')
    selection=owner(native,store).adopt(no_inputs,checkpoint_directory=directory,preparation_key='exact-input')
    assert native.calls.count(completed[0])==2
    assert native.writes.count(completed[0])==1
    assert len(native.writes)>before
    assert_exact(prepared,selection,table,{key:i for i,key in enumerate(table['source_id'].to_pylist())})


def test_actual_native_typed_dependency_adoption_keeps_giant_and_null_values(tmp_path,native):
    from congress_api.retention.catalog_cache import LocalStore
    table=values()
    prepared=owner(native,LocalStore(tmp_path/'store'),rows=128)
    selection=prepared.adopt([table],checkpoint_directory=tmp_path/'typed',preparation_key='native-exact-fixture')
    fresh=owner(native,LocalStore(tmp_path/'store'),rows=128)
    assert_exact(fresh,selection,table,{key:i for i,key in enumerate(table['source_id'].to_pylist())})


from test_docspec_boundary import native


def test_process_loss_reuses_fsynced_typed_parts_and_counts_abandoned_indexes(tmp_path):
    import subprocess
    import sys
    script='''
import os
import sys
from pathlib import Path
from test_catalog_dependency_preparation import values,owner,assert_exact
from test_catalog_dependency_storage import MemoryNative
from test_raw_source_sync import MemoryStore
root=Path(sys.argv[1]); phase=sys.argv[2]
table=values(); prepared=owner(MemoryNative(),MemoryStore())
if phase=='crash':
    def progress(value):
        if value['phase']=='prepared' and value['rows']>=4:
            os._exit(17)
    prepared.adopt([table],checkpoint_directory=root,preparation_key='process-loss-input',on_progress=progress)
    raise AssertionError('Expected process loss')
restored=[]
def chunks(start):
    assert start==4
    yield table.slice(start)
selection=prepared.adopt(chunks,checkpoint_directory=root,preparation_key='process-loss-input',
    on_progress=lambda value:restored.append(value['rows']) if value['phase']=='restored' else None)
assert max(restored)==4
assert_exact(prepared,selection,table,{key:i for i,key in enumerate(table['source_id'].to_pylist())})
assert prepared.preparation_metrics['retained_bytes']>=sum(p.stat().st_size for p in root.rglob('keys.sqlite'))
'''
    directory=tmp_path/'killed-process'
    before=subprocess.run([sys.executable,'-c',script,str(directory),'crash'],capture_output=True,text=True)
    assert before.returncode==17,before.stderr
    assert list(directory.glob('part-*.json'))
    assert list(directory.rglob('keys.sqlite'))
    after=subprocess.run([sys.executable,'-c',script,str(directory),'resume'],capture_output=True,text=True)
    assert after.returncode==0,after.stderr


def test_typed_adoption_preserves_original_hash_partitions_and_source_order():
    from congress_api.retention.catalog_rows import fits_chunk
    from congress_api.retention.partition_routing import key_hash
    from congress_api.retention.catalog_dependencies import dependency_schema
    table=values();prepared=owner();expected={}
    originals=dependency_tables(table.to_pylist(),SCHEMA)[0].to_pylist()
    def leaves(prefix):
        rows=sorted([row for row in originals if key_hash(row['source_id']).startswith(prefix)],
                    key=lambda row:row['source_id'])[:prepared.max_rows+1]
        part=pa.Table.from_pylist(rows,schema=dependency_schema(SCHEMA))
        if fits_chunk(part,max_rows=prepared.max_rows,max_bytes=prepared.max_bytes):
            if rows:expected[prefix]=part
        else:
            for char in '0123456789abcdef':leaves(prefix+char)
    leaves('')
    events=[]
    selection=prepared.adopt([table],on_progress=events.append)
    actual={prefix:prepared.read_source_leaf(selection,pin)
            for prefix,pin in prepared.sources.leaf_items(selection['source_root'])}
    assert actual.keys()==expected.keys()
    assert all(actual[prefix].equals(part,check_metadata=True) for prefix,part in expected.items())
    assert any(event['phase']=='native-source-leaf' for event in events)
    assert any(event['phase']=='prepared' for event in events)


def test_sequential_preparation_decodes_each_ordinary_row_once_at_growing_scope(tmp_path):
    measurements=[]
    for count in (256,2048):
        rows=[]
        for i in range(count):
            row=dict(filename=f'{i}.pdf',source_url=f'https://example.gov/{i}',body_key=f'body-{i}',
                media_type=['application/pdf'],http_status=['200'],source_occurrences=[dict(labels=['x'*64],bytes=None)]*3)
            row['source_id']=index.source_identity(row)
            rows.append(row)
        table=pa.Table.from_pylist(rows,schema=SCHEMA)
        prepared=owner(rows=32)
        selection=prepared.adopt([table],checkpoint_directory=tmp_path/str(count),preparation_key=f'rows-{count}')
        assert selection['next_source_order']==count
        reads=prepared.preparation_reads
        assert reads['decoded_rows']==count
        assert reads['sort_input_rows']==count
        assert reads['files']==1
        assert reads['selected_rows']==count
        measurements.append(reads)
    assert measurements[1]['files']==measurements[0]['files']


def test_giant_singletons_bypass_sorter_and_sorted_cache_reuses_completed_work(tmp_path,monkeypatch):
    import duckdb
    table=values();native=MemoryNative();store=MemoryStore();prepared=owner(native,store)
    directory=tmp_path/'checked'
    selection=prepared.adopt([table],checkpoint_directory=directory,preparation_key='same-input')
    assert prepared.preparation_reads['sort_input_rows']==4
    assert prepared.preparation_reads['decoded_rows']==len(table)
    assert prepared.preparation_reads['files']==3  # One ordinary stream and two exact giant files.
    assert (directory/'ordered.json').exists()
    monkeypatch.setattr(duckdb,'connect',lambda *a,**k:pytest.fail('Completed ordered input cache was sorted again'))
    fresh=owner(native,store)
    assert fresh.adopt([],checkpoint_directory=directory,preparation_key='same-input')==selection
    assert fresh.preparation_reads['sort_runs']==0
    assert_exact(fresh,selection,table,{key:i for i,key in enumerate(table['source_id'].to_pylist())})


def test_sort_failure_preserves_complete_source_cache_and_original_selection(tmp_path,monkeypatch):
    import duckdb
    from congress_api.retention.derived_files import file_identity
    directory=tmp_path/'sort-failure';table=values();prepared=owner()
    original=duckdb.connect
    monkeypatch.setattr(duckdb,'connect',lambda *a,**k:(_ for _ in ()).throw(OSError('sort worker lost')))
    with pytest.raises(OSError,match='sort worker lost'):
        prepared.adopt([table],checkpoint_directory=directory,preparation_key='stable')
    assert (directory/'complete.json').exists()
    preserved={path.name:dict(file_identity(path)) for path in directory.glob('part-*.parquet')}
    monkeypatch.setattr(duckdb,'connect',original)
    def no_source_inputs(start):pytest.fail('Sort retry rebuilt completed source preparation')
    prepared.adopt(no_source_inputs,checkpoint_directory=directory,preparation_key='stable')
    assert preserved=={path.name:dict(file_identity(path)) for path in directory.glob('part-*.parquet')}


def test_ordered_cache_corruption_refuses_before_native_work(tmp_path):
    prepared=owner();table=values();directory=tmp_path/'checked'
    prepared.adopt([table],checkpoint_directory=directory,preparation_key='input')
    path=directory/'ordered.parquet';path.write_bytes(path.read_bytes()+b'changed')
    before=len(prepared.native.calls)
    with pytest.raises(ValueError,match='checksum'):
        prepared.adopt([],checkpoint_directory=directory,preparation_key='input')
    assert len(prepared.native.calls)==before


def test_dependency_key_projection_keeps_unused_wide_evidence_in_arrow():
    from congress_api.retention.catalog_dependencies import dependency_key_fields
    fields=dependency_key_fields(SCHEMA)
    assert 'evidence' not in fields
    assert 'source_occurrences' not in fields
    assert {'source_id','document_id','source_url','body_key','filename','http_status','media_type'}<=set(fields)


def test_ordering_preserves_qualified_scalar_types_and_null_structs(tmp_path):
    table=values().slice(0,3)
    evidence=pa.struct([('signed',pa.int64()),('unsigned',pa.uint64()),('small',pa.int8()),('flag',pa.bool_())])
    table=table.append_column('scalar_evidence',pa.array([
        dict(signed=-(2**63),unsigned=2**64-1,small=-128,flag=True),
        None,dict(signed=2**63-1,unsigned=0,small=127,flag=False)],type=evidence))
    prepared=storage.CatalogDependencyStorage(native=MemoryNative(),store=MemoryStore(),
        namespace='qualified-types',source_schema=table.schema,max_rows=2,max_bytes=1<<20)
    selection=prepared.adopt([table],checkpoint_directory=tmp_path/'qualified',preparation_key='typed')
    assert_exact(prepared,selection,table,{key:i for i,key in enumerate(table['source_id'].to_pylist())})


@pytest.mark.parametrize('kind',[pa.timestamp('ns',tz='UTC'),pa.null()])
def test_unqualified_nested_sort_type_refuses_with_completed_inputs_preserved(tmp_path,kind):
    from hashlib import sha256
    table=values().slice(0,2).append_column('unqualified',pa.array(
        [dict(when=None),dict(when=None)],type=pa.struct([('when',kind)])))
    prepared=storage.CatalogDependencyStorage(native=MemoryNative(),store=MemoryStore(),
        namespace='refused-type',source_schema=table.schema,max_rows=2,max_bytes=1<<20)
    directory=tmp_path/'unqualified'
    with pytest.raises(ValueError,match='Unqualified.*unqualified.when') as refused:
        prepared.adopt([table],checkpoint_directory=directory,preparation_key='typed')
    assert str(kind) in str(refused.value)
    assert not prepared.native.calls
    assert (directory/'complete.json').exists()
    before={path.name:sha256(path.read_bytes()).hexdigest() for path in directory.glob('part-*.parquet')}
    assert before
    assert not (directory/'ordered.parquet').exists()
    with pytest.raises(ValueError,match='Unqualified.*sort type'):
        prepared.adopt([],checkpoint_directory=directory,preparation_key='typed')
    assert before=={path.name:sha256(path.read_bytes()).hexdigest() for path in directory.glob('part-*.parquet')}


def test_managed_sort_memory_refusal_keeps_inputs_for_retry(tmp_path,monkeypatch):
    import duckdb
    from hashlib import sha256
    from congress_api.retention import catalog_dependency_preparation as preparation
    table=values().slice(0,3);prepared=owner();directory=tmp_path/'managed-refusal'
    with monkeypatch.context() as patch:
        patch.setattr(preparation,'SORT_MEMORY_BYTES',1)
        with pytest.raises(duckdb.OutOfMemoryException):
            prepared.adopt([table],checkpoint_directory=directory,preparation_key='same-input')
    assert not prepared.native.calls
    assert (directory/'complete.json').exists()
    preserved={path.name:sha256(path.read_bytes()).hexdigest() for path in directory.glob('part-*.parquet')}
    def no_inputs(start):pytest.fail('Memory-refusal retry enumerated completed sources')
    selection=prepared.adopt(no_inputs,checkpoint_directory=directory,preparation_key='same-input')
    assert preserved=={path.name:sha256(path.read_bytes()).hexdigest() for path in directory.glob('part-*.parquet')}
    assert_exact(prepared,selection,table,{key:i for i,key in enumerate(table['source_id'].to_pylist())})


def test_ordering_multiple_flushes_respect_the_aggregate_disk_budget(tmp_path,monkeypatch):
    from congress_api.retention import catalog_dependency_preparation as preparation
    rows=[]
    for number in range(128):
        row=dict(filename=f'{number}.pdf',source_url=f'https://example.gov/{number}',body_key=f'body-{number}',
            media_type=['application/pdf'],http_status=['200'],source_occurrences=[dict(labels=['x'*512],bytes=b'\0\xff')])
        row['source_id']=index.source_identity(row);rows.append(row)
    table=pa.Table.from_pylist(rows,schema=SCHEMA)
    def work(directory,budget=None):
        return preparation.DependencyPreparation(owner(),directory=directory,preparation_key='multiple-flushes',
            first_unused_order=0,source_orders=None,staging_byte_budget=budget)
    generous=work(tmp_path/'size-basis')
    try:
        generous.prepare([table])
        basis=generous.owner.preparation_metrics['staging_bytes']
    finally:generous.close()
    directory=tmp_path/'limited';budget=basis+(32<<10);limited=work(directory,budget)
    writes=[];original=preparation._BudgetedFile.write
    def write(stream,data):
        if str(stream.name).endswith('ordered.tmp'):
            writes.append((len(data),stream.budget))
        return original(stream,data)
    try:
        limited.prepare([table])
        monkeypatch.setattr(preparation._BudgetedFile,'write',write)
        with pytest.raises(OSError,match='staging byte budget'):
            limited.prepare_order()
        assert len(writes)>2
        assert all(cap<=writes[0][1] for size,cap in writes)
        assert sum(path.stat().st_size for path in directory.rglob('*') if path.is_file())<=budget
        assert (directory/'complete.json').exists()
        assert not (directory/'ordered.json').exists()
        assert not limited.owner.native.calls
    finally:limited.close()


def test_process_loss_during_ordering_reuses_completed_source_files(tmp_path):
    import subprocess
    import sys
    from hashlib import sha256
    script='''
import os
import sys
from pathlib import Path
import pyarrow as pa
from test_catalog_dependency_preparation import owner,SCHEMA
from congress_api.retention import document_index as index
from congress_api.retention.catalog_dependency_preparation import DependencyPreparation
root=Path(sys.argv[1]);phase=sys.argv[2];rows=[]
if phase!='crash':
    import duckdb
    original_connect=duckdb.connect
    def checked_connect(*args,**kwargs):
        assert not (root/'ordered.tmp').exists(), 'Unacknowledged output still occupies the sort allowance'
        return original_connect(*args,**kwargs)
    duckdb.connect=checked_connect
for number in range(512):
    row=dict(filename=f'{number}.pdf',source_url=f'https://example.gov/{number}',body_key=f'body-{number}',
        media_type=['application/pdf'],http_status=['200'],source_occurrences=[dict(labels=['original',None],bytes=b'\\x00\\xff')])
    row['source_id']=index.source_identity(row);rows.append(row)
table=pa.Table.from_pylist(rows,schema=SCHEMA);prepared=owner(rows=32)
def progress(value):
    pending=root/'ordered.tmp'
    if phase=='crash' and value['phase']=='ordering' and pending.exists() and pending.stat().st_size>4:
        os._exit(19)
work=DependencyPreparation(prepared,directory=root,preparation_key='ordering-process-loss',
    first_unused_order=0,source_orders=None,staging_byte_budget=16<<20,on_progress=progress)
def inputs(start):
    if phase!='crash':raise AssertionError('Completed sources were enumerated after process loss')
    yield table
work.prepare(inputs);work.prepare_order()
assert prepared.preparation_reads['sort_input_rows']==len(table)
selected=[]
def visit(prefix):
    part=work.source_table(prefix)
    if part is None:
        for char in '0123456789abcdef':visit(prefix+char)
    elif len(part):selected.extend(part.to_pylist())
visit('')
by_key={row['source_id']:row for row in selected}
assert len(by_key)==len(table)
for ordinal,row in enumerate(table.to_pylist()):
    assert by_key[row['source_id']]['source_values']==row
    assert by_key[row['source_id']]['source_order']==ordinal
assert prepared.preparation_reads['decoded_rows']==len(table)
assert prepared.preparation_metrics['staging_bytes']<=16<<20
work.close()
'''
    directory=tmp_path/'ordering-process-loss'
    before=subprocess.run([sys.executable,'-c',script,str(directory),'crash'],capture_output=True,text=True)
    assert before.returncode==19,before.stderr
    assert (directory/'complete.json').exists()
    assert (directory/'ordered.tmp').exists()
    assert not (directory/'ordered.json').exists()
    preserved={path.name:sha256(path.read_bytes()).hexdigest() for path in directory.glob('part-*.parquet')}
    after=subprocess.run([sys.executable,'-c',script,str(directory),'resume'],capture_output=True,text=True)
    assert after.returncode==0,after.stderr
    assert preserved=={path.name:sha256(path.read_bytes()).hexdigest() for path in directory.glob('part-*.parquet')}
    assert (directory/'ordered.json').exists()
