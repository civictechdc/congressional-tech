"""Fallback must preserve both attempts and the existing capture decisions."""

import json
import sys

import pytest

from congress_api.models.content import RawContent
from congress_api.models.content import CapturedBody
from congress_api.retention.body_files import CapturedFile, content_bytes, close_capture_files
from congress_api.transport.rust_fetch import RustFetcher, RustResponse
from testing_fakes import response


def fetcher_with_responses(monkeypatch, direct, provider):
    fetcher = RustFetcher.__new__(RustFetcher)
    fetcher.max_bytes = 1024
    calls = []

    def capture(url, *, transport, **kwargs):
        assert kwargs['pace'] is False
        calls.append(transport)
        return direct if transport == 'direct' else provider

    monkeypatch.setattr('congress_api.transport.rust_fetch.fetch_source', capture)
    return fetcher, calls


@pytest.mark.parametrize('body,media,status,extra', [
    (b'refused', 'text/plain', 403, {}),
    (b'', 'text/plain', 200, {}),
    (b'<html><title>Just a moment</title></html>', 'text/html', 200, {}),
    (b'<html>Not found</html>', 'text/html', 200, {}),
    (b'%PDF-1.7\npartial', 'application/pdf', 200, {}),
    (b'partial', 'text/plain', 206, {}),
    (b'', 'text/plain', None, {'complete': False, 'error': 'Timeout'}),
])
def test_failed_direct_attempt_falls_back_once_and_preserves_evidence(monkeypatch, body, media, status, extra):
    url = 'https://example.gov/a.pdf'
    direct = {**response(url, body, media, status), **extra}
    good = response(url, b'%PDF-1.7\n%%EOF', provider_http_status=200)
    fetcher, calls = fetcher_with_responses(monkeypatch, direct, good)
    result = fetcher.fetch(url)
    assert calls == ['direct', 'zyte']
    assert result['prior_attempts'] == [direct]
    assert RawContent.model_validate(result['prior_attempts'][0]['content']).body_bytes() == body


@pytest.mark.parametrize('body,media', [
    (b'%PDF-1.7\n%%EOF', 'application/pdf'),
    (b'<html><a href="file.pdf">Download</a></html>', 'text/html'),
    (b'WEBVTT\n', 'text/vtt'),
    (b'media', 'video/mp4'),
])
def test_usable_direct_response_never_pays_for_zyte(monkeypatch, body, media):
    direct = response('https://example.gov/a', body, media)
    fetcher, calls = fetcher_with_responses(monkeypatch, direct, None)
    assert fetcher.fetch(direct['url']) is direct
    assert calls == ['direct']


def test_excluded_redirect_is_not_retried_through_a_provider(tmp_path):
    fetcher = RustFetcher.__new__(RustFetcher)
    fetcher.max_bytes = 1024
    body = tmp_path / '1.body'
    body.write_bytes(b'')
    calls = []

    def request(url, transport, **kwargs):
        calls.append(transport)
        return RustResponse(dict(body_file=str(body), http_status=302,
            final_url=url, response_header_items=[{'name': 'Location', 'value': 'http://127.0.0.1/private'}],
            complete=True), tmp_path)

    fetcher._request = request
    result = fetcher.fetch('https://example.gov/redirect')
    assert result['error'] == 'excluded_redirect'
    assert calls == ['direct']
    assert not body.exists()


@pytest.mark.parametrize('output', ['', '{"id":999,"response":{}}', '{"id":1}', '{"id":1,"response":null}'])
def test_dead_or_invalid_native_worker_fails_waiting_callers(tmp_path, output):
    binary = tmp_path / 'worker'
    binary.write_text(f'#!{sys.executable}\nimport sys\nsys.stdin.readline()\nprint({output!r}, flush=True)\n')
    binary.chmod(0o700)
    with RustFetcher(binary) as fetcher:
        with pytest.raises(RuntimeError, match='Native transport'):
            fetcher._request('https://example.gov/file', 'direct')


def test_fatal_native_failure_removes_its_partial_file(tmp_path):
    binary = tmp_path / 'worker'
    binary.write_text(f'#!{sys.executable}\nimport sys,json,pathlib\nr=json.loads(sys.stdin.readline())\n'
        'p=pathlib.Path(sys.argv[1])/f"{r[\"id\"]}.body"\np.write_bytes(b"partial")\n'
        'print(json.dumps({"id":r["id"],"fatal":"disk failure"}),flush=True)\n')
    binary.chmod(0o700)
    with RustFetcher(binary) as fetcher:
        with pytest.raises(RuntimeError, match='Native transport'):
            fetcher._request('https://example.gov/a', 'direct')
        assert not list(fetcher.root.glob('*.body'))


@pytest.mark.parametrize('field,value', [('media_type', 'wrong/type'), ('body_encoding', 'wrong'), ('sha256', '0'*64)])
def test_runtime_body_rejects_changed_metadata(field, value):
    content = CapturedBody.from_bytes(b'actual bytes', 'text/plain').source_dict()
    content[field] = value
    with pytest.raises(ValueError, match='Captured body metadata mismatch'):
        content_bytes(content)


def test_redirect_and_fallback_share_one_file_start(tmp_path, monkeypatch):
    import base64
    monkeypatch.setenv('ZYTE_TOKEN', 'fixture-token')
    original = 'http://docs.house.gov/start.pdf'
    upgraded = 'https://docs.house.gov/start.pdf'
    redirected = 'https://docs.house.gov/final.pdf'
    body = b'%PDF-1.7\n%%EOF'
    payload = json.dumps(dict(statusCode=200,
        httpResponseBody=base64.b64encode(body).decode(),
        httpResponseHeaders=[{'name':'Content-Type','value':'application/pdf'}])).encode()
    calls = []
    fetcher = RustFetcher.__new__(RustFetcher)
    fetcher.max_bytes = 1024**2

    def request(url, transport, *, new_file, headers=None):
        calls.append((url, transport, new_file))
        if len(calls) == 1:
            status, data, response_headers = 302, b'', [{'name':'Location','value':redirected}]
        elif len(calls) == 2:
            status, data, response_headers = 403, b'refused', []
        elif transport == 'zyte':
            status, data, response_headers = 200, payload, [{'name':'Content-Type','value':'application/json'}]
        else:
            status, data, response_headers = 200, body, [{'name':'Content-Type','value':'application/pdf'}]
        path = tmp_path / f'{len(calls)}.body'
        path.write_bytes(data)
        return RustResponse(dict(body_file=str(path),http_status=status,final_url=url,
            response_header_items=response_headers,complete=True),tmp_path)

    fetcher._request = request
    result = fetcher.fetch(original)
    second = fetcher.fetch('https://example.gov/other.pdf')
    assert calls == [(upgraded,'direct',True), (redirected,'direct',False),
                     (upgraded,'zyte',False), ('https://example.gov/other.pdf','direct',True)]
    assert result['requested_url'] == original
    assert result['request_url'] == result['url'] == upgraded
    assert result['prior_attempts'][0]['requested_url'] == original
    assert result['prior_attempts'][0]['request_url'] == upgraded
    assert len(result['prior_attempts'][0]['redirects']) == 1
    assert result['complete'] and second['complete']
    assert not list(tmp_path.glob('*.body'))


@pytest.mark.parametrize('spooled', [False, True])
def test_undeclared_xml_does_not_trigger_provider_fallback(tmp_path, monkeypatch, spooled):
    from pathlib import Path
    monkeypatch.setenv('ZYTE_TOKEN', 'fixture-token')
    data = (Path(__file__).parent / 'fixtures/raw_source_floor_schedule.xml').read_bytes()
    calls = []

    class XmlFetcher(RustFetcher):
        def __init__(self):
            self.max_bytes = 1024**2

        def _request(self, url, transport, **kwargs):
            calls.append(transport)
            assert transport == 'direct', 'Complete XML must not trigger a Zyte request'
            path = tmp_path / 'xml.body'
            path.write_bytes(data)
            return RustResponse(dict(body_file=str(path),http_status=200,final_url=url,
                response_header_items=[{'name':'Content-Type','value':'application/x-octet-stream'}],
                complete=True),tmp_path)

    fetcher = XmlFetcher()
    url = 'https://example.gov/download'
    if spooled:
        capture, inspection = fetcher.fetch_spooled(url, before_read=lambda: None)
        assert inspection[0] == 'saved'
    else:
        capture = fetcher.fetch(url)
    assert calls == ['direct']
    assert content_bytes(capture['content']) == data
    close_capture_files(capture)
    assert not list(tmp_path.glob('*.body'))


def test_native_pre_header_timeout_remains_a_timeout_without_secret_text(tmp_path):
    binary = tmp_path / 'worker'
    binary.write_text(f'''#!{sys.executable}
import sys,json
for line in sys.stdin:
 r=json.loads(line)
 print(json.dumps({{'id':r['id'],'response':{{'complete':False,'error':'timeout'}}}}),flush=True)
''')
    binary.chmod(0o700)
    with RustFetcher(binary) as fetcher:
        result = fetcher.fetch('https://example.gov/a.pdf', transport='direct')
    assert result['error'] == 'timeout'
    assert not result['complete']


@pytest.mark.parametrize('timeout', [0, -1, float('inf'), float('nan'), 901])
def test_invalid_deadline_is_rejected_before_starting_a_process(timeout):
    with pytest.raises(ValueError, match='timeout'):
        RustFetcher('/must-not-start', request_timeout=timeout)
