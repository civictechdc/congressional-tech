"""Every nullable comparison identity is a native hash key; null locators never match."""
import json
import os
from pathlib import Path
import re

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from docspec_client.client import NativeDatasets

from congress_api.lake.capture_comparison import compare_old
from congress_api.retention.provenance import run_job
from test_capture_comparison_batches import batch_fixture,KEY


def explain_step(spec,name,*,native,work):
    step=next(step for step in spec['steps'] if step['name']==name)
    prefix=spec['steps'][:spec['steps'].index(step)]
    result=run_job(work,native,inputs=spec['inputs'],steps=prefix,outputs=[],
        queries=[dict(name='plan',sql='EXPLAIN '+step['sql'])])
    return next(row['plan'] for row in result['plan'] if row['plan_type']=='physical_plan')


@pytest.mark.parametrize('step_name',['matched','old_only','new_only'])
def test_actual_comparison_plan_hashes_every_identity_without_key_residuals(tmp_path,step_name):
    old,parts=batch_fixture(tmp_path)
    native=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    compare_old(parts,old,engine=native,work=tmp_path/'comparison')
    spec=json.loads((tmp_path/'comparison/job.json').read_text())
    work=tmp_path/'explain';work.mkdir()
    physical=explain_step(spec,step_name,native=native,work=work)
    joins=[line for line in physical.splitlines() if 'HashJoinExec:' in line]
    assert len(joins)==1,physical
    [join]=joins
    keys=join.split('on=[',1)[1].split(']',1)[0]
    for key in ('receipt_key','receipt_line','body_sha','pointer','occurrence'):
        assert len(re.findall(r'\b'+key+r'@',keys))==2,physical
    assert 'NullEqualsNull' in join,physical
    assert 'filter=' not in join,physical


def test_secondary_comparison_plan_hashes_all_four_identity_keys(tmp_path):
    old,parts=batch_fixture(tmp_path)
    old_rows=pq.read_table(old).to_pylist()
    old_rows.append(dict(old_rows[0],reference_kind='file',pointer_json='["secondary"]'))
    pq.write_table(pa.Table.from_pylist(old_rows),old)
    native=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    report=compare_old(parts,old,engine=native,work=tmp_path/'comparison')
    assert report['secondary_duplicates']==1
    spec=json.loads((tmp_path/'comparison/job.json').read_text())
    work=tmp_path/'explain';work.mkdir()
    physical=explain_step(spec,'secondary_duplicates',native=native,work=work)
    joins=[line for line in physical.splitlines() if 'HashJoinExec:' in line]
    assert len(joins)==2,physical
    for join in joins:
        keys=join.split('on=[',1)[1].split(']',1)[0]
        for key in ('receipt_key','receipt_line','body_sha','context_url'):
            assert len(re.findall(r'\b'+key+r'@',keys))==2,physical
        assert 'NullEqualsNull' in join,physical
        if 'filter=' in join:
            residual=join.split('filter=',1)[1]
            assert all(re.search(r'\b'+key+r'@',residual) is None
                for key in ('receipt_key','receipt_line','body_sha','context_url')),physical


@pytest.mark.parametrize('null_key',['receipt_key','receipt_line'])
def test_former_equal_locator_keys_still_never_match_nulls_or_drop_unmatched_rows(tmp_path,null_key):
    old,parts=batch_fixture(tmp_path,old_count=1,new_count=1)
    for path in (old,parts[0]):
        table=pq.read_table(path)
        table=table.set_column(table.schema.get_field_index(null_key),null_key,
            pa.array([None],type=table.schema.field(null_key).type))
        pq.write_table(table,path)
    report=compare_old(parts,old,engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
        work=tmp_path/'comparison')
    assert report['matched']==0 and report['old_only']==report['new_only']==1
    assert report['owner_gate'] is True
    assert pq.read_table(tmp_path/'comparison/old-only.parquet')[null_key].to_pylist()==[None]
    assert pq.read_table(tmp_path/'comparison/new-only.parquet')[null_key].to_pylist()==[None]


@pytest.mark.parametrize('null_key',['receipt_key','receipt_line','sha256'])
def test_former_equal_secondary_keys_still_never_normalize_null_facts(tmp_path,null_key):
    old,parts=batch_fixture(tmp_path,old_count=1,new_count=1)
    for path in (old,parts[0]):
        table=pq.read_table(path)
        table=table.set_column(table.schema.get_field_index(null_key),null_key,
            pa.array([None],type=table.schema.field(null_key).type))
        if path==old:
            rows=table.to_pylist();rows.append(dict(rows[0],reference_kind='file',pointer_json='["secondary"]'))
            table=pa.Table.from_pylist(rows,schema=table.schema)
        pq.write_table(table,path)
    report=compare_old(parts,old,engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
        work=tmp_path/'comparison')
    assert report['secondary_duplicates']==0 and report['old_only']>=1 and report['owner_gate'] is True
    lost=pq.read_table(tmp_path/'comparison/old-only.parquet').to_pylist()
    assert any(row['reference_kind']=='file' and row[null_key] is None for row in lost)
