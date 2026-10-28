"""Ranged plans bind storage facts to one physical object before any GET."""
import gzip
import hashlib
import io
import json
import os

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.lake import readings
from congress_api.retention.body_store import BodyStore,LocalAdapter
from congress_api.retention.r2 import R2Store
from docspec_client.client import NativeDatasets
from test_readings_ranged import Client,phase


STAMP='2026-10-28T12:00:00Z'


def inputs(tmp_path,*,missing=None):
    entity=b'<html><body><p>'+b'Evidence '*1800+b'</p></body></html>'
    stored=gzip.compress(entity,mtime=0);digest=hashlib.sha256(entity).digest()
    key='bodies/sha256/'+digest.hex()[:2]+'/'+digest.hex()
    capture=dict(sha256=digest,bytes=len(entity),media_type='text/html',fidelity='exact-bytes',
        stored_suffix='',stored_bytes=None if missing=='size' else len(stored),
        stored_md5=None if missing=='md5' else hashlib.md5(stored).digest())
    # A different physical suffix must never supply the selected object's MD5.
    alternate=dict(capture,stored_suffix='.gz',stored_bytes=999,stored_md5=b'z'*16)
    schema=pa.schema([('sha256',pa.binary(32)),('bytes',pa.int64()),('media_type',pa.string()),
        ('fidelity',pa.string()),('sniffed_format',pa.string()),('sniff_version',pa.string()),('intact',pa.bool_()),
        ('stored_suffix',pa.string()),('stored_bytes',pa.int64()),('stored_md5',pa.binary(16))])
    captures=tmp_path/'captures.parquet';pq.write_table(pa.Table.from_pylist([capture,alternate],schema=schema),captures)
    inventory=tmp_path/'inventory.parquet'
    pq.write_table(pa.Table.from_pylist([dict(body_sha=digest,physical_key=key,relative_path=key,
        stored_bytes=len(stored),stored_gzip=False)],schema=pa.schema([('body_sha',pa.binary(32)),
        ('physical_key',pa.string()),('relative_path',pa.string()),('stored_bytes',pa.int64()),('stored_gzip',pa.bool_())])),inventory)
    return dict(captures=captures,body_inventory=inventory,local_root=tmp_path/'absent',decided_at=STAMP,
        engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])),stored,key


def test_native_worklist_uses_md5_and_size_for_the_exact_physical_key(tmp_path):
    args,stored,key=inputs(tmp_path)
    result=readings.plan(**args,work=tmp_path/'plan',parser=None,raw_ranges=True)
    [row]=pq.read_table(result['work_list']).to_pylist()
    assert row['physical_key']==key and row['stored_md5']==hashlib.md5(stored).hexdigest()
    assert row['captured_stored_bytes']==len(stored) and row['page_hint'] is True
    assert result['raw_custody']['missing_pins']==0


def test_absent_physical_inventory_is_not_reported_as_ready_custody(tmp_path):
    args,stored,_=inputs(tmp_path)
    inventory=pq.read_table(args['body_inventory'])
    pq.write_table(inventory.slice(0,0),args['body_inventory'])
    result=readings.plan(**args,work=tmp_path/'plan',parser=None,raw_ranges=True)
    assert result['raw_custody']['missing_pins']==1 and result['raw_custody']['missing_physical']==1
    client=Client(stored,'gzip');work=tmp_path/'stage'
    with pytest.raises(readings.RawCustodyRequired):
        readings.stage_once(**args,work=work,body_store=R2Store(client,'bucket',cache_dir=work/'raw-pages'))
    assert not client.reads


@pytest.mark.parametrize('missing',['md5','size'])
def test_missing_capture_pins_are_reported_and_refused_before_worker_or_get(tmp_path,missing):
    from congress_api.lake.readings import RawCustodyRequired
    args,stored,_=inputs(tmp_path,missing=missing);client=Client(stored,'gzip')
    work=tmp_path/'work';store=R2Store(client,'bucket',cache_dir=work/'raw-pages')
    class NeverWorker:
        def __init__(self,*_,**__):raise AssertionError('Worker before raw custody admission')
    with pytest.raises(RawCustodyRequired) as error:
        readings.stage_once(**args,work=work,body_store=store,worker_factory=NeverWorker)
    assert error.value.report['missing_pins']==1 and not client.reads
    assert pq.read_metadata(error.value.report['work_list']).num_rows==1


@pytest.mark.parametrize('workers',[0,65,True])
def test_invalid_get_concurrency_refuses_before_work(tmp_path,workers):
    with pytest.raises(ValueError):
        readings.stage_once(captures='unopened',body_inventory='unopened',local_root='unopened',engine=object(),
            work=tmp_path/'work',decided_at=STAMP,body_store=R2Store(Client(b'x'),'bucket'),max_get_workers=workers)
    assert not (tmp_path/'work').exists()


def test_prefetch_cache_budget_refuses_before_get(tmp_path):
    args,stored,_=inputs(tmp_path);client=Client(stored,'gzip');work=tmp_path/'work'
    with pytest.raises(ValueError,match='cache.*budget|budget.*cache'):
        readings.stage_once(**args,work=work,body_store=R2Store(client,'bucket',cache_dir=work/'raw-pages'),
            max_cache_bytes=128)
    assert not client.reads


@pytest.mark.parametrize('combined',[False,True])
def test_known_oversized_pages_settle_without_capture_pins_or_gets(tmp_path,combined):
    args,stored,_=inputs(tmp_path,missing='md5')
    values=pq.read_table(args['captures']).to_pylist()
    for row in values:
        row.update(sniffed_format='html',sniff_version=readings.current_version('sniff'),stored_bytes=None)
    pq.write_table(pa.Table.from_pylist(values,schema=pq.read_schema(args['captures'])),args['captures'])
    inventory=pq.read_table(args['body_inventory']);values=inventory.to_pylist()
    values[0]['stored_bytes']=readings.MAX_STORED_BYTES+1
    pq.write_table(pa.Table.from_pylist(values,schema=inventory.schema),args['body_inventory'])
    client=Client(stored,'gzip');work=tmp_path/'stage'
    store=R2Store(client,'bucket',cache_dir=work/'raw-pages')
    result=readings.stage(**args,work=work,parser=None if combined else 'html',body_store=store)
    output=pq.read_table(result['readings']).to_pylist()
    assert [(r['parser'],r['status']) for r in output]==[('html','size_limit')]
    assert result['read_bytes']==0 and not client.reads


@pytest.mark.parametrize('fail_append',[False,True])
def test_full_page_cache_is_removed_only_after_successful_readings_append(tmp_path,fail_append):
    args,stored,key=inputs(tmp_path);native=args.pop('engine');work=tmp_path/'backfill'
    class FullClient(Client):
        def get_object(self,**kwargs):
            self.reads.append(kwargs)
            assert kwargs==dict(Bucket='bucket',Key=key,IfMatch='"'+hashlib.md5(stored).hexdigest()+'"')
            return dict(Body=io.BytesIO(stored),ContentLength=len(stored),ContentEncoding='gzip',
                ETag='"'+hashlib.md5(stored).hexdigest()+'"')
    client=FullClient(stored,'gzip');store=R2Store(client,'bucket',cache_dir=work/'raw-pages')
    table=dict(namespace=['archive'],name='readings')
    readings.create_table(engine=native,work=tmp_path/'create',catalog_root=tmp_path/'catalog',
        table=table,location=tmp_path/'lake',create_namespace=True)
    class DirectWorker:
        def __init__(self,*_,**__):pass
        def __enter__(self):self.context=phase(tmp_path);self.context.__enter__();return self
        def __exit__(self,*exc):self.context.__exit__(*exc)
        def parse(self,identity,payload):return dict(status='completed',value=readings.parse_once_payload(payload,body_store=store))
    class CheckedNative:
        remote=None
        def __getattr__(self,name):return getattr(native,name)
        def run_job(self,path):
            job=json.loads(path.read_text())
            if any(op['kind']=='append' for op in job.get('table_operations',[])):
                assert store._immutable_cache_path(key).is_file()
                assert list((work/'batch-000000/body-bytes').rglob('*.bin'))
                if fail_append:raise RuntimeError('fixture append refused')
            return native.run_job(path)
    kwargs=dict(**args,engine=CheckedNative(),work=work,mode='backfill',execute=True,batch_size=1,
        table=table,catalog_root=tmp_path/'catalog',read_current=lambda **_:None,
        body_store=store,worker_factory=DirectWorker,unreadable_store=BodyStore(LocalAdapter(tmp_path/'durable')))
    if fail_append:
        with pytest.raises(RuntimeError,match='append refused'):readings.run(**kwargs)
        assert store._immutable_cache_path(key).is_file()
        assert list((work/'batch-000000/body-bytes').rglob('*.bin'))
    else:
        report=readings.run(**kwargs)
        assert report['status']=='completed' and report['batches'][0]['append'] is not None
        assert not store._immutable_cache_path(key).exists()
        assert not list((work/'batch-000000/body-bytes').rglob('*.bin'))
    assert len(client.reads)==1
