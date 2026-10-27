"""Application ID formulas run in the engine against independent golden bytes."""
import json
import os
from pathlib import Path

from congress_api.retention.provenance import json_input, list_of, run_job
from docspec_client.client import NativeDatasets

ROOT=Path(__file__).parents[3]


def test_native_source_and_document_ids_match_all_golden_vectors(tmp_path):
    fixture=json.loads((ROOT/'model/fixtures/id-golden-vectors.json').read_text())
    sources=[dict(case_id=r['name'],**r['inputs']) for r in fixture['source_ids']]
    documents=[dict(case_id=r['name'],**r['inputs']) for r in fixture['document_ids']]
    inputs=[json_input(tmp_path,'sources',sources,case_id='Utf8',body_key='Utf8',filename='Utf8',source_url='Utf8'),
        json_input(tmp_path,'documents',documents,case_id='Utf8',bodies=list_of('Utf8'),source_ids=list_of('Utf8'))]
    result=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=[dict(name='source_json',sql='SELECT case_id,json_array(body_key,filename,source_url) AS bytes FROM sources'),
        dict(name='document_json',sql="""SELECT case_id,CASE WHEN array_length(bodies)>0
            THEN json_array('bodies',array_sort(array_distinct(bodies)))
            ELSE json_array('sources',array_sort(array_distinct(source_ids))) END AS bytes FROM documents""")],
        outputs=[],queries=[dict(name=name,sql=f"SELECT case_id,bytes,encode(sha256(bytes),'hex') AS hex FROM {relation} ORDER BY case_id")
                            for name,relation in [('source_ids','source_json'),('document_ids','document_json')]])
    for name in ('source_ids','document_ids'):
        assert result[name]==[dict(case_id=r['name'],bytes=r['compact_json'],hex=r['expected_hex'])
                              for r in sorted(fixture[name],key=lambda r:r['name'])]
