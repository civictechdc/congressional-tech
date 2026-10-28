"""Nullable grouping keys must remain native hash keys, with original null semantics."""
import os
from pathlib import Path

import pytest

from congress_api.retention.provenance import json_input,run_job
from docspec_client.client import NativeDatasets

ROOT=Path(__file__).parents[3]


@pytest.mark.parametrize('name',['fingerprint-candidates','document-version-keys','edition-bodies'])
def test_endpoint_member_joins_hash_every_key_without_matching_missing_endpoints(tmp_path,name):
    rows=[dict(source_id='s'+str(i),endpoint_key=endpoint,member_path=member,body_sha=body)
        for i,(endpoint,member,body) in enumerate([
            ('endpoint',None,'a'),('endpoint',None,'b'),('endpoint','','c'),
            ('endpoint','member','d'),(None,None,'e'),(None,None,'f')])]
    inputs=[json_input(tmp_path,'endpoint_bodies',rows,source_id='Utf8',endpoint_key='Utf8',member_path='Utf8',body_sha='Utf8'),
        json_input(tmp_path,'ambiguous_endpoints',[dict(endpoint_key='endpoint',member_path=None),
            dict(endpoint_key=None,member_path=None)],endpoint_key='Utf8',member_path='Utf8'),
        json_input(tmp_path,'fingerprint_candidates',[dict(body_sha=body) for body in ['a','b']],body_sha='Utf8'),
        json_input(tmp_path,'fingerprints',[dict(body_sha=body,fingerprint='same') for body in ['a','b']],body_sha='Utf8',fingerprint='Utf8')]
    sql=(ROOT/'model/sql'/(name+'.sql')).read_text()
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        result=run_job(tmp_path,engine,inputs=inputs,steps=[],outputs=[],queries=[
            dict(name='actual',sql=sql),dict(name='plan',sql='EXPLAIN '+sql)])
    if name=='document-version-keys':assert sorted(row['source_id'] for row in result['actual'])==['s0','s1']
    else:assert sorted(row['body_sha'] for row in result['actual'])==['a','b']
    physical=next(row['plan'] for row in result['plan'] if row['plan_type']=='physical_plan')
    joins=[line for line in physical.splitlines() if 'HashJoinExec' in line and 'endpoint_key' in line]
    assert joins,physical
    for join in joins:
        assert 'member_path' in join.split('filter=')[0],physical
        assert 'filter=' not in join,physical
