"""Private typed metadata preserves the bounded capture population and facts."""
import json
import os
from datetime import datetime, timezone

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from docspec_client.client import NativeDatasets
from congress_api.lake.receipt_metadata import BOOLS, NUMBERS, STRINGS


def test_bounded_metadata_fanout_preserves_public_rows(tmp_path):
    from congress_api.lake.captures import stage_captures
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
        raw=dict(record=dict(record,content={'body':'typed-metadata-payload-stays-raw'+('x'*4096)}),captures=captures)
        rows.append(dict(record=record,captures=captures,__receipt_key=key,__receipt_line=line,
            __receipt_family='documents',__line_shape='record:object',__raw_line=json.dumps(raw),
            __type_conflicts=[],__field_paths=[]))
    counter=tmp_path/'counter.parquet'
    pq.write_table(pa.Table.from_pylist(rows,schema=schema),counter,row_group_size=8192)
    stage=stage_captures([dict(key=key)],engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
        work=tmp_path/'stage',validated_counter=counter)
    actual=pq.read_table(stage/'captures.parquet')
    assert actual.num_rows==131072
    assert actual['receipt_key'].to_pylist()==[key]*131072
    assert actual['receipt_line'].to_pylist()==[line for line in range(1,4097) for _ in range(32)]
    assert actual['capture_index'].to_pylist()==list(range(32))*4096
    assert actual['url'].to_pylist()==[f'https://example.test/typed-fixture/{line}.pdf' for line in range(1,4097) for _ in range(32)]
    for name,value in [('http_status',200),('attempt_status',200),('complete',True),('mode','fetch'),
                       ('outcome','stored'),('bytes',123),('sha256',bytes.fromhex('a'*64)),
                       ('retrieved_at',datetime(2026,10,20,12,34,56,tzinfo=timezone.utc))]:
        assert actual[name].to_pylist()==[value]*131072
    assert all('typed-metadata-payload-stays-raw' not in str(row) for row in actual.to_pylist())


@pytest.mark.parametrize("view_strings",[False,True])
def test_metadata_stays_typed_for_direct_counter_and_empty_selection(tmp_path,view_strings):
    from congress_api.lake.receipt_metadata import compact, compact_counter
    from test_receipt_metadata import counter_fixture
    counter,files=counter_fixture(tmp_path)
    if view_strings:
        table=pq.read_table(counter)
        fields=[pa.field(f.name,pa.string_view() if f.type==pa.string() else f.type,
                         nullable=f.nullable) for f in table.schema.field('record').type]
        schema=table.schema.set(0,pa.field('record',pa.struct(fields)))
        pq.write_table(pa.Table.from_pylist(table.to_pylist(),schema=schema),counter)
        assert pq.read_schema(counter).field('record').type.field('url').type==pa.string_view()
    native=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    direct=compact(files=files,engine=native,work=tmp_path/'direct')
    cached=compact(counter=counter,engine=native,work=tmp_path/'counter')
    empty=compact_counter(counter,engine=native,work=tmp_path/'empty',receipt_keys=[])
    table=pq.read_table(cached)
    assert pa.types.is_struct(table.schema.field('line').type)
    assert pa.types.is_list(table.schema.field('record_values').type)
    assert pa.types.is_struct(table.schema.field('record_values').type.value_type)
    assert table.schema.field('record_is_list').type==pa.bool_()
    assert 'record_json' not in table.column_names
    assert table.equals(pq.read_table(direct))
    assert table.schema==pq.read_table(empty).schema
    assert table['record_is_list'].to_pylist()==[False]*6
    assert table.schema.field('line').type.field('url').type==pa.string()
    assert table.schema.field('record_values').type.value_type.field('url').type==pa.string()
