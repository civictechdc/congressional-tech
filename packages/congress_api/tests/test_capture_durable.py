"""Actual runner continuation, process death, provider bytes and tiny budgets."""
import base64
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

import pytest

from congress_api.acquisition.capture_journal import DurableCapture,UnknownRemoteOutcome
from congress_api.acquisition.capture_scheduler import run_capture
from congress_api.acquisition.fetcher import Fetcher
from congress_api.models.raw_fetch import Transfer
from congress_api.retention.body_store import BodyStore,LocalAdapter
from congress_api.transport.raw_adapters import FirecrawlAdapter
from test_capture_scheduler import Adapter,ASOF,IDENTITY,LIMITS,engine,load,release

URL='https://fixture.test/document.pdf'
PDF=b'%PDF-1.7\nraw binary \x00\xff\n%%EOF'


def options(tmp_path,selected,adapter):
    return dict(release=selected,engine=engine(),work=tmp_path/'capture',as_of=ASOF,
        request_budget=10,byte_budget=1<<28,spool_budget=1<<28,
        store=BodyStore(LocalAdapter(tmp_path/'raw')),identity=IDENTITY,direct=adapter,
        resolve=lambda _:['8.8.8.8'],pace=lambda *_:None,archive_limits=LIMITS,discover=lambda *_:None)


@pytest.mark.parametrize('phase',['downloaded','body_ack','receipt_prepared','receipt_ack','committed'])
def test_sigkill_continues_actual_runner_without_repeat_download(tmp_path,phase):
    root=release(tmp_path,[dict(requested_url=URL,attempts=0)])
    tests=Path(__file__).parent
    code=f'''
import sys,os,signal,json
from pathlib import Path
sys.path.insert(0,{str(tests)!r})
from test_capture_durable import *
from congress_api.acquisition import capture_journal
from congress_api.retention.receipt_writer import ReceiptWriter
root=Path({str(tmp_path)!r})
phase={phase!r}
class Counting(Adapter):
    def hop(self,*args,**kwargs):
        with (root/'network-calls').open('a') as log:log.write('call\\n');log.flush();os.fsync(log.fileno())
        return super().hop(*args,**kwargs)
class KillAdapter(LocalAdapter):
    def create(self,key,source,**facts):
        value=super().create(key,source,**facts)
        if value and (phase=='body_ack' and key.startswith('bodies/') or phase=='receipt_ack' and key.startswith('receipts/')):
            os.kill(os.getpid(),signal.SIGKILL)
        return value
if phase in {'downloaded','committed'}:
    original=capture_journal.durable_json
    def durable(path,value):
        original(path,value)
        if Path(path).name==('downloaded.json' if phase=='downloaded' else 'committed.json'):os.kill(os.getpid(),signal.SIGKILL)
    capture_journal.durable_json=durable
if phase=='receipt_prepared':
    def kill(*args,**kwargs):os.kill(os.getpid(),signal.SIGKILL)
    ReceiptWriter._apply_frozen=kill
selected=load(root/'release',root/'read')
kwargs=options(root,selected,Counting({{URL:(200,PDF,{{'content-type':'application/pdf'}})}}))
kwargs['store']=BodyStore(KillAdapter(root/'raw'))
kwargs['request_budget']=1
run_capture(**kwargs)
'''
    child=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True)
    assert child.returncode==-signal.SIGKILL,child.stderr
    assert (tmp_path/'network-calls').read_text()=='call\n'
    adapter=Adapter({URL:(200,PDF,{'content-type':'application/pdf'})})
    selected=load(root,tmp_path/'fresh-read')
    kwargs=options(tmp_path,selected,adapter);kwargs['request_budget']=1
    result=run_capture(**kwargs)
    assert adapter.calls==[]
    assert result['captures']==1 and result['requests']==1
    assert len(list((tmp_path/'raw/receipts').rglob('*.jsonl.gz')))==1
    assert not list((tmp_path/'capture/attempts').rglob('*.sealed'))
    assert not list((tmp_path/'capture').glob('raw-receipt-*'))
    again=run_capture(**kwargs)
    assert again['captures']==1 and again['requests']==1 and adapter.calls==[]


def test_one_request_cap_permits_one_completed_direct_capture(tmp_path):
    selected=load(release(tmp_path,[dict(requested_url=URL,attempts=0)]),tmp_path/'read')
    adapter=Adapter({URL:(200,PDF,{'content-type':'application/pdf'})})
    kwargs=options(tmp_path,selected,adapter);kwargs['request_budget']=1
    result=run_capture(**kwargs)
    assert result['requests']==1 and result['captures']==1


def test_unknown_outcome_is_protected_and_one_explicit_retry_is_bounded(tmp_path):
    journal=DurableCapture(tmp_path/'journal',{'campaign':'one'})
    class Unknown:
        def hop(self,*args,**kwargs):raise RuntimeError('connection lost')
    def factory(root):return Fetcher(scope=lambda _:True,direct=Unknown(),provider=None,pace=lambda *_:None,directory=root,spool_limit=100)
    with pytest.raises(RuntimeError):journal.fetch('operation',URL,factory)
    with pytest.raises(UnknownRemoteOutcome):journal.fetch('operation',URL,factory)
    with pytest.raises(ValueError,match='protected'):journal.cleanup('operation')
    journal.retry_unknown('operation','direct',0,reason='Reviewed bounded retry; prior request remains charged')
    with pytest.raises(RuntimeError):journal.fetch('operation',URL,factory)
    with pytest.raises(ValueError,match='one bounded'):journal.retry_unknown('operation','direct',0,reason='again')


class Response:
    status_code=200
    def __init__(self,payload):self.payload=payload
    def __enter__(self):return self
    def __exit__(self,*_):pass
    def iter_content(self,chunk_size):
        data=json.dumps(self.payload).encode()
        for index in range(0,len(data),7):yield data[index:index+7]


def test_firecrawl_raw_base64_and_three_rung_wall_mismatch(tmp_path):
    payload={'success':True,'data':{'rawBase64':base64.b64encode(PDF).decode(),
             'metadata':{'sourceURL':URL,'url':URL,'statusCode':200}}}
    calls=[]
    def request(body):calls.append(body);return Response(payload)
    direct=Adapter({URL:(200,b'<html>Access denied captcha</html>',{'content-type':'text/html'})})
    zyte=Adapter({URL:(200,b'<html>Just a moment</html>',{'content-type':'text/html'})})
    fetcher=Fetcher(scope=lambda u:u==URL,direct=direct,provider=zyte,firecrawl=FirecrawlAdapter(request),
                    pace=lambda *_:None,directory=tmp_path/'spool',spool_limit=10000)
    result=fetcher.fetch(URL)
    assert result.final.transport=='firecrawl' and result.final.body.path.read_bytes()==PDF
    assert len(result.prior_attempts)==2 and calls[0]['formats']==['rawBase64'] and calls[0]['parsers']==[]


@pytest.mark.parametrize('replacement',[{'statusCode':True},{'statusCode':999},{'url':'https://outside.invalid/file'},{'rawBase64':'%%%'}])
def test_firecrawl_invalid_metadata_and_body_never_yield_valid_capture(tmp_path,replacement):
    payload={'success':True,'data':{'rawBase64':base64.b64encode(PDF).decode(),
             'metadata':{'sourceURL':URL,'url':URL,'statusCode':200}}}
    if 'rawBase64' in replacement:payload['data'].update(replacement)
    else:payload['data']['metadata'].update(replacement)
    direct=Adapter({URL:(403,b'denied',{})})
    result=Fetcher(scope=lambda u:u==URL,direct=direct,provider=None,firecrawl=FirecrawlAdapter(lambda _:Response(payload)),
        pace=lambda *_:None,directory=tmp_path/'spool',spool_limit=10000).fetch(URL)
    assert not result.final.complete


def test_paid_cli_executes_configured_mocked_binary_ladder_and_resumes(tmp_path,monkeypatch,capsys):
    """The public parser reaches the real durable runner without a live request."""
    from congress_api.cli import capture_schedule
    from congress_api.acquisition import capture_scheduler
    root=release(tmp_path,[dict(requested_url=URL,attempts=0)])
    monkeypatch.setenv('ZYTE_TOKEN','local-fixture-only')
    monkeypatch.setenv('FIRECRAWL_API_KEY','local-fixture-only')
    monkeypatch.setattr(capture_schedule,'writer_identity',lambda *_:IDENTITY)
    monkeypatch.setattr(capture_scheduler,'resolve_host',lambda _:['8.8.8.8'])
    # The function default was bound before monkeypatching. Supply only the
    # offline resolver and pacer; preserve the actual runner and provider code.
    original=capture_schedule.run_capture
    monkeypatch.setattr(capture_schedule,'run_capture',lambda *a,**k:original(*a,**k,resolve=lambda _:['8.8.8.8'],pace=lambda *_:None,archive_limits=LIMITS))
    calls=[]
    class DirectResponse(Response):
        status_code=403;url=URL;headers={}
        def iter_content(self,chunk_size):yield b'access denied'
    class Session:
        def __enter__(self):return self
        def __exit__(self,*_):pass
        def get(self,url,**kwargs):calls.append('direct');return DirectResponse({})
        def post(self,url,**kwargs):
            if 'zyte' in url:
                calls.append('zyte')
                return Response({'url':URL,'statusCode':403,'httpResponseBody':base64.b64encode(b'access denied').decode()})
            calls.append('firecrawl')
            return Response({'success':True,'data':{'rawBase64':base64.b64encode(PDF).decode(),
                'metadata':{'sourceURL':URL,'url':URL,'statusCode':200}}})
    import requests
    monkeypatch.setattr(requests,'Session',Session)
    args=['--release-root',str(root),'--engine-config',os.environ['DOCSPEC_JOB_CONFIG'],
          '--request-budget','3','--byte-budget',str(1<<28),'--spool-budget',str(1<<28),
          '--work',str(tmp_path/'cli'),'--local-store',str(tmp_path/'raw'),
          '--fetcher-binary',str(tmp_path/'no-native-fetcher'),'--spend-cap-micros','20',
          '--zyte-cost-bound-micros','7','--firecrawl-cost-bound-micros','11','--admission-db',str(tmp_path/'shared-ledger.sqlite'),'--apply']
    capture_schedule.main(args)
    first=json.loads(capsys.readouterr().out)
    assert first['captures']==1 and first['admission']=={'requests':3,'committed_cost':18,'unknown':0}
    assert calls==['direct','zyte','firecrawl']
    capture_schedule.main(args)
    again=json.loads(capsys.readouterr().out)
    assert again['captures']==1 and calls==['direct','zyte','firecrawl']
    changed=list(args);changed[changed.index('--admission-db')+1]=str(tmp_path/'other-ledger.sqlite')
    with pytest.raises(ValueError,match='continuation inputs changed'):capture_schedule.main(changed)
    assert calls==['direct','zyte','firecrawl']
    direct_only=list(args)
    for flag in ('--zyte-cost-bound-micros','--firecrawl-cost-bound-micros'):
        index=direct_only.index(flag);del direct_only[index:index+2]
    direct_only[direct_only.index('--work')+1]=str(tmp_path/'direct-only-cli')
    capture_schedule.main(direct_only)
    direct_result=json.loads(capsys.readouterr().out)
    assert direct_result['requests']==3 and direct_result['captures']==0
    assert calls==['direct','zyte','firecrawl']
    # Run the actual discovery CLI against the same spent ledger. Its native
    # membership check succeeds; admission must refuse before any HTTP call.
    import pyarrow as pa
    import pyarrow.parquet as pq
    from corpus_recovery import discovery_runtime
    from congress_api.acquisition.admission import AdmissionDenied
    targets=tmp_path/'discovery-targets.parquet';candidates=tmp_path/'discovery-candidates.parquet'
    pq.write_table(pa.table({'target_url':[URL]}),targets)
    pq.write_table(pa.table({'target_url':pa.array([],type=pa.string()),'candidate_url':pa.array([],type=pa.string())}),candidates)
    def pin(path):return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    descriptor=tmp_path/'discovery-campaign.json'
    descriptor.write_text(json.dumps(dict(version=1,campaign_id='shared-cli',requirement='historical_exact',
        target_table='targets',candidate_table='candidates',tables={'targets':pin(targets),'candidates':pin(candidates)})))
    runtime=discovery_runtime.DiscoveryRuntime
    monkeypatch.setattr(discovery_runtime,'DiscoveryRuntime',lambda *a,**k:runtime(*a,**k,resolve=lambda _:['8.8.8.8']))
    with pytest.raises(AdmissionDenied):discovery_runtime.main([
        '--campaign',str(descriptor),'--target',URL,'--work',str(tmp_path/'discovery-cli'),
        '--runtime',os.environ['DOCSPEC_JOB_CONFIG'],'--source','wayback','--max-pages','1',
        '--request-cap','3','--spend-cap-micros','20','--admission-db',str(tmp_path/'shared-ledger.sqlite')])
    assert calls==['direct','zyte','firecrawl']


def test_common_admission_charges_discovery_and_stops_paid_rung_at_cap(tmp_path):
    from congress_api.acquisition.admission import Admission
    selected=load(release(tmp_path,[dict(requested_url=URL,attempts=0)]),tmp_path/'read')
    shared=Admission(tmp_path/'shared.sqlite',3,8)
    discovery=shared.reserve('cdx',2);shared.settle(discovery,2)
    direct=Adapter({URL:(403,b'denied',{})});zyte=Adapter({URL:(403,b'denied',{})});fire=Adapter({URL:(200,PDF,{})})
    kwargs=options(tmp_path,selected,direct)
    kwargs.update(request_budget=3,provider=zyte,provider_cost=6,firecrawl=fire,firecrawl_cost=1,admission=shared)
    result=run_capture(**kwargs)
    assert result['stop_reason']=='request_or_spend_budget'
    assert shared.totals()=={'requests':3,'committed_cost':8,'unknown':0}
    assert len(direct.calls)==len(zyte.calls)==1 and not fire.calls
    assert not list((tmp_path/'capture/attempts').rglob('firecrawl-0.json'))


def test_provenance_stage_replays_exact_bytes_and_refuses_conflict(tmp_path):
    from congress_api.retention.provenance import stage_records,finish_stage,apply_staged
    # Reuse the real schema fixture, not a permissive fake validator.
    from test_provenance_contract import recovery
    row=recovery()
    stage=tmp_path/'stage'
    key,count=stage_records(stage,'recoveries',[row],decided_at='2026-10-27T12:00:00Z')
    finish_stage(stage,kind='recoveries',provenance=key,records=count,inputs=[])
    class LostAck(LocalAdapter):
        def create(self,key,source,**facts):
            created=super().create(key,source,**facts)
            if created:raise OSError('lost provenance acknowledgment')
            return created
    store=BodyStore(LostAck(tmp_path/'raw'))
    assert apply_staged(stage,store)=={'objects':1,'records':1}
    assert apply_staged(stage,BodyStore(LocalAdapter(tmp_path/'raw')))=={'objects':1,'records':1}
    assert len(list((tmp_path/'raw/provenance').rglob('*.jsonl')))==1
    (tmp_path/'raw'/key).write_text(json.dumps(dict(row,identity_note='conflicting bytes'))+'\n')
    with pytest.raises(RuntimeError):apply_staged(stage,BodyStore(LocalAdapter(tmp_path/'raw')))


@pytest.mark.parametrize('code',[401,402,403,429,500])
def test_provider_account_errors_stop_before_another_paid_provider(tmp_path,code):
    class AccountFailure:
        def hop(self,url,destination,**kwargs):
            destination.write_bytes(b'account denied')
            return Transfer(destination,url,None,{},False,
                'provider_credits' if code==402 else 'provider_quota' if code==429 else 'provider_http_error',provider_status=code)
    direct=Adapter({URL:(403,b'origin denied',{})});fire=Adapter({URL:(200,PDF,{})})
    result=Fetcher(scope=lambda _:True,direct=direct,provider=AccountFailure(),firecrawl=fire,
        pace=lambda *_:None,directory=tmp_path/'spool',spool_limit=1000).fetch(URL)
    assert result.final.transport=='zyte' and not fire.calls


@pytest.mark.parametrize('error_kind',['timeout','oserror','partial_response_timeout','partial_ssl_stream'])
def test_unknown_partial_network_outcome_blocks_escalation_and_retry_preserves_charges(tmp_path,error_kind):
    import requests
    from congress_api.acquisition.admission import Admission
    selected=load(release(tmp_path,[dict(requested_url=URL,attempts=0)]),tmp_path/'read')
    admission=Admission(tmp_path/'admission.sqlite',10,100)
    class Partial:
        calls=0
        def hop(self,url,destination,**kwargs):
            self.calls+=1
            if error_kind=='partial_ssl_stream':
                from congress_api.transport.raw_adapters import DirectAdapter
                class SSLResponse:
                    status_code=200;headers={}
                    def __enter__(self):self.url=url;return self
                    def __exit__(self,*_):pass
                    def iter_content(self,chunk_size):
                        yield b'partial bytes'
                        raise requests.exceptions.SSLError('uncertain TLS stream')
                class Session:
                    def get(self,*a,**k):return SSLResponse()
                return DirectAdapter(Session()).hop(url,destination,**kwargs)
            with destination.open('xb') as target:target.write(b'partial bytes');target.flush();os.fsync(target.fileno())
            if error_kind=='timeout':raise requests.Timeout('remote outcome unknown')
            if error_kind=='oserror':raise OSError('disk/connection outcome unknown')
            return Transfer(destination,url,200,{},False,'ReadTimeout')
    partial=Partial();paid=Adapter({URL:(200,PDF,{})})
    kwargs=options(tmp_path,selected,partial);kwargs.update(admission=admission,provider=paid,provider_cost=10)
    with pytest.raises(UnknownRemoteOutcome):run_capture(**kwargs)
    assert partial.calls==1 and not paid.calls
    assert admission.totals()=={'requests':1,'committed_cost':0,'unknown':1}
    operation=next((tmp_path/'capture/attempts').glob('*/request.json')).parent
    started=json.loads((operation/'direct-0.json').read_text())
    assert started['phase']=='started' and started['partial']['size']==13 and started['reservation_id']
    with pytest.raises(UnknownRemoteOutcome):run_capture(**kwargs)
    assert partial.calls==1
    binding=json.loads((tmp_path/'capture/attempts/binding.json').read_text())
    journal=DurableCapture(tmp_path/'capture/attempts',binding)
    journal.retry_unknown(operation.name,'direct',0,reason='Bounded reviewed retry; original remains unknown and charged')
    assert (operation/'quarantine/direct-0.body').read_bytes()==b'partial bytes'
    replacement=Adapter({URL:(200,PDF,{'content-type':'application/pdf'})})
    kwargs['direct']=replacement
    result=run_capture(**kwargs)
    assert result['captures']==1 and replacement.calls==[URL] and not paid.calls
    assert admission.totals()=={'requests':2,'committed_cost':0,'unknown':1}
    assert (operation/'quarantine/direct-0.body').read_bytes()==b'partial bytes'


def test_inflight_reservations_prevent_replacement_worker_byte_overdispatch(tmp_path):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    # Each of A/B consumes its complete 1/2 share through seven real redirect
    # hops. A completes while B is paused; C must not spend B's held bytes.
    urls={name:f'https://fixture.test/{name}' for name in 'abc'}
    selected=load(release(tmp_path,[dict(requested_url=url,attempts=0) for url in urls.values()]),tmp_path/'read')
    b_started=threading.Event();release_b=threading.Event();c_started=threading.Event()
    calls=[];call_lock=threading.Lock();size=200
    class Interleaved:
        def hop(self,url,destination,*,limit,headers):
            name=url.split('/')[-1][0];step=int(url.rsplit('-',1)[1]) if '-' in url.split('/')[-1] else 0
            with call_lock:calls.append(url)
            if name=='b' and step==0:
                b_started.set();assert release_b.wait(10)
            if name=='a' and step==6:assert b_started.wait(10)
            if name=='c':c_started.set()
            assert limit>=size
            destination.write_bytes(b'x'*size)
            if step<6:return Transfer(destination,url,302,{'location':f'/{name}-{step+1}'},True,size=size)
            return Transfer(destination,url,200,{},True,size=size)
    kwargs=options(tmp_path,selected,Interleaved());kwargs.update(workers=2,byte_budget=2800,request_budget=100)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(run_capture,**kwargs)
        assert b_started.wait(10)
        # Observe durable completion, then give the dispatcher an opportunity
        # to replace A while B still holds its complete reservation.
        deadline=__import__('time').monotonic()+10
        while not list((tmp_path/'capture/attempts').glob('*/committed.json')):
            assert __import__('time').monotonic()<deadline
            __import__('time').sleep(.01)
        assert not c_started.wait(.2)
        release_b.set();result=future.result(timeout=10)
    assert result['captures']==2 and result['fetched_bytes']==2800
    assert result['wire_admission']['committed_cost']==2800 and result['wire_admission']['unknown']==0
    assert len(calls)==14 and not c_started.is_set()


def test_byte_cap_spent_after_redirect_chain_does_not_block_sealed_resume(tmp_path):
    import threading
    from congress_api.retention.receipt_writer import ReceiptWriter
    selected=load(release(tmp_path,[dict(requested_url=URL,attempts=0)]),tmp_path/'read')
    responses={URL:(302,b'x'*len(PDF),{'location':'/hop-1'})}
    for index in range(1,6):responses[f'https://fixture.test/hop-{index}']=(302,b'x'*len(PDF),{'location':f'/hop-{index+1}'})
    responses['https://fixture.test/hop-6']=(200,PDF,{'content-type':'application/pdf'})
    adapter=Adapter(responses);kwargs=options(tmp_path,selected,adapter)
    kwargs.update(byte_budget=7*len(PDF),request_budget=7)
    original=ReceiptWriter.write
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ReceiptWriter,'write',lambda *_a,**_k:(_ for _ in ()).throw(OSError('after sealed download')))
        with pytest.raises(OSError):run_capture(**kwargs)
    assert len(adapter.calls)==7
    result=run_capture(**kwargs)
    assert result['captures']==1 and result['requests']==7 and len(adapter.calls)==7
    assert result['wire_admission']['committed_cost']==7*len(PDF)


def test_uncertain_paid_provider_preserves_full_cost_and_never_calls_next_provider(tmp_path):
    import requests
    from congress_api.acquisition.admission import Admission
    selected=load(release(tmp_path,[dict(requested_url=URL,attempts=0)]),tmp_path/'read')
    shared=Admission(tmp_path/'budget.sqlite',10,20)
    class PaidTimeout:
        calls=0
        def hop(self,url,destination,**kwargs):
            self.calls+=1;destination.write_bytes(b'partial provider response')
            raise requests.Timeout('unknown paid outcome')
    provider=PaidTimeout();fire=Adapter({URL:(200,PDF,{})})
    kwargs=options(tmp_path,selected,Adapter({URL:(403,b'denied',{})}))
    kwargs.update(provider=provider,provider_cost=7,firecrawl=fire,firecrawl_cost=11,admission=shared)
    with pytest.raises(UnknownRemoteOutcome):run_capture(**kwargs)
    assert shared.totals()=={'requests':2,'committed_cost':7,'unknown':1}
    with pytest.raises(UnknownRemoteOutcome):run_capture(**kwargs)
    assert provider.calls==1 and not fire.calls


def test_provider_invalid_metadata_does_not_trigger_another_paid_rung(tmp_path):
    from congress_api.transport.raw_adapters import ProviderAdapter
    fire=Adapter({URL:(200,PDF,{})})
    result=Fetcher(scope=lambda u:u==URL,direct=Adapter({URL:(403,b'denied',{})}),
        provider=ProviderAdapter(lambda _:Response({'statusCode':True,'url':URL,'httpResponseBody':'YQ=='})),
        firecrawl=fire,pace=lambda *_:None,directory=tmp_path/'spool',spool_limit=1000).fetch(URL)
    assert result.final.error=='invalid_provider_response' and not fire.calls


def test_restored_earlier_discovery_cannot_starve_downloaded_cap_continuation(tmp_path):
    # Two records have spent the complete request cap. A committed page points
    # to an earlier new URL; B's sealed download must finish before new work.
    from congress_api.retention.receipt_writer import ReceiptWriter
    urls=['https://fixture.test/a','https://fixture.test/z']
    selected=load(release(tmp_path,[dict(requested_url=url,attempts=0) for url in urls]),tmp_path/'read')
    responses={urls[0]:(200,b'<html><a href="/0">earlier new work</a></html>',{'content-type':'text/html'}),
               urls[1]:(200,PDF,{'content-type':'application/pdf'})}
    adapter=Adapter(responses);kwargs=options(tmp_path,selected,adapter)
    from test_capture_scheduler import fixture_discover
    kwargs.update(request_budget=2,workers=2,discover=fixture_discover)
    original=ReceiptWriter.write
    def fail_b(self,result,*args,**kw):
        if result.final.requested_url==urls[1]:raise OSError('download completed before receipt')
        return original(self,result,*args,**kw)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ReceiptWriter,'write',fail_b)
        with pytest.raises(OSError):run_capture(**kwargs)
    assert sorted(adapter.calls)==urls
    calls=list(adapter.calls)
    result=run_capture(**kwargs)
    assert result['captures']==2 and result['requests']==2 and adapter.calls==calls


def test_protected_quarantine_consumes_scratch_admission_for_new_work(tmp_path):
    selected=load(release(tmp_path,[dict(requested_url=URL,attempts=0)]),tmp_path/'read')
    adapter=Adapter({URL:(200,PDF,{})});kwargs=options(tmp_path,selected,adapter)
    # Establish the real bound journal without starting acquisition, then add
    # protected evidence representing previous uncertain, charged operations.
    kwargs['spool_budget']=20<<20
    first=run_capture(**kwargs)
    assert first['captures']==1
    # A second due URL enters through retained committed discovery so the
    # release/campaign identity and budget configuration remain unchanged.
    committed=next((tmp_path/'capture/attempts').glob('*/committed.json'))
    record=json.loads(committed.read_text());record['links']=[dict(href='https://fixture.test/new',base_href=None,
        context=URL,source=record['key'],pointer='[0]')];committed.write_text(json.dumps(record))
    protected=tmp_path/'capture/attempts'/'quarantined-old-operation'/'quarantine'/'direct-0.body'
    protected.parent.mkdir(parents=True);protected.write_bytes(b'x'*(5<<20))
    result=run_capture(**kwargs)
    assert result['captures']==1 and adapter.calls==[URL]
    assert result['protected_scratch_bytes']==5<<20
    assert result['stop_reason']=='byte_or_spool_budget' and protected.exists()


def test_unknown_retry_reserves_new_spool_alongside_protected_partial(tmp_path):
    import requests
    selected=load(release(tmp_path,[dict(requested_url=URL,attempts=0)]),tmp_path/'read')
    class Partial:
        def hop(self,url,destination,*,limit,headers):
            assert limit>=1<<20
            destination.write_bytes(b'x'*(1<<20));raise requests.Timeout('unknown')
    kwargs=options(tmp_path,selected,Partial());kwargs['spool_budget']=20<<20
    with pytest.raises(UnknownRemoteOutcome):run_capture(**kwargs)
    journal=DurableCapture(tmp_path/'capture/attempts',json.loads((tmp_path/'capture/attempts/binding.json').read_text()))
    operation=next((tmp_path/'capture/attempts').glob('*/request.json')).parent
    journal.retry_unknown(operation.name,'direct',0,reason='one bounded retry')
    replacement=Adapter({URL:(200,PDF,{})});kwargs['direct']=replacement
    result=run_capture(**kwargs)
    assert result['stop_reason']=='byte_or_spool_budget' and not replacement.calls
    assert result['protected_scratch_bytes']==1<<20
    assert (operation/'quarantine/direct-0.body').stat().st_size==1<<20
    assert result['admission']['requests']==1 and result['admission']['unknown']==1


def test_due_retry_timestamp_does_not_enter_durable_control_json(tmp_path):
    from datetime import datetime,timezone
    selected=load(release(tmp_path,[dict(requested_url=URL,attempts=2,last_outcome='failed',
        next_attempt_at=datetime(2026,10,1,tzinfo=timezone.utc))]),tmp_path/'read')
    adapter=Adapter({URL:(200,PDF,{'content-type':'application/pdf'})})
    result=run_capture(**options(tmp_path,selected,adapter))
    assert result['captures']==1 and adapter.calls==[URL]
    saved=json.loads(next((tmp_path/'capture/attempts').glob('*/request.json')).read_text())
    assert set(saved['row'])=={'requested_url','priority','observations'}


def test_terminal_provider_failure_defers_remaining_queue_before_more_paid_calls(tmp_path):
    from congress_api.acquisition.admission import Admission
    urls=['https://fixture.test/a','https://fixture.test/b']
    selected=load(release(tmp_path,[dict(requested_url=url,attempts=0) for url in urls]),tmp_path/'read')
    direct=Adapter({url:(403,b'origin denied',{}) for url in urls})
    class Quota:
        calls=[]
        def hop(self,url,destination,**kwargs):
            self.calls.append(url);destination.write_bytes(b'quota exhausted')
            return Transfer(destination,url,None,{},False,'provider_quota',provider_status=429)
    provider=Quota();fire=Adapter({url:(200,PDF,{}) for url in urls})
    kwargs=options(tmp_path,selected,direct)
    kwargs.update(provider=provider,provider_cost=7,firecrawl=fire,firecrawl_cost=11,
                  admission=Admission(tmp_path/'shared.sqlite',10,50))
    result=run_capture(**kwargs)
    assert result['stop_reason']=='provider_unavailable' and result['captures']==1
    assert direct.calls==provider.calls==[urls[0]] and not fire.calls
    assert result['admission']=={'requests':2,'committed_cost':7,'unknown':0}
    again=run_capture(**kwargs)
    assert again['stop_reason']=='provider_unavailable' and again['captures']==1
    assert direct.calls==provider.calls==[urls[0]] and not fire.calls


def test_saved_terminal_provider_response_blocks_fresh_calls_before_receipt_replay(tmp_path):
    import threading,time
    from congress_api.acquisition.admission import Admission
    from congress_api.retention.receipt_writer import ReceiptWriter
    urls=[f'https://fixture.test/{name}' for name in 'abc']
    selected=load(release(tmp_path,[dict(requested_url=url,attempts=0) for url in urls]),tmp_path/'read')
    b_started=threading.Event();direct_calls=[];paid_calls=[]
    class Direct:
        def hop(self,url,destination,**kwargs):
            direct_calls.append(url)
            if url==urls[1]:b_started.set();time.sleep(.05)
            data=PDF if url==urls[1] else b'denied'
            destination.write_bytes(data)
            return Transfer(destination,url,200 if url==urls[1] else 403,{},True,size=len(data))
    class Quota:
        def hop(self,url,destination,**kwargs):
            paid_calls.append(url);assert b_started.wait(10);destination.write_bytes(b'quota')
            return Transfer(destination,url,None,{},False,'provider_quota',provider_status=429)
    kwargs=options(tmp_path,selected,Direct());kwargs.update(workers=2,provider=Quota(),provider_cost=7,
        admission=Admission(tmp_path/'ledger.sqlite',20,100))
    original=ReceiptWriter.write
    def fail(self,result,*a,**k):
        if result.final.requested_url==urls[0]:raise OSError('terminal response sealed before receipt')
        return original(self,result,*a,**k)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ReceiptWriter,'write',fail)
        with pytest.raises(OSError):run_capture(**kwargs)
    assert sorted(direct_calls)==urls[:2] and paid_calls==[urls[0]]
    before=list(direct_calls)
    def slow_replay(self,result,*a,**k):
        if result.final.requested_url==urls[0]:time.sleep(.2)
        return original(self,result,*a,**k)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ReceiptWriter,'write',slow_replay)
        result=run_capture(**kwargs)
    assert result['captures']==2 and result['stop_reason']=='provider_unavailable'
    assert direct_calls==before and paid_calls==[urls[0]]
