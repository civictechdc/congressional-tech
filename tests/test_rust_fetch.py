"""Fallback must preserve both attempts and the existing capture decisions."""

import gzip
import json
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.acquisition.raw_sync import run_sync
from congress_api.models.content import RawContent
from congress_api.retention.bundles import restore
from congress_api.retention.raw_archive import Archive
from congress_api.transport.rust_fetch import RustFetcher, RustResponse
from test_raw_source_sync import MemoryStore, response


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


def test_fallback_receipt_recovers_both_bodies_with_their_own_status(monkeypatch):
    url = 'https://example.gov/a.pdf'
    direct = response(url, b'refused', 'text/plain', 403)
    good = response(url, b'%PDF-1.7\n%%EOF', provider_http_status=200)
    fetcher, _ = fetcher_with_responses(monkeypatch, direct, good)
    store = MemoryStore()
    stats = run_sync(Archive(store, 'fallback'), [{'url': url}], fetch=fetcher.fetch, limit=1)
    assert stats['saved'] == 1 and stats['zyte_fallbacks'] == 1
    rows = pq.read_table(pa.BufferReader(store.read('indexes/captures.parquet'))).to_pylist()
    assert {(json.dumps(json.loads(r['pointer_json'])), r['http_status'], r['family']) for r in rows} == {
        (json.dumps(['content', 'body']), 200, 'documents'),
        (json.dumps(['prior_attempts', 0, 'content', 'body']), 403, 'documents'),
    }
    receipt_key = store.keys('receipts/')[0]
    receipt = json.loads(gzip.decompress(store.read(receipt_key)).splitlines()[0])
    original = restore(receipt['record'], receipt['captures'], lambda key: gzip.decompress(store.read(key)))
    assert original['prior_attempts'][0]['http_status'] == 403
    assert RawContent.model_validate(original['prior_attempts'][0]['content']).body_bytes() == b'refused'
    assert Archive(store, 'recovered').state[url]['outcome'] == 'saved'


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


def test_failed_provider_authentication_still_retains_direct_attempt(monkeypatch):
    direct = response('https://example.gov/a', b'refused', status=403)
    failed = dict(requested_url=direct['url'], url=direct['url'], retrieved_at=direct['retrieved_at'],
                  complete=False, error='provider_http_error', provider_http_status=401)
    fetcher, calls = fetcher_with_responses(monkeypatch, direct, failed)
    store = MemoryStore()
    with pytest.raises(RuntimeError, match='authorization failed'):
        run_sync(Archive(store, 'auth'), [{'url': direct['url']}], fetch=fetcher.fetch, limit=1)
    assert calls == ['direct', 'zyte']
    assert store.keys('receipts/') and store.keys('bodies/')
