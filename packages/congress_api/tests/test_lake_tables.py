"""D1/D3 append through C7; a second run closes no already-complete work."""
import os

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
