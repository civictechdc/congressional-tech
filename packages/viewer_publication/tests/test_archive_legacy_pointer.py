"""First engine publication replaces the exact old pointer through its ETag."""
import json
from hashlib import sha256
import os
from pathlib import Path

import pytest

from archive_job_fixture import real_model_spec
from docspec_client.client import NativeDatasets
from test_archive_controller import Runtime
from test_archive_publish import Store

OLD=Path(__file__).parents[3]/'apps/site/scripts/fixtures/old-viewer-pointer.json'


@pytest.mark.parametrize('raw',[OLD.read_bytes(),b'{"release_id":"'+b'a'*64+b'","previous_release_id":null}'])
def test_outgoing_pointer_retains_opaque_etag_bound_to_exact_bytes(tmp_path,raw):
    from viewer_publication.archive_publish import read_pointer
    store=Store();store.etag='"opaque-v42/abcdef=="';store.objects['viewer-publications/manifest.json']=raw
    evidence=tmp_path/'outgoing-pointer.json'
    _,etag=read_pointer(store,bucket='derived-fixture',evidence=evidence)
    assert evidence.read_bytes()==raw
    assert json.loads(evidence.with_suffix('.response.json').read_text())==dict(
        etag=etag,sha256=sha256(raw).hexdigest(),bytes=len(raw))
    assert etag==store.etag and store.pointer_gets==1 and store.requests==[]


def test_pointer_response_evidence_survives_later_decode_failure(tmp_path,monkeypatch):
    import viewer_publication.archive_publish as publication
    store=Store();raw=OLD.read_bytes();store.objects['viewer-publications/manifest.json']=raw
    evidence=tmp_path/'outgoing-pointer.json';loads=json.loads
    def decode_failure(value):
        assert evidence.read_bytes()==raw
        assert loads(evidence.with_suffix('.response.json').read_text())==dict(
            etag='initial',sha256=sha256(raw).hexdigest(),bytes=len(raw))
        raise ValueError('Injected pointer decode failure')
    monkeypatch.setattr(publication.json,'loads',decode_failure)
    with pytest.raises(ValueError,match='Injected pointer decode failure'):
        publication.read_pointer(store,bucket='derived-fixture',evidence=evidence)
    assert store.requests==[]


def test_pointer_response_evidence_is_never_overwritten(tmp_path):
    from viewer_publication.archive_publish import read_pointer
    store=Store();store.objects['viewer-publications/manifest.json']=OLD.read_bytes()
    evidence=tmp_path/'outgoing-pointer.json';response=evidence.with_suffix('.response.json')
    response.write_bytes(b'previous held response')
    with pytest.raises(FileExistsError):read_pointer(store,bucket='derived-fixture',evidence=evidence)
    assert response.read_bytes()==b'previous held response' and store.requests==[]


def test_legacy_pointer_has_no_engine_predecessor_but_retains_exact_evidence(tmp_path):
    from viewer_publication.archive_publish import read_pointer
    store=Store();raw=OLD.read_bytes();store.objects['viewer-publications/manifest.json']=raw
    evidence=tmp_path/'outgoing.json'
    assert read_pointer(store,bucket='derived-fixture',evidence=evidence)==(None,'initial')
    assert evidence.read_bytes()==raw and len(raw)==1907
    store.objects['viewer-publications/manifest.json']=b'{"unexpected":"shape"}'
    with pytest.raises(ValueError,match='pointer'):
        read_pointer(store,bucket='derived-fixture')


def test_actual_model_first_flip_uses_old_etag_and_no_old_release(tmp_path):
    from viewer_publication.archive_controller import run_publish
    from viewer_publication.archive_model_job import load_spec
    spec,_,_=real_model_spec(tmp_path);path=tmp_path/'model.json';path.write_text(json.dumps(spec))
    store=Store();raw=OLD.read_bytes();store.objects['viewer-publications/manifest.json']=raw
    legacy_key='viewer-publications/releases/old-filename-viewer/index.html';store.objects[legacy_key]=b'legacy'
    def passed(**context):return dict(status='passed',releaseId=context['release_id'],targets='owner-approved')
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as native:
        result=run_publish(load_spec(path),work=tmp_path/'publish',client=store,engine=Runtime(native,store),
            bucket='derived-fixture',receipt_keys=['receipts/documents/2026-10-27/slice.jsonl.gz'],provenance=[],
            run={'id':'first-engine'},public_origin='https://archive.fixture.test',contract=passed,canary=passed)
    assert result['status']=='published'
    pointer=json.loads(store.objects['viewer-publications/manifest.json'])
    assert pointer==dict(release_id=result['release_id'],previous_release_id=None)
    put=next(r for r in store.requests if r['Key']=='viewer-publications/manifest.json')
    assert put['IfMatch']=='initial' and 'IfNoneMatch' not in put
    assert (tmp_path/'publish/outgoing-pointer.json').read_bytes()==raw
    assert ('get',legacy_key) not in store.events and store.objects[legacy_key]==b'legacy'
