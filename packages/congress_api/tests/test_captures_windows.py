"""Only scalar facts cross the narrow producer's joins and materializations."""
import json
import os
import re

import pyarrow as pa
import pyarrow.parquet as pq
from docspec_client.client import NativeDatasets

from test_captures_ingest import body, ingest
from test_receipt_metadata import counter_fixture
from capture_qualification_helpers import write_qualified_parquet


def test_capture_join_boundary_contains_only_scalar_facts(tmp_path):
    marker='ignored-header-prior-payload-'
    stage=ingest(tmp_path,[dict(complete=True,record=dict(url='https://example.test/a',
        content=dict(body=marker*10000),response_headers={'X-Padding':marker*10000},
        prior_attempts=[dict(content=dict(body=marker*10000))]),
        captures=[body() for _ in range(32)],file_references=[body(stored_bytes=42)])])
    evidence=pq.read_table(stage/'capture-evidence.parquet')
    assert evidence.num_rows==32 and evidence['stored_bytes'].to_pylist()==[42]*32
    assert marker not in str(evidence.to_pylist())
    assert all(not pa.types.is_nested(field.type) for field in evidence.schema)
    job=json.loads((stage/'job.json').read_text())
    steps={step['name']:step for step in job['steps']}
    assert steps['scalar_rows']['materialize'] is True
    for step in job['steps']:
        if 'JOIN' in step['sql']:
            assert all(re.search(r'\b'+name+r'\b',step['sql']) is None
                       for name in ('__raw_line','list_raw','selected_record','entry','item'))
    assert ' FROM decisions' in steps['scalar_rows']['sql']
    assert 'line' not in evidence.column_names and 'record' not in evidence.column_names


def test_native_counter_plan_scans_once_and_joins_only_materialized_scalars(tmp_path):
    from congress_api.lake.captures import mapping_steps, PK
    from congress_api.lake.receipt_metadata import source_plan
    from congress_api.retention.provenance import run_job, parquet_output
    counter, files = counter_fixture(tmp_path)
    table = pq.read_table(counter); rows = table.to_pylist()
    raw = json.loads(rows[-1]['__raw_line'])
    raw['record'] = [raw['record'], dict(url='https://example.test/list', complete=True)]
    raw['captures'][0]['pointer'] = [1, 'content', 'body']
    rows[-1].update(record=None, __raw_line=json.dumps(raw), __type_conflicts=['["record"]'])
    write_qualified_parquet(pa.Table.from_pylist(rows, schema=table.schema), counter)
    native = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    plan = source_plan(counter=counter, receipt_keys=[row['key'] for row in files])
    # The source list is shredded once, then the items side is materialized as
    # scalars before reference fanout joins it. Inspect that real item projection.
    definitions=mapping_steps()
    item_end=next(i for i,step in enumerate(definitions) if step['name']=='items')
    first = tmp_path/'before-scalar'; first.mkdir()
    item_steps=plan['steps']+[dict(step,materialize=False) for step in definitions[:item_end+1]]
    result = run_job(first, native, inputs=plan['inputs'], steps=item_steps, outputs=[],
        queries=[dict(name='plan', sql='EXPLAIN SELECT * FROM items')])
    physical = next(row['plan'] for row in result['plan'] if row['plan_type'] == 'physical_plan')
    assert physical.count('DataSourceExec') == 1
    assert physical.count('UnnestExec') == 1
    assert physical.count('json_get_many(') == 1
    assert 'JoinExec' not in physical
    second = tmp_path/'after-scalar'; second.mkdir()
    result = run_job(second, native, inputs=plan['inputs'],
        steps=plan['steps']+mapping_steps(),
        outputs=[parquet_output(second, 'scalars', 'SELECT * FROM scalar_rows', PK)],
        queries=[dict(name='plan', sql='EXPLAIN SELECT * FROM windowed')])
    physical = next(row['plan'] for row in result['plan'] if row['plan_type'] == 'physical_plan')
    assert 'JoinExec' in physical
    assert 'WindowAggExec' in physical
    assert all(name not in physical for name in ('__raw_line', 'list_raw', 'json_get_many('))
    assert re.search(r'\bselected_record\b',physical) is None
    schema=pq.read_schema(second/'scalars.parquet')
    assert schema.field('selected_record_index').type==pa.int64()
    assert all(not pa.types.is_nested(field.type) for field in schema)
