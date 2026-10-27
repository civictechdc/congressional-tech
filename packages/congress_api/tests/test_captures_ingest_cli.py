import json
import os

import pyarrow.parquet as pq

from test_captures_ingest import files, STAMP, body


def test_local_ingest_cli_stage_and_explicit_append(tmp_path):
    from congress_api.cli.captures_ingest import main
    inventory=tmp_path/'inventory.json'
    inventory.write_text(json.dumps(files(tmp_path/'raw',[dict(run_id='new',mode='fetch',
        family='documents',requested_url='https://example.org/a',url='https://example.org/a',
        retrieved_at=STAMP,http_status=200,outcome='stored',captures=[body()])])) )
    work=tmp_path/'stage'
    assert main(['--receipt-inventory',str(inventory),'--engine-config',os.environ['DOCSPEC_JOB_CONFIG'],
        '--work',str(work),'--apply','--catalog-root',str(tmp_path/'catalog'),
        '--table','archive.captures_v1','--create-table','--table-location',str(tmp_path/'data')])==0
    assert pq.read_metadata(work/'captures.parquet').num_rows==1
    assert json.loads((work/'append/result.json').read_text())['table_operations'][0]['files'][0]['rows']==1
    assert json.loads((work/'ingested-receipts.json').read_text())['receipt_keys']==[
        'receipts/documents/2026-10-20/run.jsonl.gz']
