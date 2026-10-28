"""Complete provider metadata and selected opaque record caches share one LIST."""
import hashlib
import io
from pathlib import Path

import pytest

from congress_api.retention.body_store import BodyStore,R2Adapter
from test_provenance_inventory import R2


FAMILIES=('recoveries','reviews','unreadable','verification','url_variants')


def source():
    records={f'provenance/{family}/one.jsonl':b'not-JSON\x00'+family.encode() for family in FAMILIES}
    backup='provenance/backups/large-retained.bin'
    client=R2([*records.items(),(backup,b'never fetch this backup')])
    client.list_override=[dict(Key=key,Size=len(data),ETag='"'+hashlib.md5(data).hexdigest()+'"')
        for key,data in sorted(records.items())]+[dict(Key=backup,Size=50<<30,ETag='"opaque-backup-v1"')]
    return client,records,backup


def test_complete_metadata_preserves_opaque_backups_without_fetching_them(tmp_path):
    from congress_api.retention.provenance_inventory import provenance_inventory
    client,records,backup=source();store=BodyStore(R2Adapter(client,'bucket'))
    with provenance_inventory(store,work=tmp_path/'snapshot') as snapshot:
        metadata=snapshot.metadata()
        assert metadata==sorted([dict(key=r['Key'],etag=r['ETag'],size=r['Size'])
            for r in client.list_override],key=lambda r:r['key'])
        assert not client.get_calls
        rows=snapshot.qualify(sorted(records));verified=snapshot.verified()
        assert len(rows)==5 and set(verified)=={r['path'] for r in rows}
        for row in rows:
            assert Path(row['path']).read_bytes()==records[row['key']]
            assert row['sha256']==hashlib.sha256(records[row['key']]).hexdigest()
            assert row['etag']==hashlib.md5(records[row['key']]).hexdigest()
            verified[row['path']].require(row['path'])
    assert all(Path(r['path']).is_file() for r in rows)
    assert client.list_calls==[dict(Bucket='bucket',Prefix='provenance/')]
    assert len(client.get_calls)==5 and backup not in {r['Key'] for r in client.get_calls}
    assert not client.head_calls


def test_complete_inventory_reuses_checked_files_and_has_an_unreadable_view(tmp_path):
    from congress_api.retention.provenance_inventory import provenance_inventory,UnreadableInventory
    client,records,_=source();store=BodyStore(R2Adapter(client,'bucket'))
    first=provenance_inventory(store,work=tmp_path/'first');rows=first.qualify(sorted(records))
    second=provenance_inventory(store,work=tmp_path/'second')
    assert second.qualify(sorted(records))==rows
    selected=[r for r in rows if r['key'].startswith('provenance/unreadable/')]
    view=UnreadableInventory.from_qualified(store,qualified=selected,verified=second.verified())
    assert view.rows()==selected
    assert len(client.list_calls)==2 and len(client.get_calls)==5 and not client.head_calls


@pytest.mark.parametrize('keys',[
    ['provenance/missing/one.jsonl'],
    ['provenance/reviews/one.jsonl','provenance/reviews/one.jsonl'],
    ['provenance/backups/large-retained.bin'],
])
def test_invalid_selected_records_refuse_before_any_get(tmp_path,keys):
    from congress_api.retention.provenance_inventory import provenance_inventory
    client,_,_=source();snapshot=provenance_inventory(BodyStore(R2Adapter(client,'bucket')),work=tmp_path/'snapshot')
    with pytest.raises(ValueError):snapshot.qualify(keys)
    assert len(client.list_calls)==1 and not client.get_calls and not client.head_calls


def test_missing_previously_checked_record_refuses_in_complete_metadata(tmp_path):
    from congress_api.retention.provenance_inventory import provenance_inventory
    client,records,_=source();store=BodyStore(R2Adapter(client,'bucket'))
    provenance_inventory(store,work=tmp_path/'first').qualify(sorted(records))
    client.list_override=[r for r in client.list_override if r['Key']!='provenance/reviews/one.jsonl']
    with pytest.raises(ValueError,match='missing'):
        provenance_inventory(store,work=tmp_path/'second')
    assert len(client.list_calls)==2 and len(client.get_calls)==5 and not client.head_calls


@pytest.mark.parametrize('limits',[
    dict(max_file_bytes=0,max_total_bytes=100),
    dict(max_file_bytes=100,max_total_bytes=False),
])
def test_invalid_configured_bounds_refuse_before_list(tmp_path,limits):
    from congress_api.retention.provenance_inventory import provenance_inventory
    client,_,_=source()
    with pytest.raises(ValueError,match='limit|bound'):
        provenance_inventory(BodyStore(R2Adapter(client,'bucket')),work=tmp_path/'snapshot',**limits)
    assert not client.list_calls and not client.get_calls


@pytest.mark.parametrize('limits',[
    dict(max_file_bytes=4,max_total_bytes=1000),
    dict(max_file_bytes=100,max_total_bytes=4),
])
def test_selected_file_and_total_bounds_refuse_before_get(tmp_path,limits):
    from congress_api.retention.provenance_inventory import provenance_inventory
    client,records,_=source()
    snapshot=provenance_inventory(BodyStore(R2Adapter(client,'bucket')),work=tmp_path/'snapshot',**limits)
    with pytest.raises(ValueError,match='limit|bound'):snapshot.qualify(sorted(records))
    assert len(client.list_calls)==1 and not client.get_calls and not client.head_calls


def test_conditional_get_keeps_the_exact_listed_etag_representation(tmp_path):
    from congress_api.retention.provenance_inventory import provenance_inventory
    key='provenance/reviews/one.jsonl';payload=b'opaque';etag='"'+hashlib.md5(payload).hexdigest().upper()+'"'
    class ExactConditionalR2(R2):
        def get_object(self,**kwargs):
            self.get_calls.append(kwargs)
            assert kwargs==dict(Bucket='bucket',Key=key,IfMatch=etag)
            return dict(Body=io.BytesIO(payload),ContentLength=len(payload),ETag=etag)
    client=ExactConditionalR2([(key,payload)])
    client.list_override=[dict(Key=key,Size=len(payload),ETag=etag)]
    inventory=provenance_inventory(BodyStore(R2Adapter(client,'bucket')),work=tmp_path/'snapshot')
    [qualified]=inventory.qualify([key])
    assert inventory.metadata()==[dict(key=key,size=len(payload),etag=etag)]
    assert qualified['etag']==hashlib.md5(payload).hexdigest()
