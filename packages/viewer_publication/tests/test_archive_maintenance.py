"""Derived retention validates kept evidence and never addresses raw objects."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
from uuid import NAMESPACE_URL,uuid5

import pytest

from viewer_publication.archive_publish import input_digest
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
