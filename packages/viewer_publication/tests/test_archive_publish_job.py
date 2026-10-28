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
    commands=probe_commands(spec,release=candidate,release_id=release)
    assert commands['contract']==['npm','run','contract:archive','--','--release',str(candidate),
        '--next-release',value['contract_next_release'],'--dist',value['site_dist'],'--targets',value['targets']['path'],
        '--output',str(tmp_path/'publish/contract.json')]
    assert commands['canary']==['npm','run','canary:archive','--','--pointer','https://archive.fixture.test/viewer-publications/manifest.json',
        '--release',release,'--raw','https://archive.fixture.test/','--targets',value['targets']['path'],
        '--output',str(tmp_path/'publish/canary.json')]
