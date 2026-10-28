"""Daily admission precedes raw I/O; backfills stream one native work list."""
import hashlib
import json
import os
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


class NeverWorker:
    def __init__(self,*args,**kwargs):raise AssertionError('worker before admission')


@pytest.mark.parametrize('parser',[None,'sniff'])
def test_daily_budget_refuses_before_worker_or_body_access(tmp_path,parser):
    args=inputs(tmp_path/'source')
    with pytest.raises(readings.BackfillRequired) as error:
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


def test_backfill_streams_one_plan_and_one_worker_with_one_durable_append_per_batch(tmp_path):
    args=inputs(tmp_path/'source',5);target=local_table(args,tmp_path);factory=CountingFactory();heads=[]
    def current(**kwargs):heads.append(kwargs);return None  # Explicit fake empty current table.
    result=readings.run(**args,**target,work=tmp_path/'backfill',mode='backfill',execute=True,
        batch_size=2,read_current=current,worker_factory=factory,
        unreadable_store=BodyStore(LocalAdapter(tmp_path/'durable')))
    assert len(heads)==1 and factory.started==1 and len(factory.inputs)==len(set(factory.inputs))==5
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
    assert not (tmp_path/'plan/parsed').exists()
