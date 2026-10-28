"""Private typed metadata preserves the bounded capture population and facts."""
import json
import os
from datetime import datetime, timezone

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from docspec_client.client import NativeDatasets
from congress_api.lake.receipt_metadata import BOOLS, NUMBERS, STRINGS
from capture_qualification_helpers import write_qualified_parquet,created_qualifications


def bounded_counter(tmp_path,*,header_padding=0):
    key='receipts/documents/2026-10-20/typed-fixture.jsonl.gz'
    fields=[*(pa.field(n,pa.string()) for n in STRINGS if n!='error_type'),
        *(pa.field(n,pa.int64()) for n in NUMBERS),*(pa.field(n,pa.bool_()) for n in BOOLS)]
    record_type=pa.struct(fields)
    schema=pa.schema([*fields,pa.field('record',record_type),
        pa.field('captures',pa.list_(pa.struct([('sha256',pa.string())]))),
        pa.field('file_references',pa.list_(pa.struct([('sha256',pa.string())]))),
        pa.field('__receipt_key',pa.string()),pa.field('__receipt_line',pa.int64()),
        pa.field('__receipt_family',pa.string()),pa.field('__line_shape',pa.string()),
        pa.field('__raw_line',pa.string()),pa.field('__type_conflicts',pa.list_(pa.string())),
        pa.field('__field_paths',pa.list_(pa.string()))])
    captures=[dict(sha256='a'*64,bytes=123,complete=True,pointer=['content','body']) for _ in range(32)]
    rows=[]
    for line in range(1,4097):
        record=dict(url=f'https://example.test/typed-fixture/{line}.pdf',http_status=200,
            retrieved_at='2026-10-20T12:34:56Z',outcome='stored',mode='fetch',complete=True)
        raw_record=dict(record,content={'body':'typed-metadata-payload-stays-raw'+('x'*4096)})
        if header_padding:
            raw_record['response_headers']={'X-Padding':'window-padding-marker'+('x'*(header_padding-len('window-padding-marker'))),
                'content-disposition':'attachment; filename="window.pdf"'}
        raw=dict(record=raw_record,captures=captures)
        rows.append(dict(record=record,captures=captures,__receipt_key=key,__receipt_line=line,
            __receipt_family='documents',__line_shape='record:object',__raw_line=json.dumps(raw),
            __type_conflicts=[],__field_paths=[]))
    counter=tmp_path/'counter.parquet'
    write_qualified_parquet(pa.Table.from_pylist(rows,schema=schema),counter,row_group_size=8192)
    return counter,key


def assert_bounded_capture_rows(actual,key):
    assert actual.num_rows==131072
    assert actual['receipt_key'].to_pylist()==[key]*131072
    assert actual['receipt_line'].to_pylist()==[line for line in range(1,4097) for _ in range(32)]
    assert actual['capture_index'].to_pylist()==list(range(32))*4096
    assert actual['url'].to_pylist()==[f'https://example.test/typed-fixture/{line}.pdf' for line in range(1,4097) for _ in range(32)]
    for name,value in [('http_status',200),('complete',True),('mode','fetch'),
                       ('outcome','stored'),('bytes',123),('sha256',bytes.fromhex('a'*64)),
                       ('retrieved_at',datetime(2026,10,20,12,34,56,tzinfo=timezone.utc))]:
        assert actual[name].to_pylist()==[value]*131072
    assert all('typed-metadata-payload-stays-raw' not in str(row) for row in actual.to_pylist())


def test_bounded_metadata_fanout_preserves_public_rows(tmp_path):
    from congress_api.lake.captures import stage_captures
    counter,key=bounded_counter(tmp_path)
    stage=stage_captures([dict(key=key)],engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
        work=tmp_path/'stage',validated_counter=counter,source_qualifications=created_qualifications(counter))
    assert_bounded_capture_rows(pq.read_table(stage/'captures.parquet'),key)


@pytest.mark.parametrize("view_strings",[False,True])
def test_direct_and_counter_scalar_types_match(tmp_path,view_strings):
    from congress_api.lake.captures import stage_captures
    from test_receipt_metadata import counter_fixture
    counter,files=counter_fixture(tmp_path)
    if view_strings:
        table=pq.read_table(counter)
        fields=[pa.field(f.name,pa.string_view() if f.type==pa.string() else f.type,
                         nullable=f.nullable) for f in table.schema.field('record').type]
        schema=table.schema.set(0,pa.field('record',pa.struct(fields)))
        write_qualified_parquet(pa.Table.from_pylist(table.to_pylist(),schema=schema),counter)
    native=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    direct=stage_captures(files,engine=native,work=tmp_path/'direct')
    cached=stage_captures([dict(key=f['key']) for f in files],engine=native,
        work=tmp_path/'counter',validated_counter=counter,source_qualifications=created_qualifications(counter))
    assert pq.read_table(cached/'captures.parquet').equals(pq.read_table(direct/'captures.parquet'))
    assert all(not pa.types.is_nested(field.type) for field in pq.read_schema(cached/'captures.parquet'))


def test_empty_list_duplicate_list_and_object_pointer_preserve_grain(tmp_path):
    from congress_api.lake.captures import stage_captures
    from test_captures_ingest import body,files
    native=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    source=files(tmp_path/'input',[
        dict(record=[]),
        dict(record=dict(url='https://example.test/object',http_status=206),
             captures=[body(pointer=[37,'content','body'])]),
        dict(record=[dict(url='https://example.test/same',http_status=404)]*2)])
    stage=stage_captures(source,engine=native,work=tmp_path/'stage')
    rows=pq.read_table(stage/'captures.parquet').to_pylist()
    assert len(rows)==4
    assert [row['capture_index'] for row in rows]==[0,0,0,1]
    assert [row['url'] for row in rows]==[None,'https://example.test/object','https://example.test/same','https://example.test/same']
    assert [row['http_status'] for row in rows]==[None,206,404,404]
    assert [row['sha256'] is None for row in rows]==[True,False,True,True]
