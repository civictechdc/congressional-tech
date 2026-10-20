"""Explicit investigated Parquet inputs become one coherent native selection."""
from hashlib import sha256

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.retention.raw_archive import CAPTURE_SCHEMA, STATE_SCHEMA
from congress_api.retention.raw_storage import RAW_KEY, RawStorage
from native_memory_helpers import memory_raw_storage
from test_raw_storage import SelectorStore


def inputs(tmp_path):
    captures = pa.Table.from_pylist([dict(receipt_key=f'receipts/{i // 2}.gz', receipt_line=1,
        body_key=f'bodies/{i % 3}.gz', sha256=str(i % 3), bytes=i) for i in range(9)], schema=CAPTURE_SCHEMA)
    extra = pa.schema([*STATE_SCHEMA, pa.field('opaque', pa.struct([('unsigned', pa.uint64()), ('raw', pa.binary())]))])
    states = pa.Table.from_pylist([dict(url=None if i == 0 else f'https://example.gov/{i}', outcome='saved', attempts=i,
        opaque=dict(unsigned=2**64-1-i, raw=b'\x00\xff')) for i in range(7)], schema=extra)
    paths = {name: tmp_path / f'{name}.parquet' for name in ('captures', 'state')}
    for name, table in [('captures', captures), ('state', states)]:
        pq.write_table(table, paths[name], row_group_size=2)
    hashes = {name: sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}
    return paths, hashes, captures, states


def test_adoption_streams_coalesced_candidates_and_selects_exact_values(tmp_path):
    from congress_api.retention.raw_adoption import adopt_tables
    paths, hashes, captures, states = inputs(tmp_path)
    store = SelectorStore()
    owner = memory_raw_storage(store, state_schema=states.schema, max_state_rows=3, max_capture_rows=3)
    selected = adopt_tables(owner, paths=paths, sha256s=hashes, operation='reviewed-seed', filename_version='catalog-cursor')
    assert selected.captures().equals(captures)
    assert selected.states().equals(states)
    assert selected.body_count == 3
    assert all(selected.has_receipt(key) for key in captures['receipt_key'].to_pylist())
    assert selected.manifest['filename_version'] == 'catalog-cursor'
    assert store.writes.count(RAW_KEY) == 1
    assert max(len(table) for table in owner.native.tables.values()) <= 3
    assert any(len(table) > 1 for table in owner.native.tables.values())
    before = (list(store.writes), list(owner.native.writes))
    again = adopt_tables(owner, paths=paths, sha256s=hashes, operation='reviewed-seed', filename_version='catalog-cursor')
    assert again.identity == selected.identity
    assert (store.writes, owner.native.writes) == before


def test_interrupted_adoption_resumes_on_fresh_owner_without_repeating_native_candidates(tmp_path):
    from congress_api.retention.raw_adoption import adopt_tables
    paths, hashes, captures, states = inputs(tmp_path)
    store = SelectorStore()
    owner = memory_raw_storage(store, state_schema=states.schema, max_state_rows=3, max_capture_rows=3)
    underlying = owner.native
    run = underlying.run_table
    calls = 0
    def interrupted(table, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError('Worker lost')
        return run(table, **kwargs)
    underlying.run_table = interrupted
    with pytest.raises(RuntimeError, match='Worker lost'):
        adopt_tables(owner, paths=paths, sha256s=hashes, operation='reviewed-seed')
    assert store.read(RAW_KEY) is None
    completed = set(underlying.writes)
    underlying.run_table = run
    fresh = RawStorage(store, underlying, state_schema=states.schema, max_state_rows=3, max_capture_rows=3)
    selected = adopt_tables(fresh, paths=paths, sha256s=hashes, operation='reviewed-seed')
    assert selected.captures().equals(captures) and selected.states().equals(states)
    assert all(underlying.writes.count(dataset) == 1 for dataset in completed)
    assert store.writes.count(RAW_KEY) == 1


def test_adoption_refuses_changed_inputs_or_existing_selection_before_writes(tmp_path):
    from congress_api.retention.raw_adoption import adopt_tables
    paths, hashes, _, states = inputs(tmp_path)
    store = SelectorStore()
    owner = memory_raw_storage(store, state_schema=states.schema)
    with pytest.raises(ValueError, match='digest'):
        adopt_tables(owner, paths=paths, sha256s={**hashes, 'state': '0' * 64}, operation='seed')
    assert not store.writes and not owner.native.writes
    adopt_tables(owner, paths=paths, sha256s=hashes, operation='seed')
    before = list(store.writes)
    with pytest.raises(ValueError, match='unselected'):
        adopt_tables(owner, paths=paths, sha256s=hashes, operation='different')
    assert store.writes == before


def test_adoption_losing_final_cas_leaves_only_unselected_candidates(tmp_path):
    from congress_api.retention.raw_adoption import adopt_tables
    paths, hashes, _, states = inputs(tmp_path)
    store = SelectorStore()
    owner = memory_raw_storage(store, state_schema=states.schema, max_state_rows=3)
    def competing(key, payload, *, expected_version):
        store.objects[RAW_KEY] = b'other selection'
        raise RuntimeError('Concurrent raw selection')
    store.put_index_selector = competing
    with pytest.raises(RuntimeError, match='Concurrent'):
        adopt_tables(owner, paths=paths, sha256s=hashes, operation='seed')
    assert store.objects[RAW_KEY] == b'other selection'
    assert owner.native.writes
    assert RAW_KEY not in store.writes


def test_adoption_lost_ack_and_completed_retry_after_later_change(tmp_path):
    from congress_api.retention.raw_adoption import adopt_tables
    paths, hashes, _, states = inputs(tmp_path)
    store = SelectorStore()
    owner = memory_raw_storage(store, state_schema=states.schema)
    store.lose_reply = True
    selected = adopt_tables(owner, paths=paths, sha256s=hashes, operation='seed')
    later = owner.publish(owner.prepare(selected, operation='later',
        captures=pa.Table.from_pylist([{}], schema=CAPTURE_SCHEMA)))
    writes, native_writes = list(store.writes), list(owner.native.writes)
    assert adopt_tables(owner, paths=paths, sha256s=hashes, operation='seed').identity == later.identity
    assert store.writes == writes and owner.native.writes == native_writes
    with pytest.raises(ValueError, match='different inputs'):
        adopt_tables(owner, paths=paths, sha256s=hashes, operation='seed', filename_version='changed')


def test_real_native_adoption_roundtrip_after_interruption(tmp_path):
    import os
    import shutil
    from native_test_helpers import native_test_client
    from congress_api.retention.raw_adoption import adopt_tables
    binary = os.environ.get('DOCSPEC_BINARY') or shutil.which('docspec')
    if not binary:
        pytest.skip('Set DOCSPEC_BINARY to the qualified maintained CLI')
    paths, hashes, captures, states = inputs(tmp_path)
    store = SelectorStore()
    native = native_test_client(binary, tmp_path / 'native')
    owner = RawStorage(store, native, state_schema=states.schema, max_state_rows=3, max_capture_rows=3)
    run = native.run_table
    completed = []
    def interrupted(table, **kwargs):
        if len(completed) == 2:
            raise RuntimeError('Worker lost')
        pin = run(table, **kwargs)
        completed.append(pin)
        return pin
    native.run_table = interrupted
    with pytest.raises(RuntimeError, match='Worker lost'):
        adopt_tables(owner, paths=paths, sha256s=hashes, operation='seed')
    assert store.read(RAW_KEY) is None
    # Fresh local process client, same maintained catalog/workspace. Remote cold
    # host custody was qualified separately and is not rerun by this fixture.
    restarted = native_test_client(binary, tmp_path / 'native')
    resumed = RawStorage(store, restarted, state_schema=states.schema, max_state_rows=3, max_capture_rows=3)
    selected = adopt_tables(resumed, paths=paths, sha256s=hashes, operation='seed')
    assert selected.captures().equals(captures)
    assert selected.states().equals(states)
    pins = list(resumed.capture_pages.entries(selected.manifest['captures']['head']))
    assert [entry['release'] for entry in pins[:2]] == completed


def test_duplicate_state_urls_refuse_before_native_preparation(tmp_path):
    from congress_api.retention.raw_adoption import adopt_tables
    paths, hashes, _, states = inputs(tmp_path)
    pq.write_table(pa.concat_tables([states, states.slice(0, 1)]), paths['state'])
    hashes['state'] = sha256(paths['state'].read_bytes()).hexdigest()
    store = SelectorStore()
    owner = memory_raw_storage(store, state_schema=states.schema)
    with pytest.raises(ValueError, match='Duplicate'):
        adopt_tables(owner, paths=paths, sha256s=hashes, operation='seed')
    assert not store.writes and not owner.native.writes


def test_changed_input_during_adoption_never_selects_partial_archive(tmp_path):
    from congress_api.retention.raw_adoption import adopt_tables
    paths, hashes, _, states = inputs(tmp_path)
    store = SelectorStore()
    owner = memory_raw_storage(store, state_schema=states.schema)
    run = owner.native.run_table
    def changed(table, **kwargs):
        pin = run(table, **kwargs)
        # A harmless trailing byte still violates the exact reviewed file pin.
        with paths['state'].open('ab') as stream:
            stream.write(b' ')
        return pin
    owner.native.run_table = changed
    with pytest.raises(ValueError, match='digest'):
        adopt_tables(owner, paths=paths, sha256s=hashes, operation='seed')
    assert store.read(RAW_KEY) is None
