"""D2 uses pinned conditional ranges, sharing the maintained raw transport."""
import hashlib
import io
import threading

import pytest

from congress_api.retention.r2 import R2Store
from test_r2_body_files import Client as BaseClient


DATA=b'%PDF-1.7\n'+b'x'*24000+b'%%EOF'
KEY='bodies/sha256/'+hashlib.sha256(DATA).hexdigest()[:2]+'/'+hashlib.sha256(DATA).hexdigest()
PIN=dict(md5=hashlib.md5(DATA).hexdigest(),bytes=len(DATA))


class Client(BaseClient):
    def __init__(self):
        super().__init__();self.meta.config.retries={'total_max_attempts':1};self.change={};self.streams=[]
    def get_object(self,**kwargs):
        self.reads.append(kwargs)
        if 'Range' in kwargs:
            start,end=map(int,kwargs['Range'][6:].split('-'));value=DATA[start:end+1]
            response=dict(Body=io.BytesIO(value),ContentLength=len(value),ETag='"'+PIN['md5']+'"',
                ContentRange=f'bytes {start}-{end}/{len(DATA)}',ResponseMetadata={'HTTPStatusCode':206})
        else:response=dict(Body=io.BytesIO(DATA),ContentLength=len(DATA),ETag='"'+PIN['md5']+'"')
        response.update(self.change);self.streams.append(response['Body']);return response
    def head_object(self,**_):raise AssertionError('No per-body HEAD')


def test_conditional_range_returns_only_requested_bytes_and_never_fills_whole_cache(tmp_path):
    client=Client();store=R2Store(client,'bucket',cache_dir=tmp_path/'cache')
    assert store.read(KEY,start=0,length=8192,expected=PIN)==DATA[:8192]
    assert client.reads==[dict(Bucket='bucket',Key=KEY,Range='bytes=0-8191',IfMatch='"'+PIN['md5']+'"')]
    assert client.streams[0].closed and not store._immutable_cache_path(KEY).exists()


@pytest.mark.parametrize('change',[
    dict(ContentRange=f'bytes 0-8191/{len(DATA)+1}'),dict(ContentRange=f'bytes 1-8192/{len(DATA)}'),
    dict(ContentLength=8193),dict(ETag='"'+('0'*32)+'"'),dict(ResponseMetadata={'HTTPStatusCode':200}),
    dict(Body=io.BytesIO(DATA[:8191])),dict(ContentRange='invalid'),
])
def test_range_custody_and_exact_size_refuse_inconsistent_responses(tmp_path,change):
    client=Client();client.change=change
    with pytest.raises((ValueError,OSError)):
        R2Store(client,'bucket',cache_dir=tmp_path/'cache').read(KEY,start=0,length=8192,expected=PIN)
    assert len(client.reads)==1 and client.streams[0].closed


@pytest.mark.parametrize('options',[
    dict(start=0,length=8192),dict(start=-1,length=5,expected=PIN),
    dict(start=0,length=len(DATA)+1,expected=PIN),dict(start=0,length=5,expected=dict(md5=None,bytes=len(DATA))),
])
def test_unpinned_or_invalid_ranges_refuse_before_get(options):
    client=Client()
    with pytest.raises(ValueError):R2Store(client,'bucket').read(KEY,**options)
    assert not client.reads


def test_prefetch_uses_the_same_conditional_full_read_and_retains_immutable_file(tmp_path):
    client=Client();store=R2Store(client,'bucket',cache_dir=tmp_path/'cache')
    store.prefetch_immutable([KEY],expected={KEY:PIN},max_workers=2)
    assert store._immutable_cache_path(KEY).read_bytes()==DATA
    assert client.reads==[dict(Bucket='bucket',Key=KEY,IfMatch='"'+PIN['md5']+'"')]


def test_prefetch_discards_returned_payloads_after_each_cache_write(tmp_path):
    live=peak=0;lock=threading.Lock()
    class Tracked(bytes):
        def __new__(cls,value):
            nonlocal live,peak
            result=super().__new__(cls,value)
            with lock:live+=1;peak=max(peak,live)
            return result
        def __del__(self):
            nonlocal live
            with lock:live-=1
    class Stream(io.BytesIO):
        def read(self,size=-1):return Tracked(super().read(size))
    class Many(Client):
        def get_object(self,**kwargs):
            response=super().get_object(**kwargs);response['Body']=Stream(DATA);return response
    client=Many();store=R2Store(client,'bucket',cache_dir=tmp_path/'cache')
    keys=[KEY+str(i) for i in range(8)]
    store.prefetch_immutable(keys,max_workers=2)
    assert live==0 and peak<=2
