"""S1's expected groups precede the model's native graph SQL."""
import json
import os
from pathlib import Path

import pytest
from congress_api.retention.provenance import json_input,run_job
from docspec_client.client import NativeDatasets

ROOT=Path(__file__).parents[3]
CASES=json.loads((ROOT/'model/fixtures/s1-model-cases.json').read_text())['groups']


@pytest.mark.parametrize('case',CASES,ids=lambda x:x['id'])
def test_native_model_groups_preserve_editions_and_publisher_context(case,tmp_path):
    from viewer_publication.archive_model import grouping_steps,registry_inputs
    files=[dict(x,body_sha=x['body_sha'],directory_key=x['directory']) for x in case['files']]
    inputs=registry_inputs(tmp_path/'registries')
    inputs.append(json_input(tmp_path,'source_files',files,source_id='Utf8',body_sha='Utf8',
        format='Utf8',directory_key='Utf8',stem='Utf8',is_real_file='Boolean'))
    inputs.append(json_input(tmp_path,'source_directories',files+case.get('extra_directories',[]),source_id='Utf8',directory_key='Utf8',stem='Utf8'))
    inputs.append(json_input(tmp_path,'source_endpoints',[dict(x,endpoint_key=x['context_url']) for x in files],source_id='Utf8',body_sha='Utf8',
        endpoint_key='Utf8',member_path='Utf8'))
    inputs.append(json_input(tmp_path,'body_fingerprints',files,body_sha='Utf8',fingerprint='Utf8'))
    inputs.append(json_input(tmp_path,'publisher_links',case.get('publisher_links',[]),
        source_id='Utf8',page_body='Utf8',context='Utf8',group_path='Utf8'))
    result=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=grouping_steps(),outputs=[],queries=[
            dict(name='members',sql='SELECT s.source_id,m.component FROM source_files s JOIN source_labels m USING(source_id) WHERE s.is_real_file ORDER BY s.source_id'),
            dict(name='editions',sql='SELECT body_sha FROM edition_bodies ORDER BY body_sha'),
            dict(name='renditions',sql='SELECT DISTINCT group_id FROM valid_rendition_members ORDER BY group_id')])
    components={}
    for row in result['members']:components.setdefault(row['component'],[]).append(row['source_id'])
    assert sorted(sorted(x) for x in components.values())==sorted(sorted(x) for x in case['expected']['components'])
    if 'edition_bodies' in case['expected']:
        assert [x['body_sha'] for x in result['editions']]==sorted(case['expected']['edition_bodies'])
    if case['expected'].get('rendition_groups')==[]:assert result['renditions']==[]
