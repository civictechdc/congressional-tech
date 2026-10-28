"""Reuse a controller's checked opaque provenance without another byte read."""
import pytest

from congress_api.lake.daily import _validate,_final_provenance
from congress_api.retention.body_store import BodyStore,R2Adapter
from test_daily_producers import spec,NeverNative
from test_provenance_inventory import R2,known_cache
from test_readings_budget_backfill import forbid_body_reads


@pytest.mark.parametrize('kind',['recoveries','reviews'])
def test_daily_reuses_held_initial_custody_without_rehashing(tmp_path,kind):
    cache=tmp_path/'cache';cache.mkdir()
    row,proof=known_cache(cache,b'opaque\x00provenance',key=f'provenance/{kind}/one.jsonl')
    store=BodyStore(R2Adapter(R2(),'bucket'));store.remember_provenance(row,proof)
    value=spec(tmp_path);value['provenance'][kind]=[dict(row,etag='"'+row['etag']+'"')]
    with forbid_body_reads(cache):
        _,initial,held=_validate(value,NeverNative(),store)
        assert held[row['path']] is proof
        result=_final_provenance(initial,store,[],held,unreadable_snapshot=EmptyUnreadable())
    assert result[kind]==value['provenance'][kind]
    assert not store.adapter.client.list_calls and not store.adapter.client.get_calls


class EmptyUnreadable:
    def rows(self):return []


@pytest.mark.parametrize('change',['digest','path','size','etag','replaced'])
def test_cached_initial_provenance_drift_refuses_without_fallback_reads(tmp_path,change):
    cache=tmp_path/'cache';cache.mkdir()
    row,proof=known_cache(cache,b'original',key='provenance/recoveries/one.jsonl')
    store=BodyStore(R2Adapter(R2(),'bucket'));store.remember_provenance(row,proof)
    value=spec(tmp_path);value['provenance']['recoveries']=[dict(row)]
    changed=value['provenance']['recoveries'][0]
    if change=='digest':changed['sha256']='0'*64
    elif change=='path':changed['path']=str(cache/'alias.jsonl')
    elif change=='size':changed['size']+=1
    elif change=='etag':changed['etag']='0'*32
    else:
        from pathlib import Path
        Path(row['path']).write_bytes(b'changed!')
    with forbid_body_reads(cache),pytest.raises(ValueError):_validate(value,NeverNative(),store)
