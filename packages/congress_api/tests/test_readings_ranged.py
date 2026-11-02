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


def payload(tmp_path,entity,stored,*,suffix='',known=None,prefetched=False):
    digest=hashlib.sha256(entity).hexdigest();key=f'bodies/sha256/{digest[:2]}/{digest}{suffix}'
    value=dict(path=str(tmp_path/'absent'),cache=str(tmp_path/'ranges'),body_sha=digest,
        stored_bytes=len(stored),known_format=known,skip_parsers=[],
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


# Storage encoding is the object's Content-Encoding, whatever its key suffix; no inventory flag.
@pytest.mark.parametrize('suffix,encoding',[('','gzip'),('.gz','gzip')])
def test_canonical_and_legacy_storage_gzip_use_actual_encoding_facts(tmp_path,suffix,encoding):
    entity=b'<html><body>'+b'Evidence '*2000+b'</body></html>';stored=gzip.compress(entity,mtime=0)
    client=Client(stored,encoding);store=R2Store(client,'bucket')
    with phase(tmp_path):result=readings.parse_once_payload(
        payload(tmp_path,entity,stored,suffix=suffix),body_store=store)
    assert result['rows'][0]['format']=='html' and result['rows'][1]['parser']=='html'
    assert len(client.reads)==1 and result['read_bytes']==len(stored)


@pytest.mark.parametrize('storage_gzip',[False,True])
def test_original_gzip_warc_is_not_confused_with_storage_compression(tmp_path,storage_gzip):
    entity=gzip.compress(b'WARC/1.1\r\nWARC-Type: response\r\n\r\n',mtime=0)
    stored=gzip.compress(entity,mtime=0) if storage_gzip else entity
    client=Client(stored,'gzip' if storage_gzip else None);store=R2Store(client,'bucket')
    with phase(tmp_path):result=readings.parse_once_payload(payload(tmp_path,entity,stored,
        suffix='.gz' if storage_gzip else ''),body_store=store)
    assert [r['format'] for r in result['rows']]==['warc'] and len(client.reads)==1


def test_known_canonical_gzip_json_is_decoded_and_verified_before_parse(tmp_path):
    entity=b'{"title":"A report","padding":"'+b'x'*12000+b'"}';stored=gzip.compress(entity,mtime=0)
    with phase(tmp_path):result=readings.parse_once_payload(payload(tmp_path,entity,stored,
        known='json',prefetched=True))
    assert result['rows'][-1]['parser']=='json' and result['rows'][-1]['status']=='completed'


def test_wrong_decoded_body_identity_remains_pending_instead_of_a_parser_verdict(tmp_path):
    actual=b'<html><body>'+b'Evidence '*2000+b'</body></html>';client=Client(actual)
    with phase(tmp_path):result=readings.parse_once_payload(payload(tmp_path,b'different content',actual),
        body_store=R2Store(client,'bucket'))
    assert result.get('read_error') and result['rows']==[]


def test_headerless_gzip_beyond_prefix_stays_pending_without_full_fetch(tmp_path):
    # Incompressible deterministic payload forces disjoint prefix/completion.
    entity=b'%PDF-1.7\n'+b''.join(hashlib.sha256(str(i).encode()).digest() for i in range(900))+b'%%EOF'
    stored=gzip.compress(entity,mtime=0);client=Client(stored,None)
    with phase(tmp_path):result=readings.parse_once_payload(payload(tmp_path,entity,stored,
        suffix='.gz'),body_store=R2Store(client,'bucket'))
    assert result['read_error'] and result['ambiguous_gzip'] and result['rows']==[]
    assert result['read_bytes']==8192
    assert [r['Range'] for r in client.reads]==['bytes=0-8191']


def test_headerless_original_gzip_remains_original_after_identity_proof(tmp_path):
    entity=gzip.compress(b'WARC/1.1\r\nWARC-Type: response\r\n\r\n',mtime=0)
    client=Client(entity,None)
    with phase(tmp_path):result=readings.parse_once_payload(payload(tmp_path,entity,entity,
        suffix='.gz'),body_store=R2Store(client,'bucket'))
    assert result['rows'][0]['format']=='warc' and result['read_bytes']==len(entity)


def test_captured_copies_are_read_through_the_remote_store_without_an_inventory(tmp_path):
    # The daily raw-store binding in production: no body inventory, each capture's recorded
    # copy read by range from R2. Defect guarded: an empty inventory left every body pending.
    import pyarrow as pa
    import pyarrow.parquet as pq
    from docspec_client.client import NativeDatasets
    entity=b'<html><body>'+b'Evidence '*2000+b'</body></html>';stored=gzip.compress(entity,mtime=0)
    digest=hashlib.sha256(entity).digest()
    captures=tmp_path/'captures.parquet'
    pq.write_table(pa.Table.from_pylist([dict(sha256=digest,bytes=len(entity),media_type='text/html',fidelity='exact-bytes',
        stored_suffix='',stored_bytes=len(stored),stored_md5=hashlib.md5(stored).digest())],schema=pa.schema([
        ('sha256',pa.binary(32)),('bytes',pa.int64()),('media_type',pa.string()),('fidelity',pa.string()),
        ('stored_suffix',pa.string()),('stored_bytes',pa.int64()),('stored_md5',pa.binary(16)),
        ('sniffed_format',pa.string()),('sniff_version',pa.string()),('intact',pa.bool_())])),captures)
    class PrefetchClient(Client):
        # A page-hinted body is prefetched whole, as in production.
        def get_object(self,**kwargs):
            if 'Range' in kwargs:return super().get_object(**kwargs)
            self.reads.append(kwargs)
            return dict(Body=io.BytesIO(self.data),ContentLength=len(self.data),ETag='"'+hashlib.md5(self.data).hexdigest()+'"',
                ContentEncoding=self.encoding,ResponseMetadata={'HTTPStatusCode':200})
    client=PrefetchClient(stored,'gzip')
    store=R2Store(client,'bucket',cache_dir=tmp_path/'stage'/'raw-pages')
    import os
    staged=readings.stage_once(captures=captures,body_inventory=None,captured_copies=True,local_root=tmp_path/'stage'/'raw-pages',
        body_store=store,work=tmp_path/'stage',decided_at='2026-11-02T00:00:00Z',
        engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']))
    rows={r['parser']:r for r in pq.read_table(staged['readings']).to_pylist()}
    assert rows['sniff']['format']=='html' and rows['html']['status']=='completed' and staged['pending_reads']==0
    assert client.reads and client.reads[0]['Key'].endswith(digest.hex())
