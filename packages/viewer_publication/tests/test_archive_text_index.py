"""The normal publication finalizer pins a complete derivative before checkpoint/selection."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import os
from types import SimpleNamespace

import pytest

from viewer_publication.archive_text_index import (finish_text_index,source_data_id,validate_policy,validate_attachment)

ROOT=Path(__file__).parents[3]


def fake_app(policy, calls, fail=False):
    def run(command,**kwargs):
        calls.append(command)
        if '--plan' in command:
            return SimpleNamespace(stdout=json.dumps(dict(definition={'sha256':policy['definition']})))
        if fail:
            raise RuntimeError('interrupted while indexing')
        manifest=json.loads(Path(command[command.index('--manifest')+1]).read_bytes())
        report=dict(state='complete',pending_bodies=0,source_data_id=source_data_id(manifest),
            definition={'sha256':policy['definition']},coverage={'by_source_kind':[{'kind':'document','state':'indexed','count':1}]})
        output=Path(command[command.index('--output')+1])
        with sqlite3.connect(output) as db:
            db.execute('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)')
            db.execute('INSERT INTO meta VALUES(?,?)',['artifact',json.dumps(report)])
        return SimpleNamespace(stdout=json.dumps(report))
    return run


def fixture(tmp_path):
    root=tmp_path/'release'
    shutil.copytree(ROOT/'model/fixtures/archive-contract/current',root)
    policy=dict(python='/own/app/.venv/bin/python',work=str(tmp_path/'durable'),archive_origin='https://archive.example',
        definition='d'*64,body_timeout=120,memory_mb=768,max_work_bytes=32<<30,min_free_bytes=15<<30)
    return root,policy


def test_derivative_attaches_atomically_and_reuses_completion(tmp_path,monkeypatch):
    root,policy=fixture(tmp_path)
    original=json.loads((root/'manifest.json').read_bytes())
    original_bytes={path.name:sha256(path.read_bytes()).hexdigest() for path in root.glob('*.parquet')}
    calls=[]
    monkeypatch.setattr('viewer_publication.archive_text_index.subprocess',SimpleNamespace(run=fake_app(policy,calls)))
    value=finish_text_index({'text_index':policy},root)
    assert value['release_id']!=original['release_id']
    assert value['text_index']['source_data_id']==source_data_id(original)==source_data_id(value)
    assert value['files'][-1]['name']=='search_index.sqlite' and value['files'][-1]['producer']=='verified-corpus-text-index'
    assert original_bytes=={path.name:sha256(path.read_bytes()).hexdigest() for path in root.glob('*.parquet')}
    assert finish_text_index({'text_index':policy},root)==value and len(calls)==2
    changed=deepcopy(value);changed['files'][0]['coverage']['gaps'].append('Different source meaning')
    with pytest.raises(ValueError,match='different source data'):
        validate_attachment(changed,root,policy['definition'])


def test_interrupted_index_keeps_native_manifest_and_recovers_snapshot(tmp_path,monkeypatch):
    root,policy=fixture(tmp_path)
    original=(root/'manifest.json').read_bytes()
    calls=[]
    monkeypatch.setattr('viewer_publication.archive_text_index.subprocess',SimpleNamespace(run=fake_app(policy,calls,fail=True)))
    with pytest.raises(RuntimeError,match='interrupted'):
        finish_text_index({'text_index':policy},root)
    assert (root/'manifest.json').read_bytes()==original
    # Simulate a lost process response after its immutable snapshot was written.
    good=fake_app(policy,[])
    good([policy['python'],'--manifest',str(root/'manifest.json'),'--output',str(root/'search_index.sqlite')])
    def only_plan(command,**kwargs):
        assert '--plan' in command,'A retained complete snapshot must not rerun extraction'
        return SimpleNamespace(stdout=json.dumps(dict(definition={'sha256':policy['definition']})))
    monkeypatch.setattr('viewer_publication.archive_text_index.subprocess',SimpleNamespace(run=only_plan))
    assert finish_text_index({'text_index':policy},root)['text_index']['definition']==policy['definition']


def test_actual_app_definition_refuses_before_index_payloads(tmp_path,monkeypatch):
    root,policy=fixture(tmp_path)
    def wrong(command,**kwargs):
        assert '--plan' in command
        return SimpleNamespace(stdout=json.dumps(dict(definition={'sha256':'0'*64})))
    monkeypatch.setattr('viewer_publication.archive_text_index.subprocess',SimpleNamespace(run=wrong))
    with pytest.raises(ValueError,match='definition changed'):
        finish_text_index({'text_index':policy},root)
    assert not (root/'search_index.sqlite').exists()


def test_policy_preserves_venv_executable_path_and_has_explicit_limits(tmp_path):
    executable=tmp_path/'app/.venv/bin/python'
    executable.parent.mkdir(parents=True);executable.symlink_to('/usr/bin/true')
    _,policy=fixture(tmp_path/'fixtures')
    policy['python']='app/.venv/bin/python'
    result=validate_policy(policy,tmp_path)
    assert result['python']==str(executable)
    assert result['python']!='/usr/bin/true'
    assert result['min_free_bytes']==15<<30


def test_native_controller_resumes_index_before_checkpoint_without_model_replay(tmp_path,monkeypatch):
    from archive_job_fixture import real_model_spec
    from docspec_client.client import NativeDatasets
    from test_archive_controller import Runtime
    from test_archive_publish import Store
    from viewer_publication.archive_controller import run_publish
    from viewer_publication.archive_model_job import load_spec
    import viewer_publication.archive_controller as controller
    spec,_,_=real_model_spec(tmp_path)
    # The app subprocess is mocked below; this controller fixture needs only an existing interpreter.
    policy=dict(python=sys.executable,work=str(tmp_path/'index-work'),
        archive_origin='https://archive.example',definition='d'*64,body_timeout=120,memory_mb=768,
        max_work_bytes=32<<30,min_free_bytes=15<<30)
    spec['text_index']=policy
    path=tmp_path/'model-spec.json';path.write_text(json.dumps(spec))
    spec=load_spec(path)
    store=Store();calls=[];builds=[]
    native_build=controller.build_prepared_release
    def tracked(*args,**kwargs):
        builds.append(True)
        return native_build(*args,**kwargs)
    monkeypatch.setattr(controller,'build_prepared_release',tracked)
    monkeypatch.setattr('viewer_publication.archive_text_index.subprocess',SimpleNamespace(run=fake_app(policy,calls,fail=True)))
    def probe(**context):
        assert context['manifest']['text_index']['definition']==policy['definition']
        return dict(status='passed',releaseId=context['release_id'],targets='owner-approved')
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as native:
        kwargs=dict(first_release=True,client=store,engine=Runtime(native,store),bucket='derived-fixture',
            receipt_keys=['receipts/documents/2026-10-27/slice.jsonl.gz'],provenance=[],run={'id':'indexed'},
            public_origin='https://archive.fixture.test',contract=probe,canary=probe,work=tmp_path/'publish')
        with pytest.raises(RuntimeError,match='interrupted while indexing'):
            run_publish(spec,**kwargs)
        assert (tmp_path/'publish/model-intent.json').exists()
        assert not (tmp_path/'publish/completed-model.json').exists()
        monkeypatch.setattr('viewer_publication.archive_text_index.subprocess',SimpleNamespace(run=fake_app(policy,calls)))
        result=run_publish(spec,resume=True,**kwargs)
        assert result['status']=='published' and len(builds)==1
        checkpoint=json.loads((tmp_path/'publish/completed-model.json').read_bytes())
        manifest_path=Path(checkpoint['manifest_pin']['path'])
        manifest=json.loads(manifest_path.read_bytes())
        assert manifest['text_index']['definition']==policy['definition']
        assert checkpoint['manifest_pin']['sha256']==sha256(manifest_path.read_bytes()).hexdigest()
        assert checkpoint['profile']['profile']['text_index']['definition']==policy['definition']
