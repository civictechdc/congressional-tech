"""Verify raw custody and protect kept releases during maintenance."""
import base64
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
from types import SimpleNamespace
from uuid import NAMESPACE_URL,uuid5

import pytest

from viewer_publication.archive_publish import POINTER,input_digest
from viewer_publication.receipt_pins import PREFIX,write_input_receipts

NOW=datetime(2026,10,28,12,tzinfo=timezone.utc)
LIVE='a'*64;PREVIOUS='b'*64;PINNED='c'*64;OLD='d'*64;RECENT='e'*64;BOUNDARY='f'*64


class Store:
    def __init__(self):
        self.objects={};self.times={};self.deleted=[];self.reads={};self.list_calls=0;self.pointer_calls=0
        self.live=dict(release_id=LIVE,previous_release_id=PREVIOUS);self.etag='pinned';self.change_pointer=False
    def create(self,key,body,**metadata):
        self.objects[key]=body;self.times[key]=NOW-timedelta(days=3)
    def get(self,key):
        self.reads[key]=self.reads.get(key,0)+1
        return self.objects[key]
    def pointer(self):
        self.pointer_calls+=1
        if self.change_pointer and self.pointer_calls>1:return dict(release_id=PINNED,previous_release_id=LIVE),'changed'
        return deepcopy(self.live),self.etag
    def inventory(self):
        self.list_calls+=1
        return [dict(Key=key,LastModified=self.times[key]) for key in sorted(self.objects)]
    def delete(self,key):self.deleted.append(key)


def add_input(store,release,identity):
    keys=['receipts/documents/'+identity+'.jsonl.gz']
    from viewer_publication.archive_model_profile import profile_record
    snapshots={name:dict(kind='native_table',name=name,
        metadata_location='s3://fixture-lake/'+identity+'/'+name+'/metadata/00001.json',
        table_uuid=str(uuid5(NAMESPACE_URL,identity+'/'+name)),snapshot=1,schema_id=0)
        for name in ['captures','readings','filename_readings']}
    profile=profile_record(parser_versions={name:'fixture-'+identity for name in ['sniff','html','xml','json']},
        catalog_version='fixture-catalog',engine_revision='a'*40,runtime_pins={'platform':'fixture'},
        lake_versions={name:{'schema_sha256':'b'*64} for name in snapshots},
        writer_settings={'whole':{'compression':'zstd'}},snapshots=snapshots,file_hashes={'fixture.sql':'c'*64})['profile']
    record=dict(profile=profile,provenance=[],entity_digests={},snapshots=snapshots)
    record['input_digest']=input_digest(receipt_keys=keys,**{k:record[k] for k in ['profile','provenance','entity_digests']})
    return write_input_receipts(store,release,record['input_digest'],record,keys)


def fixture():
    store=Store();records=[add_input(store,LIVE,'one'),add_input(store,LIVE,'two'),
                           add_input(store,PREVIOUS,'previous'),add_input(store,PINNED,'external')]
    for release,age in [(OLD,timedelta(days=2)),(RECENT,timedelta(days=3)),(BOUNDARY,timedelta(days=1))]:
        store.create(PREFIX+release+'/manifest.json',b'{}');store.times[PREFIX+release+'/manifest.json']=NOW-age
    store.create(PREFIX+OLD+'/list.parquet',b'old')
    # Retention takes the newest object in each release, preserving failed candidates.
    store.create(PREFIX+RECENT+'/candidate.parquet',b'new');store.times[PREFIX+RECENT+'/candidate.parquet']=NOW-timedelta(hours=1)
    return store,records


def test_plan_collects_every_kept_identity_and_uses_newest_object_age():
    from viewer_publication.archive_maintenance import maintain_releases
    store,records=fixture()
    result=maintain_releases(store,now=NOW,external_pins=(value for value in [PINNED]))
    assert result['status']=='planned' and store.deleted==[]
    assert sorted(record['input_digest'] for record in result['kept_inputs'])==sorted(record['input_digest'] for record in records)
    assert result['kept_releases']==[LIVE,PREVIOUS,PINNED]
    assert result['delete_keys']==[PREFIX+OLD+'/list.parquet',PREFIX+OLD+'/manifest.json']
    assert store.list_calls==1 and store.pointer_calls==1
    assert all(count==1 for count in store.reads.values())


def test_execute_rereads_pointer_before_only_old_derived_deletes():
    from viewer_publication.archive_maintenance import maintain_releases
    store,_=fixture()
    result=maintain_releases(store,now=NOW,external_pins=[PINNED],execute=True)
    assert result['status']=='executed' and store.deleted==result['delete_keys']
    assert store.pointer_calls==2
    assert all(key.startswith(PREFIX+OLD+'/') for key in store.deleted)


def test_execute_refuses_release_writes_if_external_pins_change_after_listing():
    from viewer_publication.archive_maintenance import maintain_releases
    from viewer_publication.archive_publish import SPICY_PINS

    store,_=fixture()
    pins=[PINNED]
    original_inventory=store.inventory
    def inventory():
        rows=original_inventory()
        pins.append(OLD)
        return rows
    def pin_source():
        return dict(version=1,updated_at=NOW.isoformat(),releases=pins)
    store.inventory=inventory
    with pytest.raises(ValueError,match='External release pins changed'):
        maintain_releases(store,now=NOW,external_pins_source=pin_source,execute=True)
    assert store.pointer_calls==2 and store.deleted==[]
    assert SPICY_PINS not in store.objects


@pytest.mark.parametrize('change',[None,{'base_release_id':'invalid'}, {'registry_sha256':None},
    {'schema_sha256':'g'*64}, {'relationships_version':2}, {'relationships_version':True}])
def test_metadata_only_release_preserves_valid_retention_inputs(change):
    from viewer_publication.archive_maintenance import maintain_releases
    from viewer_publication.receipt_pins import read_receipt_list
    store,records=fixture()
    record=deepcopy(records[0])
    original_profile=deepcopy(record['profile'])
    keys=read_receipt_list(record['receipt_keys_sha256'],store.get(
        PREFIX+LIVE+'/inputs/receipts/'+record['receipt_keys_sha256']+'.json.gz'))
    update=dict(base_release_id=PREVIOUS,registry_sha256='1'*64,schema_sha256='2'*64,relationships_version=1)
    if change:update.update(change)
    record['profile']['relationship_metadata_update']=update
    record['input_digest']=input_digest(receipt_keys=keys,**{k:record[k] for k in ['profile','provenance','entity_digests']})
    assert record['input_digest']!=records[0]['input_digest']
    write_input_receipts(store,LIVE,record['input_digest'],record,keys)
    if change:
        with pytest.raises(ValueError):maintain_releases(store,now=NOW,execute=True)
        assert store.deleted==[]
    else:
        result=maintain_releases(store,now=NOW)
        kept=next(item for item in result['kept_inputs'] if item['input_digest']==record['input_digest'])
        assert kept['profile'].pop('relationship_metadata_update')==update
        assert kept['profile']==original_profile
        assert store.deleted==[]


@pytest.mark.parametrize('failure',['identity','receipts','missing','pointer','escape'])
def test_invalid_kept_evidence_or_pointer_race_prevents_every_delete(failure):
    from viewer_publication.archive_maintenance import maintain_releases
    store,_=fixture()
    record_key=next(key for key in store.objects if key.startswith(PREFIX+LIVE+'/inputs/') and key.endswith('.json'))
    if failure=='identity':
        row=json.loads(store.objects[record_key]);row['profile']={'changed':True};store.objects[record_key]=json.dumps(row).encode()
    elif failure=='receipts':
        key=next(key for key in store.objects if key.startswith(PREFIX+LIVE+'/inputs/receipts/'));store.objects[key]=b'bad gzip'
    elif failure=='missing':
        for key in list(store.objects):
            if key.startswith(PREFIX+PREVIOUS+'/'):del store.objects[key]
    elif failure=='pointer':store.change_pointer=True
    else:store.objects['bodies/sha256/raw']=b'raw';store.times['bodies/sha256/raw']=NOW-timedelta(days=3)
    with pytest.raises(ValueError):maintain_releases(store,now=NOW,external_pins=[PINNED],execute=True)
    assert store.deleted==[]


def test_invalid_pin_or_naive_time_refuses_without_inventory():
    from viewer_publication.archive_maintenance import maintain_releases
    for now,pins in [(NOW,['../raw']),(datetime(2026,10,28),[])]:
        store,_=fixture()
        with pytest.raises(ValueError):maintain_releases(store,now=now,external_pins=pins,execute=True)
        assert store.list_calls==0 and store.deleted==[]


def test_sdk_adapter_lists_only_release_inventory_and_guards_delete_keys():
    from types import SimpleNamespace
    from viewer_publication.archive_maintenance import ArchiveMaintenanceStore
    class SDK:
        meta=SimpleNamespace(config=SimpleNamespace(retries={'total_max_attempts':1}))
        def __init__(self):self.calls=[]
        def get_object(self,**request):raise AssertionError('Unexpected SDK GET')
        def put_object(self,**request):raise AssertionError('Maintenance must not PUT')
        def list_objects_v2(self,**request):
            self.calls.append(('list',request))
            return dict(Contents=[dict(Key=PREFIX+OLD+'/list.parquet',LastModified=NOW)],IsTruncated=False)
        def delete_object(self,**request):self.calls.append(('delete',request));return {}
    client=SDK();store=ArchiveMaintenanceStore(client=client,bucket='archive-fixture')
    assert list(store.inventory())==[dict(Key=PREFIX+OLD+'/list.parquet',LastModified=NOW)]
    assert client.calls==[('list',dict(Bucket='archive-fixture',Prefix=PREFIX))]
    for bad in ['bodies/sha256/raw',PREFIX,PREFIX+OLD+'/',PREFIX+OLD+'/../raw',PREFIX+OLD+'/%2e%2e/raw']:
        with pytest.raises(ValueError):store.delete(bad)
    assert len(client.calls)==1
    store.delete(PREFIX+OLD+'/list.parquet')
    assert client.calls[-1]==('delete',dict(Bucket='archive-fixture',Key=PREFIX+OLD+'/list.parquet'))
    client.meta=SimpleNamespace(config=SimpleNamespace(retries={'total_max_attempts':2}))
    with pytest.raises(ValueError):ArchiveMaintenanceStore(client=client,bucket='archive-fixture')


def test_legacy_release_objects_are_preserved_without_reading_or_deleting():
    from viewer_publication.archive_maintenance import maintain_releases
    store,_=fixture();legacy=PREFIX+'filename-viewer-v4-old/list.parquet'
    store.create(legacy,b'legacy');store.times[legacy]=NOW-timedelta(days=100)
    result=maintain_releases(store,now=NOW,external_pins=[PINNED],execute=True)
    assert legacy not in store.deleted and legacy not in store.reads
    assert result['ignored_legacy_objects']==1
    assert all(key.startswith(PREFIX+OLD+'/') for key in store.deleted)


def test_legacy_live_pointer_refuses_before_inventory_or_deletion():
    from viewer_publication.archive_maintenance import maintain_releases
    store,_=fixture();store.live=dict(release_id='filename-viewer-v4-old',previous_release_id=None)
    with pytest.raises(ValueError):maintain_releases(store,now=NOW,execute=True)
    assert store.list_calls==0 and store.deleted==[]


@pytest.mark.parametrize('failure',['missing_snapshots','empty_snapshots','incomplete_tables','unknown_tables',
    'native_uuid','native_schema','native_snapshot','native_metadata','wrong_name','parquet_digest',
    'missing_profile','profile_field','profile_file_hashes','profile_null_file_hashes'])
def test_unusable_kept_model_pins_refuse_before_deletes_or_purge_evidence(failure):
    from viewer_publication.archive_maintenance import maintain_releases
    store,_=fixture()
    key=next(key for key in store.objects if key.startswith(PREFIX+LIVE+'/inputs/') and key.endswith('.json'))
    record=json.loads(store.objects[key])
    if failure=='missing_snapshots':del record['snapshots']
    elif failure=='empty_snapshots':record['snapshots']={}
    elif failure=='incomplete_tables':del record['snapshots']['filename_readings']
    elif failure=='unknown_tables':record['snapshots']['unrecognized']=record['snapshots']['captures']
    elif failure=='native_uuid':record['snapshots']['captures']['table_uuid']='invalid'
    elif failure=='native_schema':del record['snapshots']['readings']['schema_id']
    elif failure=='native_snapshot':record['snapshots']['captures']['snapshot']='latest'
    elif failure=='native_metadata':record['snapshots']['captures']['metadata_location']=''
    elif failure=='wrong_name':record['snapshots']['readings']['name']='captures'
    elif failure=='parquet_digest':record['snapshots']['captures']=dict(kind='parquet',path='/not-opened/table.parquet',sha256='bad',size=1)
    elif failure=='missing_profile':del record['profile']
    elif failure=='profile_field':del record['profile']['runtime_pins']
    elif failure=='profile_file_hashes':record['profile']['file_hashes']={}
    else:record['profile']['file_hashes']=None
    if 'profile' in record:
        # Profiles are semantic: keep the mutated record's digest self-consistent,
        # so shape checks rather than a stale digest must protect the purge seam.
        from viewer_publication.receipt_pins import read_receipt_list
        keys=read_receipt_list(record['receipt_keys_sha256'],store.objects[
            PREFIX+LIVE+'/inputs/receipts/'+record['receipt_keys_sha256']+'.json.gz'])
        record['input_digest']=input_digest(receipt_keys=keys,**{k:record[k] for k in ['profile','provenance','entity_digests']})
        key=PREFIX+LIVE+'/inputs/'+record['input_digest']+'.json'
    store.create(key,json.dumps(record).encode())
    for execute in [False,True]:
        with pytest.raises(ValueError):maintain_releases(store,now=NOW,external_pins=[PINNED],execute=execute)
        assert store.deleted==[]


def test_every_historical_kept_native_selector_protects_its_generation(tmp_path):
    from congress_api.lake.maintenance import PIN_FIELDS,purge_generation
    from viewer_publication.archive_maintenance import maintain_releases
    store,records=fixture();result=maintain_releases(store,now=NOW,external_pins=[PINNED])
    for record in records:
        for selector in record['snapshots'].values():
            selected={key:selector[key] for key in PIN_FIELDS}
            with pytest.raises(ValueError,match='kept release pins'):
                purge_generation(selected,table='fixture_generation',kept_inputs=result['kept_inputs'],
                    engine=object(),work=tmp_path/'not-created',catalog_root='/not-opened')
    assert not (tmp_path/'not-created').exists() and store.deleted==[]


def test_valid_kept_parquet_selectors_require_no_local_payload_reads():
    from viewer_publication.archive_maintenance import maintain_releases
    store,_=fixture()
    for key in list(store.objects):
        if '/inputs/' in key and key.endswith('.json'):
            record=json.loads(store.objects[key]);record['snapshots']={name:dict(kind='parquet',
                path='/not-opened/'+name+'.parquet',sha256='a'*64,size=17)
                for name in ['captures','readings','filename_readings']}
            store.objects[key]=json.dumps(record).encode()
    result=maintain_releases(store,now=NOW,external_pins=[PINNED])
    assert len(result['kept_inputs'])==4 and store.deleted==[]


@pytest.mark.parametrize('historical',[True,False])
def test_kept_entity_parquet_profile_uses_its_original_parser_fields(historical):
    from viewer_publication import archive_maintenance
    from viewer_publication.receipt_pins import read_receipt_list

    store,records=fixture()
    record=deepcopy(records[3])
    old_digest=record['input_digest']
    for name in ('meeting_records','appearance_records'):
        record['snapshots'][name]=dict(kind='parquet',path='/not-opened/'+name+'.parquet',sha256='a'*64,size=17)
        record['profile']['lake_versions'][name]=dict(schema_sha256='b'*64)
    record['profile']['file_hashes'][archive_maintenance.PROFILE_SOURCE]=(
        archive_maintenance.LEGACY_PROFILE_SHA if historical else 'a'*64)
    prefix=PREFIX+PINNED+'/inputs/'
    keys=read_receipt_list(record['receipt_keys_sha256'],store.get(
        prefix+'receipts/'+record['receipt_keys_sha256']+'.json.gz'))
    record['input_digest']=input_digest(receipt_keys=keys,**{k:record[k] for k in ('profile','provenance','entity_digests')})
    del store.objects[prefix+old_digest+'.json']
    write_input_receipts(store,PINNED,record['input_digest'],record,keys)
    if historical:
        result=archive_maintenance.maintain_releases(store,now=NOW,external_pins=[PINNED])
        assert result['kept_releases']==[LIVE,PREVIOUS,PINNED]
    else:
        with pytest.raises(ValueError,match='requires pinned meeting_records'):
            archive_maintenance.maintain_releases(store,now=NOW,external_pins=[PINNED])
    assert store.deleted==[]


def test_maintenance_and_backfill_cli_plan_and_execute_specs(tmp_path,capsys,monkeypatch):
    from pathlib import Path
    from congress_api.lake.daily import ALL_TABLE_NAMES
    from congress_shared import storage
    from viewer_publication import archive_backfill_job,archive_maintenance
    from urllib import request
    root=Path(__file__).resolve().parents[3]
    store,_=fixture()
    client=RecordingS3(store)
    def fetch_pins(req,*,timeout):
        assert req.full_url=='https://data.spicygov.ai/pins/archive-releases.json'
        assert req.get_header('User-agent')=='CongressionalArchiveMaintenance/1.0'
        return io.BytesIO(json.dumps(dict(version=1,updated_at=NOW.isoformat(),releases=[PINNED])).encode())
    monkeypatch.setattr(storage,'connect_r2',lambda **_:client)
    monkeypatch.setattr(request,'urlopen',fetch_pins)
    assert archive_maintenance.main(['--spec',str(root/'model/jobs/maintenance.json'),'--plan'])==0
    maint_plan=json.loads(capsys.readouterr().out)
    assert maint_plan['status']=='planned' and maint_plan['executed'] is False
    assert set(maint_plan['tables'])==set(ALL_TABLE_NAMES)
    assert maint_plan['raw_verification']['captures']==json.loads(
        (root/'model/jobs/publish-model.json').read_text())['captures']
    assert maint_plan['raw_verification']['body_workers']==8
    releases=maint_plan['releases']
    assert releases['kept_releases']==[LIVE,PREVIOUS,PINNED]
    assert set(releases['delete_keys'])>={PREFIX+OLD+'/list.parquet',PREFIX+OLD+'/manifest.json'}
    assert releases['delete_bytes']==sum(len(store.objects[key]) for key in releases['delete_keys'])
    assert client.calls.count('list_objects_v2')==1
    assert set(client.calls)=={'get_object','list_objects_v2'}

    assert archive_backfill_job.main(['--spec',str(root/'model/jobs/backfill.json'),'--plan'])==0
    backfill_plan=json.loads(capsys.readouterr().out)
    assert backfill_plan['status']=='planned' and backfill_plan['executed'] is False
    # Canonical backfill includes the qualified committee and playlist readings;
    # expensive recording-byte acquisition remains a separate opt-in scope.
    assert set(backfill_plan['tables'])==set(ALL_TABLE_NAMES)|{'committee_records','playlist_records'}
    assert 'video_records' not in backfill_plan['tables']
    committed=archive_backfill_job.load_spec(root/'model/jobs/backfill.json')
    publisher=json.loads((root/'model/jobs/publish.json').read_text())['producers']
    assert {name:(Path(pin['path']).name,pin['sha256']) for name,pin in committed['producers'].items()}=={
        name:(Path(pin['path']).name,pin['sha256']) for name,pin in publisher.items()}


def test_a_daily_backfill_of_the_r2_lake_refuses_without_producer_anchors(tmp_path):
    from viewer_publication import archive_backfill_job
    root=Path(__file__).resolve().parents[3]
    value=json.loads((root/'model/jobs/backfill.json').read_text())
    del value['producers']
    spec=tmp_path/'backfill.json';spec.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='producer anchors'):archive_backfill_job.load_spec(spec)
    spec.write_text(json.dumps(dict(value,catalog_root=str(tmp_path/'catalog'))))
    assert 'producers' not in archive_backfill_job.load_spec(spec)


@pytest.mark.parametrize('entry',['load','plan','execute','selective','daily'])
@pytest.mark.parametrize('with_scope',[False,True])
def test_backfill_derived_opt_in_refuses_at_entry_before_effects(tmp_path,entry,with_scope):
    from congress_api.lake.compatible_versions import current_pins
    from viewer_publication import archive_backfill_job,archive_selective
    value=dict(derived_parsers=['html_metadata'],work=str(tmp_path/'must-not-exist'))
    if with_scope:
        value['derived_scopes']={'html_metadata':dict(captures=dict(metadata_location='/qualified.metadata.json',
            table_uuid='a'*32,snapshot=7,schema_id=0),versions=current_pins(),max_stored_bytes=1024,batch_size=1)}
    def forbidden(*args,**kwargs):raise AssertionError('Runtime/storage/producer opened before derived mode refusal')
    with pytest.raises(ValueError,match='Backfill derived passes are unsupported'):
        if entry=='load':
            path=tmp_path/'unsupported.json';path.write_text(json.dumps(value))
            archive_backfill_job.load_spec(path)
        elif entry=='plan':archive_backfill_job.plan(value)
        elif entry=='execute':archive_backfill_job.execute(value,runtime_factory=forbidden,storage_factory=forbidden,producer=forbidden)
        elif entry=='selective':archive_selective.execute_selective(value,runtime_factory=forbidden)
        else:archive_selective._daily(SimpleNamespace(spec=value,state={},raw_store=forbidden))
    assert not (tmp_path/'must-not-exist').exists()


def test_maintenance_execute_verifies_runtime_before_storage_access_and_backfill_reads_through_raw_store(tmp_path):
    from pathlib import Path
    from viewer_publication import archive_backfill_job,archive_maintenance
    from congress_api.lake.daily import ALL_TABLE_NAMES
    events=[]
    class FailingRuntime:
        def __enter__(self):return self
        def __exit__(self,*_):pass
        def verify_runtime(self):
            events.append('verify_runtime')
            raise ValueError('Runtime qualification failed')
    def never_storage(**_):
        events.append('storage')
        raise AssertionError('Storage must not be opened before engine verification')
    maint_spec=dict(
        version=1,
        bucket='archive-fixture',
        catalog_root=None,
        work=str(tmp_path/'maint-work'),
        external_pins=[],
        tables={name:dict(namespace=['archive'],name=name) for name in ALL_TABLE_NAMES},
        thresholds=dict(file_count=256,manifest_count=64,scan_planning_seconds=30.0),
        engine_config=str(tmp_path/'runtime.json'),
        lake_maintenance=dict(observations={}),
    )
    with pytest.raises(ValueError,match='Runtime qualification failed'):
        archive_maintenance.execute(maint_spec,runtime_factory=lambda _:FailingRuntime(),storage_factory=never_storage,now=NOW)
    assert events==['verify_runtime']

    # The backfill's daily spec names no body inventory: readings reads bodies through raw_store
    # (an empty inventory made every new body a pending read).
    class OkRuntime:
        def __enter__(self):return self
        def __exit__(self,*_):pass
        def verify_runtime(self):return dict(verified=True)
    from types import SimpleNamespace
    hooks=[]
    class BackfillR2:
        meta=SimpleNamespace(config=SimpleNamespace(retries={'total_max_attempts':1}),
            events=SimpleNamespace(register_first=lambda *a,**k:hooks.append(k.get('unique_id'))))
        def get_paginator(self,op):
            assert op=='list_objects_v2'
            history=dict(Key='provenance/verification/baseline.jsonl',Size=400<<20,ETag='"'+'a'*32+'"')
            return SimpleNamespace(paginate=lambda **_: [dict(Contents=[history],IsTruncated=False)])
    observed_daily={}
    anchor=tmp_path/'appearance_records.json';anchor.write_bytes(b'{"selector":{}}\n')
    def fake_producer(daily_spec,*,engine,raw_store,producer_records):
        observed_daily.update(daily_spec,producer_records=producer_records)
        assert 'body_inventory' not in daily_spec and 'local_root' not in daily_spec
        readings=dict(work_list=tmp_path/'work-list.parquet',batches=[dict(readings=tmp_path/'readings.parquet')])
        return dict(status='completed',pins={},producerreports=dict(readings=readings))
    backfill_spec=dict(
        version=1,
        bucket='archive-fixture',
        catalog_root=None,
        work=str(tmp_path/'backfill-work'),
        tables={name:dict(namespace=['archive'],name=name) for name in (*ALL_TABLE_NAMES,'committee_records','playlist_records')},
        batch_size=100,
        max_batches=2,
        engine_config=str(tmp_path/'runtime.json'),
        producers=dict(appearance_records=dict(path=str(anchor),sha256=hashlib.sha256(anchor.read_bytes()).hexdigest(),
            size=anchor.stat().st_size)),
    )
    spec_path=tmp_path/'backfill.json';spec_path.write_text(json.dumps(backfill_spec))
    report=archive_backfill_job.execute(
        archive_backfill_job.load_spec(spec_path),
        runtime_factory=lambda _:OkRuntime(),
        storage_factory=lambda **_:BackfillR2(),
        producer=fake_producer,
    )
    assert report['status']=='executed' and report['production']['status']=='completed'
    assert hooks==['r2-http-429']
    assert observed_daily['max_work_items']==200
    assert {'committee_records','playlist_records'}<=observed_daily['tables'].keys()
    assert observed_daily['producer_records'].anchors==dict(appearance_records=anchor.read_bytes())
    written=json.loads((tmp_path/'backfill-work/backfill-report.json').read_text())
    assert written['production']['producerreports']['readings']==dict(
        work_list=str(tmp_path/'work-list.parquet'),batches=[dict(readings=str(tmp_path/'readings.parquet'))])
    with pytest.raises(TypeError,match='set'):archive_backfill_job._dumps(dict(production={1}))


WRITE_CALL=re.compile('put|delete|copy|write|upload|create|complete|abort|restore',re.IGNORECASE)


class RecordingS3:
    """An S3 SDK fake over a fixture release store that records every operation it is asked for."""
    def __init__(self,store):
        self.store,self.calls,self.retry_hooks=store,[],[]
        self.meta=SimpleNamespace(config=SimpleNamespace(retries={'total_max_attempts':1}),
            events=SimpleNamespace(register_first=lambda *a,**k:self.retry_hooks.append(k['unique_id'])))
    def __getattr__(self,name):
        if name.startswith('_'):raise AttributeError(name)
        def operation(*args,**request):
            self.calls.append(name)
            handler=getattr(type(self),'_'+name,None)
            return handler(self,**request) if handler else {}
        return operation
    def _get_object(self,*,Bucket,Key,**_):
        from botocore.exceptions import ClientError
        body=json.dumps(self.store.live).encode() if Key==POINTER else self.store.objects.get(Key)
        if body is None:
            raise ClientError({'Error':{'Code':'NoSuchKey'},'ResponseMetadata':{'HTTPStatusCode':404}},'GetObject')
        etag=hashlib.md5(body).hexdigest() if Key.startswith(('bodies/','receipts/','provenance/')) else self.store.etag
        return dict(Body=io.BytesIO(body),ContentLength=len(body),ETag='"'+etag+'"')
    def _list_objects_v2(self,*,Bucket,Prefix,**_):
        keys=sorted(key for key in self.store.objects if key.startswith(Prefix))
        return dict(Contents=[dict(Key=key,LastModified=self.store.times[key],Size=len(self.store.objects[key]),
                                  ETag='"'+hashlib.md5(self.store.objects[key]).hexdigest()+'"')
                              for key in keys],IsTruncated=False)
    def get_paginator(self,operation):
        assert operation=='list_objects_v2'
        return SimpleNamespace(paginate=lambda **request:[self.list_objects_v2(**request)])
    def _put_object(self,*,ContentMD5=None,**_):
        md5=base64.b64decode(ContentMD5).hex() if ContentMD5 else 'd'*32
        return dict(ETag='"'+md5+'"')


def _maintenance_run(tmp_path,monkeypatch,*,execute,pin_old_during_verification=False):
    """One maintenance run whose raw verification is valid and whose lake policy asks for a rebuild and a purge."""
    import congress_api.lake.maintenance as lake
    import congress_api.retention.raw_verifier as raw_verifier
    from congress_api.lake.daily import ALL_TABLE_NAMES
    from viewer_publication import archive_maintenance
    store,_=fixture();client=RecordingS3(store);lake_calls=[]
    if pin_old_during_verification:
        add_input(store,OLD,'pinned-during-verification')
    pin_path=tmp_path/'archive-releases.json'
    def write_pins(releases):
        pin_path.write_text(json.dumps(dict(version=1,updated_at=NOW.isoformat(),releases=releases)))
    write_pins([PINNED])
    def staged_verification(source,*,work,checked_at,body_workers,**_):
        assert body_workers==8
        # Plant a write in a phase intended to read only. The underlying fake
        # accepts writes, so the attempt must fail before it reaches that client.
        with pytest.raises(PermissionError,match='put_object'):
            source.client.put_object(Bucket=source.bucket,Key='provenance/verification/fault.jsonl',Body=b'{}')
        work=Path(work);work.mkdir(parents=True)
        records=work/'verification.jsonl'
        records.write_text(json.dumps(dict(key='bodies/sha256/aa/'+'a'*64+'.gz',sha256_verified=True))+'\n')
        report=dict(valid=True,listed=1,checked=1,accepted_records=1,
            records_sha256=hashlib.sha256(records.read_bytes()).hexdigest(),
            provenance_key='provenance/verification/20261028T120000Z-fixture.jsonl')
        (work/'report.json').write_text(json.dumps(report))
        if pin_old_during_verification:
            write_pins([PINNED,OLD])
        return report
    monkeypatch.setattr(raw_verifier,'verify',staged_verification)
    monkeypatch.setattr(lake,'rebuild_generation',lambda *a,**k:lake_calls.append('rebuild') or {})
    monkeypatch.setattr(lake,'purge_generation',lambda *a,**k:lake_calls.append('purge') or {})
    inputs=tmp_path/'inputs';inputs.mkdir()
    (inputs/'captures.parquet').write_bytes(b'not read: verification is staged')
    for name in ('receipt-inventory.json','verification-inventory.json'):(inputs/name).write_text('[]')
    class OkRuntime:
        def __enter__(self):return self
        def __exit__(self,*_):pass
        def verify_runtime(self):return dict(verified=True)
    spec=dict(version=1,bucket='archive-fixture',catalog_root=None,work=str(tmp_path/'work'),external_pins=[],
        external_pins_source=str(pin_path),
        tables={name:dict(namespace=['archive'],name=name) for name in ALL_TABLE_NAMES},
        thresholds=dict(file_count=256,manifest_count=64,scan_planning_seconds=30.0),
        engine_config=str(tmp_path/'runtime.json'),
        raw_verification=dict(captures=str(inputs/'captures.parquet'),
            receipt_inventory=str(inputs/'receipt-inventory.json'),
            verification_inventory=str(inputs/'verification-inventory.json'),apply_staged=True,body_workers=8),
        lake_maintenance=dict(observations=dict(captures=dict(file_count=999,manifest_count=0,scan_planning_seconds=0)),
            rebuild=dict(captures=dict(old_pin={},schema={},location='s3://fixture/new',keys=['k'],definition={})),
            purge=[dict(table='captures',pin={})]))
    path=tmp_path/'maintenance.json';path.write_text(json.dumps(spec))
    result=archive_maintenance.execute(path,runtime_factory=lambda _:OkRuntime(),
        storage_factory=lambda **_:client,now=NOW,execute=execute)
    return result,client,store,lake_calls


def test_a_dry_run_makes_no_storage_or_lake_writes(tmp_path,monkeypatch):
    result,client,store,lake_calls=_maintenance_run(tmp_path,monkeypatch,execute=False)
    assert [call for call in client.calls if WRITE_CALL.search(call)]==[]
    assert lake_calls==[] and store.deleted==[]
    assert result['executed'] is False and result['status']=='dry_run'
    assert result['releases']['delete_keys']==[PREFIX+OLD+'/list.parquet',PREFIX+OLD+'/manifest.json']
    assert result['raw_verification']['applied'] is None
    assert client.retry_hooks==['r2-http-429']


def test_an_executed_run_applies_verification_and_deletes_through_the_same_client(tmp_path,monkeypatch):
    result,client,_,lake_calls=_maintenance_run(tmp_path,monkeypatch,execute=True)
    writes=[call for call in client.calls if WRITE_CALL.search(call)]
    assert writes.count('put_object')==2 and writes.count('delete_object')==2
    assert lake_calls==['rebuild','purge'] and result['executed'] is True
    assert result['raw_verification']['applied']['provenance']=='provenance/verification/20261028T120000Z-fixture.jsonl'


def test_execute_keeps_release_pinned_during_raw_verification(tmp_path,monkeypatch):
    result,client,_,_=_maintenance_run(tmp_path,monkeypatch,execute=True,pin_old_during_verification=True)
    assert OLD in result['releases']['kept_releases']
    assert result['releases']['pointer']==dict(release_id=LIVE,previous_release_id=PREVIOUS)
    assert result['releases']['delete_keys']==[] and 'delete_object' not in client.calls


def test_cli_dry_run_stages_bucket_receipts_and_verification_for_native_checks(tmp_path,monkeypatch,capsys):
    import pyarrow as pa
    import pyarrow.parquet as pq
    from congress_shared import storage
    from viewer_publication import archive_maintenance

    store,_=fixture()
    data=b'archive body'
    digest=hashlib.sha256(data).hexdigest()
    body_key=f'bodies/sha256/{digest[:2]}/{digest}'
    receipt_key='receipts/documents/2026-10-27/run.jsonl.gz'
    verification_key='provenance/verification/previous.jsonl'
    store.create(body_key,data)
    receipt=dict(captures=[dict(body_key=body_key,stored_bytes=len(data))])
    store.create(receipt_key,gzip.compress((json.dumps(receipt)+'\n').encode()))
    verification=dict(key=body_key,size=len(data),etag=hashlib.md5(data).hexdigest(),sha256_verified=True,
        stored_sha256=digest,checked_at=NOW.isoformat(),job='raw-verifier')
    store.create(verification_key,(json.dumps(verification)+'\n').encode())
    store.create('provenance/recovery/irrelevant.jsonl',b'invalid')
    client=RecordingS3(store)
    monkeypatch.setattr(storage,'connect_r2',lambda **_:client)

    captures=tmp_path/'captures.parquet'
    pq.write_table(pa.table({'body_key':pa.array([],type=pa.string())}),captures)
    root=Path(__file__).resolve().parents[3]
    spec=json.loads((root/'model/jobs/maintenance.json').read_text())
    spec.pop('external_pins_source')
    work=tmp_path/'run'
    spec.update(work=str(work),engine_config=os.environ['DOCSPEC_JOB_CONFIG'],external_pins=[PINNED],
        raw_verification=dict(captures=str(captures),body_workers=8))
    spec_path=tmp_path/'maintenance.json'
    spec_path.write_text(json.dumps(spec))
    assert archive_maintenance.main(['--spec',str(spec_path),'--dry-run'])==0
    report=json.loads(capsys.readouterr().out)
    assert report['status']=='dry_run' and report['raw_verification']['verification']['valid']
    assert report['raw_verification']['verification']['listed']==1
    assert report['raw_verification']['applied'] is None
    assert set(client.calls)=={'get_object','list_objects_v2'}
    [baseline]=pq.read_table(work/'raw-verify/baseline.parquet').to_pylist()
    assert baseline['key']==body_key and baseline['has_capture'] and baseline['has_verification']
    inputs=work/'raw-verification-inputs'
    for name,key in [('receipt',receipt_key),('verification',verification_key)]:
        [row]=json.loads((inputs/(name+'-inventory.json')).read_text())
        assert row['key']==key and Path(row['path']).read_bytes()==store.objects[key]


def test_maintenance_can_stage_a_verifier_baseline_above_the_unreadable_file_limit(tmp_path):
    from congress_api.retention.provenance_inventory import MAX_OBJECT_BYTES
    from viewer_publication.archive_maintenance import ReadOnlyClient,_stage_raw_inventories

    store=Store()
    key='provenance/verification/baseline.jsonl'
    line=b'{"key":"bodies/sha256/aa/'+b'a'*64+b'","sha256_verified":false}\n'
    data=line*(MAX_OBJECT_BYTES//len(line)+1)
    store.create(key,data)
    client=RecordingS3(store)
    receipts,[baseline]=_stage_raw_inventories(ReadOnlyClient(client),'archive-fixture',tmp_path)
    assert receipts==[] and baseline['key']==key
    assert Path(baseline['path']).stat().st_size==len(data)
    assert set(client.calls)=={'get_object','list_objects_v2'}


@pytest.mark.parametrize('workers',[False,0,33,8.0,'8'])
def test_maintenance_spec_rejects_invalid_raw_body_worker_count(tmp_path,workers):
    from viewer_publication.archive_maintenance import load_spec

    root=Path(__file__).resolve().parents[3]
    spec=json.loads((root/'model/jobs/maintenance.json').read_text())
    spec['raw_verification'].update(captures='captures.parquet',body_workers=workers)
    path=tmp_path/'maintenance.json'
    path.write_text(json.dumps(spec))
    with pytest.raises(ValueError,match='body_workers'):
        load_spec(path)
