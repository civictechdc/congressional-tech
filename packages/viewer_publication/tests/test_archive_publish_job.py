"""The public publisher command plans safely and refuses before external effects."""
import json
import os
from pathlib import Path

import pytest

from archive_job_fixture import model_spec
from congress_api.retention.provenance import file_pin


def publish_spec(tmp_path):
    model=tmp_path/'model.json';model.write_text(json.dumps(model_spec(tmp_path)))
    targets=tmp_path/'targets.json';targets.write_text(json.dumps(dict(version=1,status='measured',
        ceilings=dict(startupMs=100,searchMs=100,detailMs=100,heapBytes=1000000))))
    dist=tmp_path/'site';dist.mkdir()
    return dict(version=1,model_spec=dict(path=str(model),**file_pin(model)),bucket='derived-fixture',
        work=str(tmp_path/'publish'),public_origin='https://archive.fixture.test',
        receipt_keys=['receipts/documents/fixture.jsonl.gz'],provenance=[],run={'id':'fixture'},
        contract_next_release=str(tmp_path/'next'),targets=dict(path=str(targets),**file_pin(targets)),site_dist=str(dist))


def invoke(tmp_path,value,*args):
    from viewer_publication.archive_publish_job import main
    path=tmp_path/'publish.json';path.write_text(json.dumps(value))
    return main(['--spec',str(path),*args])


def test_default_plan_never_opens_runtime_targets_or_data_or_creates_work(tmp_path,capsys):
    value=publish_spec(tmp_path)
    Path(value['targets']['path']).unlink()
    assert invoke(tmp_path,value)==0
    result=json.loads(capsys.readouterr().out)
    assert result['status']=='planned' and result['executed'] is False
    assert result['model_spec']==value['model_spec']
    assert not Path(value['work']).exists()
    assert not (tmp_path/'model').exists() and not (tmp_path/'release').exists()
    assert not (tmp_path/'unopened-runtime.json').exists()


@pytest.mark.parametrize('change,match',[
    ('unknown','unknown'),('version','version 1'),('http','HTTPS'),('origin_path','origin'),
    ('pin','SHA-256'),('receipt','receipt'),('provenance','provenance'),('run','run metadata'),
    ('work_overlap','separate'),('command','unknown'),
])
def test_strict_spec_refuses_before_effects(tmp_path,capsys,change,match):
    value=publish_spec(tmp_path)
    if change=='unknown':value['extra']=True
    elif change=='version':value['version']=True
    elif change=='http':value['public_origin']='http://archive.fixture.test'
    elif change=='origin_path':value['public_origin']='https://archive.fixture.test/nested'
    elif change=='pin':value['model_spec']['sha256']='bad'
    elif change=='receipt':value['receipt_keys']=['other/unsafe']
    elif change=='provenance':value['provenance']=[dict(key='provenance/reviews/test.jsonl',etag='')]
    elif change=='run':value['run']={}
    elif change=='work_overlap':value['work']=str(tmp_path/'model')
    elif change=='command':value['contract_command']=['echo','passed']
    with pytest.raises(SystemExit) as error:invoke(tmp_path,value,'--execute')
    assert error.value.code==2 and match in capsys.readouterr().err
    assert not (tmp_path/'publish').exists()


@pytest.mark.parametrize('which',['publisher','model'])
def test_blocked_jobs_refuse_without_runtime(tmp_path,capsys,which):
    value=publish_spec(tmp_path)
    if which=='publisher':value=dict(status='blocked',reason='Owner target binding pending')
    else:
        path=Path(value['model_spec']['path']);path.write_text(json.dumps(dict(status='blocked',reason='Owner model binding pending')))
        value['model_spec']=dict(path=str(path),**file_pin(path))
    assert invoke(tmp_path,value,'--execute')==2
    assert json.loads(capsys.readouterr().out)['status']=='blocked'
    assert not (tmp_path/'publish').exists()


@pytest.mark.parametrize('change,match',[
    ('model_pin','checksum mismatch'),('target_pin','checksum mismatch'),('pending','measured'),
    ('invalid_ceiling','measured'),('existing_work','fresh'),('missing_dist','site_dist'),
])
def test_execute_checks_local_pins_targets_and_work_before_runtime(tmp_path,capsys,change,match):
    value=publish_spec(tmp_path)
    if change=='model_pin':Path(value['model_spec']['path']).write_text('{}')
    elif change=='target_pin':Path(value['targets']['path']).write_text('{}')
    elif change in {'pending','invalid_ceiling'}:
        path=Path(value['targets']['path']);targets=json.loads(path.read_text())
        if change=='pending':targets['status']='owner-gated'
        else:targets['ceilings']['heapBytes']=0
        path.write_text(json.dumps(targets));value['targets']=dict(path=str(path),**file_pin(path))
    elif change=='existing_work':Path(value['work']).mkdir()
    elif change=='missing_dist':Path(value['site_dist']).rmdir()
    with pytest.raises(SystemExit) as error:invoke(tmp_path,value,'--execute')
    assert error.value.code==2 and match in capsys.readouterr().err
    assert not (tmp_path/'model').exists() and not (tmp_path/'release').exists()


def test_execute_requires_remote_before_storage_connection(tmp_path,capsys):
    value=publish_spec(tmp_path);path=Path(value['model_spec']['path'])
    model=json.loads(path.read_text());model['engine_config']=os.environ['DOCSPEC_JOB_CONFIG']
    path.write_text(json.dumps(model));value['model_spec']=dict(path=str(path),**file_pin(path))
    with pytest.raises(SystemExit) as error:invoke(tmp_path,value,'--execute')
    assert error.value.code==2 and 'remote native engine' in capsys.readouterr().err
    assert not Path(value['work']).exists()


def test_fixed_site_probe_arguments_use_one_publisher_and_declared_paths(tmp_path):
    from viewer_publication.archive_publish_job import load_spec,probe_commands
    value=publish_spec(tmp_path);path=tmp_path/'publish.json';path.write_text(json.dumps(value))
    spec=load_spec(path);candidate=tmp_path/'release';release='a'*64
    commands=probe_commands(spec,release=candidate,release_id=release,probe_selectors=dict(saved_row=7,link_key='0123456789abcdef'))
    assert commands['contract']==['npm','run','contract:archive','--','--release',str(candidate),
        '--next-release',value['contract_next_release'],'--dist',value['site_dist'],'--targets',value['targets']['path'],
        '--output',str(tmp_path/'publish/contract.json'),'--link-key','0123456789abcdef']
    assert commands['canary']==['npm','run','canary:archive','--','--pointer','https://archive.fixture.test/viewer-publications/manifest.json',
        '--release',release,'--raw','https://archive.fixture.test/','--targets',value['targets']['path'],
        '--output',str(tmp_path/'publish/canary.json'),'--saved-row','7']


def remote_config(tmp_path,*,endpoint=None,owned_prefix=None):
    path=tmp_path/'public-remote.json'
    path.write_text(json.dumps(dict(owned_prefix=owned_prefix or 's3://derived-fixture/__r2_data_catalog/ct-archive-v2',
        properties={'s3.endpoint':endpoint or 'https://'+'a'*32+'.r2.cloudflarestorage.com','s3.region':'auto',
                    'uri':'https://catalog.cloudflarestorage.com/'+'a'*32+'/derived-fixture',
                    'warehouse':'a'*32+'_derived-fixture','docspec.namespace-generation':'00000000-0000-4000-8000-000000000001'},
        secret_env={'s3.access-key-id':'DOCSPEC_R2_ACCESS','s3.secret-access-key':'DOCSPEC_R2_SECRET'})))
    return path


@pytest.mark.parametrize('endpoint,prefix',[
    ('https://different-provider.test',None),('http://'+'a'*32+'.r2.cloudflarestorage.com',None),
    ('https://'+'a'*32+'.r2.cloudflarestorage.com/other-account',None),
    (None,'s3://other-bucket/viewer-publications'),(None,'s3://derived-fixture/other-namespace'),
    (None,'s3://derived-fixture/viewer-publications-other'),
])
def test_destination_refuses_provider_bucket_or_namespace_before_any_native_or_sdk_call(tmp_path,endpoint,prefix):
    from viewer_publication.archive_publish_job import execute,load_spec
    value=publish_spec(tmp_path);path=tmp_path/'publish.json';path.write_text(json.dumps(value))
    remote=remote_config(tmp_path,endpoint=endpoint,owned_prefix=prefix);events=[]
    runtime=tmp_path/'public-runtime.json';runtime.write_text(json.dumps(dict(version=1,binary='/unopened/binary',
        workspace=str(tmp_path/'workspace'),remote=str(remote),credentials='/unopened/credentials.json')))
    modelpath=Path(value['model_spec']['path']);model=json.loads(modelpath.read_text());model['engine_config']=str(runtime)
    modelpath.write_text(json.dumps(model));value['model_spec']=dict(path=str(modelpath),**file_pin(modelpath));path.write_text(json.dumps(value))
    class Runtime:
        def __init__(self):self.remote=remote
        def __enter__(self):return self
        def __exit__(self,*_):pass
        def verify_runtime(self):events.append('native');raise AssertionError('Must refuse before native activity')
    def storage_factory(**kwargs):events.append('sdk');raise AssertionError('Must refuse before SDK activity')
    with pytest.raises(ValueError,match='destination'):
        execute(load_spec(path),runtime_factory=lambda _:Runtime(),storage_factory=storage_factory)
    assert events==[] and not Path(value['work']).exists()


def test_metadata_first_probe_selectors_are_required_and_not_daily_owner_options(tmp_path):
    from viewer_publication.archive_publish_job import load_spec,probe_commands
    value=publish_spec(tmp_path);path=tmp_path/'publish.json';path.write_text(json.dumps(value));spec=load_spec(path)
    # Native metadata selects a saved row beyond metadata-only rows at the start.
    selectors=dict(saved_row=7,link_key='0123456789abcdef')
    commands=probe_commands(spec,release=tmp_path/'release',release_id='a'*64,probe_selectors=selectors)
    assert commands['contract'][-2:]==['--link-key',selectors['link_key']]
    assert commands['canary'][-2:]==['--saved-row','7']
    for invalid in [None,{},dict(saved_row=True,link_key='0'*16),dict(saved_row=-1,link_key='0'*16),
                    dict(saved_row=1,link_key='ABCDEF0123456789'),dict(saved_row=1,link_key='0'*15),
                    dict(saved_row=1,link_key='0'*16,extra=True)]:
        with pytest.raises(ValueError,match='probe selectors'):
            probe_commands(spec,release=tmp_path/'release',release_id='a'*64,probe_selectors=invalid)


def test_execute_binds_matching_destination_and_records_actual_native_probe_commands(tmp_path):
    from docspec_client.client import NativeDatasets
    from viewer_publication.archive_publish_job import execute,load_spec
    from archive_job_fixture import real_model_spec
    from test_archive_controller import Runtime as NativeTransport
    from test_archive_publish import Store
    value=publish_spec(tmp_path);model,_,_=real_model_spec(tmp_path)
    path=Path(value['model_spec']['path']);path.write_text(json.dumps(model));value['model_spec']=dict(path=str(path),**file_pin(path))
    specpath=tmp_path/'publish.json';specpath.write_text(json.dumps(value));spec=load_spec(specpath)
    remote=remote_config(tmp_path);store=Store();events=[];commands=[];configs=[]
    runtime=tmp_path/'public-runtime.json';settings=json.loads(Path(os.environ['DOCSPEC_JOB_CONFIG']).read_text())
    # Fake transport owns its credentials; these public references are never opened.
    original=Path(os.environ['DOCSPEC_JOB_CONFIG']).parent
    for field in ['binary','limits','workspace']:
        if field in settings:settings[field]=str((original/settings[field]).resolve())
    settings.update(remote=str(remote),credentials='/unopened/fake-credentials.json')
    runtime.write_text(json.dumps(settings));model['engine_config']=str(runtime)
    Path(value['model_spec']['path']).write_text(json.dumps(model))
    value['model_spec']=dict(path=value['model_spec']['path'],**file_pin(value['model_spec']['path']))
    value['receipt_keys']=['receipts/documents/2026-10-27/slice.jsonl.gz']
    specpath.write_text(json.dumps(value));spec=load_spec(specpath)
    class Runtime(NativeTransport):
        def __init__(self,native,configuration):super().__init__(native,store);self.remote=Path(configuration['remote'])
        def __enter__(self):return self
        def __exit__(self,*_):self.native.close()
        def verify_runtime(self):events.append('qualified');return self.native.verify_runtime()
    def runtime_factory(path):
        configuration=json.loads(Path(path).read_text());configs.append(configuration)
        return Runtime(NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),configuration)
    def storage_factory(**kwargs):
        assert events and events[0]=='qualified'
        assert kwargs==dict(bucket='derived-fixture',endpoint_url='https://'+'a'*32+'.r2.cloudflarestorage.com',retries={'total_max_attempts':1})
        events.append('sdk');return store
    def process_runner(command,**kwargs):
        assert command[:3] in [['npm','run','contract:archive'],['npm','run','canary:archive']]
        assert kwargs['check'] is True and kwargs['cwd'].name=='site'
        commands.append(command)
        # External browser execution is recorded; native model and publisher remain actual.
        manifest=json.loads((Path(model['output'])/'manifest.json').read_text())
        output=Path(command[command.index('--output')+1])
        output.write_text(json.dumps(dict(status='passed',releaseId=manifest['release_id'],targets='measured')))
    result=execute(spec,runtime_factory=runtime_factory,storage_factory=storage_factory,process_runner=process_runner)
    assert result['status']=='published' and len(commands)==2 and events.index('sdk')>events.index('qualified')
    native=json.loads((Path(model['scratch'])/'result.json').read_text())
    selectors=next(query['data'][0] for query in native['queries'] if query['name']=='probe_selectors')
    assert commands[0][-2:]==['--link-key',selectors['link_key']]
    assert commands[1][-2:]==['--saved-row',str(selectors['saved_row'])]
    assert spec['provenance']==value['provenance']
    assert len(configs)==2 and configs[0]['remote']!=configs[1]['remote']
    assert all(configs[0][name]==configs[1][name] for name in ['binary','limits','binary_sha256','source_revision'])
    assert not Path(configs[1]['remote']).exists()  # Owned startup metadata was cleaned up.
