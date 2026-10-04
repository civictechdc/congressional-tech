"""Standalone migration publishes staged generations without changing legacy bytes."""
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from congress_api.retention import document_index as index
from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.catalog_publication import read_catalog,publish_catalog,local_catalog_paths,MANIFEST_KEY
from congress_api.retention.raw_archive import CAPTURE_SCHEMA

MODES=('write','filename_refresh','source_refresh','reindex','inventory_build')


def setup(root,selected):
    (root / 'indexes').mkdir()
    row=dict(body_key=None,filename='old.pdf',source_url='https://example.gov/old.pdf')
    path=root / 'indexes/document-filenames.parquet'
    index.write_document_indexes(path,[row],index.SOURCE_SCHEMA)
    pq.write_table(pa.Table.from_pylist([],schema=CAPTURE_SCHEMA),root / 'indexes/captures.parquet')
    inventory=root / 'inventory';inventory.mkdir()
    pq.write_table(pa.table({'filename_key':['old.pdf'],'filename':['old.pdf'],'variants':pa.array([['old.pdf']],type=pa.list_(pa.string()))}),inventory / 'filenames.parquet')
    pq.write_table(pa.table({'url':['https://example.gov/old.pdf'],'filename_keys':pa.array([['old.pdf']],type=pa.list_(pa.string()))}),inventory / 'urls.parquet')
    store=LocalStore(root)
    if selected:
        publish_catalog(store,path,path.with_name('documents.parquet'),previous=read_catalog(store))
    return row,{name:(root / 'indexes' / name).read_bytes() for name in ('document-filenames.parquet','documents.parquet')},read_catalog(store)


def invoke(root,mode,row):
    if mode=='write':
        return index.write_filename_metadata(root,[{**row,'filename':'new.pdf','source_url':'https://example.gov/new.pdf'}],workers=1)
    if mode=='filename_refresh':
        return index.refresh_filename_metadata(root,workers=1)
    if mode=='source_refresh':
        return index.refresh_source_metadata(root,index.DocumentSources())
    if mode=='reindex':
        return index.reindex_documents(root)
    return index.build(root,root / 'inventory',workers=1)


@pytest.mark.parametrize('mode',MODES)
@pytest.mark.parametrize('selected',[False,True])
@pytest.mark.parametrize('failure',['second_stage_replace','second_generation_upload','selector'])
def test_failed_standalone_publication_preserves_input_pair(tmp_path,monkeypatch,mode,selected,failure):
    row,legacy,snapshot=setup(tmp_path,selected)
    replace,put=Path.replace,LocalStore.put
    def fail_replace(path,target):
        if Path(target).name=='documents.parquet':
            assert Path(target).parent != tmp_path / 'indexes'
            raise OSError('injected second stage replace')
        return replace(path,target)
    def fail_put(store,key,*args,**kwargs):
        if key.startswith('catalog-generations/') and key.endswith('/documents.parquet'):
            raise OSError('injected second generation upload')
        return put(store,key,*args,**kwargs)
    def fail_select(*args,**kwargs):
        raise OSError('injected selector failure')
    if failure=='second_stage_replace':monkeypatch.setattr(Path,'replace',fail_replace)
    elif failure=='second_generation_upload':monkeypatch.setattr(LocalStore,'put',fail_put)
    else:monkeypatch.setattr(LocalStore,'put_catalog_manifest',fail_select)
    with pytest.raises(OSError,match='injected'):
        invoke(tmp_path,mode,row)
    assert {name:(tmp_path / 'indexes' / name).read_bytes() for name in legacy} == legacy
    current=read_catalog(LocalStore(tmp_path))
    assert current.filenames==snapshot.filenames and current.documents==snapshot.documents
    assert current.version==snapshot.version
    assert (tmp_path / MANIFEST_KEY).is_file()==selected


@pytest.mark.parametrize('mode',MODES)
@pytest.mark.parametrize('selected',[False,True])
def test_successful_standalone_publication_preserves_legacy_and_returns_selected_paths(tmp_path,mode,selected):
    row,legacy,snapshot=setup(tmp_path,selected)
    result=invoke(tmp_path,mode,row)
    assert {name:(tmp_path / 'indexes' / name).read_bytes() for name in legacy} == legacy
    paths=local_catalog_paths(tmp_path)
    assert Path(result['output'])==paths[0] and Path(result['documents_output'])==paths[1]
    assert all(path.is_file() and 'catalog-generations' in path.parts for path in paths)
    current=read_catalog(LocalStore(tmp_path))
    assert current.version != snapshot.version
    assert result['catalog_id']==current.manifest['catalog_id']
