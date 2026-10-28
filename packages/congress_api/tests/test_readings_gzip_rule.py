"""Amended owner rule: prefix plus one conditional trailer, never size equality alone."""
import gzip
import hashlib
import io
import json
import random

import pytest

from congress_api.lake import readings
from congress_api.retention.r2 import R2Store
from test_readings_ranged import Client,payload,phase


def request(tmp_path,entity,stored,*,original_bytes=None,suffix='.gz'):
    value=json.loads(payload(tmp_path,entity,stored,suffix=suffix))
    value['original_bytes']=len(entity) if original_bytes is None else original_bytes
    return json.dumps(value).encode()


def random_pdf():
    return b'%PDF-1.7\n'+random.Random(20261028).randbytes(16384)+b'\n%%EOF\n'


def test_different_sizes_recorded_gzip_and_pinned_isize_settle_storage(tmp_path):
    entity=random_pdf();stored=gzip.compress(entity,mtime=0);client=Client(stored,None)
    value=request(tmp_path,entity,stored);store=R2Store(client,'bucket')
    with phase(tmp_path):
        result=readings.parse_once_payload(value,body_store=store)
        retry=readings.parse_once_payload(value,body_store=store)
    assert result['gzip_rule']==2 and result['rows'][0]['format']=='pdf'
    assert retry==result and result['read_bytes']==8196
    assert [r['Range'] for r in client.reads]==['bytes=0-8191',f'bytes={len(stored)-4}-{len(stored)-1}']
    assert {r['IfMatch'] for r in client.reads}=={'"'+hashlib.md5(stored).hexdigest()+'"'}


def test_equal_size_storage_counterexample_remains_ambiguous(tmp_path):
    entity=b'%PDF-1.7\n'+random.Random(20261028).randbytes(16384)+b'\0'*61+b'\n%%EOF\n'
    stored=gzip.compress(entity,mtime=0)
    assert len(entity)==len(stored)==16461 and int.from_bytes(stored[-4:],'little')==16461
    client=Client(stored,None)
    with phase(tmp_path):result=readings.parse_once_payload(request(tmp_path,entity,stored),body_store=R2Store(client,'bucket'))
    assert result['gzip_rule']==4 and result['ambiguous_gzip'] and result['rows']==[]
    assert result['read_bytes']==8196 and len(client.reads)==2


def test_original_multimember_warc_has_no_historical_single_member_proof(tmp_path):
    entity=gzip.compress(b'WARC/1.1\r\nWARC-Type: response\r\n\r\n',mtime=0)+gzip.compress(
        random.Random(20261028).randbytes(16384),mtime=0)
    assert len(entity)>8192 and int.from_bytes(entity[-4:],'little')!=len(entity)
    client=Client(entity,None)
    with phase(tmp_path):result=readings.parse_once_payload(request(tmp_path,entity,entity),body_store=R2Store(client,'bucket'))
    assert result['gzip_rule']==4 and result['ambiguous_gzip'] and result['rows']==[]
    assert result['read_bytes']==8196


@pytest.mark.parametrize('suffix,delta',[('.gz',1),('',0)])
def test_unconfirmed_storage_gzip_stays_pending(tmp_path,suffix,delta):
    entity=random_pdf();stored=gzip.compress(entity,mtime=0);client=Client(stored,None)
    with phase(tmp_path):result=readings.parse_once_payload(request(tmp_path,entity,stored,
        original_bytes=len(entity)+delta,suffix=suffix),body_store=R2Store(client,'bucket'))
    assert result['gzip_rule']==4 and result['rows']==[] and result['ambiguous_gzip']
    assert result['read_bytes']==(8196 if suffix=='.gz' else 8192)


def test_non_gzip_prefix_sets_raw_rule_and_preserves_pdf_tail(tmp_path):
    entity=random_pdf();client=Client(entity,None)
    with phase(tmp_path):result=readings.parse_once_payload(request(tmp_path,entity,entity,suffix=''),body_store=R2Store(client,'bucket'))
    assert result['gzip_rule']==1 and result['rows'][0]['format']=='pdf' and result['rows'][0]['intact'] is True
    assert result['read_bytes']==16384 and len(client.reads)==2


def test_isize_tail_preserves_opaque_conditional_version(tmp_path):
    entity=random_pdf();stored=gzip.compress(entity,mtime=0);etag='"multipart-12-7"'
    class OpaqueClient(Client):
        def get_object(self,**kwargs):
            self.reads.append(kwargs);assert kwargs['IfMatch']==etag
            start,end=map(int,kwargs['Range'][6:].split('-'));piece=stored[start:end+1]
            return dict(Body=io.BytesIO(piece),ContentLength=len(piece),ETag=etag,
                ContentRange=f'bytes {start}-{end}/{len(stored)}',ResponseMetadata={'HTTPStatusCode':206})
    value=json.loads(request(tmp_path,entity,stored));value['remote'].update(md5=None,etag=etag)
    client=OpaqueClient(stored)
    with phase(tmp_path):result=readings.parse_once_payload(json.dumps(value).encode(),body_store=R2Store(client,'bucket'))
    assert result['gzip_rule']==2 and result['rows'][0]['format']=='pdf' and result['read_bytes']==8196
    assert len(client.reads)==2
