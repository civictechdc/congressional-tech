"""Typed occurrences retain logical values while all native inputs stay bounded."""
from contextlib import contextmanager
from copy import deepcopy

import pyarrow as pa
import pytest

from congress_api.retention.catalog_rows import CatalogRows, core_table
from test_raw_source_sync import MemoryStore


OCC=pa.list_(pa.struct([pa.field('label',pa.list_(pa.string())),pa.field('url',pa.list_(pa.string()))]))
SCHEMA=pa.schema([pa.field('document_id',pa.string(),nullable=False),pa.field('title',pa.string()),pa.field('source_occurrences',OCC)],metadata={b'catalog_id':b'exact',b'custom':b'original'})


class Native:
    def __init__(self):self.tables,self.reads={},[]
    def run_table(self,table,*,dataset,operation,definition):
        if dataset in self.tables:assert self.tables[dataset].equals(table,check_metadata=True)
        self.tables[dataset]=table
        return dict(verified=True,id=operation,dataset=dict(dataset=dataset,groups=dict(source=dict(rows=len(table))),computed={},related=None,evidence=None))
    @contextmanager
    def source_batches(self,pin,*,schema=None):
        name=pin['dataset']['dataset'];self.reads.append(name)
        table=self.tables[name]
        # Native storage order need not retain application occurrence order.
        yield table.take(pa.array(list(reversed(range(len(table)))),type=pa.int64())).to_reader()


def values():
    return pa.Table.from_pylist([
        dict(document_id='null',title='n',source_occurrences=None),
        dict(document_id='empty',title='e',source_occurrences=[]),
        dict(document_id='edge',title='x',source_occurrences=[None,dict(label=None,url=[]),dict(label=['é','é'],url=['u']),dict(label=['é','é'],url=['u'])]),
        dict(document_id='large',title='big',source_occurrences=[dict(label=['x'*1024],url=['u'])]*18000),
    ],schema=SCHEMA)


def test_large_list_is_typed_bounded_and_exact_projected_reads_skip_children():
    native,store=Native(),MemoryStore();owner=CatalogRows(native=native,store=store)
    table=values();assert table.nbytes>16<<20
    with pytest.raises(ValueError,match='retained byte budget'):
        owner.write(table,dataset='mixed',operation='initial',definition='test',owner_column='document_id',max_rows=8192,max_bytes=16<<20)
    edge=table.slice(0,3)
    edge_pin=owner.write(edge,dataset='edge',operation='initial',definition='test',owner_column='document_id',max_rows=8192,max_bytes=16<<20)
    assert owner.occurrences(edge_pin,schema=SCHEMA,owner_id='null') is None
    assert len(owner.occurrences(edge_pin,schema=SCHEMA,owner_id='empty'))==0
    assert pa.Table.from_batches(list(owner.read(edge_pin,schema=SCHEMA))).equals(edge,check_metadata=True)
    large=table.slice(3,1)
    pin=owner.write(large,dataset='typed',operation='initial',definition='test',owner_column='document_id',max_rows=8192,max_bytes=16<<20)
    assert all(len(t)<=8192 and t.nbytes<=16<<20 for t in native.tables.values())
    native.reads.clear()
    projected=pa.Table.from_batches(list(owner.read(pin,schema=SCHEMA,columns=['document_id','title'])))
    assert projected.equals(large.select(['document_id','title']),check_metadata=True)
    assert all('-occ-' not in name for name in native.reads)
    seq=owner.occurrences(pin,schema=SCHEMA,owner_id='large');assert len(seq)==18000
    assert sum(len(a)for a in seq)==18000
    assert sum(len(a)for a in seq)==18000
    actual=pa.Table.from_batches(list(owner.read(pin,schema=SCHEMA)))
    assert actual.equals(large,check_metadata=True)
    assert native.reads.count('typed')==1
    assert core_table(table).nbytes<1024
    assert owner.write(large,dataset='typed',operation='initial',definition='test',owner_column='document_id',max_rows=8192,max_bytes=16<<20)==pin


def test_selected_descriptor_tampering_refuses_before_native_read():
    native,store=Native(),MemoryStore();owner=CatalogRows(native=native,store=store)
    pin=owner.write(values().slice(0,3),dataset='small',operation='initial',definition='test',owner_column='document_id',max_rows=8,max_bytes=8192)
    changed=deepcopy(pin);changed['catalog_rows']['rows']+=1
    with pytest.raises(ValueError,match='binding'):
        list(owner.read(changed,schema=SCHEMA))
    assert not native.reads


def test_nested_dependency_projection_and_replacement_preserve_exact_values():
    from congress_api.retention.catalog_dependency_storage import CatalogDependencyStorage
    from congress_api.retention import document_index as index
    from test_catalog_dependencies import source,identity
    from test_catalog_dependency_storage import SCHEMA as BASE
    native,store=Native(),MemoryStore()
    schema=BASE.append(pa.field('source_occurrences',OCC))
    row=source('a.pdf','body',source_occurrences=[dict(label=['x'*1024],url=['u'])]*18000)
    owner=CatalogDependencyStorage(native=native,store=store,namespace='nested',source_schema=schema,max_rows=8192,max_bytes=16<<20)
    selected=owner.prepare(None,replacements=[row])
    _,pin=owner.sources.lookup(selected['source_root'],identity(row))
    native.reads.clear()
    projected=owner.read_source_leaf(selected,pin,source_columns=['filename','body_key'])
    assert projected['source_values'][0].as_py()==dict(filename='a.pdf',body_key='body')
    assert all('-occ-'not in name for name in native.reads)
    values=owner.source_occurrences(selected,pin,identity(row));assert len(values)==18000
    assert sum(len(batch)for batch in values)==18000
    assert owner.selected(selected).source(identity(row))==pa.Table.from_pylist([row],schema=schema).to_pylist()[0]
    changed=owner.prepare(selected,replacements=[dict(row,source_occurrences=[None,dict(label=[],url=None)])])
    assert owner.selected(changed).source(identity(row))['source_occurrences']==[None,dict(label=[],url=None)]
    assert owner.selected(selected).source(identity(row))['source_occurrences']==row['source_occurrences']
    removed=owner.prepare(changed,deletions=[identity(row)])
    assert owner.selected(removed).source(identity(row))is None


def test_missing_duplicate_or_wrong_owner_child_refuses():
    native,store=Native(),MemoryStore();owner=CatalogRows(native=native,store=store)
    pin=owner.write(values().slice(2,1),dataset='corrupt',operation='initial',definition='test',owner_column='document_id',max_rows=8,max_bytes=8192)
    key=next(name for name in native.tables if '-occ-'in name)
    original=native.tables[key]
    for changed in (original.slice(1),original.set_column(0,original.schema.field('owner_row'),pa.array([7]*len(original),type=pa.int64())),original.set_column(2,original.schema.field('occurrence_order'),pa.array([0]*len(original),type=pa.int64()))):
        native.tables[key]=changed
        fresh=CatalogRows(native=native,store=store)
        with pytest.raises(ValueError,match='count|owner|ordinal'):
            list(fresh.occurrences(pin,schema=SCHEMA,owner_id='edge'))
    native.tables[key]=original


def test_existing_unsplit_and_absent_nullable_occurrences_remain_readable():
    native,store=Native(),MemoryStore();owner=CatalogRows(native=native,store=store)
    table=values().slice(0,3)
    pin=native.run_table(table,dataset='historical',operation='initial',definition='old')
    list(owner.read(pin,schema=SCHEMA,columns=['document_id']))
    assert owner.occurrences(pin,schema=SCHEMA,owner_id='null')is None
    assert len(owner.occurrences(pin,schema=SCHEMA,owner_id='empty'))==0
    assert sum(len(a)for a in owner.occurrences(pin,schema=SCHEMA,owner_id='edge'))==4
    assert native.reads.count('historical')==1
    assert owner.occurrences(pin,schema=SCHEMA.remove(2),owner_id='empty')is None


def test_directory_lookup_prunes_irrelevant_owner_pages():
    native,store=Native(),MemoryStore();owner=CatalogRows(native=native,store=store)
    table=pa.Table.from_pylist([dict(document_id=str(i),title='t',source_occurrences=[dict(label=['a'],url=[])])for i in range(300)],schema=SCHEMA)
    pin=owner.write(table,dataset='many',operation='initial',definition='test',owner_column='document_id',max_rows=300,max_bytes=64<<10)
    # Force many bounded pages with one child per native part, independently
    # of a realistic larger native row budget.
    assert pa.Table.from_batches(list(owner.read(pin,schema=SCHEMA))).equals(table,check_metadata=True)


def test_actual_native_large_logical_row_roundtrip(tmp_path):
    import os,shutil
    from native_test_helpers import native_test_client
    binary=os.environ.get('DOCSPEC_BINARY')or shutil.which('docspec')
    if not binary:pytest.skip('Set DOCSPEC_BINARY to maintained local CLI')
    native=native_test_client(binary,tmp_path/'native')
    owner=CatalogRows(native=native,store=MemoryStore())
    table=values().slice(3,1)
    pin=owner.write(table,dataset='native-giant',operation='initial',definition='test',owner_column='document_id',max_rows=8192,max_bytes=4<<20)
    assert pa.Table.from_batches(list(owner.read(pin,schema=SCHEMA))).equals(table,check_metadata=True)
