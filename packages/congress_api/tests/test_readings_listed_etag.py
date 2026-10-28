"""Exact physical listing facts supplement capture custody through native SQL."""
import hashlib
import io

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.lake import readings
from congress_api.retention.r2 import R2Store
from test_readings_ranged_plan import inputs


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
    args,stored,key=inputs(tmp_path)
    with pytest.raises(readings.RawCustodyRequired) as error:
        readings.stage_once(**args,work=tmp_path/'stage',
            body_listing=listing(tmp_path,key,stored,**change),
            body_store=R2Store(object(),'bucket',cache_dir=tmp_path/'stage/raw-pages'))
    assert error.value.report['conflicts']==1


def test_another_suffix_cannot_supply_missing_listing_version(tmp_path):
    args,stored,key=inputs(tmp_path,missing='md5');path=listing(tmp_path,key,stored)
    table=pq.read_table(path);pq.write_table(table.slice(1),path)
    result=readings.plan(**args,work=tmp_path/'plan',parser=None,raw_ranges=True,body_listing=path)
    assert result['raw_custody']['missing_pins']==1
    [row]=pq.read_table(result['work_list']).to_pylist()
    assert row['conditional_etag'] is None
