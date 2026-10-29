"""Comparison acceptance stays private and is guarded at actual write boundaries."""
import json
import os
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from test_archive_comparison_acceptance import fixture,pin,write,MAPPING,CAPTURE


def selected_acceptance(tmp_path,capture_pin=CAPTURE):
    from viewer_publication.archive_comparison_acceptance import accept_comparison
    tmp_path.mkdir()
    report,terminal,changed,_,_=fixture(tmp_path)
    pq.write_table(pq.read_table(changed).slice(0,0),changed)
    r=json.loads(report.read_text());r.update(status='compared',capture_pin=capture_pin)
    r['counts'].update(owner_gate=False,unexplained=0)
    r['outputs'][0].update(sha256=pin(changed)['sha256'],size=pin(changed)['size'],rows=0)
    write(report,r);write(terminal,dict(status='compared',report=str(report),measurement=dict(returncode=0,failure=None)))
    accept_comparison(report,expected_mapping_digest=MAPPING,capture_pin=capture_pin,work=tmp_path/'accepted',engine=None)
    return dict(receipt=pin(tmp_path/'accepted/acceptance.json'),mapping_digest=MAPPING),report


def test_comparison_custody_refuses_changed_receipt_inputs_without_rehashing(tmp_path):
    from viewer_publication.archive_comparison_acceptance import ComparisonAcceptance
    selected,report=selected_acceptance(tmp_path/'comparison')
    held=ComparisonAcceptance(selected['receipt'],expected_mapping_digest=MAPPING,capture_pin=CAPTURE)
    held.require()
    report.write_text(report.read_text()+'\n')
    with pytest.raises(ValueError):held.require()


@pytest.mark.parametrize('change',['shape','mapping','parquet','seed','daily'])
def test_publication_selector_requires_explicit_raw_native_identity(tmp_path,change):
    from test_archive_publish_job import publish_spec
    from viewer_publication.archive_publish_job import load_spec
    value=publish_spec(tmp_path)
    model=Path(value['model_spec']['path']);m=json.loads(model.read_text());m['captures']=dict(kind='native_table',**CAPTURE);write(model,m);value['model_spec']=pin(model)
    selector=dict(receipt=dict(path=str(tmp_path/'not-opened-receipt.json'),sha256='a'*64,size=1),mapping_digest=MAPPING)
    value['comparison_acceptance']=selector
    if change=='shape':selector['approved']=True
    elif change=='mapping':selector['mapping_digest']='wrong'
    elif change=='parquet':m['captures']=dict(kind='parquet',path=str(tmp_path/'captures.parquet'),sha256='a'*64,size=1);write(model,m);value['model_spec']=pin(model)
    elif change=='seed':value['model_kind']='seed_v5'
    else:value['daily']=dict(path=str(tmp_path/'not-opened-daily.json'),sha256='a'*64,size=1)
    with pytest.raises(ValueError):load_spec(write(tmp_path/'publish.json',value))
    assert not Path(value['work']).exists()


def test_execute_stale_comparison_refuses_before_target_runtime_or_sdk(tmp_path):
    from test_archive_publish_job import publish_spec
    from viewer_publication.archive_publish_job import load_spec,execute
    value=publish_spec(tmp_path);model=Path(value['model_spec']['path']);m=json.loads(model.read_text());m['captures']=dict(kind='native_table',**CAPTURE);write(model,m);value['model_spec']=pin(model)
    value['comparison_acceptance'],report=selected_acceptance(tmp_path/'comparison')
    spec=load_spec(write(tmp_path/'publish.json',value));report.write_text(report.read_text()+'\n')
    def never(*a,**kw):raise AssertionError('Stale comparison reached runtime or SDK')
    with pytest.raises(ValueError):execute(spec,runtime_factory=never,storage_factory=never,process_runner=never)
    assert not Path(value['work']).exists()


def test_canary_mutation_refuses_pointer_write(tmp_path):
    from viewer_publication.archive_comparison_acceptance import ComparisonAcceptance
    from viewer_publication.archive_gate import gate_and_flip
    selected,report=selected_acceptance(tmp_path/'comparison')
    held=ComparisonAcceptance(selected['receipt'],expected_mapping_digest=MAPPING,capture_pin=CAPTURE)
    class Store:
        def put_object(self,**kwargs):raise AssertionError('Stale comparison reached pointer PUT')
    def passed():return dict(status='passed',releaseId='b'*64,targets='owner-approved')
    def mutate():report.write_text(report.read_text()+'\n');return passed()
    with pytest.raises(ValueError):
        gate_and_flip(Store(),bucket='fixture',release_id='b'*64,previous_release_id=None,expected_etag=None,
            contract=passed,canary=mutate,comparison_acceptance=held)


def test_receipt_mutated_by_actual_model_refuses_all_successful_writes(tmp_path):
    from archive_job_fixture import real_model_spec
    from congress_api.lake import captures,tables
    from docspec_client.client import NativeDatasets
    from test_archive_controller import Runtime
    from test_archive_publish import Store
    from viewer_publication.archive_controller import run_publish
    from viewer_publication.archive_model_job import validate_spec
    from viewer_publication.archive_comparison_acceptance import ComparisonAcceptance
    model,_,_=real_model_spec(tmp_path)
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as native:
        model,held,report=native_capture_model(tmp_path,model,native)
        store=Store()
        class MutatingRuntime(Runtime):
            def run_job(self,path):
                result=self.native.run_job(path)
                report.write_text(report.read_text()+'\n')
                return result
        def never(**kwargs):raise AssertionError('Stale comparison reached a reader probe')
        with pytest.raises(ValueError):
            run_publish(model,client=store,engine=MutatingRuntime(native,store),bucket='derived-fixture',work=tmp_path/'publish',
                receipt_keys=['receipts/documents/2026-10-27/slice.jsonl.gz'],provenance=[],run={'id':'fixture'},
                public_origin='https://archive.fixture.test',contract=never,canary=never,comparison_acceptance=held)
        assert set(store.objects)<= {'viewer-publications/status.json'}
        assert not any('/inputs/' in key or key=='viewer-publications/manifest.json' for key in store.objects)


def test_effect_guard_opens_no_input_bytes_after_initial_verification(tmp_path):
    import sys
    from viewer_publication.archive_comparison_acceptance import ComparisonAcceptance
    selected,report=selected_acceptance(tmp_path/'comparison')
    held=ComparisonAcceptance(selected['receipt'],expected_mapping_digest=MAPPING,capture_pin=CAPTURE)
    paths={str(verified.path) for verified in held._held}
    reads=[];active=[True]
    def audit(event,args):
        if active[0] and event=='open' and isinstance(args[0],(str,bytes)) and str(args[0]) in paths:
            reads.append(args[0])
    sys.addaudithook(audit)
    try:
        for _ in range(4):held.require()
        assert reads==[], 'An effect guard reopened/rehashed accepted input bytes'
    finally:active[0]=False
    report.write_text(report.read_text()+'\n')
    with pytest.raises(ValueError):held.require()


def native_capture_model(tmp_path,model,native):
    from congress_api.lake import captures,tables
    from viewer_publication.archive_model_job import validate_spec
    from viewer_publication.archive_comparison_acceptance import ComparisonAcceptance
    schema=json.loads((Path(__file__).resolve().parents[3]/'model/lake/captures.schema.json').read_text())
    ref=dict(namespace=['fixture'],name='captures');catalog=tmp_path/'catalog'
    tables.create_table(engine=native,work=tmp_path/'create',catalog_root=catalog,table=ref,schema=schema,location=tmp_path/'lake-captures',create_namespace=True)
    appended=tables.append_rows(model['captures']['path'],engine=native,work=tmp_path/'append',catalog_root=catalog,table=ref,keys=['receipt_key'],definition=captures.current_version(),file_bytes=8<<20,row_group_rows=1024,row_group_bytes=1<<20)
    capture_pin={k:appended[k] for k in ('metadata_location','table_uuid','snapshot','schema_id')}
    model['captures']=dict(kind='native_table',**capture_pin);model=validate_spec(model,base=tmp_path)
    selector,report=selected_acceptance(tmp_path/'comparison',capture_pin)
    held=ComparisonAcceptance(selector['receipt'],expected_mapping_digest=MAPPING,capture_pin=capture_pin)
    return model,held,report


def status_mutating_store(report):
    from test_archive_publish import Store
    class StatusMutator(Store):
        armed=True
        def get_object(self,**kwargs):
            try:return super().get_object(**kwargs)
            finally:
                if self.armed and kwargs['Key']=='viewer-publications/status.json':
                    report.write_text(report.read_text()+'\n')
    return StatusMutator()


@pytest.mark.parametrize('status',['input_unchanged','release_unchanged','published'])
def test_success_status_rechecks_comparison_after_status_get(tmp_path,status):
    from viewer_publication.archive_comparison_acceptance import ComparisonAcceptance
    from viewer_publication.archive_publish import write_status
    selected,report=selected_acceptance(tmp_path/'comparison')
    held=ComparisonAcceptance(selected['receipt'],expected_mapping_digest=MAPPING,capture_pin=CAPTURE)
    store=status_mutating_store(report)
    with pytest.raises(ValueError):
        write_status(store,bucket='derived-fixture',status={'status':status},comparison_acceptance=held)
    assert not store.requests


def test_failed_status_can_be_recorded_after_comparison_changes(tmp_path):
    from viewer_publication.archive_comparison_acceptance import ComparisonAcceptance
    from viewer_publication.archive_publish import write_status
    selected,report=selected_acceptance(tmp_path/'comparison')
    held=ComparisonAcceptance(selected['receipt'],expected_mapping_digest=MAPPING,capture_pin=CAPTURE)
    store=status_mutating_store(report)
    write_status(store,bucket='derived-fixture',status={'status':'failed'},comparison_acceptance=held)
    assert json.loads(store.objects['viewer-publications/status.json'])['status']=='failed'


def test_release_unchanged_final_status_get_cannot_write_stale_success(tmp_path):
    from test_archive_publish import candidate,record,Native
    from viewer_publication.archive_comparison_acceptance import ComparisonAcceptance
    from viewer_publication.archive_publish import publish_candidate
    selected,report=selected_acceptance(tmp_path/'comparison')
    held=ComparisonAcceptance(selected['receipt'],expected_mapping_digest=MAPPING,capture_pin=CAPTURE)
    artifacts,manifest=candidate(tmp_path);input_record,keys=record();store=status_mutating_store(report)
    def never(**kwargs):raise AssertionError('Unchanged release should not need reader probes')
    with pytest.raises(ValueError):
        publish_candidate(client=store,engine=Native(store),bucket='derived-fixture',work=tmp_path/'publish',
            **artifacts,input_record=input_record,receipt_keys=keys,pointer={'release_id':manifest['release_id']},
            expected_etag='initial',public_origin='https://archive.fixture.test',contract=never,canary=never,
            comparison_acceptance=held)
    assert not any(json.loads(r['Body']).get('status')=='release_unchanged' for r in store.requests if r['Key']=='viewer-publications/status.json')


def test_input_unchanged_final_status_get_cannot_write_stale_success(tmp_path):
    from archive_job_fixture import real_model_spec
    from docspec_client.client import NativeDatasets
    from test_archive_controller import Runtime
    from viewer_publication.archive_controller import run_publish
    model,_,_=real_model_spec(tmp_path)
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as native:
        model,held,report=native_capture_model(tmp_path,model,native)
        store=status_mutating_store(report);store.armed=False
        def passed(**context):return dict(status='passed',releaseId=context['release_id'],targets='owner-approved')
        options=dict(client=store,engine=Runtime(native,store),bucket='derived-fixture',
            receipt_keys=['receipts/documents/2026-10-27/slice.jsonl.gz'],provenance=[],run={'id':'fixture'},
            public_origin='https://archive.fixture.test',contract=passed,canary=passed,comparison_acceptance=held)
        first=run_publish(model,work=tmp_path/'publish-first',**options)
        assert first['status']=='published'
        record=next(json.loads(v) for k,v in store.objects.items() if '/inputs/' in k and k.endswith('.json'))
        assert record['run']=={'id':'fixture'}
        before=dict(store.objects);store.armed=True
        model=dict(model,output=str(tmp_path/'release-second'),scratch=str(tmp_path/'model-second'))
        with pytest.raises(ValueError):run_publish(model,work=tmp_path/'publish-second',**options)
        assert store.objects==before
