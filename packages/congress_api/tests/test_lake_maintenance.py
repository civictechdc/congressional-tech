"""D5: measured triggers, typed generation equality and kept-release protection."""
import os

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from docspec_client.client import NativeDatasets


SCHEMA={'type':'struct','schema-id':0,'identifier-field-ids':[1], 'fields':[
    {'id':1,'name':'key','required':True,'type':'string'},
    {'id':2,'name':'value','required':False,'type':'binary'}]}


def generation(tmp_path,name,rows):
    from congress_api.lake.tables import create_table,append_rows
    engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    table=dict(namespace=['archive'],name=name)
    catalog=tmp_path/'catalog'
    create_table(engine=engine,work=tmp_path/(name+'-create'),catalog_root=catalog,
        table=table,schema=SCHEMA,location=tmp_path/name,create_namespace=name=='old')
    source=tmp_path/(name+'.parquet')
    pq.write_table(pa.Table.from_pylist(rows,schema=pa.schema([
        ('key',pa.string()),('value',pa.binary())])),source)
    result=append_rows(source,engine=engine,work=tmp_path/(name+'-append'),
        catalog_root=catalog,table=table,keys=['key'],definition='fixture-v1')
    pin=dict(kind='native_table',snapshot=result.get('snapshot'),**{k:result[k] for k in
        ('metadata_location','table_uuid','schema_id')})
    return engine,table,pin


def test_policy_uses_only_explicit_measured_thresholds():
    from congress_api.lake.maintenance import maintenance_decision
    numbers=dict(file_count=3,manifest_count=2,scan_planning_seconds=0.5)
    assert maintenance_decision(numbers,numbers)==[]
    assert maintenance_decision(numbers,{**numbers,'file_count':2})==['file_count']
    for value in (-1,float('nan'),float('inf'),True,'2'):
        with pytest.raises(ValueError):
            maintenance_decision({**numbers,'scan_planning_seconds':value},numbers)
    with pytest.raises(ValueError):maintenance_decision(numbers,{})
    with pytest.raises(ValueError):maintenance_decision({**numbers,'file_count':1.5},numbers)


def test_native_rebuild_returns_equal_generation_and_keeps_old(tmp_path):
    from congress_api.lake.maintenance import rebuild_generation,verify_generations,purge_generation
    engine,old_table,old=generation(tmp_path,'old',[
        dict(key='b',value=None),dict(key='a',value=b'\x00\xff')])
    new=rebuild_generation(old,engine=engine,work=tmp_path/'rebuild',
        catalog_root=tmp_path/'catalog',table=dict(namespace=['archive'],name='new_g1'),
        schema=SCHEMA,location=tmp_path/'new_g1',keys=['key'],definition='fixture-v1')
    assert new['table_uuid']!=old['table_uuid']
    verify_generations(old,new,keys=['key'],engine=engine,work=tmp_path/'equal')
    kept=[{'inputs':{'tables':{'captures':old}}},{'inputs':{'tables':{'captures':new}}}]
    with pytest.raises(ValueError,match='kept release'):
        purge_generation(old,table=old_table,kept_inputs=kept,engine=engine,
            work=tmp_path/'refused',catalog_root=tmp_path/'catalog')
    assert not (tmp_path/'refused').exists()
    # Purge must also protect earlier snapshots of this same generation.
    with pytest.raises(ValueError,match='kept release'):
        purge_generation(old,table=old_table,kept_inputs=[{'tables':{
            'old':{**old,'metadata_location':'/earlier.metadata.json'}}}],engine=engine,
            work=tmp_path/'refused-earlier',catalog_root=tmp_path/'catalog')
    purge_generation(old,table=old_table,kept_inputs=[{'tables':{'new':new}}],
        engine=engine,work=tmp_path/'purge',catalog_root=tmp_path/'catalog')
    verify_generations(new,new,keys=['key'],engine=engine,work=tmp_path/'survives')


def test_native_equality_refuses_changed_typed_values(tmp_path):
    from congress_api.lake.maintenance import verify_generations
    engine,_,old=generation(tmp_path,'old',[dict(key='a',value=b'\x00')])
    _,_,new=generation(tmp_path,'changed',[dict(key='a',value=b'\xff')])
    with pytest.raises(ValueError,match='differ'):
        verify_generations(old,new,keys=['key'],engine=engine,work=tmp_path/'different')


def test_native_rebuild_refuses_duplicate_primary_key_before_creation(tmp_path):
    from congress_api.lake.maintenance import rebuild_generation
    engine,_,old=generation(tmp_path,'old',[
        dict(key='a',value=b'one'),dict(key='a',value=b'two')])
    with pytest.raises(ValueError,match='primary key'):
        rebuild_generation(old,engine=engine,work=tmp_path/'refused',
            catalog_root=tmp_path/'catalog',table=dict(namespace=['archive'],name='new'),
            schema=SCHEMA,location=tmp_path/'new',keys=['key'],definition='fixture-v1')
    assert not (tmp_path/'refused'/'create').exists()


def test_native_empty_generation_rebuild_keeps_typed_schema(tmp_path):
    from congress_api.lake.maintenance import rebuild_generation
    engine,_,old=generation(tmp_path,'old',[])
    new=rebuild_generation(old,engine=engine,work=tmp_path/'empty-rebuild',
        catalog_root=tmp_path/'catalog',table=dict(namespace=['archive'],name='empty_g1'),
        schema=SCHEMA,location=tmp_path/'empty_g1',keys=['key'],definition='fixture-v1')
    assert new['snapshot'] is None and new['table_uuid']!=old['table_uuid']


def test_native_purge_rejects_stale_metadata_and_never_deletes_raw(tmp_path):
    from congress_api.lake.maintenance import purge_generation
    from congress_api.lake.tables import append_rows
    from docspec_client.models import DocSpecFailure
    engine,table,old=generation(tmp_path,'old',[dict(key='a',value=b'one')])
    raw=tmp_path/'raw';raw.mkdir();(raw/'body').write_bytes(b'raw truth')
    source=tmp_path/'more.parquet'
    pq.write_table(pa.table({'key':['b'],'value':[b'two']}),source)
    current=append_rows(source,engine=engine,work=tmp_path/'more',
        catalog_root=tmp_path/'catalog',table=table,keys=['key'],definition='fixture-v1')
    with pytest.raises(DocSpecFailure,match='stale_authority'):
        purge_generation(old,table=table,kept_inputs=[],engine=engine,
            work=tmp_path/'stale',catalog_root=tmp_path/'catalog')
    fresh={**old,**{key:current[key] for key in old if key!='kind'}}
    purge_generation(fresh,table=table,kept_inputs=[],engine=engine,
        work=tmp_path/'purge',catalog_root=tmp_path/'catalog')
    assert (raw/'body').read_bytes()==b'raw truth'


def test_native_equality_refuses_schema_coercion(tmp_path):
    from congress_api.lake.maintenance import verify_generations
    from congress_api.lake.tables import create_table,append_rows
    engine,_,old=generation(tmp_path,'old',[dict(key='a',value=b'one')])
    schema={**SCHEMA,'fields':[SCHEMA['fields'][0],{**SCHEMA['fields'][1],'type':'string'}]}
    table=dict(namespace=['archive'],name='text')
    create_table(engine=engine,work=tmp_path/'text-create',catalog_root=tmp_path/'catalog',
        table=table,schema=schema,location=tmp_path/'text')
    source=tmp_path/'text.parquet'
    pq.write_table(pa.table({'key':['a'],'value':['one']}),source)
    result=append_rows(source,engine=engine,work=tmp_path/'text-append',
        catalog_root=tmp_path/'catalog',table=table,keys=['key'],definition='fixture-v1')
    new={**old,**{key:result[key] for key in old if key!='kind'}}
    with pytest.raises(ValueError,match='typed schema'):
        verify_generations(old,new,keys=['key'],engine=engine,work=tmp_path/'different')


@pytest.mark.parametrize('uppercase_on',['selected','kept'])
def test_purge_protects_equivalent_uuid_spellings_before_effects(tmp_path,uppercase_on):
    from congress_api.lake.maintenance import purge_generation
    engine,table,selected=generation(tmp_path,'old',[dict(key='a',value=b'one')])
    kept={**selected,'metadata_location':'/earlier.metadata.json'}
    if uppercase_on=='selected':
        selected={**selected,'table_uuid':selected['table_uuid'].upper()}
    else:
        kept={**kept,'table_uuid':kept['table_uuid'].upper()}
    with pytest.raises(ValueError,match='kept release'):
        purge_generation(selected,table=table,kept_inputs=[{'tables':{'old':kept}}],
            engine=engine,work=tmp_path/'refused',catalog_root=tmp_path/'catalog')
    assert not (tmp_path/'refused').exists()
