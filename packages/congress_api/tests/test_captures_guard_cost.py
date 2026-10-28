"""The production item guard compares wide facts only for repeated item keys."""
import json
import os

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from docspec_client.client import NativeDatasets

from congress_api.lake.captures import COLUMNS,capture_checks
from congress_api.retention.provenance import run_job


@pytest.mark.parametrize('conflict',['none','same_ordinal_different_primary_count','null_key'])
def test_saved_production_item_guard_prefilters_duplicate_three_key_groups(tmp_path,conflict):
    integers={'receipt_line','capture_index','bytes','stored_bytes','http_status','list_ordinal','primary_count'}
    booleans={'complete','intact','is_secondary'}
    binaries={'sha256','evidence_sha256'}
    names=[*COLUMNS,'reference_kind','is_secondary','list_ordinal','primary_count']
    schema=pa.schema([(name,pa.int64() if name in integers else pa.bool_() if name in booleans else
        pa.binary(32) if name in binaries else pa.timestamp('ns','UTC') if name in {'retrieved_at','imported_at'}
        else pa.string()) for name in names])
    def item(line,*,ordinal=0,index=0,primary=0,url='same',key='receipts/documents/2026-10-28/guard.gz',**changes):
        return dict(receipt_key=key,receipt_line=line,capture_index=index,reference_kind='line',
            is_secondary=False,list_ordinal=ordinal,primary_count=primary,url='https://fixture.test/'+url,**changes)
    rows=[item(line) for line in range(1,513)]
    rows += [item(513,index=2,primary=2),item(513,index=9,primary=9)]
    rows += [item(514,ordinal=1,index=3,primary=2),item(514,ordinal=1,index=8,primary=7,
        url='changed' if conflict=='same_ordinal_different_primary_count' else 'same')]
    rows += [item(515,index=0,key=None),item(515,index=1,key=None,
        url='changed' if conflict=='null_key' else 'same')]
    # Neither body-reference facts nor secondary storage rows are list-item facts.
    for changes in (dict(reference_kind='capture'),dict(is_secondary=True)):
        excluded=item(513,index=11,url='excluded-matching-key');excluded.update(changes);rows.append(excluded)
    for line,changes in [(516,dict(reference_kind='capture')),(517,dict(is_secondary=True))]:
        a=item(line);b=item(line,index=1,url='excluded-change');a.update(changes);b.update(changes);rows += [a,b]
    source=tmp_path/'scalar-rows.parquet';pq.write_table(pa.Table.from_pylist(rows,schema=schema),source)
    sql=next(check['sql'] for check in capture_checks() if check['name']=='list_facts')
    result=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
        inputs=[dict(name='scalar_rows',kind='parquet',path=str(source))],steps=[],outputs=[],
        queries=[dict(name='violations',sql=sql),dict(name='plan',sql='EXPLAIN '+sql)])
    assert json.loads((tmp_path/'job.json').read_text())['queries'][0]['sql']==sql
    expected=[] if conflict=='none' else [dict(receipt_key=None if conflict=='null_key' else rows[0]['receipt_key'],
        receipt_line=515 if conflict=='null_key' else 514,reason='list record conflicting facts')]
    assert result['violations']==expected
    physical=next(row['plan'] for row in result['plan'] if row['plan_type']=='physical_plan')
    # This source has no joins of its own: a native duplicate-key prefilter must
    # restrict the wide comparison rather than grouping every singleton's facts.
    assert 'JoinExec' in physical
