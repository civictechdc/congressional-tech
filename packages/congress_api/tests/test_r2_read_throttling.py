"""D2 bounds transient GET retries and never overlaps streams for one object."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import io
import json
import os
import threading

import boto3
from botocore.awsrequest import AWSResponse
from botocore.config import Config
from botocore.exceptions import ClientError
import pytest

from congress_api.retention.r2 import R2Store
from test_r2_body_files import Client


DATA=b'complete'
DIGEST=hashlib.sha256(DATA).hexdigest()
KEY=f'bodies/sha256/{DIGEST[:2]}/{DIGEST}'
PIN=dict(bytes=len(DATA),md5=hashlib.md5(DATA).hexdigest())


@pytest.mark.parametrize('second_reader',['bytes','file','other-store'])
def test_same_key_waits_until_the_previous_stream_closes(tmp_path,second_reader):
    entered=threading.Event();release=threading.Event();second_started=threading.Event()
    overlap=threading.Event();other_finished=threading.Event()
    active=0;peak=0;lock=threading.Lock()

    class Stream(io.BytesIO):
        def __init__(self,blocked):super().__init__(DATA);self.blocked=blocked
        def read(self,*args):
            if self.blocked:
                entered.set()
                if not release.wait(3):raise TimeoutError('fixture did not release first read')
            return super().read(*args)
        def close(self):
            nonlocal active
            if not self.closed and self.blocked is not None:
                with lock:active-=1
            super().close()

    class Reads(Client):
        def get_object(self,**args):
            nonlocal active,peak
            if args['Key']!=KEY:
                other_finished.set()
                return dict(Body=io.BytesIO(DATA),ContentLength=len(DATA),ETag='version')
            with lock:
                first=not self.reads;self.reads.append(args);active+=1;peak=max(peak,active)
                if active>1:overlap.set()
            return dict(Body=Stream(first),ContentLength=len(DATA),ETag='version')

    client=Reads();store=R2Store(client,'bucket')
    def second():
        second_started.set()
        if second_reader=='file':
            return store.read_file(KEY,tmp_path/'second',max_bytes=len(DATA))
        target=R2Store(client,'bucket') if second_reader=='other-store' else store
        return target.read(KEY)
    with ThreadPoolExecutor(max_workers=3) as pool:
        first=pool.submit(store.read,KEY)
        try:
            assert entered.wait(2)
            following=pool.submit(second)
            assert second_started.wait(2)
            distinct=pool.submit(store.read,'bodies/another-key')
            assert other_finished.wait(2), 'A different key must progress while the first key is blocked'
            assert distinct.result(timeout=2)==DATA
            observed_overlap=overlap.wait(.2)
        finally:release.set()
        assert first.result(timeout=2)==DATA
        result=following.result(timeout=2)
    assert result==(len(DATA) if second_reader=='file' else DATA)
    assert not observed_overlap and peak==1 and active==0
    assert len(client.reads)==2


class WireBytes(io.BytesIO):
    def stream(self,amt=1024,decode_content=False):
        while piece:=self.read(amt):yield piece


def sdk_transport(monkeypatch,client,responses):
    """Run actual SDK retry dispatch with a finite in-memory HTTP transport."""
    calls=[];sleeps=[]
    def send(request):
        response=responses[min(len(calls),len(responses)-1)]
        calls.append(request)
        if isinstance(response,Exception):raise response
        status,code,extra=response
        body=(DATA if status==200 else
              f'<Error><Code>{code}</Code><Message>R2 throttle</Message></Error>'.encode())
        headers={'content-length':str(len(body)),'etag':'"'+PIN['md5']+'"',
                 'x-amz-request-id':f'fixture-{len(calls)}',**extra}
        return AWSResponse(request.url,status,headers,WireBytes(body))
    monkeypatch.setattr(client._endpoint.http_session,'send',send)
    monkeypatch.setattr('botocore.endpoint.time.sleep',sleeps.append)
    monkeypatch.setattr('congress_api.retention.r2.random.random',lambda:.25)
    return calls,sleeps


def sdk_client(mode='standard',maximum=1):
    return boto3.client('s3',endpoint_url='https://r2.example.test',region_name='auto',
        aws_access_key_id='test',aws_secret_access_key='test',
        config=Config(retries={'total_max_attempts':maximum,'mode':mode}))


def transport_failure(kind):
    from botocore.exceptions import ConnectionClosedError,EndpointConnectionError,HTTPClientError,ReadTimeoutError
    if kind=='reset':return ConnectionResetError('fixture reset')
    if kind=='wrapped-reset':return HTTPClientError(error=ConnectionResetError('fixture reset'))
    cls={'closed':ConnectionClosedError,'timeout':ReadTimeoutError,'endpoint':EndpointConnectionError}[kind]
    return cls(endpoint_url='https://r2.example.test')


@pytest.mark.parametrize('mode',['legacy','standard'])
@pytest.mark.parametrize('kind',['closed','timeout','endpoint','reset','wrapped-reset'])
@pytest.mark.parametrize('failures',[0,1,4,5])
def test_transport_get_recovers_within_one_shared_attempt_bound(monkeypatch,mode,kind,failures):
    error=transport_failure(kind)
    with closing(sdk_client(mode)) as client:
        calls,sleeps=sdk_transport(monkeypatch,client,[error]*failures+[(200,'',{})])
        timing={};store=R2Store(client,'bucket',read_throttle_attempts=5)
        if failures<5:
            assert store.read(KEY,expected=PIN,timing=timing)==DATA
            assert timing['sdk_retries']==failures and timing['sdk_retry_metadata_complete']
        else:
            from congress_api.retention.r2 import R2GetTransportExhausted
            with pytest.raises(R2GetTransportExhausted) as caught:
                store.read(KEY,expected=PIN,timing=timing)
            assert caught.value.__cause__ is error and not isinstance(caught.value,OSError)
            assert timing['sdk_retry_metadata_complete'] is False
        assert len(calls)==min(failures+1,5)
        assert sleeps==[1.25,2.25,4.25,8.25][:min(failures,4)]
        assert timing['requests']==1
        assert all(request.headers['If-Match']==b'"'+PIN['md5'].encode()+b'"' for request in calls)


@pytest.mark.parametrize('mode',['legacy','standard'])
def test_503_and_transport_errors_share_one_get_attempt_counter(monkeypatch,mode):
    sequence=[(503,'SlowDown',{}),transport_failure('closed'),transport_failure('timeout'),
        transport_failure('endpoint'),(200,'',{})]
    with closing(sdk_client(mode)) as client:
        calls,sleeps=sdk_transport(monkeypatch,client,sequence)
        assert R2Store(client,'bucket',read_throttle_attempts=5).read(KEY,expected=PIN)==DATA
        assert len(calls)==5 and sleeps==[1.25,2.25,4.25,8.25]


@pytest.mark.parametrize('mode',['legacy','standard'])
@pytest.mark.parametrize('operation',['put_object','head_object'])
def test_get_transport_override_does_not_expand_other_operations(monkeypatch,mode,operation):
    with closing(sdk_client(mode)) as client:
        calls,sleeps=sdk_transport(monkeypatch,client,[transport_failure('closed')])
        R2Store(client,'bucket',read_throttle_attempts=5)
        with pytest.raises(type(transport_failure('closed'))):
            getattr(client,operation)(Bucket='bucket',Key=KEY,**({'Body':DATA} if operation=='put_object' else {}))
        assert len(calls)==1 and sleeps==[]


@pytest.mark.parametrize('mode',['legacy','standard'])
def test_unclassified_get_exception_is_not_promoted_to_retryable(monkeypatch,mode):
    with closing(sdk_client(mode)) as client:
        calls,sleeps=sdk_transport(monkeypatch,client,[ValueError('fixture nontransport failure')])
        with pytest.raises(ValueError,match='nontransport'):
            R2Store(client,'bucket',read_throttle_attempts=5).read(KEY,expected=PIN)
        assert len(calls)==1 and sleeps==[]


@pytest.mark.parametrize('mode',['legacy','standard'])
@pytest.mark.parametrize('get_budget',[None,1,2,5])
def test_transport_uses_configured_or_explicit_get_budget_without_a_stream_multiplier(monkeypatch,mode,get_budget):
    error=transport_failure('reset');maximum=3 if get_budget is None else get_budget
    with closing(sdk_client(mode,maximum=3)) as client:
        calls,sleeps=sdk_transport(monkeypatch,client,[error])
        from congress_api.retention.r2 import R2GetTransportExhausted
        with pytest.raises(ConnectionResetError if get_budget is None else R2GetTransportExhausted):
            R2Store(client,'bucket',read_throttle_attempts=get_budget).read(KEY,expected=PIN)
        assert len(calls)==maximum and len(sleeps)==maximum-1


@pytest.mark.parametrize('mode',['legacy','standard'])
@pytest.mark.parametrize('recover',[True,False])
def test_async_adapter_shares_the_sdk_transport_policy_without_an_outer_request_retry(monkeypatch,mode,recover):
    import asyncio
    from aiobotocore.awsrequest import AioAWSResponse
    from aiobotocore.session import get_session
    from congress_api.retention.r2 import AsyncBodies
    calls=[];sleeps=[]
    class AsyncWire:
        def __init__(self):self.stream=io.BytesIO(DATA);self.content=self
        async def read(self,n=-1):return self.stream.read(n)
        def close(self):self.stream.close()
    async def send(request):
        calls.append(request)
        if not recover or len(calls)<3:raise transport_failure('reset')
        return AioAWSResponse(request.url,200,{'content-length':str(len(DATA))},AsyncWire())
    async def sleep(delay):sleeps.append(delay)
    async def check():
        async with get_session().create_client('s3',endpoint_url='https://r2.example.test',region_name='auto',
                aws_access_key_id='test',aws_secret_access_key='test',
                config=Config(retries={'total_max_attempts':3,'mode':mode})) as client:
            monkeypatch.setattr(client._endpoint.http_session,'send',send)
            monkeypatch.setattr('aiobotocore.endpoint.asyncio.sleep',sleep)
            monkeypatch.setattr('congress_api.retention.r2.random.random',lambda:.25)
            store=AsyncBodies(client,'bucket')
            if recover:assert await store.read(KEY)==DATA
            else:
                with pytest.raises(ConnectionResetError):await store.read(KEY)
    asyncio.run(check())
    assert len(calls)==3 and sleeps==[1.25,2.25]


@pytest.mark.parametrize('kind',['closed','timeout','endpoint','reset'])
def test_exhausted_get_aborts_the_ranged_reader_instead_of_becoming_pending(tmp_path,monkeypatch,kind):
    from congress_api.lake.readings import parse_once_payload
    from congress_api.retention.r2 import R2GetTransportExhausted
    from test_readings_ranged import phase,payload
    with closing(sdk_client('legacy')) as client:
        calls,sleeps=sdk_transport(monkeypatch,client,[transport_failure(kind)])
        with phase(tmp_path),pytest.raises(R2GetTransportExhausted):
            parse_once_payload(payload(tmp_path,DATA,DATA),body_store=R2Store(client,'bucket',read_throttle_attempts=5))
        assert len(calls)==5 and sleeps==[1.25,2.25,4.25,8.25]


@pytest.mark.parametrize('status,code',[(429,'ServiceUnavailable'),(503,'ServiceUnavailable'),(503,'SlowDown')])
@pytest.mark.parametrize('recover',[False,True])
def test_throttled_get_uses_five_attempts_without_multiplying_body_retries(monkeypatch,status,code,recover):
    sequence=[(status,code,{})]*4+([(200,'',{})] if recover else [(status,code,{})])
    with closing(sdk_client()) as client:
        calls,sleeps=sdk_transport(monkeypatch,client,sequence)
        store=R2Store(client,'bucket',read_throttle_attempts=5);timing={}
        if recover:assert store.read(KEY,expected=PIN,timing=timing)==DATA
        else:
            with pytest.raises(ClientError) as caught:store.read(KEY,expected=PIN,timing=timing)
            assert caught.value.response['ResponseMetadata']['RetryAttempts']==4
        assert len(calls)==5 and sleeps==[1.25,2.25,4.25,8.25]
        assert timing['requests']==1 and timing['sdk_retries']==4 and timing['sdk_retry_metadata_complete']
        assert timing['bytes']==(len(DATA) if recover else 0)
        assert all(request.headers['If-Match']==b'"'+PIN['md5'].encode()+b'"' for request in calls)


@pytest.mark.parametrize('status,code,extra',[
    (403,'AccessDenied',{}),(500,'InternalError',{}),(503,'AccessDenied',{}),
    (503,'SlowDown',{'retry-after':'61'}),
])
def test_other_get_errors_and_excessive_server_waits_do_not_gain_retries(monkeypatch,status,code,extra):
    with closing(sdk_client()) as client:
        calls,sleeps=sdk_transport(monkeypatch,client,[(status,code,extra)])
        with pytest.raises(ClientError):R2Store(client,'bucket',read_throttle_attempts=5).read(KEY,expected=PIN)
        assert len(calls)==1 and sleeps==[]


def test_d2_get_retry_budget_does_not_change_put_budget(monkeypatch):
    with closing(sdk_client()) as client:
        calls,sleeps=sdk_transport(monkeypatch,client,[(503,'ServiceUnavailable',{})])
        R2Store(client,'bucket',read_throttle_attempts=5)
        with pytest.raises(ClientError):client.put_object(Bucket='bucket',Key=KEY,Body=DATA)
        assert len(calls)==1 and sleeps==[]


@pytest.mark.parametrize('attempts',[0,-1,True,6])
def test_invalid_get_throttle_budget_refuses_before_read(attempts):
    client=Client()
    with pytest.raises(ValueError,match='throttle'):R2Store(client,'bucket',read_throttle_attempts=attempts)
    assert not client.reads


def test_persistent_worker_store_enables_the_get_budget(monkeypatch):
    from congress_api.lake.readings import _ranged_store
    from congress_shared.storage import R2Config
    with closing(sdk_client()) as client:
        calls,sleeps=sdk_transport(monkeypatch,client,[(503,'SlowDown',{}),(200,'',{})])
        monkeypatch.setattr(R2Config,'from_env',lambda **_:object())
        monkeypatch.setattr('congress_shared.storage.connect_r2',lambda _:client)
        _ranged_store.cache_clear()
        try:assert _ranged_store('fixture').read(KEY,expected=PIN)==DATA
        finally:_ranged_store.cache_clear()
        assert len(calls)==2 and sleeps==[1.25]


def test_cli_page_store_enables_the_same_get_budget(tmp_path,monkeypatch,capsys):
    from congress_api.cli.readings import main
    from congress_shared.storage import R2Config
    values=dict(captures=[],body_inventory=None,local_root=None,work=str(tmp_path/'work'),
        decided_at='2026-10-28T00:00:00Z',parser=None,
        apply=dict(catalog_root=str(tmp_path/'catalog'),table=dict(namespace=['fixture'],name='readings')))
    spec=tmp_path/'spec.json';spec.write_text(json.dumps(values))
    with closing(sdk_client()) as client:
        calls,sleeps=sdk_transport(monkeypatch,client,[(503,'SlowDown',{}),(200,'',{})])
        monkeypatch.setattr(R2Config,'from_env',lambda **_:object())
        monkeypatch.setattr('congress_shared.storage.connect_r2',lambda _:client)
        def run(**kwargs):
            assert kwargs['body_store'].read(KEY,expected=PIN)==DATA
            return dict(status='fixture-read-complete')
        monkeypatch.setattr('congress_api.lake.readings.run',run)
        assert main(['--spec',str(spec),'--engine-config',os.environ['DOCSPEC_JOB_CONFIG'],
            '--mode','backfill','--execute','--batch-size','32','--raw-bucket','bucket'])==0
        assert json.loads(capsys.readouterr().out)['status']=='fixture-read-complete'
        assert len(calls)==2 and sleeps==[1.25]


def test_transport_failure_after_a_throttle_marks_retry_measurement_incomplete(monkeypatch):
    from botocore.exceptions import ReadTimeoutError
    with closing(sdk_client()) as client:
        calls,sleeps=sdk_transport(monkeypatch,client,[(429,'ServiceUnavailable',{})])
        send=client._endpoint.http_session.send
        def fail_second(request):
            if calls:
                calls.append(request)
                raise ReadTimeoutError(endpoint_url='https://r2.example.test')
            return send(request)
        monkeypatch.setattr(client._endpoint.http_session,'send',fail_second)
        timing={}
        from congress_api.retention.r2 import R2GetTransportExhausted
        with pytest.raises(R2GetTransportExhausted) as caught:
            R2Store(client,'bucket',read_throttle_attempts=5).read(KEY,expected=PIN,timing=timing)
        assert isinstance(caught.value.__cause__,ReadTimeoutError)
        assert len(calls)==5 and sleeps==[1.25,2.25,4.25,8.25]
        assert timing['error_type']=='R2GetTransportExhausted' and timing['requests']==1
        assert timing['sdk_retry_metadata_complete'] is False
