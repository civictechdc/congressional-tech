"""D2 uses pinned conditional ranges, sharing the maintained raw transport."""
import hashlib
import io
import threading

import pytest

from congress_api.retention.r2 import R2Store, RawRangeReadError, raw_range_diagnostic
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


@pytest.mark.parametrize('etag',['"opaque-version-7"','multipart-version-7-12'])
@pytest.mark.parametrize('ranged',[False,True])
def test_listed_opaque_etag_is_exact_condition_not_md5(tmp_path,etag,ranged):
    client=Client();client.change={'ETag':etag}
    store=R2Store(client,'bucket',cache_dir=tmp_path/'cache')
    pin=dict(etag=etag,md5=None,bytes=len(DATA))
    options=dict(start=0,length=8192) if ranged else {}
    result=store.read(KEY,expected=pin,**options)
    assert result==(DATA[:8192] if ranged else DATA)
    assert client.reads[0]['IfMatch']==etag
    assert client.streams[0].closed


def test_listed_etag_cannot_hide_captured_md5_mismatch(tmp_path):
    client=Client();client.change={'ETag':'"opaque"'}
    with pytest.raises(ValueError,match='MD5'):
        R2Store(client,'bucket',cache_dir=tmp_path/'cache').read(KEY,
            expected=dict(etag='"opaque"',md5='0'*32,bytes=len(DATA)))
    assert len(client.reads)==1


def test_listed_opaque_etag_drift_refuses_before_body_consumption(tmp_path):
    class Untouched(io.BytesIO):
        def read(self,*args):raise AssertionError('Changed object must not be consumed')
    client=Client();client.change={'ETag':'"changed"','Body':Untouched(DATA)}
    with pytest.raises(ValueError):
        R2Store(client,'bucket',cache_dir=tmp_path/'cache').read(KEY,start=0,length=8192,
            expected=dict(etag='"listed"',md5=None,bytes=len(DATA)))
    assert client.streams[0].closed


def test_opaque_version_cache_without_checksum_is_requalified_conditionally(tmp_path):
    client=Client();client.change={'ETag':'"opaque"'}
    store=R2Store(client,'bucket',cache_dir=tmp_path/'cache')
    cache=store._immutable_cache_path(KEY);cache.parent.mkdir(parents=True)
    cache.write_bytes(b'wrong'+b'x'*(len(DATA)-5))
    assert store.read(KEY,expected=dict(etag='"opaque"',md5=None,bytes=len(DATA)))==DATA
    assert len(client.reads)==1 and cache.read_bytes()==DATA


def test_captured_md5_prefetch_preserves_single_put_quote_normalization(tmp_path):
    client=Client();client.change={'ETag':PIN['md5']}
    store=R2Store(client,'bucket',cache_dir=tmp_path/'cache')
    store.prefetch_immutable([KEY],expected={KEY:PIN})
    assert store._immutable_cache_path(KEY).read_bytes()==DATA
    assert client.reads[0]['IfMatch']=='"'+PIN['md5']+'"'


@pytest.mark.parametrize('change,reason,observed,range_valid,etag_matches',[
    (dict(ContentLength=8193),'response_metadata_mismatch',None,None,True),
    (dict(ETag='"'+('0'*32)+'"'),'response_metadata_mismatch',None,None,False),
    (dict(ContentRange='bytes 0-8191/99999'),'range_mismatch',None,False,True),
    (dict(ResponseMetadata={'HTTPStatusCode':200}),'range_mismatch',None,False,True),
    (dict(Body=io.BytesIO(DATA[:8191])),'payload_length_mismatch',8191,True,True),
])
def test_range_failure_evidence_preserves_lengths_without_a_success_cache(
        tmp_path,change,reason,observed,range_valid,etag_matches):
    client=Client();client.change=change
    store=R2Store(client,'bucket',cache_dir=tmp_path/'cache');timing={}
    with pytest.raises(RawRangeReadError) as failure:
        store.read(KEY,start=0,length=8192,expected=PIN,timing=timing)
    diagnostic=failure.value.diagnostic
    assert diagnostic==dict(version=1,reason=reason,
        phase='response_body' if observed is not None else 'response_headers',
        expected_total_bytes=len(DATA),range_start=0,expected_bytes=8192,
        observed_content_length=change.get('ContentLength',8192),observed_bytes=observed,
        http_status=change.get('ResponseMetadata',{}).get('HTTPStatusCode',206),
        range_valid=range_valid,etag_matches=etag_matches)
    assert timing['error_type']=='ValueError' and timing['bytes']==0
    assert len(client.reads)==1 and client.streams[0].closed
    assert not store._immutable_cache_path(KEY).exists()


def test_raw_failure_diagnostic_is_a_closed_bounded_schema():
    secret='https://credentials.invalid/?token=DO_NOT_RETAIN'
    value=raw_range_diagnostic(dict(phase=[secret],reason=secret,expected_total_bytes=True,
        range_start=-1,expected_bytes=1<<80,observed_content_length=secret,observed_bytes=1.5,
        http_status=999,range_valid=secret,etag_matches=1,url=secret,error=secret))
    assert value==dict(version=1,phase='store_read',reason='unknown_value_error',
        **dict.fromkeys(('expected_total_bytes','range_start','expected_bytes','observed_content_length',
                         'observed_bytes','http_status','range_valid','etag_matches')))


def test_missing_response_metadata_does_not_hide_a_length_failure():
    client=Client();client.change=dict(ContentLength=8193,ResponseMetadata=None)
    with pytest.raises(RawRangeReadError) as failure:
        R2Store(client,'bucket').read(KEY,start=0,length=8192,expected=PIN)
    assert failure.value.diagnostic['reason']=='response_metadata_mismatch'
    assert failure.value.diagnostic['http_status'] is None
    assert client.streams[0].closed


def test_unknown_store_value_error_stays_pending_without_copying_exception_attributes(tmp_path,monkeypatch):
    from congress_api.lake.readings import _ReadOnceBody
    secret='https://credentials.invalid/?token=DO_NOT_RETAIN'
    class Store:
        def read(self,*args,**kwargs):
            error=ValueError(secret)
            error.diagnostic={'reason':secret,'phase':secret,'url':secret}
            raise error
    monkeypatch.setenv('DOCSPEC_PARSER_IO_MARKER',str(tmp_path/'io-marker'))
    source=_ReadOnceBody(None,tmp_path/'ranges',len(DATA),body_store=Store(),
        remote=dict(bucket='bucket',key=KEY,md5=PIN['md5']))
    with pytest.raises(OSError,match='^raw_range_ValueError$') as failure:
        source.read(0,8192)
    assert failure.value.raw_read_diagnostic==raw_range_diagnostic(dict(phase='store_read',
        expected_total_bytes=len(DATA),range_start=0,expected_bytes=8192))
    assert source.read_bytes==0 and not list(source.cache.glob('*.bin'))
    assert not list(source.cache.glob('*.pending'))
    assert secret not in str(failure.value.raw_read_diagnostic)


def test_other_value_error_categories_keep_their_existing_pending_reason(tmp_path,monkeypatch):
    from congress_api.lake.readings import _ReadOnceBody
    class ClientError(Client):
        def get_object(self,**kwargs):raise UnicodeError('do not retain transport error text')
    monkeypatch.setenv('DOCSPEC_PARSER_IO_MARKER',str(tmp_path/'io-marker'))
    source=_ReadOnceBody(None,tmp_path/'ranges',len(DATA),body_store=R2Store(ClientError(),'bucket'),
        remote=dict(bucket='bucket',key=KEY,md5=PIN['md5']))
    with pytest.raises(OSError,match='^raw_range_UnicodeError$') as failure:
        source.read(0,8192)
    assert not hasattr(failure.value,'raw_read_diagnostic')
    assert source.read_bytes==0
