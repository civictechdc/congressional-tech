"""D1/D3 forward one catalog authority to native declarative jobs."""
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from docspec_client.client import NativeDatasets


class RecordingEngine:
    """External catalog adapter: local SQL executes; table writes are recorded."""
    def __init__(self,*,remote=True,native=None):
        self.remote=Path('/fixture/remote.json') if remote else None
        self.native=native
        self.source_revision=native.source_revision if native else 'fixture-revision'
        self.binary_sha256=native.binary_sha256 if native else 'a'*64
        self.jobs=[]

    def run_job(self,path):
        job=json.loads(Path(path).read_text())
        if not job.get('table_operations'):
            assert self.native is not None
            return self.native.run_job(path)
        self.jobs.append(job)
        return {'table_operations':[dict(name=op['name'],files=[])
                                    for op in job['table_operations']]}


def test_remote_create_and_append_preserve_native_jobs_and_uri(tmp_path):
    from congress_api.lake.tables import create_table,append_rows
    engine=RecordingEngine()
    table=dict(namespace=['archive'],name='body_readings_v1')
    schema={'type':'struct','schema-id':0,'fields':[
        {'id':1,'name':'body_sha','required':True,'type':'fixed[32]'}]}
    uri='s3://fixture-lake/tables/body_readings_v1/'
    create_table(engine=engine,work=tmp_path/'create',catalog_root=None,table=table,
                 schema=schema,location=uri,create_namespace=True)
    source=tmp_path/'incoming.parquet'
    pq.write_table(pa.table({'body_sha':pa.array([b'a'*32],type=pa.binary(32))}),source)
    append_rows(source,engine=engine,work=tmp_path/'append',catalog_root=None,
                table=table,keys=['body_sha'],definition='reader-v1')
    create,append=engine.jobs
    assert 'catalog_root' not in create and 'catalog_root' not in append
    assert create['table_operations'][1]['location']==uri
    assert create['table_operations'][1]['schema']==schema
    operation=append['table_operations'][0]
    assert operation['kind']=='append' and operation['table']==table
    assert 'LEFT ANTI JOIN existing' in operation['sql']
    assert "encode(cast(\"body_sha\" AS BYTEA),'hex')" in operation['identity_sql']
    assert append['inputs']==[dict(name='incoming',kind='parquet',path=str(source))]


@pytest.mark.parametrize('remote,root',[(False,None),(True,'local-catalog')])
def test_table_binding_rejects_missing_or_ambiguous_authority_before_work(tmp_path,remote,root):
    from congress_api.lake.tables import create_table,append_rows
    engine=RecordingEngine(remote=remote)
    with pytest.raises(ValueError,match='catalog'):
        create_table(engine=engine,work=tmp_path/'refused',catalog_root=root,
            table=dict(namespace=['archive'],name='captures'),schema={},location='s3://fixture/table')
    assert not (tmp_path/'refused').exists() and engine.jobs==[]
    with pytest.raises(ValueError,match='catalog'):
        append_rows(tmp_path/'unopened.parquet',engine=engine,work=tmp_path/'refused-append',
            catalog_root=root,table=dict(namespace=['archive'],name='captures'),
            keys=['receipt_key'],definition='fixture')
    assert not (tmp_path/'refused-append').exists() and engine.jobs==[]


def test_local_binding_still_normalizes_host_paths(tmp_path):
    from congress_api.lake.tables import create_table
    engine=RecordingEngine(remote=False)
    root=tmp_path/'a/../catalog';location=tmp_path/'b/../data'
    create_table(engine=engine,work=tmp_path/'create',catalog_root=root,
        table=dict(namespace=['archive'],name='captures'),schema={},location=location)
    [job]=engine.jobs
    assert job['catalog_root']==str(root.resolve())
    assert job['table_operations'][0]['location']==str(location.resolve())


@pytest.mark.parametrize('producer',['captures','filenames'])
@pytest.mark.parametrize('remote,with_root',[(False,False),(True,True)])
def test_cli_refuses_authority_before_opening_inputs(tmp_path,producer,remote,with_root):
    engine=RecordingEngine(remote=remote)
    args=['--engine-config','/fixture/not-opened.json','--work',str(tmp_path/'refused'),
          '--apply','--table','archive.table_v1']
    if with_root:
        args+=['--catalog-root',str(tmp_path/'catalog')]
    if producer=='captures':
        from congress_api.cli.captures_ingest import main
        args+=['--receipt-inventory','/does-not-exist/inventory.json']
    else:
        from congress_api.lake.filenames import main
        args+=['--captures','/does-not-exist/captures.parquet',
               '--recovery-inventory','/does-not-exist/recoveries.json',
               '--decided-at','2026-10-27T18:00:00Z']
    with pytest.raises(SystemExit) as error:
        main(args,engine_factory=lambda _:engine)
    assert error.value.code==2
    assert not (tmp_path/'refused').exists() and engine.jobs==[]


def test_capture_cli_remote_apply_uses_real_local_stage_and_recorded_table_writes(tmp_path):
    from congress_api.cli.captures_ingest import main
    from test_captures_ingest import files,STAMP,body
    engine=RecordingEngine(native=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']))
    inventory=tmp_path/'inventory.json'
    inventory.write_text(json.dumps(files(tmp_path/'raw',[dict(mode='fetch',family='documents',
        requested_url='https://example.org/a',url='https://example.org/a',
        retrieved_at=STAMP,http_status=200,outcome='stored',captures=[body()])])))
    uri='s3://fixture-lake/tables/captures_v1/'
    assert main(['--receipt-inventory',str(inventory),'--engine-config','/fixture/not-opened.json',
        '--work',str(tmp_path/'stage'),'--apply','--table','archive.captures_v1',
        '--create-table','--table-location',uri],engine_factory=lambda _:engine)==0
    assert len(engine.jobs)==2
    assert all('catalog_root' not in job for job in engine.jobs)
    assert engine.jobs[0]['table_operations'][0]['location']==uri
    assert pq.read_metadata(tmp_path/'stage/captures.parquet').num_rows==1


def test_filename_cli_remote_apply_reuses_one_client_and_preserves_partition(tmp_path):
    from congress_api.lake import filenames
    from test_filename_readings import input_tables,Worker,STAMP
    engine=RecordingEngine(native=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']))
    captures=input_tables(tmp_path,[dict(receipt_key='r',receipt_line=1,capture_index=0,mode='fetch',
        url='https://example.org/BILLS-119hr6028ih.pdf')])
    inventory=tmp_path/'recoveries.json';inventory.write_text('[]')
    calls=[]
    def factory(path):
        calls.append(path)
        return engine
    uri='s3://fixture-lake/tables/filename_readings_v1/'
    assert filenames.main(['--captures',str(captures),'--recovery-inventory',str(inventory),
        '--engine-config','/fixture/not-opened.json','--decided-at',STAMP,
        '--work',str(tmp_path/'stage'),'--apply','--table','archive.filename_readings_v1',
        '--create-table','--table-location',uri],worker_factory=Worker,engine_factory=factory)==0
    assert len(calls)==1 and len(engine.jobs)==2
    assert all('catalog_root' not in job for job in engine.jobs)
    create=engine.jobs[0]['table_operations'][0]
    assert create['location']==uri and create['partition_spec']==filenames.PARTITION_SPEC
    assert pq.read_metadata(tmp_path/'stage/filename-readings.parquet').num_rows==1
