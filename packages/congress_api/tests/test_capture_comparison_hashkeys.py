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


@pytest.mark.parametrize('scoped',[False,True])
def test_actual_comparison_pivot_groups_nullable_identities_without_wide_builds(tmp_path,scoped):
    old,parts=batch_fixture(tmp_path)
    native=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    compare_old(parts,old,engine=native,work=tmp_path/'comparison',receipt_keys=[KEY] if scoped else None)
    spec=json.loads((tmp_path/'comparison/job.json').read_text())
    retained={step['name'] for step in spec['steps'] if step.get('materialize',False)}
    assert 'old_numbered' in retained and 'old_facts' not in retained
    assert len(retained & {'new_input','new_values'})==1
    work=tmp_path/'explain';work.mkdir()
    physical=explain_step(spec,'paired',native=native,work=work)
    aggregates=[line for line in physical.splitlines() if 'AggregateExec:' in line]
    assert any('mode=Partial' in line for line in aggregates),physical
    assert any('mode=FinalPartitioned' in line for line in aggregates),physical
    assert 'RepartitionExec: partitioning=Hash' in physical,physical
    for key in ('receipt_key','receipt_line','body_sha','pointer','occurrence','invalid_side'):
        assert any(re.search(r'\b'+key+r'@',line) for line in aggregates),physical
    # The surviving identity anti-join builds only secondary old-row IDs.
    joins=[line for line in physical.splitlines() if 'HashJoinExec:' in line]
    assert len(joins)==1+int(scoped),physical
    [join]=[line for line in joins if 'join_type=RightAnti' in line]
    assert 'old_row@' in join and 'filter=' not in join,physical
    scope_joins=[line for line in joins if 'join_type=RightSemi' in line]
    assert len(scope_joins)==int(scoped),physical
    assert all('receipt_key@' in line and 'filter=' not in line for line in scope_joins),physical
    assert 'projection=[old_row]' in physical,physical


@pytest.mark.parametrize('step_name',['new_selected','excluded_receipts'])
def test_comparison_scope_builds_only_the_small_receipt_key_set(tmp_path,step_name):
    old,parts=batch_fixture(tmp_path)
    native=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    compare_old(parts,old,engine=native,work=tmp_path/'comparison',receipt_keys=[KEY])
    spec=json.loads((tmp_path/'comparison/job.json').read_text())
    work=tmp_path/'explain';work.mkdir()
    physical=explain_step(spec,step_name,native=native,work=work)
    join=next(line for line in physical.splitlines() if 'HashJoinExec:' in line)
    assert ('join_type=RightSemi' if step_name=='new_selected' else 'join_type=RightAnti') in join,physical
    # The first leaf below the join is the one-column explicit scope inventory.
    leaves=[line for line in physical.splitlines()[physical.splitlines().index(join)+1:]
            if 'DataSourceExec:' in line or 'StreamingTableExec:' in line]
    assert leaves and 'receipt_key' in leaves[0] and 'projection=[receipt_key]' in leaves[0],physical


@pytest.mark.parametrize('null_context',[False,True])
def test_secondary_comparison_plan_hashes_all_four_identity_keys(tmp_path,null_context):
    old,parts=batch_fixture(tmp_path)
    if null_context:
        for path in (old,*parts):
            table=pq.read_table(path)
            table=table.set_column(table.schema.get_field_index('context_url'),'context_url',
                pa.array([None]*table.num_rows,type=pa.string()))
            pq.write_table(table,path)
    old_rows=pq.read_table(old).to_pylist()
    old_rows.append(dict(old_rows[0],reference_kind='file',pointer_json='["secondary"]'))
    pq.write_table(pa.Table.from_pylist(old_rows,schema=pq.read_schema(old)),old)
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
        assert 'NullsEqual: true' in join,physical
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


def test_new_only_proof_builds_only_ordinal_and_source_line_keys(tmp_path):
    old,parts=batch_fixture(tmp_path)
    native=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    compare_old(parts,old,engine=native,work=tmp_path/'comparison')
    spec=json.loads((tmp_path/'comparison/job.json').read_text())
    work=tmp_path/'explain';work.mkdir()
    physical=explain_step(spec,'new_only_proof',native=native,work=work)
    lines=physical.splitlines()
    joins=[line for line in lines if 'HashJoinExec:' in line]
    assert len(joins)==2,physical
    assert all('join_type=Right' in line and 'filter=' not in line for line in joins),physical
    builds=[]
    for join in joins:
        leaves=[line for line in lines[lines.index(join)+1:]
                if 'DataSourceExec:' in line or 'StreamingTableExec:' in line]
        assert leaves,physical
        builds.append(leaves[0])
    assert any('projection=[old_source_key, old_source_line]' in line for line in builds),physical
    assert any('projection=[proof_receipt_key, proof_receipt_line, proof_record_index, source_ordinal_occurrences]'
               in line for line in builds),physical
