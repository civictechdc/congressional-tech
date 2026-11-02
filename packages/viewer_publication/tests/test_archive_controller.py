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
        return dict(status='passed',releaseId=context['release_id'],targets='owner-approved')
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as native:
        engine=Runtime(native,store)
        kwargs=dict(client=store,engine=engine,bucket='derived-fixture',receipt_keys=keys,provenance=[],
            run={'id':'first'},public_origin='https://archive.fixture.test',contract=probe,canary=probe)
        first=run_publish(load_spec(specpath),work=tmp_path/'publish-first',**kwargs)
        assert first['status']=='published' and len(calls)==2
        before=dict(store.objects)
        spec.update(output=str(tmp_path/'release-again'),scratch=str(tmp_path/'model-again'))
        specpath.write_text(json.dumps(spec))
        skipped=run_publish(load_spec(specpath),work=tmp_path/'publish-again',measured_release_id=first['release_id'],**kwargs)
        assert skipped['status']=='input_unchanged' and len(calls)==2
        assert not Path(spec['output']).exists()
        assert not (Path(spec['scratch'])/'job.json').exists()
        assert (Path(spec['scratch'])/'admission/result.json').is_file()
        assert {k:v for k,v in store.objects.items() if k!='viewer-publications/status.json'}=={
            k:v for k,v in before.items() if k!='viewer-publications/status.json'}
        # A measured/approved candidate pin also binds the admitted early skip.
        spec.update(output=str(tmp_path/'release-wrong-measurement'),scratch=str(tmp_path/'model-wrong-measurement'))
        specpath.write_text(json.dumps(spec))
        with pytest.raises(ValueError,match='Measured.*release'):
            run_publish(load_spec(specpath),work=tmp_path/'publish-wrong-measurement',
                measured_release_id='ab'*32,**kwargs)
        assert len(calls)==2
        assert store.objects['viewer-publications/manifest.json']==before['viewer-publications/manifest.json']
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
    def passed(**context):return dict(status='passed',releaseId=context['release_id'],targets='owner-approved')
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


def test_completed_model_continues_after_canary_failure_without_rebuild(tmp_path):
    from viewer_publication.archive_controller import run_publish
    from viewer_publication.archive_model_job import load_spec
    spec,_,_=real_model_spec(tmp_path)
    path=tmp_path/'model-spec.json';path.write_text(json.dumps(spec));store=Store()
    def passed(**context):return dict(status='passed',releaseId=context['release_id'],targets='owner-approved')
    def failed(**context):raise RuntimeError('injected canary failure')
    keys=['receipts/documents/2026-10-27/slice.jsonl.gz']
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as native:
        engine=Runtime(native,store)
        kwargs=dict(client=store,engine=engine,bucket='derived-fixture',receipt_keys=keys,provenance=[],
            run={'id':'resume'},public_origin='https://archive.fixture.test',contract=passed)
        with pytest.raises(RuntimeError,match='injected'):
            run_publish(load_spec(path),work=tmp_path/'publish',canary=failed,**kwargs)
        checkpoint=(tmp_path/'publish/completed-model.json').read_bytes()
        result_path=Path(spec['scratch'])/'result.json'
        before=(result_path.read_bytes(),result_path.stat().st_mtime_ns)
    # A new native client simulates a fresh process while retaining only files and storage.
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as native:
        kwargs['engine']=Runtime(native,store)
        store.objects['viewer-publications/manifest.json']=json.dumps(dict(release_id='f'*64,previous_release_id=None)).encode()
        with pytest.raises(ValueError,match='Selected release changed'):
            run_publish(load_spec(path),work=tmp_path/'publish',canary=passed,resume=True,**kwargs)
        del store.objects['viewer-publications/manifest.json']
        result=run_publish(load_spec(path),work=tmp_path/'publish',canary=passed,resume=True,**kwargs)
        assert result['status']=='published'
        assert (result_path.read_bytes(),result_path.stat().st_mtime_ns)==before
        assert (tmp_path/'publish/completed-model.json').read_bytes()==checkpoint
        assert json.loads(store.objects['viewer-publications/manifest.json'])['release_id']==result['release_id']
        with pytest.raises(ValueError,match='inputs differ'):
            run_publish(load_spec(path),work=tmp_path/'publish',canary=passed,resume=True,**dict(kwargs,run={'id':'changed'}))


@pytest.mark.parametrize('boundary',['canary','completed_export','during_native','manifest_temp'])
def test_fresh_process_resumes_completed_model(tmp_path,boundary):
    import subprocess
    import sys
    spec,_,_=real_model_spec(tmp_path)
    path=tmp_path/'model-spec.json';path.write_text(json.dumps(spec))
    script=tmp_path/'resume-process.py'
    script.write_text('''import json, os, pickle, sys
from pathlib import Path
from docspec_client.client import NativeDatasets
from test_archive_controller import Runtime
from test_archive_publish import Store
from viewer_publication.archive_model_job import load_spec
import viewer_publication.archive_controller as controller
root=Path(sys.argv[1]); resume=sys.argv[2]=='resume'; boundary=sys.argv[3]
store=pickle.loads((root/'store.pickle').read_bytes()) if resume else Store()
def passed(**ctx): return dict(status='passed',releaseId=ctx['release_id'],targets='owner-approved')
def failed(**ctx): raise RuntimeError('injected canary failure')
if resume and boundary not in ('during_native','manifest_temp'):
    def no_rebuild(*args,**kwargs): raise AssertionError('completed model rebuilt')
    controller.build_prepared_release=no_rebuild
elif boundary=='completed_export':
    import signal
    original=controller.build_prepared_release
    (root/'store.pickle').write_bytes(pickle.dumps(store))
    def completed_then_killed(*args,**kwargs):
        original(*args,**kwargs)
        os.kill(os.getpid(),signal.SIGKILL)
    controller.build_prepared_release=completed_then_killed
if not resume and boundary=='manifest_temp':
    import signal
    import viewer_publication.archive_format as archive_format
    actual_write=archive_format.write_atomic_bytes
    (root/'store.pickle').write_bytes(pickle.dumps(store))
    def partial_manifest_then_killed(path,data,**kwargs):
        if Path(path).name!='manifest.json':return actual_write(path,data,**kwargs)
        temporary=Path(path).with_name('.manifest.interrupted.tmp')
        with temporary.open('xb') as stream:
            stream.write(data[:17]);stream.flush();os.fsync(stream.fileno())
        os.kill(os.getpid(),signal.SIGKILL)
    archive_format.write_atomic_bytes=partial_manifest_then_killed
try:
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as native:
        if not resume and boundary=='during_native':
            import signal,subprocess,time
            (root/'store.pickle').write_bytes(pickle.dumps(store))
            def killed_native(path):
                job=json.loads(Path(path).read_text())
                process=subprocess.Popen([*native._command(remote=True),'job','--spec',str(path)],
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
                deadline=time.monotonic()+5
                while process.poll() is None and not Path(job['scratch']).exists() and time.monotonic()<deadline:
                    time.sleep(0.001)
                running=process.poll() is None
                (root/'native-kill.json').write_text(json.dumps(dict(running=running,job=str(path),pid=process.pid)))
                assert running,'Native job completed before the interruption boundary'
                os.killpg(process.pid,signal.SIGKILL);process.wait()
                os.kill(os.getpid(),signal.SIGKILL)
            native.run_job=killed_native
        result=controller.run_publish(load_spec(root/'model-spec.json'),client=store,engine=Runtime(native,store),
            bucket='derived-fixture',work=root/'publish-process',receipt_keys=['receipts/documents/2026-10-27/slice.jsonl.gz'],
            provenance=[],run={'id':'fresh-process'},public_origin='https://archive.fixture.test',contract=passed,
            canary=passed if resume else failed,resume=resume)
        (root/'resume-result.json').write_text(json.dumps(result))
except RuntimeError as error:
    if resume or str(error)!='injected canary failure': raise
finally:
    (root/'store.pickle').write_bytes(pickle.dumps(store))
''')
    env=dict(os.environ)
    env['PYTHONPATH']=str(Path(__file__).parent)+os.pathsep+env.get('PYTHONPATH','')
    failed=subprocess.run([sys.executable,str(script),str(tmp_path),'fail',boundary],env=env)
    assert failed.returncode==(-9 if boundary in ('completed_export','during_native','manifest_temp') else 0)
    if boundary in ('completed_export','during_native','manifest_temp'):
        assert not (tmp_path/'publish-process/completed-model.json').exists()
        assert (tmp_path/'publish-process/model-intent.json').is_file()
    result_path=Path(spec['scratch'])/'result.json'
    if boundary in ('during_native','manifest_temp'):
        if boundary=='during_native':assert json.loads((tmp_path/'native-kill.json').read_text())['running']
        if boundary=='during_native':assert not result_path.exists()
        else:
            assert not (Path(spec['output'])/'manifest.json').exists()
            assert (Path(spec['output'])/'.manifest.interrupted.tmp').read_bytes()
        old_job=Path(spec['scratch'])/'job.json';old_bytes=old_job.read_bytes()
        inputs={name:(Path(spec[name]['path']).read_bytes(),Path(spec[name]['path']).stat().st_mtime_ns)
                for name in ('captures','readings','filename_readings')}
    else:before=(result_path.read_bytes(),result_path.stat().st_mtime_ns)
    subprocess.run([sys.executable,str(script),str(tmp_path),'resume',boundary],env=env,check=True)
    assert json.loads((tmp_path/'resume-result.json').read_text())['status']=='published'
    if boundary in ('during_native','manifest_temp'):
        assert old_job.read_bytes()==old_bytes
        if boundary=='during_native':assert not result_path.exists()
        else:assert (Path(spec['output'])/'.manifest.interrupted.tmp').is_file()
        checkpoint=json.loads((tmp_path/'publish-process/completed-model.json').read_text())
        assert checkpoint['stage']['scratch']!=spec['scratch']
        assert Path(checkpoint['result_pin']['path']).is_file()
        assert len(list((tmp_path/'publish-process/model-attempts').glob('attempt-*/prior-intent.json')))==1
        assert {name:(Path(spec[name]['path']).read_bytes(),Path(spec[name]['path']).stat().st_mtime_ns)
                for name in inputs}==inputs
    else:assert (result_path.read_bytes(),result_path.stat().st_mtime_ns)==before


@pytest.mark.parametrize('damage',['checkpoint_json','checkpoint_fields','manifest','result','input'])
def test_completed_checkpoint_refuses_corruption_and_changed_inputs(tmp_path,damage):
    from viewer_publication.archive_controller import run_publish
    from viewer_publication.archive_model_job import load_spec
    spec,_,_=real_model_spec(tmp_path)
    path=tmp_path/'model-spec.json';path.write_text(json.dumps(spec));store=Store()
    def passed(**ctx):return dict(status='passed',releaseId=ctx['release_id'],targets='owner-approved')
    def failed(**ctx):raise RuntimeError('stop before selection')
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as native:
        kwargs=dict(client=store,engine=Runtime(native,store),bucket='derived-fixture',
            receipt_keys=['receipts/documents/2026-10-27/slice.jsonl.gz'],provenance=[],
            run={'id':'corruption'},public_origin='https://archive.fixture.test',contract=passed)
        with pytest.raises(RuntimeError,match='stop before selection'):
            run_publish(load_spec(path),work=tmp_path/'publish',canary=failed,**kwargs)
        checkpoint=tmp_path/'publish/completed-model.json'
        if damage=='checkpoint_json':checkpoint.write_text('{')
        elif damage=='checkpoint_fields':checkpoint.write_text(json.dumps({'version':1}))
        else:
            target={'manifest':Path(spec['output'])/'manifest.json','result':Path(spec['scratch'])/'result.json',
                    'input':Path(spec['captures']['path'])}[damage]
            with target.open('ab') as out:out.write(b'changed')
        before=dict(store.objects)
        with pytest.raises(ValueError):
            run_publish(load_spec(path),work=tmp_path/'publish',canary=passed,resume=True,**kwargs)
        assert {k:v for k,v in store.objects.items() if k!='viewer-publications/status.json'}=={
            k:v for k,v in before.items() if k!='viewer-publications/status.json'}


def test_publish_seeds_the_ledger_from_the_live_release_and_its_named_history(tmp_path):
    """Gates 1 and 2 through run_publish: keys from the live release and from an earlier
    release named in link_history land in retired_links; the comparison still needs causes."""
    from viewer_publication.archive_controller import run_publish
    from viewer_publication.archive_model_job import load_spec
    from test_release_gate import release_dir
    spec,_,_=real_model_spec(tmp_path)
    specpath=tmp_path/'model-spec.json';specpath.write_text(json.dumps(spec))
    store=Store();ids={}
    for name,documents in [('live',['Q']),('history',['H'])]:
        manifest=release_dir(tmp_path/name,documents);ids[name]=manifest['release_id']
        for item in manifest['files']+[dict(name='manifest.json')]:
            store.objects['viewer-publications/releases/'+manifest['release_id']+'/'+item['name']]=(tmp_path/name/item['name']).read_bytes()
    store.objects['viewer-publications/manifest.json']=json.dumps(dict(release_id=ids['live'],previous_release_id=None)).encode()
    def probe(**context):raise AssertionError('no probe may run before the gates pass')
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as native:
        kwargs=dict(client=store,engine=Runtime(native,store),bucket='derived-fixture',
            receipt_keys=['receipts/documents/2026-10-27/slice.jsonl.gz'],provenance=[],run={'id':'gated'},
            public_origin='https://archive.fixture.test',contract=probe,canary=probe)
        with pytest.raises(ValueError,match='must name link_history'):
            run_publish(load_spec(specpath),work=tmp_path/'publish-bare',**kwargs)
        with pytest.raises(ValueError,match='no recorded cause'):
            run_publish(load_spec(specpath),work=tmp_path/'publish',link_history=[ids['history']],**kwargs)
    retired=pq.read_table(Path(spec['output'])/'retired_links.parquet').to_pylist()
    assert {(row['link_key'],row['successor_key'],row['last_release_id']) for row in retired}=={
        (b'Q'*8,None,ids['live']),(b'H'*8,None,ids['history'])}
    [report]=list((tmp_path/'publish').glob('candidate-*/release-gate.json'))
    report=json.loads(report.read_text())
    assert report['link_rule']['missing']==0 and report['base_release']==ids['live']
    assert json.loads(store.objects['viewer-publications/manifest.json'])['release_id']==ids['live']
