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


def old_compact_adoption(tmp_path,monkeypatch):
    f=fixture(tmp_path,monkeypatch)
    f.code['target_revision']=tool.COMPACT_RUNTIME
    adopt(f)
    path=f.root/'continuation.json'
    c=json.loads(path.read_bytes())
    marker=c['binding']['checkpoint_reuse']
    marker['recovery_tool_sha256']=tool.ORIGINAL_TOOL_SHA256
    tool.save(f.root/tool.RECEIPT,marker);tool.save(path,c)
    result=json.loads((f.root/'checkpoint-adoption-result.json').read_bytes())
    result['receipt_sha256']=tool.digest(f.root/tool.RECEIPT)
    tool.save(f.root/'checkpoint-adoption-result.json',result)
    with sqlite3.connect(f.root/'publication.renderer-upgrade/stages.sqlite') as db:
        renderer=json.loads(db.execute('SELECT binding FROM build').fetchone()[0])
        renderer['preparation']=c['binding']
        db.execute('UPDATE build SET binding=?',(tool.canonical_json_bytes(renderer).decode(),))
        db.execute('CREATE TABLE assets(path TEXT,bytes INTEGER,sha256 TEXT)')
        db.execute('INSERT INTO assets VALUES (?,?,?)',('releases/a/file.bin',27,'original-asset-hash'))
        db.execute("INSERT INTO progress VALUES ('source-route:completed-leaf','{\"retained\":true}')")
        db.execute("INSERT INTO progress VALUES ('component-entries','null')")
    f.optimized_code=dict(f.code,compact_implementation='new',target_implementation='optimized',
                          target_revision='optimized-head',reviewed_source_cache_revision=tool.SOURCE_CACHE)
    f.optimized_identity=dict(f.identity,implementation='optimized')
    f.optimized_requirements=dict(f.requirements,implementation='optimized-renderer')
    return f


def rebind(f,**changes):
    options=dict(authorization='User authorized exact source-cache checkpoint reuse',
                 code=f.optimized_code,identity=f.optimized_identity,requirements=f.optimized_requirements)
    options.update(changes)
    return tool.rebind_copy(f.root,**options)


def states(f):
    with sqlite3.connect(f.root/'publication.renderer-upgrade/stages.sqlite') as db:
        return {name:db.execute('SELECT * FROM '+name).fetchall() for name in ('progress','assets','chunks','chunk_assets')}


def test_rebind_preserves_all_tasks_assets_references_and_origin(tmp_path,monkeypatch):
    f=old_compact_adoption(tmp_path,monkeypatch)
    before=states(f)
    previous=json.loads((f.root/'continuation.json').read_bytes())['binding']
    result=rebind(f)
    assert result['status']=='rebound_local_checkpoint' and result['reused_chunks']==2
    assert states(f)==before
    binding=json.loads((f.root/'continuation.json').read_bytes())['binding']
    marker=binding['checkpoint_reuse']
    assert binding['provenance_revision']=='optimized-head'
    assert marker['previous_preparation_binding']==previous
    assert marker['previous_preparation_binding']['checkpoint_reuse']['original_preparation_binding']['provenance_revision']==tool.ORIGIN
    assert marker['code']['reviewed_source_cache_revision']==tool.SOURCE_CACHE
    assert marker['reused_tasks']==sorted(row[0] for row in before['progress'])
    with sqlite3.connect(f.root/'publication.renderer-upgrade/stages.sqlite') as db:
        raw,created=db.execute('SELECT binding,created FROM build').fetchone()
        renderer=json.loads(raw)
        assert renderer['preparation']==binding and created=='original-created'
        assert renderer['requirements']==f.optimized_requirements
    with tool.authorized_continuation(f.root):
        calculated=dict(binding);calculated.pop('checkpoint_reuse')
        assert tool.attempt.Continuation(f.root,calculated,resume=True).value['binding']==binding


@pytest.mark.parametrize('damage',['accepted_phase','receipt','manifest','finished','old_code',
                                   'old_marker','catalog','dependencies','policy','unreviewed_code'])
def test_rebind_refuses_changed_or_accepted_context(tmp_path,monkeypatch,damage):
    f=old_compact_adoption(tmp_path,monkeypatch)
    options={}
    if damage=='accepted_phase':
        p=f.root/'continuation.json';v=json.loads(p.read_bytes());v['phases']['prepared']={};tool.save(p,v)
    elif damage=='receipt':tool.save(f.root/'preparation.json',{})
    elif damage=='manifest':tool.save(f.root/'publication/manifest.json',{})
    elif damage=='finished':
        with sqlite3.connect(f.root/'publication.renderer-upgrade/stages.sqlite') as db:db.execute("INSERT INTO progress VALUES ('finished','{}')")
    elif damage=='old_code':
        p=f.root/'continuation.json';v=json.loads(p.read_bytes());v['binding']['provenance_revision']='other';tool.save(p,v)
    elif damage=='old_marker':
        p=f.root/tool.RECEIPT;v=json.loads(p.read_bytes());v['authorization']='altered';tool.save(p,v)
    elif damage=='catalog':
        with sqlite3.connect(f.root/'publication.renderer-upgrade/stages.sqlite') as db:
            v=json.loads(db.execute('SELECT binding FROM build').fetchone()[0]);v['source']['selector_sha256']='other'
            db.execute('UPDATE build SET binding=?',(json.dumps(v),))
    elif damage=='dependencies':options['identity']=dict(f.optimized_identity,dependencies='other')
    elif damage=='policy':options['requirements']=dict(f.optimized_requirements,policy={'different':1})
    elif damage=='unreviewed_code':options['code']=dict(f.optimized_code,reviewed_source_cache_revision='other')
    before=states(f)
    with pytest.raises(ValueError):rebind(f,**options)
    assert states(f)==before
    assert not (f.root/'checkpoint-rebind.json').exists()


def test_rebind_cli_refuses_changed_native_execution(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from congress_api.retention.docspec import NativeDatasets
    f=old_compact_adoption(tmp_path,monkeypatch)
    executable=tmp_path/'different-native';executable.write_bytes(b'different native bytes')
    monkeypatch.setattr(NativeDatasets,'from_config',lambda *args:SimpleNamespace(execution_files=lambda:[executable]))
    report=tmp_path/'native-refusal.json'
    monkeypatch.setattr('sys.argv',['recover_local_checkpoint.py','rebind','--directory',str(f.root),
        '--authorization','authorized','--native-config',str(tmp_path/'config.json'),
        '--metadata-cache',str(tmp_path/'cache'),'--report',str(report)])
    before=states(f)
    with pytest.raises(ValueError,match='Native executable/configuration'):
        tool.main()
    assert states(f)==before
    assert json.loads(report.read_bytes())['status']=='failed'


def test_rebind_preserves_arbitrary_completed_unaccepted_stages(tmp_path,monkeypatch):
    f=old_compact_adoption(tmp_path,monkeypatch)
    with sqlite3.connect(f.root/'publication.renderer-upgrade/stages.sqlite') as db:
        db.executemany('INSERT INTO progress VALUES (?,?)',[
            ('stage:component_preparation','null'),
            ('stage:component_metadata','{"path":"retained-component-root","rows":2}'),
            ('stage:source_preparation','{"path":"retained-source-root","rows":2}'),
            ('stage:browse_preparation','{"path":"retained-browse-root","rows":2}')])
    before=states(f)
    result=rebind(f)
    assert states(f)==before
    assert result['preserved_state']['progress']['rows']==len(before['progress'])
    bound=json.loads((f.root/'continuation.json').read_bytes())['binding']
    assert bound['checkpoint_reuse']['reused_tasks']==sorted(row[0] for row in before['progress'])
