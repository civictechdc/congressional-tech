"""Narrow source helpers validate counters before native registration."""
import gzip
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from capture_qualification_helpers import write_qualified_bytes,write_qualified_parquet



def counter_fixture(tmp_path):
    record_type=pa.struct([('url',pa.string()),('http_status',pa.int64()),('retrieved_at',pa.string())])
    body_type=pa.list_(pa.struct([('sha256',pa.string())]))
    schema=pa.schema([('record',record_type),('captures',body_type),('file_references',body_type),
        ('__receipt_key',pa.string()),('__receipt_line',pa.int64()),('__receipt_family',pa.string()),
        ('__raw_line',pa.string()),('__type_conflicts',pa.list_(pa.string()))])
    rows=[];files=[]
    for index in range(3):
        key=f'receipts/documents/2026-10-20/{index}.jsonl.gz'
        path=tmp_path/f'{index}.jsonl.gz'
        raw_rows=[]
        for line in range(1,3):
            record=dict(url=f'https://example.org/{index}/{line}',http_status=200,
                        retrieved_at='2026-10-20T12:34:56Z')
            raw=dict(record=dict(record,content={'body':'raw-payload '*1000},
                prior_attempts=[dict(http_status=206,complete=False,content={'body':'prior '*1000})]),
                captures=[dict(sha256='a'*64,bytes=100,pointer=['content','body'])])
            rows.append(dict(record=record,captures=raw['captures'],file_references=None,
                __receipt_key=key,__receipt_line=line,__receipt_family='documents',
                __raw_line=json.dumps(raw),__type_conflicts=[]))
            raw_rows.append(raw)
        data=gzip.compress(''.join(json.dumps(raw)+'\n' for raw in raw_rows).encode(),mtime=0)
        qualification=write_qualified_bytes(path,data)
        files.append(dict(key=key,path=str(path),qualification=qualification))
    counter=tmp_path/'counter.parquet'
    write_qualified_parquet(pa.Table.from_pylist(rows,schema=schema),counter,row_group_size=2)
    return counter,files


def test_source_projection_selects_disjoint_bulk_leaves(tmp_path):
    from congress_api.lake.receipt_metadata import source_plan
    counter,_=counter_fixture(tmp_path)
    plan=source_plan(counter=counter)
    assert len(plan['inputs'])==1 and plan['inputs'][0]['path']==str(counter)
    sql=plan['steps'][0]['sql']
    assert 'json_get_many' in sql and "arrow_cast(json_get_json(__raw_line,'record'),'Utf8View')" in sql
    for excluded in ('prior_attempts','response_header_items','lockfile_digest','record_sha'):
        assert excluded not in sql
    assert not plan['steps'][0].get('materialize',False)


@pytest.mark.parametrize('operation',['plan','pins'])
def test_source_directory_counter_refuses_before_registration(tmp_path,operation):
    from congress_api.lake.receipt_metadata import source_plan,source_pins
    directory=tmp_path/'counter';directory.mkdir()
    with pytest.raises(ValueError,match='single.*file'):
        (source_plan if operation=='plan' else source_pins)(counter=directory)
