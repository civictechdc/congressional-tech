"""Characterize the production HTTP clients without network I/O."""
import json
from collections import defaultdict
from types import SimpleNamespace

import pytest
import requests

from congress_api import http, meetings

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


def test_caption_transport_keeps_pool_timeout_and_empty_body_retries(monkeypatch):
    from congress_api.senate import captions
    assert captions.sess.get_adapter('https://example.gov')._pool_maxsize == 32
    calls = []
    bodies = [response(200, b''), response(503), response(200, b'WEBVTT\n\n')]
    def get(url, **kwargs):
        calls.append(kwargs)
        return bodies[len(calls) - 1]
    monkeypatch.setattr(captions.sess, 'get', get)
    assert captions.get_source('https://example.gov/captions.vtt').raw_body.body_bytes() == b'WEBVTT\n\n'
    assert len(calls) == 3
    assert all(call == {'headers': captions.HDR, 'timeout': 30} for call in calls)


def test_transcription_metadata_fetch_keeps_urllib_bytes_and_timeout(monkeypatch):
    import io
    from congress_api.transcribe import metadata
    calls = []
    def urlopen(request, **kwargs):
        calls.append((request.full_url, request.get_header('User-agent'), kwargs))
        return io.BytesIO(b'original metadata bytes')
    monkeypatch.setattr(metadata.urllib.request, 'urlopen', urlopen)
    assert metadata.fetch('https://example.gov/mods.xml') == b'original metadata bytes'
    assert calls == [('https://example.gov/mods.xml', 'Mozilla/5.0', {'timeout': 60})]


def test_transcription_duration_uses_direct_youtube_request(monkeypatch):
    from congress_api.transcribe import main
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
    from congress_api.transcribe import main, gpo_parse
    from congress_api.gpo.evidence import body_bytes
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
    main.from_gpo('CHRG-test', csv, source_dir=tmp_path / 'source')
    assert calls == [('https://example.gov/transcript.htm', {'timeout': 60, 'headers': {'User-Agent': 'Mozilla/5.0'}})]
    captured = json.loads((tmp_path / 'source/CHRG-test.json').read_text())
    assert body_bytes(captured) == data and captured['acquisition'] == 'http'
