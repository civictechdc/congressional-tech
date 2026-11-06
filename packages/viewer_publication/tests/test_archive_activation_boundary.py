"""No application checkpoint or missing native intent can authorize activation."""
from pathlib import Path

import pytest


def test_external_activation_refuses_before_creating_work(tmp_path):
    from viewer_publication.archive_publish_job import execute
    with pytest.raises(ValueError,match='no qualified frozen publication intent'):
        execute(dict(work=str(tmp_path/'publish'),_model=dict(scratch=str(tmp_path/'model'))))
    assert not list(tmp_path.iterdir())


def test_retired_daily_checkpoint_is_not_a_resume_selector(tmp_path):
    from viewer_publication.archive_publish_job import nightly_spec
    root=tmp_path/'nightly';old=root/'archive-publish';old.mkdir(parents=True)
    (old/'completed-model.json').write_text('{"untrusted":"retired state"}')
    original=(old/'completed-model.json').read_bytes()
    value=nightly_spec(dict(_daily=dict(receipt_families=['documents']),_model={}),root)
    assert 'resume' not in value
    assert Path(value['_model']['scratch'])==root/'archive-model'
    assert (old/'completed-model.json').read_bytes()==original


def test_nightly_refuses_before_checkout_setup_or_retirement(tmp_path,monkeypatch):
    import importlib.util
    root=Path(__file__).parents[3]
    spec=importlib.util.spec_from_file_location('nightly_current',root/'scripts/nightly_publish.py')
    nightly=importlib.util.module_from_spec(spec);spec.loader.exec_module(nightly)
    candidate=tmp_path/'candidate';candidate.mkdir()
    paths=[candidate/'release-request.json',candidate/'accepted-native-export.parquet']
    for path in paths:path.write_bytes(b'original retained bytes')
    before={path:(path.read_bytes(),path.stat()) for path in paths}
    def must_not_run(*args,**kwargs):
        pytest.fail('Unavailable publication reached checkout setup')
    monkeypatch.setattr(nightly,'main_checkout',must_not_run)
    assert nightly.main([])==2
    assert nightly.run(tmp_path,False)==2
    for path,(content,stat) in before.items():
        assert path.read_bytes()==content
        assert (path.stat().st_ino,path.stat().st_mtime_ns)==(stat.st_ino,stat.st_mtime_ns)
