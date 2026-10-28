"""An accepted direct-receipt stage uses the same fresh-head native append path."""
import json
import os
from pathlib import Path
import shutil

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from test_captures_ingest import files,STAMP,body


@pytest.fixture(scope='module')
def accepted(tmp_path_factory):
    from congress_api.lake.captures import stage_captures
    from docspec_client.client import NativeDatasets
    root=tmp_path_factory.mktemp('accepted-direct-stage')
    records=[]
    for number in range(2):
        records+=files(root/str(number),[dict(run_id='accepted-'+str(number),mode='fetch',family='documents',
            requested_url='https://example.org/'+str(number),url='https://example.org/'+str(number),
            retrieved_at=STAMP,http_status=200,outcome='stored',captures=[body()])],
            key=f'receipts/documents/2026-10-20/{number}.jsonl.gz')
    engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    stage=stage_captures(records,engine=engine,work=root/'stage')
    for row in records:
        Path(row['path']).unlink();Path(row['qualification']).unlink()
    return stage,[r['key'] for r in records]


def setup(tmp_path,accepted):
    original,keys=accepted
    stage=tmp_path/'accepted';shutil.copytree(original,stage)
    inventory=tmp_path/'inventory.json';inventory.write_text(json.dumps(keys))
    argv=['--append-stage',str(stage),'--receipt-inventory',str(inventory),
        '--engine-config',os.environ['DOCSPEC_JOB_CONFIG'],'--work',str(tmp_path/'work'),
        '--apply','--catalog-root',str(tmp_path/'catalog'),'--table','archive.captures_v1',
        '--create-table','--create-namespace','--table-location',str(tmp_path/'data')]
    return stage,inventory,argv


@pytest.mark.parametrize('change',[
    'sha','size','mapping','version','counter','keys','missing-job','job-drift','native-keys','native-pk',
])
def test_invalid_accepted_stage_refuses_before_table_creation(tmp_path,accepted,change):
    from congress_api.cli.captures_ingest import main
    from congress_api.retention.provenance import file_pin
    stage,_,argv=setup(tmp_path,accepted)
    path=stage/'ingested-receipts.json';manifest=json.loads(path.read_text())
    output=next(o for o in manifest['outputs'] if o['name']=='captures')
    if change=='sha':output['sha256']='0'*64
    if change=='size':output['size']+=1
    if change=='mapping':manifest['mapping_digest']='0'*64
    if change=='version':manifest['version']=1
    if change=='counter':manifest['input']['kind']='validated-counter'
    if change=='keys':manifest['receipt_keys']=manifest['receipt_keys'][:1]
    if change=='missing-job':del manifest['input']['job']
    if change=='job-drift':(stage/'job.json').write_bytes((stage/'job.json').read_bytes()+b' ')
    if change in {'native-keys','native-pk'}:
        table=pq.read_table(stage/'captures.parquet')
        if change=='native-keys':
            table=table.set_column(table.schema.get_field_index('receipt_key'),'receipt_key',
                pa.array(['receipts/documents/2026-10-20/other.jsonl.gz']*table.num_rows))
        else:table=pa.concat_tables([table,table.slice(0,1)])
        pq.write_table(table,stage/'captures.parquet')
        output.update(file_pin(stage/'captures.parquet'),rows=table.num_rows)
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):main(argv)
    assert not (tmp_path/'catalog').exists() and not (tmp_path/'work/create').exists()
    assert not (tmp_path/'work/append').exists()


@pytest.mark.parametrize('extra',[
    ['--validated-counter','/unopened/counter.parquet'],
    ['--receipt-root','/unopened/raw'],
    ['--receipt-family','documents'],
    ['--source-qualifications','/unopened/qualifications.json'],
])
def test_append_stage_conflicting_source_flags_refuse_before_configuration(tmp_path,extra):
    from congress_api.cli.captures_ingest import main
    def unopened(_):raise AssertionError('Engine configured before flag refusal')
    with pytest.raises(SystemExit) as error:
        main(['--append-stage','/unopened/stage','--receipt-inventory','/unopened/inventory.json',
            '--engine-config',os.environ['DOCSPEC_JOB_CONFIG'],'--work',str(tmp_path/'work'),
            '--apply','--catalog-root',str(tmp_path/'catalog'),'--table','archive.captures_v1',*extra],
            engine_factory=unopened)
    assert error.value.code==2 and not (tmp_path/'work').exists()


@pytest.mark.parametrize('missing',['apply','inventory'])
def test_append_stage_requires_apply_and_batch_inventory_before_configuration(tmp_path,missing):
    from congress_api.cli.captures_ingest import main
    def unopened(_):raise AssertionError('Engine configured before flag refusal')
    argv=['--append-stage','/unopened/stage','--engine-config',os.environ['DOCSPEC_JOB_CONFIG'],
        '--work',str(tmp_path/'work'),'--catalog-root',str(tmp_path/'catalog'),'--table','archive.captures_v1']
    argv+=(['--receipt-inventory','/unopened/inventory.json'] if missing=='apply' else ['--apply'])
    with pytest.raises(SystemExit) as error:main(argv,engine_factory=unopened)
    assert error.value.code==2 and not (tmp_path/'work').exists()


def test_accepted_stage_append_survives_lost_ack_then_skips_a_missing_artifact(tmp_path,accepted,capsys):
    from congress_api.cli.captures_ingest import main
    from docspec_client.client import NativeDatasets
    stage,inventory,argv=setup(tmp_path,accepted)
    engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    class LostAck:
        def __getattr__(self,name):return getattr(engine,name)
        def run_job(self,path):
            result=engine.run_job(path)
            if any(op['kind']=='append' for op in json.loads(path.read_text()).get('table_operations',[])):
                raise TimeoutError('append committed; lost acknowledgment')
            return result
    before={p.name:p.read_bytes() for p in stage.iterdir() if p.is_file()}
    with pytest.raises(TimeoutError,match='lost acknowledgment'):
        main(argv,engine_factory=lambda _:LostAck())
    assert {p.name:p.read_bytes() for p in stage.iterdir() if p.is_file()}==before
    assert (tmp_path/'work/append/job.json').is_file()
    shutil.rmtree(stage)
    assert main(['--append-stage',str(stage),'--receipt-inventory',str(inventory),
        '--engine-config',os.environ['DOCSPEC_JOB_CONFIG'],'--work',str(tmp_path/'retry'),
        '--apply','--catalog-root',str(tmp_path/'catalog'),'--table','archive.captures_v1'])==0
    assert json.loads(capsys.readouterr().out)==dict(stage=None,applied=False,no_work=True,receipts=0)
    assert not stage.exists() and not (tmp_path/'retry').exists()


def test_stage_batch_identity_includes_committed_keys_and_append_filters_them(tmp_path,accepted):
    from congress_api.cli.captures_ingest import main
    from congress_api.lake.tables import append_rows,create_table,resolve_tables,table_input
    from congress_api.lake.captures import current_version
    from congress_api.retention.provenance import run_job
    from docspec_client.client import NativeDatasets
    stage,_,argv=setup(tmp_path,accepted);engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    table=dict(namespace=['archive'],name='captures_v1')
    schema=json.loads((Path(__file__).resolve().parents[3]/'model/lake/captures.schema.json').read_text())
    create_table(engine=engine,work=tmp_path/'bootstrap',catalog_root=tmp_path/'catalog',table=table,
        schema=schema,location=tmp_path/'data',create_namespace=True)
    first=tmp_path/'first.parquet';pq.write_table(pq.read_table(stage/'captures.parquet').slice(0,1),first)
    append_rows(first,engine=engine,work=tmp_path/'first-append',catalog_root=tmp_path/'catalog',
        table=table,keys=['receipt_key'],definition=current_version())
    argv=argv[:argv.index('--create-table')]
    assert main(argv)==0
    appended=json.loads((tmp_path/'work/append/result.json').read_text())['table_operations'][0]
    assert sum(f['rows'] for f in appended['files'])==1
    pin=resolve_tables(engine=engine,work=tmp_path/'head',catalog_root=tmp_path/'catalog',tables={'captures':table})['captures']
    proof=tmp_path/'proof';proof.mkdir()
    assert run_job(proof,engine,inputs=[table_input('captures',pin)],steps=[],outputs=[],
        queries=[dict(name='rows',sql='SELECT count(*) AS n FROM captures')])==dict(rows=[dict(n=2)])
