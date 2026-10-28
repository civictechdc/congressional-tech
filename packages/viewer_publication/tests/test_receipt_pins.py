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
    def __init__(self): self.objects = {}; self.puts = []; self.gets = []
    def create(self, key, data, **headers):
        self.puts.append((key, headers))
        if key in self.objects:
            assert self.objects[key] == data
        else: self.objects[key] = data
    def get(self, key):
        self.gets.append(key)
        return self.objects[key]
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


def test_kept_input_records_return_all_metadata_and_read_shared_lists_once():
    from collections import Counter
    store=Store();expected=[]
    for release,input_id in [('a'*64,'b'*64),('a'*64,'c'*64),('d'*64,'e'*64)]:
        record=dict(input_digest=input_id,profile={'version':'retained'},snapshots={'captures':{'snapshot':7}})
        actual=pins.write_input_receipts(store,release,input_id,record,['receipts/z','receipts/a'])
        expected.append(dict(release_id=release,key=pins.PREFIX+release+'/inputs/'+input_id+'.json',
            record=actual,receipt_keys=['receipts/a','receipts/z']))
    before=list(store.puts)
    entries,protected=pins.kept_input_records(store,['d'*64,'a'*64,'a'*64])
    assert entries==expected
    assert protected==set(store.objects)
    assert Counter(store.gets)==Counter({key:1 for key in store.objects})
    assert store.puts==before
    store.gets.clear()
    assert pins.kept_receipt_keys(store,['a'*64,'d'*64])==protected
    assert Counter(store.gets)==Counter({key:1 for key in store.objects})


@pytest.mark.parametrize('corruption',['missing','changed'])
def test_same_list_digest_in_another_kept_release_still_requires_its_own_valid_object(corruption):
    store=Store()
    for release in ['a'*64,'d'*64]:
        pins.write_input_receipts(store,release,'b'*64,{'input_digest':'b'*64},['receipts/a'])
    key=next(key for key in store.objects if '/'+('d'*64)+'/' in key and key.endswith('.json.gz'))
    if corruption=='missing':del store.objects[key]
    else:store.objects[key]=b'changed'
    before=list(store.puts)
    with pytest.raises(ValueError):pins.kept_input_records(store,['a'*64,'d'*64])
    assert store.puts==before


def test_bad_later_input_record_prevents_returning_any_kept_evidence():
    store=Store();release='a'*64
    for input_id in ['b'*64,'c'*64]:
        pins.write_input_receipts(store,release,input_id,{'input_digest':input_id},['receipts/a'])
    key=pins.PREFIX+release+'/inputs/'+('c'*64)+'.json'
    value=json.loads(store.objects[key]);value['input_digest']='d'*64
    store.objects[key]=json.dumps(value).encode()
    with pytest.raises(ValueError,match='Input record identity differs'):
        pins.kept_input_records(store,[release])
