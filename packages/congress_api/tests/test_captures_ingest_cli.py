import json
import os
from pathlib import Path

import pyarrow.parquet as pq
import pytest

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
        '--table','archive.captures_v1','--create-table','--create-namespace',
        '--table-location',str(tmp_path/'data')])==0
    assert pq.read_metadata(work/'captures.parquet').num_rows==1
    assert json.loads((work/'append/result.json').read_text())['table_operations'][0]['files'][0]['rows']==1
    assert json.loads((work/'ingested-receipts.json').read_text())['receipt_keys']==[
        'receipts/documents/2026-10-20/run.jsonl.gz']


def test_cli_discovers_local_receipts_and_reuses_existing_namespace(tmp_path):
    from congress_api.cli.captures_ingest import main
    from congress_api.lake.tables import create_table
    from docspec_client.client import NativeDatasets
    engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    create_table(engine=engine,work=tmp_path/'bootstrap',catalog_root=tmp_path/'catalog',
        table=dict(namespace=['archive'],name='other'),
        schema={'type':'struct','schema-id':0,'fields':[
            {'id':1,'name':'id','required':True,'type':'string'}]},
        location=tmp_path/'other-data',create_namespace=True)
    [receipt]=files(tmp_path/'raw',[dict(run_id='new',mode='fetch',family='documents',
        requested_url='https://example.org/a',url='https://example.org/a',
        retrieved_at=STAMP,http_status=200,outcome='stored',captures=[body()])])
    target=tmp_path/'raw'/receipt['key']
    target.parent.mkdir(parents=True)
    Path(receipt['path']).rename(target)
    work=tmp_path/'stage'
    assert main(['--receipt-root',str(tmp_path/'raw'),'--receipt-family','documents',
        '--engine-config',os.environ['DOCSPEC_JOB_CONFIG'],'--work',str(work),
        '--apply','--catalog-root',str(tmp_path/'catalog'),'--table','archive.captures_v1',
        '--create-table','--table-location',str(tmp_path/'data')])==0
    assert pq.read_metadata(work/'captures.parquet').num_rows==1
    job=json.loads((work/'create/job.json').read_text())
    assert [op['kind'] for op in job['table_operations']]==['create']


def test_cli_skips_ingested_unreadable_receipts_before_compaction(tmp_path,capsys):
    import pyarrow as pa
    from congress_api.cli.captures_ingest import main
    key='receipts/documents/2026-10-20/a.gz'
    inventory=tmp_path/'inventory.json'
    inventory.write_text(json.dumps([dict(key=key,path='/does-not-exist/unopened.gz')]))
    prior=tmp_path/'existing.parquet'
    pq.write_table(pa.table({'receipt_key':[key]}),prior)
    work=tmp_path/'stage'
    assert main(['--receipt-inventory',str(inventory),'--existing',str(prior),
        '--engine-config',os.environ['DOCSPEC_JOB_CONFIG'],'--work',str(work)])==0
    summary=json.loads(capsys.readouterr().out)
    assert summary['no_work'] is True and summary['applied'] is False
    assert not work.exists()


@pytest.mark.parametrize('size',['0','1025','-1','1'])
def test_obsolete_receipt_batch_flag_is_refused_before_input_reads(tmp_path,size):
    from congress_api.cli.captures_ingest import main
    with pytest.raises(SystemExit) as error:
        main(['--receipt-inventory',str(tmp_path/'unopened.json'),
            '--engine-config',os.environ['DOCSPEC_JOB_CONFIG'],'--work',str(tmp_path/'work'),
            '--receipt-batch-size',size])
    assert error.value.code==2
