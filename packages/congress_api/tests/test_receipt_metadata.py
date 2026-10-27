"""Bounded receipt-key batches preserve native metadata and pinned outputs."""
import gzip
import json
import os

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from docspec_client.client import NativeDatasets


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
        with gzip.open(path,'wt') as output:
            output.write(''.join(json.dumps(raw)+'\n' for raw in raw_rows))
        files.append(dict(key=key,path=str(path)))
    counter=tmp_path/'counter.parquet'
    pq.write_table(pa.Table.from_pylist(rows,schema=schema),counter,row_group_size=2)
    return counter,files


def engine():
    return NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])


def test_batched_counter_matches_single_native_projection_and_pins_parts(tmp_path):
    from congress_api.lake.receipt_metadata import compact, compact_counter, validate_metadata
    counter,files=counter_fixture(tmp_path)
    native=engine()
    single=compact(counter=counter,engine=native,work=tmp_path/'single')
    parts=compact_counter(counter,engine=native,work=tmp_path/'batched',receipt_batch_size=1)
    assert parts.is_dir() and len(list(parts.glob('*.parquet')))==3
    actual=pq.read_table(parts)
    assert actual.equals(pq.read_table(single))
    assert actual.num_rows==6
    descriptor=validate_metadata(parts,engine=native)
    assert descriptor['version']==2 and descriptor['kind']=='receipt-metadata'
    assert descriptor['rows']==6 and descriptor['receipts']==3
    assert descriptor['selection']['receipt_batch_size']==1
    assert descriptor['selection']['receipt_keys']==[row['key'] for row in files]
    assert [entry['path'] for entry in descriptor['files']]==sorted(entry['path'] for entry in descriptor['files'])
    assert len(descriptor['source'])==1 and descriptor['source'][0]['path']==str(counter)
    for batch in sorted((tmp_path/'batched/jobs').iterdir()):
        job=json.loads((batch/'job.json').read_text())
        steps={step['name']:step for step in job['steps']}
        assert 'WHERE __receipt_key IN' in steps['counter']['sql']
        assert not steps['counter'].get('materialize',False)
        assert steps['small_records']['materialize'] is True
        assert steps['root_metadata']['materialize'] is True
    assert all('raw-payload' not in str(row) and 'prior prior' not in str(row)
               for row in actual.to_pylist())


def test_explicit_selection_is_native_and_empty_selection_has_valid_schema(tmp_path):
    from congress_api.lake.receipt_metadata import compact_counter, validate_metadata
    counter,files=counter_fixture(tmp_path)
    native=engine()
    selected=compact_counter(counter,engine=native,work=tmp_path/'selected',
        receipt_keys=[files[1]['key']],receipt_batch_size=2)
    assert pq.read_table(selected)['__receipt_key'].to_pylist()==[files[1]['key']]*2
    assert validate_metadata(selected)['receipts']==1
    empty=compact_counter(counter,engine=native,work=tmp_path/'empty',receipt_keys=[])
    assert pq.read_table(empty).num_rows==0
    assert pq.ParquetDataset(empty).schema==pq.ParquetDataset(selected).schema
    assert validate_metadata(empty)['rows']==0
    with pytest.raises(ValueError,match='not present'):
        compact_counter(counter,engine=native,work=tmp_path/'missing',
            receipt_keys=['receipts/documents/2026-10-20/missing.gz'])


@pytest.mark.parametrize('size',[True,False,0,-1,1.5,'1',1025])
def test_invalid_receipt_batch_size_refuses_before_stage_creation(tmp_path,size):
    from congress_api.lake.receipt_metadata import compact_counter
    with pytest.raises(ValueError,match='batch'):
        compact_counter(tmp_path/'unopened-counter',engine=engine(),work=tmp_path/'refused',
                        receipt_batch_size=size)
    assert not (tmp_path/'refused').exists()


def test_metadata_validation_refuses_changed_parts_definition_and_runtime(tmp_path):
    from congress_api.lake.receipt_metadata import compact_counter, validate_metadata
    counter,_=counter_fixture(tmp_path)
    parts=compact_counter(counter,engine=engine(),work=tmp_path/'batch')
    manifest=tmp_path/'batch/metadata.json'
    original=manifest.read_text();descriptor=json.loads(original)
    descriptor['producer']['sha256']='0'*64
    manifest.write_text(json.dumps(descriptor))
    with pytest.raises(ValueError,match='producer'):
        validate_metadata(parts)
    descriptor=json.loads(original);descriptor['producer']['binary_sha256']='0'*64
    manifest.write_text(json.dumps(descriptor))
    with pytest.raises(ValueError,match='runtime'):
        validate_metadata(parts,engine=engine())
    manifest.write_text(original)
    [part]=list(parts.glob('*.parquet'))
    with part.open('ab') as output:
        output.write(b'changed')
    with pytest.raises(ValueError,match='pin'):
        validate_metadata(parts)


def test_prior_metadata_contains_only_real_array_attempts(tmp_path):
    from congress_api.lake.receipt_metadata import metadata_plan
    from congress_api.retention.provenance import run_job
    counter,files=counter_fixture(tmp_path)
    table=pq.read_table(counter);rows=table.to_pylist()
    # Absent, null, empty and object-shaped values contain no array attempts.
    # Explicit null elements of a real array still occupy their source slot.
    values=[None,None,[],dict(http_status=200,complete=False),
            [dict(http_status=206,complete=False)],[None,dict(http_status=503,complete=False)]]
    for index,(row,value) in enumerate(zip(rows,values)):
        source=json.loads(row['__raw_line']);source['record'].pop('prior_attempts',None)
        if index:
            source['record']['prior_attempts']=value
            source['prior_attempts']=value
        row['__raw_line']=json.dumps(source)
    pq.write_table(pa.Table.from_pylist(rows,schema=table.schema),counter)
    plan=metadata_plan(counter=counter)
    boundary=next(index for index,step in enumerate(plan['steps']) if step['name']=='prior_metadata')
    steps=plan['steps'][:boundary+1]
    work=tmp_path/'prior';work.mkdir()
    result=run_job(work,engine(),inputs=plan['inputs'],steps=steps,outputs=[],queries=[
        dict(name='prior',sql='''SELECT receipt_key,receipt_line,record_index,
            cast(prior_json AS VARCHAR) AS value FROM prior_metadata
            ORDER BY receipt_key,receipt_line,record_index''')])['prior']
    assert [(row['receipt_key'],row['receipt_line'],row['record_index']) for row in result]==[
        (files[2]['key'],1,-1),(files[2]['key'],1,0),(files[2]['key'],2,-1),(files[2]['key'],2,0)]
    for row in result:
        attempts=json.loads(row['value'])
        if row['receipt_line']==1:
            assert len(attempts)==1 and attempts[0]['http_status']==206 and attempts[0]['complete'] is False
        else:
            assert len(attempts)==2 and all(value is None for value in attempts[0].values())
            assert attempts[1]['http_status']==503 and attempts[1]['complete'] is False
