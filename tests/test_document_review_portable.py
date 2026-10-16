"""Portable evidence must work without original paths and preserve every byte."""
from copy import deepcopy
import json
from pathlib import Path
import shutil

import pyarrow.parquet as pq
import pytest

from congress_api.retention import document_review_bundle as reader
from congress_api.retention import document_review_portable as portable
from congress_api.retention.document_review_catalog import write_candidates
from congress_api.retention.document_review_receipts import file_digest
from test_document_review_catalog import fixture


def exported(tmp_path,unsupported=False):
    original=tmp_path/'original';original.mkdir()
    args=fixture(original,unsupported);write_candidates(**args)
    summary=args['output']/'summary.json';expected=file_digest(summary)
    output=tmp_path/'export'
    portable.export_bundle(summary,expected,args['sources'],args['documents'],output)
    return args,output/'manifest.json'


@pytest.mark.parametrize('unsupported',[False,True])
def test_relocated_store_works_without_original_files(tmp_path,monkeypatch,unsupported):
    args,manifest=exported(tmp_path,unsupported);pin=file_digest(manifest)
    summary=args['output']/'summary.json'
    expected=reader.load_bundle(summary,file_digest(summary),args['sources'],args['documents'])
    raw_manifest=json.loads(manifest.read_text())
    # Identical evidence bytes share one object even when they have different locators.
    assert len(list((manifest.parent/'objects').iterdir()))==len(set(raw_manifest['locators'].values()))
    moved=tmp_path/'moved';manifest.parent.rename(moved)
    shutil.rmtree(tmp_path/'original')
    elsewhere=tmp_path/'elsewhere';elsewhere.mkdir();monkeypatch.chdir(elsewhere)
    manifest=moved/'manifest.json'
    candidates=portable.load_portable(manifest,pin)
    assert candidates==expected
    source=pq.read_table(portable.resolve_evidence(manifest,pin,str(args['sources']))).to_pylist()
    document=pq.read_table(portable.resolve_evidence(manifest,pin,str(args['documents']))).to_pylist()[0]
    assert reader.select_document(document,source,candidates)==expected['d']
    assert reader.select_document(document,source)['document']==document
    observation=candidates['d']['review']['body_observation']
    assert portable.resolve_evidence(manifest,pin,observation['path']).read_bytes().startswith(b'%PDF-')
    with pytest.raises(ValueError,match='Unbound'):
        portable.resolve_evidence(manifest,pin,'/etc/passwd')


@pytest.mark.parametrize('change',['manifest','missing','bytes','escape','missing_locator','extra_locator','symlink','reader_policy','version'])
def test_portable_store_refuses_missing_or_altered_evidence(tmp_path,change):
    args,manifest=exported(tmp_path);pin=file_digest(manifest);data=json.loads(manifest.read_text())
    pdf=str(tmp_path/'original/body.pdf');target=manifest.parent/'objects'/data['locators'][pdf]
    if change=='manifest':manifest.write_text('{}')
    elif change=='missing':target.unlink()
    elif change=='bytes':target.write_bytes(b'changed')
    elif change=='symlink':target.unlink();target.symlink_to(pdf)
    else:
        if change=='escape':data['locators'][pdf]='../outside'
        elif change=='missing_locator':data['locators'].pop(pdf)
        elif change=='extra_locator':data['locators']['unbound']=data['locators'][pdf]
        elif change=='reader_policy':data['reader_policy']={}
        else:data['portable_version']=True
        manifest.write_text(json.dumps(data));pin=file_digest(manifest)
    with pytest.raises((ValueError,FileNotFoundError)):
        portable.load_portable(manifest,pin)


def test_portable_policy_allows_new_install_path_but_not_different_code(tmp_path,monkeypatch):
    args,manifest=exported(tmp_path);pin=file_digest(manifest)
    original=reader.implementation();moved=deepcopy(original)
    moved['source_sha256']={str(Path('/different/install')/Path(p).name):h for p,h in original['source_sha256'].items()}
    monkeypatch.setattr(reader,'implementation',lambda:moved)
    assert portable.load_portable(manifest,pin)['d']['status']=='candidate_applied'
    summary=args['output']/'summary.json'
    with pytest.raises(ValueError,match='implementation'):
        reader.load_bundle(summary,file_digest(summary),args['sources'],args['documents'])
    moved['source_sha256'][next(iter(moved['source_sha256']))]='0'*64
    with pytest.raises(ValueError,match='implementation'):portable.load_portable(manifest,pin)


def test_manifest_rechecked_after_loading(tmp_path,monkeypatch):
    _,manifest=exported(tmp_path);pin=file_digest(manifest);original=reader._load_bundle
    def changed(*args,**kwargs):
        result=original(*args,**kwargs);manifest.write_text('{}');return result
    monkeypatch.setattr(reader,'_load_bundle',changed)
    with pytest.raises(ValueError,match='digest'):portable.load_portable(manifest,pin)


def test_failed_copy_has_no_completion_marker_and_cannot_be_reused(tmp_path,monkeypatch):
    original=tmp_path/'original';original.mkdir();args=fixture(original);write_candidates(**args)
    summary=args['output']/'summary.json';output=tmp_path/'export'
    monkeypatch.setattr(portable.shutil,'copyfileobj',lambda incoming,outgoing,**kwargs:outgoing.write(b'broken'))
    with pytest.raises(ValueError,match='digest'):
        portable.export_bundle(summary,file_digest(summary),args['sources'],args['documents'],output)
    assert not (output/'manifest.json').exists()
    with pytest.raises(FileExistsError):
        portable.export_bundle(summary,file_digest(summary),args['sources'],args['documents'],output)
