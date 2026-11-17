"""ct-31qi: a hosted re-run resumes the candidate a stopped run kept, only when it is this run's.

The real controller and native model run here; only the object store and site probes are fakes.
Each "next runner" receives just what the Actions cache carries (kept_candidate_paths).
"""
import json
import os
from pathlib import Path

import pytest

from archive_job_fixture import next_hosted_runner,real_model_spec
from docspec_client.client import NativeDatasets
from test_archive_controller import GATED_GROUPS,Runtime
from test_archive_publish import Store
from test_release_gate import record_for,release_dir

POINTER='viewer-publications/manifest.json'


@pytest.fixture
def gated(tmp_path,monkeypatch):
    """A live release the fixture candidate replaces only with a recorded cause; counted builds."""
    from viewer_publication import archive_controller
    spec,_,_=real_model_spec(tmp_path)
    store=Store();ids={}
    for name,documents in [('live',['Q']),('history',['H'])]:
        manifest=release_dir(tmp_path/name,documents);ids[name]=manifest['release_id']
        for item in manifest['files']+[dict(name='manifest.json')]:
            store.objects['viewer-publications/releases/'+manifest['release_id']+'/'+item['name']]=(tmp_path/name/item['name']).read_bytes()
    store.objects[POINTER]=json.dumps(dict(release_id=ids['live'],previous_release_id=ids['history'])).encode()
    builds=[];build=archive_controller.build_prepared_release
    monkeypatch.setattr(archive_controller,'build_prepared_release',lambda *args,**kwargs:builds.append(True) or build(*args,**kwargs))
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as native:
        yield dict(spec=spec,store=store,ids=ids,builds=builds,engine=Runtime(native,store),tmp_path=tmp_path)


def publish(gated,**changes):
    """One hosted run's publish step: the job's kept-candidate path over the actual controller."""
    from viewer_publication.archive_controller import run_publish
    from viewer_publication.archive_model_job import load_spec
    from viewer_publication.archive_publish_job import publish_kept_candidate
    tmp_path=gated['tmp_path'];path=tmp_path/'model-spec.json';path.write_text(json.dumps(gated['spec']))
    model=load_spec(path)
    def passed(**context):return dict(status='passed',releaseId=context['release_id'],targets='owner-approved')
    options=dict(dict(client=gated['store'],engine=gated['engine'],bucket='derived-fixture',work=tmp_path/'publish',
        receipt_keys=['receipts/documents/2026-10-27/slice.jsonl.gz'],provenance=[],run={'id':'gated'},
        public_origin='https://archive.fixture.test',contract=passed,canary=passed,link_history=[gated['ids']['history']]),
        **changes)
    return publish_kept_candidate(lambda resume:run_publish(model,resume=resume,**options),
        work=options['work'],model=model,engine=gated['engine'])


def next_runner(gated):
    from viewer_publication.archive_publish_job import kept_candidate_paths
    tmp_path=gated['tmp_path'];spec=gated['spec']
    next_hosted_runner(tmp_path/'actions-cache',kept=kept_candidate_paths(tmp_path/'publish',spec),
        owned=[tmp_path/'publish',spec['output'],spec['scratch']])


def test_a_stopped_run_resumes_at_the_gates_without_a_rebuild_and_a_live_one_is_not_published_again(gated):
    with pytest.raises(ValueError,match='no recorded cause'):publish(gated)
    checkpoint=(gated['tmp_path']/'publish/completed-model.json').read_bytes()
    candidate=json.loads((Path(gated['spec']['output'])/'manifest.json').read_text())['release_id']
    next_runner(gated)
    # Re-run before the record is committed: the same gate refuses the kept candidate again.
    with pytest.raises(ValueError,match='no recorded cause'):publish(gated)
    assert len(gated['builds'])==1
    next_runner(gated)
    causes=record_for(gated['ids']['live'],candidate,gated['tmp_path'],groups=GATED_GROUPS)
    result=publish(gated,release_causes=causes)
    assert result['status']=='published' and result['release_id']==candidate
    assert len(gated['builds'])==1 and (gated['tmp_path']/'publish/completed-model.json').read_bytes()==checkpoint
    # The run went red after the flip (say the hosted MCP check): its re-run finds its own release live.
    flips=gated['store'].events.count(('put',POINTER))
    next_runner(gated)
    assert publish(gated,release_causes=causes)['status']=='release_unchanged'
    assert len(gated['builds'])==1 and gated['store'].events.count(('put',POINTER))==flips


@pytest.mark.parametrize('change',['inputs','definitions','checkpoint_missing','checkpoint_corrupt','release_file','evidence'])
def test_a_kept_candidate_that_is_not_this_runs_is_deleted_and_rebuilt_never_published(gated,monkeypatch,change):
    from viewer_publication import archive_model_profile
    from viewer_publication.archive_publish_job import _kept_candidate_damage
    with pytest.raises(ValueError,match='no recorded cause'):publish(gated)
    work=gated['tmp_path']/'publish';output=Path(gated['spec']['output']);scratch=Path(gated['spec']['scratch'])
    built=json.loads((work/'completed-model.json').read_text())
    next_runner(gated)
    changes={}
    if change=='inputs':
        # The identity digests the model's table pins, receipt keys, provenance and run alike;
        # test_archive_publish_job's hosted-new-receipts case changes it through the daily ingest.
        changes['run']={'id':'new receipts'}
    elif change=='definitions':
        hashes=archive_model_profile._definition_hashes
        monkeypatch.setattr(archive_model_profile,'_definition_hashes',lambda root:dict(hashes(root),**{'model/sql/changed.sql':'0'*64}))
    elif change=='checkpoint_missing':(work/'completed-model.json').unlink()  # a cache that lost its checkpoint
    elif change=='checkpoint_corrupt':(work/'completed-model.json').write_text('{')
    elif change=='release_file':
        with (output/'list.parquet').open('ab') as damaged:damaged.write(b'changed')
    else:(scratch/'evidence/recording_video_links.parquet').unlink()
    live=gated['store'].objects[POINTER]
    # The rebuilt candidate meets the same gate; nothing kept was published or left behind.
    with pytest.raises(ValueError,match='no recorded cause'):publish(gated,**changes)
    assert len(gated['builds'])==2 and gated['store'].objects[POINTER]==live
    rebuilt=json.loads((work/'completed-model.json').read_text())
    assert _kept_candidate_damage(work,dict(output=str(output),scratch=str(scratch)),gated['engine']) is None
    assert (rebuilt['identity']!=built['identity'])==(change=='inputs')
    assert (rebuilt['profile']['profile']['file_hashes']!=built['profile']['profile']['file_hashes'])==(change=='definitions')


def test_keep_candidate_is_an_execute_option_apart_from_the_mac_nightly(tmp_path,capsys):
    from viewer_publication.archive_publish_job import main
    for args in (['--plan','--keep-candidate'],['--execute','--keep-candidate','--nightly-work',str(tmp_path)]):
        with pytest.raises(SystemExit) as error:main(['--spec',str(tmp_path/'unread.json'),*args])
        assert error.value.code==2 and '--keep-candidate requires' in capsys.readouterr().err
