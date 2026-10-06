"""Explicit retries and resource-based admission preserve capture boundaries."""
import copy
import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading

import pytest

from congress_api.acquisition.raw_sync import response_capacity, run_sync
from congress_api.cli import raw_sync
from congress_api.retention.raw_archive import Archive
from congress_api.transport.rust_fetch import RustFetcher
from test_archive_members import archive as zip_bytes
from test_async_capture import receipts
from test_raw_capture_only import execute
from test_raw_source_sync import MemoryStore, response


@pytest.mark.parametrize('buffer,spool', [(2048, 5120), (300, 1024), (8, 2)])
def test_capacity_fits_both_reservations(buffer, spool):
    cap = response_capacity(buffer * 1024**2, spool * 1024**2)
    assert cap * 3 + 1024**2 <= buffer * 1024**2
    assert cap * 4 // 3 + 1024**2 <= spool * 1024**2
    assert (cap + 1) * 3 + 1024**2 > buffer * 1024**2 or (cap + 1) * 4 // 3 + 1024**2 > spool * 1024**2


@pytest.mark.parametrize('buffer,spool', [(1024, 2048), (2048, 1024)])
def test_impossible_capacity_refused(buffer, spool):
    with pytest.raises(ValueError):
        response_capacity(buffer, spool)


def test_retry_now_only_admits_selected_failures_and_preserves_old_receipts():
    store = MemoryStore()
    a = Archive(store, 'before')
    selected, other, saved = ['https://www.govinfo.gov/' + n for n in ['a.pdf', 'b.pdf', 'c.pdf']]
    for url in [selected, other, saved]:
        a.record(response(url, b'%PDF-1.7\nfixture\n%%EOF'),
                 outcome='saved' if url == saved else 'size_limit', links=[])
    a.state[selected]['next_attempt_at'] = a.state[other]['next_attempt_at'] = '2099-01-01T00:00:00+00:00'
    a.save()
    before = copy.deepcopy(a.state)
    old_receipts = {k:v for k,v in store.objects.items() if k.startswith('receipts/')}
    calls = []
    def fetch(url):
        calls.append(url)
        return response(url, b'%PDF-1.7\nfixed\n%%EOF')
    result = run_sync(Archive(store, 'after'), [], fetch=fetch,
        urls=[selected, saved], retry_outcomes=['size_limit'], retry_now=True)
    assert result['retry_now'] and calls == [selected] and result['saved'] == 1
    final = Archive(store, 'read').state
    assert final[other] == before[other] and final[saved] == before[saved]
    assert final[selected]['attempts'] == before[selected]['attempts'] + 1
    assert all(store.objects[k] == v for k,v in old_receipts.items())


@pytest.mark.parametrize('options', [
    dict(retry_now=True), dict(retry_now=True, retry_outcomes=['request_failed']),
    dict(retry_outcomes=['size_limit']), dict(retry_outcomes=['saved'], urls=['https://example.gov/a.pdf']),
])
def test_unsafe_retry_modes_refused(options):
    with pytest.raises(ValueError):
        run_sync(Archive(MemoryStore(), 'invalid'), [], fetch=lambda _: pytest.fail('No fetch'), **options)


@pytest.mark.parametrize('argv', [
    ['--capture-only', '--retry-now'],
    ['--capture-only', '--retry-outcome', 'size_limit'],
    ['--capture-only', '--max-file-mib', '-1'],
])
def test_cli_modes_refused_before_storage(tmp_path, argv):
    with pytest.raises(SystemExit):
        execute(tmp_path, object(), *argv)


@pytest.mark.skipif(not os.environ.get('SOURCE_FETCH_BINARY'), reason='Requires native worker')
@pytest.mark.parametrize('kind', ['pdf', 'zip'])
def test_native_capture_over_64_mib_and_zip_members_with_no_file_policy(tmp_path, monkeypatch, kind):
    pdf = b'%PDF-1.7\n' + b'0' * (65 * 1024**2) + b'\n%%EOF'
    payload = zip_bytes([('large.pdf', pdf)]) if kind == 'zip' else pdf
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Content-Type', 'application/zip' if kind == 'zip' else 'application/pdf')
            self.end_headers()
            for offset in range(0, len(payload), 65536):
                self.wfile.write(payload[offset:offset+65536])
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    target = 'https://www.govinfo.gov/content/pkg/test.' + kind
    class LocalFetcher(RustFetcher):
        def _request(self, url, transport, **kwargs):
            assert url == target and transport == 'direct'
            return super()._request(f'http://127.0.0.1:{server.server_port}/body', transport, **kwargs)
    monkeypatch.setattr(raw_sync, 'RustFetcher', LocalFetcher)
    store = MemoryStore(); a = Archive(store, 'before'); a.seed({'url': target})
    a.state[target].update(outcome='size_limit', next_attempt_at='2099-01-01T00:00:00+00:00'); a.save()
    urls=tmp_path/'urls.json';urls.write_text(json.dumps([target]))
    try:
        result = execute(tmp_path, store, '--capture-only', '--urls', urls,
            '--retry-outcome', 'size_limit', '--retry-now', '--max-file-mib', '0',
            '--max-buffer-mib', '300', '--max-spool-mib', '1024',
            '--fetcher-binary', os.environ['SOURCE_FETCH_BINARY'])
    finally:
        server.shutdown();server.server_close();thread.join()
    assert result['saved'] == 1 and result['max_file_mib'] == 0
    assert result['peak_body_payload_reservation_bytes'] <= 300 * 1024**2
    final=Archive(store,'check').state[target]
    assert gzip.decompress(store.objects[final['body_key']]) == payload
    receipt=receipts(store)[-1]
    record=receipt['record']
    if kind == 'zip':
        assert record['archive_processing']['status'] == 'completed'
        member, = record['archive_members']
        assert member['status'] == 'completed'
        cap, = [c for c in receipt['captures'] if c['pointer'] == ['archive_members', 0, 'content', 'body']]
        assert gzip.decompress(store.objects[cap['body_key']]) == pdf


def test_resource_refusal_preserves_native_error_and_never_uses_provider(monkeypatch):
    from congress_api.transport import rust_fetch
    calls=[]
    # Supply a complete synthetic native result without starting a worker.
    def fetch(url, **options):
        calls.append(options['transport'])
        result=response(url,b'')
        result.update(complete=False,error='response_limit',source_metadata={
            'body_read_skipped':'declared_size_limit','declared_body_bytes':9999})
        return result
    monkeypatch.setattr(rust_fetch,'fetch_source',fetch)
    fetcher=RustFetcher.__new__(RustFetcher);fetcher.max_bytes=1024;fetcher.limit_basis='resource_budget'
    result,(outcome,links)=fetcher._fetch('https://www.govinfo.gov/a.pdf',transport='auto')
    assert calls==['direct'] and outcome=='resource_limit' and not links
    assert result['error']=='response_limit' and not result['complete']
    assert result['source_metadata']['declared_body_bytes']==9999
    assert result['body_limit_basis']=='resource_budget' and result['body_limit_bytes']==1024


def test_retry_now_preserves_server_delay_and_attempt_budget():
    from test_capture_delayed_retry import deferred
    a=Archive(MemoryStore(), 'force-delay')
    url='https://www.govinfo.gov/a.zip'
    a.seed({'url':url});a.state[url].update(outcome='retry_later',next_attempt_at='2099-01-01T00:00:00+00:00')
    result=run_sync(a,[],fetch=lambda u:deferred(u,delay=7200),urls=[url],retry_outcomes=['retry_later'],retry_now=True,limit=4)
    assert result['attempted']==1 and result['retry_later']==1
    from datetime import datetime
    assert (datetime.fromisoformat(a.state[url]['next_attempt_at'])-datetime.fromisoformat(a.state[url]['checked_at'])).total_seconds()==7200
