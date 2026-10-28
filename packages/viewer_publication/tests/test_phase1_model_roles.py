"""Existing S1 role outcomes bind the production policy before model assembly."""
import json
import os
from pathlib import Path

from congress_api.retention.provenance import json_input,run_job
from docspec_client.client import NativeDatasets

ROOT=Path(__file__).parents[3]


def test_s1_role_cases_use_production_registries(tmp_path):
    from viewer_publication.archive_model import registry_inputs
    cases=json.loads((ROOT/'model/fixtures/s1-model-cases.json').read_text())['roles']
    rows=[dict(c['input'],id=c['id']) for c in cases]
    fields=dict(id='Utf8',mode='Utf8',outcome='Utf8',http_status='Int32',complete='Boolean',
        sha256='Utf8',bytes='Int64',context_url='Utf8',url='Utf8',member_path='Utf8',format='Utf8',
        intact='Boolean',intact_basis='Utf8',error_type='Utf8',reading_status='Utf8',xml_root='Utf8',
        title='Utf8',heading='Utf8',text_head='Utf8',text_bytes='Int64',link_count='Int64',link_text_bytes='Int64')
    inputs=registry_inputs(tmp_path/'registries')
    inputs.append(json_input(tmp_path,'cases',rows,**fields))
    steps=[dict(name='capture_evidence',sql="""SELECT id AS receipt_key,cast(1 AS INT) AS receipt_line,
        cast(0 AS INT) AS capture_index,sha256,format,coalesce(intact_basis,'unchecked') AS intact_basis,
        intact,error_type,mode,outcome,http_status,complete,bytes,url,context_url,member_path FROM cases"""),
        dict(name='captures',sql='SELECT * FROM capture_evidence'),
        dict(name='capture_locators',sql='SELECT DISTINCT url,member_path FROM cases'),
        dict(name='page_facts',sql="""SELECT sha256 AS body_sha,reading_status AS status,xml_root,title,heading,
            text_head,text_bytes,link_count,link_text_bytes FROM cases WHERE sha256 IS NOT NULL""")]
    for name in ['body-signals','locator-signals','placeholders','record-roles']:
        steps.append(dict(name=name.replace('-','_'),sql=(ROOT/'model/sql'/(name+'.sql')).read_text(),materialize=True))
    result=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,steps=steps,outputs=[],
        queries=[dict(name='roles',sql='SELECT receipt_key AS id,record_role,is_real_file AS real_file FROM record_roles ORDER BY receipt_key')])
    assert result['roles']==[dict(id=c['id'],**c['expected']) for c in sorted(cases,key=lambda x:x['id'])]
