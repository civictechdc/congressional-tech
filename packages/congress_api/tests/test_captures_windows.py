"""Wide receipt evidence must leave capture rows before window sorting."""
import json
import os
from pathlib import Path

import pyarrow.parquet as pq

from docspec_client.client import NativeDatasets
from test_captures_typed import bounded_counter,assert_bounded_capture_rows
from test_captures_ingest import STAMP,body,ingest


def bounded_engine(tmp_path):
    """Fixed fixture controls, independent of production runtime limits."""
    settings=json.loads(Path(os.environ['DOCSPEC_JOB_CONFIG']).read_text())
    limits=json.loads(Path(settings['limits']).read_text())
    limits.update(memory_bytes=1<<30,scratch_bytes=64<<20,batch_rows=64,compute_threads=2)
    target=tmp_path/'limits.json';target.write_text(json.dumps(limits))
    settings['limits']=str(target)
    runtime=tmp_path/'runtime.json';runtime.write_text(json.dumps(settings))
    return NativeDatasets.from_config(runtime)


def test_unused_header_padding_fits_capture_mapping_budget(tmp_path):
    from congress_api.lake.captures import stage_captures
    counter,key=bounded_counter(tmp_path,header_padding=8192)
    native=bounded_engine(tmp_path)
    stage=stage_captures([dict(key=key)],engine=native,
        work=tmp_path/'stage',validated_counter=counter)
    actual=pq.read_table(stage/'captures.parquet')
    assert_bounded_capture_rows(actual,key)
    assert actual['h_content_disposition'].to_pylist()==['attachment; filename="window.pdf"']*131072
    for name in ('expansion','recovery_category','original_url','recovered_url','writer_job','writer_commit'):
        assert actual[name].null_count==131072
    assert all('window-padding-marker' not in str(row) for row in actual.to_pylist())


def test_completed_final_suppresses_inferred_cutoff_but_keeps_own_completeness(tmp_path):
    stage=ingest(tmp_path,[dict(record=dict(url='https://example.test/final',http_status=200,
        retrieved_at=STAMP,outcome='saved'),captures=[
            dict(body(),bytes=64<<20,complete=False),body(complete=True)])])
    rows=pq.read_table(stage/'captures.parquet').to_pylist()
    assert [row['outcome'] for row in rows]==['stored','stored']
    assert [row['complete'] for row in rows]==[False,True]


def test_member_expansion_stays_in_its_context_and_attempt(tmp_path):
    a='https://example.test/a';b='https://example.test/b'
    stage=ingest(tmp_path,[dict(record=dict(url=a,http_status=200,retrieved_at=STAMP),captures=[
        body(context_url=a,attempt=0),body(context_url=b,attempt=0),body(context_url=a,attempt=1),
        body(context_url=a,attempt=0,pointer=['archive_members',0,'body'],member_path='member.pdf'),
        body(context_url=b,attempt=0,expansion='publisher-explicit')])])
    rows=pq.read_table(stage/'captures.parquet').to_pylist()
    assert [row['expansion'] for row in rows]==['expanded',None,None,None,'publisher-explicit']
    assert [row['context_url'] for row in rows]==[a,b,a,a,b]


def test_retry_deadline_overrides_cutoff_inference(tmp_path):
    stage=ingest(tmp_path,[dict(record=dict(url='https://example.test/retry',http_status=200,
        retrieved_at=STAMP,outcome='saved',response_headers={'Retry-After':'120'}),
        captures=[dict(body(),bytes=64<<20,complete=False)])])
    [row]=pq.read_table(stage/'captures.parquet').to_pylist()
    assert row['outcome']=='retry_later' and row['complete'] is False
    assert row['retry_after'].isoformat()=='2026-10-20T12:36:56+00:00'


def test_wide_list_record_baseline_preserves_direct_counter_and_cache_rows(tmp_path):
    import pyarrow as pa
    from congress_api.lake.captures import stage_captures
    from congress_api.lake.receipt_metadata import compact
    from test_captures_ingest import files
    from test_captures_root_objects import minimal_counter
    key='receipts/documents/2026-10-20/window-list.jsonl.gz'
    padding='window-list-padding'+('x'*(8192-len('window-list-padding')))
    rows=[]
    for line in range(1,65):
        records=[dict(url=f'https://example.test/list/{line}/{index}',http_status=200,
            retrieved_at=STAMP,mode='fetch',outcome='stored',complete=True,
            response_headers={'X-Padding':padding,'content-disposition':f'attachment; filename="record-{index}.pdf"'},
            content={'body':'window-list-body-stays-raw'}) for index in range(16)]
        rows.append(dict(record=records,response_headers={'X-Padding':padding,
            'content-disposition':'attachment; filename="root-window.pdf"'},
            writer=dict(job='window-list',commit='d'*40),captures=[
                body(pointer=[index%16 if index<16 else str(index%16),'content','body'],
                    context_url=f'https://example.test/context/{index%2}',attempt=index%2,
                    http_status=200,complete=True) for index in range(32)]))
    source=files(tmp_path/'input',rows,key=key)
    counter=minimal_counter(tmp_path,[(key,row) for row in rows],False)
    table=pq.read_table(counter)
    table=table.set_column(table.schema.get_field_index('__receipt_line'),'__receipt_line',
        pa.array(range(1,65),type=pa.int64()))
    pq.write_table(table,counter)
    native=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    metadata=compact(counter=counter,engine=native,work=tmp_path/'metadata')
    for kind,arguments in [('direct',dict(files=source)),
                           ('counter',dict(files=[dict(key=key)],validated_counter=counter)),
                           ('cached',dict(files=[dict(key=key)],counter=metadata))]:
        stage=stage_captures(engine=native,work=tmp_path/kind,**arguments)
        actual=pq.read_table(stage/'captures.parquet')
        assert actual.num_rows==2048
        assert actual['receipt_line'].to_pylist()==[line for line in range(1,65) for _ in range(32)]
        assert actual['capture_index'].to_pylist()==list(range(32))*64
        assert actual['url'].to_pylist()==[f'https://example.test/list/{line}/{index%16}'
            for line in range(1,65) for index in range(32)]
        for name,value in [('http_status',200),('attempt_status',200),('complete',True),
            ('mode','fetch'),('outcome','stored'),('bytes',123),('sha256',bytes.fromhex('a'*64)),
            ('h_content_disposition','attachment; filename="root-window.pdf"'),
            ('writer_job','window-list'),('writer_commit','d'*40)]:
            assert actual[name].to_pylist()==[value]*2048
        assert all(value.isoformat()=='2026-10-20T12:34:56+00:00' for value in actual['retrieved_at'].to_pylist())
        assert actual['context_url'].to_pylist()==[f'https://example.test/context/{index%2}'
            for _ in range(64) for index in range(32)]
        for name in ('expansion','original_url','recovered_url','recovery_category'):
            assert actual[name].null_count==2048
        assert all('window-list-padding' not in str(row) and 'window-list-body-stays-raw' not in str(row)
                   for row in actual.to_pylist())
        if kind=='direct':
            expected=actual
        else:
            assert actual.equals(expected)


def test_capture_join_boundary_contains_only_scalar_facts(tmp_path):
    import pyarrow as pa
    from congress_api.lake.captures import PK,mapping_steps
    from congress_api.lake.receipt_metadata import compact
    from congress_api.retention.provenance import json_input,parquet_output,run_job
    from test_receipt_metadata import counter_fixture
    counter,files=counter_fixture(tmp_path)
    native=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    metadata=compact(counter=counter,engine=native,work=tmp_path/'metadata')
    work=tmp_path/'boundary';work.mkdir()
    steps=mapping_steps()
    boundary=next(index for index,step in enumerate(steps) if step['name']=='capture_scalars')
    inputs=[dict(name='receipts',kind='parquet',path=str(metadata)),
        json_input(work,'selected_receipts',[dict(receipt_key=row['key']) for row in files],receipt_key='Utf8')]
    run_job(work,native,inputs=inputs,steps=steps[:boundary+1],queries=[],outputs=[
        parquet_output(work,'scalars','SELECT * FROM capture_scalars',PK)])
    actual=pq.read_table(work/'scalars.parquet')
    assert actual.num_rows==6
    assert not {'line','record','record_values','entry','recovery','association','headers','prior_record'} & set(actual.column_names)
    assert not any(pa.types.is_nested(field.type) for field in actual.schema)
    assert all('raw-payload' not in str(row) and 'prior prior' not in str(row) for row in actual.to_pylist())
