"""F4: kept input identities retain their exact, verifiable receipt keys."""
import gzip
from hashlib import sha256
import json

import pytest

from viewer_publication import receipt_pins as pins


def test_receipt_list_identity_is_uncompressed_canonical_json():
    digest, payload = pins.receipt_list(['receipts/z.jsonl.gz', 'receipts/é.jsonl.gz', 'receipts/a.jsonl.gz', 'receipts/z.jsonl.gz'])
    raw = '["receipts/a.jsonl.gz","receipts/z.jsonl.gz","receipts/é.jsonl.gz"]'.encode()
    assert digest == sha256(raw).hexdigest()
    assert gzip.decompress(payload) == raw
    assert payload == pins.receipt_list(json.loads(raw))[1]
    assert pins.read_receipt_list(digest, payload) == json.loads(raw)


@pytest.mark.parametrize('keys', [['bodies/a'], ['receipts/../escape'], ['receipts/a?token=x'], ['receipts/a\\b'], [None]])
def test_receipt_list_rejects_non_receipt_object_keys(keys):
    with pytest.raises(ValueError):
        pins.receipt_list(keys)


def test_corrupted_or_noncanonical_receipt_list_refuses():
    digest, payload = pins.receipt_list(['receipts/a'])
    with pytest.raises(ValueError):
        pins.read_receipt_list('0' * 64, payload)
    raw = b'["receipts/z","receipts/a"]'
    with pytest.raises(ValueError):
        pins.read_receipt_list(sha256(raw).hexdigest(), gzip.compress(raw, mtime=0))
    with pytest.raises(ValueError):
        pins.read_receipt_list(digest, b'bad gzip')


class Store:
    def __init__(self): self.objects = {}; self.puts = []
    def create(self, key, data, **headers):
        self.puts.append((key, headers))
        if key in self.objects:
            assert self.objects[key] == data
        else: self.objects[key] = data
    def get(self, key): return self.objects[key]
    def keys(self, prefix): return [key for key in self.objects if key.startswith(prefix)]


def test_same_release_new_input_keeps_all_receipt_lists_for_replay():
    store = Store(); release = 'a' * 64
    for input_id, receipt in [('b' * 64, 'receipts/a'), ('c' * 64, 'receipts/b')]:
        pins.write_input_receipts(store, release, input_id, {'input_digest': input_id, 'profile': {}}, [receipt])
    expected = dict(store.objects)
    pins.write_input_receipts(store, release, 'b' * 64, {'input_digest': 'b' * 64, 'profile': {}}, ['receipts/a'])
    assert store.objects == expected
    protected = pins.kept_receipt_keys(store, [release])
    assert protected == set(store.objects)
    assert len(protected) == 4
    assert all(headers['content_md5'] and headers['cache_control'].endswith('immutable') for _, headers in store.puts)


def test_kept_release_with_missing_or_changed_receipt_list_blocks_maintenance():
    store = Store(); release = 'a' * 64
    pins.write_input_receipts(store, release, 'b' * 64, {'input_digest': 'b' * 64}, ['receipts/a'])
    key = next(key for key in store.objects if key.endswith('.json.gz'))
    store.objects[key] = b'changed'
    with pytest.raises(ValueError): pins.kept_receipt_keys(store, [release])
    del store.objects[key]
    with pytest.raises(ValueError): pins.kept_receipt_keys(store, [release])
