"""The maintained local analysis reader uses selected logical native tables."""
import importlib.util
from pathlib import Path
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tests'))
from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.catalog_publication import read_catalog
from test_catalog_coalesced_batches import Native
from test_native_catalog_selection import seed

spec=importlib.util.spec_from_file_location('native_analysis_viewer',ROOT/'docs/youtube-coverage/research/scripts/view_document_filenames.py')
viewer=importlib.util.module_from_spec(spec);spec.loader.exec_module(viewer)


def test_selected_analysis_preserves_search_detail_and_stable_ids_without_full_exports(tmp_path,monkeypatch):
    store,native=LocalStore(tmp_path/'store'),Native()
    seed(tmp_path,store,native)
    selected=read_catalog(store,native=native)
    expected={label:pa.Table.from_batches(list(selected.table(label,max_ordered_bytes=1<<20).iter_batches()))
              for label in ('filenames','documents')}
    legacy=tmp_path/'legacy';legacy.mkdir()
    pq.write_table(expected['filenames'],legacy/'source.parquet');pq.write_table(expected['documents'],legacy/'documents.parquet')
    with viewer.Catalog(legacy/'source.parquet') as old:
        old_result=old.search({'scope':'all'})
        old_rows=[{k:v for k,v in row.items() if k!='_row'} for row in old_result['rows']]
    monkeypatch.setattr(pq,'ParquetFile',lambda *a,**kw:pytest.fail('Native analysis opened a complete Parquet file'))
    with viewer.Catalog.from_snapshot(selected,max_ordered_bytes=1<<20) as catalog:
        result=catalog.search({'scope':'all'})
        assert [{k:v for k,v in row.items() if k!='_row'} for row in result['rows']]==old_rows
        assert all(row['_row']==row['source_id'] for row in result['rows'])
        for source in expected['filenames'].to_pylist():
            row=catalog.resolve(source['source_id'],catalog.info['catalog_id'])
            assert catalog.record(row)==source
            assert catalog.document(row)==next(doc for doc in expected['documents'].to_pylist() if doc['document_id']==source['document_id'])
        with pytest.raises(ValueError,match='not present'):catalog.resolve('0')
        with pytest.raises(viewer.SnapshotChanged):catalog.resolve(source['source_id'],'other')
        assert catalog.search({'q':'other','scope':'all'})['total']==1


@pytest.mark.loopback
def test_native_local_http_exposes_selected_document_and_refuses_positional_downloads(tmp_path):
    from threading import Thread
    from urllib.error import HTTPError
    from urllib.request import urlopen
    import json
    store,native=LocalStore(tmp_path/'store'),Native()
    seed(tmp_path,store,native)
    snapshot=read_catalog(store,native=native)
    with viewer.Catalog.from_snapshot(snapshot,max_ordered_bytes=1<<20) as catalog:
        server=viewer.ThreadingHTTPServer(('127.0.0.1',0),viewer.handler_for(catalog))
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        identity=next(iter(catalog.source_ids))
        try:
            with urlopen(base+'/api/selection') as response:
                assert json.load(response)==dict(manifest=snapshot.manifest,identity=snapshot.identity)
            with urlopen(base+'/api/document/'+identity+'?catalog='+catalog.info['catalog_id']) as response:
                assert json.load(response)==catalog.document(catalog.resolve(identity))
            for path,status in [('/api/entry/0',400),('/api/row/0',400),('/data.parquet',404),('/sources.parquet',404)]:
                with pytest.raises(HTTPError) as error:urlopen(base+path)
                assert error.value.code==status
        finally:
            server.shutdown();server.server_close();thread.join()


from test_docspec_boundary import native


def test_actual_native_analysis_reads_complete_selected_details(native,tmp_path):
    store=LocalStore(tmp_path/'store')
    seed(tmp_path,store,native)
    snapshot=read_catalog(store,native=native)
    with viewer.Catalog.from_snapshot(snapshot,max_ordered_bytes=1<<20) as catalog:
        source=next(iter(catalog.source_ids))
        row=catalog.resolve(source)
        assert catalog.record(row)==catalog.dependencies.source(source)
        assert catalog.document(row)['document_id']==catalog.record(row)['document_id']
        assert catalog.entry(row)['sources'][0]['_row'] in catalog.source_ids
