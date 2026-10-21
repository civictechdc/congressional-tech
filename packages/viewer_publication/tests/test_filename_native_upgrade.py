"""Explicit rendering upgrades resume existing stages without catalog rebuilds."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'apps/site/scripts'),str(ROOT/'tests')]
from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.catalog_publication import read_catalog
from test_catalog_coalesced_batches import Native
from test_native_catalog_selection import seed

spec=importlib.util.spec_from_file_location('upgrade_viewer_builder',ROOT/'scripts/publication/publish-filename-viewer.py')
builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)


def prepared(tmp_path):
    store,native=LocalStore(tmp_path/'store'),Native()
    seed(tmp_path,store,native)
    snapshot=read_catalog(store,native=native)
    previous=builder.publish_selected(snapshot,tmp_path/'old',review_identities=None,
        compression_policy=builder.DEFAULT_COMPRESSION_POLICY._replace(level=9))
    native.reads.clear()
    return store,native,snapshot,previous


@pytest.mark.parametrize('task_prefix',['component-chunk:','source-route:'])
@pytest.mark.parametrize('event',['renderer_task_started','renderer_task_completed'])
def test_upgrade_resumes_before_or_after_a_physical_chunk_without_reopening_completed_chunks(tmp_path,event,task_prefix):
    store,native,snapshot,previous=prepared(tmp_path)
    original=store.read('indexes/catalog.json')
    old_files={str(p.relative_to(tmp_path/'old')):p.read_bytes() for p in (tmp_path/'old').rglob('*') if p.is_file()}
    stopped=[]
    def interrupt(value):
        if value['event']==event and value.get('task','').startswith(task_prefix):
            stopped.extend(native.reads)
            raise RuntimeError('worker stopped')
    options=dict(previous=previous,read_asset=lambda name:(tmp_path/'old'/name).read_bytes(),review_identities=None,
                 renderer_upgrade=True)
    with pytest.raises(RuntimeError,match='worker stopped'):
        builder.publish_selected(snapshot,tmp_path/'new',stage_event=interrupt,**options)
    native.reads.clear()
    resumed=builder.publish_selected(snapshot,tmp_path/'new',resume_upgrade=True,**options)
    if event=='renderer_task_completed':assert not set(stopped)&set(native.reads)
    assert resumed['source_identity']==previous['source_identity']
    assert resumed['requirements']['compression']['level']==3
    assert store.read('indexes/catalog.json')==original
    assert all((tmp_path/'old'/name).read_bytes()==raw for name,raw in old_files.items())
    native.reads.clear()
    again=builder.publish_selected(snapshot,tmp_path/'new',resume_upgrade=True,**options)
    assert again==resumed and not native.reads
    assert json.loads((tmp_path/'new/manifest.json').read_bytes())==resumed


def test_upgrade_refuses_changed_inputs_and_corrupted_completed_assets(tmp_path):
    store,native,snapshot,previous=prepared(tmp_path)
    options=dict(previous=previous,read_asset=lambda name:(tmp_path/'old'/name).read_bytes(),review_identities=None,
                 renderer_upgrade=True)
    def stop(value):
        if value['event']=='renderer_task_completed' and value.get('task','').startswith('component-chunk:'):
            raise RuntimeError('worker stopped')
    with pytest.raises(RuntimeError):builder.publish_selected(snapshot,tmp_path/'new',stage_event=stop,**options)
    native.reads.clear()
    with pytest.raises(ValueError,match='inputs changed'):
        builder.publish_selected(snapshot,tmp_path/'new',resume_upgrade=True,
            compression_policy=builder.DEFAULT_COMPRESSION_POLICY._replace(level=19),**options)
    assert not native.reads
    changed_previous=dict(previous,published_at='2026-10-20T00:00:00+00:00')
    with pytest.raises(ValueError,match='inputs changed'):
        builder.publish_selected(snapshot,tmp_path/'new',resume_upgrade=True,
            **dict(options,previous=changed_previous))
    assert not native.reads
    # A real newly selected catalog cannot inherit the old operation.
    from test_native_catalog_selection import scope_for, identity
    from congress_api.retention.catalog_dependency_storage import CatalogDependencyStorage
    from congress_api.retention.catalog_selection import publish_native_catalog
    from test_catalog_dependencies import source
    owner=CatalogDependencyStorage.for_snapshot(snapshot)
    proof=scope_for(tmp_path/'changed',store,owner,snapshot,[],name='changed',deletions=[identity(source('other.pdf','O'))])
    publish_native_catalog(store,proof,previous=snapshot)
    changed=read_catalog(store,native=native);native.reads.clear()
    with pytest.raises(ValueError,match='inputs changed'):
        builder.publish_selected(changed,tmp_path/'new',resume_upgrade=True,**options)
    assert not native.reads
    asset=next((tmp_path/'new').rglob('*.parquet'));raw=asset.read_bytes();asset.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
    with pytest.raises(ValueError,match='asset.*changed'):
        builder.publish_selected(snapshot,tmp_path/'new',resume_upgrade=True,**options)
    assert not native.reads


from test_docspec_boundary import native


@pytest.mark.parametrize('event',['renderer_task_started','renderer_task_completed'])
def test_actual_native_upgrade_survives_abrupt_worker_exit_without_new_native_candidates(native,tmp_path,event):
    import subprocess
    store=LocalStore(tmp_path/'store')
    seed(tmp_path,store,native)
    snapshot=read_catalog(store,native=native)
    previous=builder.publish_selected(snapshot,tmp_path/'old',review_identities=None,
        compression_policy=builder.DEFAULT_COMPRESSION_POLICY._replace(level=9))
    native.close()
    selector=store.read('indexes/catalog.json')
    script=r'''
from contextlib import contextmanager
from hashlib import sha256
import importlib.util,json,os,sys
from pathlib import Path
repo,folder,binary,workspace,limits,event,mode=map(str,sys.argv[1:])
folder=Path(folder);sys.path[:0]=[str(Path(repo)/p) for p in ('apps/site/scripts','tests')]
from congress_api.retention.docspec import NativeDatasets
from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.catalog_publication import read_catalog
spec=importlib.util.spec_from_file_location('worker_upgrade',Path(repo)/'scripts/publication/publish-filename-viewer.py')
builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
native=NativeDatasets(binary,workspace,limits=limits)
original=native.source_batches;reads=[]
@contextmanager
def observed(pin,**options):
 reads.append(sha256(json.dumps(pin,sort_keys=True).encode()).hexdigest())
 (folder/(mode+'-reads.json')).write_text(json.dumps(reads))
 with original(pin,**options) as stream:yield stream
native.source_batches=observed
native.run_table=lambda *a,**k:(_ for _ in ()).throw(AssertionError('Upgrade wrote a native dataset'))
snapshot=read_catalog(LocalStore(folder/'store'),native=native)
previous=json.loads((folder/'old/manifest.json').read_bytes())
def interrupted(value):
 if mode=='stop' and value['event']==event and value.get('task','').startswith('component-chunk:'):os._exit(73)
manifest=builder.publish_selected(snapshot,folder/'new',previous=previous,
 read_asset=lambda path:(folder/'old'/path).read_bytes(),review_identities=None,
 renderer_upgrade=True,resume_upgrade=mode=='resume',stage_event=interrupted)
assert manifest['source_identity']==previous['source_identity']
'''
    args=[sys.executable,'-c',script,str(ROOT),str(tmp_path),str(native.binary),str(native.workspace),str(native.limits),event]
    stopped=subprocess.run([*args,'stop'],capture_output=True,text=True,timeout=60)
    assert stopped.returncode==73,stopped.stderr
    resumed=subprocess.run([*args,'resume'],capture_output=True,text=True,timeout=60)
    assert resumed.returncode==0,resumed.stderr
    before=json.loads((tmp_path/'stop-reads.json').read_bytes()) if (tmp_path/'stop-reads.json').is_file() else []
    after=json.loads((tmp_path/'resume-reads.json').read_bytes())
    if event=='renderer_task_completed':assert not set(before)&set(after)
    assert store.read('indexes/catalog.json')==selector


@pytest.mark.parametrize('kind',['node','file'])
@pytest.mark.parametrize('window',['copy','before_link','after_link'])
def test_abrupt_exit_inside_asset_copy_keeps_partials_outside_publication(tmp_path,kind,window):
    import subprocess
    script=r'''
import json,os,sys
from pathlib import Path
repo,folder,kind,window,mode=sys.argv[1:]
sys.path.insert(0,str(Path(repo)/'apps/site/scripts'))
from viewer_publication.filename_native import ViewerAssets
import viewer_publication.filename_renderer_state as stages
folder=Path(folder);target=folder/'publication';target.mkdir(exist_ok=True)
assets=ViewerAssets(target)
with stages.RendererState(target,{'fixture':'write-loss'},resume=mode=='resume') as state:
 assets.state=state;state.restore(assets)
 if mode=='stop' and window=='copy':
  original=stages.copy_checked
  def interrupted(source,*args,**options):
   class LostWorker:
    calls=0
    def read(self,size):
     self.calls+=1
     if self.calls==2:os._exit(73)
     return source.read(min(size,5))
   return original(LostWorker(),*args,**options)
  stages.copy_checked=interrupted
 if mode=='stop' and window!='copy':
  original_link=os.link
  def interrupted_link(source,destination,*args,**options):
   if window=='before_link':os._exit(73)
   original_link(source,destination,*args,**options)
   os._exit(73)
  os.link=interrupted_link
 def render():
  if kind=='node':return assets.put_node({'version':1,'fixture':'complete-metadata'})
  source=folder/'input.bin';source.write_bytes(b'complete bounded payload')
  return assets.put_file(source,name='details.parquet')
 reference=state.run('asset',render)
 assert (target/reference['path']).stat().st_size==reference['bytes']
 assert not list(target.rglob('*.partial'))
 for relative,identity in assets.identities.items():identity.require(target/relative)
 (folder/'result.json').write_text(json.dumps(reference))
'''
    args=[sys.executable,'-c',script,str(ROOT),str(tmp_path),kind,window]
    stopped=subprocess.run([*args,'stop'],capture_output=True,text=True,timeout=30)
    assert stopped.returncode==73,stopped.stderr
    assert not list((tmp_path/'publication').rglob('*.partial'))
    if window!='after_link':
        assert not [p for p in (tmp_path/'publication').rglob('*') if p.is_file()]
    assert list((tmp_path/'publication.renderer-upgrade').rglob('*.partial'))
    resumed=subprocess.run([*args,'resume'],capture_output=True,text=True,timeout=30)
    assert resumed.returncode==0,resumed.stderr
    from congress_api.retention.derived_files import file_identity
    reference=json.loads((tmp_path/'result.json').read_bytes())
    assert file_identity(tmp_path/'publication'/reference['path'])=={k:reference[k] for k in ('bytes','sha256')}


def test_split_document_upgrade_resumes_after_an_occurrence_asset_write(tmp_path, monkeypatch):
    import runpy
    from viewer_publication.filename_native import ViewerAssets, public_component, iterator_inventory
    folder = tmp_path / 'fixture'
    folder.mkdir()
    monkeypatch.setenv('FILENAME_FIXTURE_GIANT_DOCUMENT', '1')
    monkeypatch.setattr(sys, 'argv', [str(ROOT / 'packages/viewer_publication/tests/native_viewer_fixture.py'), str(folder)])
    fixture = runpy.run_path(sys.argv[0])
    snapshot, native = fixture['snapshot'], fixture['native']
    previous = builder.publish_selected(snapshot, tmp_path / 'old', review_identities=None,
        compression_policy=builder.DEFAULT_COMPRESSION_POLICY._replace(level=9))
    native_tables = set(native.tables)
    original = ViewerAssets.put_file
    stopped = []
    def stop(self, source, *, name):
        result = original(self, source, name=name)
        if name == 'observations.bin' and not stopped:
            stopped.append(result)
            raise RuntimeError('stopped after split occurrence asset')
        return result
    options = dict(previous=previous, read_asset=lambda path: (tmp_path / 'old' / path).read_bytes(),
                   review_identities=None, renderer_upgrade=True)
    monkeypatch.setattr(ViewerAssets, 'put_file', stop)
    with pytest.raises(RuntimeError, match='stopped after split occurrence'):
        builder.publish_selected(snapshot, tmp_path / 'upgrade', **options)
    assert stopped and not (tmp_path / 'upgrade' / 'manifest.json').exists()
    monkeypatch.setattr(ViewerAssets, 'put_file', original)
    complete = builder.publish_selected(snapshot, tmp_path / 'upgrade', resume_upgrade=True, **options)
    assets = ViewerAssets(tmp_path / 'upgrade')
    document = fixture['documents']['document_id'][0].as_py()
    component = public_component(assets, complete['roots']['components'], document)
    assert component['document_occurrences_split'] is True
    files = component['document_observations']['files']
    inventory = {item['path'] for item in iterator_inventory(assets, complete['inventory'])}
    assert {component['document_file']['path'], *[item['path'] for item in files.values()]} <= inventory
    assert all((assets.root / path).is_file() for path in inventory)
    assert set(native.tables) == native_tables  # Rendering never creates native candidates.
    native.reads.clear()
    assert builder.publish_selected(snapshot, tmp_path / 'upgrade', resume_upgrade=True, **options) == complete
    assert not native.reads
