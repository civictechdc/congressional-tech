"""The publisher must not bypass guards through managed file uploads."""
import io
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from guarded_recovery_publication_client import GuardedPublicationClient


class Client:
    def __init__(self):
        self.calls = []; self.raw = b''; self.lose_ack = False
    def put_object(self, **kwargs):
        self.calls.append(kwargs)
        body = kwargs['Body']
        self.raw = body if isinstance(body, bytes) else body.read()
        if self.lose_ack:
            raise TimeoutError()
        return {'ETag': 'new'}
    def get_object(self, **kwargs):
        return dict(Body=io.BytesIO(self.raw), ContentLength=len(self.raw), ETag='new')


class GuardTests(unittest.TestCase):
    def make(self, client, guard=lambda: None):
        self.updated = []
        return GuardedPublicationClient(client, guard=guard,
            journal=lambda event, value: None,
            after_write=lambda key, etag: self.updated.append((key, etag)))

    def test_file_transfer_is_conditional_and_guarded(self):
        client = Client(); checks = []
        proxy = self.make(client, lambda: checks.append(True))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'file'; path.write_bytes(b'full bytes')
            proxy.upload_file(path, 'bucket', 'viewer-publications/releases/x/file')
        self.assertEqual(checks, [True])
        self.assertEqual(client.raw, b'full bytes')
        self.assertEqual(client.calls[0]['IfNoneMatch'], '*')
        self.assertEqual(len(self.updated), 1)

    def test_raw_index_and_unconditional_writes_blocked(self):
        client = Client(); proxy = self.make(client)
        for kwargs in [dict(Key='indexes/captures.parquet', IfMatch='old'),
                       dict(Key='indexes/catalog.json')]:
            with self.assertRaises(ValueError):
                proxy.put_object(Bucket='bucket', Body=b'x', **kwargs)
        self.assertFalse(client.calls)

    def test_guard_failure_stops_file_upload(self):
        def refuse(): raise RuntimeError('Competing writer')
        client = Client(); proxy = self.make(client, refuse)
        with self.assertRaises(RuntimeError):
            proxy.put_object(Bucket='b', Key='indexes/catalog.json', Body=b'x', IfMatch='old')
        self.assertFalse(client.calls)

    def test_lost_ack_does_not_repeat_write(self):
        client = Client(); client.lose_ack = True; proxy = self.make(client)
        proxy.put_object(Bucket='b', Key='indexes/catalog.json', Body=b'x', IfMatch='old')
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(len(self.updated), 1)


if __name__ == '__main__': unittest.main()
