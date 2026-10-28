"""A display-only seed can be viewed but never supplies capture authority."""
import json
from pathlib import Path

import pytest

from test_capture_scheduler import ASOF,IDENTITY,PublicSession,engine,release


MARKERS=[dict(origin=dict(kind='seed_v5',display_only=False)),
         dict(origin=dict(kind='model',display_only=True)),
         dict(origin=dict(kind='model'),display_only=True)]


def marked_manifest(root,marker):
    path=root/'manifest.json';manifest=json.loads(path.read_text())
    identity=manifest['release_id'];manifest.update(marker)
    path.write_text(json.dumps(manifest))
    assert json.loads(path.read_text())['release_id']==identity


@pytest.mark.parametrize('marker',MARKERS)
def test_display_only_public_release_stops_after_pointer_and_manifest(tmp_path,marker):
    from congress_api.acquisition.capture_scheduler import load_release
    root=release(tmp_path,[]);marked_manifest(root,marker)
    session=PublicSession(root)
    with pytest.raises(ValueError,match='display-only.*capture'):
        load_release(pointer='https://public.fixture/current.json',session=session,work=tmp_path/'read')
    assert [url.rsplit('/',1)[1] for url,_ in session.calls]==['current.json','manifest.json']
    assert not (tmp_path/'read/url_state.parquet').exists()
    assert not (tmp_path/'read/capture_scope.json').exists()


@pytest.mark.parametrize('marker',MARKERS)
def test_display_only_local_manifest_refuses_before_scheduler_file_access(tmp_path,marker):
    from congress_api.acquisition.capture_scheduler import load_release
    root=release(tmp_path,[]);marked_manifest(root,marker)
    for name in ('url_state.parquet','capture_scope.json','capture_profile.json','url_variants.parquet'):
        (root/name).unlink()
    with pytest.raises(ValueError,match='display-only.*capture'):
        load_release(release_root=root,work=tmp_path/'read')


@pytest.mark.parametrize('selected',[
    dict(origin=dict(kind='seed_v5')),
    dict(origin='local',manifest_origin=dict(kind='model',display_only=True)),
    dict(origin='public',display_only=True)])
@pytest.mark.parametrize('entrypoint',['binding','plan','capture','cutoffs'])
def test_hand_built_seed_metadata_refuses_before_any_scheduler_effect(tmp_path,selected,entrypoint):
    from congress_api.acquisition.capture_scheduler import _url_binding,plan_queue,run_capture,cutoff_report
    class Never:
        def run_job(self,*_):raise AssertionError('Seed reached native scheduling')
        def put(self,*_):raise AssertionError('Seed wrote raw data')
        def hop(self,*_,**__):raise AssertionError('Seed fetched a URL')
    native=Never();work=tmp_path/'work'
    with pytest.raises(ValueError,match='display-only.*capture'):
        if entrypoint=='binding':_url_binding(selected,native)
        elif entrypoint=='plan':plan_queue(selected,engine=native,work=work,as_of=ASOF,request_budget=1)
        elif entrypoint=='capture':run_capture(selected,engine=native,work=work,as_of=ASOF,
            request_budget=1,byte_budget=1,spool_budget=1,store=native,identity=IDENTITY,direct=native)
        else:cutoff_report(selected,urls=(),attempted=tmp_path/'missing-attempts',engine=native,
            work=work,as_of=ASOF,stop_reason=None)
    assert not work.exists()


def test_loaded_model_origin_is_retained_for_later_capture_admission(tmp_path):
    from congress_api.acquisition.capture_scheduler import load_release
    root=release(tmp_path,[]);origin=dict(kind='model',gaps=[])
    marked_manifest(root,dict(origin=origin))
    selected=load_release(release_root=root,work=tmp_path/'read')
    assert selected['manifest_origin']==origin and selected['origin']=='local'
    assert selected['release_id']==json.loads((root/'manifest.json').read_text())['release_id']
    assert Path(selected['state']).read_bytes()==(root/'url_state.parquet').read_bytes()
