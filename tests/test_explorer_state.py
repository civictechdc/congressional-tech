"""State storage must preserve stable IDs and fail before restoring corrupt bytes."""
import json
import pytest
from committee_explorer.state import pack,unpack


def test_state_archive_restores_only_supported_state_and_checks_hashes(tmp_path):
    original=tmp_path/'state';original.mkdir()
    (original/'ids.json').write_text('{"identity":"stable"}')
    (original/'publication.json').write_text('{"publication":"one"}')
    (original/'export.lock').touch()
    (original/'issue-history').mkdir();(original/'issue-history'/'one.sqlite').write_bytes(b'retained evidence')
    archive=tmp_path/'packed';manifest=pack(original,archive)
    assert all(p['byte_size']<=50*1024*1024 for p in manifest['parts'])
    target=tmp_path/'restored';assert unpack(archive,target)
    assert (target/'ids.json').read_bytes()==(original/'ids.json').read_bytes()
    assert not (target/'export.lock').exists()
    assert (target/'issue-history'/'one.sqlite').read_bytes()==b'retained evidence'
    (archive/manifest['parts'][0]['path']).write_bytes(b'bad')
    with pytest.raises(ValueError,match='differs'):unpack(archive,tmp_path/'corrupt')
    assert list((tmp_path/'corrupt').iterdir())==[]


def test_missing_prior_state_bootstraps_empty(tmp_path):
    assert not unpack(tmp_path/'missing',tmp_path/'state')
    assert (tmp_path/'state').is_dir()


def test_partial_checkpoint_never_resets_public_identities(tmp_path):
    source=tmp_path/'incomplete';source.mkdir();(source/'0000.part').write_bytes(b'previous IDs')
    with pytest.raises(ValueError,match='manifest is missing'):
        unpack(source,tmp_path/'state')
