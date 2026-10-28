"""The daily producer refreshes all three lake inputs before publication."""
import hashlib
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.retention.body_store import BodyStore,LocalAdapter


STAMP='2026-10-28T12:00:00Z'
TABLES={name:dict(namespace=['archive'],name=name)
        for name in ['captures','readings','filename_readings']}


def spec(root):
    return dict(work=str(root/'work'),decided_at=STAMP,catalog_root=str(root/'catalog'),
        tables=TABLES,receipt_inventory=[],body_inventory=str(root/'body-inventory.parquet'),
        local_root=str(root/'raw'),max_work_items=10,
        provenance={kind:[] for kind in ['recoveries','reviews','unreadable']})


class NeverNative:
    remote=None
    def run_job(self,path):raise AssertionError('Native job before validation')


@pytest.mark.parametrize('budget',[None,True,False,0,-1,1.5,'10'])
def test_invalid_daily_budget_refuses_before_any_effect(tmp_path,budget):
    from congress_api.lake.daily import produce_daily
    value=spec(tmp_path);value['max_work_items']=budget
    with pytest.raises(ValueError,match='max_work_items'):
        produce_daily(value,engine=NeverNative(),raw_store=BodyStore(LocalAdapter(tmp_path/'durable')))
    assert not (tmp_path/'work').exists() and not (tmp_path/'durable').exists()


def test_invalid_daily_provenance_refuses_before_catalog_or_store(tmp_path):
    from congress_api.lake.daily import produce_daily
    value=spec(tmp_path);value['provenance']['recoveries']=[dict(key='provenance/recoveries/a.jsonl',
        path=str(tmp_path/'absent'),etag=None,sha256='not-a-digest',size=2)]
    with pytest.raises(ValueError,match='provenance'):
        produce_daily(value,engine=NeverNative(),raw_store=BodyStore(LocalAdapter(tmp_path/'durable')))
    assert not (tmp_path/'work').exists() and not (tmp_path/'durable').exists()


def test_daily_requires_three_distinct_explicit_tables_before_effects(tmp_path):
    from congress_api.lake.daily import produce_daily
    value=spec(tmp_path);value['tables']=dict(TABLES,filename_readings=TABLES['readings'])
    with pytest.raises(ValueError,match='tables'):
        produce_daily(value,engine=NeverNative(),raw_store=BodyStore(LocalAdapter(tmp_path/'durable')))
    assert not (tmp_path/'work').exists()


def test_daily_preflights_all_heads_without_creating_a_missing_table(tmp_path):
    from congress_api.lake.daily import produce_daily
    jobs=[]
    class MissingNative:
        remote=None
        def run_job(self,path):
            job=json.loads(path.read_text());jobs.append(job)
            return dict(table_operations=[dict(name=n,kind='resolve',exists=False) for n in TABLES])
    with pytest.raises(ValueError,match='table does not exist'):
        produce_daily(spec(tmp_path),engine=MissingNative(),
            raw_store=BodyStore(LocalAdapter(tmp_path/'durable')))
    assert len(jobs)==1
    assert jobs[0]['table_operations']==[dict(kind='resolve',name=n,table=t) for n,t in TABLES.items()]
    assert not (tmp_path/'catalog').exists() and not (tmp_path/'durable').exists()
    assert not (tmp_path/'work/captures').exists()


def test_local_unreadable_inventory_reuses_exact_imported_records(tmp_path):
    from congress_api.retention.provenance import import_unreadable,local_unreadable_inventory
    path=tmp_path/'decisions.jsonl'
    path.write_text(json.dumps(dict(id='a',body_sha256='a'*64,parser='readings',parser_version='v1',
        reason='timeout',decided_by='readings',decided_at=STAMP,supersedes=None))+'\n')
    store=BodyStore(LocalAdapter(tmp_path/'raw'))
    imported=import_unreadable(store,path,decided_at=STAMP)
    assert local_unreadable_inventory(store)==[dict(key=imported['key'],
        path=str(tmp_path/'raw'/imported['key']))]
    assert hashlib.sha256((tmp_path/'raw'/imported['key']).read_bytes()).hexdigest()==imported['sha256']


def native_fixture(tmp_path,count=1):
    from capture_qualification_helpers import write_qualified_bytes
    from congress_api.models.raw_fetch import BodyFile,FetchAttempt,FetchResult
    from congress_api.retention.receipt_writer import ReceiptWriter
    from congress_api.lake import filenames,readings,tables
    from docspec_client.client import NativeDatasets
    engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    root=tmp_path/'raw';qualifications={}
    class QualifiedAdapter(LocalAdapter):
        def create(self,key,source,**kwargs):
            if key.startswith('receipts/'):
                qualifications[key]=write_qualified_bytes(root/key,source.read());return True
            return super().create(key,source,**kwargs)
    store=BodyStore(QualifiedAdapter(root))
    writer=ReceiptWriter(store,identity=dict(job='capture',commit='a'*40,lockfile_digest='b'*64),
        run_id='daily',write_date='2026-10-28',archive_limits=None)
    files=[];inventory=[]
    for i in range(count):
        data=json.dumps(dict(title='Daily input '+str(i),url='https://docs.house.gov/report'+str(i)+'.json')).encode()
        entity=tmp_path/('body'+str(i));entity.write_bytes(data);digest=hashlib.sha256(data).hexdigest()
        body=BodyFile(entity,digest,len(data),'application/json',None,None,None)
        url='https://docs.house.gov/report'+str(i)+'.json'
        attempt=FetchAttempt(url,url,STAMP,'direct',200,None,{},(),True,body)
        key,line=writer.write(FetchResult(attempt),family='documents')
        files.append(dict(key=key,path=str(root/key),qualification=qualifications[key]))
        capture=line['captures'][0];physical='bodies/sha256/'+digest[:2]+'/'+digest+capture['stored_suffix']
        inventory.append(dict(body_sha=bytes.fromhex(digest),physical_key=physical,relative_path=physical,
            stored_bytes=capture['stored_bytes'],stored_gzip=capture['stored_suffix']=='.gz'))
    value=spec(tmp_path);value['receipt_inventory']=files
    pq.write_table(pa.Table.from_pylist(inventory,schema=pa.schema([('body_sha',pa.binary(32)),
        ('physical_key',pa.string()),('relative_path',pa.string()),('stored_bytes',pa.int64()),
        ('stored_gzip',pa.bool_())])),value['body_inventory'])
    schema=json.loads((Path(__file__).resolve().parents[3]/'model/lake/captures.schema.json').read_text())
    tables.create_table(engine=engine,work=tmp_path/'create-captures',catalog_root=value['catalog_root'],
        table=TABLES['captures'],schema=schema,location=tmp_path/'lake-captures',create_namespace=True)
    readings.create_table(engine=engine,work=tmp_path/'create-readings',catalog_root=value['catalog_root'],
        table=TABLES['readings'],location=tmp_path/'lake-readings')
    filenames.create_table(engine=engine,work=tmp_path/'create-filenames',catalog_root=value['catalog_root'],
        table=TABLES['filename_readings'],location=tmp_path/'lake-filenames')
    return value,engine,store


def test_native_daily_producer_returns_fresh_three_pins_and_reuses_current_work(tmp_path):
    from congress_api.lake.daily import produce_daily
    value,engine,store=native_fixture(tmp_path)
    first=produce_daily(value,engine=engine,raw_store=store)
    assert first['status']=='completed' and set(first['pins'])==set(TABLES)
    assert first['receipt_keys']==[value['receipt_inventory'][0]['key']]
    assert all(p['snapshot'] is not None for p in first['pins'].values())
    assert first['producerreports']['readings']['work_items']==1
    assert first['producerreports']['readings']['read_bytes']>0
    assert first['currentversions']['filename_readings']
    value=replace_spec(value,work=str(tmp_path/'second'))
    second=produce_daily(value,engine=engine,raw_store=store)
    assert second['status']=='completed' and second['receipt_keys']==[]
    assert second['producerreports']['readings']['work_items']==0
    assert second['producerreports']['readings']['read_bytes']==0
    final=json.loads((tmp_path/'second/final-heads/job.json').read_text())
    assert final['table_operations']==[dict(kind='resolve',name=n,table=t) for n,t in TABLES.items()]


def replace_spec(value,**changes):
    return dict(value,**changes)


def test_native_daily_budget_reports_backfill_before_body_or_filename_work(tmp_path):
    from congress_api.lake.daily import produce_daily
    value,engine,store=native_fixture(tmp_path,2);value['max_work_items']=1
    result=produce_daily(value,engine=engine,raw_store=store)
    assert result['status']=='backfill_required' and result['pins'] is None
    assert result['producerreports']['readings']['work_items']==2
    assert not (tmp_path/'work/readings/batch-000000').exists()
    assert not (tmp_path/'work/filenames').exists() and not (tmp_path/'work/final-heads').exists()


def test_native_daily_pending_body_stops_before_filename_or_publisher_pins(tmp_path):
    from congress_api.lake.daily import produce_daily
    value,engine,store=native_fixture(tmp_path)
    item=pq.read_table(value['body_inventory']).to_pylist()[0]
    (tmp_path/'raw'/item['relative_path']).unlink()
    result=produce_daily(value,engine=engine,raw_store=store)
    assert result['status']=='pending' and result['pins'] is None
    assert result['producerreports']['readings']['pending_reads']==1
    assert not (tmp_path/'work/filenames').exists() and not (tmp_path/'work/final-heads').exists()
