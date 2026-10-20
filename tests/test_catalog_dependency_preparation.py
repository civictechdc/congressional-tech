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
