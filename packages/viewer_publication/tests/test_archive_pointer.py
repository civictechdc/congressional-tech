"""Current pointers retain exact durable evidence before interpretation."""
import json
from hashlib import sha256
import os

import pytest

from test_archive_publish import Store

CURRENT=b'{"release_id":"'+b'a'*64+b'","previous_release_id":null}'


@pytest.mark.parametrize('raw',[CURRENT,b'{"release_id":"'+b'b'*64+b'","previous_release_id":"'+b'a'*64+b'"}'],ids=['first','successor'])
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
    store=Store();raw=CURRENT;store.objects['viewer-publications/manifest.json']=raw
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
    store=Store();store.objects['viewer-publications/manifest.json']=CURRENT
    evidence=tmp_path/'outgoing-pointer.json';response=evidence.with_suffix('.response.json')
    response.write_bytes(b'previous held response')
    with pytest.raises(FileExistsError):read_pointer(store,bucket='derived-fixture',evidence=evidence)
    assert response.read_bytes()==b'previous held response' and store.requests==[]


def test_pointer_directory_sync_failure_prevents_decode_and_publication(tmp_path,monkeypatch):
    import stat
    import viewer_publication.archive_publish as publication
    store=Store();store.objects['viewer-publications/manifest.json']=CURRENT
    evidence=tmp_path/'outgoing-pointer.json';fsync=os.fsync
    def sync_or_fail_directory(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):raise OSError('Injected directory sync failure')
        return fsync(fd)
    monkeypatch.setattr(os,'fsync',sync_or_fail_directory)
    monkeypatch.setattr(publication.json,'loads',lambda _:pytest.fail('Decode preceded durable evidence'))
    with pytest.raises(OSError,match='Injected directory sync failure'):
        publication.read_pointer(store,bucket='derived-fixture',evidence=evidence)
    assert evidence.read_bytes()==CURRENT and store.requests==[]


@pytest.mark.parametrize('raw',[b'{"unexpected":"shape"}',b'{"version":1,"catalog_id":"retired-format"}',b'null'])
def test_unknown_pointer_refuses_and_retains_exact_evidence(tmp_path,raw):
    from viewer_publication.archive_publish import read_pointer
    store=Store();store.objects['viewer-publications/manifest.json']=raw
    evidence=tmp_path/'outgoing.json'
    with pytest.raises(ValueError,match='pointer'):
        read_pointer(store,bucket='derived-fixture',evidence=evidence)
    assert evidence.read_bytes()==raw
    assert json.loads(evidence.with_suffix('.response.json').read_text())==dict(
        etag='initial',sha256=sha256(raw).hexdigest(),bytes=len(raw))
    assert store.requests==[]
