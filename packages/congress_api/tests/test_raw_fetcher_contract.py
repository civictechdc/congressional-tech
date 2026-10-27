"""B2 fetch fixtures: transfer facts, scope on every hop, bounded spool files."""
import base64
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

URL = 'https://docs.house.gov/a.pdf'


def parts():
    from congress_api.acquisition.fetcher import CaptureScope, Fetcher
    from congress_api.models.raw_fetch import Transfer
    return CaptureScope, Fetcher, Transfer


class Adapter:
    def __init__(self, responses):
        self.responses, self.calls = iter(responses), []

    def hop(self, url, destination, *, limit, headers):
        _, _, Transfer = parts()
        self.calls.append((url, limit, headers))
        values = next(self.responses)
        payload = values.pop('payload', b'%PDF-1.7\n%%EOF')
        destination.write_bytes(payload[:limit])
        return Transfer(path=destination, url=url, http_status=200,
                        headers={}, complete=len(payload) <= limit, **values)


def fetcher(tmp_path, responses, **options):
    CaptureScope, Fetcher, _ = parts()
    scope = CaptureScope([r'https://docs\.house\.gov/.*'], [], resolve=lambda host: ['8.8.8.8'])
    adapter = Adapter(responses)
    return Fetcher(scope=scope, direct=adapter, provider=options.pop('provider', None),
                   pace=lambda url, transport: None, directory=tmp_path, spool_limit=options.pop('spool_limit', 10**7),
                   **options), adapter


def test_six_redirects_are_followed_then_final_response(tmp_path):
    _, _, Transfer = parts()
    class Redirects:
        def __init__(self): self.calls = []
        def hop(self, url, destination, **options):
            self.calls.append(url)
            number = len(self.calls)
            destination.write_bytes(b'' if number < 7 else b'ok')
            return Transfer(destination, url, 302 if number < 7 else 201,
                            {'location': f'/{number}.pdf'} if number < 7 else {}, True)
    adapter = Redirects()
    f, _ = fetcher(tmp_path, [])
    f.direct = adapter
    result = f.fetch(URL)
    assert result.final.http_status == 201 and result.final.complete
    assert len(result.final.redirects) == 6 and len(adapter.calls) == 7
    assert result.final.body.size == 2


def test_seventh_redirect_stops(tmp_path):
    _, _, Transfer = parts()
    class Redirects:
        def __init__(self): self.calls = 0
        def hop(self, url, destination, **options):
            self.calls += 1
            destination.write_bytes(b'')
            return Transfer(destination, url, 302, {'location': '/next'}, True)
    f, _ = fetcher(tmp_path, [])
    f.direct = Redirects()
    assert f.fetch(URL).final.error == 'redirect_limit'
    assert f.direct.calls == 7


@pytest.mark.parametrize('url', ['http://127.0.0.1/a', 'http://169.254.169.254/a',
                                'https://user:password@docs.house.gov/a', 'https://other.gov/a'])
def test_initial_scope_refusal_before_adapter_io(tmp_path, url):
    f, adapter = fetcher(tmp_path, [])
    with pytest.raises(ValueError, match='scope'):
        f.fetch(url)
    assert not adapter.calls and list(tmp_path.iterdir()) == []


def test_private_dns_resolution_and_redirect_hop_are_refused(tmp_path):
    CaptureScope, _, Transfer = parts()
    assert not CaptureScope([r'https://docs\.house\.gov/.*'], [], resolve=lambda h: ['10.0.0.1'])(URL)
    class Redirect:
        def hop(self, url, destination, **kwargs):
            destination.write_bytes(b'')
            return Transfer(destination, url, 302, {'location': 'http://127.0.0.1/a'}, True)
    f, _ = fetcher(tmp_path, [])
    f.direct = Redirect()
    assert f.fetch(URL).final.error == 'excluded_redirect'


def test_provider_final_url_is_scope_checked_and_attempts_keep_own_facts(tmp_path):
    _, _, Transfer = parts()
    class Direct:
        def hop(self, url, destination, **kwargs):
            destination.write_bytes(b'cut off')
            return Transfer(destination, url, 200, {}, False, error='body_error')
    class Provider:
        def hop(self, url, destination, **kwargs):
            destination.write_bytes(b'provider result')
            return Transfer(destination, 'https://other.gov/a', 200, {}, True, provider_status=200)
    f, _ = fetcher(tmp_path, [], provider=Provider())
    f.direct = Direct()
    result = f.fetch(URL)
    assert result.final.error == 'excluded_redirect' and not result.final.complete
    assert result.prior_attempts[0].http_status == 200 and not result.prior_attempts[0].complete
    assert result.prior_attempts[0].body.path.read_bytes() == b'cut off'


def test_large_body_uses_bounded_chunks(tmp_path):
    from congress_api.transport.raw_adapters import DirectAdapter
    class Response:
        status_code, url, headers, capture_complete = 200, URL, {}, True
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def iter_content(self, chunk_size):
            assert chunk_size <= 1024**2
            for _ in range(70): yield b'x' * 1024**2
    class Session:
        def get(self, url, **kwargs):
            assert kwargs['allow_redirects'] is False and kwargs['stream'] is True
            return Response()
    result = DirectAdapter(Session()).hop(URL, tmp_path / 'body', limit=80*1024**2, headers={})
    assert result.complete and result.path.stat().st_size == 70*1024**2
    assert result.sha256 == hashlib.sha256(b'x' * 1024**2 * 70).hexdigest()


def test_provider_scalar_decodes_escaped_chunks_and_validates_metadata(tmp_path):
    from congress_api.transport.raw_adapters import decode_provider
    data = bytes(range(256)) * 5000
    payload = json.dumps(dict(url=URL, statusCode=201, httpResponseHeaders=[],
                              httpResponseBody=base64.b64encode(data).decode()))
    source = tmp_path / 'provider'
    source.write_text(payload.replace('/', r'\/'))
    metadata, digest, size = decode_provider(source, tmp_path / 'body', limit=len(data)+1, chunk_bytes=17)
    assert metadata['statusCode'] == 201 and metadata['httpResponseBody'] == ''
    assert (tmp_path / 'body').read_bytes() == data
    assert digest == hashlib.sha256(data).hexdigest() and size == len(data)
    source.write_text('{"httpResponseBody":"YQ==","httpResponseBody":"Yg==","statusCode":200}')
    with pytest.raises(ValueError): decode_provider(source, tmp_path / 'duplicate', limit=100)


@pytest.mark.parametrize('text', ['{"httpResponseBody":"YQ=="', '{"httpResponseBody":"??"}',
                                  '{"httpResponseBody":"YQ==","statusCode":"200"}',
                                  '{"httpResponseBody":"YQ==","statusCode":200,"x":{"httpResponseBody":"Yg=="}}'])
def test_provider_invalid_json_or_body_is_never_complete(tmp_path, text):
    from congress_api.transport.raw_adapters import decode_provider
    source = tmp_path / 'provider'
    source.write_text(text)
    with pytest.raises(ValueError): decode_provider(source, tmp_path / 'body', limit=100)


def test_range_requests_pin_every_range_with_if_range(tmp_path):
    from congress_api.transport.raw_adapters import download_ranges
    class Response:
        status_code, url = 206, URL
        def __init__(self, start, end): self.headers = {'content-range': f'bytes {start}-{end}/6', 'etag': '"v1"'}
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def iter_content(self, chunk_size): yield b'ab'
    class Session:
        def get(self, url, **kwargs):
            assert kwargs['headers']['If-Range'] == '"v1"'
            bounds = kwargs['headers']['Range'].split('=')[1].split('-')
            return Response(*map(int, bounds))
    result = download_ranges(Session(), URL, tmp_path / 'ranges', size=6, validator='"v1"', range_bytes=2)
    assert result.complete and result.path.read_bytes() == b'ababab'
    assert not (tmp_path / 'ranges.ranges.json').exists()


def test_host_registry_spaces_house_starts_and_honors_retry_after():
    from congress_api.acquisition.fetcher import HostPacer
    now, sleeps = [0.0], []
    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds
    pacer = HostPacer({'default_gap_seconds':0.2,'provider_gap_seconds':0,
                      'hosts':{'docs.house.gov':{'gap_seconds':1.2,'backoffs':{'403':60}}}},
                     clock=lambda:now[0],sleep=sleep,utc_now=lambda:0)
    pacer(URL,'direct')
    pacer(URL,'direct')
    assert sleeps[-1] == pytest.approx(1.2)
    pacer.observe(URL,'direct',403,{})
    pacer(URL,'direct')
    assert sleeps[-1] == pytest.approx(60)
    pacer.observe(URL,'direct',200,{'retry-after':'120'})
    pacer(URL,'direct')
    assert sleeps[-1] == pytest.approx(120)


def test_provider_adapter_disables_redirects_and_keeps_separate_status(tmp_path):
    from congress_api.transport.raw_adapters import ProviderAdapter
    class Response:
        status_code=200
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_content(self,chunk_size):
            yield json.dumps({'url':URL,'statusCode':302,'httpResponseBody':'',
                              'httpResponseHeaders':[{'name':'Location','value':'/next.pdf'}]}).encode()
    def request(payload):
        assert payload['followRedirect'] is False
        return Response()
    result=ProviderAdapter(request).hop(URL,tmp_path/'body',limit=1000,headers={})
    assert result.provider_status==200 and result.http_status==302 and result.complete
    assert result.headers['location']=='/next.pdf'


def test_range_entity_change_retains_only_incomplete_evidence(tmp_path):
    from congress_api.transport.raw_adapters import download_ranges
    class Response:
        status_code,url=206,URL
        headers={'content-range':'bytes 0-1/2','etag':'"changed"'}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_content(self,chunk_size):raise AssertionError('Do not read changed entity')
    class Session:
        def get(self,*args,**kwargs):return Response()
    result=download_ranges(Session(),URL,tmp_path/'body',size=2,validator='"old"')
    assert not result.complete and result.error=='range_entity_changed'
    assert result.path.read_bytes()==b''


def test_partial_http_response_is_not_a_complete_fetch(tmp_path):
    from congress_api.transport.raw_adapters import DirectAdapter
    class Response:
        status_code,url,headers=206,URL,{'content-range':'bytes 0-1/10'}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_content(self,chunk_size):yield b'ab'
    class Session:
        def get(self,*args,**kwargs):return Response()
    result=DirectAdapter(Session()).hop(URL,tmp_path/'body',limit=100,headers={})
    assert not result.complete and result.error=='partial_response'


def test_provider_combined_source_and_decoded_files_fit_spool_budget(tmp_path):
    from congress_api.transport.raw_adapters import ProviderAdapter
    class Response:
        status_code=200
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_content(self,chunk_size):
            yield json.dumps({'url':URL,'statusCode':200,'httpResponseBody':base64.b64encode(b'x'*1000).decode()}).encode()
    result=ProviderAdapter(lambda _:Response()).hop(URL,tmp_path/'body',limit=1500,headers={})
    assert not result.complete and result.error=='size_limit'
    assert sum(p.stat().st_size for p in tmp_path.iterdir()) <= 1500


@pytest.mark.parametrize(('status','headers'),[(206,[]),(200,[{'name':'Content-Range','value':'bytes 0-1/10'}])])
def test_provider_partial_publisher_response_is_incomplete(tmp_path,status,headers):
    from congress_api.transport.raw_adapters import ProviderAdapter
    class Response:
        status_code=200
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_content(self,chunk_size):
            yield json.dumps({'url':URL,'statusCode':status,'httpResponseHeaders':headers,
                              'httpResponseBody':base64.b64encode(b'ab').decode()}).encode()
    result=ProviderAdapter(lambda _:Response()).hop(URL,tmp_path/'body',limit=2000,headers={})
    assert not result.complete and result.error=='partial_response'
    assert result.http_status==status and result.provider_status==200
    assert result.path.read_bytes()==b'ab'


def test_waiting_host_does_not_block_other_hosts_or_retry_observations():
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from congress_api.acquisition.fetcher import HostPacer
    sleeping,released=threading.Event(),threading.Event()
    now=[0.0]
    def sleep(seconds):
        sleeping.set()
        assert released.wait(5)
        now[0]+=seconds
    pacer=HostPacer({'default_gap_seconds':0.2,'provider_gap_seconds':0,
                    'hosts':{'docs.house.gov':{'gap_seconds':1.2,'backoffs':{}}}},
                   clock=lambda:now[0],sleep=sleep,utc_now=lambda:0)
    pacer(URL,'direct')
    with ThreadPoolExecutor(max_workers=3) as pool:
        waiting=pool.submit(pacer,URL,'direct')
        assert sleeping.wait(2)
        other=pool.submit(pacer,'https://www.senate.gov/a','direct')
        observation=pool.submit(pacer.observe,URL,'direct',429,{'retry-after':'120'})
        try:
            other_finished=other.done() or other.exception(timeout=1) is None
            observation_finished=observation.done() or observation.exception(timeout=1) is None
        except TimeoutError:
            other_finished=other.done()
            observation_finished=observation.done()
        finally:
            released.set()
        waiting.result(timeout=2)
        other.result(timeout=2)
        observation.result(timeout=2)
    assert other_finished and observation_finished
    assert now[0] >= 120  # The waiting request rechecks a newly observed server deadline.
