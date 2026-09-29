"""The Zyte client exposes original provider metadata and keeps its old API."""
import base64
from types import SimpleNamespace

from congress_api import zyte
from congress_api.models.transport import ZyteResponse


def test_request_keeps_complete_response_and_requests_publisher_headers(monkeypatch):
    monkeypatch.setenv('ZYTE_TOKEN', 'test-token')
    native = {'url': 'https://publisher.gov/file.pdf', 'statusCode': 200,
              'httpResponseBody': base64.b64encode(b'%PDF-original').decode(),
              'httpResponseHeaders': [{'name': 'Link', 'value': '<a>; rel="alternate"'},
                                      {'name': 'Link', 'value': '<b>; rel="describedby"'}],
              'requestId': 'request-1', 'newMetadata': {'publisherValue': None}}
    response = SimpleNamespace(status_code=200, json=lambda: native)
    def post(url, **kwargs):
        assert url == zyte.API
        assert kwargs['auth'] == ('test-token', '')
        assert kwargs['json'] == {'url': native['url'], 'httpResponseBody': True, 'httpResponseHeaders': True}
        return response
    session = SimpleNamespace(post=post)
    assert zyte.request(native['url'], session) is response
    assert ZyteResponse.model_validate(native).source_dict() == native
    assert zyte.get(native['url'], session) == (200, b'%PDF-original')


def test_provider_error_is_not_treated_as_publisher_success(monkeypatch):
    monkeypatch.setenv('ZYTE_TOKEN', 'test-token')
    session = SimpleNamespace(post=lambda *a, **k: SimpleNamespace(status_code=429))
    assert zyte.get('https://publisher.gov/file.pdf', session) == (429, b'')
