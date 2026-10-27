"""D1/D3 append through C7; a second run closes no already-complete work."""
import os

import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from docspec_client.client import NativeDatasets


def test_native_table_creation_and_repeated_append(tmp_path):
    from congress_api.lake.tables import create_table, append_rows
    engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    schema={'type':'struct','schema-id':0,'identifier-field-ids':[1],
            'fields':[{'id':1,'name':'receipt_key','required':True,'type':'string'},
                      {'id':2,'name':'value','required':False,'type':'long'}]}
    table=dict(namespace=['archive'],name='captures_v1')
    create_table(engine=engine,work=tmp_path/'create',catalog_root=tmp_path/'catalog',
        table=table,schema=schema,location=tmp_path/'data',create_namespace=True)
    source=tmp_path/'source.parquet'
    pq.write_table(pa.table({'receipt_key':['one','two'],'value':[1,2]}),source)
    first=append_rows(source,engine=engine,work=tmp_path/'first',catalog_root=tmp_path/'catalog',
        table=table,keys=['receipt_key'],definition='mapping-v1')
    assert sum(f['rows'] for f in first['files'])==2
    second=append_rows(source,engine=engine,work=tmp_path/'second',catalog_root=tmp_path/'catalog',
        table=table,keys=['receipt_key'],definition='mapping-v1')
    assert second['files']==[] and second['metadata_location']==first['metadata_location']
    more=tmp_path/'more.parquet'
    pq.write_table(pa.table({'receipt_key':['two','three'],'value':[2,3]}),more)
    third=append_rows(more,engine=engine,work=tmp_path/'third',catalog_root=tmp_path/'catalog',
        table=table,keys=['receipt_key'],definition='mapping-v1')
    assert sum(f['rows'] for f in third['files'])==1
    assert third['table_uuid']==first['table_uuid']
    assert third['snapshot']!=first['snapshot']


@pytest.mark.parametrize('binary_type,iceberg_type', [
    (pa.binary(32),'fixed[32]'), (pa.binary(),'binary')])
def test_compound_binary_work_key_appends_and_repeats_as_noop(tmp_path,binary_type,iceberg_type):
    """D2 body digests remain binary in storage and identify native pending work."""
    from congress_api.lake.tables import create_table, append_rows
    engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    schema={'type':'struct','schema-id':0,'identifier-field-ids':[1,2],
        'fields':[{'id':1,'name':'body_sha','required':True,'type':iceberg_type},
                  {'id':2,'name':'parser_version','required':True,'type':'string'},
                  {'id':3,'name':'value','required':False,'type':'long'}]}
    table=dict(namespace=['archive'],name='body_readings')
    create_table(engine=engine,work=tmp_path/'create',catalog_root=tmp_path/'catalog',
        table=table,schema=schema,location=tmp_path/'data',create_namespace=True)
    arrow_schema=pa.schema([('body_sha',binary_type),('parser_version',pa.string()),('value',pa.int64())])
    source=tmp_path/'source.parquet'
    pq.write_table(pa.Table.from_pylist([
        dict(body_sha=b'a'*32,parser_version='v1',value=1),
        dict(body_sha=b'a'*32,parser_version='v2',value=2)],schema=arrow_schema),source)
    kwargs=dict(engine=engine,catalog_root=tmp_path/'catalog',table=table,
                keys=['body_sha','parser_version'],definition='body-reader-v1')
    first=append_rows(source,work=tmp_path/'first',**kwargs)
    assert sum(f['rows'] for f in first['files'])==2
    second=append_rows(source,work=tmp_path/'second',**kwargs)
    assert second['files']==[] and second['metadata_location']==first['metadata_location']
    more=tmp_path/'more.parquet'
    pq.write_table(pa.Table.from_pylist([
        dict(body_sha=b'a'*32,parser_version='v2',value=2),
        dict(body_sha=b'b'*32,parser_version='v1',value=3)],schema=arrow_schema),more)
    third=append_rows(more,work=tmp_path/'third',**kwargs)
    assert sum(f['rows'] for f in third['files'])==1
    stored=pa.concat_tables([pq.read_table(f['path']) for f in first['files']+third['files']])
    assert set(zip(stored['body_sha'].to_pylist(),stored['parser_version'].to_pylist()))=={
        (b'a'*32,'v1'),(b'a'*32,'v2'),(b'b'*32,'v1')}
