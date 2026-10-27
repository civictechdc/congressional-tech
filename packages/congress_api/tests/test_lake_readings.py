"""Native body work lists feed bounded parsers once per input and version."""
import hashlib
import json
import os

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.lake import readings
from docspec_client.client import NativeDatasets


def setup(tmp_path, body=b'<html><body><p>Evidence</p><a href="a.pdf">PDF</a></body></html>',
          *, copies=2, size=None, missing=False, body_format='html'):
    raw=tmp_path/'raw';raw.mkdir()
    digest=hashlib.sha256(body).digest()
    key='bodies/sha256/'+digest.hex()[:2]+'/'+digest.hex()
    path=raw/key;path.parent.mkdir(parents=True)
    if not missing:path.write_bytes(body)
    captures=tmp_path/'captures.parquet'
    schema=pa.schema([('sha256',pa.binary(32)),('stored_bytes',pa.int64()),('stored_suffix',pa.string()),
        ('sniffed_format',pa.string()),('sniff_version',pa.string())])
    pq.write_table(pa.Table.from_pylist([dict(sha256=digest,stored_bytes=len(body) if size is None else size,
        stored_suffix='',sniffed_format=body_format,sniff_version='sniff-fixture')]*copies,schema=schema),captures)
    inventory=tmp_path/'bodies.parquet'
    pq.write_table(pa.Table.from_pylist([dict(body_sha=digest,physical_key=key,
        stored_bytes=len(body) if size is None else size,stored_gzip=False)],schema=pa.schema([
        ('body_sha',pa.binary(32)),('physical_key',pa.string()),('stored_bytes',pa.int64()),
        ('stored_gzip',pa.bool_())])),inventory)
    return dict(captures=captures,body_inventory=inventory,local_root=raw,
                engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
                decided_at='2026-10-27T12:00:00Z'),digest


def stage(args,tmp_path,**kwargs):
    return readings.stage(**args,work=tmp_path,parser='html',sniff_version='sniff-fixture',**kwargs)


def test_duplicate_captures_parse_once_and_nested_links_survive_native_export(tmp_path):
    args,digest=setup(tmp_path)
    result=stage(args,tmp_path/'first')
    rows=pq.read_table(result['readings']).to_pylist()
    assert len(rows)==1 and rows[0]['body_sha']==digest
    assert rows[0]['parser']=='html' and rows[0]['status']=='completed'
    assert rows[0]['links'][0]['href']=='a.pdf'
    assert len(rows[0]['fingerprint'])==32
    repeated=stage(args,tmp_path/'again',existing=result['readings'])
    assert pq.ParquetFile(repeated['work_list']).metadata.num_rows==0


def test_oversize_input_is_not_opened(tmp_path):
    args,_=setup(tmp_path,size=readings.MAX_STORED_BYTES+1,missing=True)
    result=stage(args,tmp_path/'stage')
    row=pq.read_table(result['readings']).to_pylist()[0]
    assert row['status']=='size_limit'
    assert result['pending_reads']==0


def test_missing_raw_input_writes_no_reading_or_unreadable_decision(tmp_path):
    args,_=setup(tmp_path,missing=True)
    result=stage(args,tmp_path/'stage')
    assert pq.ParquetFile(result['readings']).metadata.num_rows==0
    assert result['pending_reads']==1 and result['unreadable_path'] is None


def test_active_unreadable_skips_only_its_parser_version_and_supersession_restores_work(tmp_path):
    args,digest=setup(tmp_path)
    decision=dict(id='one',body_sha256=digest.hex(),parser='html',parser_version=readings.current_version('html'),
                  supersedes=None)
    path=tmp_path/'unreadable.jsonl';path.write_text(json.dumps(decision)+'\n')
    result=stage(args,tmp_path/'skip',unreadable_files=[dict(key='provenance/unreadable/one.jsonl',path=str(path))])
    assert pq.ParquetFile(result['work_list']).metadata.num_rows==0
    decision['parser_version']='old'
    path.write_text(json.dumps(decision)+'\n')
    retried=stage(args,tmp_path/'newversion',unreadable_files=[dict(key='provenance/unreadable/one.jsonl',path=str(path))])
    assert pq.ParquetFile(retried['readings']).metadata.num_rows==1


def test_sniff_reads_only_a_prefix_of_large_ordinary_file(tmp_path):
    args,digest=setup(tmp_path,body=b'plain evidence\n'+b'x'*(2<<20),copies=1)
    result=readings.stage(**args,work=tmp_path/'sniff',parser='sniff')
    row=pq.read_table(result['readings']).to_pylist()[0]
    assert row['body_sha']==digest and row['format']=='text'
    assert result['read_bytes']==8192


def test_completed_error_reading_and_local_native_append_noop(tmp_path):
    args,_=setup(tmp_path,body=b'<broken',body_format='xml')
    result=readings.stage(**args,work=tmp_path/'stage',parser='xml',sniff_version='sniff-fixture')
    assert pq.read_table(result['readings']).to_pylist()[0]['status']=='error'
    table=dict(namespace=['archive'],name='readings')
    readings.create_table(engine=args['engine'],work=tmp_path/'create',catalog_root=tmp_path/'catalog',
        table=table,location=tmp_path/'table',create_namespace=True)
    first=readings.append(result,engine=args['engine'],work=tmp_path/'append',catalog_root=tmp_path/'catalog',table=table)
    repeated=readings.append(result,engine=args['engine'],work=tmp_path/'repeat',catalog_root=tmp_path/'catalog',table=table)
    assert first['status']=='appended' and repeated['status']=='empty'
