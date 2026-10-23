"""Complete raw adoption streams qualified reading routes through the same CAS."""
from hashlib import sha256
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.retention.raw_archive import CAPTURE_SCHEMA, STATE_SCHEMA
from congress_api.retention.raw_storage import RAW_KEY, RawStorage
from congress_api.retention.raw_readings import LEAF_ENTRIES
from congress_api.retention.raw_adoption import adopt_tables
from test_raw_readings import part
from test_raw_adoption import inputs
from testing_fakes import SelectorStore
from native_memory_helpers import memory_raw_storage


def inventory(tmp_path, paths, hashes, references):
    path = tmp_path / 'readings.jsonl'
    path.write_text(''.join(json.dumps({key: ref[key] for key in ('key','bytes','sha256','rows')})+'\n' for ref in references))
    return dict(paths, readings=path), dict(hashes, readings=sha256(path.read_bytes()).hexdigest())


def test_complete_adoption_streams_reading_routes_without_generic_all_body_prepare(tmp_path):
    store = SelectorStore()
    paths, hashes, captures, states = inputs(tmp_path)
    references = [part(store, f'part-{i:04d}', f'body:{i:04d}', 'failed') for i in range(LEAF_ENTRIES+3)]
    paths, hashes = inventory(tmp_path, paths, hashes, references)
    owner = memory_raw_storage(store, state_schema=states.schema, max_state_rows=3, max_capture_rows=3)
    owner.readings.prepare = lambda *a, **k: pytest.fail('Unbounded incoming body dictionary')
    selected = adopt_tables(owner, paths=paths, sha256s=hashes, operation='complete-seed')
    assert selected.captures().equals(captures) and selected.states().equals(states)
    assert len(list(selected.body_readings(['body:0000', f'body:{LEAF_ENTRIES+2:04d}']))) == 2
    assert max(len(value['entries']) for _, value in owner.readings.routes.leaf_items(selected.manifest['readings']['root'])) <= LEAF_ENTRIES
    assert store.writes.count(RAW_KEY) == 1
    selected_changes, = selected.changes_since(owner.empty_identity)
    assert len(list(selected.changed_reading_parts(selected_changes))) == len(references)
    before = list(store.writes), list(owner.native.writes)
    assert adopt_tables(owner, paths=paths, sha256s=hashes, operation='complete-seed').identity == selected.identity
    assert (store.writes,owner.native.writes) == before


def test_explicit_empty_reading_inventory_qualifies_empty_complete_archive(tmp_path):
    paths = {name: tmp_path/f'{name}.parquet' for name in ('captures','state')}
    pq.write_table(pa.Table.from_pylist([],schema=CAPTURE_SCHEMA),paths['captures'])
    pq.write_table(pa.Table.from_pylist([],schema=STATE_SCHEMA),paths['state'])
    hashes = {name:sha256(path.read_bytes()).hexdigest() for name,path in paths.items()}
    paths,hashes=inventory(tmp_path,paths,hashes,[])
    store=SelectorStore();owner=memory_raw_storage(store)
    selected=adopt_tables(owner,paths=paths,sha256s=hashes,operation='explicit-empty')
    assert list(selected.body_readings([])) == []
    assert not owner.native.writes
    assert store.writes.count(RAW_KEY)==1


def test_invalid_or_changed_reading_inventory_refuses_before_native_writes(tmp_path):
    store=SelectorStore();paths,hashes,_,states=inputs(tmp_path)
    reference=part(store,'bad','body:a')
    paths,hashes=inventory(tmp_path,paths,hashes,[reference])
    owner=memory_raw_storage(store,state_schema=states.schema)
    paths['readings'].write_text('{}\n')
    with pytest.raises(ValueError,match='digest'):
        adopt_tables(owner,paths=paths,sha256s=hashes,operation='bad-input')
    hashes['readings']=sha256(paths['readings'].read_bytes()).hexdigest()
    with pytest.raises(ValueError,match='reading.*reference'):
        adopt_tables(owner,paths=paths,sha256s=hashes,operation='bad-reference')
    assert not owner.native.writes and RAW_KEY not in store.writes


def test_reading_route_interruption_reuses_native_candidates_on_fresh_owner(tmp_path):
    store=SelectorStore();paths,hashes,captures,states=inputs(tmp_path)
    reference=part(store,'one','body:a')
    paths,hashes=inventory(tmp_path,paths,hashes,[reference])
    owner=memory_raw_storage(store,state_schema=states.schema,max_state_rows=3,max_capture_rows=3)
    write=store.put
    def interrupt(key,data,**kwargs):
        if key.startswith('indexes/native-manifests/raw-readings-v1/'):
            raise RuntimeError('Lost before reading route completion')
        return write(key,data,**kwargs)
    store.put=interrupt
    with pytest.raises(RuntimeError,match='reading route'):
        adopt_tables(owner,paths=paths,sha256s=hashes,operation='seed')
    assert RAW_KEY not in store.objects
    completed=list(owner.native.writes)
    store.put=write
    fresh=RawStorage(store,owner.native,state_schema=states.schema,max_state_rows=3,max_capture_rows=3)
    selected=adopt_tables(fresh,paths=paths,sha256s=hashes,operation='seed')
    assert selected.captures().equals(captures) and selected.states().equals(states)
    assert list(selected.body_readings(['body:a']))[0]['status']=='completed'
    assert owner.native.writes==completed
