"""One real native model feeds publication and the admitted early-skip path."""
import json
from hashlib import md5
import os
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from archive_job_fixture import real_model_spec
from docspec_client.client import NativeDatasets
from test_archive_publish import Store,Native


class Runtime:
    """Keep SQL native while the external object transport is recorded locally."""
    remote='fixture transport'
    def __init__(self,native,store):self.native=native;self.upload=Native(store)
    def __getattr__(self,name):return getattr(self.native,name)
    def create_file(self,spec):return self.upload.create_file(spec)


def test_actual_model_publishes_then_checks_admission_before_input_skip(tmp_path):
    from viewer_publication.archive_controller import run_publish
    from viewer_publication.archive_model_job import load_spec
    spec,_,_=real_model_spec(tmp_path)
    specpath=tmp_path/'model-spec.json';specpath.write_text(json.dumps(spec))
    store=Store();keys=['receipts/documents/2026-10-27/slice.jsonl.gz'];calls=[]
    def probe(**context):
        assert context['probe_selectors']['saved_row']==0
        assert len(context['probe_selectors']['link_key'])==16
        calls.append(context['release_id'])
        return dict(status='passed',releaseId=context['release_id'],targets='measured')
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as native:
        engine=Runtime(native,store)
        kwargs=dict(client=store,engine=engine,bucket='derived-fixture',receipt_keys=keys,provenance=[],
            run={'id':'first'},public_origin='https://archive.fixture.test',contract=probe,canary=probe)
        first=run_publish(load_spec(specpath),work=tmp_path/'publish-first',**kwargs)
        assert first['status']=='published' and len(calls)==2
        before=dict(store.objects)
        spec.update(output=str(tmp_path/'release-again'),scratch=str(tmp_path/'model-again'))
        specpath.write_text(json.dumps(spec))
        skipped=run_publish(load_spec(specpath),work=tmp_path/'publish-again',**kwargs)
        assert skipped['status']=='input_unchanged' and len(calls)==2
        assert not Path(spec['output']).exists()
        assert not (Path(spec['scratch'])/'job.json').exists()
        assert (Path(spec['scratch'])/'admission/result.json').is_file()
        assert {k:v for k,v in store.objects.items() if k!='viewer-publications/status.json'}=={
            k:v for k,v in before.items() if k!='viewer-publications/status.json'}
        # Identical semantic identity does not excuse a physically incomplete lake.
        empty=tmp_path/'missing-readings.parquet';pq.write_table(pq.read_table(spec['readings']['path']).slice(0,0),empty)
        from congress_api.retention.provenance import file_pin
        spec['readings']=dict(kind='parquet',path=str(empty),**file_pin(empty))
        spec.update(output=str(tmp_path/'release-incomplete'),scratch=str(tmp_path/'model-incomplete'))
        specpath.write_text(json.dumps(spec))
        with pytest.raises(ValueError,match='admission'):
            run_publish(load_spec(specpath),work=tmp_path/'publish-incomplete',**kwargs)
        assert len(calls)==2 and store.objects['viewer-publications/manifest.json']==before['viewer-publications/manifest.json']


def test_receipt_identity_must_equal_actual_native_model_keys(tmp_path):
    from viewer_publication.archive_controller import run_publish
    from viewer_publication.archive_model_job import load_spec
    spec,_,_=real_model_spec(tmp_path)
    path=tmp_path/'model-spec.json';path.write_text(json.dumps(spec));store=Store()
    def never(**_):raise AssertionError('Invalid replay evidence must refuse before probes')
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as native:
        with pytest.raises(ValueError,match='receipt'):
            run_publish(load_spec(path),work=tmp_path/'publish',client=store,engine=Runtime(native,store),
                bucket='derived-fixture',receipt_keys=['receipts/wrong.jsonl.gz'],provenance=[],run={'id':'bad'},
                public_origin='https://archive.fixture.test',contract=never,canary=never)
    assert set(store.objects)=={'viewer-publications/status.json'}


def test_identity_cannot_pin_a_provenance_file_omitted_from_the_model(tmp_path):
    from archive_job_fixture import model_spec
    from viewer_publication.archive_model_job import load_spec
    from viewer_publication.archive_controller import run_publish
    value=model_spec(tmp_path);path=tmp_path/'model-spec.json';path.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='provenance'):
        run_publish(load_spec(path),client=None,engine=None,bucket='derived-fixture',work=tmp_path/'publish',
            receipt_keys=[],provenance=[dict(key='provenance/reviews/omitted.jsonl',etag='etag')],run={'id':'bad'},
            public_origin='https://archive.fixture.test',contract=None,canary=None)
    assert not (tmp_path/'publish').exists()


def test_transport_validation_failure_still_records_one_failed_status(tmp_path):
    from viewer_publication.archive_controller import run_publish
    from viewer_publication.archive_model_job import load_spec
    spec,_,_=real_model_spec(tmp_path);path=tmp_path/'model-spec.json';path.write_text(json.dumps(spec));store=Store()
    def never(**_):raise AssertionError('Invalid origin must refuse before probes')
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as native:
        with pytest.raises(ValueError,match='HTTPS'):
            run_publish(load_spec(path),work=tmp_path/'publish',client=store,engine=Runtime(native,store),
                bucket='derived-fixture',receipt_keys=['receipts/documents/2026-10-27/slice.jsonl.gz'],provenance=[],
                run={'id':'invalid-origin'},public_origin='http://archive.fixture.test',contract=never,canary=never)
    assert set(store.objects)=={'viewer-publications/status.json'}
    assert json.loads(store.objects['viewer-publications/status.json'])['status']=='failed'
    assert sum(1 for event in store.events if event==('put','viewer-publications/status.json'))==1


def test_provenance_inventory_must_match_the_pinned_current_etags(tmp_path):
    from congress_api.retention.provenance import file_pin
    from viewer_publication.archive_controller import run_publish
    from viewer_publication.archive_model_job import load_spec
    spec,_,_=real_model_spec(tmp_path)
    path=tmp_path/'empty-reviews.jsonl';path.write_bytes(b'')
    key='provenance/reviews/fixture.jsonl'
    spec['review_files']=[dict(key=key,path=str(path),**file_pin(path))]
    pin_etag='"'+md5(b'').hexdigest()+'"'
    model=tmp_path/'model-spec.json';model.write_text(json.dumps(spec))
    class MetadataStore(Store):
        def list_objects_v2(self,*,Bucket,Prefix,**kwargs):
            self.events.append(('list',Prefix))
            return dict(Contents=[dict(Key=k,ETag='"'+md5(v).hexdigest()+'"')
                for k,v in self.objects.items() if k.startswith(Prefix)],IsTruncated=False)
    store=MetadataStore();store.objects[key]=b'changed raw provenance'
    def never(**_):raise AssertionError('Changed provenance must refuse before probes')
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as native:
        with pytest.raises(ValueError,match='provenance'):
            run_publish(load_spec(model),work=tmp_path/'publish',client=store,engine=Runtime(native,store),
                bucket='derived-fixture',receipt_keys=['receipts/documents/2026-10-27/slice.jsonl.gz'],
                provenance=[dict(key=key,etag=pin_etag)],run={'id':'stale'},
                public_origin='https://archive.fixture.test',contract=never,canary=never)
    assert set(store.objects)=={key,'viewer-publications/status.json'}
    assert ('list','provenance/') in store.events
    assert not any(event==('get',key) for event in store.events)


def test_nonrecord_provenance_is_pinned_without_becoming_a_model_input(tmp_path):
    from viewer_publication.archive_controller import run_publish
    from viewer_publication.archive_model_job import load_spec
    spec,_,_=real_model_spec(tmp_path)
    path=tmp_path/'model-spec.json';path.write_text(json.dumps(spec))
    key='provenance/recoveries/accepted-'+'a'*64+'.json'
    # Historical backup ETags are opaque: this file is never a model record.
    etag='"'+'b'*32+'-2"'
    class MetadataStore(Store):
        backup_etag=etag
        def list_objects_v2(self,*,Bucket,Prefix,**kwargs):
            self.events.append(('list',Prefix))
            return dict(Contents=[dict(Key=key,ETag=self.backup_etag)],IsTruncated=False)
    store=MetadataStore();store.objects[key]=b'not a JSONL model record'
    def passed(**context):return dict(status='passed',releaseId=context['release_id'],targets='measured')
    provenance=[dict(key=key,etag=etag)]
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as native:
        engine=Runtime(native,store)
        kwargs=dict(client=store,engine=engine,bucket='derived-fixture',
            receipt_keys=['receipts/documents/2026-10-27/slice.jsonl.gz'],provenance=provenance,
            run={'id':'nonrecord'},public_origin='https://archive.fixture.test',contract=passed,canary=passed)
        result=run_publish(load_spec(path),work=tmp_path/'publish',**kwargs)
        assert result['status']=='published'
        record=json.loads(store.objects['viewer-publications/releases/'+result['release_id']+
            '/inputs/'+result['input_digest']+'.json'])
        assert record['provenance']==provenance
        uploads=len(engine.upload.calls)
        spec.update(output=str(tmp_path/'unused-release'),scratch=str(tmp_path/'unused-model'))
        path.write_text(json.dumps(spec));store.backup_etag='"'+'c'*32+'-2"'
        with pytest.raises(ValueError,match='current immutable raw inventory'):
            run_publish(load_spec(path),work=tmp_path/'stale-publish',**kwargs)
        assert len(engine.upload.calls)==uploads
        assert not Path(spec['scratch']).exists()
    assert ('get',key) not in store.events
    assert store.objects[key]==b'not a JSONL model record'


def test_record_acknowledgment_md5_matches_list_etag_without_normalizing_backups():
    from viewer_publication.archive_controller import _provenance_snapshot
    record='provenance/reviews/fixture.jsonl'
    backup='provenance/recoveries/accepted-backup.json'
    current=[dict(key=record,etag='"'+'b'*32+'"'),dict(key=backup,etag='"opaque-backup-2"')]
    class MetadataStore(Store):
        def list_objects_v2(self,*,Bucket,Prefix,**kwargs):
            self.events.append(('list',Prefix))
            return dict(Contents=[dict(Key=row['key'],ETag=row['etag']) for row in current],IsTruncated=False)
    store=MetadataStore()
    expected=[dict(key=record,etag='B'*32),dict(key=backup,etag='"opaque-backup-2"')]
    assert _provenance_snapshot(store,'derived-fixture',expected)==sorted(current,key=lambda row:row['key'])
    for changed in [dict(key=record,etag='c'*32),dict(key=backup,etag='opaque-backup-2')]:
        stale=[changed if row['key']==changed['key'] else row for row in expected]
        with pytest.raises(ValueError,match='current immutable raw inventory'):
            _provenance_snapshot(store,'derived-fixture',stale)
    assert store.events==[('list','provenance/')]*3
