import base64
import hashlib
import json
from pathlib import Path

import pytest

from congress_api.acquisition.admission import Admission,AdmissionDenied
from congress_api.acquisition.capture_journal import UnknownRemoteOutcome
from corpus_recovery.discovery_runtime import DiscoveryRuntime


class Response:
    def __init__(self,url,body,status=200):self.url,self.body,self.status_code,self.headers=url,body,status,{}
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def iter_content(self,chunk_size):
        for i in range(0,len(self.body),chunk_size):yield self.body[i:i+chunk_size]


class Session:
    def __init__(self,body):self.body,self.calls=body,[]
    def get(self,url,**kwargs):self.calls.append(('get',url,kwargs));return Response(url,self.body)
    def post(self,url,**kwargs):self.calls.append(('post',url,kwargs));return Response(url,self.body)


def runtime(tmp_path,session,cap=3):
    return DiscoveryRuntime(tmp_path/'journal',binding={'campaign':'test'},session=session,
        admission=Admission(tmp_path/'admission.sqlite',cap,100),resolve=lambda _:['8.8.8.8'])


def test_control_restart_retains_evidence_and_does_not_dispatch_again(tmp_path):
    session=Session(b'[]');first=runtime(tmp_path,session)
    url='https://web.archive.org/cdx/search/cdx?url=example.gov'
    a=first.control('cdx',url)
    b=runtime(tmp_path,session).control('cdx',url)
    assert a==b and len(session.calls)==1
    assert first.admission.totals()==dict(requests=1,committed_cost=0,unknown=0)
    with pytest.raises(ValueError):first.control('cdx','https://outside.example/index')


def test_binary_replay_remains_spooled_and_digest_verified(tmp_path):
    body=b'%PDF-1.7\x00\xff'+b'A'*(2<<20)
    session=Session(body);owner=runtime(tmp_path,session)
    original='https://example.gov/a.pdf';timestamp='20200102030405'
    candidate=dict(url=f'https://web.archive.org/web/{timestamp}id_/{original}',source='wayback',original_url=original,
        timestamp=timestamp,digest=base64.b32encode(hashlib.sha1(body).digest()).decode())
    fetched,operation=owner.replay(candidate)
    assert fetched.final.body.path.read_bytes()==body
    assert owner.replay(candidate)[1]==operation and len(session.calls)==1
    with pytest.raises(ValueError,match='digest'):owner.replay({**candidate,'digest':'A'*32})


def test_search_is_scoped_bounded_charged_and_not_exhaustive(tmp_path):
    body=json.dumps(dict(success=True,data=dict(web=[dict(url='https://example.gov/new.pdf')]))).encode()
    session=Session(body);owner=runtime(tmp_path,session)
    search=owner.search(api_key='test-only',upper_cost=7,result_limit=2)
    result=search('report-2020',None,('example.gov',))
    assert result['candidates']==['https://example.gov/new.pdf'] and not result['complete']
    assert session.calls[0][2]['json']['includeDomains']==['example.gov']
    assert owner.admission.totals()['committed_cost']==7
    assert search('report-2020',None,('example.gov',))==result and len(session.calls)==1
    assert 'test-only' not in ''.join(p.read_text(errors='ignore') for p in (tmp_path/'journal').rglob('*.json'))


def test_shared_request_cap_covers_search_and_archive(tmp_path):
    owner=runtime(tmp_path,Session(b'[]'),cap=1)
    owner.control('cdx','https://web.archive.org/cdx/search/cdx?url=a.gov')
    with pytest.raises(AdmissionDenied):owner.search(api_key='test',upper_cost=1)('name',None,('example.gov',))


def test_uncertain_remote_call_is_charged_and_never_silently_repeated(tmp_path):
    class Crash(Session):
        def get(self,*args,**kwargs):raise RuntimeError('unknown remote outcome')
    owner=runtime(tmp_path,Crash(b''));url='https://web.archive.org/cdx/search/cdx?url=a.gov'
    with pytest.raises(RuntimeError,match='unknown'):owner.control('cdx',url)
    with pytest.raises(UnknownRemoteOutcome):owner.control('cdx',url)
    assert owner.admission.totals()['unknown']==1


@pytest.mark.parametrize('bad_url',[
    'https://attacker.example/file',
    'https://web.archive.org/web/20210102030405id_/https://example.gov/a.pdf',
    'https://web.archive.org/web/20200102030405/https://example.gov/a.pdf',
    'https://web.archive.org/web/20200102030405id_/https://example.gov/other.pdf'])
def test_runtime_replay_refuses_wrong_host_original_time_or_mode(tmp_path,bad_url):
    session=Session(b'body');owner=runtime(tmp_path,session)
    with pytest.raises(ValueError,match='identity'):
        owner.replay(dict(source='wayback',url=bad_url,original_url='https://example.gov/a.pdf',timestamp='20200102030405'))
    assert session.calls==[] and owner.admission.totals()['requests']==0



def test_partial_timeout_keeps_discovery_reservation_unknown(tmp_path):
    import requests
    class Partial(Response):
        def iter_content(self,chunk_size):
            yield b'partial'
            raise requests.ReadTimeout('uncertain')
    class TimeoutSession(Session):
        def get(self,url,**kwargs):
            self.calls.append(url)
            return Partial(url,b'')
    session=TimeoutSession(b'');owner=runtime(tmp_path,session)
    url='https://web.archive.org/cdx/search/cdx?url=a.gov'
    with pytest.raises(UnknownRemoteOutcome):owner.control('cdx',url)
    with pytest.raises(UnknownRemoteOutcome):owner.control('cdx',url)
    assert len(session.calls)==1 and owner.admission.totals()['unknown']==1
