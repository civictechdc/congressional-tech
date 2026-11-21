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
        from botocore.hooks import HierarchicalEmitter
        self.meta=SimpleNamespace(config=SimpleNamespace(retries={'total_max_attempts':1}),events=HierarchicalEmitter())
    def get_object(self,*,Bucket,Key):
        self.events.append(('get',Key))
        if Key=='viewer-publications/manifest.json':self.pointer_gets+=1
        if Key not in self.objects:raise StorageError(404)
        body=self.objects[Key]
        return dict(Body=BytesIO(body),ContentLength=len(body),ETag=self.etag)
    def head_object(self,*,Bucket,Key):
        self.events.append(('head',Key))
        if Key not in self.objects:raise StorageError(404)
        raw=self.objects[Key]
        return dict(ContentLength=len(raw),ETag=md5(raw).hexdigest())
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


@pytest.fixture(autouse=True)
def transport_gates(request,monkeypatch):
    """These transport fixtures publish opaque bytes, so gates 1 and 2 are recorded, not run;
    test_release_gate_* below run the real gates through this same publish path."""
    calls=[]
    if 'real_gates' not in request.fixturenames:
        import viewer_publication.archive_publish as module
        monkeypatch.setattr(module,'require_release_gates',lambda *a,**k:calls.append((a,k)))
    return calls


@pytest.fixture
def real_gates():return True


def launch(root,*,store=None,native=None,input_record=None,artifacts=None,canary=None,contract=None,release_causes=None):
    store=store or Store();native=native or Native(store)
    default,keys=record();input_record=input_record or default
    if artifacts is None:artifacts,_=candidate(root)
    pointer,etag=read_pointer(store,bucket='derived-fixture')
    def passed(**context):return dict(status='passed',releaseId=context['release_id'],targets='owner-approved')
    result=publish_candidate(client=store,engine=native,bucket='derived-fixture',work=root/'publish',
        **artifacts,input_record=input_record,receipt_keys=keys,pointer=pointer,expected_etag=etag,
        public_origin='https://archive.example.test',canary=canary or passed,contract=contract or passed,
        base_release=root/'base-release' if pointer else None,release_causes=release_causes,
        first_release=pointer is None)  # an empty store: the explicit, recorded bootstrap
    return result,store,native


def test_input_identity_excludes_run_and_snapshot_metadata():
    first,_=record();second,_=record(run={'id':'another'},snapshots={'captures':{'snapshot':99}})
    assert first['input_digest']==second['input_digest']
    third,_=record(profile={'sql':'new','parser':'pinned'})
    assert first['input_digest']!=third['input_digest']
    with pytest.raises(ValueError,match='phase one'):record(entity_digests={'members':'not-phase-one'})


def test_receipts_then_input_contract_upload_canary_and_single_flip(tmp_path):
    store=Store()
    def contract(**context):store.events.append(('contract',context['release_id']));return dict(status='passed',releaseId=context['release_id'],targets='owner-approved')
    def canary(**context):
        assert context['public_origin'].startswith('https://')
        release=context['release_id'];assert 'viewer-publications/releases/'+release+'/manifest.json' in store.objects
        store.events.append(('canary',release));return dict(status='passed',releaseId=release,targets='owner-approved')
    result,store,native=launch(tmp_path/'run',store=store,contract=contract,canary=canary)
    release=result['release_id'];assert result['status']=='published' and store.pointer_gets==1
    published=json.loads(store.objects['viewer-publications/manifest.json'])
    assert {key:published[key] for key in ('release_id','previous_release_id')}==dict(release_id=release,previous_release_id=None)
    assert published['published_at'].endswith('Z')
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
    def failed(**context):return dict(status='failed',releaseId=context['release_id'],targets='owner-approved')
    with pytest.raises(ValueError,match='canary'):launch(tmp_path/'failed',store=store,native=native,input_record=changed,artifacts=artifacts,canary=failed)
    assert json.loads(store.objects['viewer-publications/manifest.json'])['release_id']==first['release_id']
    changed,_=record(profile={'sql':'another','parser':'pinned'});artifacts,_=candidate(tmp_path/'race',payload=b'new export bytes')
    def race(**context):
        store.objects['viewer-publications/manifest.json']=encoded(dict(release_id='c'*64,previous_release_id=first['release_id']));store.etag='competing'
        return dict(status='passed',releaseId=context['release_id'],targets='owner-approved')
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
    def refused(**context):return dict(status='failed',releaseId=context['release_id'],targets='owner-approved')
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
    def refused(**context):return dict(status='failed',releaseId=context['release_id'],targets='owner-approved')
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


@pytest.mark.parametrize('origin,message',[(dict(kind='converted_catalog',gaps=[]),'converted catalog'),
    (dict(kind='seed_v5',gaps=[]),'seed profile'),(dict(kind='model',gaps=[],display_only=True),'seed profile')])
def test_non_model_origins_refuse_before_upload(tmp_path,origin,message):
    artifacts,_=candidate(tmp_path/'run')
    manifest=Path(artifacts['manifest_pin']['path']);value=json.loads(manifest.read_text())
    value['origin']=origin;manifest.write_bytes(encoded(value));artifacts['manifest_pin']=pin(manifest)
    store=Store();native=Native(store)
    with pytest.raises(ValueError,match=message):
        launch(tmp_path/'run',store=store,native=native,artifacts=artifacts)
    assert native.calls==[] and 'viewer-publications/manifest.json' not in store.objects


def test_generator_receipt_keys_keep_replay_evidence(tmp_path):
    artifacts,manifest=candidate(tmp_path/'run');entry,keys=record();store=Store();native=Native(store)
    def passed(**context):return dict(status='passed',releaseId=context['release_id'],targets='owner-approved')
    result=publish_candidate(client=store,engine=native,bucket='derived-fixture',work=tmp_path/'publish',
        **artifacts,input_record=entry,receipt_keys=(key for key in keys),pointer=None,expected_etag=None,
        public_origin='https://archive.example.test',contract=passed,canary=passed,first_release=True)
    reader=NativeArchiveStore(client=store,engine=native,bucket='derived-fixture',work=tmp_path/'reader')
    assert matching_live_input(reader,release_id=manifest['release_id'],digest=result['input_digest']) is not None


@pytest.mark.parametrize('ack',[None,{},dict(ETag='')])
def test_missing_pointer_acknowledgement_requires_exact_readback(tmp_path,ack):
    class NoPointerAck(Store):
        def put_object(self,**request):
            result=super().put_object(**request)
            return ack if request['Key']=='viewer-publications/manifest.json' else result
    store=NoPointerAck()
    result,store,_=launch(tmp_path/'run',store=store)
    report=json.loads(store.objects['viewer-publications/status.json'])
    assert result['status']=='published'
    assert report['live_release_basis']=='selected_pointer_reconciled'
    assert store.pointer_gets==2


@pytest.mark.parametrize('unchanged',[False,True])
@pytest.mark.parametrize('matching',[False,True])
def test_raw_measured_candidate_identity_precedes_upload_or_pointer_effects(tmp_path,unchanged,matching):
    artifacts,manifest=candidate(tmp_path);value,keys=record();store=Store();native=Native(store)
    def passed(**context):
        assert matching
        return dict(status='passed',releaseId=context['release_id'],targets='owner-approved')
    def publish():
        return publish_candidate(client=store,engine=native,bucket='derived-fixture',work=tmp_path/'publish',
            **artifacts,input_record=value,receipt_keys=keys,
            pointer={'release_id':manifest['release_id']} if unchanged else None,
            expected_etag='outgoing' if unchanged else None,public_origin='https://archive.example.test',
            contract=passed,canary=passed,first_release=not unchanged,
            measured_release_id=manifest['release_id'] if matching else 'ab'*32)
    if matching:
        result=publish()
        assert result['status']==('release_unchanged' if unchanged else 'published')
    else:
        with pytest.raises(ValueError,match='Measured.*release'):publish()
        assert native.calls==[]
        assert not any('/inputs/' in key or key.endswith('/manifest.json') for key in store.objects)


def test_publisher_reports_pointer_readback_after_lost_acknowledgment(tmp_path):
    class LostPointerAck(Store):
        def put_object(self,**request):
            result=super().put_object(**request)
            if request['Key']=='viewer-publications/manifest.json':
                raise OSError('lost acknowledgment')
            return result
    store=LostPointerAck()
    result,store,_=launch(tmp_path/'run',store=store)
    assert result['status']=='published'
    assert result['live_release_basis']=='selected_pointer_reconciled'
    assert store.pointer_gets==2
    assert len([r for r in store.requests if r['Key']=='viewer-publications/manifest.json'])==1
    report=json.loads(store.objects['viewer-publications/status.json'])
    assert report['live_release_basis']=='selected_pointer_reconciled'


def test_asset_journal_reuses_acknowledged_transfer_without_payload_reads(tmp_path,monkeypatch):
    payload=b'one qualified release asset';source=tmp_path/'asset.parquet';source.write_bytes(payload)
    facts=dict(sha256=sha256(payload).hexdigest(),md5=md5(payload).hexdigest(),size=len(payload))
    key='viewer-publications/releases/'+'a'*64+'/list.parquet';store=Store();native=Native(store)
    journal=tmp_path/'asset-journal.json'
    def adapter(name):return NativeArchiveStore(client=store,engine=native,bucket='derived-fixture',work=tmp_path/name,asset_journal=journal)
    adapter('first').upload_file(key,source,facts,content_type='application/vnd.apache.parquet')
    assert len(native.calls)==1
    original=Path.open
    def no_payload_read(path,*args,**kwargs):
        if path==source:raise AssertionError('Acknowledged payload reopened')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',no_payload_read)
    assert adapter('fresh-process-files').upload_file(key,source,facts,content_type='application/vnd.apache.parquet')=='already_exists'
    assert len(native.calls)==1 and ('head',key) in store.events


@pytest.mark.parametrize('damage',['local','remote'])
def test_asset_journal_refuses_changed_identity_before_retransfer(tmp_path,monkeypatch,damage):
    payload=b'original';source=tmp_path/'asset.parquet';source.write_bytes(payload)
    facts=dict(sha256=sha256(payload).hexdigest(),md5=md5(payload).hexdigest(),size=len(payload))
    key='viewer-publications/releases/'+'a'*64+'/list.parquet';store=Store();native=Native(store)
    journal=tmp_path/'asset-journal.json'
    options=dict(client=store,engine=native,bucket='derived-fixture',asset_journal=journal)
    NativeArchiveStore(work=tmp_path/'first',**options).upload_file(key,source,facts,content_type='application/vnd.apache.parquet')
    if damage=='local':source.write_bytes(b'changed!')
    else:store.objects[key]=b'changed!'
    original=Path.open
    def no_payload_read(path,*args,**kwargs):
        if path==source:raise AssertionError('Changed payload opened')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',no_payload_read)
    with pytest.raises(ValueError,match='asset.*changed|asset identity changed'):
        NativeArchiveStore(work=tmp_path/'resume',**options).upload_file(key,source,facts,content_type='application/vnd.apache.parquet')
    assert len(native.calls)==1


def test_asset_journal_reconciles_unknown_native_acknowledgment_by_head(tmp_path,monkeypatch):
    payload=b'qualified';source=tmp_path/'asset.parquet';source.write_bytes(payload)
    facts=dict(sha256=sha256(payload).hexdigest(),md5=md5(payload).hexdigest(),size=len(payload))
    key='viewer-publications/releases/'+'a'*64+'/list.parquet';store=Store()
    class LostAck(Native):
        def create_file(self,spec):
            super().create_file(spec)
            raise RuntimeError('lost native acknowledgment')
    native=LostAck(store);journal=tmp_path/'asset-journal.json'
    options=dict(client=store,engine=native,bucket='derived-fixture',asset_journal=journal)
    with pytest.raises(RuntimeError,match='lost native'):
        NativeArchiveStore(work=tmp_path/'first',**options).upload_file(key,source,facts,content_type='application/vnd.apache.parquet')
    assert json.loads(journal.read_text())['assets'][key]['phase']=='started'
    original=Path.open
    def no_payload_read(path,*args,**kwargs):
        if path==source:raise AssertionError('Uncertain acknowledged payload reopened')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',no_payload_read)
    NativeArchiveStore(work=tmp_path/'resume',**options).upload_file(key,source,facts,content_type='application/vnd.apache.parquet')
    assert len(native.calls)==1 and json.loads(journal.read_text())['assets'][key]['phase']=='acknowledged'


def test_release_manifest_is_visible_only_after_complete_atomic_write(tmp_path,monkeypatch):
    from viewer_publication.archive_format import _content
    target=tmp_path/'manifest.json';observed=[]
    def stop_before_rename(temporary,destination):
        assert Path(destination)==target and not target.exists()
        assert json.loads(temporary.read_bytes())=={'release_id':'a'*64}
        observed.append(temporary)
        raise RuntimeError('interrupted final rename')
    monkeypatch.setattr(Path,'replace',stop_before_rename)
    with pytest.raises(RuntimeError,match='interrupted final rename'):
        _content(target,{'release_id':'a'*64})
    assert observed and not target.exists()


def native_outputs(root, manifest):
    import pyarrow as pa
    import pyarrow.parquet as pq
    path = root / 'evidence/recording_video_links.parquet'
    path.parent.mkdir()
    pq.write_table(pa.table({'extracted_key': pa.array([], pa.string()), 'page_body': pa.array([], pa.string())}), path)
    return [*(f for f in manifest['files'] if f['name'].endswith('.parquet')), dict(name=path.name, **pin(path))]


def real_release(root,documents,retired=None):
    """A real release through the publisher's own candidate checks."""
    from test_release_gate import release_dir
    manifest=release_dir(root/'release',documents,retired)
    result=root/'result.json'
    result.write_bytes(encoded(dict(outputs=native_outputs(root,manifest),
        queries=[dict(name=name,data=[dict(violation=0)]) for name in ['invariants','model_invariants','url_state_invariants','profile_completeness']])))
    return dict(release=root/'release',manifest_pin=pin(root/'release/manifest.json'),result_pin=pin(result)),manifest


def live_store(root):
    """A store whose pointer names an uploaded release with documents A and B."""
    store=Store();_,manifest=real_release(root/'live',['A','B'])
    prefix='viewer-publications/releases/'+manifest['release_id']+'/'
    for item in manifest['files']+[dict(name='manifest.json')]:
        store.objects[prefix+item['name']]=(root/'live/release'/item['name']).read_bytes()
    store.objects['viewer-publications/manifest.json']=encoded(dict(release_id=manifest['release_id'],previous_release_id=None))
    return store,manifest['release_id']


def test_release_gate_refuses_before_contract_upload_or_flip(tmp_path,real_gates):
    store,live=live_store(tmp_path);native=Native(store);contracts=[]
    artifacts,_=real_release(tmp_path/'next',['A'])  # B vanishes: no redirect and no removal notice
    def contract(**context):contracts.append(context);return dict(status='passed',releaseId=context['release_id'],targets='owner-approved')
    with pytest.raises(ValueError,match='link rule: 1 base link keys vanish'):
        launch(tmp_path/'run',store=store,native=native,artifacts=artifacts,contract=contract)
    assert contracts==[] and native.calls==[]
    assert json.loads(store.objects['viewer-publications/manifest.json'])['release_id']==live
    assert [key for action,key in store.events if action=='put']==['viewer-publications/status.json']
    assert json.loads(store.objects['viewer-publications/status.json'])['status']=='failed'
    report=json.loads((tmp_path/'run/publish/release-gate.json').read_text())
    assert report['base_release']==live and report['link_rule']['missing_keys']==[(b'B'*8).hex()]


def test_release_gate_pass_reaches_contract(tmp_path,real_gates):
    from test_release_gate import record_for
    store,live=live_store(tmp_path)
    retired=[dict(link_key=b'B'*8,successor_key=None,last_release_id=live,last_filename='B.pdf')]
    artifacts,_=real_release(tmp_path/'next',['A'],retired)
    with pytest.raises(ValueError,match='no recorded cause'):
        launch(tmp_path/'first',store=store,artifacts=artifacts)
    causes=record_for(live,json.loads((tmp_path/'next/release/manifest.json').read_text())['release_id'],tmp_path)
    result,store,_=launch(tmp_path/'second',store=store,artifacts=artifacts,release_causes=causes)
    assert result['status']=='published' and result['release_gates']=='passed'
    assert json.loads(store.objects['viewer-publications/manifest.json'])['previous_release_id']==live


@pytest.mark.parametrize('pointer',['missing','legacy'])
def test_no_live_release_refuses_unless_a_first_release_is_declared(tmp_path,pointer,real_gates):
    """Fail closed: a missing or legacy pointer is not proof that nothing was published."""
    store=Store();native=Native(store)
    if pointer=='legacy':
        store.objects['viewer-publications/manifest.json']=encoded(dict(version=1,publisher_version=10,catalog_id='old',manifest='m.json'))
    artifacts,_=candidate(tmp_path/'run');value,keys=record()
    live,etag=read_pointer(store,bucket='derived-fixture')
    def passed(**context):return dict(status='passed',releaseId=context['release_id'],targets='owner-approved')
    common=dict(client=store,engine=native,bucket='derived-fixture',**artifacts,input_record=value,receipt_keys=keys,
        pointer=live,expected_etag=etag,public_origin='https://archive.example.test',contract=passed,canary=passed)
    with pytest.raises(ValueError,match='first release must be declared'):
        publish_candidate(work=tmp_path/'refused',**common)
    assert native.calls==[]
    result=publish_candidate(work=tmp_path/'bootstrap',first_release=True,**common)
    assert result['status']=='published' and result['first_release'] is True
    assert json.loads(store.objects['viewer-publications/status.json'])['first_release'] is True


@pytest.mark.parametrize('pinned',[None,'spent','other'])
def test_nightly_additions_from_new_receipts_publish_through_the_real_path(tmp_path,real_gates,pinned):
    """ct-ud0b end to end in publish_candidate: live input records give the receipt set, raw
    receipts come from the bucket, captures from its pin; no cause record is supplied.
    ct-pz32: a record still pinned from the release that is now live is spent and changes nothing;
    a record bound to any other release still refuses."""
    import gzip,os
    import pyarrow as pa
    import pyarrow.parquet as pq
    from docspec_client.client import NativeDatasets
    from viewer_publication.receipt_pins import write_input_receipts
    from test_archive_controller import Runtime
    store,live=live_store(tmp_path)
    old,old_keys=record()
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as native:
        engine=Runtime(native,store)
        write_input_receipts(NativeArchiveStore(client=store,engine=engine,bucket='derived-fixture',work=tmp_path/'seed'),
            live,old['input_digest'],old,['receipts/documents/2026-11-01/live.jsonl.gz'])
        body=b'N'*8+sha256(b'N').digest()[:24];receipt='receipts/documents/2026-11-03/nightly.jsonl.gz'
        # Raw receipts are read through their own client (the job's retrying reader), never the
        # single-attempt publication client: the receipt exists only there.
        class Receipts:
            raw={receipt:gzip.compress((json.dumps(dict(captures=[dict(sha256=body.hex())]))+'\n').encode(),mtime=0)}
            read=[]
            def get_object(self,*,Bucket,Key):
                from io import BytesIO
                assert Bucket=='derived-fixture';self.read.append(Key);return dict(Body=BytesIO(self.raw[Key]))
        receipts=Receipts()
        pq.write_table(pa.table({'receipt_key':[receipt],'receipt_line':pa.array([1],pa.int32()),'sha256':pa.array([body],pa.binary(32))}),tmp_path/'captures.parquet')
        artifacts,_=real_release(tmp_path/'next',['A','B','N'],retired=[])
        value,keys=record(run={'id':'nightly'})
        pointer,etag=read_pointer(store,bucket='derived-fixture')
        def passed(**context):return dict(status='passed',releaseId=context['release_id'],targets='owner-approved')
        causes=None
        if pinned:
            from test_release_gate import record_for
            causes=record_for('f'*64,live if pinned=='spent' else 'e'*64,tmp_path,groups=[])
        publish=lambda:publish_candidate(client=store,engine=engine,bucket='derived-fixture',work=tmp_path/'publish',**artifacts,
            input_record=value,receipt_keys=keys,pointer=pointer,expected_etag=etag,public_origin='https://archive.example.test',
            contract=passed,canary=passed,base_release=tmp_path/'base-release',release_causes=causes,
            automatic_captures=dict(kind='parquet',path=str(tmp_path/'captures.parquet')),receipt_client=receipts)
        if pinned=='other':
            with pytest.raises(ValueError,match='cause record: bound to base'):publish()
            assert json.loads(store.objects['viewer-publications/manifest.json'])['release_id']==live
            return
        result=publish()
    assert result['status']=='published' and receipts.read==[receipt]
    report=json.loads((tmp_path/'publish/release-gate.json').read_text())
    assert report['automatic_causes'] and all(e['tickets']==['ct-ud0b'] for e in report['automatic_causes'])


@pytest.mark.parametrize('night',['data_only','definition_changed','producer_changed','receipt_dropped'])
def test_a_capture_night_that_changes_existing_rows_publishes_only_under_the_live_definition(tmp_path,real_gates,night):
    """ct-pz32 through publish_candidate: a retitled document is no addition, so the traced proof
    stops; the night still publishes when the live release's own definition built it from a
    receipt set that only grew, and refuses when either is not so."""
    import os
    import pyarrow as pa
    from docspec_client.client import NativeDatasets
    from viewer_publication.receipt_pins import write_input_receipts
    from test_archive_controller import Runtime
    from test_release_gate import release_dir
    def release(root,documents,titles):
        manifest=release_dir(root/'release',documents,list=pa.table({'filename':[f'{keys}.pdf' for keys in documents],'title':titles}))
        result=root/'result.json'
        result.write_bytes(encoded(dict(outputs=native_outputs(root,manifest),
            queries=[dict(name=name,data=[dict(violation=0)]) for name in ['invariants','model_invariants','url_state_invariants','profile_completeness']])))
        return dict(release=root/'release',manifest_pin=pin(root/'release/manifest.json'),result_pin=pin(result)),manifest
    _,manifest=release(tmp_path/'live',['A','B'],['first','second']);live=manifest['release_id'];store=Store()
    for item in manifest['files']+[dict(name='manifest.json')]:
        store.objects['viewer-publications/releases/'+live+'/'+item['name']]=(tmp_path/'live/release'/item['name']).read_bytes()
    store.objects['viewer-publications/manifest.json']=encoded(dict(release_id=live,previous_release_id=None))
    def inputs(keys,**changes):
        value=record(**changes)[0]
        value.setdefault('unprofiled_inputs',dict(producer_versions={'captures':'c'*64},job_pins={'daily':'d'*64}))
        value['input_digest']=input_digest(receipt_keys=keys,**{key:value[key] for key in ['provenance','profile','entity_digests']})
        return value
    held=['receipts/documents/2026-11-01/live.jsonl.gz','receipts/house/pages/2026-11-01/live.jsonl.gz']
    keys=sorted([*(held[:1] if night=='receipt_dropped' else held),'receipts/documents/2026-11-03/nightly.jsonl.gz'])
    value=inputs(keys,run={'id':'nightly'},**(dict(profile={'sql':'second','parser':'pinned'}) if night=='definition_changed' else
        dict(unprofiled_inputs=dict(producer_versions={'captures':'e'*64},job_pins={'daily':'d'*64})) if night=='producer_changed' else {}))
    pq_path=tmp_path/'captures.parquet'
    import pyarrow.parquet as pq
    pq.write_table(pa.table({'receipt_key':pa.array([],pa.string()),'receipt_line':pa.array([],pa.int32()),'sha256':pa.array([],pa.binary(32))}),pq_path)
    artifacts,_=release(tmp_path/'next',['A','B','N'],['first','second, retitled','new'])
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as native:
        engine=Runtime(native,store)
        write_input_receipts(NativeArchiveStore(client=store,engine=engine,bucket='derived-fixture',work=tmp_path/'seed'),
            live,inputs(held)['input_digest'],inputs(held),held)
        pointer,etag=read_pointer(store,bucket='derived-fixture')
        def passed(**context):return dict(status='passed',releaseId=context['release_id'],targets='owner-approved')
        publish=lambda:publish_candidate(client=store,engine=engine,bucket='derived-fixture',work=tmp_path/'publish',**artifacts,
            input_record=value,receipt_keys=keys,pointer=pointer,expected_etag=etag,public_origin='https://archive.example.test',
            contract=passed,canary=passed,base_release=tmp_path/'base-release',
            automatic_captures=dict(kind='parquet',path=str(pq_path)),receipt_client=store)
        if night!='data_only':
            refusal=dict(definition_changed='differs from the live release in profile.sql',
                producer_changed='differs from the live release in unprofiled_inputs.producer_versions.captures',
                receipt_dropped='1 receipts the live release read are absent')[night]
            with pytest.raises(ValueError,match='no recorded cause for list.parquet.changed title') as refused:publish()
            stopped=json.loads((tmp_path/'publish/release-gate.json').read_text())['automatic_reasons']
            # Why the night is not a data-only night leads, in the report and in the error a person reads.
            assert refusal in stopped[0] and stopped[-1].endswith('not additions the traced proof reads, so it ran no check')
            assert str(refused.value).splitlines()[1]==stopped[0] and 'no recorded cause' in str(refused.value).splitlines()[-1]
            assert not (tmp_path/'publish/data-only-night.json').exists()
            assert json.loads(store.objects['viewer-publications/manifest.json'])['release_id']==live
            return
        result=publish()
    assert result['status']=='published'
    report=json.loads((tmp_path/'publish/release-gate.json').read_text())
    causes={entry['id']:entry for entry in report['automatic_causes']}
    assert causes['list.parquet|changed title|value differs on matched key']['count']==1
    assert all(entry['tickets']==['ct-pz32'] and entry['evidence']==[report['data_only_night']] for entry in causes.values())
    facts=json.loads((tmp_path/'publish/data-only-night.json').read_text())
    assert facts['new_receipt_keys']==['receipts/documents/2026-11-03/nightly.jsonl.gz'] and facts['live_receipts']==2


@pytest.mark.parametrize('page',[True,False])
def test_a_recaptured_page_publishes_through_the_real_gate_and_a_replaced_file_does_not(tmp_path,real_gates,page):
    """ct-pz32 through publish_candidate, its capture scan and raw receipt: the page at one address
    is captured again with new bytes, so its link key, lookup key and address would open the new
    file. As an HTML page under its own unchanged title that is proven and published; as a file
    whose title is its listing's link text it is left to a person."""
    import gzip,os
    import pyarrow as pa
    import pyarrow.parquet as pq
    from docspec_client.client import NativeDatasets
    from viewer_publication.receipt_pins import write_input_receipts
    from test_archive_controller import Runtime
    from test_release_gate import K,addresses,body,release_dir
    def release(root,documents,saved,titles):
        detail=pa.table({'link_key':pa.array([K(keys[0]) for keys in documents],pa.binary(8)),
            'saved_body':pa.array([K(letter)+bytes(24) for letter in saved],pa.binary(32)),
            'title_source':pa.array(['page_title' if page else 'link_text']*len(documents),pa.string()),
            'saved_media_type':pa.array(['text/html' if page else 'application/pdf']*len(documents),pa.string())})
        manifest=release_dir(root/'release',documents,saved=saved,detail=detail,
            list=pa.table({'filename':[f'{keys}.html' for keys in documents],'title':titles}),**addresses([keys.lower() for keys in documents]))
        result=root/'result.json'
        result.write_bytes(encoded(dict(outputs=native_outputs(root,manifest),
            queries=[dict(name=name,data=[dict(violation=0)]) for name in ['invariants','model_invariants','url_state_invariants','profile_completeness']])))
        return dict(release=root/'release',manifest_pin=pin(root/'release/manifest.json'),result_pin=pin(result)),manifest
    _,manifest=release(tmp_path/'live',['A','B'],'AB',['Hearing','Markup']);live=manifest['release_id'];store=Store()
    for item in manifest['files']+[dict(name='manifest.json')]:
        store.objects['viewer-publications/releases/'+live+'/'+item['name']]=(tmp_path/'live/release'/item['name']).read_bytes()
    store.objects['viewer-publications/manifest.json']=encoded(dict(release_id=live,previous_release_id=None))
    def inputs(keys,**changes):
        value=record(**changes)[0]
        value['unprofiled_inputs']=dict(producer_versions={'captures':'c'*64},job_pins={'daily':'d'*64})
        value['input_digest']=input_digest(receipt_keys=keys,**{key:value[key] for key in ['provenance','profile','entity_digests']})
        return value
    held=['receipts/house/pages/2026-11-01/live.jsonl.gz'];receipt='receipts/house/pages/2026-11-03/nightly.jsonl.gz'
    keys=sorted([*held,receipt]);value=inputs(keys,run={'id':'nightly'})
    # The night's raw receipt: the same address fetched again at HTTP 200, storing the new file C.
    store.objects[receipt]=gzip.compress((json.dumps(dict(url='https://example.test/a',requested_url='https://example.test/A',
        http_status=200,captures=[dict(sha256=body('C'),bytes=9)]))+'\n').encode(),mtime=0)
    pq.write_table(pa.table({'receipt_key':[receipt],'receipt_line':pa.array([1],pa.int32()),
        'sha256':pa.array([bytes.fromhex(body('C'))],pa.binary(32))}),tmp_path/'captures.parquet')
    artifacts,_=release(tmp_path/'next',['A','B'],'CB',['Hearing','Markup'])    # row 0 now saves file C
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as native:
        engine=Runtime(native,store)
        write_input_receipts(NativeArchiveStore(client=store,engine=engine,bucket='derived-fixture',work=tmp_path/'seed'),
            live,inputs(held)['input_digest'],inputs(held),held)
        pointer,etag=read_pointer(store,bucket='derived-fixture')
        def passed(**context):return dict(status='passed',releaseId=context['release_id'],targets='owner-approved')
        publish=lambda:publish_candidate(client=store,engine=engine,bucket='derived-fixture',work=tmp_path/'publish',**artifacts,
            input_record=value,receipt_keys=keys,pointer=pointer,expected_etag=etag,public_origin='https://archive.example.test',
            contract=passed,canary=passed,base_release=tmp_path/'base-release',
            automatic_captures=dict(kind='parquet',path=str(tmp_path/'captures.parquet')),receipt_client=store)
        if not page:
            with pytest.raises(ValueError,match='link rule: 1 live link keys answer another file'):publish()
            stopped=json.loads((tmp_path/'publish/release-gate.json').read_text())['automatic_reasons']
            assert 'would open another file, and it is not a page captured again at its own address' in stopped[0]
            assert json.loads(store.objects['viewer-publications/manifest.json'])['release_id']==live
            return
        result=publish()
    assert result['status']=='published'
    report=json.loads((tmp_path/'publish/release-gate.json').read_text())
    proven={(entry['kind'],entry['key']) for entry in report['link_rule']['proven_corrections']}
    assert proven=={('link_key',K('A').hex()),('lookup_key',K('a').hex()),('address','https://example.test/a')}
    assert all(entry['live_body']==body('A') and entry['candidate_body']==body('C') for entry in report['link_rule']['proven_corrections'])
    facts=json.loads((tmp_path/'publish/data-only-night.json').read_text())
    assert facts['recaptures']==[dict(address='https://example.test/a',live_body=body('A'),candidate_body=body('C'),receipt=receipt,title='Hearing')]
    assert report['reasons']==[] and report['named_corrections']['link_key']['waived']==0


def test_a_declared_first_release_is_checked_against_the_live_pointer_and_the_release_listing(tmp_path,real_gates):
    """M1: never replace a live release; and a missing pointer with releases already listed is
    not a first release (the declaration is verified, not trusted)."""
    store,live=live_store(tmp_path)
    artifacts,_=real_release(tmp_path/'next',['A','B','N'],retired=[])
    value,keys=record()
    pointer,etag=read_pointer(store,bucket='derived-fixture')
    def passed(**context):return dict(status='passed',releaseId=context['release_id'],targets='owner-approved')
    common=dict(client=store,engine=Native(store),bucket='derived-fixture',**artifacts,input_record=value,receipt_keys=keys,
        public_origin='https://archive.example.test',contract=passed,canary=passed,first_release=True)
    with pytest.raises(ValueError,match='cannot replace a live release'):
        publish_candidate(work=tmp_path/'live',pointer=pointer,expected_etag=etag,base_release=tmp_path/'base',**common)
    del store.objects['viewer-publications/manifest.json']  # the pointer is lost; releases remain
    with pytest.raises(ValueError,match='releases already exist'):
        publish_candidate(work=tmp_path/'lost',pointer=None,expected_etag=None,**common)
    assert 'viewer-publications/manifest.json' not in store.objects
