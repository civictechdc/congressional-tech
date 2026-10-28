"""Native body work lists feed bounded parsers once per input and version."""
import hashlib
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.lake import readings
from docspec_client.client import NativeDatasets


def setup(tmp_path, body=b'<html><body><p>Evidence</p><a href="a.pdf">PDF</a></body></html>',
          *, copies=2, size=None, missing=False, body_format='html',logical_body=None):
    raw=tmp_path/'raw';raw.mkdir()
    digest=hashlib.sha256(body if logical_body is None else logical_body).digest()
    key='bodies/sha256/'+digest.hex()[:2]+'/'+digest.hex()
    path=raw/key;path.parent.mkdir(parents=True)
    if not missing:path.write_bytes(body)
    captures=tmp_path/'captures.parquet'
    schema=pa.schema([('sha256',pa.binary(32)),('stored_bytes',pa.int64()),('stored_suffix',pa.string())])
    pq.write_table(pa.Table.from_pylist([dict(sha256=digest,stored_bytes=len(body) if size is None else size,
        stored_suffix='')]*copies,schema=schema),captures)
    existing=tmp_path/'sniff.parquet'
    pq.write_table(pa.Table.from_pylist([dict(body_sha=digest,parser='sniff',parser_version='sniff-fixture',
        status='completed',format=body_format)],schema=pa.schema([('body_sha',pa.binary(32)),
        ('parser',pa.string()),('parser_version',pa.string()),('status',pa.string()),('format',pa.string())])),existing)
    inventory=tmp_path/'bodies.parquet'
    pq.write_table(pa.Table.from_pylist([dict(body_sha=digest,physical_key=key,relative_path=key,
        stored_bytes=len(body) if size is None else size,stored_gzip=False)],schema=pa.schema([
        ('body_sha',pa.binary(32)),('physical_key',pa.string()),('relative_path',pa.string()),('stored_bytes',pa.int64()),
        ('stored_gzip',pa.bool_())])),inventory)
    return dict(captures=captures,body_inventory=inventory,local_root=raw,existing=existing,
                engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
                decided_at='2026-10-27T12:00:00Z'),digest


def stage(args,tmp_path,**kwargs):
    return readings.stage(**{**args,**kwargs},work=tmp_path,parser='html',sniff_version='sniff-fixture')


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


def test_active_unreadable_skips_only_its_parser_version(tmp_path):
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
    assert first['kind']==repeated['kind']=='append'
    assert sum(item['rows'] for item in first['files'])==1 and repeated['files']==[]
    assert first['snapshot']==repeated['snapshot']
    assert first['metadata_location']==repeated['metadata_location']


def test_absent_inventory_entry_remains_on_the_work_list(tmp_path):
    args,_=setup(tmp_path)
    inventory=pq.read_table(args['body_inventory']).slice(0,0)
    pq.write_table(inventory,args['body_inventory'])
    result=stage(args,tmp_path/'stage')
    assert pq.ParquetFile(result['work_list']).metadata.num_rows==1
    assert pq.ParquetFile(result['readings']).metadata.num_rows==0
    assert result['pending_reads']==1 and result['unreadable_path'] is None


def test_read_only_cache_layout_keeps_physical_identity_separate_from_local_path(tmp_path):
    args,digest=setup(tmp_path)
    rows=pq.read_table(args['body_inventory']).to_pylist()
    original=args['local_root']/rows[0]['physical_key']
    cache=args['local_root']/'cached-body.stored'
    original.rename(cache)
    rows[0]['relative_path']='cached-body.stored'
    pq.write_table(pa.Table.from_pylist(rows),args['body_inventory'])
    result=stage(args,tmp_path/'stage')
    assert pq.read_table(result['readings']).to_pylist()[0]['body_sha']==digest
    assert result['pending_reads']==0
    assert cache.read_bytes().startswith(b'<html>')


@pytest.mark.parametrize('relative_path',['../outside','/absolute'])
def test_cache_path_escape_refuses_before_body_read(tmp_path,relative_path):
    args,_=setup(tmp_path)
    rows=pq.read_table(args['body_inventory']).to_pylist()
    rows[0]['relative_path']=relative_path
    pq.write_table(pa.Table.from_pylist(rows),args['body_inventory'])
    with pytest.raises(ValueError,match='relative|escapes'):
        stage(args,tmp_path/'stage')


def test_readings_cli_stages_locally_and_reports_pending_without_applying(tmp_path,capsys):
    from congress_api.cli.readings import main
    args,_=setup(tmp_path,missing=True)
    spec={k:str(v) if hasattr(v,'__fspath__') else v for k,v in args.items() if k!='engine'}
    spec.update(parser='html',sniff_version='sniff-fixture',work=str(tmp_path/'stage'))
    path=tmp_path/'spec.json';path.write_text(json.dumps(spec))
    assert main(['--spec',str(path)])==0
    result=json.loads(capsys.readouterr().out)
    assert result['pending_reads']==1 and result['applied'] is False
    assert pq.ParquetFile(result['readings']).metadata.num_rows==0


def test_post_read_decoded_bound_is_an_error_not_pre_read_size_limit(tmp_path):
    import gzip
    decoded=b'x'*(readings.MAX_DECODED_BYTES+1)
    body=gzip.compress(decoded,mtime=0)
    args,_=setup(tmp_path,body=body,logical_body=decoded)
    rows=pq.read_table(args['body_inventory']).to_pylist()
    rows[0]['stored_gzip']=True
    pq.write_table(pa.Table.from_pylist(rows),args['body_inventory'])
    result=stage(args,tmp_path/'stage')
    row=pq.read_table(result['readings']).to_pylist()[0]
    assert row['status']=='error' and row['error_type']=='decoded_size_limit'
    assert result['pending_reads']==0 and result['read_bytes']>0


def test_unreadable_batches_from_one_run_use_distinct_stable_raw_keys(tmp_path):
    class FailedWorker:
        def __init__(self,*args,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def parse(self,*args):return dict(status='unreadable',reason='parser_crash',attempts=2)
    args,_=setup(tmp_path)
    page=stage(args,tmp_path/'html',worker_factory=FailedWorker)
    sniff=readings.stage(**args,work=tmp_path/'sniff',parser='sniff',worker_factory=FailedWorker)
    repeated=stage(args,tmp_path/'repeated',worker_factory=FailedWorker)
    assert page['unreadable_key']!=sniff['unreadable_key']
    assert page['unreadable_key']==repeated['unreadable_key']
    assert Path(page['unreadable_path']).read_bytes()==Path(repeated['unreadable_path']).read_bytes()


@pytest.mark.parametrize('sniff_state', ['current','missing','old','failed'])
def test_page_work_requires_a_completed_pinned_sniff_reading(tmp_path,sniff_state):
    args,_=setup(tmp_path)
    table=pq.read_table(args['existing'])
    if sniff_state=='missing':table=table.slice(0,0)
    elif sniff_state in {'old','failed'}:
        row=table.to_pylist()[0]
        row['parser_version']='old' if sniff_state=='old' else 'sniff-fixture'
        row['status']='error' if sniff_state=='failed' else 'completed'
        table=pa.Table.from_pylist([row],schema=table.schema)
    pq.write_table(table,args['existing'])
    result=stage(args,tmp_path/'stage')
    expected=1 if sniff_state=='current' else 0
    assert pq.ParquetFile(result['work_list']).metadata.num_rows==expected
    assert pq.ParquetFile(result['readings']).metadata.num_rows==expected
