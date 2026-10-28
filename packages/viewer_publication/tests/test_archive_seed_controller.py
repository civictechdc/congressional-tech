"""The actual native seed producer feeds the existing publication path."""
import json
import os
from pathlib import Path

import pytest


def publication(tmp_path):
    from test_archive_seed import seed_spec
    from test_archive_publish_job import publish_spec
    from congress_api.retention.provenance import file_pin
    value=publish_spec(tmp_path);seed,_=seed_spec(tmp_path)
    return dict(value,model_kind='seed_v5',model_spec=dict(path=str(seed),**file_pin(seed)),
        receipt_keys=[],provenance=[])


def test_seed_startup_plan_reads_only_pinned_job_metadata(tmp_path,capsys):
    from test_archive_publish_job import invoke
    from congress_api.retention.provenance import file_pin
    value=publication(tmp_path);path=Path(value['model_spec']['path']);seed=json.loads(path.read_text())
    for item in seed['input_files'].values():Path(item['path']).unlink()
    seed['engine_config']=str(tmp_path/'unopened-runtime.json');path.write_text(json.dumps(seed))
    value['model_spec']=dict(path=str(path),**file_pin(path))
    Path(value['targets']['path']).unlink()
    assert invoke(tmp_path,value,'--plan')==0
    plan=json.loads(capsys.readouterr().out)
    assert plan['model_kind']=='seed_v5' and plan['executed'] is False
    assert not Path(value['work']).exists() and not Path(seed['scratch']).exists()


@pytest.mark.parametrize('change',['daily','receipts','provenance','kind'])
def test_seed_startup_rejects_raw_authority_before_runtime_or_storage(tmp_path,capsys,change):
    from test_archive_publish_job import invoke
    value=publication(tmp_path)
    if change=='daily':value['daily']=dict(path='unopened-daily.json',sha256='a'*64,size=1)
    elif change=='receipts':value['receipt_keys']=['receipts/not-seed.jsonl.gz']
    elif change=='provenance':value['provenance']=[dict(key='provenance/reviews/a.jsonl',etag='etag')]
    else:value['model_kind']='unknown'
    with pytest.raises(SystemExit) as error:invoke(tmp_path,value,'--execute')
    assert error.value.code==2 and ('seed' in capsys.readouterr().err.lower() or change=='kind')
    assert not Path(value['work']).exists()


def test_actual_native_seed_publishes_through_existing_transport(tmp_path):
    from test_archive_seed import seed_spec
    from test_archive_controller import Runtime
    from test_archive_publish import Store
    from docspec_client.client import NativeDatasets
    from viewer_publication.archive_controller import run_seed_publish
    from viewer_publication.archive_seed import load_seed_spec
    path,_=seed_spec(tmp_path);spec=load_seed_spec(path);store=Store();contexts=[]
    def probe(**context):
        assert context['manifest']['origin']['kind']=='seed_v5'
        assert context['manifest']['origin']['display_only'] is True
        assert type(context['probe_selectors']['saved_row']) is int
        contexts.append(context)
        return dict(status='passed',releaseId=context['release_id'],targets='measured')
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as native:
        result=run_seed_publish(spec,client=store,engine=Runtime(native,store),bucket='derived-fixture',
            work=tmp_path/'publish',run={'id':'seed-fixture'},public_origin='https://archive.fixture.test',
            contract=probe,canary=probe)
    assert result['status']=='published' and result['label']=='seed: v5 catalog bbbbbbbb'
    assert len(contexts)==2 and 'viewer-publications/manifest.json' in store.objects
    keys=[key for key in store.objects if '/inputs/' in key and key.endswith('.json')]
    assert len(keys)==1
    record=json.loads(store.objects[keys[0]])
    assert record['profile']['kind']=='seed_v5' and record['snapshots']=={} and record['provenance']==[]
