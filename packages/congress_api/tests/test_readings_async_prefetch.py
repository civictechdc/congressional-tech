"""Verified page prefetch cannot hold up unrelated parser submissions."""
import hashlib,io,json,threading
from pathlib import Path
import pyarrow.parquet as pq
from congress_api.lake import readings
from congress_api.retention.r2 import R2Store
from test_readings_parser_pool import fixture
from test_readings_ranged import Client


def test_ranges_progress_while_a_page_prefetch_is_waiting(tmp_path):
    args,objects=fixture(tmp_path);table=pq.read_table(args['captures']);rows=table.to_pylist()
    slow=next(key for key in objects if key.endswith(rows[0]['sha256'].hex()))
    rows[0]['media_type']='text/html'
    import pyarrow as pa
    pq.write_table(pa.Table.from_pylist(rows,schema=table.schema),args['captures'])
    progressed=threading.Event();prefetch_done=threading.Event()
    class Mixed(Client):
        def get_object(self,**kwargs):
            data=objects[kwargs['Key']];self.reads.append(kwargs)
            if kwargs['Key']==slow and 'Range' not in kwargs:
                assert progressed.wait(3),'Page prefetch blocked every parser submission'
                prefetch_done.set()
            result=dict(Body=io.BytesIO(data),ContentLength=len(data),ETag=kwargs['IfMatch'])
            if 'Range' in kwargs:result.update(ContentRange=f'bytes 0-{len(data)-1}/{len(data)}',ResponseMetadata={'HTTPStatusCode':206})
            return result
    client=Mixed(b'fixture');work=tmp_path/'stage';store=R2Store(client,'bucket',cache_dir=work/'raw-pages')
    class Worker:
        def __init__(self,*args,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def parse(self,body,payload):
            request=json.loads(payload)
            if request.get('prefetched'):data=Path(request['path']).read_bytes()
            else:
                progressed.set();remote=request['remote']
                data=store.read(remote['key'],start=0,length=request['stored_bytes'],
                    expected=dict(etag=remote['etag'],md5=remote['md5'],bytes=request['stored_bytes']))
            assert hashlib.sha256(data).hexdigest()==body
            return dict(status='completed',value=dict(rows=[dict(parser='sniff',parser_version=request['versions']['sniff'],status='completed',format='pdf')]))
    result=readings.stage_once(**args,work=work,body_store=store,worker_factory=Worker,
        parser_workers=2,parser_memory_bytes=1<<30,max_cache_bytes=1<<20)
    assert prefetch_done.is_set() and len(client.reads)==4
    values=pq.read_table(result['readings']).to_pylist()
    assert len(values)==4 and [r['body_sha'] for r in values]==sorted(r['body_sha'] for r in values)
    assert result['pending_reads']==result['unreadable']==0
