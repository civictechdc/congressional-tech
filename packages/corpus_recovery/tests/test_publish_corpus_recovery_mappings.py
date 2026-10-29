"""Check conditional mapping writes, failures and acknowledgment loss."""
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest

import pytest

from corpus_recovery.mappings import KEY, publish_mappings
from viewer_publication.client import VerifiedTransfer


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
        self.gets = self.heads = 0

    def get_object(self, **kwargs):
        self.gets += 1
        return dict(Body=io.BytesIO(self.raw), ContentLength=len(self.raw), ETag=self.etag)

    def head_object(self, **kwargs):
        self.heads += 1
        return dict(ContentLength=len(self.raw), ETag=self.etag)

    def put_object(self, **kwargs):
        self.writes.append(kwargs)
        if self.conflict or kwargs['IfMatch'] != self.etag:
            raise RuntimeError('Precondition failed')
        self.raw = b'changed' if self.corrupt else kwargs['Body']
        self.etag = 'new'
        if self.lose_ack:
            raise TimeoutError('Acknowledgment lost')
        return {'ETag': self.etag}


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

    def test_stores_canonical_rows_and_cleans_a_non_canonical_mapping(self):
        def validate(rows):
            return [{key: row[key] for key in ('original_url', 'body_key')} for row in rows]
        raw = dict(version=1, recoveries=[dict(original_url='https://example.org/a', body_key='new',
                                               body_path='/Users/someone/local/body.html')])
        client = Client(raw)
        self.saved = {}
        result = publish_mappings(client, bucket='test', baseline=raw, prepared=raw, validate=validate,
            guard=lambda: None, save_payload=self.saved.__setitem__, journal=lambda event, value: None)
        self.assertTrue(result['wrote'])
        self.assertEqual(json.loads(client.raw), doc('new'))
        # Once canonical, the same publication is a no-op.
        self.assertFalse(publish_mappings(client, bucket='test', baseline=doc('new'), prepared=raw,
            validate=validate, guard=lambda: None, save_payload=self.saved.__setitem__,
            journal=lambda event, value: None)['wrote'])

    def test_validator_failure_blocks_write(self):
        def validate(rows):
            raise ValueError('Invalid mapping')
        client = Client(doc())
        with self.assertRaisesRegex(ValueError, 'Invalid'):
            self.run_publish(client, validate=validate)
        self.assertFalse(client.writes)

    def test_verified_transfer_is_consumed_without_another_body_read(self):
        client = Client(doc())
        body_reads = []
        original = client.get_object
        def track(**kwargs):
            body_reads.append(kwargs['Key'])
            return original(**kwargs)
        client.get_object = track
        def put_object(**kwargs):
            client.writes.append(kwargs)
            client.raw = kwargs['Body']
            client.etag = 'new'
            digest = hashlib.sha256(kwargs['Body']).hexdigest()
            return {'_verified_transfer': VerifiedTransfer(
                'test', KEY, len(kwargs['Body']), digest, 'new')}
        client.put_object = put_object
        confirmed = []
        def confirm(receipt, *, bucket, key, size, sha256):
            confirmed.append((receipt, bucket, key, size, sha256))
            return True
        client.confirm_transfer = confirm
        result = self.run_publish(client)
        self.assertEqual(body_reads, [KEY])
        self.assertEqual(len(client.writes), 1)
        self.assertEqual(len(confirmed), 1)
        self.assertEqual(confirmed[0][1:], ('test', KEY, len(client.raw), hashlib.sha256(client.raw).hexdigest()))
        self.assertEqual(result['etag'], 'new')
        self.assertFalse(result['acknowledgment_reconciled'])

    def test_rejected_transfer_checks_bytes_without_rewriting(self):
        client = Client(doc())
        body_reads = []
        original = client.get_object
        def track(**kwargs):
            body_reads.append(kwargs['Key'])
            return original(**kwargs)
        client.get_object = track
        def put_object(**kwargs):
            client.writes.append(kwargs)
            return {'_verified_transfer': VerifiedTransfer('test', KEY, 1, 'ab', 'new')}
        client.put_object = put_object
        client.confirm_transfer = lambda *args, **kwargs: False
        with self.assertRaisesRegex(ValueError, 'readback'):
            self.run_publish(client)
        self.assertEqual(len(client.writes), 1)
        self.assertEqual(body_reads, [KEY, KEY])


class CountedBody(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.consumed = 0

    def read(self, size=-1):
        assert size >= 0, 'control read must request a bounded amount'
        chunk = super().read(size)
        self.consumed += len(chunk)
        return chunk


def test_publisher_and_mapping_share_one_control_reader_and_policy():
    import congress_api.retention.control_documents as controls
    import corpus_recovery.mappings as mappings
    import viewer_publication.publish_viewer_r2 as publisher
    assert publisher.bounded_control_read is mappings.bounded_control_read is controls.bounded_control_read
    assert publisher.CONTROL_LIMITS is mappings.CONTROL_LIMITS is controls.CONTROL_LIMITS
    assert controls.CONTROL_LIMITS == {'manifest': 4 * 1024**2, 'accepted': 16 * 1024**2, 'recovery': 32 * 1024**2}


@pytest.mark.parametrize('proof', ['issued', 'missing', 'foreign', 'stale', 'wrong_key'])
def test_real_guarded_receipts_or_independent_fallback_verify_one_put(proof):
    from viewer_publication.client import GuardedPublicationClient
    base = Client(doc())
    events, saved = [], {}
    journal = lambda event, value: events.append(event)
    other = GuardedPublicationClient(base, guard=lambda: None, journal=journal, after_write=lambda *args: None)

    class Proxy(GuardedPublicationClient):
        def put_object(self, **kwargs):
            result = super().put_object(**kwargs)
            if proof == 'missing':
                result.pop('_verified_transfer')
            elif proof == 'foreign':
                result = other.verified_result({}, bucket='test', key=KEY, size=len(base.raw),
                    sha256=hashlib.sha256(base.raw).hexdigest(), etag=base.etag)
            elif proof == 'stale':
                base.etag = 'same-bytes-new-version'
            elif proof == 'wrong_key':
                result = self.verified_result({}, bucket='test', key='viewer-publications/other', size=len(base.raw),
                    sha256=hashlib.sha256(base.raw).hexdigest(), etag=base.etag)
            return result

    proxy = Proxy(base, guard=lambda: None, journal=journal, after_write=lambda *args: None)
    result = publish_mappings(proxy, bucket='test', baseline=doc(), prepared=doc('new'), validate=lambda rows: rows,
        guard=lambda: None, save_payload=saved.__setitem__, journal=journal)
    assert result['complete'] and not result['viewer_pointer_advanced']
    # The receipt records our acknowledged write, not a later remote version.
    assert result['etag'] == 'new'
    assert base.etag == ('same-bytes-new-version' if proof == 'stale' else 'new')
    assert len(base.writes) == 1 and base.writes[0]['IfMatch'] == 'old'
    assert base.raw == saved['accepted-proposed.json']
    assert json.loads(saved['accepted-before.json']) == doc()
    # Successful guarded PUTs need no readback; unusable receipts require one.
    assert base.gets == (1 if proof in ('issued', 'stale') else 2)
    assert base.heads == 0
    assert events.count('publication_write_verified') == 1


@pytest.mark.parametrize('proof', ['missing', 'foreign', 'wrong_key'])
def test_unusable_guarded_receipt_still_rejects_changed_mapping_readback(proof):
    from viewer_publication.client import GuardedPublicationClient
    base = Client(doc())
    events = []
    options = dict(guard=lambda: None, journal=lambda event, value: events.append(event),
                   after_write=lambda *args: None)
    other = GuardedPublicationClient(base, **options)

    class Proxy(GuardedPublicationClient):
        def put_object(self, **kwargs):
            result = super().put_object(**kwargs)
            if proof == 'missing':
                result.pop('_verified_transfer')
            else:
                issuer = other if proof == 'foreign' else self
                key = KEY if proof == 'foreign' else 'viewer-publications/other'
                result = issuer.verified_result({}, bucket='test', key=key, size=len(base.raw),
                    sha256=hashlib.sha256(base.raw).hexdigest(), etag=base.etag)
            base.raw = base.raw.replace(b'"new"', b'"bad"')
            assert base.raw != kwargs['Body'] and len(base.raw) == len(kwargs['Body'])
            base.etag = 'concurrent-version'
            return result

    with pytest.raises(ValueError, match='readback differs'):
        publish_mappings(Proxy(base, **options), bucket='test', baseline=doc(), prepared=doc('new'),
            validate=lambda rows: rows, guard=lambda: None, save_payload=lambda *args: None,
            journal=options['journal'])
    assert len(base.writes) == 1 and base.writes[0]['IfMatch'] == 'old'
    assert base.gets == 2 and base.heads == 0
    assert events.count('publication_write_verified') == 1
    assert 'mapping_readback_verified' not in events


@pytest.mark.parametrize('mutation', ['mapping_version', 'mapping_bytes', 'source_pin'])
def test_acknowledged_mapping_does_not_authorize_next_write_after_input_changes(tmp_path, mutation):
    from corpus_recovery.guards import RecoveryGuard
    from viewer_publication.client import GuardedPublicationClient
    base = Client(doc())
    source = tmp_path / 'source.json'
    source.write_bytes(b'original source')
    versions = {KEY: 'old'}

    def protected_check():
        if base.head_object(Bucket='test', Key=KEY)['ETag'] != versions[KEY]:
            raise RuntimeError('Publication input changed: ' + KEY)

    guard = RecoveryGuard(pins={source: hashlib.sha256(source.read_bytes()).hexdigest()},
        local_check=lambda: None, cloud_check=lambda: None, protected_check=protected_check)

    class Proxy(GuardedPublicationClient):
        def put_object(self, **kwargs):
            result = super().put_object(**kwargs)
            if mutation == 'source_pin':
                source.write_bytes(b'changed source!')
            else:
                base.etag = 'concurrent-version'
                if mutation == 'mapping_bytes':
                    base.raw = base.raw.replace(b'"new"', b'"bad"')
            return result

    proxy = Proxy(base, guard=guard, journal=lambda *args: None,
        after_write=lambda key, etag: versions.__setitem__(key, etag))
    result = publish_mappings(proxy, bucket='test', baseline=doc(), prepared=doc('new'),
        validate=lambda rows: rows, guard=guard.boundary, save_payload=lambda *args: None,
        journal=lambda *args: None)
    assert result['complete'] and result['etag'] == versions[KEY] == 'new'
    assert len(base.writes) == 1 and base.gets == 1
    # The next mutable write must refresh the real guard before reaching PUT.
    with pytest.raises(RuntimeError, match='Pinned input changed|Publication input changed'):
        proxy.put_object(Bucket='test', Key=KEY, Body=b'next payload', IfMatch=result['etag'])
    assert len(base.writes) == 1


def test_guarded_failure_keeps_its_own_reconciliation_without_outer_read():
    from viewer_publication.client import GuardedPublicationClient
    client = Client(doc())
    request_error, read_error = TimeoutError('request detail'), OSError('read detail')
    original_put, original_get = client.put_object, client.get_object
    def put(**kwargs):
        original_put(**kwargs)
        raise request_error
    def get(**kwargs):
        if client.writes:
            client.gets += 1
            raise read_error
        return original_get(**kwargs)
    client.put_object, client.get_object = put, get
    proxy = GuardedPublicationClient(client, guard=lambda: None,
        journal=lambda *args: None, after_write=lambda *args: None)
    with pytest.raises(RuntimeError, match='outcome is uncertain') as caught:
        publish_mappings(proxy, bucket='test', baseline=doc(), prepared=doc('new'), validate=lambda rows: rows,
            guard=lambda: None, save_payload=lambda *args: None, journal=lambda *args: None)
    assert caught.value.request_error is request_error
    assert caught.value.reconciliation_error is read_error
    assert client.gets == 2 and len(client.writes) == 1


def test_plain_lost_ack_reuses_exact_readback_and_retains_both_failures():
    client = Client(doc()); client.lose_ack = True
    result = publish_mappings(client, bucket='test', baseline=doc(), prepared=doc('new'), validate=lambda rows: rows,
        guard=lambda: None, save_payload=lambda *args: None, journal=lambda *args: None)
    assert result['acknowledgment_reconciled'] and client.gets == 2 and len(client.writes) == 1
    client = Client(doc())
    request_error = TimeoutError('signed URL and secret request detail')
    read_error = OSError('secret reconciliation detail')
    original_put, original_get = client.put_object, client.get_object
    def put(**kwargs):
        original_put(**kwargs)
        raise request_error
    def get(**kwargs):
        if client.writes:
            raise read_error
        return original_get(**kwargs)
    client.put_object, client.get_object = put, get
    with pytest.raises(RuntimeError, match='outcome is uncertain') as caught:
        publish_mappings(client, bucket='test', baseline=doc(), prepared=doc('new'), validate=lambda rows: rows,
            guard=lambda: None, save_payload=lambda *args: None, journal=lambda *args: None)
    assert caught.value.request_error is caught.value.__cause__ is request_error
    assert caught.value.reconciliation_error is read_error
    assert 'secret' not in str(caught.value) and all('secret' not in note for note in caught.value.__notes__)
    assert len(client.writes) == 1


@pytest.mark.parametrize('damage', ['declared_oversize', 'streamed_oversize', 'truncated', 'malformed', 'shape', 'version', 'missing_version'])
def test_mapping_admission_closes_bad_input_before_any_write(damage):
    from congress_api.retention.control_documents import CONTROL_LIMITS
    client = Client(doc())
    raw, declared, etag = client.raw, len(client.raw), 'old'
    if damage == 'declared_oversize':
        declared = CONTROL_LIMITS['accepted'] + 1
    elif damage == 'streamed_oversize':
        raw = b' ' * (CONTROL_LIMITS['accepted'] + 1)
        declared = CONTROL_LIMITS['accepted']
    elif damage == 'truncated':
        declared += 1
    elif damage == 'malformed':
        raw = b'{'; declared = len(raw)
    elif damage == 'shape':
        raw = b'[]'; declared = len(raw)
    elif damage == 'version':
        raw = json.dumps(dict(version=True, recoveries=[])).encode(); declared = len(raw)
    else:
        etag = ''
    body = CountedBody(raw)
    client.get_object = lambda **kwargs: dict(Body=body, ContentLength=declared, ETag=etag)
    with pytest.raises(ValueError):
        publish_mappings(client, bucket='test', baseline=doc(), prepared=doc('new'), validate=lambda rows: rows,
            guard=lambda: None, save_payload=lambda *args: None, journal=lambda *args: None)
    assert not client.writes and body.closed
    assert body.consumed <= CONTROL_LIMITS['accepted'] + 1
    if damage == 'declared_oversize':
        assert body.consumed == 0


def test_proposed_mapping_must_fit_supported_ceiling_before_put(monkeypatch):
    from congress_api.retention.control_documents import CONTROL_LIMITS
    client = Client(doc())
    monkeypatch.setitem(CONTROL_LIMITS, 'accepted', len(client.raw))
    with pytest.raises(ValueError, match='byte limit'):
        publish_mappings(client, bucket='test', baseline=doc(), prepared=doc('new'), validate=lambda rows: rows,
            guard=lambda: None, save_payload=lambda *args: None, journal=lambda *args: None)
    assert not client.writes


if __name__ == '__main__':
    unittest.main()
