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
        schema=json.loads((Path(__file__).resolve().parents[3]/'model/lake/captures.schema.json').read_text())
        ref=dict(namespace=['fixture'],name='captures');catalog=tmp_path/'catalog'
        tables.create_table(engine=native,work=tmp_path/'create',catalog_root=catalog,table=ref,schema=schema,location=tmp_path/'lake-captures',create_namespace=True)
        appended=tables.append_rows(model['captures']['path'],engine=native,work=tmp_path/'append',catalog_root=catalog,table=ref,keys=['receipt_key'],definition=captures.current_version())
        capture_pin={k:appended[k] for k in ('metadata_location','table_uuid','snapshot','schema_id')}
        model['captures']=dict(kind='native_table',**capture_pin);model=validate_spec(model,base=tmp_path)
        selector,report=selected_acceptance(tmp_path/'comparison',capture_pin)
        held=ComparisonAcceptance(selector['receipt'],expected_mapping_digest=MAPPING,capture_pin=capture_pin)
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
