"""Real async S3 transport on loopback; intentionally outside the offline suite."""
import asyncio
from contextlib import asynccontextmanager, closing, contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time

import boto3
import pytest

from aiobotocore.session import get_session
from botocore.config import Config

from congress_api.acquisition.raw_sync import run_async
from congress_api.retention.raw_archive import Archive
from congress_api.retention.r2 import AsyncBodies
from test_raw_source_sync import MemoryStore, response


@contextmanager
def s3_responses(responses):
    """Serve an exact response sequence through the real SDK transport."""
    calls = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def do_PUT(self):
            data = self.rfile.read(int(self.headers['Content-Length']))
            calls.append(dict(time=time.monotonic(), path=self.path, body=data,
                              headers=dict(self.headers)))
            status, code, extra = responses[min(len(calls) - 1, len(responses) - 1)]
            body = (f'<Error><Code>{code}</Code><Message>R2 throttle</Message></Error>'.encode()
                    if status != 200 else b'')
            self.send_response(status)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Content-Type', 'application/xml')
            self.send_header('ETag', '"' + hashlib.md5(data).hexdigest() + '"')
            self.send_header('x-amz-request-id', 'test-request')
            for key, value in extra.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield dict(endpoint_url=f'http://127.0.0.1:{server.server_port}', region_name='auto',
                   aws_access_key_id='test', aws_secret_access_key='test',
                   config=Config(retries={'mode': 'standard', 'total_max_attempts': 3},
                                 request_checksum_calculation='when_required',
                                 response_checksum_validation='when_required')), calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@contextmanager
def s3_downloads(responses):
    """Serve streamed failures after successful headers, as in the CI incident."""
    calls, release = [], threading.Event()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def do_GET(self):
            calls.append(dict(path=self.path, headers=dict(self.headers)))
            outcome = responses[min(len(calls) - 1, len(responses) - 1)]
            status = 403 if outcome == 'denied' else 200
            data = b'<Error><Code>AccessDenied</Code></Error>' if status == 403 else b'complete'
            self.send_response(status)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('ETag', '"' + outcome + '"')
            self.send_header('x-amz-request-id', 'download-' + str(len(calls)))
            self.end_headers()
            self.wfile.write(data[:2] if outcome in {'timeout', 'disconnect'} else data)
            self.wfile.flush()
            if outcome == 'timeout':
                release.wait(5)
            if outcome in {'timeout', 'disconnect'}:
                self.close_connection = True

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield dict(endpoint_url=f'http://127.0.0.1:{server.server_port}', region_name='auto',
                   aws_access_key_id='test', aws_secret_access_key='test',
                   config=Config(read_timeout=0.15,
                                 retries={'mode': 'standard', 'total_max_attempts': 3},
                                 request_checksum_calculation='when_required',
                                 response_checksum_validation='when_required')), calls
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize('transport', ['sync', 'async'])
@pytest.mark.parametrize('failure', ['timeout', 'disconnect'])
@pytest.mark.parametrize('recover', [True, False])
def test_r2_streamed_download_recovers_or_exhausts_bounded_reads(transport, failure, recover, caplog):
    import json
    from congress_api.retention.r2 import R2Store
    from botocore.exceptions import ReadTimeoutError, ResponseStreamingError
    from aiohttp import ClientPayloadError

    key = 'indexes/processing/body-results/test.parquet'
    sequence = [failure, 'complete'] if recover else [failure] * 3
    with s3_downloads(sequence) as (options, calls):
        def assertions(store, value):
            if recover:
                assert value == b'complete'  # Never return partial bytes from the first response.
            if transport == 'sync':
                assert store.index_etags == ({key: '"complete"'} if recover else {})

        if transport == 'sync':
            with closing(boto3.client('s3', **options)) as client:
                store = R2Store(client, 'archive')
                if recover:
                    assertions(store, store.read(key))
                else:
                    with pytest.raises((ReadTimeoutError, ResponseStreamingError)):
                        store.read(key)
                    assertions(store, None)
        else:
            async def run():
                async with get_session().create_client('s3', **options) as client:
                    store = AsyncBodies(client, 'archive')
                    if recover:
                        assertions(store, await store.read(key))
                    else:
                        with pytest.raises((ReadTimeoutError, ResponseStreamingError, ClientPayloadError)):
                            await store.read(key)
            asyncio.run(run())
        assert len(calls) == (2 if recover else 3)
        assert all('Range' not in c['headers'] for c in calls)
        events = [json.loads(r.message) for r in caplog.records
                  if r.name == 'congress_api.retention.r2' and 'r2_stream_read_error' in r.message]
        assert len(events) == (1 if recover else 3)
        assert events[0]['key'] == key and events[0]['request_id'] == 'download-1'
        assert events[-1]['max_attempts'] == 3
        if not recover:
            assert events[-1]['retry_delay_seconds'] is None


@pytest.mark.parametrize('transport', ['sync', 'async'])
@pytest.mark.parametrize('failure', ['timeout', 'denied'])
def test_r2_download_respects_disabled_retries_and_permanent_errors(transport, failure):
    from congress_api.retention.r2 import R2Store
    from botocore.exceptions import ReadTimeoutError, ClientError
    with s3_downloads([failure]) as (options, calls):
        if failure == 'timeout':
            options['config'] = options['config'].merge(Config(retries={'total_max_attempts': 1}))
        if transport == 'sync':
            with closing(boto3.client('s3', **options)) as client:
                with pytest.raises((ReadTimeoutError, ClientError)):
                    R2Store(client, 'archive').read('bodies/test.gz')
        else:
            async def run():
                async with get_session().create_client('s3', **options) as client:
                    with pytest.raises((ReadTimeoutError, ClientError)):
                        await AsyncBodies(client, 'archive').read('bodies/test.gz')
            asyncio.run(run())
        assert len(calls) == 1


def test_r2_stream_read_backoff_is_async_and_cancellable(monkeypatch):
    # A long retry delay makes it possible to cancel specifically during backoff.
    monkeypatch.setattr('congress_api.retention.r2.random.random', lambda: 5)
    with s3_downloads(['timeout']) as (options, calls):
        async def run():
            async with get_session().create_client('s3', **options) as client:
                task = asyncio.create_task(AsyncBodies(client, 'archive').read('bodies/test.gz'))
                try:
                    async with asyncio.timeout(2):
                        while not calls:
                            await asyncio.sleep(0.01)
                    await asyncio.sleep(0.3)
                    assert not task.done() and len(calls) == 1
                finally:
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                assert len(calls) == 1
        asyncio.run(run())


@pytest.mark.parametrize('transport', ['async', 'sync'])
@pytest.mark.parametrize('code', ['ServiceUnavailable', 'TooManyRequests'])
def test_r2_429_retries_with_real_sdk_and_preserves_upload(transport, code, caplog):
    from congress_api.retention.r2 import R2Store
    import json
    data, key = b'compressed', 'bodies/sha256/test.gz'
    with s3_responses([(429, code, {'Retry-After': '1'}), (200, '', {})]) as (options, calls):
        if transport == 'sync':
            with closing(boto3.client('s3', **options)) as client:
                assert R2Store(client, 'archive').put(key, data, immutable=True)
        else:
            async def run():
                async with get_session().create_client('s3', **options) as client:
                    assert await AsyncBodies(client, 'archive').put(key, data)
            asyncio.run(run())
        assert len(calls) == 2
        assert calls[1]['time'] - calls[0]['time'] >= 1
        assert all(c['body'] == data and c['headers']['If-None-Match'] == '*' for c in calls)
        events = [json.loads(r.message) for r in caplog.records if r.name == 'congress_api.retention.r2']
        assert events[0]['key'] == key
        assert events[0]['request_id'] == 'test-request'
        assert events[0]['http_status'] == 429 and events[0]['attempt'] == 1


@pytest.mark.parametrize('sequence', [
    [(429, 'ServiceUnavailable', {})] * 3,
    [(503, 'ServiceUnavailable', {}), (429, 'TooManyRequests', {}), (503, 'ServiceUnavailable', {})],
])
def test_r2_throttle_and_sdk_errors_share_one_attempt_budget(sequence):
    from botocore.exceptions import ClientError
    with s3_responses(sequence) as (options, calls):
        async def run():
            async with get_session().create_client('s3', **options) as client:
                with pytest.raises(ClientError) as caught:
                    await AsyncBodies(client, 'archive').put('bodies/test.gz', b'data')
                assert caught.value.response['ResponseMetadata']['RetryAttempts'] == 2
        asyncio.run(run())
        assert len(calls) == 3


@pytest.mark.parametrize('status,code,headers', [
    (403, 'AccessDenied', {}),
    (429, 'SlowDown', {'Retry-After': '61'}),
])
def test_r2_refuses_permanent_errors_and_excessive_waits(status, code, headers):
    from botocore.exceptions import ClientError
    with s3_responses([(status, code, headers)]) as (options, calls):
        async def run():
            async with get_session().create_client('s3', **options) as client:
                with pytest.raises(ClientError):
                    await AsyncBodies(client, 'archive').put('bodies/test.gz', b'data')
        asyncio.run(run())
        assert len(calls) == 1


def test_r2_retry_does_not_overwrite_existing_body_or_add_retries_when_disabled():
    from botocore.exceptions import ClientError
    with s3_responses([(429, 'ServiceUnavailable', {}), (412, 'PreconditionFailed', {})]) as (options, calls):
        async def run():
            async with get_session().create_client('s3', **options) as client:
                assert await AsyncBodies(client, 'archive').put('bodies/test.gz', b'data') is False
        asyncio.run(run())
        assert len(calls) == 2
    with s3_responses([(429, 'ServiceUnavailable', {})]) as (options, calls):
        options['config'] = options['config'].merge(Config(retries={'total_max_attempts': 1, 'mode': 'standard'}))
        async def run():
            async with get_session().create_client('s3', **options) as client:
                with pytest.raises(ClientError):
                    await AsyncBodies(client, 'archive').put('bodies/test.gz', b'data')
        asyncio.run(run())
        assert len(calls) == 1


def test_r2_backoff_is_async_and_cancellable():
    with s3_responses([(429, 'ServiceUnavailable', {})]) as (options, calls):
        async def run():
            async with get_session().create_client('s3', **options) as client:
                task = asyncio.create_task(AsyncBodies(client, 'archive').put('bodies/test.gz', b'data'))
                try:
                    async with asyncio.timeout(3):
                        while not calls:
                            await asyncio.sleep(0.01)
                    await asyncio.sleep(0.1)
                    assert not task.done()
                    assert len(calls) == 1
                finally:
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
        asyncio.run(run())


def test_capture_recovers_from_r2_throttle_without_duplicate_uploads():
    from test_async_capture import receipts
    with s3_responses([(429, 'ServiceUnavailable', {}), (200, '', {})]) as (options, calls):
        class Store(MemoryStore):
            @asynccontextmanager
            async def async_bodies(self):
                async with get_session().create_client('s3', **options) as client:
                    yield AsyncBodies(client, 'archive')

        async def run():
            store = Store()
            result = await run_async(Archive(store, 'throttle'),
                [{'url': f'https://example.gov/{i}.pdf'} for i in range(3)],
                fetch=lambda u: response(u, b'%PDF-1.7\n%%EOF'), workers=3, limit=3)
            assert result['saved'] == 3
            assert len(receipts(store)) == 3
            restored = Archive(store, 'readback')
            assert all(row['outcome'] == 'saved' for row in restored.state.values())
        asyncio.run(run())
        assert len(calls) == 2  # Three aliases share one upload and its retry.


def test_native_s3_uploads_overlap_and_preserve_conditional_checksums():
    both, release = threading.Event(), threading.Event()
    guard = threading.Lock()
    received, headers = {}, []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def do_PUT(self):
            data = self.rfile.read(int(self.headers['Content-Length']))
            with guard:
                received[self.path] = data
                headers.append(dict(self.headers))
                if len(received) == 2:
                    both.set()
            assert release.wait(5)
            self.send_response(200)
            self.send_header('ETag', '"' + hashlib.md5(data).hexdigest() + '"')
            self.send_header('Content-Length', '0')
            self.end_headers()

        def log_message(self, *args):
            pass

        def do_GET(self):
            data = received[self.path]
            self.send_response(200)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    class Store(MemoryStore):
        @asynccontextmanager
        async def async_bodies(self):
            async with get_session().create_client('s3',
                endpoint_url=f'http://127.0.0.1:{server.server_port}', region_name='auto',
                aws_access_key_id='test', aws_secret_access_key='test',
                config=Config(retries={'max_attempts': 0}, max_pool_connections=4,
                              request_checksum_calculation='when_required',
                              response_checksum_validation='when_required')) as client:
                bodies = AsyncBodies(client, 'archive')
                yield bodies
                for path, data in received.items():
                    assert await bodies.read(path.removeprefix('/archive/')) == data

    async def check():
        store = Store()
        task = asyncio.create_task(run_async(Archive(store, 'native-s3'),
            [{'url': f'https://example.gov/{i}.pdf'} for i in range(2)],
            fetch=lambda u: response(u, b'%PDF-1.7\n' + u.encode() + b'\n%%EOF'), workers=2))
        try:
            assert await asyncio.to_thread(both.wait, 3), 'R2 uploads remained serial'
            assert not store.keys('receipts/')
        finally:
            release.set()
        result = await asyncio.wait_for(task, 5)
        assert result['saved'] == 2
        assert len(received) == 2
        assert all(h['If-None-Match'] == '*' and h['Content-MD5'] for h in headers)
        assert store.keys('receipts/')

    try:
        asyncio.run(check())
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join()
