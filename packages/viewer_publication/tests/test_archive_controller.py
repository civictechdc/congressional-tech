"""One real native model feeds publication and the admitted early-skip path."""
import json
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
