"""Check conditional mapping writes, failures and acknowledgment loss."""
import io
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from publish_corpus_recovery_mappings import publish_mappings


def doc(body=None):
    return dict(version=1, recoveries=[] if body is None else
                [dict(original_url='https://example.org/a', body_key=body)])


class Client:
    def __init__(self, value):
        self.raw = json.dumps(value).encode()
        self.etag = 'old'
        self.writes = []
        self.lose_ack = False
        self.conflict = False
        self.corrupt = False

    def get_object(self, **kwargs):
        return dict(Body=io.BytesIO(self.raw), ContentLength=len(self.raw), ETag=self.etag)

    def put_object(self, **kwargs):
        self.writes.append(kwargs)
        if self.conflict or kwargs['IfMatch'] != self.etag:
            raise RuntimeError('Precondition failed')
        self.raw = b'changed' if self.corrupt else kwargs['Body']
        self.etag = 'new'
        if self.lose_ack:
            raise TimeoutError('Acknowledgment lost')


class PublishTests(unittest.TestCase):
    def run_publish(self, client, guard=lambda: None, validate=lambda rows: rows):
        self.saved = {}
        return publish_mappings(client, bucket='test', baseline=doc(), prepared=doc('new'),
            validate=validate, guard=guard, save_payload=self.saved.__setitem__,
            journal=lambda event, value: None)

    def test_lost_ack_reconciles_without_second_write(self):
        client = Client(doc()); client.lose_ack = True
        result = self.run_publish(client)
        self.assertTrue(result['acknowledgment_reconciled'])
        self.assertEqual(len(client.writes), 1)
        self.assertEqual(client.writes[0]['IfMatch'], 'old')
        self.assertEqual(client.raw, self.saved['accepted-proposed.json'])

    def test_conflict_does_not_retry_or_overwrite(self):
        client = Client(doc()); client.conflict = True; old = client.raw
        with self.assertRaisesRegex(RuntimeError, 'Precondition'):
            self.run_publish(client)
        self.assertEqual(len(client.writes), 1)
        self.assertEqual(client.raw, old)

    def test_guard_failure_after_preparation_blocks_write(self):
        calls = []
        def guard():
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError('Competing writer')
        client = Client(doc())
        with self.assertRaisesRegex(RuntimeError, 'Competing'):
            self.run_publish(client, guard=guard)
        self.assertFalse(client.writes)
        self.assertIn('accepted-proposed.json', self.saved)

    def test_changed_readback_is_not_complete(self):
        client = Client(doc()); client.corrupt = True
        with self.assertRaisesRegex(ValueError, 'readback'):
            self.run_publish(client)

    def test_already_current_mapping_needs_no_write(self):
        client = Client(doc('new'))
        self.assertFalse(self.run_publish(client)['wrote'])
        self.assertFalse(client.writes)

    def test_validator_failure_blocks_write(self):
        def validate(rows):
            raise ValueError('Invalid mapping')
        client = Client(doc())
        with self.assertRaisesRegex(ValueError, 'Invalid'):
            self.run_publish(client, validate=validate)
        self.assertFalse(client.writes)


if __name__ == '__main__':
    unittest.main()
