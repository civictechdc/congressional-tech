"""All item identities must be actual hash keys, preserving original NULL rules."""
import os
import re

import pyarrow as pa
import pyarrow.parquet as pq
from docspec_client.client import NativeDatasets


def test_item_lookup_hashes_every_identity_and_preserves_original_nonnull_keys(tmp_path):
    from congress_api.lake.captures import mapping_steps
    from congress_api.lake.receipt_metadata import SCALARS
    from congress_api.retention.provenance import run_job
    sql=next(step['sql'] for step in mapping_steps() if step['name']=='selected_records')
    columns=list(dict.fromkeys(re.findall(r'i\.(i_\w+)',sql)))
    left_fields=dict(source_row_id=pa.int64(),receipt_key=pa.string(),receipt_line=pa.int64(),
        selected_record_index=pa.int64(),record_is_list=pa.bool_(),is_secondary=pa.bool_(),
        is_placeholder=pa.bool_(),reference_kind=pa.string(),ordinal=pa.int64())
    right_fields=dict(source_row_id=pa.int64(),receipt_key=pa.string(),receipt_line=pa.int64(),item_index=pa.int64())
    for column in columns:
        kind=SCALARS.get(column[2:],'bool' if column=='i_error_present' else 'str')
        right_fields[column]=pa.bool_() if kind=='bool' else pa.int64() if kind=='int' else pa.string()
    entries=[];items=[]
    for ordinal,(source,index,key,line) in enumerate([(1,0,None,None),(None,1,'r',1),(2,None,'r',1)]):
        entries.append(dict(source_row_id=source,receipt_key=key,receipt_line=line,
            selected_record_index=index,record_is_list=True,is_secondary=False,
            is_placeholder=False,reference_kind='capture',ordinal=ordinal))
        item=dict.fromkeys(right_fields)
        item.update(source_row_id=source,receipt_key=key,receipt_line=line,item_index=index,
            i_url='https://fixture.test/'+str(ordinal),i_error_present=False)
        items.append(item)
    paths=[]
    for name,rows,fields in [('entry_facts',entries,left_fields),('items',items,right_fields)]:
        path=tmp_path/(name+'.parquet');pq.write_table(pa.Table.from_pylist(rows,schema=pa.schema(list(fields.items()))),path)
        paths.append(dict(name=name,kind='parquet',path=str(path)))
    result=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
        inputs=paths,steps=[dict(name='selected_records',sql=sql)],outputs=[],queries=[
            dict(name='values',sql='SELECT ordinal,i_url FROM selected_records ORDER BY ordinal'),
            dict(name='plan',sql='EXPLAIN SELECT * FROM selected_records')])
    assert result['values']==[dict(ordinal=0,i_url='https://fixture.test/0'),
        dict(ordinal=1,i_url=None),dict(ordinal=2,i_url=None)]
    physical=next(row['plan'] for row in result['plan'] if row['plan_type']=='physical_plan')
    joins=[line for line in physical.splitlines() if 'HashJoinExec:' in line]
    assert len(joins)==1
    line=joins[0];on=line.split('on=[',1)[1].split(']',1)[0]
    for field in ('source_row_id','receipt_key','receipt_line','selected_record_index','item_index'):
        assert field in on,line
    assert 'NullEqualsNull' in line
    residual=line.split('filter=',1)[1] if 'filter=' in line else ''
    assert all(field not in residual for field in ('source_row_id','receipt_key','receipt_line','selected_record_index','item_index'))
