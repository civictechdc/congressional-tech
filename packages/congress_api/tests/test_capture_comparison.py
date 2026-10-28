"""D1 parity diagnoses differences; derived-only facts remain owner decisions."""
import os
from pathlib import Path

import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from docspec_client.client import NativeDatasets


def test_comparison_keeps_old_only_and_explains_declared_transformations(tmp_path):
    from congress_api.lake.capture_comparison import compare_old
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    old_schema = pa.schema([(k,t) for k,t in (
        ('receipt_key',pa.string()),('receipt_line',pa.int64()),('reference_kind',pa.string()),
        ('pointer_json',pa.string()),('sha256',pa.string()),('context_url',pa.string()),
        ('bytes',pa.int64()),('stored_bytes',pa.int64()),('media_type',pa.string()),
        ('fidelity',pa.string()),('http_status',pa.int64()),('retrieved_at',pa.string()))])
    old = tmp_path/'old.parquet'
    base = dict(receipt_key='receipts/documents/2026-10-20/run.jsonl.gz',receipt_line=1,
        reference_kind='capture',pointer_json='["body", 0]',sha256='a'*64,
        context_url='https://example.org/a',bytes=100,stored_bytes=None,
        media_type='application/pdf',fidelity='exact-bytes',http_status=None,retrieved_at=None)
    pq.write_table(pa.Table.from_pylist([base, dict(base,reference_kind='file',
        pointer_json='["old-file"]',stored_bytes=42), dict(base,receipt_line=2,sha256='b'*64)],schema=old_schema),old)
    new = tmp_path/'new.parquet'
    schema = pa.schema([(k,t) for k,t in (
        ('receipt_key',pa.string()),('receipt_line',pa.int32()),('capture_index',pa.int32()),
        ('pointer_json',pa.string()),('sha256',pa.binary(32)),('context_url',pa.string()),
        ('bytes',pa.int64()),('stored_bytes',pa.int64()),('media_type',pa.string()),
        ('fidelity',pa.string()),('http_status',pa.int32()),('retrieved_at',pa.timestamp('us','UTC')))])
    row = {k:v for k,v in base.items() if k in schema.names}
    row.update(sha256=bytes.fromhex('a'*64),capture_index=0,pointer_json='["body",0]',
        http_status=200,stored_bytes=42)
    pq.write_table(pa.Table.from_pylist([row],schema=schema),new)
    report = compare_old(new,old,engine=engine,work=tmp_path/'comparison')
    assert report['old_rows']==3 and report['new_rows']==1
    assert report['secondary_duplicates']==1 and report['old_only']==1
    assert report['new_only']==report['unexplained']==0
    assert report['expected_changes']==1
    [lost] = pq.read_table(tmp_path/'comparison/old-only.parquet').to_pylist()
    assert lost['sha256']=='b'*64 and lost['receipt_line']==2
    assert report['owner_gate'] is True


def test_unexplained_receipt_fact_change_is_not_accepted_as_restoration(tmp_path):
    from congress_api.lake.capture_comparison import compare_old
    old=tmp_path/'old.parquet';new=tmp_path/'new.parquet'
    base=dict(receipt_key='receipts/f/2026-10-20/run.gz',receipt_line=1,
        pointer_json='[]',context_url='https://example.org/a',bytes=100,
        stored_bytes=42,media_type='text/plain',fidelity='exact-bytes',
        http_status=200,retrieved_at=None)
    pq.write_table(pa.Table.from_pylist([dict(base,sha256='a'*64,reference_kind='capture')]),old)
    pq.write_table(pa.Table.from_pylist([dict(base,sha256=bytes.fromhex('a'*64),
        capture_index=0,bytes=99)]),new)
    report=compare_old(new,old,engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
                       work=tmp_path/'comparison')
    assert report['unexplained']==1 and report['owner_gate'] is True
    [changed]=pq.read_table(tmp_path/'comparison/changed-fields.parquet').to_pylist()
    assert (changed['old_bytes'],changed['new_bytes'])==(100,99)


@pytest.mark.parametrize('old_time,new_time,expected,unexplained,reason', [
    (None,'2026-10-20T08:00:00Z',1,0,'missing_time_restored'),
    ('2026-10-20T08:00:00Z',None,0,1,'timestamp_lost'),
    ('2026-10-20T08:00:00Z','2026-10-21T08:00:00Z',0,1,'timestamp_changed'),
    ('2026-10-20T08:00:00Z','2026-10-20T10:00:00+02:00',0,0,'unchanged'),
    ('2026-10-20T08:00:00Z','invalid',0,1,'invalid_new_timestamp'),
    ('invalid','2026-10-20T08:00:00Z',0,1,'invalid_old_timestamp'),
])
def test_fetch_time_comparison_accepts_only_declared_restoration(
        tmp_path,old_time,new_time,expected,unexplained,reason):
    from congress_api.lake.capture_comparison import compare_old
    old=tmp_path/'old.parquet';new=tmp_path/'new.parquet'
    base=dict(receipt_key='receipts/f/2026-10-20/run.gz',receipt_line=1,
        pointer_json='[]',context_url='https://example.org/a',bytes=100,
        stored_bytes=42,media_type='text/plain',fidelity='exact-bytes',http_status=200)
    old_row=dict(base,sha256='a'*64,reference_kind='capture',retrieved_at=old_time)
    new_row=dict(base,sha256=bytes.fromhex('a'*64),capture_index=0,retrieved_at=new_time)
    for path,row in ((old,old_row),(new,new_row)):
        fields=pa.Table.from_pylist([row]).schema
        fields=fields.set(fields.get_field_index('retrieved_at'),pa.field('retrieved_at',pa.string()))
        pq.write_table(pa.Table.from_pylist([row],schema=fields),path)
    report=compare_old(new,old,engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
                       work=tmp_path/'comparison')
    assert report['expected_changes']==expected
    assert report['unexplained']==unexplained
    assert report['owner_gate'] is bool(unexplained)
    changed=pq.read_table(tmp_path/'comparison/changed-fields.parquet').to_pylist()
    if expected or unexplained:
        [row]=changed
        assert row['old_retrieved_at']==old_time and row['new_retrieved_at']==new_time
        assert row['retrieved_at_reason']==reason
    else:
        assert changed==[]


@pytest.mark.parametrize('old_count,new_count,old_only,new_only,matched',[
    (2,1,1,0,1),(1,2,0,1,1),(2,2,0,0,2),
])
def test_comparison_preserves_repeated_capture_occurrences(
        tmp_path,old_count,new_count,old_only,new_only,matched):
    from congress_api.lake.capture_comparison import compare_old
    old=tmp_path/'old.parquet';new=tmp_path/'new.parquet'
    base=dict(receipt_key='receipts/f/2026-10-20/run.gz',receipt_line=1,
        pointer_json='[]',context_url='https://example.org/a',bytes=100,
        stored_bytes=42,media_type='text/plain',fidelity='exact-bytes',http_status=200,
        retrieved_at='2026-10-20T00:00:00Z')
    pq.write_table(pa.Table.from_pylist([dict(base,sha256='a'*64,reference_kind='capture')
        for _ in range(old_count)]),old)
    pq.write_table(pa.Table.from_pylist([dict(base,sha256=bytes.fromhex('a'*64),capture_index=i)
        for i in range(new_count)]),new)
    report=compare_old(new,old,engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
                       work=tmp_path/'comparison')
    assert report['matched']==matched
    assert report['old_only']==old_only and report['new_only']==new_only
    assert report['owner_gate'] is bool(old_only or new_only)
    assert pq.read_metadata(tmp_path/'comparison/old-only.parquet').num_rows==old_only
    assert pq.read_metadata(tmp_path/'comparison/new-only.parquet').num_rows==new_only


def test_repeated_times_rank_by_utc_instant_without_losing_source_spelling(tmp_path):
    from datetime import datetime
    from congress_api.lake.capture_comparison import compare_old
    base=dict(receipt_key='receipts/f/2026-10-20/run.gz',receipt_line=1,
        pointer_json='[]',context_url='https://example.org/a',bytes=100,
        stored_bytes=42,media_type='text/plain',fidelity='exact-bytes',http_status=200)
    old_times=['2026-10-20T01:00:00+01:00','2026-10-20T00:30:00Z']
    new_times=['2026-10-20T00:00:00+00:00','2026-10-20T00:30:00+00:00']
    old=tmp_path/'old.parquet';new=tmp_path/'new.parquet'
    pq.write_table(pa.Table.from_pylist([dict(base,sha256='a'*64,reference_kind='capture',
        retrieved_at=value) for value in old_times]),old)
    rows=[dict(base,sha256=bytes.fromhex('a'*64),capture_index=index,
        retrieved_at=datetime.fromisoformat(value)) for index,value in enumerate(new_times)]
    pq.write_table(pa.Table.from_pylist(rows),new)
    report=compare_old(new,old,engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
        work=tmp_path/'comparison')
    assert report['matched']==2 and report['unexplained']==0 and report['owner_gate'] is False
    assert pq.read_metadata(tmp_path/'comparison/changed-fields.parquet').num_rows==0
    assert pq.read_table(old)['retrieved_at'].to_pylist()==old_times
