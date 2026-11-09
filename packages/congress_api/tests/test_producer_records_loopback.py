"""Owed producer records' compare-and-swap through the real S3 SDK against a local HTTP fake."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import pytest

from congress_api.lake.producer_records import ProducerRecords, owed_key

pytestmark = pytest.mark.loopback
BASE = dict(table_uuid='01a1a35c-8940-77f2-a48f-c52881d2ccb2', snapshot=7)
PRECONDITION = (b'<?xml version="1.0" encoding="UTF-8"?><Error><Code>PreconditionFailed</Code>'
                b'<Message>At least one of the pre-conditions you specified did not hold</Message></Error>')


@pytest.fixture
def bucket():
    """One bucket honouring If-Match / If-None-Match per object, as R2 does."""
    objects, headers = {}, []

    class Handler(BaseHTTPRequestHandler):
        def _key(self):
            return self.path.split('?')[0].split('/', 2)[2]

        def _send(self, status, body=b'', etag=None, content_type='application/xml'):
            self.send_response(status)
            if etag:
                self.send_header('ETag', etag)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            found = objects.get(self._key())
            if found is None:
                return self._send(404, b'<?xml version="1.0"?><Error><Code>NoSuchKey</Code></Error>')
            self._send(200, found[0], found[1], 'application/json')

        def do_PUT(self):
            data = self.rfile.read(int(self.headers['Content-Length']))
            key, current = self._key(), objects.get(self._key())
            headers.append({k: self.headers[k] for k in ('If-Match', 'If-None-Match') if self.headers[k]})
            if (self.headers['If-None-Match'] == '*' and current is not None
                    or self.headers['If-Match'] and (current is None or current[1] != self.headers['If-Match'])):
                return self._send(412, PRECONDITION)
            objects[key] = (data, '"' + hashlib.md5(data).hexdigest() + '"')
            self._send(200, etag=objects[key][1])

        def log_message(self, *args):
            pass

    import boto3
    from botocore.config import Config
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = boto3.client('s3', endpoint_url=f'http://127.0.0.1:{server.server_port}',
                              aws_access_key_id='test', aws_secret_access_key='test', region_name='auto',
                              config=Config(retries={'total_max_attempts': 1}, s3={'addressing_style': 'path'},
                                            request_checksum_calculation='when_required'))
        yield ProducerRecords(client=client, bucket='raw'), objects, headers
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_owed_records_change_only_from_the_version_they_were_read_at(bucket):
    records, objects, headers = bucket
    intent = dict(input='captures', base=dict(selector=dict(kind='native_table', **BASE), record=None))
    assert records.owed(BASE) is None
    key = records.owe(dict(intent, owed=dict(status='pending')), None)
    assert key == owed_key(BASE) and headers[-1] == {'If-None-Match': '*'}
    with pytest.raises(ValueError, match='changed concurrently'):  # A 412 is never a success.
        records.owe(dict(intent, owed=dict(status='pending', other=True)), None)

    found, _, version = records.owed(BASE)
    assert found['owed'] == dict(status='pending') and version == objects[key][1]
    records.owe(dict(intent, owed=dict(status='refused')), version)
    assert headers[-1] == {'If-Match': version}
    with pytest.raises(ValueError, match='changed concurrently'):  # The read version is now stale.
        records.owe(dict(intent, owed=dict(status='recorded')), version)
    assert records.owed(BASE)[0]['owed'] == dict(status='refused')
