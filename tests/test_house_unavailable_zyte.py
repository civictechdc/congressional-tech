"""Bounded recovery of retained unavailable requests, without live network."""
from copy import deepcopy
from types import SimpleNamespace
from threading import Event
import base64
import json

import pytest
import requests
from congress_api.acquisition import house, house_sites
from congress_api.models.content import RawContent, content_bytes
from congress_api.parsers.committee_discovery import key, task
from congress_api.transport import http
from test_house_sites import client, TODAY, DIRECTORY, HOME, BODY

HOST = 'energycommerce.house.gov'
URL = HOME + 'events/recover'


def unavailable(*, kind='event', body=None, status=404):
    item = task(URL, kind, body=body)
    receipt = dict(url=URL, status_code=status, outcome='not_found', completed_at='old')
    if body is not None:
        receipt.update(method='POST', request_json=body)
    source = dict(url=URL, kind=kind, status=status, receipts=[receipt],
                  content=RawContent.from_bytes(b'old absence', 'text/html').source_dict())
    state = {HOST: dict(home=HOME, pages={}, sources={key(item): source}, pending=[],
                       done={key(item): dict(url=URL, kind=kind)}, errors={},
                       discovery_checked='2026-10-07', pagination={'old': {}}, parser_version=6)}
    return state, [{'site': HOST, 'request': item}]


@pytest.mark.parametrize('kind,status', [('event',404), ('event',410), ('sitemap',404)])
def test_recorded_unavailable_is_a_bounded_retry_without_synthetic_failure(kind, status):
    state, manifest = unavailable(kind=kind, status=status)
    get, calls = client({URL: BODY if kind == 'event' else b'<urlset/>'})
    result = house_sites.collect(DIRECTORY, state, today=TODAY, get=get, retry_requests=manifest)
    assert result['requests'] == 1 and result['failed'] == result['pending'] == 0
    saved = state[HOST]
    assert not saved['errors'] and not saved.get('resolved_errors')
    assert saved['discovery_checked'] == '2026-10-07' and saved['pagination'] == {'old': {}}
    assert len(saved['sources'][key(manifest[0]['request'])]['receipts']) == 2
    house_sites.collect(DIRECTORY, state, today=TODAY, get=get, retry_requests=manifest)
    assert len(calls) == 1


def test_recorded_unavailable_post_preserves_key_body_and_rejects_alteration():
    query = {'offset': 20, 'limit': 20}
    state, manifest = unavailable(kind='calendar_api', body=query)
    before = deepcopy(state)
    bad = deepcopy(manifest); bad[0]['request']['body']['offset'] = 40
    with pytest.raises(ValueError):
        house_sites.collect(DIRECTORY, state, today=TODAY, get=lambda *a, **k: pytest.fail('No network'), retry_requests=bad)
    assert state == before
    get, calls = client({URL: b'{"events_connection":{"nodes":[]}}'})
    house_sites.collect(DIRECTORY, state, today=TODAY, get=get, retry_requests=manifest)
    assert calls == [(URL, {'json_body': query})]


def test_unavailable_resume_does_not_repeat_completed_target():
    state, manifest = unavailable()
    item = task(HOME+'events/second', 'event'); manifest.append({'site':HOST, 'request':item})
    saved = state[HOST]
    saved['sources'][key(item)] = dict(url=item['url'], kind='event', status=410, receipts=[])
    saved['done'][key(item)] = dict(item)
    get, calls = client({URL: None, item['url']: BODY})
    stop = Event(); stop.set()
    first = house_sites.collect(DIRECTORY, state, today=TODAY, get=get, retry_requests=manifest, stop=stop)
    assert first['pending'] == 2 and not calls
    house_sites.collect(DIRECTORY, state, today=TODAY, get=get, retry_requests=manifest, limit=1)
    house_sites.collect(DIRECTORY, state, today=TODAY, get=get, retry_requests=manifest)
    assert [u for u, _ in calls] == [URL, item['url']]


def response(code, body=b'publisher', url=URL):
    r = requests.Response(); r.status_code=code; r._content=body; r.url=url
    return r


@pytest.fixture
def transport(monkeypatch):
    monkeypatch.setattr(http, 'pace_request', lambda *a, **kw: (kw.get('request_pacer') or (lambda:None))())
    direct, proxy, calls = [], [], []
    def fetch(method, url, **kw):
        calls.append(('direct', method, kw))
        value = direct.pop(0)
        if isinstance(value, Exception): raise value
        return value
    def zyte_request(url, session, **kw):
        calls.append(('zyte', kw))
        value = proxy.pop(0)
        if isinstance(value, Exception): raise value
        return value
    monkeypatch.setattr(http, '_local', SimpleNamespace(session=SimpleNamespace(request=fetch)))
    monkeypatch.setattr(http.zyte, 'request', zyte_request)
    return direct, proxy, calls


def api_response(status=200, body=BODY, provider_status=200, final=URL):
    payload={'statusCode':status, 'httpResponseBody':base64.b64encode(body).decode(), 'url':final}
    return SimpleNamespace(status_code=provider_status, json=lambda:payload)


def test_successful_direct_never_uses_zyte(transport):
    direct, proxy, calls = transport; direct.append(response(200,BODY))
    receipts=[]
    result=house_sites.request_with_fallback(URL, receipts)
    assert result.content == BODY and len(calls)==1
    assert receipts[0]['transport']=='direct' and receipts[0]['selected']


@pytest.mark.parametrize('status', [401,403,404,410])
def test_unavailable_or_refused_direct_falls_back_once(transport, status):
    direct, proxy, calls=transport; direct.append(response(status,b'literal absence')); proxy.append(api_response())
    receipts=[]; pacer=[]
    result=house_sites.request_with_fallback(URL, receipts, request_pacer=lambda:pacer.append(True))
    assert result.content==BODY and [c[0] for c in calls]==['direct','zyte'] and len(pacer)==2
    assert [r['transport'] for r in receipts]==['direct','zyte']
    assert [r['selected'] for r in receipts]==[False,True]
    assert content_bytes(receipts[0]['content'])==b'literal absence'
    assert receipts[1]['provider_http_status']==200


def test_transport_failure_then_zyte_keeps_post_body(transport):
    direct, proxy, calls=transport; direct.extend([requests.ConnectionError('DNS')] * 3); proxy.append(api_response())
    receipts=[]; query={'offset':20,'limit':20}
    result=house_sites.request_with_fallback(URL, receipts, json_body=query)
    assert result.status_code==200 and len(calls)==4
    assert all(c[1]=='POST' and json.loads(c[2]['data'])==query for c in calls[:3])
    assert calls[-1][1]['json_body']==query
    assert receipts[0]['outcome']=='error' and receipts[1]['request_json']==query


@pytest.mark.parametrize('api_status', [401,403,404,429,500])
def test_provider_failure_never_replaces_literal_publisher_absence(transport, api_status):
    direct, proxy, calls=transport; direct.append(response(410,b'Gone')); proxy.append(api_response(provider_status=api_status))
    receipts=[]; result=house_sites.request_with_fallback(URL, receipts)
    assert result.status_code==410 and result.content==b'Gone'
    assert len(calls)==2 and receipts[0]['selected'] and not receipts[1]['selected']
    assert receipts[1]['provider_http_status']==api_status
    assert receipts[1].get('status_code') is None


def test_both_transports_fail_without_inventing_publisher_absence(transport):
    direct, proxy, calls=transport; direct.extend([requests.ConnectionError('DNS')] * 3); proxy.append(api_response(provider_status=401))
    receipts=[]
    with pytest.raises(http.HttpRequestError) as error:
        house_sites.request_with_fallback(URL, receipts)
    assert error.value.status=='request error'
    assert len(receipts)==2 and receipts[-1]['provider_http_status']==401


def test_fallback_absence_does_not_override_complete_direct_absence(transport):
    direct, proxy, calls=transport; direct.append(response(404,b'literal')); proxy.append(api_response(status=410,body=b'proxy absence'))
    receipts=[]; result=house_sites.request_with_fallback(URL, receipts)
    assert result.status_code==404 and [r['selected'] for r in receipts]==[True,False]
    assert content_bytes(receipts[-1]['content'])==b'proxy absence'


def test_fallback_success_keeps_publisher_redirect_for_site_validation(transport):
    direct, proxy, calls=transport; direct.append(response(404)); proxy.append(api_response(final='https://elsewhere.gov/event'))
    assert house_sites.request_with_fallback(URL, []).url=='https://elsewhere.gov/event'


def test_selected_receipt_matches_retained_body_after_proxy_provider_failure(transport):
    state, manifest=unavailable(); direct, proxy, calls=transport
    direct.append(response(404,b'new literal')); proxy.append(api_response(provider_status=401))
    house_sites.collect(DIRECTORY,state,today=TODAY,get=house_sites.request_with_fallback,retry_requests=manifest)
    observation=state[HOST]['sources'][key(manifest[0]['request'])]
    assert observation['status']==404 and content_bytes(observation['content'])==b'new literal'
    assert observation['receipts'][1]['sha256']==observation['content']['sha256']
    assert observation['receipts'][2]['provider_http_status']==401


def test_cli_fallback_is_exclusive_with_forced_proxy_before_state_io(tmp_path):
    with pytest.raises(ValueError, match='zyte'):
        house_sites.main(tmp_path/'missing',tmp_path,tmp_path,zyte=True,zyte_fallback=True)


def test_cli_passes_fallback_option(monkeypatch, tmp_path):
    from congress_api.cli import house_sites as cli
    calls=[]; monkeypatch.setattr(cli,'main',lambda **kw:calls.append(kw))
    cli.parse_args_and_run(['--committees',str(tmp_path/'c'),'--state-dir',str(tmp_path),'--output-dir',str(tmp_path),'--zyte-fallback'])
    assert calls[0]['zyte_fallback'] and not calls[0]['zyte']


@pytest.mark.parametrize('status', [401, 403, 500])
def test_both_publisher_responses_refused_remain_errors_with_bodies(transport, status):
    direct, proxy, calls = transport
    direct.append(response(status, b'direct refusal')); proxy.append(api_response(status=status, body=b'proxy refusal'))
    receipts = []
    with pytest.raises(http.HttpRequestError) as error:
        house_sites.request_with_fallback(URL, receipts)
    assert error.value.status == status and len(calls) == 2
    assert [r['selected'] for r in receipts] == [True, False]
    assert [content_bytes(r['content']) for r in receipts] == [b'direct refusal', b'proxy refusal']


def test_malformed_provider_payload_preserves_direct_absence(transport):
    direct, proxy, calls = transport
    direct.append(response(404, b'literal')); proxy.append(SimpleNamespace(status_code=200, json=lambda: {}))
    receipts = []
    assert house_sites.request_with_fallback(URL, receipts).content == b'literal'
    assert receipts[0]['selected'] and receipts[1]['outcome'] == 'error' and len(calls) == 2


def test_retained_page_timestamp_comes_from_selected_transport(transport, monkeypatch):
    direct, proxy, _ = transport
    direct.append(response(404)); proxy.append(api_response(body=BODY))
    ticks = iter(['direct-start', 'direct-end', 'proxy-start', 'proxy-end'])
    monkeypatch.setattr(house, 'timestamp', lambda: next(ticks))
    state, manifest = unavailable()
    house_sites.collect(DIRECTORY, state, today=TODAY, get=house_sites.request_with_fallback, retry_requests=manifest)
    assert state[HOST]['pages'][URL]['retrieved_at'] == 'proxy-end'
    old = state[HOST]['sources'][key(manifest[0]['request'])]['receipts'][0]
    assert old['completed_at'] == 'old'


@pytest.mark.parametrize('same_body', [False, True])
def test_bounded_refresh_preserves_distinct_original_source_and_page_bodies(same_body):
    state, manifest = unavailable()
    old_page_body = BODY if same_body else b'<h1>Old event</h1><p>Date: January 1, 2001</p>'
    state[HOST]['pages'][URL] = house_sites.parse_event_page(old_page_body, URL)
    original_receipts = deepcopy(state[HOST]['sources'][key(manifest[0]['request'])]['receipts'])
    get, _ = client({URL: BODY})
    house_sites.collect(DIRECTORY, state, today=TODAY, get=get, retry_requests=manifest)
    source = state[HOST]['sources'][key(manifest[0]['request'])]
    history = [content_bytes(c) for c in source['content_history']]
    assert history == ([b'old absence'] if same_body else [b'old absence', old_page_body])
    assert source['receipts'][:1] == original_receipts
    assert content_bytes(state[HOST]['pages'][URL]['raw_html']) == BODY


def test_unchanged_source_body_does_not_duplicate_history():
    state, manifest = unavailable(kind='sitemap')
    previous = state[HOST]['sources'][key(manifest[0]['request'])]
    previous['content'] = RawContent.from_bytes(b'<urlset/>', 'application/xml').source_dict()
    get, _ = client({URL: b'<urlset/>'})
    house_sites.collect(DIRECTORY, state, today=TODAY, get=get, retry_requests=manifest)
    assert not state[HOST]['sources'][key(manifest[0]['request'])].get('content_history')


@pytest.mark.parametrize('url', [HOME+'download/testimony', HOME+'sites/evo-subsites/committee/files/evo-media-document/document.pdf%20'])
def test_unavailable_document_routes_are_reported_excluded_without_file_fetch(url):
    state, _ = unavailable()
    item = task(url, 'html'); identifier = key(item)
    original = dict(url=url, kind='html', status=404, receipts=[{'status_code':404}])
    state[HOST]['sources'] = {identifier:deepcopy(original)}
    state[HOST]['done'] = {identifier:dict(item)}
    result = house_sites.collect(DIRECTORY, state, today=TODAY,
        get=lambda *a, **k: pytest.fail('Must not download a linked file'), retry_requests=[{'site':HOST, 'request':item}])
    assert result['requests'] == result['pending'] == result['failed'] == 0
    assert result['excluded'] == 1 and state[HOST]['sources'][identifier] == original


def test_fallback_cli_uses_shared_recovery_transport(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(house_sites, 'read_state', lambda _: {})
    monkeypatch.setattr(house_sites, 'read_committees', lambda _: DIRECTORY)
    monkeypatch.setattr(house_sites, 'outputs', lambda *args: None)
    monkeypatch.setattr(house_sites, 'request_with_fallback', lambda *args, **kwargs: calls.append((args, kwargs)))
    def collect(*args, get, **kwargs):
        get(URL, [], json_body={'offset':20, 'limit':20})
        return dict(failed=0)
    monkeypatch.setattr(house_sites, 'collect', collect)
    committees = tmp_path/'committees'; committees.touch()
    house_sites.main(committees, tmp_path, tmp_path, zyte_fallback=True, requests_per_second=30)
    assert calls[0][0][0] == URL and calls[0][1]['json_body'] == {'offset':20,'limit':20}
    assert isinstance(calls[0][1]['request_pacer'], http.RequestPacer)


def test_failed_retry_preserves_prior_diagnostic_without_claiming_resolution():
    state, manifest = unavailable()
    identifier = key(manifest[0]['request'])
    previous = dict(request=deepcopy(manifest[0]['request']), error='Original DNS failure', checked_at='old check')
    state[HOST]['errors'][identifier] = deepcopy(previous)
    receipts = deepcopy(state[HOST]['sources'][identifier]['receipts'])
    get, _ = client({URL: RuntimeError('New refusal')})
    result = house_sites.collect(DIRECTORY, state, today=TODAY, get=get, retry_requests=manifest)
    assert result['failed'] == result['retained_failed'] == 1
    assert state[HOST]['error_history'][identifier] == [previous]
    assert state[HOST]['errors'][identifier]['error'] == 'New refusal'
    assert state[HOST]['errors'][identifier]['checked_at'] != previous['checked_at']
    assert not state[HOST].get('resolved_errors')
    updated = state[HOST]['sources'][identifier]['receipts']
    assert updated[:1] == receipts and len(updated) == 2
