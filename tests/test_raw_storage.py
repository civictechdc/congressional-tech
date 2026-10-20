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


def test_unselected_native_update_does_not_block_independent_raw_candidate(storage, tmp_path):
    """Native latest may advance while the coherent application pin stays old."""
    import pyarrow.parquet as pq
    from congress_api.retention.raw_storage import state_key, STATE_KEY_FIELD

    first = storage.publish(storage.prepare(storage.snapshot(), operation='seed', states=states('a', 'b')))
    _, reference = storage.state_routes.lookup(first.manifest['state']['root'], state_key('https://example.gov/a'))
    base_pin = reference['release']
    rows = storage._read_states(reference).to_pylist()
    rows[0]['attempts'] = 99
    replacement = tmp_path / 'unselected.parquet'
    pq.write_table(pa.Table.from_pylist([rows[0]], schema=storage.state_native_schema), replacement)
    request = dict(dataset=base_pin['dataset']['dataset'], operation='unselected', definition='raw-native-v1',
        base=base_pin['id'], keys=[STATE_KEY_FIELD], replacements=dict(path=str(replacement),
            digest=storage.native.hash_input(replacement)['digest']))
    native_candidate = storage.native.update(request)
    assert native_candidate != base_pin
    assert storage.snapshot().manifest == first.manifest
    assert first.states().equals(states('a', 'b'))
    with pytest.raises(DocSpecFailure, match='stale_base'):
        storage.native.update({**request, 'operation': 'next-candidate'})
    correction = states('a').to_pylist()
    correction[0]['attempts'] = 3
    selected = storage.publish(storage.prepare(storage.snapshot(), operation='independent',
        states=pa.Table.from_pylist(correction, schema=STATE_SCHEMA)))
    assert selected.state('https://example.gov/a')['attempts'] == 3
    assert selected.state('https://example.gov/b') == first.state('https://example.gov/b')
    assert first.states().equals(states('a', 'b'))
from contextlib import contextmanager
from copy import deepcopy

from congress_api.retention.raw_values import NATIVE_CAPTURE_SCHEMA, capture_table
from congress_api.retention.raw_storage import STATE_NATIVE_SCHEMA


def test_delivery_retry_after_later_publication_does_not_append(storage):
    first = storage.publish(storage.prepare(storage.snapshot(), operation='delivery', captures=captures('a'), states=states('a')))
    later = storage.publish(storage.prepare(first, operation='later', captures=captures('b'), states=states('b')))
    writes = list(storage.store.writes)
    restarted = RawStorage(storage.store, storage.native, max_state_rows=2)
    replay = restarted.prepare(restarted.snapshot(), operation='delivery', captures=captures('a'), states=states('a'))
    result = restarted.publish(replay)
    assert result.manifest == later.manifest
    assert len(result.captures()) == 2
    assert result.delivery['capture_rows'] == 1
    assert result.delivery['first_order'] == 0
    assert replay['already_applied']
    assert storage.store.writes == writes
    with pytest.raises(ValueError, match='request'):
        restarted.prepare(result, operation='delivery', captures=captures('different'), states=states('a'))


def test_selected_state_and_capture_bounds_refuse_before_or_during_accumulation():
    class Native:
        opened = yielded = 0
        @contextmanager
        def source_batches(self, pin, *, schema=None):
            self.opened += 1
            table = capture_table(captures('a'), first_order=0)
            owner = self
            class Reader:
                schema = table.schema
                def __iter__(self):
                    for _ in range(3):
                        owner.yielded += 1
                        yield table.to_batches()[0]
            yield Reader()
    native = Native()
    owner = RawStorage(SelectorStore(), native, max_state_rows=2, max_state_bytes=1024)
    pin = dict(verified=True, id='v', dataset=dict(version='v', groups=dict(source=dict(rows=1))))
    with pytest.raises(ValueError, match='budget'):
        owner._read_states(dict(release=pin, rows=3, decoded_bytes=50))
    with pytest.raises(ValueError, match='budget'):
        owner._read_states(dict(release=pin, rows=1, decoded_bytes=1025))
    assert native.opened == 0
    with pytest.raises(ValueError, match='row count'):
        owner._read_table(pin, 1, schema=NATIVE_CAPTURE_SCHEMA, max_rows=1, max_bytes=1024, decoded_bytes=None)
    assert native.yielded == 2


def test_publish_returns_verified_selection_if_another_writer_advances(storage):
    prepared = storage.prepare(storage.snapshot(), operation='race', captures=captures('a'))
    original_read = storage.store.read
    selected_reads = 0
    def read(key):
        nonlocal selected_reads
        value = original_read(key)
        if key == RAW_KEY and value == prepared['data']:
            selected_reads += 1
            if selected_reads == 1:
                # This is the successful readback; advance immediately after it.
                newer = deepcopy(prepared['manifest'])
                newer['unrelated'] = 'newer writer'
                from congress_api.retention.immutable_metadata import encoded
                storage.store.objects[key] = encoded(newer)
        return value
    storage.store.read = read
    result = storage.publish(prepared)
    assert result.manifest == prepared['manifest']
    assert result.version == sha256(prepared['data']).hexdigest()
    assert storage.snapshot().manifest != result.manifest


def test_capture_single_row_over_byte_budget_refuses_before_native(storage):
    calls = []
    storage._candidate = lambda *args, **kwargs: calls.append(args)
    storage.max_capture_bytes = 1
    with pytest.raises(ValueError, match='single capture'):
        storage.prepare(storage.snapshot(), operation='large', captures=captures('a'))
    assert calls == []


def test_unchanged_state_with_reversed_native_order_has_zero_writes(storage):
    selected = storage.publish(storage.prepare(storage.snapshot(), operation='ordered', states=states('a', 'b')))
    original_batches = storage.native.source_batches
    @contextmanager
    def reversed_batches(pin, *, schema=None):
        with original_batches(pin) as reader:
            table = reader.read_all()
        yield pa.RecordBatchReader.from_batches(table.schema, table.take(pa.array(list(reversed(range(len(table)))))).to_batches())
    storage.native.source_batches = reversed_batches
    storage._candidate = lambda *args, **kwargs: pytest.fail('Identical state caused native write')
    before = list(storage.store.writes)
    prepared = storage.prepare(selected, operation='identical', states=states('a', 'b'))
    assert not prepared['changed']
    storage.publish(prepared)
    assert storage.store.writes == before

def test_body_lookup_and_count_do_not_read_capture_history(storage):
    table = captures('a').to_pylist()
    table[0].update(sha256='a' * 64, bytes=7, stored_sha256='b' * 64, stored_bytes=12)
    table += [dict(body_key='bodies/legacy.gz'), dict(body_key='bodies/legacy.gz')]
    selected = storage.publish(storage.prepare(storage.snapshot(), operation='body-seed',
        captures=pa.Table.from_pylist(table, schema=CAPTURE_SCHEMA)))
    storage.capture_pages.entries = lambda *args: pytest.fail('Hidden full capture history read')
    assert selected.body_info('a' * 64)['body_key'] == 'bodies/a.gz'
    assert selected.body_count == 2
    updated = storage.publish(storage.prepare(selected, operation='body-repeat', captures=captures('a')))
    assert updated.body_count == 2


def test_richer_state_schema_and_null_url_survive_native_selection(storage):
    schema = STATE_SCHEMA.append(pa.field('extra', pa.struct([
        pa.field('large', pa.uint64()), pa.field('nested', pa.list_(pa.binary()))])))
    owner = RawStorage(storage.store, storage.native, state_schema=schema)
    original = pa.Table.from_pylist([
        dict(url='untouched', outcome='failed', attempts=7,
             extra=dict(large=2**64-1, nested=[None, b'exact'])),
        dict(url=None, outcome=None)], schema=schema)
    first = owner.publish(owner.prepare(owner.snapshot(), operation='rich-seed', states=original))
    assert first.states().equals(original)
    changed = owner.publish(owner.prepare(first, operation='rich-append',
        states=pa.Table.from_pylist([dict(url='new', outcome='pending')], schema=schema)))
    assert changed.states().slice(0, 2).equals(original)
    assert changed.states().schema.equals(schema)
    assert changed.state(None) == original.to_pylist()[1]


def test_iter_states_for_streams_requested_native_rows_in_original_order(tmp_path):
    from native_memory_helpers import memory_raw_storage
    from congress_api.retention.raw_storage import STATE_ORDER
    owner = memory_raw_storage(SelectorStore(), max_state_rows=2)
    selected = owner.publish(owner.prepare(owner.snapshot(), operation='ordered', states=states('b', 'a', 'c')))
    rows = list(selected.iter_states_for(iter(['https://example.gov/c', 'https://example.gov/b',
                                               'https://example.gov/c', 'https://example.gov/missing'])))
    assert [row['url'] for row in rows] == ['https://example.gov/b', 'https://example.gov/c']
    assert [row[STATE_ORDER] for row in rows] == [0, 2]
    assert [{key: row[key] for key in owner.state_schema.names} for row in rows] == states('b', 'c').to_pylist()
    owner.publish(owner.prepare(selected, operation='later', states=states('d')))
    assert list(selected.iter_states_for(['https://example.gov/d'])) == []
