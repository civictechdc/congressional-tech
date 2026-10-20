"""Raw captures and URL state publish as one exact native snapshot."""
from hashlib import sha256
import os
import shutil

import pyarrow as pa
import pytest

from native_test_helpers import native_test_client
from congress_api.retention.raw_archive import CAPTURE_SCHEMA, STATE_SCHEMA
from congress_api.retention.docspec import DocSpecFailure
from congress_api.retention.raw_storage import RawStorage, RAW_KEY
from test_raw_source_sync import MemoryStore


class SelectorStore(MemoryStore):
    def __init__(self):
        super().__init__()
        self.lose_reply = False
    def put_index_selector(self, key, data, *, expected_version):
        current = self.objects.get(key)
        version = sha256(current).hexdigest() if current is not None else None
        if version != expected_version:
            raise RuntimeError('Concurrent raw update')
        self.put(key, data)
        if self.lose_reply:
            self.lose_reply = False
            raise TimeoutError('reply lost')


@pytest.fixture
def storage(tmp_path):
    binary = os.environ.get('DOCSPEC_BINARY') or shutil.which('docspec')
    if not binary:
        pytest.skip('Set DOCSPEC_BINARY to the qualified maintained CLI')
    store = SelectorStore()
    native = native_test_client(binary, tmp_path / 'native')
    return RawStorage(store, native, max_state_rows=2)


def captures(label):
    return pa.Table.from_pylist([dict(body_key=f'bodies/{label}.gz', receipt_key=f'receipts/{label}.gz',
        receipt_line=1, context_url=f'https://example.gov/{label}', http_status=200, resolution='saved')],
        schema=CAPTURE_SCHEMA)


def states(*labels):
    return pa.Table.from_pylist([dict(url=f'https://example.gov/{label}', outcome='saved',
        attempts=1, links_scanned=True, body_key=f'bodies/{label}.gz') for label in labels], schema=STATE_SCHEMA)


def test_raw_selection_is_coherent_idempotent_and_old_snapshot_survives(storage):
    old = storage.snapshot()
    first = storage.prepare(old, operation='first', captures=captures('a'), states=states('a'))
    competing = storage.prepare(old, operation='competing', captures=captures('b'), states=states('b'))
    restarted = RawStorage(storage.store, storage.native, max_state_rows=2)
    replay = restarted.prepare(restarted.snapshot(), operation='first', captures=captures('a'), states=states('a'))
    assert replay['data'] == first['data']
    with pytest.raises(DocSpecFailure, match='operation_conflict'):
        storage.prepare(old, operation='first', captures=captures('different'), states=states('a'))
    storage.store.lose_reply = True
    selected = storage.publish(first)
    assert selected.captures().to_pylist() == captures('a').to_pylist()
    assert selected.states().to_pylist() == states('a').to_pylist()
    assert selected.receipt_keys() == {'receipts/a.gz'}
    assert len(old.captures()) == len(old.states()) == 0
    writes = list(storage.store.writes)
    assert storage.publish(first).manifest == selected.manifest
    assert storage.store.writes == writes
    with pytest.raises(RuntimeError, match='Concurrent'):
        storage.publish(competing)
    assert storage.snapshot().manifest == selected.manifest
    assert storage.snapshot().captures().to_pylist() == captures('a').to_pylist()
    before = list(storage.store.writes)
    unchanged = storage.prepare(selected, operation='unchanged')
    storage.publish(unchanged)
    assert storage.store.writes == before


def test_only_full_state_leaf_splits_and_duplicate_captures_keep_order(storage):
    first = storage.publish(storage.prepare(storage.snapshot(), operation='seed', captures=captures('a'), states=states('a', 'b')))
    old_capture_head = first.manifest['captures']['head']
    changed = storage.prepare(first, operation='append', captures=captures('a'), states=states('c'))
    selected = storage.publish(changed)
    assert selected.manifest['captures']['rows'] == 2
    assert selected.captures().to_pylist() == captures('a').to_pylist() * 2
    assert selected.states()['url'].to_pylist() == states('a', 'b', 'c')['url'].to_pylist()
    assert first.manifest['captures']['head'] == old_capture_head
    assert len(first.states()) == 2
    assert selected.manifest['state']['rows'] == 3
    assert len(list(storage.state_routes.leaf_items(selected.manifest['state']['root']))) >= 2
