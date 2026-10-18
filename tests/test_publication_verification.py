"""Read-only receipts retain independent pending gates and exact document IDs."""
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import publication_verification as verification


def observed(tmp_path):
    path=tmp_path/'documents.parquet'
    table=pa.table({'document_id':['a'*64], 'document_kind':[['bill']], 'document_family':[['legislation']], 'document_kind_source':[['filename']]}).replace_schema_metadata({b'catalog_id':b'catalog'})
    pq.write_table(table,path);raw=path.read_bytes()
    item=dict(path='documents.parquet',bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),rows=1)
    source={'catalog_id':'catalog','generation':'generation'}
    v=dict(pointer={'catalog_id':'catalog','source_manifest':source},manifest={'info':{'catalog_id':'catalog'},'source_manifest':source,'files':{'documents':item}},manifest_url='https://data.test/release/manifest.json',
        loader={'info':{'reviewed_search':True,'review_sha256':'pin'},'rows':[{'document_id':'a'*64,'baseline':{'document_kind':['other'],'document_family':['other'],'document_kind_source':['old']},'selected':{'document_kind':['letter']}}]},
        pages={'assets':[{'sha256':'asset'}],'runtime_execution':{'state':'passed','method':'fixture worker'}},withdrawn=[{'document_id':'a'*64,'reason':'body_changed'}])
    def read(location,**kwargs):
        assert kwargs['expected']==item and kwargs['limit']==32*1024**2
        return raw
    return source,v,read


def test_complete_verified_table_diff_uses_document_identity_and_preserves_withdrawals(tmp_path):
    source,value,read=observed(tmp_path)
    result=verification.verify(source,value,current_raw=True,read=read,raw_digest='exact',expected_raw_digest='exact')
    assert result['status']=='verified' and result['read_only']
    difference=next(item['detail'] for item in result['checks'] if item['check']=='document_category_readback')
    assert difference['maximum_batch_rows']==256
    assert difference['documents'][0]['document_id']=='a'*64
    assert difference['documents'][0]['different_from_review_baseline'] is True
    assert result['withdrawn_reasons'][0]['reason']=='body_changed'


def test_missing_runtime_or_run_pin_or_live_raw_never_claims_complete(tmp_path):
    source,value,read=observed(tmp_path)
    result=verification.verify(source,value,read=read)
    assert result['status']=='pending'
    assert {'raw_selector_freshness','raw_run_output_binding'} <= {item['check'] for item in result['checks'] if item['state']=='pending'}
    value['pages']['runtime_execution']={'state':'pending','reason':'browser unavailable'}
    result=verification.verify(source,value,current_raw=True,read=read,raw_digest='x',expected_raw_digest='x')
    assert result['status']=='pending'


def test_mismatched_selection_or_run_pin_fails_without_promoting_metadata(tmp_path):
    source,value,read=observed(tmp_path);value['pointer']['catalog_id']='other'
    result=verification.verify(source,value,current_raw=True,read=lambda *a,**kw:pytest.fail('table read after identity mismatch'),raw_digest='wrong',expected_raw_digest='expected')
    assert result['status']=='failed'
    assert any(item['check']=='raw_viewer_identity' and item['state']=='failed' for item in result['checks'])


def test_oversized_table_is_pending_before_download(tmp_path):
    _,value,_=observed(tmp_path);value['manifest']['files']['documents']['bytes']=32*1024**2+1
    result=verification.catalog_differences(value,read=lambda *a,**kw:pytest.fail('oversized table download'))
    assert result['state']=='pending'


def test_control_read_hash_and_length_are_complete_and_bounded(tmp_path):
    path=tmp_path/'control';path.write_bytes(b'complete')
    expected={'bytes':8,'sha256':hashlib.sha256(b'complete').hexdigest()}
    assert verification.control(path,limit=8,expected=expected)==b'complete'
    with pytest.raises(ValueError,match='byte budget'):verification.control(path,limit=7)
    with pytest.raises(ValueError,match='pinned'):verification.control(path,expected=dict(expected,sha256='wrong'))
