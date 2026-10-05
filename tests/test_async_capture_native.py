"""Real async S3 transport on loopback; intentionally outside the offline suite."""
import asyncio
from contextlib import asynccontextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

from aiobotocore.session import get_session
from botocore.config import Config

from congress_api.acquisition.raw_sync import run_async
from congress_api.retention.raw_archive import Archive
from congress_api.retention.r2 import AsyncBodies
from test_raw_source_sync import MemoryStore, response


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
