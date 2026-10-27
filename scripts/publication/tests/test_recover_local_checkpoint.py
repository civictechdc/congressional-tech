"""Focused checks for the explicitly authorized local checkpoint adoption."""
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('recover_local_checkpoint', ROOT/'scripts/publication/recover_local_checkpoint.py')
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(tool, 'EXPECTED_CHUNKS', {'documents':1,'filenames':1})
    archive = tmp_path/'archive'
    root = archive/'run'
    state = root/'publication.renderer-upgrade'
    state.mkdir(parents=True)
    asset = root/'publication/releases/a/file.bin'
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b'unchanged observation bytes')
    old = dict(provenance_revision=tool.ORIGIN, code_runtime=dict(implementation='old',dependencies='runtime',publisher_version=10),
               publisher_version=10, source=dict(sha256='catalog'), native_execution={}, run_id='original',run_attempt='1')
    renderer = dict(preparation=old, source=dict(selector_sha256='catalog'), requirements=dict(policy={},compression={}),previous='old',reviews=None)
    continuation = dict(binding=old,phases={},writes={},versions={},version=1)
    tool.save(root/'continuation.json', continuation)
    dbpath=state/'stages.sqlite'
    with sqlite3.connect(dbpath) as db:
        db.executescript('CREATE TABLE build(binding TEXT,created TEXT);CREATE TABLE progress(task TEXT,result TEXT);'
            'CREATE TABLE chunks(name TEXT,label TEXT);CREATE TABLE discarded(path TEXT);'
            'CREATE TABLE chunk_assets(name TEXT,reference TEXT);')
        db.execute('INSERT INTO build VALUES (?,?)',(tool.canonical_json_bytes(renderer).decode(),'original-created'))
        db.executemany('INSERT INTO chunks VALUES (?,?)',[('doc','documents'),('source','filenames')])
        db.executemany('INSERT INTO progress VALUES (?,?)',[(x,'null') for x in
            ['component-registration','stage:component_scope','component-chunk:doc','component-chunk:source']])
        ref=dict(document_file=dict(path='document',bytes=1,sha256='d'),document_observations=dict(rows=1,files=dict(
            observations=dict(path='observations',bytes=1,sha256='o'),
            observation_rows=dict(path='rows',bytes=1,sha256='r'),
            observation_index=dict(path='index',bytes=1,sha256='i'),
            occurrences=dict(path='flat',row_slices=[[0,1]]))))
        db.execute('INSERT INTO chunk_assets VALUES (?,?)',('doc',json.dumps(ref)))
    inventory=[dict(path=str(p.relative_to(archive)),bytes=p.stat().st_size,sha256=tool.digest(p))
               for p in archive.rglob('*') if p.is_file()]
    manifest=tmp_path/'archive-inventory.json';tool.save(manifest,inventory)
    copied=tmp_path/'copied'
    shutil.copytree(archive,copied)
    code=dict(original_implementation='old',target_implementation='new',target_revision='new-code',
              original_revision=tool.ORIGIN,reviewed_compact_revision=tool.COMPACT)
    identity=dict(implementation='new',dependencies='runtime',publisher_version=10)
    return SimpleNamespace(archive=archive,root=copied/'run',inventory=manifest,code=code,identity=identity,
                           requirements=dict(policy={},compression={},implementation='new-renderer'))


def adopt(f, **changes):
    options=dict(authorization='User explicitly authorized local checkpoint reuse',code=f.code,
                 identity=f.identity,requirements=f.requirements,
                 copy_proof=tool.verify_copy(f.archive,f.root,f.inventory))
    options.update(changes)
    return tool.adopt_copy(f.root,**options)


def test_adopts_only_refs_and_bindings_preserving_archive_and_binary_bytes(tmp_path,monkeypatch):
    f=fixture(tmp_path,monkeypatch)
    before={str(p.relative_to(f.archive)):tool.digest(p) for p in f.archive.rglob('*') if p.is_file()}
    result=adopt(f)
    assert result['reused_chunks']==2 and result['transformed_document_references']==1
    assert before=={str(p.relative_to(f.archive)):tool.digest(p) for p in f.archive.rglob('*') if p.is_file()}
    assert (f.root/'publication/releases/a/file.bin').read_bytes()==b'unchanged observation bytes'
    bound=json.loads((f.root/'continuation.json').read_bytes())['binding']
    assert bound['provenance_revision']=='new-code'
    marker=bound['checkpoint_reuse']
    assert marker['original_preparation_binding']['provenance_revision']==tool.ORIGIN
    assert marker['original_preparation_binding']['run_id']==bound['run_id']=='original'
    with sqlite3.connect(f.root/'publication.renderer-upgrade/stages.sqlite') as db:
        raw,created=db.execute('SELECT binding,created FROM build').fetchone()
        assert json.loads(raw)['preparation']==bound and created=='original-created'
        assert db.execute('SELECT count(*) FROM progress').fetchone()[0]==4
        ref=json.loads(db.execute('SELECT reference FROM chunk_assets').fetchone()[0])
        assert set(ref['document_observations']['files'])=={'observations','observation_rows','observation_index'}


@pytest.mark.parametrize('damage',['bytes','symlink','shared_inode'])
def test_copy_verification_refuses_unsafe_or_changed_copy(tmp_path,monkeypatch,damage):
    f=fixture(tmp_path,monkeypatch)
    p=f.root/'publication/releases/a/file.bin'
    if damage=='bytes':p.write_bytes(b'changed')
    elif damage=='symlink':p.unlink();p.symlink_to(f.archive/'run/publication/releases/a/file.bin')
    else:
        import os
        p.unlink();os.link(f.archive/'run/publication/releases/a/file.bin',p)
    with pytest.raises(ValueError):tool.verify_copy(f.archive,f.root,f.inventory)


@pytest.mark.parametrize('damage',['runtime','source','tasks','policy','authorization'])
def test_adoption_refuses_unqualified_boundary_before_acceptance(tmp_path,monkeypatch,damage):
    f=fixture(tmp_path,monkeypatch)
    options={}
    if damage=='runtime':options['identity']=dict(f.identity,dependencies='changed')
    elif damage=='source':options['code']=dict(f.code,original_implementation='changed')
    elif damage=='policy':options['requirements']=dict(policy={'changed':1},compression={})
    elif damage=='authorization':options['authorization']=''
    else:
        with sqlite3.connect(f.root/'publication.renderer-upgrade/stages.sqlite') as db:
            db.execute("INSERT INTO progress VALUES ('component-entries','null')")
    if damage=='tasks':
        with pytest.raises(ValueError,match='boundary'):
            tool.adopt_copy(f.root,authorization='authorized',code=f.code,identity=f.identity,requirements=f.requirements,copy_proof={})
    else:
        with pytest.raises(ValueError):adopt(f,**options)
    assert not (f.root/tool.RECEIPT).exists()


def test_resume_override_is_scoped_and_explicitly_binds_origin(tmp_path,monkeypatch):
    f=fixture(tmp_path,monkeypatch);adopt(f)
    binding=json.loads((f.root/'continuation.json').read_bytes())['binding']
    from viewer_publication.continuation import Continuation
    assert tool.attempt.Continuation is Continuation
    with tool.authorized_continuation(f.root):
        computed=dict(binding);computed.pop('checkpoint_reuse')
        resumed=tool.attempt.Continuation(f.root,computed,resume=True)
        assert resumed.value['binding']==binding
        assert computed['checkpoint_reuse']['original_preparation_binding']['provenance_revision']==tool.ORIGIN
        with pytest.raises(ValueError):tool.attempt.Continuation(tmp_path/'other',computed,resume=True)
    assert tool.attempt.Continuation is Continuation


def test_local_tool_is_outside_release_identity():
    from viewer_publication.release_identity import source_files
    assert 'scripts/publication/recover_local_checkpoint.py' not in source_files(ROOT)


def test_main_writes_structured_failure_report(tmp_path,monkeypatch):
    report=tmp_path/'result.json'
    monkeypatch.setattr('sys.argv',['recover_local_checkpoint.py','resume','--directory',str(tmp_path/'run'),
        '--native-config',str(tmp_path/'missing-config.json'),'--metadata-cache',str(tmp_path/'cache'),
        '--report',str(report)])
    with pytest.raises(FileNotFoundError):tool.main()
    result=json.loads(report.read_bytes())
    assert result['status']=='failed' and result['command']=='local-checkpoint-resume'
