"""Exact repair locators are hash keys; NULL body keys still never match."""
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from docspec_client.client import NativeDatasets

from test_raw_repair import fixture,DIGEST,SIZE
from congress_api.retention.provenance import file_pin,run_job
from congress_api.retention.raw_repair import prepare_repair


def nullable_inputs(tmp_path,*,null_body=False):
    captures,repairs,rows=fixture(tmp_path)
    a=pq.read_table(captures);b=pq.read_table(repairs)
    values=a.to_pylist();fixes=b.to_pylist()
    for row in values+fixes:row.update(receipt_key=None,receipt_line=None,pointer_json=None)
    if null_body:values[0]['body_key']=None;fixes[0]['key']=None
    pq.write_table(pa.Table.from_pylist(values,schema=a.schema),captures)
    pq.write_table(pa.Table.from_pylist(fixes,schema=b.schema),repairs)
    return captures,repairs,values


def test_repair_hashes_every_nullable_locator_without_residual_key_filter(tmp_path):
    captures,repairs,rows=nullable_inputs(tmp_path)
    native=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    stage=prepare_repair(captures,repairs,engine=native,work=tmp_path/'repair',expected=file_pin(captures)['sha256'])
    assert pq.read_table(stage['output']).to_pylist()==[dict(rows[0],stored_sha256=DIGEST,stored_bytes=SIZE)]
    job=json.loads((tmp_path/'repair/job.json').read_text())
    check=tmp_path/'plan';check.mkdir()
    result=run_job(check,native,inputs=job['inputs'],steps=job['steps'],outputs=[],
        queries=[dict(name='plan',sql='EXPLAIN SELECT * FROM patched')])
    physical=next(row['plan'] for row in result['plan'] if row['plan_type']=='physical_plan')
    joins=[line for line in physical.splitlines() if 'HashJoinExec:' in line]
    assert len(joins)==1
    line=joins[0];on=line.split('on=[',1)[1].split(']',1)[0]
    for key in ('body_key','key','receipt_key','receipt_line','pointer_json'):assert key in on,line
    assert 'NullsEqual: true' in line
    residual=line.split('filter=',1)[1] if 'filter=' in line else ''
    assert all(key not in residual for key in ('body_key','receipt_key','receipt_line','pointer_json'))


def test_null_body_repair_stays_unmatched_and_cannot_become_a_correction(tmp_path):
    captures,repairs,rows=nullable_inputs(tmp_path,null_body=True)
    with pytest.raises(ValueError,match='Ambiguous'):
        prepare_repair(captures,repairs,engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
            work=tmp_path/'repair',expected=file_pin(captures)['sha256'])
    result=json.loads((tmp_path/'repair/result.json').read_text())
    audit=next(query['data'][0] for query in result['queries'] if query['name']=='audit')
    assert audit['unmatched']==1 and audit['ambiguous']==0 and audit['changed']==0
    assert pq.read_table(tmp_path/'repair/corrected.parquet').to_pylist()==rows
    assert not (tmp_path/'repair/manifest.json').exists()
