"""Characterize the production HTTP clients without network I/O."""
import json
from collections import defaultdict
from types import SimpleNamespace

import pytest
import requests
from congress_api.acquisition import meetings
from congress_api.transport import http
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


def test_production_wrapper_retries_five_times_and_preserves_parameters(unpaced):
    calls = []
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return response(503 if len(calls) < 5 else 200)
    assert meetings.get(SimpleNamespace(request=request), URL, 'test-key', {'offset': 250}) == {'committees': []}
    assert len(calls) == 5
    assert calls[-1] == ('GET', URL, {'params': {'offset': 250, 'api_key': 'test-key', 'format': 'json'},
                                     'timeout': 60, 'headers': http.UA})


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
