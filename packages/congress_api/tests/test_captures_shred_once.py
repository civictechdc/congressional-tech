"""List items are shredded once before a scalar lookup, without row multiplication."""
import json
import os

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from docspec_client.client import NativeDatasets

from capture_qualification_helpers import created_qualifications
from test_captures_ingest import body,ingest
from test_captures_root_objects import minimal_counter


def test_list_item_projection_precedes_reference_join_and_discards_item_text(tmp_path):
    from congress_api.lake.captures import mapping_steps
    from congress_api.retention.provenance import parquet_output,run_job
    source=dict(run_id='shred',record=[dict(url=f'https://fixture.test/{i}',
        content=dict(body='item-payload-marker-'*1000),outcome='saved') for i in range(3)],
        captures=[body(pointer=[0,'content','body']),body(pointer=['0','other','body'])])
    stage=ingest(tmp_path,[source]);job=json.loads((stage/'job.json').read_text())
    steps={step['name']:step for step in job['steps']}
    assert steps['lines']['materialize'] is True and steps['items']['materialize'] is True
    assert 'record_items' not in steps['entries']['sql']
    assert all('list_raw' not in step['sql'] and 'json_get_json(list_raw,' not in step['sql'] for step in job['steps'])
    assert 'json_get_many(item,' in steps['items']['sql']
    assert 'source_row_id' in steps['selected_records']['sql']
    assert 'selected_record_index' in steps['selected_records']['sql'] and 'item_index' in steps['selected_records']['sql']
    check=tmp_path/'item-plan';check.mkdir()
    result=run_job(check,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
        inputs=job['inputs'],steps=job['steps'][:next(i for i,s in enumerate(job['steps']) if s['name']=='items')+1],
        outputs=[parquet_output(check,'items','SELECT * FROM items',['source_row_id','item_index'])],
        queries=[dict(name='plan',sql='EXPLAIN SELECT * FROM items')])
    table=pq.read_table(check/'items.parquet')
    assert table.num_rows==3
    assert table['item_index'].to_pylist()==[0,1,2]
    assert all(not pa.types.is_nested(f.type) for f in table.schema)
    assert 'item-payload-marker-' not in str(table.to_pylist())
    physical=next(row['plan'] for row in result['plan'] if row['plan_type']=='physical_plan')
    assert 'json_get_' not in physical and 'UnnestExec' not in physical
    rows=pq.read_table(stage/'captures.parquet').to_pylist()
    assert [(r['capture_index'],r['url']) for r in rows]==[(0,'https://fixture.test/0'),
        (1,'https://fixture.test/0'),(2,'https://fixture.test/1'),(3,'https://fixture.test/2')]
    assert 'source_row_id' not in rows[0]


def test_equal_duplicate_source_lines_do_not_multiply_through_item_lookup(tmp_path):
    from congress_api.lake.captures import stage_captures
    key='receipts/documents/2026-10-28/assemble-duplicate.gz'
    raw=dict(record=[dict(url='https://fixture.test/same')],captures=[])
    counter=minimal_counter(tmp_path,[(key,raw),(key,raw)],False)
    from congress_api.lake.captures import mapping_steps
    from congress_api.lake.receipt_metadata import source_plan
    from congress_api.retention.provenance import run_job
    from docspec_client.models import DocSpecFailure
    native=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    plan=source_plan(counter=counter,receipt_keys=[key])
    check=tmp_path/'counts';check.mkdir()
    result=run_job(check,native,inputs=plan['inputs'],steps=plan['steps']+mapping_steps(),outputs=[],
        queries=[dict(name='count',sql='SELECT count(*) AS n FROM capture_facts')])
    assert result['count']==[dict(n=2)]
    # The pre-existing exporter refuses duplicate public ordering keys.
    with pytest.raises(DocSpecFailure,match='ordering keys are not unique'):
        stage_captures([dict(key=key)],validated_counter=counter,
            source_qualifications=created_qualifications(counter),engine=native,work=tmp_path/'stage')
    assert not (tmp_path/'stage/ingested-receipts.json').exists()
