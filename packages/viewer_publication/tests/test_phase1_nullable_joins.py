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
        assert 'NullsEqual: true' in join,physical
    lines=physical.splitlines()
    index=next(i for i,line in enumerate(lines) if 'HashJoinExec' in line and 'endpoint_key' in line)
    first=index+1;depth=len(lines[first])-len(lines[first].lstrip())
    end=next((i for i in range(first+1,len(lines)) if len(lines[i])-len(lines[i].lstrip())<=depth),len(lines))
    build='\n'.join(lines[first:end])
    if name=='fingerprint-candidates':
        assert 'AggregateExec' in build,physical
    else:
        assert 'projection=[endpoint_key, member_path]' in build,physical


def test_adjacent_link_join_keeps_null_context_keys_in_hash_plan(tmp_path):
    from viewer_publication.archive_model import registry_inputs,link_steps
    rows=[dict(id=label,page_body='body',context_url='https://fixture.test/page',
        member_path=member,base_href=None,href='https://fixture.test/report.pdf',
        link_index=0,text='Report',group_path=None,doc_type=None,add_date=None,
        publish_date=None,remove_date=None) for label,member in [('null',None),('empty','')]]
    inputs=registry_inputs(tmp_path/'registries')
    inputs.append(json_input(tmp_path,'link_inputs',rows,**{name:'Utf8' for name in rows[0] if name!='link_index'},link_index='Int64'))
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        result=run_job(tmp_path,engine,inputs=inputs,steps=link_steps(),outputs=[],queries=[
            dict(name='actual',sql='SELECT id FROM resolved_links ORDER BY id'),
            dict(name='plan',sql='EXPLAIN '+(ROOT/'model/sql/link-targets.sql').read_text())])
    assert result['actual']==[{'id':'empty'},{'id':'null'}]
    physical=next(row['plan'] for row in result['plan'] if row['plan_type']=='physical_plan')
    context=next(line for line in physical.splitlines() if 'HashJoinExec' in line and 'page_body' in line)
    assert all(name in context for name in ['page_body','context_url','member_path','base_href']),physical
    assert 'NullsEqual: true' in context and 'filter=' not in context,physical
