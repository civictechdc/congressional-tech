"""Controller expectations: native create-only assets and one guarded pointer flip."""
from copy import deepcopy
from hashlib import md5,sha256
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from viewer_publication.archive_publish import NativeArchiveStore,input_digest,publish_candidate,read_pointer,matching_live_input
from viewer_publication.archive_format import release_identity


def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()


class StorageError(RuntimeError):
    def __init__(self,status):
        self.response={'ResponseMetadata':{'HTTPStatusCode':status},'Error':{'Code':str(status)}}
        super().__init__('storage refused')


class Store:
    def __init__(self):
        self.objects={};self.events=[];self.etag='initial';self.pointer_gets=0;self.requests=[]
        self.meta=SimpleNamespace(config=SimpleNamespace(retries={'total_max_attempts':1}))
    def get_object(self,*,Bucket,Key):
        self.events.append(('get',Key))
        if Key=='viewer-publications/manifest.json':self.pointer_gets+=1
        if Key not in self.objects:raise StorageError(404)
        body=self.objects[Key]
        return dict(Body=BytesIO(body),ContentLength=len(body),ETag=self.etag)
    def put_object(self,**request):
        key=request['Key'];self.events.append(('put',key));self.requests.append(request)
        if key=='viewer-publications/manifest.json':
            if request.get('IfMatch') is not None and request['IfMatch']!=self.etag:raise StorageError(412)
            if request.get('IfNoneMatch')=='*' and key in self.objects:raise StorageError(412)
            self.etag='next-etag'
        self.objects[key]=bytes(request['Body'])
        return dict(ETag=self.etag)
    def list_objects_v2(self,*,Bucket,Prefix,**kwargs):
        return dict(Contents=[dict(Key=key) for key in sorted(self.objects) if key.startswith(Prefix)],IsTruncated=False)


class Native:
    remote='explicit-remote-configuration'
    def __init__(self,store):self.store=store;self.calls=[];self.refuse=None
    def create_file(self,spec):
        spec=json.loads(Path(spec).read_text());self.calls.append(spec)
        if self.refuse:raise StorageError(self.refuse)
        key=spec['destination'].split('/',3)[3];data=Path(spec['source']).read_bytes()
        assert sha256(data).hexdigest()==spec['sha256'] and md5(data).hexdigest()==spec['md5'] and len(data)==spec['size']
        self.store.events.append(('native',key))
        result='already_exists' if key in self.store.objects else 'created'
        if result=='created':self.store.objects[key]=data
        return dict(result=result,**{key:spec[key] for key in ['destination','sha256','md5','size']})


def record(**changes):
    value=dict(profile={'sql':'first','parser':'pinned'},provenance=[dict(key='provenance/reviews/fixture.jsonl',etag='review-etag')],
        entity_digests={},snapshots={'captures':{'snapshot':1}},run={'id':'fixture-run'})
    value.update(changes)
    keys=['receipts/documents/2026-10-20/fixture.jsonl.gz']
    value['input_digest']=input_digest(receipt_keys=keys,**{key:value[key] for key in ['provenance','profile','entity_digests']})
    return value,keys


def pin(path):
    body=path.read_bytes();return dict(path=str(path),sha256=sha256(body).hexdigest(),size=len(body))


def candidate(root,*,payload=b'qualified export bytes',rows=1):
    """Authored transport fixture with real hashes, not a reader qualification."""
    output=root/'release';output.mkdir(parents=True)
    (output/'list.parquet').write_bytes(payload)
    entry=dict(name='list.parquet',sha256=sha256(payload).hexdigest(),md5=md5(payload).hexdigest(),size=len(payload),rows=rows)
    release_id=release_identity(1,[entry])
    manifest=dict(schema_version=1,files=[entry],facet_counts=[],release_id=release_id)
    path=output/'manifest.json';path.write_bytes(encoded(manifest))
    result=root/'result.json'
    result.write_bytes(encoded(dict(outputs=[entry],queries=[dict(name=name,data=[dict(violation=0)])
        for name in ['invariants','model_invariants','url_state_invariants','profile_completeness']])))
    return dict(release=output,manifest_pin=pin(path),result_pin=pin(result)),manifest


def launch(root,*,store=None,native=None,input_record=None,artifacts=None,canary=None,contract=None):
    store=store or Store();native=native or Native(store)
    default,keys=record();input_record=input_record or default
    if artifacts is None:artifacts,_=candidate(root)
    pointer,etag=read_pointer(store,bucket='derived-fixture')
    def passed(**context):return dict(status='passed',releaseId=context['release_id'],targets='measured')
    result=publish_candidate(client=store,engine=native,bucket='derived-fixture',work=root/'publish',
        **artifacts,input_record=input_record,receipt_keys=keys,pointer=pointer,expected_etag=etag,
        public_origin='https://archive.example.test',canary=canary or passed,contract=contract or passed)
    return result,store,native


def test_input_identity_excludes_run_and_snapshot_metadata():
    first,_=record();second,_=record(run={'id':'another'},snapshots={'captures':{'snapshot':99}})
    assert first['input_digest']==second['input_digest']
    third,_=record(profile={'sql':'new','parser':'pinned'})
    assert first['input_digest']!=third['input_digest']
    with pytest.raises(ValueError,match='phase one'):record(entity_digests={'members':'not-phase-one'})


def test_receipts_then_input_contract_upload_canary_and_single_flip(tmp_path):
    store=Store()
    def contract(**context):store.events.append(('contract',context['release_id']));return dict(status='passed',releaseId=context['release_id'],targets='measured')
    def canary(**context):
        assert context['public_origin'].startswith('https://')
        release=context['release_id'];assert 'viewer-publications/releases/'+release+'/manifest.json' in store.objects
        store.events.append(('canary',release));return dict(status='passed',releaseId=release,targets='measured')
    result,store,native=launch(tmp_path/'run',store=store,contract=contract,canary=canary)
    release=result['release_id'];assert result['status']=='published' and store.pointer_gets==1
    assert json.loads(store.objects['viewer-publications/manifest.json'])==dict(release_id=release,previous_release_id=None)
    keys=[key for action,key in store.events if action=='native']
    assert '/inputs/receipts/' in keys[0] and keys[1].endswith('/inputs/'+result['input_digest']+'.json')
    assert keys[-1].endswith('/manifest.json')
    assert store.events.index(('contract',release))<next(i for i,event in enumerate(store.events) if event[0]=='native')
    assert store.events.count(('contract',release))==1
    assert store.events.index(('canary',release))<store.events.index(('put','viewer-publications/manifest.json'))
    assert json.loads(store.objects['viewer-publications/status.json'])['status']=='published'
    assert all(call['destination'].startswith('s3://derived-fixture/viewer-publications/releases/') for call in native.calls)


def test_exact_live_input_lookup_reuses_retained_receipt_keys(tmp_path):
    from viewer_publication.receipt_pins import kept_receipt_keys
    first,store,native=launch(tmp_path/'first')
    reader=NativeArchiveStore(client=store,engine=native,bucket='derived-fixture',work=tmp_path/'reader')
    found=matching_live_input(reader,release_id=first['release_id'],digest=first['input_digest'])
    assert found['input_digest']==first['input_digest'] and found['snapshots']=={'captures':{'snapshot':1}}
    assert matching_live_input(reader,release_id=first['release_id'],digest='f'*64) is None
    assert len(kept_receipt_keys(reader,[first['release_id']]))==2


def test_same_content_new_input_records_identity_without_gates_or_flip(tmp_path):
    first,store,native=launch(tmp_path/'first');changed,_=record(profile={'sql':'new','parser':'pinned'})
    before=len([event for event in store.events if event==('put','viewer-publications/manifest.json')])
    def never(**kwargs):pytest.fail('unchanged content must not run gates')
    second,_,_=launch(tmp_path/'second',store=store,native=native,input_record=changed,contract=never,canary=never)
    assert second['status']=='release_unchanged' and first['release_id']==second['release_id']
    assert len([event for event in store.events if event==('put','viewer-publications/manifest.json')])==before
    assert len([key for key in store.objects if '/inputs/' in key and key.endswith('.json')])==2


def test_failed_native_completeness_and_empty_list_refuse_before_upload(tmp_path):
    for name,empty in [('failed',False),('empty',True)]:
        work=tmp_path/name;artifacts,_=candidate(work,rows=0 if empty else 1)
        if not empty:
            result=Path(artifacts['result_pin']['path']);value=json.loads(result.read_text());value['queries'][-1]['data']=[dict(missing_readings=1)]
            result.write_bytes(encoded(value));artifacts['result_pin']=pin(result)
        store=Store();native=Native(store)
        with pytest.raises(ValueError,match='empty|did not pass'):launch(work,store=store,native=native,artifacts=artifacts)
        assert native.calls==[] and 'viewer-publications/manifest.json' not in store.objects
        assert json.loads(store.objects['viewer-publications/status.json'])['status']=='failed'


def test_changed_native_result_and_mismatched_manifest_facts_refuse(tmp_path):
    artifacts,_=candidate(tmp_path/'run');Path(artifacts['result_pin']['path']).write_bytes(b'changed')
    store=Store();native=Native(store)
    with pytest.raises(ValueError,match='artifact changed'):launch(tmp_path/'run',store=store,native=native,artifacts=artifacts)
    assert native.calls==[]
    other,_=candidate(tmp_path/'other');result=Path(other['result_pin']['path']);value=json.loads(result.read_text());value['outputs'][0]['size']+=1
    result.write_bytes(encoded(value));other['result_pin']=pin(result)
    with pytest.raises(ValueError,match='native export'):launch(tmp_path/'other',artifacts=other)


def test_input_412_requires_exact_physical_and_run_record_readback(tmp_path):
    reference,manifest=candidate(tmp_path/'reference');entry,_=record()
    store=Store();native=Native(store)
    key='viewer-publications/releases/'+manifest['release_id']+'/inputs/'+entry['input_digest']+'.json'
    store.objects[key]=b'{"different_physical_or_run_fields":true}'
    with pytest.raises(ValueError,match='input record differs'):launch(tmp_path/'run',store=store,native=native)
    assert ('get',key) in store.events and 'viewer-publications/manifest.json' not in store.objects


def test_native_409_is_not_a_412_success(tmp_path):
    store=Store();native=Native(store);native.refuse=409
    with pytest.raises(StorageError):launch(tmp_path/'run',store=store,native=native)
    assert len(native.calls)==1 and 'viewer-publications/manifest.json' not in store.objects
    assert json.loads(store.objects['viewer-publications/status.json'])['status']=='failed'


def test_failed_canary_and_lost_pointer_race_do_not_replace_live(tmp_path):
    first,store,native=launch(tmp_path/'first');changed,_=record(profile={'sql':'new','parser':'pinned'})
    artifacts,_=candidate(tmp_path/'failed',payload=b'new export bytes')
    def failed(**context):return dict(status='failed',releaseId=context['release_id'],targets='measured')
    with pytest.raises(ValueError,match='canary'):launch(tmp_path/'failed',store=store,native=native,input_record=changed,artifacts=artifacts,canary=failed)
    assert json.loads(store.objects['viewer-publications/manifest.json'])['release_id']==first['release_id']
    changed,_=record(profile={'sql':'another','parser':'pinned'});artifacts,_=candidate(tmp_path/'race',payload=b'new export bytes')
    def race(**context):
        store.objects['viewer-publications/manifest.json']=encoded(dict(release_id='c'*64,previous_release_id=first['release_id']));store.etag='competing'
        return dict(status='passed',releaseId=context['release_id'],targets='measured')
    with pytest.raises(StorageError):launch(tmp_path/'race',store=store,native=native,input_record=changed,artifacts=artifacts,canary=race)
    assert json.loads(store.objects['viewer-publications/manifest.json'])['release_id']=='c'*64


def test_raw_prefix_and_sdk_retry_refuse_before_effects(tmp_path):
    store=Store();native=Native(store);adapter=NativeArchiveStore(client=store,engine=native,bucket='derived-fixture',work=tmp_path/'adapter')
    source=tmp_path/'body';source.write_bytes(b'evidence')
    for key in ['receipts/unsafe','viewer-publications/releases/'+('a'*64)+'/%2e%2e/receipt']:
        with pytest.raises(ValueError,match='release prefix'):
            adapter.upload_file(key,source,dict(sha256=sha256(b'evidence').hexdigest(),md5=md5(b'evidence').hexdigest(),size=8),content_type='application/octet-stream')
    assert native.calls==[] and store.events==[]
    store.meta.config.retries={'total_max_attempts':2}
    with pytest.raises(ValueError,match='retries'):read_pointer(store,bucket='derived-fixture')
    assert store.events==[]


def test_local_contract_refuses_before_any_release_or_input_upload(tmp_path):
    store=Store();native=Native(store)
    def refused(**context):return dict(status='failed',releaseId=context['release_id'],targets='measured')
    with pytest.raises(ValueError,match='contract'):
        launch(tmp_path/'run',store=store,native=native,contract=refused)
    assert native.calls==[] and 'viewer-publications/manifest.json' not in store.objects
    assert [key for action,key in store.events if action=='put']==['viewer-publications/status.json']
    assert json.loads(store.objects['viewer-publications/status.json'])['status']=='failed'


def test_status_is_conditional_and_failure_keeps_the_original_refusal(tmp_path):
    _,store,native=launch(tmp_path/'first')
    writes=[request for request in store.requests if request['Key']=='viewer-publications/status.json']
    assert writes[-1].get('IfNoneMatch')=='*'
    changed,_=record(profile={'sql':'new','parser':'pinned'})
    launch(tmp_path/'second',store=store,native=native,input_record=changed)
    writes=[request for request in store.requests if request['Key']=='viewer-publications/status.json']
    assert writes[-1].get('IfMatch') and 'IfNoneMatch' not in writes[-1]
    class StatusRefusal(Store):
        def put_object(self,**request):
            if request['Key']=='viewer-publications/status.json':raise StorageError(503)
            return super().put_object(**request)
    failed=StatusRefusal()
    def refused(**context):return dict(status='failed',releaseId=context['release_id'],targets='measured')
    with pytest.raises(ValueError,match='contract') as error:
        launch(tmp_path/'failed',store=failed,contract=refused)
    assert 'Archive status update also failed' in error.value.__notes__
    assert 'viewer-publications/manifest.json' not in failed.objects


def test_wrong_content_release_identity_refuses_before_upload(tmp_path):
    artifacts,_=candidate(tmp_path/'run')
    manifest=Path(artifacts['manifest_pin']['path']);value=json.loads(manifest.read_text())
    value['release_id']='a'*64;manifest.write_bytes(encoded(value));artifacts['manifest_pin']=pin(manifest)
    store=Store();native=Native(store)
    with pytest.raises(ValueError,match='release identity'):
        launch(tmp_path/'run',store=store,native=native,artifacts=artifacts)
    assert native.calls==[] and 'viewer-publications/manifest.json' not in store.objects


def test_generator_receipt_keys_keep_replay_evidence(tmp_path):
    artifacts,manifest=candidate(tmp_path/'run');entry,keys=record();store=Store();native=Native(store)
    def passed(**context):return dict(status='passed',releaseId=context['release_id'],targets='measured')
    result=publish_candidate(client=store,engine=native,bucket='derived-fixture',work=tmp_path/'publish',
        **artifacts,input_record=entry,receipt_keys=(key for key in keys),pointer=None,expected_etag=None,
        public_origin='https://archive.example.test',contract=passed,canary=passed)
    reader=NativeArchiveStore(client=store,engine=native,bucket='derived-fixture',work=tmp_path/'reader')
    assert matching_live_input(reader,release_id=manifest['release_id'],digest=result['input_digest']) is not None


@pytest.mark.parametrize('ack',[None,{},dict(ETag='')])
def test_missing_pointer_acknowledgement_never_claims_publication(tmp_path,ack):
    class NoPointerAck(Store):
        def put_object(self,**request):
            result=super().put_object(**request)
            return ack if request['Key']=='viewer-publications/manifest.json' else result
    store=NoPointerAck()
    with pytest.raises(ValueError,match='acknowledged.*ETag'):
        launch(tmp_path/'run',store=store)
    report=json.loads(store.objects['viewer-publications/status.json'])
    assert report['status']=='failed' and report['live_release_basis']=='unacknowledged_pointer_write'
