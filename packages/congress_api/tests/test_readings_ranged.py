"""Pinned byte ranges feed the existing read-once worker without duplicate GETs."""
from contextlib import contextmanager
import gzip
import hashlib
import io
import json
import os

import pytest

from congress_api.lake import readings
from congress_api.retention.r2 import R2Store
from test_r2_body_files import Client as BaseClient


@contextmanager
def phase(tmp_path):
    previous=os.environ.get('DOCSPEC_PARSER_IO_MARKER')
    os.environ['DOCSPEC_PARSER_IO_MARKER']=str(tmp_path/'phase')
    try:yield
    finally:
        if previous is None:os.environ.pop('DOCSPEC_PARSER_IO_MARKER',None)
        else:os.environ['DOCSPEC_PARSER_IO_MARKER']=previous


class Client(BaseClient):
    def __init__(self,data,encoding=None):
        super().__init__();self.data=data;self.encoding=encoding
        self.meta.config.retries={'total_max_attempts':1}
    def get_object(self,**kwargs):
        self.reads.append(kwargs)
        assert kwargs['IfMatch']=='"'+hashlib.md5(self.data).hexdigest()+'"'
        assert 'Range' in kwargs,'An unknown body must start with a bounded range'
        start,end=map(int,kwargs['Range'][6:].split('-'));piece=self.data[start:end+1]
        return dict(Body=io.BytesIO(piece),ContentLength=len(piece),ContentRange=f'bytes {start}-{end}/{len(self.data)}',
            ETag='"'+hashlib.md5(self.data).hexdigest()+'"',ContentEncoding=self.encoding,
            ResponseMetadata={'HTTPStatusCode':206})
    def head_object(self,**_):raise AssertionError('No per-body HEAD')


def payload(tmp_path,entity,stored,*,suffix='',stored_gzip=False,known=None,prefetched=False):
    digest=hashlib.sha256(entity).hexdigest();key=f'bodies/sha256/{digest[:2]}/{digest}{suffix}'
    value=dict(path=str(tmp_path/'absent'),cache=str(tmp_path/'ranges'),body_sha=digest,
        stored_bytes=len(stored),stored_gzip=stored_gzip,known_format=known,skip_parsers=[],
        versions={p:readings.current_version(p) for p in ['sniff','html','xml','json']},prefetched=prefetched)
    if prefetched:
        (tmp_path/'cached').write_bytes(stored);value['path']=str(tmp_path/'cached')
    else:value['remote']=dict(bucket='bucket',key=key,md5=hashlib.md5(stored).hexdigest())
    return json.dumps(value).encode()


def test_bare_pdf_uses_disjoint_prefix_tail_and_cache_retry(tmp_path):
    data=b'%PDF-1.7\n'+b'x'*24000+b'%%EOF';client=Client(data);store=R2Store(client,'bucket')
    request=payload(tmp_path,data,data)
    with phase(tmp_path):
        first=readings.parse_once_payload(request,body_store=store)
        again=readings.parse_once_payload(request,body_store=store)
    assert first['rows'][0]['format']=='pdf' and first['rows'][0]['intact'] is True
    assert again==first and len(client.reads)==2
    assert [r['Range'] for r in client.reads]==[f'bytes=0-8191',f'bytes={len(data)-8192}-{len(data)-1}']


@pytest.mark.parametrize('kind',['html','xml','json'])
def test_unknown_or_mislabelled_page_reads_each_physical_byte_once(tmp_path,kind):
    data={'html':b'<html><body>'+b'Evidence '*2500+b'</body></html>',
          'xml':b'<?xml version="1.0"?><record><title>'+b'Evidence '*2500+b'</title></record>',
          'json':b'{"title":"Evidence","padding":"'+b'x'*22000+b'"}'}[kind]
    client=Client(data);store=R2Store(client,'bucket')
    with phase(tmp_path):result=readings.parse_once_payload(payload(tmp_path,data,data),body_store=store)
    assert [(r['parser'],r['status']) for r in result['rows']]==[('sniff','completed'),(kind,'completed')]
    intervals=[tuple(map(int,r['Range'][6:].split('-'))) for r in client.reads]
    assert intervals==[(0,8191),(8192,len(data)-1)] and result['read_bytes']==len(data)


@pytest.mark.parametrize('suffix,declared,encoding',[('',False,'gzip'),('.gz',True,None)])
def test_canonical_and_legacy_storage_gzip_use_actual_encoding_facts(tmp_path,suffix,declared,encoding):
    entity=b'<html><body>'+b'Evidence '*2000+b'</body></html>';stored=gzip.compress(entity,mtime=0)
    client=Client(stored,encoding);store=R2Store(client,'bucket')
    with phase(tmp_path):result=readings.parse_once_payload(
        payload(tmp_path,entity,stored,suffix=suffix,stored_gzip=declared),body_store=store)
    assert result['rows'][0]['format']=='html' and result['rows'][1]['parser']=='html'
    assert len(client.reads)==1 and result['read_bytes']==len(stored)


@pytest.mark.parametrize('storage_gzip',[False,True])
def test_original_gzip_warc_is_not_confused_with_storage_compression(tmp_path,storage_gzip):
    entity=gzip.compress(b'WARC/1.1\r\nWARC-Type: response\r\n\r\n',mtime=0)
    stored=gzip.compress(entity,mtime=0) if storage_gzip else entity
    client=Client(stored,'gzip' if storage_gzip else None);store=R2Store(client,'bucket')
    with phase(tmp_path):result=readings.parse_once_payload(payload(tmp_path,entity,stored,
        suffix='.gz' if storage_gzip else '',stored_gzip=storage_gzip),body_store=store)
    assert [r['format'] for r in result['rows']]==['warc'] and len(client.reads)==1


def test_known_canonical_gzip_json_is_decoded_and_verified_before_parse(tmp_path):
    entity=b'{"title":"A report","padding":"'+b'x'*12000+b'"}';stored=gzip.compress(entity,mtime=0)
    with phase(tmp_path):result=readings.parse_once_payload(payload(tmp_path,entity,stored,
        known='json',stored_gzip=False,prefetched=True))
    assert result['rows'][-1]['parser']=='json' and result['rows'][-1]['status']=='completed'


def test_wrong_decoded_body_identity_remains_pending_instead_of_a_parser_verdict(tmp_path):
    actual=b'<html><body>'+b'Evidence '*2000+b'</body></html>';client=Client(actual)
    with phase(tmp_path):result=readings.parse_once_payload(payload(tmp_path,b'different content',actual),
        body_store=R2Store(client,'bucket'))
    assert result.get('read_error') and result['rows']==[]
