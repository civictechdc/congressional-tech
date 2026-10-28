"""Applied CLI retries select missing receipts from a fresh native table head."""
import json
import os
from pathlib import Path

import pytest

from test_captures_ingest import files,STAMP,body


def arguments(tmp_path,inventory,work):
    return ['--receipt-inventory',str(inventory),'--engine-config',os.environ['DOCSPEC_JOB_CONFIG'],
        '--work',str(work),'--apply','--catalog-root',str(tmp_path/'catalog'),
        '--table','archive.captures_v1']


@pytest.mark.parametrize('create',[False,True])
def test_existing_snapshot_is_staging_only_and_refuses_apply_before_any_effect(tmp_path,create,capsys):
    from congress_api.cli.captures_ingest import main
    def unopened(_):raise AssertionError('engine configured before argument refusal')
    argv=arguments(tmp_path,tmp_path/'absent-inventory.json',tmp_path/'stage')
    argv+=['--existing',str(tmp_path/'absent-existing.parquet'),
           '--source-qualifications',str(tmp_path/'absent-qualifications.json')]
    if create:argv+=['--create-table','--table-location',str(tmp_path/'data')]
    with pytest.raises(SystemExit) as error:main(argv,engine_factory=unopened)
    assert error.value.code==2 and '--existing' in capsys.readouterr().err
    assert not (tmp_path/'stage').exists() and not (tmp_path/'catalog').exists()


def test_apply_table_name_is_validated_before_configuration_or_inventory(tmp_path,capsys):
    from congress_api.cli.captures_ingest import main
    def unopened(_):raise AssertionError('engine configured before argument refusal')
    argv=arguments(tmp_path,tmp_path/'absent-inventory.json',tmp_path/'stage')
    argv[argv.index('archive.captures_v1')]='archive..captures'
    with pytest.raises(SystemExit) as error:main(argv,engine_factory=unopened)
    assert error.value.code==2 and '--table' in capsys.readouterr().err
    assert not (tmp_path/'stage').exists()


def test_existing_table_is_resolved_before_receipt_payload_admission(tmp_path):
    from congress_api.cli.captures_ingest import main
    inventory=tmp_path/'inventory.json'
    inventory.write_text(json.dumps([dict(key='receipts/documents/2026-10-20/a.gz',
        path='/unopened/absent-receipt.gz')]))
    jobs=[]
    class MissingNative:
        remote=None
        def run_job(self,path):
            jobs.append(json.loads(path.read_text()))
            return dict(table_operations=[dict(kind='resolve',name='captures',exists=False)])
    with pytest.raises(ValueError,match='captures table does not exist'):
        main(arguments(tmp_path,inventory,tmp_path/'stage'),engine_factory=lambda _:MissingNative())
    assert len(jobs)==1 and jobs[0]['table_operations']==[dict(kind='resolve',name='captures',
        table=dict(namespace=['archive'],name='captures_v1'))]
    assert not (tmp_path/'stage').exists() and not (tmp_path/'stage-inventory').exists()


def test_lost_append_ack_retry_skips_unavailable_raw_and_later_appends_only_new_receipts(tmp_path,capsys):
    from congress_api.cli.captures_ingest import main
    from congress_api.lake.tables import resolve_tables,table_input
    from congress_api.retention.provenance import run_job
    from docspec_client.client import NativeDatasets
    engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    one=files(tmp_path/'one',[dict(run_id='new',mode='fetch',family='documents',
        requested_url='https://example.org/one',url='https://example.org/one',
        retrieved_at=STAMP,http_status=200,outcome='stored',captures=[body()])])
    inventory=tmp_path/'inventory.json';inventory.write_text(json.dumps(one))
    class LostAppendAck:
        def __getattr__(self,name):return getattr(engine,name)
        def run_job(self,path):
            result=engine.run_job(path)
            if any(op['kind']=='append' for op in json.loads(path.read_text()).get('table_operations',[])):
                raise TimeoutError('native commit completed; acknowledgment lost')
            return result
    initial=arguments(tmp_path,inventory,tmp_path/'initial')+[
        '--create-table','--create-namespace','--table-location',str(tmp_path/'data')]
    with pytest.raises(TimeoutError,match='acknowledgment lost'):
        main(initial,engine_factory=lambda _:LostAppendAck())
    # Neither raw bytes nor the old qualification are available for a retry.
    Path(one[0]['path']).unlink();Path(one[0]['qualification']).unlink()
    retry=tmp_path/'retry'
    assert main(arguments(tmp_path,inventory,retry),engine_factory=lambda _:engine)==0
    summary=json.loads(capsys.readouterr().out)
    assert summary==dict(stage=None,applied=False,no_work=True,receipts=0,rows=0)
    assert not retry.exists() and not (retry/'append').exists()
    selection=json.loads((tmp_path/'retry-inventory/job.json').read_text())
    assert next(i for i in selection['inputs'] if i['name']=='existing')['kind']=='native_table'
    two=files(tmp_path/'two',[dict(run_id='second',mode='fetch',family='documents',
        requested_url='https://example.org/two',url='https://example.org/two',
        retrieved_at=STAMP,http_status=200,outcome='stored',captures=[body()])],
        key='receipts/documents/2026-10-21/two.jsonl.gz')
    inventory.write_text(json.dumps(one+two))
    qualifications=tmp_path/'qualifications.json'
    qualifications.write_text(json.dumps({row['path']:row['qualification'] for row in one+two}))
    delta=tmp_path/'delta'
    assert main(arguments(tmp_path,inventory,delta)+['--source-qualifications',str(qualifications)],
        engine_factory=lambda _:engine)==0
    assert json.loads((delta/'ingested-receipts.json').read_text())['receipt_keys']==[two[0]['key']]
    # Discovery uses the same fresh current pin for its native watermark query.
    discovery=tmp_path/'discovery'
    assert main(['--receipt-root',str(tmp_path/'empty-raw'),'--receipt-family','documents',
        '--engine-config',os.environ['DOCSPEC_JOB_CONFIG'],'--work',str(discovery),'--apply',
        '--catalog-root',str(tmp_path/'catalog'),'--table','archive.captures_v1'],engine_factory=lambda _:engine)==0
    prefixes=json.loads((tmp_path/'discovery-inventory/prefixes/job.json').read_text())
    assert next(i for i in prefixes['inputs'] if i['name']=='existing')['kind']=='native_table'
    pin=resolve_tables(engine=engine,work=tmp_path/'proof-head',catalog_root=tmp_path/'catalog',
        tables={'captures':dict(namespace=['archive'],name='captures_v1')})['captures']
    proof=tmp_path/'proof';proof.mkdir()
    result=run_job(proof,engine,inputs=[table_input('captures',pin)],steps=[],outputs=[],queries=[
        dict(name='rows',sql='SELECT count(*) AS n FROM captures'),
        dict(name='keys',sql='''SELECT count(*) AS n FROM (SELECT receipt_key,receipt_line,capture_index
            FROM captures GROUP BY receipt_key,receipt_line,capture_index)''')])
    assert result==dict(rows=[dict(n=2)],keys=[dict(n=2)])


def test_new_table_keeps_payload_admission_before_creation(tmp_path):
    from congress_api.cli.captures_ingest import main
    inventory=tmp_path/'inventory.json'
    inventory.write_text(json.dumps([dict(key='receipts/documents/2026-10-20/a.gz',
        path='/unopened/absent-receipt.gz')]))
    with pytest.raises(FileNotFoundError):
        main(arguments(tmp_path,inventory,tmp_path/'stage')+[
            '--create-table','--create-namespace','--table-location',str(tmp_path/'data')])
    assert not (tmp_path/'stage/create').exists() and not (tmp_path/'catalog').exists()
    assert not (tmp_path/'stage-current').exists()
