"""Exact physical listing facts supplement capture custody through native SQL."""
import hashlib
import gzip
import io

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.lake import readings
from congress_api.retention.r2 import R2Store
from test_readings_ranged_plan import inputs
from test_readings_ranged import Client


def listing(tmp_path,key,stored,*,etag=None,size=None):
    path=tmp_path/'listing.parquet'
    rows=[dict(key=key,size=len(stored) if size is None else size,
               etag='"'+hashlib.md5(stored).hexdigest()+'"' if etag is None else etag),
          dict(key=key+'.gz',size=999,etag='"other-suffix"')]
    pq.write_table(pa.Table.from_pylist(rows,schema=pa.schema([
        ('key',pa.string()),('size',pa.int64()),('etag',pa.string())])),path)
    return path


@pytest.mark.parametrize('missing',[None,'md5'])
def test_exact_listing_supplies_conditional_version_without_borrowing_suffix(tmp_path,missing):
    args,stored,key=inputs(tmp_path,missing=missing)
    etag='"'+hashlib.md5(stored).hexdigest()+'"' if missing is None else '"opaque-7-12"'
    result=readings.plan(**args,work=tmp_path/'plan',parser=None,raw_ranges=True,
        body_listing=listing(tmp_path,key,stored,etag=etag))
    [row]=pq.read_table(result['work_list']).to_pylist()
    assert row['physical_key']==key and row['conditional_etag']==etag
    assert row['stored_md5']==(None if missing else hashlib.md5(stored).hexdigest())
    assert result['raw_custody']['capture_md5']==(0 if missing else 1)
    assert result['raw_custody']['listing_etag']==(1 if missing else 0)
    assert result['raw_custody']['missing_pins']==0


@pytest.mark.parametrize('change',[{'etag':'"different"'},{'size':999}])
def test_capture_listing_conflict_is_counted_and_refused_before_get(tmp_path,change):
    args,stored,key=inputs(tmp_path);client=Client(stored)
    with pytest.raises(readings.RawCustodyRequired) as error:
        readings.stage_once(**args,work=tmp_path/'stage',
            body_listing=listing(tmp_path,key,stored,**change),
            body_store=R2Store(client,'bucket',cache_dir=tmp_path/'stage/raw-pages'))
    assert error.value.report['conflicts']==1
    assert not client.reads


def test_another_suffix_cannot_supply_missing_listing_version(tmp_path):
    args,stored,key=inputs(tmp_path,missing='md5');path=listing(tmp_path,key,stored)
    table=pq.read_table(path);pq.write_table(table.slice(1),path)
    result=readings.plan(**args,work=tmp_path/'plan',parser=None,raw_ranges=True,body_listing=path)
    assert result['raw_custody']['missing_pins']==1
    [row]=pq.read_table(result['work_list']).to_pylist()
    assert row['conditional_etag'] is None


def test_listed_opaque_page_is_decoded_proved_and_parsed_by_actual_worker(tmp_path):
    args,stored,key=inputs(tmp_path,missing='md5');etag='"multipart-12-7"'
    class PageClient(Client):
        def get_object(self,**kwargs):
            self.reads.append(kwargs)
            assert kwargs==dict(Bucket='bucket',Key=key,IfMatch=etag)
            return dict(Body=io.BytesIO(stored),ETag=etag,ContentLength=len(stored),ContentEncoding='gzip')
    client=PageClient(stored)
    result=readings.stage_once(**args,work=tmp_path/'stage',
        body_listing=listing(tmp_path,key,stored,etag=etag),
        body_store=R2Store(client,'bucket',cache_dir=tmp_path/'stage/raw-pages'))
    assert result['pending_reads']==0 and result['unreadable']==0
    rows=pq.read_table(result['readings']).to_pylist()
    assert [(r['parser'],r['status']) for r in rows]==[('html','completed'),('sniff','completed')]
    assert len(client.reads)==1


@pytest.mark.parametrize('bare',['valid','missing','conflict','neither'])
def test_direct_listing_chooses_recorded_copy_then_falls_back_by_owner_rule(tmp_path,bare):
    args,stored,key=inputs(tmp_path)
    alternative=gzip.compress(gzip.decompress(stored),compresslevel=1,mtime=1)
    captures=pq.read_table(args['captures']);rows=captures.to_pylist()
    rows[1].update(stored_bytes=len(alternative),stored_md5=hashlib.md5(alternative).digest())
    pq.write_table(pa.Table.from_pylist(rows,schema=captures.schema),args['captures'])
    etag='"'+hashlib.md5(stored).hexdigest()+'"'
    objects=[dict(key=key,size=len(stored),etag=etag),dict(key=key+'.gz',size=len(alternative),
        etag='"'+hashlib.md5(alternative).hexdigest()+'"')]
    if bare=='missing':objects=objects[1:]
    if bare=='conflict':objects[0]['etag']='"wrong"'
    if bare=='neither':objects=[]
    path=tmp_path/'full-list.parquet'
    pq.write_table(pa.Table.from_pylist(objects,schema=pa.schema([
        ('key',pa.string()),('size',pa.int64()),('etag',pa.string())])),path)
    args['body_inventory']=None
    result=readings.plan(**args,work=tmp_path/'plan',parser=None,raw_ranges=True,body_listing=path)
    [row]=pq.read_table(result['work_list']).to_pylist();report=result['raw_custody']
    assert row['physical_key']==key+('.gz' if bare in {'missing','conflict'} else '')
    selected=alternative if bare in {'missing','conflict'} else stored
    assert row['stored_md5']==hashlib.md5(selected).hexdigest() and row['stored_bytes']==len(selected)
    assert report['missing_pins']==(1 if bare=='neither' else 0)
    assert report['fallback_missing']==(1 if bare=='missing' else 2 if bare=='neither' else 0)
    assert report['fallback_conflict']==(1 if bare=='conflict' else 0)
    assert row['stored_gzip'] is False # An object suffix is not a storage-encoding observation.


def test_direct_listing_never_uses_an_unrecorded_alternative(tmp_path):
    args,stored,key=inputs(tmp_path)
    captures=pq.read_table(args['captures']);pq.write_table(captures.slice(0,1),args['captures'])
    path=listing(tmp_path,key,stored);objects=pq.read_table(path)
    pq.write_table(objects.slice(1),path);args['body_inventory']=None
    result=readings.plan(**args,work=tmp_path/'plan',parser=None,raw_ranges=True,body_listing=path)
    assert result['raw_custody']['missing_pins']==1 and result['raw_custody']['fallback_missing']==1
    [row]=pq.read_table(result['work_list']).to_pylist();assert row['physical_key']==key


def test_unknown_capture_suffix_refuses_before_reads(tmp_path):
    args,stored,key=inputs(tmp_path);captures=pq.read_table(args['captures']);rows=captures.to_pylist()
    rows[0]['stored_suffix']='.zip'
    pq.write_table(pa.Table.from_pylist(rows,schema=captures.schema),args['captures'])
    args['body_inventory']=None
    with pytest.raises(ValueError,match='Conflicting or incomplete'):
        readings.plan(**args,work=tmp_path/'plan',parser=None,raw_ranges=True,
            body_listing=listing(tmp_path,key,stored))
