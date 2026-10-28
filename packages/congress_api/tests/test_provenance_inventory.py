"""Read-only raw inventory caches opaque bytes against current provider facts."""
import hashlib
import io
import json
from pathlib import Path

import pytest

from congress_api.retention.body_store import BodyStore,R2Adapter
from congress_shared.custody import issue_verified_file


PREFIX='provenance/unreadable/'
KEY=PREFIX+'20261028T120000Z-'+('a'*64)+'.jsonl'


class R2:
    def __init__(self,objects=()):
        self.objects=dict(objects);self.list_calls=[];self.get_calls=[];self.head_calls=[];self.put_calls=[]
        self.list_override=None;self.get_override=None
    def get_paginator(self,name):
        assert name=='list_objects_v2';return self
    def paginate(self,**kwargs):
        self.list_calls.append(kwargs)
        rows=self.list_override if self.list_override is not None else [
            dict(Key=k,Size=len(v),ETag='"'+hashlib.md5(v).hexdigest()+'"')
            for k,v in sorted(self.objects.items()) if k.startswith(kwargs['Prefix'])]
        yield dict(Contents=rows)
    def get_object(self,**kwargs):
        self.get_calls.append(kwargs)
        data=self.objects[kwargs['Key']];etag=hashlib.md5(data).hexdigest()
        if 'IfMatch' in kwargs and kwargs['IfMatch']!='"'+etag+'"':raise OSError('precondition failed')
        result=dict(Body=io.BytesIO(data),ContentLength=len(data),ETag='"'+etag+'"')
        if self.get_override:result.update(self.get_override)
        return result
    def head_object(self,**kwargs):
        self.head_calls.append(kwargs);raise AssertionError('No per-object HEAD')
    def put_object(self,**kwargs):
        self.put_calls.append(kwargs)
        source=kwargs['Body'];data=source if isinstance(source,bytes) else source.read()
        assert kwargs['IfNoneMatch']=='*' and kwargs['Key'] not in self.objects
        self.objects[kwargs['Key']]=data
        return dict(ETag='"'+hashlib.md5(data).hexdigest()+'"')


def known_cache(tmp_path,data,*,key=KEY):
    path=tmp_path/'qualified.jsonl';path.write_bytes(data)
    sha=hashlib.sha256(data).hexdigest();etag=hashlib.md5(data).hexdigest()
    public=dict(key=key,path=str(path),etag=etag,sha256=sha,size=len(data))
    proof=issue_verified_file(path,dict(sha256=sha,bytes=len(data),md5=etag))
    return public,proof


def test_single_put_md5_parser_preserves_only_actual_plain_checksums():
    from congress_shared.storage import single_put_md5
    assert single_put_md5('"'+('A'*32)+'"')=='a'*32
    assert single_put_md5('b'*32)=='b'*32
    for value in [None,False,'','a'*32+'-2','W/"'+('a'*32)+'"',' '+('a'*32)]:
        with pytest.raises(ValueError,match='single-PUT MD5'):single_put_md5(value)


def test_b9_source_alias_keeps_legacy_default_and_uses_the_same_transport():
    from congress_api.cli.raw_verify import R2Source as LegacySource
    from congress_api.retention.body_store import R2Source
    client=R2([('bodies/a',b'body')]);source=LegacySource(client,'bucket')
    assert LegacySource is R2Source
    assert list(source.listing())==[dict(key='bodies/a',size=4,etag=hashlib.md5(b'body').hexdigest())]
    assert source.get('bodies/a')['Body'].read()==b'body'
    assert client.list_calls==[dict(Bucket='bucket',Prefix='bodies/')]


def test_remote_snapshot_lists_once_and_fetches_all_missing_opaque_objects(tmp_path):
    from congress_api.retention.provenance_inventory import unreadable_inventory
    data=b'opaque-not-JSON\x00';other=PREFIX+'other.jsonl';client=R2([(KEY,data),(other,b'second')])
    store=BodyStore(R2Adapter(client,'bucket'))
    with unreadable_inventory(store,work=tmp_path/'snapshot') as snapshot:
        rows=snapshot.rows();files=snapshot.files()
        assert [r['key'] for r in rows]==sorted([KEY,other])
        assert files==[dict(key=r['key'],path=r['path']) for r in rows]
        assert Path(rows[0]['path']).is_file()
        for row in rows:
            payload=client.objects[row['key']]
            assert Path(row['path']).read_bytes()==payload and row['sha256']==hashlib.sha256(payload).hexdigest()
            assert row['etag']==hashlib.md5(payload).hexdigest()
    assert all(Path(row['path']).is_file() for row in rows)
    assert len(client.list_calls)==1 and len(client.get_calls)==2 and not client.head_calls
    assert all('IfMatch' in call for call in client.get_calls)


def test_matching_checked_cache_uses_zero_gets_and_zero_heads(tmp_path):
    from congress_api.retention.provenance_inventory import unreadable_inventory
    data=b'cached';public,proof=known_cache(tmp_path,data);client=R2([(KEY,data)])
    store=BodyStore(R2Adapter(client,'bucket'))
    with unreadable_inventory(store,work=tmp_path/'one',qualified=[public],verified={public['path']:proof}) as first:
        assert first.rows()==[public]
    with unreadable_inventory(store,work=tmp_path/'two') as second:
        assert second.rows()==[public]
    assert len(client.list_calls)==2 and not client.get_calls and not client.head_calls


@pytest.mark.parametrize('change',[dict(Size=7),dict(ETag='"'+('0'*32)+'"')])
def test_previously_checked_raw_key_cannot_change_its_size_or_etag(tmp_path,change):
    from congress_api.retention.provenance_inventory import unreadable_inventory
    data=b'cached';public,proof=known_cache(tmp_path,data);client=R2([(KEY,data)])
    row=dict(Key=KEY,Size=len(data),ETag='"'+public['etag']+'"');row.update(change);client.list_override=[row]
    with pytest.raises(ValueError,match='changed'):
        unreadable_inventory(BodyStore(R2Adapter(client,'bucket')),work=tmp_path/'snapshot',
            qualified=[public],verified={public['path']:proof})
    assert not client.get_calls and not client.head_calls


def test_previously_checked_raw_key_missing_from_list_refuses_instead_of_replaying_cache(tmp_path):
    from congress_api.retention.provenance_inventory import unreadable_inventory
    public,proof=known_cache(tmp_path,b'cached');client=R2()
    with pytest.raises(ValueError,match='missing'):
        unreadable_inventory(BodyStore(R2Adapter(client,'bucket')),work=tmp_path/'snapshot',
            qualified=[public],verified={public['path']:proof})
    assert len(client.list_calls)==1 and not client.get_calls


@pytest.mark.parametrize('remove',[False,True])
def test_lost_cache_custody_fetches_a_new_checked_copy_without_overwriting_it(tmp_path,remove):
    from congress_api.retention.provenance_inventory import unreadable_inventory
    data=b'cached';public,proof=known_cache(tmp_path,data);client=R2([(KEY,data)])
    old=Path(public['path'])
    if remove:old.unlink()
    else:old.write_bytes(b'broken')
    with unreadable_inventory(BodyStore(R2Adapter(client,'bucket')),work=tmp_path/'snapshot',
            qualified=[public],verified={public['path']:proof}) as inventory:
        [fresh]=inventory.rows();assert fresh['path']!=public['path']
        assert Path(fresh['path']).read_bytes()==data and fresh['sha256']==public['sha256']
    assert len(client.get_calls)==1 and not client.head_calls
    if not remove:assert old.read_bytes()==b'broken'


@pytest.mark.parametrize('rows',[
    [dict(Key=KEY,Size=1,ETag='multipart-2')],
    [dict(Key='outside/a.jsonl',Size=1,ETag='a'*32)],
    [dict(Key=KEY,Size=-1,ETag='a'*32)],
    [dict(Key=KEY,Size=1,ETag='a'*32),dict(Key=KEY,Size=1,ETag='a'*32)],
])
def test_invalid_authoritative_metadata_refuses_before_get(tmp_path,rows):
    from congress_api.retention.provenance_inventory import unreadable_inventory
    client=R2();client.list_override=rows
    with pytest.raises(ValueError):
        unreadable_inventory(BodyStore(R2Adapter(client,'bucket')),work=tmp_path/'snapshot')
    assert not client.get_calls and not client.head_calls


@pytest.mark.parametrize('change',[dict(ContentLength=99),dict(ETag='"'+('0'*32)+'"')])
def test_get_metadata_must_match_the_selected_listing(tmp_path,change):
    from congress_api.retention.provenance_inventory import unreadable_inventory
    client=R2([(KEY,b'bytes')]);client.get_override=change
    with pytest.raises(ValueError,match='changed'):
        unreadable_inventory(BodyStore(R2Adapter(client,'bucket')),work=tmp_path/'snapshot')
    assert len(client.list_calls)==1 and len(client.get_calls)==1 and not client.head_calls


def test_new_durable_import_is_an_acknowledged_delta_without_get_or_reread(tmp_path):
    from congress_api.retention.provenance import import_unreadable,imported_unreadable_provenance
    from congress_api.retention.provenance_inventory import unreadable_inventory
    client=R2();store=BodyStore(R2Adapter(client,'bucket'))
    source=tmp_path/'decision.jsonl';source.write_text(json.dumps(dict(id='a',body_sha256='a'*64,
        parser='readings',parser_version='v1',reason='timeout',decided_by='readings',
        decided_at='2026-10-28T12:00:00Z',supersedes=None))+'\n')
    with unreadable_inventory(store,work=tmp_path/'snapshot') as snapshot:
        imported=import_unreadable(store,source,decided_at='2026-10-28T12:00:00Z',cache=tmp_path/'ack-cache')
        public,custody=imported_unreadable_provenance(imported,store,source)
        custody.require(public['path'])
        assert snapshot.rows()==[public]
        assert public['etag']==imported['etag']==hashlib.md5(client.objects[public['key']]).hexdigest()
    assert len(client.list_calls)==1 and len(client.put_calls)==1 and not client.get_calls and not client.head_calls
    assert Path(public['path']).is_file()


def test_declared_object_limit_refuses_before_any_download(tmp_path):
    from congress_api.retention.provenance_inventory import unreadable_inventory
    client=R2([(KEY,b'oversized')])
    with pytest.raises(ValueError,match='limit'):
        unreadable_inventory(BodyStore(R2Adapter(client,'bucket')),work=tmp_path/'snapshot',max_bytes=4)
    assert len(client.list_calls)==1 and not client.get_calls and not client.head_calls


@pytest.mark.parametrize('payload',[b'four',b'sixsix'])
def test_actual_response_length_cannot_disagree_with_listing(tmp_path,payload):
    from congress_api.retention.provenance_inventory import unreadable_inventory
    client=R2([(KEY,b'bytes')]);client.get_override=dict(Body=io.BytesIO(payload))
    with pytest.raises(ValueError,match='length|changed'):
        unreadable_inventory(BodyStore(R2Adapter(client,'bucket')),work=tmp_path/'snapshot')
    assert len(client.get_calls)==1 and not client.head_calls


def test_response_bytes_must_match_single_put_checksum(tmp_path):
    from congress_api.retention.provenance_inventory import unreadable_inventory
    client=R2([(KEY,b'bytes')]);client.get_override=dict(Body=io.BytesIO(b'other'))
    with pytest.raises(ValueError,match='MD5|checksum'):
        unreadable_inventory(BodyStore(R2Adapter(client,'bucket')),work=tmp_path/'snapshot')
    assert len(client.get_calls)==1 and not client.head_calls


def test_initial_qualified_snapshot_and_ack_deltas_need_no_second_listing(tmp_path):
    from congress_api.retention.provenance_inventory import UnreadableInventory
    data=b'qualified';public,proof=known_cache(tmp_path,data);client=R2([(KEY,data)])
    store=BodyStore(R2Adapter(client,'bucket'))
    snapshot=UnreadableInventory.from_qualified(store,qualified=[public],verified={public['path']:proof})
    assert snapshot.rows()==[public] and snapshot.files()==[dict(key=KEY,path=public['path'])]
    assert not client.list_calls and not client.get_calls and not client.head_calls


def test_initial_snapshot_checks_its_actual_remote_checksum_without_get(tmp_path):
    from congress_api.retention.provenance_inventory import UnreadableInventory
    public,_=known_cache(tmp_path,b'qualified');public['etag']='0'*32;client=R2()
    with pytest.raises(ValueError,match='MD5|checksum'):
        UnreadableInventory.from_qualified(BodyStore(R2Adapter(client,'bucket')),qualified=[public])
    assert not client.list_calls and not client.get_calls and not client.head_calls


def test_default_standalone_backfill_refreshes_remote_inventory_once(tmp_path):
    from congress_api.lake import readings
    payload=b'opaque-native-parser-input';client=R2([(KEY,payload)])
    class EmptyWorkNative:
        remote=None
        def run_job(self,path):
            job=json.loads(path.read_text())
            selected=next(i for i in job['inputs'] if i['name']=='unreadable')['files']
            assert len(selected)==1 and selected[0]['key']==KEY
            assert Path(selected[0]['path']).read_bytes()==payload
            return dict(queries=[dict(name=q['name'],data=[dict(n=0)]) for q in job['queries']])
    report=readings.run(engine=EmptyWorkNative(),work=tmp_path/'backfill',mode='backfill',execute=True,
        batch_size=2,table=dict(namespace=['archive'],name='readings'),catalog_root=tmp_path/'catalog',
        captures=tmp_path/'unused-captures.parquet',body_inventory=tmp_path/'unused-bodies.parquet',
        local_root=tmp_path/'body-cache',decided_at='2026-10-28T12:00:00Z',
        read_current=lambda **kwargs:None,unreadable_store=BodyStore(R2Adapter(client,'bucket')))
    assert report['status']=='completed' and report['work_items']==0
    assert len(client.list_calls)==1 and len(client.get_calls)==1 and not client.head_calls


def test_daily_r2_decision_store_accepts_complete_qualified_snapshot_without_list(tmp_path):
    from congress_api.lake.daily import produce_daily
    public,_=known_cache(tmp_path,b'qualified');client=R2([(KEY,b'qualified')]);jobs=[]
    names=['captures','readings','filename_readings']
    class MissingNative:
        remote=None
        def run_job(self,path):
            jobs.append(json.loads(path.read_text()))
            return dict(table_operations=[dict(name=n,kind='resolve',exists=False) for n in names])
    spec=dict(work=str(tmp_path/'daily'),decided_at='2026-10-28T12:00:00Z',
        catalog_root=str(tmp_path/'catalog'),tables={n:dict(namespace=['archive'],name=n) for n in names},
        receipt_inventory=[],body_inventory=str(tmp_path/'bodies.parquet'),local_root=str(tmp_path/'body-cache'),
        max_work_items=5,provenance=dict(recoveries=[],reviews=[],unreadable=[public]))
    with pytest.raises(ValueError,match='table does not exist'):
        produce_daily(spec,engine=MissingNative(),raw_store=BodyStore(R2Adapter(client,'bucket')))
    assert len(jobs)==1 and not client.list_calls and not client.get_calls and not client.head_calls


def test_oversized_unreadable_import_refuses_before_put_or_acknowledgment(tmp_path):
    from congress_api.retention.provenance import import_unreadable
    from congress_api.retention.provenance_inventory import MAX_OBJECT_BYTES
    source=tmp_path/'oversized.jsonl'
    # Valid input exceeds the supported next-run inventory bound. Build its
    # padding in chunks so the fixture itself needs no oversized allocation.
    with source.open('wb') as out:
        out.write(b'{"id":"')
        for _ in range(MAX_OBJECT_BYTES//65536):out.write(b'x'*65536)
        out.write(b'","body_sha256":"'+b'a'*64+b'","parser":"readings","parser_version":"v1",'
            b'"reason":"timeout","decided_by":"readings","decided_at":"2026-10-28T12:00:00Z",'
            b'"supersedes":null}\n')
    client=R2();store=BodyStore(R2Adapter(client,'bucket'))
    with pytest.raises(ValueError,match='limit'):
        import_unreadable(store,source,decided_at='2026-10-28T12:00:00Z',cache=tmp_path/'cache')
    assert not client.put_calls and not client.get_calls and not client.head_calls
    assert not store._provenance_acks and source.is_file()


def test_exact_inventory_byte_limit_is_accepted_by_writer_and_next_inventory(tmp_path):
    from congress_api.retention.provenance import import_unreadable,imported_unreadable_provenance
    from congress_api.retention.provenance_inventory import MAX_OBJECT_BYTES,unreadable_inventory
    source=tmp_path/'exact-limit.jsonl'
    prefix=b'{"id":"'
    suffix=(b'","body_sha256":"'+b'a'*64+b'","parser":"readings","parser_version":"v1",'
        b'"reason":"timeout","decided_by":"readings","decided_at":"2026-10-28T12:00:00Z",'
        b'"supersedes":null}\n')
    remaining=MAX_OBJECT_BYTES-len(prefix)-len(suffix)
    with source.open('wb') as out:
        out.write(prefix)
        while remaining:
            chunk=min(65536,remaining);out.write(b'x'*chunk);remaining-=chunk
        out.write(suffix)
    assert source.stat().st_size==MAX_OBJECT_BYTES
    client=R2();store=BodyStore(R2Adapter(client,'bucket'))
    imported=import_unreadable(store,source,decided_at='2026-10-28T12:00:00Z',cache=tmp_path/'cache')
    public,custody=imported_unreadable_provenance(imported,store,source)
    with unreadable_inventory(store,work=tmp_path/'next') as snapshot:
        assert snapshot.rows()==[public] and public['size']==MAX_OBJECT_BYTES
        custody.require(public['path'])
    assert len(client.put_calls)==1 and len(client.list_calls)==1 and not client.get_calls and not client.head_calls


@pytest.mark.parametrize('complete',[False,True])
def test_acknowledged_local_import_custody_matches_current_rows_without_rereading(tmp_path,complete):
    from congress_api.retention.body_store import LocalAdapter
    from congress_api.retention.provenance import import_unreadable,imported_unreadable_provenance
    from congress_api.retention.provenance_inventory import provenance_inventory,unreadable_inventory
    from test_readings_budget_backfill import forbid_body_reads
    store=BodyStore(LocalAdapter(tmp_path/'raw'))
    factory=provenance_inventory if complete else unreadable_inventory
    snapshot=factory(store,work=tmp_path/'snapshot')
    source=tmp_path/'decision.jsonl';source.write_text(json.dumps(dict(id='ack',body_sha256='a'*64,
        parser='readings',parser_version='v1',reason='timeout',decided_by='readings',
        decided_at='2026-10-28T12:00:00Z',supersedes=None))+'\n')
    imported=import_unreadable(store,source,decided_at='2026-10-28T12:00:00Z')
    public,custody=imported_unreadable_provenance(imported,store,source)
    with forbid_body_reads(tmp_path/'raw'):
        assert snapshot.rows()==[public]
        verified=snapshot.verified()
        assert verified=={public['path']:custody} and verified[public['path']] is custody
        assert custody._require_custody(public['path']) is custody
    # Consuming bytes uses main's stronger check after metadata-only planning.
    assert custody.require(public['path']) is custody
