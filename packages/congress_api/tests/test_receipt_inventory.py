"""D1 lists metadata and removes ingested keys before opening receipt bytes."""
import os

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from docspec_client.client import NativeDatasets


def engine():
    return NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])


def existing(tmp_path,keys):
    path=tmp_path/'existing.parquet'
    pq.write_table(pa.table({'receipt_key':pa.array(keys,type=pa.string())}),path)
    return path


def test_native_selection_preserves_metadata_without_opening_paths(tmp_path):
    from congress_api.lake.receipt_inventory import select_receipts
    first='receipts/documents/2026-10-20/a.gz'
    later='receipts/documents/2026-10-21/z.gz'
    new='receipts/documents/2026-10-21/b.gz'
    files=[dict(key=later,path='/does-not-exist/z',etag='literal',size=30),
           dict(key=first,path='/does-not-exist/a'),dict(key=new,path='/does-not-exist/b',size=5)]
    selected=select_receipts(files,existing(tmp_path,[first,first]),
        engine=engine(),work=tmp_path/'select')
    assert selected==[files[2],files[0]]
    assert select_receipts(selected,existing(tmp_path,[later,new]),
        engine=engine(),work=tmp_path/'empty')==[]


def test_inventory_refuses_duplicate_keys_and_unsafe_paths_before_native_work(tmp_path):
    from congress_api.lake.receipt_inventory import select_receipts
    row=dict(key='receipts/f/2026-10-20/a.gz',path='/unopened')
    for rows in ([row,row],[dict(row,key='receipts/f/../a.gz')]):
        with pytest.raises(ValueError):
            select_receipts(rows,None,engine=engine(),work=tmp_path/'refused')
    assert not (tmp_path/'refused').exists()


class Listing:
    """Object listing boundary: fake metadata with no content read capability."""
    def __init__(self):
        self.listed=[]
    def prefixes(self,prefix):
        return [prefix+part+'/' for part in ('2026-10-19','2026-10-20','2026-10-21',
                                              'undated','mixed-dates','2026-02-30')]
    def files(self,prefix):
        self.listed.append(prefix)
        return [dict(key=prefix+'a.gz',path='/unopened/'+prefix+'a.gz',size=17)]
    def open(self,key):
        raise AssertionError('Receipt selection must not open contents')


@pytest.mark.parametrize('mode',['backfill','raw-check'])
def test_only_explicit_full_listing_modes_include_non_date_segments(tmp_path,mode):
    from congress_api.lake.receipt_inventory import discover_receipts
    adapter=Listing()
    rows=discover_receipts(adapter,['documents'],existing=existing(tmp_path,[
        'receipts/documents/2026-10-20/already.gz']),engine=engine(),work=tmp_path/'discover',mode=mode)
    assert len(rows)==6
    assert {'receipts/documents/undated/','receipts/documents/mixed-dates/'}<=set(adapter.listed)


def test_incremental_listing_is_inclusive_per_family_and_bootstraps_new_family(tmp_path):
    from congress_api.lake.receipt_inventory import discover_receipts
    adapter=Listing()
    already='receipts/documents/2026-10-20/a.gz'
    rows=discover_receipts(adapter,['documents','congress/meetings'],
        existing=existing(tmp_path,[already,'receipts/documents/undated/z.gz']),
        engine=engine(),work=tmp_path/'discover')
    assert adapter.listed==[
        'receipts/congress/meetings/2026-10-19/',
        'receipts/congress/meetings/2026-10-20/',
        'receipts/congress/meetings/2026-10-21/',
        'receipts/documents/2026-10-20/','receipts/documents/2026-10-21/']
    assert [row['key'] for row in rows]==[
        'receipts/congress/meetings/2026-10-19/a.gz',
        'receipts/congress/meetings/2026-10-20/a.gz',
        'receipts/congress/meetings/2026-10-21/a.gz',
        'receipts/documents/2026-10-21/a.gz']


def test_local_listing_read_adapter_is_read_only_and_stays_inside_root(tmp_path):
    from congress_api.lake.receipt_inventory import LocalReceiptStore
    root=tmp_path/'raw';path=root/'receipts/f/2026-10-20/a.gz'
    path.parent.mkdir(parents=True);path.write_bytes(b'raw bytes')
    adapter=LocalReceiptStore(root)
    assert list(adapter.prefixes('receipts/f/'))==['receipts/f/2026-10-20/']
    [row]=list(adapter.files('receipts/f/2026-10-20/'))
    assert row==dict(key='receipts/f/2026-10-20/a.gz',path=str(path.resolve()),size=9)
    with adapter.open(row['key']) as source:
        assert source.read()==b'raw bytes'
    with pytest.raises(ValueError):
        adapter.open('receipts/../outside.gz')
