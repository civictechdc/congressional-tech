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
        engine=engine(),work=tmp_path/'discover',lookback_days=0)
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


def test_watermarks_group_by_receipt_key_family_when_full_capture_schema_also_has_family(tmp_path):
    from congress_api.lake.receipt_inventory import discover_receipts
    prior=tmp_path/'captures.parquet'
    pq.write_table(pa.table(dict(receipt_key=['receipts/documents/2026-10-20/a.gz',
        'receipts/congress/meetings/2026-10-21/a.gz'],family=['other-physical-family','other-physical-family'])),prior)
    adapter=Listing()
    rows=discover_receipts(adapter,['documents','congress/meetings'],existing=prior,
        engine=engine(),work=tmp_path/'discover',lookback_days=0)
    assert adapter.listed==['receipts/congress/meetings/2026-10-21/',
        'receipts/documents/2026-10-20/','receipts/documents/2026-10-21/']
    assert [row['key'] for row in rows]==['receipts/documents/2026-10-21/a.gz']


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


def test_incremental_discovery_finds_planted_late_receipt_in_older_day_prefix_within_lookback(tmp_path):
    """ct-mt88: once 2026-11-08 is ingested, a late receipt written into 2026-10-31 (within lookback_days)
    is still listed and selected, while prefixes older than lookback_days and non-date prefixes stay skipped."""
    from congress_api.lake.receipt_inventory import discover_receipts

    class LateListing:
        def __init__(self):
            self.listed=[]
            self.objects={
                'receipts/documents/2026-09-30/':[dict(key='receipts/documents/2026-09-30/ancient.jsonl.gz',path='/unopened/ancient',size=10)],
                'receipts/documents/2026-10-31/':[
                    dict(key='receipts/documents/2026-10-31/already.jsonl.gz',path='/unopened/already',size=11),
                    dict(key='receipts/documents/2026-10-31/late-tail.jsonl.gz',path='/unopened/late',size=12),
                ],
                'receipts/documents/2026-11-08/':[dict(key='receipts/documents/2026-11-08/ingested.jsonl.gz',path='/unopened/ingested',size=13)],
                'receipts/documents/undated/':[dict(key='receipts/documents/undated/legacy.jsonl.gz',path='/unopened/legacy',size=14)],
            }
        def prefixes(self,prefix):
            return sorted(self.objects)
        def files(self,prefix):
            self.listed.append(prefix)
            return list(self.objects[prefix])

    prior=existing(tmp_path,[
        'receipts/documents/2026-10-31/already.jsonl.gz',
        'receipts/documents/2026-11-08/ingested.jsonl.gz',
    ])
    adapter=LateListing()
    rows=discover_receipts(adapter,['documents'],existing=prior,engine=engine(),work=tmp_path/'default-lookback')
    assert adapter.listed==['receipts/documents/2026-10-31/','receipts/documents/2026-11-08/']
    assert [r['key'] for r in rows]==['receipts/documents/2026-10-31/late-tail.jsonl.gz']

    strict=LateListing()
    assert discover_receipts(strict,['documents'],existing=prior,engine=engine(),
        work=tmp_path/'zero-lookback',lookback_days=0)==[]
    assert strict.listed==['receipts/documents/2026-11-08/']

    with pytest.raises(ValueError,match='lookback_days'):
        discover_receipts(LateListing(),['documents'],existing=prior,engine=engine(),
            work=tmp_path/'bad-lookback',lookback_days=-1)
