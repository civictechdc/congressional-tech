"""The daily producer refreshes all three lake inputs before publication."""
import gzip
import hashlib
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.retention.body_store import BodyStore,LocalAdapter
from native_test_helpers import empty_readings


STAMP='2026-10-28T12:00:00Z'
TABLES={name:dict(namespace=['archive'],name=name)
        for name in ['captures','readings','filename_readings']}


def spec(root):
    return dict(work=str(root/'work'),decided_at=STAMP,catalog_root=str(root/'catalog'),
        tables=dict(TABLES),receipt_inventory=[],body_inventory=str(root/'body-inventory.parquet'),
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
        inventory.append(dict(body_sha=bytes.fromhex(digest),physical_key=physical,relative_path=physical,
            stored_bytes=capture['stored_bytes']))
    value=spec(tmp_path);value['receipt_inventory']=files
    pq.write_table(pa.Table.from_pylist(inventory,schema=pa.schema([('body_sha',pa.binary(32)),
        ('physical_key',pa.string()),('relative_path',pa.string()),('stored_bytes',pa.int64())])),value['body_inventory'])
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


def test_native_daily_refuses_receipts_built_by_another_capture_mapping(tmp_path,monkeypatch):
    # Defect guarded: rows from an older mapping look present to the receipt anti-join, so
    # daily never corrects them (v21's ~51k wrong rows after the Basin snapshot).
    from congress_api.lake import daily
    value,engine,store=native_fixture(tmp_path,2)
    first=daily.produce_daily(dict(value,receipt_inventory=value['receipt_inventory'][:1]),engine=engine,raw_store=store)
    assert first['status']=='completed'
    built=first['currentversions']['captures']
    monkeypatch.setattr(daily.captures,'current_version',lambda:'next-mapping')
    second=daily.produce_daily(dict(value,work=str(tmp_path/'second')),engine=engine,raw_store=store)
    assert second['status']=='backfill_required' and second['pins'] is None
    [stale]=second['producerreports']['captures']['stale_mappings']
    assert stale['mapping_version']==built and stale['receipts']==1 and stale['captures']>=1
    # Nothing was staged: neither the stale receipt again nor the new one.
    assert not (tmp_path/'second/captures').exists() and not (tmp_path/'second/readings').exists()


def replace_spec(value,**changes):
    return dict(value,**changes)


def test_native_daily_defers_receipts_past_the_budget_to_later_nights(tmp_path):
    from congress_api.lake.daily import produce_daily
    value,engine,store=native_fixture(tmp_path,2);value['max_work_items']=1
    keys=sorted(row['key'] for row in value['receipt_inventory'])
    first=produce_daily(value,engine=engine,raw_store=store)
    assert first['status']=='completed' and first['new_receipt_keys']==keys[:1]
    assert first['receipt_budget']==dict(selected=2,kept=1,fresh_bodies=1,pending_bodies=0,max_work_items=1)
    assert first['producerreports']['readings']['work_items']==1
    second=produce_daily(dict(value,work=str(tmp_path/'second')),engine=engine,raw_store=store)
    assert second['status']=='completed' and second['new_receipt_keys']==keys[1:]
    third=produce_daily(dict(value,work=str(tmp_path/'third')),engine=engine,raw_store=store)
    assert third['status']=='completed' and third['new_receipt_keys']==[]


def test_native_daily_pending_backlog_fills_the_budget_before_any_new_receipt(tmp_path):
    # Defect guarded: the receipt budget ignored bodies already pending in captures, so a night
    # appended new bodies on top of them and then refused after the append (2026-11-04).
    from congress_api.lake import tables
    from congress_api.lake.daily import produce_daily
    value,engine,store=native_fixture(tmp_path,2);value['max_work_items']=1
    older,newer=sorted(value['receipt_inventory'],key=lambda row:row['key'])
    item=pq.read_table(value['body_inventory']).to_pylist()
    first_body=json.loads(gzip.open(older['path'],'rt').readline())['captures'][0]['sha256']
    missing=next(row for row in item if row['body_sha'].hex()==first_body)
    (tmp_path/'raw'/missing['relative_path']).rename(tmp_path/'held')
    pending=produce_daily(dict(value,receipt_inventory=[older]),engine=engine,raw_store=store)
    assert pending['status']=='pending'
    head=lambda name:tables.resolve_tables(engine=engine,work=tmp_path/name,catalog_root=value['catalog_root'],
        tables={'captures':TABLES['captures']})['captures']
    before=head('before')
    result=produce_daily(dict(value,work=str(tmp_path/'second')),engine=engine,raw_store=store)
    assert result['status']=='pending' and result['pins'] is None
    assert result['receipt_budget']==dict(selected=1,kept=0,fresh_bodies=0,pending_bodies=1,max_work_items=1)
    assert result['new_receipt_keys']==[] and result['producerreports']['captures']==dict(stage=None,append=None)
    assert head('after')==before and result['producerreports']['readings']['work_items']==1
    (tmp_path/'held').rename(tmp_path/'raw'/missing['relative_path'])
    drained=produce_daily(dict(value,work=str(tmp_path/'third')),engine=engine,raw_store=store)
    assert drained['status']=='completed' and drained['new_receipt_keys']==[]
    assert drained['producerreports']['readings']['work_items']==1
    admitted=produce_daily(dict(value,work=str(tmp_path/'fourth')),engine=engine,raw_store=store)
    assert admitted['status']=='completed' and admitted['new_receipt_keys']==[newer['key']]


def test_budget_keeps_the_oldest_receipts_counting_each_new_body_once(tmp_path):
    from congress_api.lake.daily import _within_budget
    from docspec_client.client import NativeDatasets
    engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    sha=lambda n:hashlib.sha256(bytes([n])).digest()
    staged=[('receipts/meetings/2026-10-31/m.jsonl.gz',sha(1)),('receipts/meetings/2026-10-31/m.jsonl.gz',sha(2)),
            ('receipts/documents/2026-10-30/d.jsonl.gz',sha(3)),('receipts/documents/2026-10-30/d.jsonl.gz',sha(9)),
            ('receipts/documents/2026-11-01/e.jsonl.gz',sha(1)),('receipts/documents/2026-11-01/e.jsonl.gz',sha(4)),
            ('receipts/house/2026-11-01/f.jsonl.gz',None)]
    schema=pa.schema([('receipt_key',pa.string()),('sha256',pa.binary(32))])
    pq.write_table(pa.Table.from_pylist([dict(receipt_key=k,sha256=s) for k,s in staged],schema=schema),tmp_path/'staged.parquet')
    pq.write_table(pa.Table.from_pylist([dict(receipt_key='receipts/documents/2026-10-01/old.jsonl.gz',sha256=sha(9))],
        schema=schema),tmp_path/'captures.parquet')
    selected=[dict(key=k) for k in sorted({k for k,_ in staged},reverse=True)]
    run=lambda budget,name:_within_budget(tmp_path/'staged.parquet',selected,tmp_path/'captures.parquet',budget,
        engine=engine,work=tmp_path/name)
    kept,fresh=run(3,'three')
    # d (10-30) adds 3 (9 is in captures), m (10-31) adds 1 and 2; e would add 4, a fourth.
    assert [r['key'] for r in kept]==['receipts/documents/2026-10-30/d.jsonl.gz','receipts/meetings/2026-10-31/m.jsonl.gz']
    assert fresh==3
    kept,fresh=run(4,'four')
    assert [r['key'] for r in kept][-2:]==['receipts/documents/2026-11-01/e.jsonl.gz','receipts/house/2026-11-01/f.jsonl.gz']
    assert fresh==4
    assert run(1,'one')==([dict(key='receipts/documents/2026-10-30/d.jsonl.gz')],1)


def test_native_daily_refuses_a_receipt_that_alone_exceeds_the_budget(tmp_path,monkeypatch):
    from congress_api.lake import daily
    value,engine,store=native_fixture(tmp_path,2);value['max_work_items']=1
    monkeypatch.setattr(daily,'_within_budget',lambda *a,**k:([],0))
    result=daily.produce_daily(value,engine=engine,raw_store=store)
    assert result['status']=='backfill_required' and result['pins'] is None
    assert result['producerreports']['captures']['receipt']==min(r['key'] for r in value['receipt_inventory'])
    assert not (tmp_path/'work/captures-append').exists() and not (tmp_path/'work/readings').exists()


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
    from congress_api.lake import capture_staging,captures,tables
    from congress_api.lake.daily import produce_daily
    value,engine,store=native_fixture(tmp_path,2)
    late=value['receipt_inventory'][1]
    first=produce_daily(dict(value,receipt_inventory=value['receipt_inventory'][:1]),engine=engine,raw_store=store)
    assert first['status']=='completed'
    staged=capture_staging.stage_captures([late],engine=engine,work=tmp_path/'late-captures')
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
    assert first['currentversions']['meeting_records']==meeting_records.current_versions()
    assert first['currentversions']['appearance_records']==appearance_records.current_versions()
    assert first['producerreports']['meeting_records']['produced']==1
    assert first['producerreports']['appearance_records']['produced']==1
    second=produce_daily(dict(value,work=str(tmp_path/'second')),engine=engine,raw_store=store)
    assert second['status']=='completed' and set(second['pins'])==set(ALL_TABLE_NAMES)
    assert second['producerreports']['meeting_records']['work_items']==0
    assert second['producerreports']['appearance_records']['work_items']==0


def test_native_daily_video_records_are_opt_in_and_reuse_the_current_pin(tmp_path):
    from congress_api.lake import video_records
    from congress_api.lake.daily import produce_daily

    payload = json.dumps(dict(kind='youtube#videoListResponse', items=[
        dict(kind='youtube#video', id='ABCDEFGHIJK', snippet=dict(title='Committee hearing'),
             contentDetails=dict(duration='PT42S')),
    ])).encode()
    value, engine, store = native_fixture(tmp_path, payloads=[payload], family='youtube/api',
        url_prefix='https://www.googleapis.com/youtube/v3/videos?id=', url_suffix='')
    with engine:
        base = produce_daily(value, engine=engine, raw_store=store)
        assert base['status'] == 'completed'
        assert 'video_records' not in base['pins'] and 'video_records' not in base['producerreports']

        table = dict(namespace=['archive'], name='video_records')
        video_records.create_table(engine=engine, work=tmp_path/'create-videos', catalog_root=value['catalog_root'],
            table=table, location=tmp_path/'lake-videos')
        opted_in = dict(value, tables=dict(value['tables'], video_records=table))
        first = produce_daily(dict(opted_in, work=str(tmp_path/'videos')), engine=engine, raw_store=store)
        assert first['status'] == 'completed' and first['pins']['captures'] == base['pins']['captures']
        assert first['currentversions']['video_records'] == video_records.current_versions()
        produced = first['producerreports']['video_records']
        assert produced['append'] is not None
        [row] = pq.read_table(produced['records']).to_pylist()
        assert row['record_sha'] == hashlib.sha256(payload).digest()
        assert row['source'] == 'youtube_api' and row['status'] == 'completed'
        assert [(video['video_id'], video['duration_seconds']) for video in row['videos']] == [('ABCDEFGHIJK', 42)]

        again = produce_daily(dict(opted_in, work=str(tmp_path/'again')), engine=engine, raw_store=store)
        assert again['status'] == 'completed' and again['pins']['video_records'] == first['pins']['video_records']
        assert again['producerreports']['video_records']['work_items'] == 0


def test_native_daily_retries_playlist_work_after_budget_refusal(tmp_path):
    from congress_api.lake import playlist_records
    from congress_api.lake.daily import produce_daily

    payloads = [f'#EXTM3U\n#EXTINF:8.0,\ntext_{i}.vtt\n#EXT-X-ENDLIST\n'.encode() for i in range(2)]
    value, engine, store = native_fixture(tmp_path, count=2, payloads=payloads,
        url_prefix='https://www.senate.gov/streams/ag051023/text_', url_suffix='.m3u8', family='senate/captions')
    # Put both receipts in captures first so the small budget is tested at the playlist stage.
    base = produce_daily(value, engine=engine, raw_store=store)
    assert base['status'] == 'completed'

    table = dict(namespace=['archive'], name='playlist_records')
    playlist_records.create_table(engine=engine, work=tmp_path/'create-playlists', catalog_root=value['catalog_root'],
        table=table, location=tmp_path/'lake-playlists')
    value['tables']['playlist_records'] = table
    limited = produce_daily(dict(value, work=str(tmp_path/'limited'), max_work_items=1), engine=engine, raw_store=store)
    assert limited['status'] == 'backfill_required'
    assert limited['producerreports']['playlist_records']['work_items'] == 2

    first = produce_daily(dict(value, work=str(tmp_path/'backfill'), max_work_items=2), engine=engine, raw_store=store)
    assert first['status'] == 'completed'
    assert first['pins']['captures'] == base['pins']['captures']
    assert first['currentversions']['playlist_records'] == playlist_records.current_versions()
    records = first['producerreports']['playlist_records']
    assert records['produced'] == 2 and records['append'] is not None
    rows = pq.read_table(records['records']).to_pylist()
    assert {row['record_sha'] for row in rows} == {hashlib.sha256(payload).digest() for payload in payloads}
    assert {tuple(row['segments']) for row in rows} == {('text_0.vtt',), ('text_1.vtt',)}

    second = produce_daily(dict(value, work=str(tmp_path/'second')), engine=engine, raw_store=store)
    assert second['status'] == 'completed'
    assert second['pins']['playlist_records'] == first['pins']['playlist_records']
    assert second['producerreports']['playlist_records']['work_items'] == 0


def test_inline_saved_record_and_govinfo_mods_staging_with_anti_join(tmp_path):
    import gzip
    from docspec_client.client import NativeDatasets
    from congress_api.lake import appearance_records,capture_staging,captures,meeting_records
    raw=tmp_path/'raw';raw.mkdir()
    store=BodyStore(LocalAdapter(raw))
    inline_row=dict(
        writer=dict(job='b14-meeting-fetchers',commit='a'*40),
        run_id='inline-run',
        family='congress/meetings',
        requested_url='https://api.congress.gov/v3/committee-meeting/118/house/115599?format=json',
        url='https://api.congress.gov/v3/committee-meeting/118/house/115599?format=json',
        retrieved_at=STAMP,
        record=dict(
            committeeMeeting=dict(
                eventId='115599',
                congress=118,
                chamber='House',
                title='Inline Saved Meeting',
                date='2024-08-01T14:00:00Z',
                committees=[dict(systemCode='hsif00',name='Energy',chamber='House')],
                witnesses=[dict(name='Dr. Inline Witness',organization='Lab')],
            )
        ),
    )
    receipt_rel='receipts/congress/meetings/2026-10-28/assemble-inline.jsonl.gz'
    receipt_path=raw/receipt_rel;receipt_path.parent.mkdir(parents=True,exist_ok=True)
    receipt_path.write_bytes(gzip.compress((json.dumps(inline_row)+'\n').encode(),mtime=0))
    qual=tmp_path/'inline-qual.json'
    from congress_api.retention.provenance import file_pin
    qual.write_text(json.dumps(dict(path=str(receipt_path),**file_pin(receipt_path),producer='inline test')))
    eng=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    try:
        cap_stage=capture_staging.stage_captures([dict(key=receipt_rel,path=str(receipt_path),qualification=str(qual))],
            engine=eng,work=tmp_path/'cap-stage')/'captures.parquet'
        m_stage=meeting_records.stage(captures=cap_stage,readings=empty_readings(tmp_path/"readings"),engine=eng,work=tmp_path/'m1',
            local_root=raw,raw_store=store,decided_at=STAMP,unreadable_store=store)
        assert m_stage['work_items']==1 and m_stage['produced']==1
        m_rows=pq.read_table(m_stage['records']).to_pylist()
        assert len(m_rows)==1 and m_rows[0]['meetings'][0]['event_id']=='115599'
        # Second pass with existing records anti-joins the inline record
        m_stage2=meeting_records.stage(captures=cap_stage,readings=empty_readings(tmp_path/"readings"),existing=m_stage['records'],engine=eng,
            work=tmp_path/'m2',local_root=raw,raw_store=store,decided_at=STAMP,unreadable_store=store)
        assert m_stage2['work_items']==0 and m_stage2['produced']==0

        a_stage=appearance_records.stage(captures=cap_stage,readings=empty_readings(tmp_path/"readings"),engine=eng,work=tmp_path/'a1',
            local_root=raw,raw_store=store,decided_at=STAMP,unreadable_store=store)
        assert a_stage['work_items']==1 and a_stage['produced']==1
        a_rows=pq.read_table(a_stage['records']).to_pylist()
        assert len(a_rows)==1 and a_rows[0]['appearances'][0]['name']=='Dr. Inline Witness'
        a_stage2=appearance_records.stage(captures=cap_stage,readings=empty_readings(tmp_path/"readings"),existing=a_stage['records'],engine=eng,
            work=tmp_path/'a2',local_root=raw,raw_store=store,decided_at=STAMP,unreadable_store=store)
        assert a_stage2['work_items']==0 and a_stage2['produced']==0

        # Unreadable decisions with short parser ('meetings'/'appearances') or scoped parser ('meeting_records.congress_gov')
        # and body_sha256 (with record_sha=None) also settle inline/body candidates in stage_record_table
        inline_sha=m_rows[0]['record_sha'].hex()
        unr_path=tmp_path/'unreadable-short-scoped.jsonl'
        unr_path.write_text(
            json.dumps(dict(
                id='u-mr',
                body_sha256=inline_sha,
                record_sha=None,
                parser='meetings',
                parser_version=meeting_records.current_version('congress_gov'),
                supersedes=None,
            )) + '\n' +
            json.dumps(dict(
                id='u-ar',
                body_sha256=inline_sha,
                record_sha=None,
                parser='appearance_records.congress_gov',
                parser_version=appearance_records.current_version('congress_gov'),
                supersedes=None,
            )) + '\n'
        )
        m_stage_unr=meeting_records.stage(captures=cap_stage,readings=empty_readings(tmp_path/"readings"),unreadable_files=[dict(key='provenance/unreadable/u.jsonl',path=str(unr_path))],
            engine=eng,work=tmp_path/'m-unr',local_root=raw,raw_store=store,decided_at=STAMP,unreadable_store=store)
        assert m_stage_unr['work_items']==0 and m_stage_unr['produced']==0
        a_stage_unr=appearance_records.stage(captures=cap_stage,readings=empty_readings(tmp_path/"readings"),unreadable_files=[dict(key='provenance/unreadable/u.jsonl',path=str(unr_path))],
            engine=eng,work=tmp_path/'a-unr',local_root=raw,raw_store=store,decided_at=STAMP,unreadable_store=store)
        assert a_stage_unr['work_items']==0 and a_stage_unr['produced']==0
    finally:
        eng.close()


@pytest.mark.parametrize('table',['meeting_records','appearance_records'])
@pytest.mark.parametrize('kind',['composite_scalar','arbitrary_scalar'])
def test_daily_entity_version_check_rejects_scalar_composite_versions(table,kind):
    from congress_api.lake import appearance_records,meeting_records
    from congress_api.lake.daily import _check_entity_versions
    mod=meeting_records if table=='meeting_records' else appearance_records
    bad=mod.current_version() if kind=='composite_scalar' else 'scalar-hash'
    with pytest.raises(ValueError,match=table):
        _check_entity_versions(table,bad,mod)



@pytest.mark.parametrize('derived',['html_metadata',['html'],['html_metadata','html_metadata'],[1]])
def test_invalid_derived_parsers_refuse_before_any_effect(tmp_path,derived):
    from congress_api.lake.daily import produce_daily
    value=dict(spec(tmp_path),derived_parsers=derived)
    with pytest.raises(ValueError,match='derived_parsers'):
        produce_daily(value,engine=NeverNative(),raw_store=BodyStore(LocalAdapter(tmp_path/'durable')))
    assert not (tmp_path/'work').exists()


def test_native_daily_derived_pass_reads_html_after_the_combined_pass(tmp_path):
    from congress_api.lake import compatible_versions,readings,tables
    from congress_api.lake.daily import produce_daily
    pages=[f'<html><head><title>Hearing {i}</title><meta property="og:description" content="About it"></head><body><p>x</p></body></html>'.encode()
        for i in range(3)]
    value,engine,store=native_fixture(tmp_path,4,payloads=[*pages,json.dumps(dict(url='https://x.test/a')).encode()],
        url_suffix='.htm')
    value['derived_parsers']=['html_metadata']
    baseline=tables.resolve_tables(engine=engine,catalog_root=value['catalog_root'],work=tmp_path/'baseline',
        tables={'captures':value['tables']['captures']})['captures']
    value['derived_scopes']={'html_metadata':dict(captures=baseline,versions=compatible_versions.current_pins(),
        max_stored_bytes=1<<20)}
    first=produce_daily(value,engine=engine,raw_store=store)
    assert first['status']=='completed'
    assert first['producerreports']['readings']['work_items']==4
    derived=first['producerreports']['html_metadata']
    assert derived['work_items']==3 and derived['parser_version']==readings.current_version('html_metadata')
    # ct-z4i9: the admitted pass is one parser batch and one catalog commit, not one per page.
    assert [sum(f['rows'] for f in b['append']['files']) for b in derived['batches']]==[3]
    assert first['currentversions']['html_metadata']==derived['parser_version']
    second=produce_daily(dict(value,work=str(tmp_path/'second')),engine=engine,raw_store=store)
    assert second['producerreports']['html_metadata']['work_items']==0
    assert derived['budget']['stored_bytes']>0 and derived['budget']['missing_sizes']==0
    assert second['producerreports']['html_metadata']['read_bytes']==0
    without=produce_daily(dict(value,work=str(tmp_path/'third'),derived_parsers=[],derived_scopes={}),engine=engine,raw_store=store)
    assert 'html_metadata' not in without['producerreports'] and 'html_metadata' not in without['currentversions']


@pytest.mark.parametrize('change',['absent','versions','bytes','batch','unknown'])
def test_daily_derived_scope_refuses_before_effects(tmp_path,change):
    from congress_api.lake import compatible_versions,daily
    baseline=dict(metadata_location='/qualified.metadata.json',table_uuid='a'*32,snapshot=7,schema_id=0)
    scope=dict(captures=baseline,versions=compatible_versions.current_pins(),max_stored_bytes=1024)
    value=dict(spec(tmp_path),derived_parsers=['html_metadata'],derived_scopes={'html_metadata':scope})
    if change=='absent':value.pop('derived_scopes')
    elif change=='versions':scope['versions']=dict(scope['versions'],html_metadata='old')
    elif change=='bytes':scope['max_stored_bytes']=True
    elif change=='batch':scope['batch_size']=1  # retired (ct-z4i9): one commit per pass
    else:scope['extra']='unrecognized'
    with pytest.raises(ValueError,match='scope|stored_bytes|batch_size'):
        daily.produce_daily(value,engine=NeverNative(),raw_store=BodyStore(LocalAdapter(tmp_path/'durable')))
    assert not (tmp_path/'work').exists() and not (tmp_path/'durable').exists()
