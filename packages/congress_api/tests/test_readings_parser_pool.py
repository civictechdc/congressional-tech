"""Parallel conditional reads keep budgets, durable decisions and native writes ordered."""
import hashlib
import io
import json
import threading
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.lake import readings
from congress_api.retention.body_store import BodyStore,LocalAdapter
from congress_api.retention.r2 import R2Store
from test_readings_ranged import Client
from test_readings_ranged_plan import inputs,STAMP


def fixture(tmp_path):
    args,_,_=inputs(tmp_path);schema=pq.read_schema(args['captures']);objects={};captures=[];listed=[]
    for number in range(4):
        data=b'%PDF-1.7\n'+bytes([65+number])*100+b'\n%%EOF'
        sha=hashlib.sha256(data).digest();key='bodies/sha256/'+sha.hex()[:2]+'/'+sha.hex();objects[key]=data
        captures.append(dict(sha256=sha,bytes=len(data),media_type='application/pdf',fidelity='exact-bytes',
            stored_suffix='',stored_bytes=len(data),stored_md5=hashlib.md5(data).digest()))
        listed.append(dict(key=key,size=len(data),etag='"'+hashlib.md5(data).hexdigest()+'"'))
    pq.write_table(pa.Table.from_pylist(captures,schema=schema),args['captures'])
    path=tmp_path/'listing.parquet';pq.write_table(pa.Table.from_pylist(listed),path)
    args.update(body_inventory=None,body_listing=path)
    return args,objects


@pytest.mark.parametrize('unreadable',[False,True])
def test_parallel_ranges_keep_main_thread_decisions_and_close_before_export(tmp_path,unreadable):
    args,objects=fixture(tmp_path);main=threading.get_ident();lock=threading.Lock();barrier=threading.Barrier(2)
    state=dict(active=0,peak=0,created=0,closed=0,decisions=0,budgets=[])
    class Ranges(Client):
        def get_object(self,**kwargs):
            data=objects[kwargs['Key']]
            assert kwargs['IfMatch']=='"'+hashlib.md5(data).hexdigest()+'"'
            assert kwargs['Range']==f'bytes=0-{len(data)-1}'
            with lock:
                self.reads.append(kwargs);state['active']+=1;state['peak']=max(state['peak'],state['active'])
            try:
                barrier.wait(5)
                return dict(Body=io.BytesIO(data),ContentLength=len(data),ContentRange=f'bytes 0-{len(data)-1}/{len(data)}',
                    ETag=kwargs['IfMatch'],ResponseMetadata={'HTTPStatusCode':206})
            finally:
                with lock:state['active']-=1
    client=Ranges(next(iter(objects.values())));work=tmp_path/'stage'
    store=R2Store(client,'bucket',cache_dir=work/'raw-pages')
    class Worker:
        def __init__(self,*args,**limits):pass
        def __enter__(self):
            with lock:state['created']+=1
            return self
        def __exit__(self,*error):
            assert threading.get_ident()==main
            state['closed']+=1
        def parse(self,body,payload):
            request=json.loads(payload);remote=request['remote']
            assert 0<request['max_read_bytes']<=(1<<20)//2
            with lock:state['budgets'].append((threading.get_ident(),request['max_read_bytes']))
            data=store.read(remote['key'],start=0,length=request['stored_bytes'],
                expected=dict(etag=remote['etag'],md5=remote['md5'],bytes=request['stored_bytes']))
            assert hashlib.sha256(data).hexdigest()==body
            cache=Path(request['cache']);cache.mkdir(parents=True)
            (cache/'0-115.bin').write_bytes(data)
            if unreadable and remote['key']==min(objects):return dict(status='unreadable',reason='fixture',attempts=2)
            return dict(status='completed',value=dict(read_bytes=len(data),rows=[dict(parser='sniff',
                parser_version=request['versions']['sniff'],status='completed',format='pdf')]))
    class Durable(LocalAdapter):
        def create(self,*args,**kwargs):
            assert threading.get_ident()==main;state['decisions']+=1
            return super().create(*args,**kwargs)
    native=args['engine']
    class CheckedEngine:
        def __getattr__(self,name):return getattr(native,name)
        def run_job(self,path):
            assert state['closed']==state['created']
            return native.run_job(path)
    args['engine']=CheckedEngine()
    result=readings.stage_once(**args,work=work,body_store=store,worker_factory=Worker,
        parser_workers=2,parser_memory_bytes=1<<30,max_cache_bytes=1<<20,
        unreadable_store=BodyStore(Durable(tmp_path/'durable')))
    rows=pq.read_table(result['readings']).to_pylist()
    assert state['peak']==2 and state['created']==state['closed']==2
    assert len(client.reads)==4 and len(rows)==(3 if unreadable else 4)
    assert result['unreadable']==int(unreadable) and result['pending_reads']==0
    assert state['decisions']==int(unreadable)
    assert all(r['parser']=='sniff' and r['status']=='completed' for r in rows)
    for thread in {thread for thread,_ in state['budgets']}:
        budgets=[budget for owner,budget in state['budgets'] if owner==thread]
        assert len(budgets)==2 and budgets[1]<budgets[0]


@pytest.mark.parametrize('workers,budget',[(0,1<<30),(True,1<<30),(33,1<<40),(2,512<<20)])
def test_bad_pool_admission_refuses_before_work_or_transport(tmp_path,workers,budget):
    with pytest.raises(ValueError,match='[Pp]arser|[Ww]orker|memory'):
        readings.stage_once(captures='unopened',body_inventory='unopened',local_root='unopened',
            engine=object(),work=tmp_path/'work',decided_at=STAMP,
            parser_workers=workers,parser_memory_bytes=budget)
    assert not (tmp_path/'work').exists()


def test_parallel_page_preflight_refuses_before_get_or_worker(tmp_path):
    args,_=fixture(tmp_path)
    table=pq.read_table(args['captures']).to_pylist()
    for row in table:row['media_type']='application/json'
    pq.write_table(pa.Table.from_pylist(table,schema=pq.read_schema(args['captures'])),args['captures'])
    work=tmp_path/'work';client=Client(b'never');store=R2Store(client,'bucket',cache_dir=work/'raw-pages')
    def forbidden(*args,**kwargs):raise AssertionError('Worker before actual-size cache admission')
    with pytest.raises(ValueError,match='prefetch.*budget'):
        readings.stage_once(**args,work=work,body_store=store,worker_factory=forbidden,
            parser_workers=2,parser_memory_bytes=1<<30,max_cache_bytes=1)
    assert client.reads==[] and not (work/'body-bytes').exists()


@pytest.mark.parametrize('workers',[0,-1,33])
def test_cli_invalid_workers_refuse_before_spec_read(tmp_path,workers,capsys):
    from congress_api.cli.readings import main
    with pytest.raises(SystemExit) as error:
        main(['--spec',str(tmp_path/'unopened'),'--parser-workers',str(workers)])
    assert error.value.code==2
    assert 'Parser workers' in capsys.readouterr().err


def test_cli_pool_memory_refuses_before_transport(tmp_path,capsys):
    from congress_api.cli.readings import main
    config=tmp_path/'runtime.json';limits=tmp_path/'limits.json'
    limits.write_text(json.dumps(dict(memory_bytes=512<<20)))
    config.write_text(json.dumps(dict(version=1,binary='/unopened',workspace=str(tmp_path/'native'),limits=str(limits))))
    spec=tmp_path/'spec.json';spec.write_text(json.dumps(dict(captures='unopened',body_inventory='unopened',
        local_root='unopened',work=str(tmp_path/'work'),decided_at=STAMP,parser=None,
        apply=dict(catalog_root=str(tmp_path/'catalog'),table=dict(namespace=['archive'],name='readings')))))
    with pytest.raises(SystemExit) as error:
        main(['--spec',str(spec),'--engine-config',str(config),'--mode','daily','--execute',
            '--max-work-items','1','--raw-bucket','unopened','--parser-workers','2'])
    assert error.value.code==2 and 'memory' in capsys.readouterr().err
    assert not (tmp_path/'work').exists()
