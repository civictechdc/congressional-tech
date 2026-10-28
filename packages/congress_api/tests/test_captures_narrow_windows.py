"""Heavy flags/ranks use narrow inputs and preserve prior window semantics."""
import json
import os

import pyarrow as pa
import pyarrow.parquet as pq
from docspec_client.client import NativeDatasets


def test_heavy_window_sql_projects_only_consumed_keys_and_inputs():
    from congress_api.lake.captures import mapping_steps
    steps={step['name']:step for step in mapping_steps()}
    for name in ('window_inputs','item_references','cutoff_flags','member_flags','append_ranks'):
        sql=steps[name]['sql']
        assert 'SELECT *' not in sql.upper()
        assert all(field not in sql for field in ('run_id','requested_url','pointer_json','media_type'))
    assert 'GROUP BY' in steps['item_references']['sql'] and 'OVER (' not in steps['item_references']['sql']
    assert steps['retained_keys']['materialize'] is True
    ranks=steps['append_ranks']['sql']
    assert 'WHERE is_placeholder' in ranks and 'context_url' not in ranks
    assert 'ORDER BY selected_record_index,capture_index' in ranks
    assert 'OVER (' not in steps['windowed']['sql']
    assert 'source_row_id' in steps['windowed']['sql']
    assert 'source_row_id' not in steps['capture_facts']['sql']


def test_native_narrow_flags_and_ranks_equal_legacy_multiset_with_nullable_duplicates(tmp_path):
    from congress_api.lake.captures import mapping_steps
    from congress_api.retention.provenance import run_job
    def row(source,index,*,key='receipts/test/2026-10-28/window.gz',line=1,item=0,
            placeholder=False,secondary=False,**changes):
        value=dict(source_row_id=source,receipt_key=key,receipt_line=line,selected_record_index=item,
            capture_index=index,primary_count=3,is_placeholder=placeholder,is_secondary=secondary,
            reference_kind='line' if placeholder else 'file' if secondary else 'capture',
            cutoff_candidate=False,completed_final=False,body_sha=None,top_level=True,
            attempt=0,context_url='https://fixture.test/context',url='https://fixture.test/'+str(item),
            run_id='unused-wide-'+('r'*2048),pointer_json='unused-pointer-'+('p'*2048))
        value.update(changes);return value
    rows=[]
    for source in (1,2):
        rows += [row(source,0,cutoff_candidate=True,body_sha='a'*64),
            row(source,1,completed_final=source==2,body_sha='a'*64),
            row(source,2,body_sha='a'*64,top_level=False),
            row(source,3,placeholder=True),row(source,4,item=1,placeholder=True),
            row(source,5,item=2,placeholder=True),row(source,6,item=2,secondary=True,body_sha='a'*64)]
    rows += [row(3,0,line=2,primary_count=2,cutoff_candidate=True,body_sha='a'*64),
        row(3,1,line=2,item=1,primary_count=2,completed_final=True,body_sha='a'*64),
        row(4,0,key=None,line=None,item=None,body_sha='a'*64,top_level=False,
            cutoff_candidate=None,completed_final=None,attempt=None,context_url=None),
        row(4,1,key=None,line=None,item=None,placeholder=True,attempt=None,context_url=None),
        row(5,1,key=None,line=None,item=1,placeholder=True,primary_count=1,attempt=None,context_url=None)]
    integer={'source_row_id','receipt_line','selected_record_index','capture_index','primary_count','attempt'}
    boolean={'is_placeholder','is_secondary','cutoff_candidate','completed_final','top_level'}
    schema=pa.schema([(key,pa.int64() if key in integer else pa.bool_() if key in boolean else pa.string()) for key in rows[0]])
    source=tmp_path/'rows.parquet';pq.write_table(pa.Table.from_pylist(rows,schema=schema),source)
    definitions=mapping_steps();start=next(i for i,step in enumerate(definitions) if step['name']=='window_inputs')
    end=next(i for i,step in enumerate(definitions) if step['name']=='windowed')
    steps=[dict(name='enriched',sql='SELECT * FROM scalar_rows WHERE NOT is_secondary')]+definitions[start:end+1]
    # Frozen pre-change SQL is the oracle, independent of the new group/join path.
    steps += [dict(name='legacy_item_references',sql="""SELECT *,bool_or(NOT is_placeholder AND reference_kind IN ('capture','file'))
        OVER (PARTITION BY receipt_key,receipt_line,selected_record_index) AS has_primary_reference FROM enriched"""),
        dict(name='legacy_retained_items',sql='SELECT * FROM legacy_item_references WHERE NOT is_placeholder OR NOT has_primary_reference'),
        dict(name='legacy_windowed',sql="""SELECT *,
        sum(CASE WHEN is_placeholder THEN 1 ELSE 0 END) OVER (PARTITION BY receipt_key,receipt_line
            ORDER BY selected_record_index,capture_index ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS appended_index,
        bool_or(cutoff_candidate) OVER (PARTITION BY receipt_key,receipt_line,selected_record_index) AS has_cutoff,
        bool_or(completed_final) OVER (PARTITION BY receipt_key,receipt_line,selected_record_index) AS has_completed_final,
        bool_or(body_sha IS NOT NULL AND NOT top_level) OVER
            (PARTITION BY receipt_key,receipt_line,selected_record_index,attempt,context_url) AS has_member FROM legacy_retained_items""")]
    fields='receipt_key,receipt_line,selected_record_index,capture_index,url,run_id,pointer_json,has_cutoff,has_completed_final,has_member'
    final='CASE WHEN is_placeholder THEN primary_count+appended_index-1 ELSE capture_index END AS final_index'
    for name,origin in [('before','legacy_windowed'),('after','windowed')]:
        steps.append(dict(name=name,sql=f'SELECT {fields},{final} FROM {origin}'))
        steps.append(dict(name=name+'_multiset',sql=f'SELECT *,count(*) AS occurrences FROM {name} GROUP BY ALL'))
    result=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
        inputs=[dict(name='scalar_rows',kind='parquet',path=str(source))],steps=steps,outputs=[],queries=[
            dict(name='left_only',sql='SELECT * FROM before_multiset EXCEPT SELECT * FROM after_multiset'),
            dict(name='right_only',sql='SELECT * FROM after_multiset EXCEPT SELECT * FROM before_multiset'),
            dict(name='count',sql='SELECT count(*) AS n FROM windowed'),
            dict(name='appended',sql='SELECT final_index FROM after WHERE receipt_line=1 AND selected_record_index IN (1,2) ORDER BY final_index'),
            dict(name='rank_plan',sql='EXPLAIN SELECT * FROM append_ranks')])
    assert result['left_only']==result['right_only']==[]
    assert result['count']==[dict(n=14)]
    assert result['appended']==[dict(final_index=i) for i in (3,4,5,6)]
    physical=next(r['plan'] for r in result['rank_plan'] if r['plan_type']=='physical_plan')
    assert 'WindowAggExec' in physical
    assert all(field not in physical for field in ('run_id','pointer_json','context_url','body_sha'))
    assert json.loads((tmp_path/'job.json').read_text())['queries'][-1]['sql']=='EXPLAIN SELECT * FROM append_ranks'
