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


def test_complete_receipt_identity_reads_the_final_native_pin_only(tmp_path):
    from congress_api.lake.daily import _complete_receipt_keys
    pin=dict(metadata_location='file:///fixed.metadata.json',table_uuid='a'*32,snapshot=7,schema_id=0)
    class Native:
        def run_job(self,path):
            job=json.loads(path.read_text())
            assert job['inputs']==[dict(name='current_captures',kind='native_table',**pin)]
            assert job['outputs']==[]
            assert job['queries']==[dict(name='receipt_keys',sql='SELECT DISTINCT receipt_key FROM current_captures ORDER BY receipt_key')]
            return dict(queries=[dict(name='receipt_keys',data=[dict(receipt_key='receipts/a/one.jsonl.gz'),
                dict(receipt_key='receipts/a/two.jsonl.gz')])])
    assert _complete_receipt_keys(pin,engine=Native(),work=tmp_path/'identity')==[
        'receipts/a/one.jsonl.gz','receipts/a/two.jsonl.gz']


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


def acknowledged_import(tmp_path,adapter_type=LocalAdapter):
    from congress_api.retention.provenance import import_unreadable
    source=tmp_path/'decisions.jsonl'
    source.write_text(json.dumps(dict(id='a',body_sha256='a'*64,parser='readings',parser_version='v1',
        reason='timeout',decided_by='readings',decided_at=STAMP,supersedes=None))+'\n')
    store=BodyStore(adapter_type(tmp_path/'raw'))
    imported=import_unreadable(store,source,decided_at=STAMP)
    row=dict(key=imported['key'],path=str(tmp_path/'raw'/imported['key']),
             sha256=imported['sha256'],size=imported['size'],etag=None)
    return store,imported,row


def test_acknowledged_import_missing_from_inventory_cannot_disappear_from_inputs(tmp_path):
    from congress_api.lake.daily import _final_provenance
    store,_,row=acknowledged_import(tmp_path)
    Path(row['path']).unlink()
    with pytest.raises(ValueError,match='[Aa]cknowledged|custody|changed'):
        _final_provenance({k:[] for k in ['recoveries','reviews','unreadable']},store,[row],{})


def test_acknowledged_import_same_size_replacement_cannot_reuse_its_old_digest(tmp_path):
    from congress_api.lake.daily import _final_provenance
    store,_,row=acknowledged_import(tmp_path)
    Path(row['path']).write_bytes(b'x'*row['size'])
    with pytest.raises(ValueError,match='[Aa]cknowledged|custody|changed'):
        _final_provenance({k:[] for k in ['recoveries','reviews','unreadable']},store,[row],{})


def test_import_custody_is_verified_immediately_after_the_durable_acknowledgment(tmp_path):
    from congress_api.retention.provenance import imported_unreadable_provenance
    class ReplacedAfterCreate(LocalAdapter):
        def create(self,key,source,**kwargs):
            created=super().create(key,source,**kwargs)
            if created and key.startswith('provenance/unreadable/'):
                (self.root/key).write_bytes(b'x'*kwargs['size'])
            return created
    store,imported,row=acknowledged_import(tmp_path,ReplacedAfterCreate)
    with pytest.raises(ValueError,match='[Aa]cknowledged|SHA-256|changed'):
        imported_unreadable_provenance(imported,store,row['path'])


def test_acknowledged_import_keeps_private_custody_and_the_five_public_fields(tmp_path):
    from congress_api.lake.daily import _final_provenance
    from congress_api.retention.provenance import imported_unreadable_provenance
    store,imported,row=acknowledged_import(tmp_path)
    public,custody=imported_unreadable_provenance(imported,store,row['path'])
    assert public==row and set(public)=={'key','path','etag','sha256','size'}
    custody.require(row['path'])
    final=_final_provenance({k:[] for k in ['recoveries','reviews','unreadable']},store,[public],{},
                            acknowledgements={row['key']:custody})
    assert final['unreadable']==[row]


def test_private_ack_custody_rejects_replacement_even_with_a_valid_initial_alias(tmp_path):
    from congress_api.lake.daily import _final_provenance
    from congress_api.retention.provenance import imported_unreadable_provenance
    from congress_shared.custody import custody_identity
    store,imported,row=acknowledged_import(tmp_path)
    alias=tmp_path/'initial-copy.jsonl';alias.write_bytes(Path(row['path']).read_bytes())
    initial=dict(row,path=str(alias),etag='initial-qualification')
    public,custody=imported_unreadable_provenance(imported,store,row['path'])
    Path(row['path']).write_bytes(b'x'*row['size'])
    with pytest.raises(ValueError,match='[Aa]cknowledged|custody|changed'):
        _final_provenance(dict(recoveries=[],reviews=[],unreadable=[initial]),store,[public],
            {str(alias):custody_identity(alias)},acknowledgements={row['key']:custody})


def test_private_ack_custody_keeps_a_deleted_import_mandatory(tmp_path):
    from congress_api.lake.daily import _final_provenance
    from congress_api.retention.provenance import imported_unreadable_provenance
    store,imported,row=acknowledged_import(tmp_path)
    public,custody=imported_unreadable_provenance(imported,store,row['path'])
    Path(row['path']).unlink()
    with pytest.raises(ValueError,match='[Aa]cknowledged|custody|changed'):
        _final_provenance({k:[] for k in ['recoveries','reviews','unreadable']},store,[public],{},
            acknowledgements={row['key']:custody})


def test_initial_same_key_qualification_is_checked_before_any_path_preference(tmp_path):
    from congress_api.lake.daily import _final_provenance
    store,_,row=acknowledged_import(tmp_path)
    initial=dict(row,sha256='0'*64)
    with pytest.raises(ValueError,match='[Cc]onflicting|[Aa]cknowledged|custody'):
        _final_provenance(dict(recoveries=[],reviews=[],unreadable=[initial]),store,[row],{})


def test_matching_ack_keeps_the_initial_same_key_qualification(tmp_path):
    from congress_api.lake.daily import _final_provenance
    from congress_api.retention.provenance import imported_unreadable_provenance
    from congress_shared.custody import custody_identity
    store,imported,row=acknowledged_import(tmp_path)
    alias=tmp_path/'initial-copy.jsonl';alias.write_bytes(Path(row['path']).read_bytes())
    initial=dict(row,path=str(alias),etag='initial-qualification')
    public,custody=imported_unreadable_provenance(imported,store,row['path'])
    final=_final_provenance(dict(recoveries=[],reviews=[],unreadable=[initial]),store,[public],
        {str(alias):custody_identity(alias)},acknowledgements={row['key']:custody})
    assert final['unreadable']==[initial]


def native_fixture(tmp_path,count=1,*,payloads=None,url_prefix='https://docs.house.gov/report',url_suffix='.json',family='documents'):
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
        data=(payloads[i] if payloads is not None else
            json.dumps(dict(title='Daily input '+str(i),url=url_prefix+str(i)+url_suffix)).encode())
        entity=tmp_path/('body'+str(i));entity.write_bytes(data);digest=hashlib.sha256(data).hexdigest()
        body=BodyFile(entity,digest,len(data),'application/json',None,None,None)
        url=url_prefix+str(i)+url_suffix
        attempt=FetchAttempt(url,url,STAMP,'direct',200,None,{},(),True,body)
        key,line=writer.write(FetchResult(attempt),family=family)
        files.append(dict(key=key,path=str(root/key),qualification=qualifications[key]))
        capture=line['captures'][0];physical='bodies/sha256/'+digest[:2]+'/'+digest+capture['stored_suffix']
        # Canonical gzip bodies have no suffix. Inventory records byte facts.
        with (root/physical).open('rb') as stored:stored_gzip=stored.read(2)==b'\x1f\x8b'
        inventory.append(dict(body_sha=bytes.fromhex(digest),physical_key=physical,relative_path=physical,
            stored_bytes=capture['stored_bytes'],stored_gzip=stored_gzip))
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
    assert first['new_receipt_keys']==first['receipt_keys']
    assert all(p['snapshot'] is not None for p in first['pins'].values())
    assert first['producerreports']['readings']['work_items']==1
    assert first['producerreports']['readings']['read_bytes']>0
    assert first['currentversions']['filename_readings']
    value=replace_spec(value,work=str(tmp_path/'second'))
    second=produce_daily(value,engine=engine,raw_store=store)
    assert second['status']=='completed' and second['receipt_keys']==first['receipt_keys']
    assert second['new_receipt_keys']==[]
    assert second['producerreports']['readings']['work_items']==0
    assert second['producerreports']['readings']['read_bytes']==0
    final=json.loads((tmp_path/'second/final-heads/job.json').read_text())
    assert final['table_operations']==[dict(kind='resolve',name=n,table=t) for n,t in TABLES.items()]


def test_native_daily_identity_includes_existing_and_new_receipts(tmp_path):
    from congress_api.lake.daily import produce_daily
    value,engine,store=native_fixture(tmp_path,2)
    first=produce_daily(dict(value,receipt_inventory=value['receipt_inventory'][:1]),engine=engine,raw_store=store)
    second=produce_daily(dict(value,work=str(tmp_path/'second')),engine=engine,raw_store=store)
    keys=sorted(row['key'] for row in value['receipt_inventory'])
    assert first['receipt_keys']==keys[:1]
    assert second['receipt_keys']==keys and second['new_receipt_keys']==keys[1:]
    third=produce_daily(dict(value,work=str(tmp_path/'third')),engine=engine,raw_store=store)
    assert third['receipt_keys']==keys and third['new_receipt_keys']==[]


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


def test_native_daily_refuses_captures_committed_after_its_parser_work(tmp_path):
    from congress_api.lake import captures,tables
    from congress_api.lake.daily import produce_daily
    value,engine,store=native_fixture(tmp_path,2)
    late=value['receipt_inventory'][1]
    first=produce_daily(dict(value,receipt_inventory=value['receipt_inventory'][:1]),engine=engine,raw_store=store)
    assert first['status']=='completed'
    staged=captures.stage_captures([late],engine=engine,work=tmp_path/'late-captures')
    manifest=json.loads((staged/'ingested-receipts.json').read_text())
    class ConcurrentNative:
        def __getattr__(self,name):return getattr(engine,name)
        def run_job(self,path):
            if path.parent.name=='final-heads':
                tables.append_rows(staged/'captures.parquet',engine=engine,
                    work=tmp_path/'late-append',catalog_root=value['catalog_root'],
                    table=TABLES['captures'],keys=['receipt_key'],definition=manifest['mapping_digest'])
            return engine.run_job(path)
    with pytest.raises(ValueError,match='captures.*changed'):
        produce_daily(dict(value,receipt_inventory=value['receipt_inventory'][:1],work=str(tmp_path/'second')),
            engine=ConcurrentNative(),raw_store=store)
    assert (tmp_path/'late-append/result.json').exists()


def test_native_daily_r2_imports_and_resume_reuse_complete_qualified_inputs(tmp_path):
    from congress_api.lake.daily import produce_daily
    from congress_api.retention.body_store import R2Adapter
    from test_provenance_inventory import R2,KEY,known_cache
    prior=json.dumps(dict(id='prior',body_sha256='b'*64,parser='json',parser_version='old',
        reason='timeout',decided_by='readings',decided_at=STAMP,supersedes=None)).encode()+b'\n'
    public,_=known_cache(tmp_path,prior);client=R2([(KEY,prior)])
    decision_store=BodyStore(R2Adapter(client,'bucket'))
    # Malformed JSON is a completed input rejection. A valid page with more
    # than the worker's 8MiB output budget exercises real failure settlement.
    payload=json.dumps(dict(urls=['https://fixture.test/'+('a'*2200)]*4096)).encode()
    value,engine,_=native_fixture(tmp_path,payloads=[payload])
    value['provenance']['unreadable']=[public]
    first=produce_daily(value,engine=engine,raw_store=decision_store)
    assert first['status']=='completed' and first['producerreports']['readings']['unreadable']>=1
    assert len(first['provenance']['unreadable'])>=2 and client.put_calls
    decisions=[json.loads(line) for row in first['provenance']['unreadable']
        if row['key']!=KEY for line in Path(row['path']).read_text().splitlines()]
    assert decisions and all(row['reason']=='output_limit' for row in decisions)
    for row in first['provenance']['unreadable']:
        payload=client.objects[row['key']]
        assert row['etag']==hashlib.md5(payload).hexdigest()
        assert row['sha256']==hashlib.sha256(payload).hexdigest()
        assert Path(row['path']).read_bytes()==payload
    puts=len(client.put_calls)
    second=produce_daily(dict(value,work=str(tmp_path/'second'),provenance=first['provenance']),
        engine=engine,raw_store=decision_store)
    assert second['status']=='completed' and second['receipt_keys']==first['receipt_keys']
    assert second['producerreports']['readings']['work_items']==0
    assert second['provenance']==first['provenance'] and len(client.put_calls)==puts
    assert not client.list_calls and not client.get_calls and not client.head_calls


def test_native_daily_producer_refreshes_and_pins_all_five_tables(tmp_path):
    from congress_api.lake import appearance_records,meeting_records
    from congress_api.lake.daily import ALL_TABLE_NAMES,produce_daily
    detail_payload=json.dumps({
        'committeeMeeting':{
            'eventId':'115538',
            'congress':118,
            'chamber':'House',
            'title':'Daily Hearing',
            'date':'2024-07-09T14:00:00Z',
            'committees':[{'systemCode':'hsju00','name':'Judiciary','chamber':'House'}],
            'witnesses':[{'name':'Dr. Jane Doe','organization':'ACME'}],
        }
    }).encode()
    value,engine,store=native_fixture(tmp_path,payloads=[detail_payload],
        url_prefix='https://api.congress.gov/v3/committee-meeting/118/house/11553',url_suffix='',family='congress/meetings')
    five_tables={name:dict(namespace=['archive'],name=name) for name in ALL_TABLE_NAMES}
    meeting_records.create_table(engine=engine,work=tmp_path/'create-meetings',catalog_root=value['catalog_root'],
        table=five_tables['meeting_records'],location=tmp_path/'lake-meetings')
    appearance_records.create_table(engine=engine,work=tmp_path/'create-appearances',catalog_root=value['catalog_root'],
        table=five_tables['appearance_records'],location=tmp_path/'lake-appearances')
    value['tables']=five_tables
    first=produce_daily(value,engine=engine,raw_store=store)
    assert first['status']=='completed' and set(first['pins'])==set(ALL_TABLE_NAMES)
    assert first['currentversions']['meeting_records']==meeting_records.current_version()
    assert first['currentversions']['appearance_records']==appearance_records.current_version()
    assert first['producerreports']['meeting_records']['produced']==1
    assert first['producerreports']['appearance_records']['produced']==1
    second=produce_daily(dict(value,work=str(tmp_path/'second')),engine=engine,raw_store=store)
    assert second['status']=='completed' and set(second['pins'])==set(ALL_TABLE_NAMES)
    assert second['producerreports']['meeting_records']['work_items']==0
    assert second['producerreports']['appearance_records']['work_items']==0
