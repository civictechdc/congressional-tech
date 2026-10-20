"""Raw and catalog snapshots share the same narrow conditional selector write."""
from hashlib import sha256

import pytest

from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.r2 import R2Store
from test_r2_archive_store import client, Stubber


def test_local_selector_cas_preserves_winner_and_independent_selector(tmp_path):
    store = LocalStore(tmp_path)
    key = 'indexes/raw.json'
    store.put_index_selector(key, b'first', expected_version=None)
    old = sha256(b'first').hexdigest()
    store.put_index_selector(key, b'winner', expected_version=old)
    with pytest.raises(RuntimeError, match='Concurrent'):
        store.put_index_selector(key, b'loser', expected_version=old)
    assert store.read(key) == b'winner'
    store.put_catalog_manifest(b'catalog', expected_version=None)
    assert store.read('indexes/catalog.json') == b'catalog'
    assert store.read(key) == b'winner'
    with pytest.raises(ValueError, match='selector'):
        store.put_index_selector('../outside.json', b'bad', expected_version=None)


def test_remote_selector_uses_captured_version_even_after_other_reads():
    from congress_api.retention.r2 import put_parameters
    c = client()
    key, data = 'indexes/raw.json', b'candidate'
    with Stubber(c) as stub:
        stub.add_client_error('put_object', service_error_code='PreconditionFailed', http_status_code=412,
            expected_params=put_parameters('archive', key, data, IfMatch='"original"'))
        store = R2Store(c, 'archive')
        store.index_etags[key] = '"subsequent-read"'
        with pytest.raises(RuntimeError, match='Concurrent'):
            store.put_index_selector(key, data, expected_version='"original"')
        stub.assert_no_pending_responses()
