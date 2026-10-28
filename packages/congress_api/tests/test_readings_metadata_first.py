"""Known oversized pages settle from pinned metadata before raw body access."""
import hashlib
import os

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from docspec_client.client import NativeDatasets

from congress_api.lake import readings
from congress_api.retention.body_store import BodyStore,LocalAdapter


def missing_inputs(tmp_path,*,format,size,proof='capture',settled=False):
    digest=hashlib.sha256(b'unavailable synthetic metadata-first source').digest()
    key='bodies/sha256/'+digest.hex()[:2]+'/'+digest.hex()
    raw=tmp_path/'raw';raw.mkdir()
    captures=tmp_path/'captures.parquet'
    capture=dict(sha256=digest,bytes=size,media_type='application/octet-stream',fidelity='exact-bytes',
        sniffed_format=format if proof=='capture' else None,
        sniff_version=readings.current_version('sniff') if proof=='capture' and format is not None else None)
    pq.write_table(pa.Table.from_pylist([capture],schema=pa.schema([
        ('sha256',pa.binary(32)),('bytes',pa.int64()),('media_type',pa.string()),('fidelity',pa.string()),
        ('sniffed_format',pa.string()),('sniff_version',pa.string()),('intact',pa.bool_())])),captures)
    inventory=tmp_path/'inventory.parquet'
    pq.write_table(pa.Table.from_pylist([dict(body_sha=digest,physical_key=key,relative_path=key,
        stored_bytes=size,stored_gzip=False)]),inventory)
    existing=tmp_path/'existing.parquet';rows=[]
    if proof=='reading' and format is not None:
        rows.append(dict(body_sha=digest,parser='sniff',parser_version=readings.current_version('sniff'),
            status='completed',format=format))
    if settled:
        rows.append(dict(body_sha=digest,parser=format,parser_version=readings.current_version(format),
            status='size_limit',error_type='stored_size_limit'))
    pq.write_table(pa.Table.from_pylist(rows,schema=pa.schema([('body_sha',pa.binary(32)),
        ('parser',pa.string()),('parser_version',pa.string()),('status',pa.string()),
        ('format',pa.string()),('intact',pa.bool_()),('error_type',pa.string())])),existing)
    assert not (raw/key).exists()
    return dict(captures=captures,body_inventory=inventory,existing=existing,local_root=raw,
        engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
        unreadable_store=BodyStore(LocalAdapter(tmp_path/'durable')),
        decided_at='2026-10-28T12:00:00Z'),digest


@pytest.mark.parametrize('format',['html','xml','json'])
@pytest.mark.parametrize('proof',['capture','reading'])
def test_known_oversize_missing_body_settles_the_actual_leaf_without_a_sniff(tmp_path,format,proof):
    args,digest=missing_inputs(tmp_path,format=format,size=readings.MAX_STORED_BYTES+1,proof=proof)
    result=readings.stage_once(**args,work=tmp_path/'stage')
    assert result['pending_reads']==0 and result['read_bytes']==0 and result['unreadable']==0
    assert pq.read_metadata(result['work_list']).num_rows==1
    [row]=pq.read_table(result['readings']).to_pylist()
    assert (row['body_sha'],row['parser'],row['parser_version'],row['status'],row['error_type'])==(
        digest,format,readings.current_version(format),'size_limit','stored_size_limit')
    assert row['format'] is None and result['unreadable_key'] is None
    assert not (tmp_path/'stage/body-bytes').exists()


@pytest.mark.parametrize('format,size',[(None,readings.MAX_STORED_BYTES+1),
    ('html',123),('xml',123),('json',123)])
def test_missing_body_still_stays_pending_when_bytes_are_needed(tmp_path,format,size):
    args,_=missing_inputs(tmp_path,format=format,size=size)
    result=readings.stage_once(**args,work=tmp_path/'stage')
    assert result['pending_reads']==1 and result['read_bytes']==0 and result['unreadable']==0
    assert pq.read_metadata(result['readings']).num_rows==0 and result['unreadable_key'] is None


@pytest.mark.parametrize('format',['html','xml','json'])
def test_current_page_size_limit_is_already_settled_without_raw_access(tmp_path,format):
    args,_=missing_inputs(tmp_path,format=format,size=readings.MAX_STORED_BYTES+1,proof='reading',settled=True)
    result=readings.stage_once(**args,work=tmp_path/'stage')
    assert result['pending_reads']==0 and result['read_bytes']==0 and result['unreadable']==0
    assert pq.read_metadata(result['work_list']).num_rows==0
    assert pq.read_metadata(result['readings']).num_rows==0
