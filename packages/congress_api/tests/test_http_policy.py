"""Characterize the production HTTP clients without network I/O."""
import json
from collections import defaultdict
from types import SimpleNamespace

import pytest
import requests
from congress_api.acquisition import committees, meetings
from congress_api.transport import congress, http
from congress_api.transport.senate import HDR as captions_HDR
from congress_api.transport.senate import get_source as captions_get_source
from congress_api.transport.senate import sess as captions_sess

URL = 'https://api.congress.gov/v3/committee/119'


def response(status=200, body=b'{"committees": []}'):
    result = requests.Response()
    result.status_code, result._content, result.url = status, body, URL
    return result


@pytest.fixture
def unpaced(monkeypatch):
    monkeypatch.setattr(http.time, 'sleep', lambda *_: None)
    monkeypatch.setattr(http, '_next', defaultdict(float))


@pytest.mark.parametrize('collector', [meetings, committees])
def test_production_wrapper_retries_five_times_and_preserves_parameters(unpaced, collector):
    calls = []
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return response(503 if len(calls) < 5 else 200)
    assert collector.get(SimpleNamespace(request=request), URL, 'test-key', {'offset': 250}) == {'committees': []}
    assert len(calls) == 5
    assert calls[-1] == ('GET', URL, {'params': {'offset': 250, 'api_key': 'test-key', 'format': 'json'},
                                     'timeout': 60, 'headers': http.UA})


def test_congress_wrapper_preserves_existing_collector_imports():
    assert meetings.API == committees.API == congress.API == 'https://api.congress.gov/v3'
    assert meetings.get is committees.get is congress.get


def test_congress_wrapper_overrides_credentials_and_format_without_changing_caller_params(unpaced):
    params = {'offset': 250, 'limit': 100, 'api_key': 'discarded-key', 'format': 'xml'}
    original = params.copy()
    calls = []
    def request(method, url, **kwargs):
        calls.append(kwargs)
        return response()
    assert congress.get(SimpleNamespace(request=request), URL, 'test-key', params) == {'committees': []}
    assert calls[0]['params'] == {'offset': 250, 'limit': 100, 'api_key': 'test-key', 'format': 'json'}
    assert params == original


def test_congress_wrapper_preserves_explicit_attempt_budget(unpaced):
    calls = []
    def request(*args, **kwargs):
        calls.append(kwargs)
        return response(503)
    with pytest.raises(http.HttpRequestError) as failure:
        congress.get(SimpleNamespace(request=request), URL, 'test-key', attempts=2)
    assert len(calls) == failure.value.details['attempts'] == 2


def test_congress_json_failure_propagates_without_retrying_http_success(unpaced):
    calls = []
    def request(*args, **kwargs):
        calls.append(kwargs)
        return response(200, b'not JSON')
    with pytest.raises(requests.exceptions.JSONDecodeError):
        congress.get(SimpleNamespace(request=request), URL, 'test-key')
    assert len(calls) == 1


def test_gateway_default_is_three_attempts_and_redacts_query_secrets(unpaced):
    calls = []
    def request(*args, **kwargs):
        calls.append(args)
        return response(503)
    with pytest.raises(RuntimeError) as failure:
        http.get_with_retry(SimpleNamespace(request=request), URL + '?api_key=test-secret')
    assert len(calls) == 3
    assert 'test-secret' not in str(failure.value)


def test_gateway_requires_explicit_absence_status(unpaced):
    session = SimpleNamespace(request=lambda *a, **k: response(404))
    assert http.get_with_retry(session, URL, allowed=(200, 404)).status_code == 404
    with pytest.raises(RuntimeError, match='404'):
        http.get_with_retry(session, URL)


def test_zyte_synthetic_response_maps_publisher_headers(unpaced, monkeypatch):
    import base64

    monkeypatch.setenv('ZYTE_TOKEN', 'test-token')
    payload = {
        'url': 'https://docs.house.gov/file.xml',
        'statusCode': 200,
        'httpResponseBody': base64.b64encode(b'<committee-meeting/>').decode(),
        'httpResponseHeaders': [
            {'name': 'Content-Type', 'value': 'application/xml'},
            {'name': 'X-Publisher-Document-Type', 'value': 'Meeting'},
        ],
    }
    monkeypatch.setattr(http.zyte, 'request', lambda *a, **k: SimpleNamespace(
        status_code=200, json=lambda: payload))
    result = http.get_with_retry(None, payload['url'], through_zyte=True)
    assert result.status_code == 200
    assert result.content == b'<committee-meeting/>'
    assert result.headers['Content-Type'] == 'application/xml'
    assert result.headers['X-Publisher-Document-Type'] == 'Meeting'


def test_zyte_get_rejects_payload_without_publisher_status(monkeypatch):
    import base64

    from congress_api.transport import zyte
    from pydantic import ValidationError

    monkeypatch.setenv('ZYTE_TOKEN', 'test-token')
    payload = {'httpResponseBody': base64.b64encode(b'x').decode()}
    session = SimpleNamespace(post=lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: payload))
    with pytest.raises(ValidationError, match='statusCode'):
        zyte.get('https://publisher.gov/file.pdf', session)


def test_caption_transport_keeps_pool_timeout_and_empty_body_retries(monkeypatch):
    assert captions_sess.get_adapter('https://example.gov')._pool_maxsize == 32
    calls = []
    bodies = [response(200, b''), response(503), response(200, b'WEBVTT\n\n')]
    def get(url, **kwargs):
        calls.append(kwargs)
        return bodies[len(calls) - 1]
    monkeypatch.setattr(captions_sess, 'get', get)
    assert captions_get_source('https://example.gov/captions.vtt').raw_body.body_bytes() == b'WEBVTT\n\n'
    assert len(calls) == 3
    assert all(call == {'headers': captions_HDR, 'timeout': 30} for call in calls)


def test_transcription_metadata_fetch_keeps_urllib_bytes_and_timeout(monkeypatch):
    import io

    from congress_api.transcripts import context as metadata
    calls = []
    def urlopen(request, **kwargs):
        calls.append((request.full_url, request.get_header('User-agent'), kwargs))
        return io.BytesIO(b'original metadata bytes')
    monkeypatch.setattr(metadata.urllib.request, 'urlopen', urlopen)
    assert metadata.fetch('https://example.gov/mods.xml') == b'original metadata bytes'
    assert calls == [('https://example.gov/mods.xml', 'Mozilla/5.0', {'timeout': 60})]


def test_transcription_duration_uses_direct_youtube_request(monkeypatch):
    from congress_api.transcripts import generate as main
    monkeypatch.setenv('YOUTUBE_API_KEY', 'test-key')
    calls = []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return response(body=b'{"items":[{"contentDetails":{"duration":"PT1H2M3S"}}]}')
    monkeypatch.setattr(main.requests, 'get', get)
    assert main.video_duration('example') == 3723
    assert calls == [('https://www.googleapis.com/youtube/v3/videos',
                      {'params': {'part': 'contentDetails', 'id': 'example', 'key': 'test-key'}, 'timeout': 30})]


def test_transcription_gpo_keeps_direct_html_capture(tmp_path, monkeypatch):
    from congress_api.parsers import gpo_text as gpo_parse
    from congress_api.retention.gpo import body_bytes
    from congress_api.transcripts import generate as main
    data = b'<html><pre>Retained transcript source</pre></html>'
    csv = tmp_path / 'gpo.csv'
    csv.write_text('package_id,chamber,event_id,html_url\nCHRG-test,House,1,https://example.gov/transcript.htm\n')
    facts = {k: '' for k in ('title', 'congress', 'session', 'committee', 'committee_code', 'subcommittee', 'held_date', 'serial')}
    monkeypatch.setattr(main, 'mods_people', lambda _: ({}, facts))
    calls = []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return response(body=data)
    monkeypatch.setattr(main.requests, 'get', get)
    monkeypatch.setattr(gpo_parse, 'parse_gpo_text', lambda source, *a, **k: source)
    monkeypatch.setattr(main, 'bind_gpo_transcript', lambda transcript: transcript)
    main.from_gpo('CHRG-test', csv, source_dir=tmp_path / 'source')
    assert calls == [('https://example.gov/transcript.htm', {'timeout': 60, 'headers': {'User-Agent': 'Mozilla/5.0'}})]
    captured = json.loads((tmp_path / 'source/CHRG-test.json').read_text())
    assert body_bytes(captured) == data and captured['acquisition'] == 'http'


def test_read_only_post_uses_shared_request_retry_and_same_body(unpaced):
    calls = []
    query = {'start': '2025-09-18', 'limit': 20}
    def request(method, url, **kwargs):
        calls.append((method, kwargs))
        return response(503 if len(calls) < 2 else 200)
    http.get_with_retry(SimpleNamespace(request=request), URL, method='POST', json_body=query)
    assert len(calls) == 2
    assert all(method == 'POST' and kwargs['json'] == query for method, kwargs in calls)
    with pytest.raises(ValueError, match='require POST'):
        http.get_with_retry(SimpleNamespace(request=request), URL, json_body=query)
    assert len(calls) == 2


def test_read_only_post_through_zyte_preserves_publisher_method_and_json(unpaced, monkeypatch):
    import base64
    calls = []
    monkeypatch.setenv('ZYTE_TOKEN', 'test-token')
    def post(url, **kwargs):
        calls.append((url, kwargs))
        payload = {'statusCode': 200, 'httpResponseBody': base64.b64encode(b'{}').decode(), 'httpResponseHeaders': []}
        return SimpleNamespace(status_code=200, json=lambda: payload)
    query = {'start': '2025-09-18', 'limit': 20}
    result = http.get_with_retry(SimpleNamespace(post=post), URL, method='POST', json_body=query, through_zyte=True)
    assert result.content == b'{}'
    sent = calls[0][1]['json']
    assert sent['httpRequestMethod'] == 'POST'
    assert json.loads(sent['httpRequestText']) == query
    assert sent['customHttpRequestHeaders'] == [{'name': 'Content-Type', 'value': 'application/json'}]


@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(http.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(http.time, 'sleep', lambda delay: now.__setitem__(0, now[0] + delay))
    monkeypatch.setattr(http, '_next', defaultdict(float))
    return now


def test_shared_request_pacer_spaces_threads_and_does_not_accumulate_idle_credit(clock):
    from concurrent.futures import ThreadPoolExecutor
    pacer = http.RequestPacer(30)
    with ThreadPoolExecutor(30) as pool:
        list(pool.map(lambda _: pacer(), range(61)))
    assert clock[0] == pytest.approx(102)
    clock[0] = 200
    pacer()
    assert clock[0] == 200
    pacer()
    assert clock[0] == pytest.approx(200 + 1 / 30)


@pytest.mark.parametrize('rate', [0, -1, float('nan'), float('inf')])
def test_request_pacer_rejects_invalid_rates(rate):
    with pytest.raises(ValueError, match='positive finite'):
        http.RequestPacer(rate)


def test_rate_limit_spans_hosts_retries_and_calendar_posts_without_removing_backoff(clock):
    starts = []
    def request(method, url, **kwargs):
        starts.append((clock[0], method, kwargs))
        return response(503 if len(starts) == 2 else 200)
    session = SimpleNamespace(request=request)
    pacer = http.RequestPacer(30)
    http.get_with_retry(session, 'https://a.house.gov/event', request_pacer=pacer)
    http.get_with_retry(session, 'https://b.house.gov/calendar', method='POST', json_body={'month': 10}, request_pacer=pacer)
    assert [s[0] for s in starts] == pytest.approx([100, 100 + 1 / 30, 102 + 1 / 30])
    assert all(s[1] == 'POST' and s[2]['json'] == {'month': 10} for s in starts[1:])


def test_global_wait_preserves_host_spacing_and_docs_refusal_delay(clock):
    pacer = http.RequestPacer(1)
    pacer()  # Another host used the global slot.
    starts = []
    def request(*args, **kwargs):
        starts.append(clock[0])
        return response(403 if len(starts) == 1 else 200)
    session = SimpleNamespace(request=request)
    http.get_with_retry(session, 'https://docs.house.gov/event', request_pacer=pacer)
    http.get_with_retry(session, 'https://docs.house.gov/event', request_pacer=pacer)
    assert starts == pytest.approx([101, 161, 162.2])


def test_zyte_attempts_use_the_same_global_pacer(clock, monkeypatch):
    starts = []
    def request(*args, **kwargs):
        starts.append(clock[0])
        return None
    monkeypatch.setattr(http.zyte, 'request', request)
    monkeypatch.setattr(http.zyte, 'decode', lambda _: (200, b'{}', []))
    pacer = http.RequestPacer(30)
    for host in ('a', 'b'):
        http.get_with_retry(None, f'https://{host}.house.gov/', through_zyte=True, request_pacer=pacer)
    assert starts == pytest.approx([100, 100 + 1 / 30])


@pytest.mark.parametrize('header_value,expected_wait', [
    ('15', 15.0),
    ('Wed, 21 Oct 2026 07:28:15 GMT', 15.0),
    ('Wed, 21 Oct 2026 07:27:00 GMT', 2.0),  # Past HTTP-date falls back to backoff floor.
    ('invalid-retry-after', 2.0),
    ('1', 2.0),  # Never undercuts 2**(attempt+1) backoff floor.
])
def test_retry_after_numeric_and_http_date_honored_with_backoff_floor(clock, monkeypatch, header_value, expected_wait):
    from datetime import datetime, timezone
    base_epoch = datetime(2026, 10, 21, 7, 28, 0, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(http.time, 'time', lambda: base_epoch)
    starts = []
    def request(*args, **kwargs):
        starts.append(clock[0])
        resp = response(503 if len(starts) == 1 else 200)
        if len(starts) == 1:
            resp.headers['Retry-After'] = header_value
        return resp
    result = http.get_with_retry(SimpleNamespace(request=request), 'https://www.govinfo.gov/pkg.zip')
    assert result.status_code == 200
    assert starts == pytest.approx([100.0, 100.0 + expected_wait])


def test_retry_after_on_302_redirect_history_and_house_403_floor(clock):
    starts = []
    def request(*args, **kwargs):
        starts.append(clock[0])
        if len(starts) == 1:
            redirect = response(302)
            redirect.headers['Retry-After'] = '15'
            final = response(503)
            final.history = [redirect]
            return final
        return response(200)
    http.get_with_retry(SimpleNamespace(request=request), 'https://www.govinfo.gov/pkg.zip')
    assert starts == pytest.approx([100.0, 115.0])

    house_starts = []
    def house_request(*args, **kwargs):
        house_starts.append(clock[0])
        resp = response(403 if len(house_starts) == 1 else 200)
        if len(house_starts) == 1:
            resp.headers['Retry-After'] = '5'
        return resp
    http.get_with_retry(SimpleNamespace(request=house_request), 'https://docs.house.gov/event')
    assert house_starts == pytest.approx([115.0, 175.0])


def test_retry_after_multiple_raw_headers_preserves_http_date_commas(clock, monkeypatch):
    from datetime import datetime, timezone
    from urllib3.response import HTTPResponse
    base_epoch = datetime(2026, 10, 21, 7, 28, 0, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(http.time, 'time', lambda: base_epoch)
    starts = []
    def request(*args, **kwargs):
        starts.append(clock[0])
        resp = response(429 if len(starts) == 1 else 200)
        if len(starts) == 1:
            raw = HTTPResponse(headers={})
            raw.headers.add('Retry-After', '5')
            raw.headers.add('Retry-After', 'Wed, 21 Oct 2026 07:28:25 GMT')
            resp.raw = raw
        return resp
    http.get_with_retry(SimpleNamespace(request=request), 'https://www.govinfo.gov/pkg.zip')
    assert starts == pytest.approx([100.0, 125.0])


def test_http_412_fails_without_retrying(unpaced):
    calls = []
    def request(*args, **kwargs):
        calls.append(kwargs)
        return response(412)
    with pytest.raises(http.HttpRequestError) as failure:
        http.get_with_retry(SimpleNamespace(request=request), 'https://www.govinfo.gov/pkg.zip', allowed=(200, 206))
    assert failure.value.status == 412
    assert len(calls) == 1
