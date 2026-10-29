"""Daily admission precedes raw I/O; backfills stream one native work list."""
import hashlib
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.lake import readings
from congress_api.retention.body_store import BodyStore, LocalAdapter
from congress_api.retention.parser_worker import ParserWorker
from docspec_client.client import NativeDatasets

STAMP='2026-10-28T12:00:00Z'


def inputs(root,count=3):
    root.mkdir();raw=root/'raw';raw.mkdir()
    captures=[];inventory=[]
    for i in range(count):
        data=json.dumps(dict(url='https://fixture.test/'+str(i),padding='x'*100)).encode()
        digest=hashlib.sha256(data).digest();key='bodies/sha256/'+digest.hex()[:2]+'/'+digest.hex()
        path=raw/key;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        captures.append(dict(sha256=digest,bytes=len(data),media_type='application/json',fidelity='exact-bytes'))
        inventory.append(dict(body_sha=digest,physical_key=key,relative_path=key,stored_bytes=len(data),stored_gzip=False))
    cap=root/'captures.parquet';inv=root/'inventory.parquet'
    pq.write_table(pa.Table.from_pylist(captures,schema=pa.schema([('sha256',pa.binary(32)),('bytes',pa.int64()),
        ('media_type',pa.string()),('fidelity',pa.string()),('sniffed_format',pa.string()),
        ('sniff_version',pa.string()),('intact',pa.bool_())])),cap)
    pq.write_table(pa.Table.from_pylist(inventory,schema=pa.schema([('body_sha',pa.binary(32)),
        ('physical_key',pa.string()),('relative_path',pa.string()),('stored_bytes',pa.int64()),('stored_gzip',pa.bool_())])),inv)
    return dict(captures=cap,body_inventory=inv,local_root=raw,decided_at=STAMP,
        engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']))


@contextmanager
def forbid_body_reads(root):
    active=True
    def audit(event,args):
        if active and event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
            path=Path(os.fsdecode(args[0])).absolute()
            if path.is_relative_to(root):raise AssertionError('body opened before admission')
    sys.addaudithook(audit)
    try:yield
    finally:active=False


class NeverWorker:
    def __init__(self,*args,**kwargs):raise AssertionError('worker before admission')


@pytest.mark.parametrize('parser',[None,'sniff'])
def test_daily_budget_refuses_before_worker_or_body_access(tmp_path,parser):
    args=inputs(tmp_path/'source')
    with forbid_body_reads(args['local_root']), pytest.raises(readings.BackfillRequired) as error:
        readings.stage(**args,work=tmp_path/'stage',parser=parser,max_work_items=2,worker_factory=NeverWorker)
    report=error.value.as_dict()
    assert report['status']=='backfill_required' and report['work_items']==3 and report['max_work_items']==2
    assert report['parser']==('readings' if parser is None else parser)
    assert pq.ParquetFile(report['work_list']).metadata.num_rows==3
    assert not (tmp_path/'stage/parsed').exists() and not (tmp_path/'stage/body-bytes').exists()
    job=json.loads((tmp_path/'stage/job.json').read_text())
    assert len([s for s in job['steps'] if s['name']=='pending_bodies' and s.get('materialize')])==1


@pytest.mark.parametrize('value',[True,False,0,-1,1.5,'2'])
def test_invalid_explicit_budget_refuses_before_work(tmp_path,value):
    with pytest.raises(ValueError,match='positive integer'):
        readings.stage(captures='missing',body_inventory='missing',local_root='missing',engine=object(),
            work=tmp_path/'work',decided_at=STAMP,parser=None,max_work_items=value)
    assert not (tmp_path/'work').exists()


def test_plan_materializes_work_once_without_worker_or_raw_access(tmp_path):
    args=inputs(tmp_path/'source')
    with forbid_body_reads(args['local_root']):
        result=readings.plan(**args,work=tmp_path/'plan',parser=None,max_work_items=3)
    assert result['work_items']==3 and result['status']=='planned'
    assert not (tmp_path/'plan/parsed').exists() and not (tmp_path/'plan/body-bytes').exists()
    job=json.loads((tmp_path/'plan/job.json').read_text())
    assert next(s for s in job['steps'] if s['name']=='pending_bodies')['materialize'] is True
    assert next(o for o in job['outputs'] if o['name']=='work-list')['sql']=='SELECT * FROM pending_bodies'
    assert result['parser']=='readings' and result['parser_version']


class CountingFactory:
    def __init__(self):self.started=0;self.inputs=[]
    def __call__(self,*args,**kwargs):
        self.started+=1;owner=self;worker=ParserWorker(*args,**kwargs)
        class Count:
            def __enter__(self):worker.__enter__();return self
            def __exit__(self,*args):return worker.__exit__(*args)
            def parse(self,key,payload):owner.inputs.append(key);return worker.parse(key,payload)
        return Count()


def local_table(args,tmp_path):
    table=dict(namespace=['archive'],name='readings')
    readings.create_table(engine=args['engine'],work=tmp_path/'create',catalog_root=tmp_path/'catalog',
        table=table,location=tmp_path/'lake',create_namespace=True)
    return dict(table=table,catalog_root=tmp_path/'catalog')


def test_backfill_streams_one_plan_and_closes_workers_for_each_durable_batch(tmp_path):
    args=inputs(tmp_path/'source',5);target=local_table(args,tmp_path);factory=CountingFactory();heads=[]
    def current(**kwargs):heads.append(kwargs);return None  # Explicit fake empty current table.
    result=readings.run(**args,**target,work=tmp_path/'backfill',mode='backfill',execute=True,
        batch_size=2,read_current=current,worker_factory=factory,
        unreadable_store=BodyStore(LocalAdapter(tmp_path/'durable')))
    assert len(heads)==1 and factory.started==3 and len(factory.inputs)==len(set(factory.inputs))==5
    assert result['status']=='completed' and result['work_items']==5 and result['applied'] is True
    assert [b['work_items'] for b in result['batches']]==[2,2,1]
    assert [sum(f['rows'] for f in b['append']['files']) for b in result['batches']]==[4,4,2]
    assert len(list((tmp_path/'backfill').rglob('work-list.parquet')))==1
    assert len(list((tmp_path/'backfill').rglob('body-admissions.parquet')))==1


@pytest.mark.parametrize('mode,extra',[('daily',dict(max_work_items=10)),('backfill',dict(batch_size=2))])
def test_execute_requires_durable_unreadable_authority_before_body_work(tmp_path,mode,extra):
    with pytest.raises(ValueError,match='durable unreadable'):
        readings.run(captures='missing',body_inventory='missing',local_root='missing',engine=object(),
            work=tmp_path/'work',decided_at=STAMP,mode=mode,execute=True,table={},catalog_root='missing',**extra)
    assert not (tmp_path/'work').exists()


def test_daily_requires_explicit_budget(tmp_path):
    with pytest.raises(ValueError,match='max_work_items'):
        readings.run(captures='missing',body_inventory='missing',local_root='missing',engine=object(),
            work=tmp_path/'work',decided_at=STAMP,mode='daily',execute=False)
    assert not (tmp_path/'work').exists()


def test_backfill_refuses_stale_existing_authority_before_work(tmp_path):
    with pytest.raises(ValueError,match='current|existing'):
        readings.run(captures='missing',body_inventory='missing',local_root='missing',engine=object(),
            work=tmp_path/'work',decided_at=STAMP,mode='backfill',execute=False,batch_size=2,existing='stale')
    assert not (tmp_path/'work').exists()


def test_cli_first_class_plan_is_metadata_only(tmp_path,capsys):
    from congress_api.cli.readings import main
    args=inputs(tmp_path/'source')
    spec={k:str(v) if isinstance(v,Path) else v for k,v in args.items() if k!='engine'}
    spec.update(parser=None,work=str(tmp_path/'plan'))
    path=tmp_path/'spec.json';path.write_text(json.dumps(spec))
    assert main(['--spec',str(path),'--mode','daily','--plan','--max-work-items','3'])==0
    report=json.loads(capsys.readouterr().out)
    assert report['status']=='planned' and report['work_items']==3 and report['applied'] is False
    assert not list((tmp_path/'plan').rglob('parsed')) and not list((tmp_path/'plan').rglob('body-bytes'))


def test_daily_under_budget_uses_exactly_one_append(tmp_path):
    args=inputs(tmp_path/'source');target=local_table(args,tmp_path);factory=CountingFactory()
    result=readings.run(**args,**target,work=tmp_path/'daily',mode='daily',execute=True,
        max_work_items=3,read_current=lambda **kwargs:None,worker_factory=factory,
        unreadable_store=BodyStore(LocalAdapter(tmp_path/'durable')))
    assert result['status']=='completed' and len(result['batches'])==1
    assert sum(f['rows'] for f in result['batches'][0]['append']['files'])==6
    assert factory.started==1 and len(factory.inputs)==3


def test_unreadable_import_failure_stops_before_append_and_next_batch(tmp_path):
    args=inputs(tmp_path/'source',5);target=local_table(args,tmp_path);parsed=[]
    class Terminal:
        def __init__(self,*args,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def parse(self,key,payload):parsed.append(key);return dict(status='unreadable',attempts=2,reason='timeout')
    class UnavailableStore(BodyStore):
        def put(self,key,path,media):raise OSError('durable raw unavailable')
    with pytest.raises(OSError,match='durable raw unavailable'):
        readings.run(**args,**target,work=tmp_path/'backfill',mode='backfill',execute=True,
            batch_size=2,read_current=lambda **kwargs:None,worker_factory=Terminal,
            unreadable_store=UnavailableStore(LocalAdapter(tmp_path/'durable')))
    assert len(parsed)==2 and not list((tmp_path/'backfill').rglob('append'))
    assert not (tmp_path/'backfill/batch-000001').exists()


def test_resumed_backfill_refreshes_current_lake_and_only_parses_missing_work(tmp_path):
    from congress_api.retention.provenance import run_job,parquet_output
    args=inputs(tmp_path/'source',3);target=local_table(args,tmp_path);factory=CountingFactory();heads=[]
    # External table-reader fake uses an immutable native export supplied for
    # each invocation. Native C2 still owns every real local append and its CAS.
    current=[None]
    def read_current(**kwargs):heads.append(kwargs);return current[0]
    first=readings.run(**args,**target,work=tmp_path/'first',mode='backfill',execute=True,
        batch_size=2,read_current=read_current,worker_factory=factory,
        unreadable_store=BodyStore(LocalAdapter(tmp_path/'durable')))
    joined=tmp_path/'current';joined.mkdir()
    parts=[dict(name='part'+str(i),kind='parquet',path=str(batch['readings']))
        for i,batch in enumerate(first['batches'])]
    run_job(joined,args['engine'],inputs=parts,steps=[],outputs=[parquet_output(joined,'readings',
        ' UNION ALL '.join('SELECT * FROM '+p['name'] for p in parts),readings.PK)])
    current[0]=joined/'readings.parquet'
    second=readings.run(**args,**target,work=tmp_path/'second',mode='backfill',execute=True,
        batch_size=1,read_current=read_current,worker_factory=factory,
        unreadable_store=BodyStore(LocalAdapter(tmp_path/'durable')))
    assert len(heads)==2 and heads[0]['work']!=heads[1]['work']
    assert second['work_items']==0 and second['batches']==[] and second['applied'] is False
    assert factory.started==2 and len(factory.inputs)==3


def test_cli_daily_plan_over_budget_reports_backfill_required(tmp_path,capsys):
    from congress_api.cli.readings import main
    args=inputs(tmp_path/'source')
    spec={k:str(v) if isinstance(v,Path) else v for k,v in args.items() if k!='engine'}
    spec.update(parser=None,work=str(tmp_path/'plan'))
    path=tmp_path/'spec.json';path.write_text(json.dumps(spec))
    assert main(['--spec',str(path),'--mode','daily','--plan','--max-work-items','2'])==2
    report=json.loads(capsys.readouterr().out)
    assert report['status']=='backfill_required' and report['work_items']==3
    assert not (tmp_path/'plan/plan/parsed').exists()


def test_unavailable_native_current_lookup_refuses_before_body_work(tmp_path):
    args=inputs(tmp_path/'source');jobs=[]
    class UnavailableNative:
        remote=None
        def run_job(self,path):
            jobs.append(json.loads(path.read_text()))
            raise OSError('native current-table lookup unavailable')
    args['engine']=UnavailableNative()
    with pytest.raises(OSError,match='native current-table lookup unavailable'):
        readings.run(**args,work=tmp_path/'work',mode='backfill',execute=True,batch_size=2,
            catalog_root=tmp_path/'catalog',table=dict(namespace=['archive'],name='readings'),
            unreadable_store=BodyStore(LocalAdapter(tmp_path/'durable')))
    assert jobs[0]['table_operations']==[dict(kind='resolve',name='readings',
        table=dict(namespace=['archive'],name='readings'))]
    assert not (tmp_path/'work/plan').exists() and not (tmp_path/'durable').exists()


def test_current_native_pin_is_bound_without_exporting_or_parsing_the_table(tmp_path):
    pin=dict(metadata_location='file:///fixture/immutable.metadata.json',
        table_uuid='11111111-1111-4111-8111-111111111111',snapshot=5,schema_id=0)
    class Native:
        def run_job(self,path):
            job=json.loads(Path(path).read_text())
            assert next(x for x in job['inputs'] if x['name']=='existing')==dict(kind='native_table',name='existing',**pin)
            return dict(queries=[dict(name=q['name'],data=[dict(n=0)]) for q in job['queries']])
    result=readings.plan(captures='unopened',body_inventory='unopened',local_root=tmp_path,
        engine=Native(),work=tmp_path/'work',decided_at=STAMP,parser=None,existing=pin)
    assert result['work_items']==0


@pytest.mark.parametrize('arguments',[
    ['--plan'],['--mode','daily'],['--mode','daily','--execute','--max-work-items','1'],
    ['--mode','backfill','--plan'],['--mode','daily','--plan','--max-work-items','1','--batch-size','2'],
    ['--mode','backfill','--plan','--batch-size','2','--max-work-items','1'],
])
def test_cli_invalid_modes_and_budgets_refuse_before_spec_read(tmp_path,arguments):
    from congress_api.cli.readings import main
    with pytest.raises(SystemExit) as error:
        main(['--spec',str(tmp_path/'unopened'),*arguments])
    assert error.value.code==2


def test_resumed_terminal_unreadable_refreshes_durable_raw_inventory(tmp_path):
    args=inputs(tmp_path/'source',2);target=local_table(args,tmp_path);parsed=[]
    store=BodyStore(LocalAdapter(tmp_path/'durable'))
    class Terminal:
        def __init__(self,*args,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def parse(self,key,payload):
            parsed.append(key);return dict(status='unreadable',attempts=2,reason='timeout')
    first=readings.run(**args,**target,work=tmp_path/'first',mode='backfill',execute=True,
        batch_size=1,read_current=lambda **kwargs:None,worker_factory=Terminal,
        unreadable_store=store,unreadable_files=[])
    assert first['unreadable']==2 and len(parsed)==2
    assert len(list((tmp_path/'durable/provenance/unreadable').glob('*.jsonl')))==2
    # The original spec is deliberately reused: it contains no refreshed files.
    second=readings.run(**args,**target,work=tmp_path/'second',mode='backfill',execute=True,
        batch_size=1,read_current=lambda **kwargs:None,worker_factory=NeverWorker,
        unreadable_store=store,unreadable_files=[])
    assert second['work_items']==0 and second['batches']==[] and len(parsed)==2
    files=next(i for i in json.loads((tmp_path/'second/plan/job.json').read_text())['inputs']
               if i['name']=='unreadable')['files']
    assert len(files)==2 and all(i['key'].startswith('provenance/unreadable/') for i in files)
