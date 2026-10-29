"""The driver calls the incremental CLI and only releases a guarded generation."""
import json
import os

import pytest
from docspec_client.client import NativeDatasets

from congress_api.lake import capture_backfill
from test_captures_ingest import files as receipts
from test_capture_backfill_scratch import over_default_allocated_root


def inputs(tmp_path):
    files=[];counts=[]
    for index in range(2):
        key=f'receipts/documents/2026-10-28/batch-{index}.jsonl.gz'
        files+=receipts(tmp_path/str(index),[dict(run_id='batch-fixture',mode='fetch',outcome='failed',
            family='documents',http_status=404,url=f'https://fixture.test/{index}',record={})],key)
        counts.append(dict(key=key,source_rows=1,expected_captures=1,uncompressed_bytes=200,
            list_items=1,max_line_bytes=200,max_line_items=1))
    return files,counts


def test_real_two_batch_append_then_fresh_retry_never_reopens_raw(tmp_path,over_default_allocated_root):
    files,counts=inputs(tmp_path/'input')
    engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    common=dict(engine=engine,engine_config=os.environ['DOCSPEC_JOB_CONFIG'],
        table=dict(namespace=['batch_fixture'],name='captures_v1_gtest'),
        catalog_root=tmp_path/'catalog',location=tmp_path/'table',byte_target=1000,item_target=1)
    # A retained sibling larger than the default quota belongs to another job.
    work=over_default_allocated_root.parent/'first'
    first=capture_backfill.execute_batches(files,counts,work=work,
        create_table=True,create_namespace=True,**common)
    assert first['status']=='public_guard_passed' and first['qualified_for_downstream'] is False
    assert len(first['batches'])==2 and first['guard']['rows']==2 and first['guard']['receipts']==2
    assert all(batch['measurement']['sampled_peak_tree_physical_footprint']>0 for batch in first['batches'])
    assert len({batch['measurement']['owned_pgid'] for batch in first['batches']})==2
    for row in files:
        from pathlib import Path
        Path(row['path']).unlink();Path(row['qualification']).unlink()
    second=capture_backfill.execute_batches(files,counts,work=tmp_path/'retry',**common)
    assert second['guard']['rows']==2 and second['guard']['receipts']==2
    assert all(batch['outcome']['no_work'] for batch in second['batches'])


def test_driver_refuses_counter_source_before_any_catalog_effect(tmp_path):
    key='receipts/documents/2026-10-28/no-counter.gz'
    counts=[dict(key=key,source_rows=1,expected_captures=1,uncompressed_bytes=1,list_items=1,
        max_line_bytes=1,max_line_items=1)]
    with pytest.raises(ValueError,match='source'):
        capture_backfill.execute_batches([dict(key=key)],counts,
            engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
            engine_config=os.environ['DOCSPEC_JOB_CONFIG'],work=tmp_path/'work',
            table=dict(namespace=['must_not_exist'],name='captures_gtest'),
            catalog_root=tmp_path/'catalog',location=tmp_path/'table',create_table=True,
            create_namespace=True,byte_target=100,item_target=10)
    assert not (tmp_path/'catalog').exists() and not (tmp_path/'table').exists()


def test_validation_child_rejects_unbound_job_shape_before_catalog(tmp_path):
    spec=tmp_path/'spec.json';spec.write_text(json.dumps(dict(arbitrary='callback')))
    with pytest.raises(ValueError,match='validation spec'):
        capture_backfill.validate_spec(spec)


def test_driver_refuses_unowned_outputs_before_any_catalog_effect(tmp_path):
    files,counts=inputs(tmp_path/'input')
    with pytest.raises(ValueError,match='Owned scratch'):
        capture_backfill.execute_batches(files,counts,
            engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
            engine_config=os.environ['DOCSPEC_JOB_CONFIG'],work=tmp_path/'work',
            table=dict(namespace=['must_not_exist'],name='captures_gtest'),
            catalog_root=tmp_path/'catalog',location=tmp_path/'table',create_table=True,
            create_namespace=True,scratch_root=tmp_path/'different-owned-root')
    assert not (tmp_path/'catalog').exists() and not (tmp_path/'table').exists()


def test_failed_batch_status_keeps_the_measured_failed_process_peak(tmp_path):
    key='receipts/documents/2026-10-28/invalid-mode.jsonl.gz'
    files=receipts(tmp_path/'input',[dict(run_id='bad',mode='unknown-mode',outcome='failed',
        family='documents',http_status=404,url='https://fixture.test/bad',record={})],key)
    counts=[dict(key=key,source_rows=1,expected_captures=1,uncompressed_bytes=200,
        list_items=1,max_line_bytes=200,max_line_items=1)]
    with pytest.raises(RuntimeError,match='Batch exited'):
        capture_backfill.execute_batches(files,counts,
            engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
            engine_config=os.environ['DOCSPEC_JOB_CONFIG'],work=tmp_path/'work',
            table=dict(namespace=['invalid_fixture'],name='captures'),
            catalog_root=tmp_path/'catalog',location=tmp_path/'table',create_table=True,
            create_namespace=True,progress_log=tmp_path/'status.jsonl')
    measurements=list((tmp_path/'work').glob('batch-*/monitor/measurement.json'))
    assert len(measurements)==1
    actual=json.loads(measurements[0].read_text())['sampled_peak_tree_physical_footprint']
    last=json.loads((tmp_path/'status.jsonl').read_text().splitlines()[-1])
    assert actual>0 and last['status']=='fail'
    assert last['peak_phys_gb']==actual/1e9


def test_driver_rejects_historical_counter_flag_even_with_direct_files(tmp_path):
    files,counts=inputs(tmp_path/'raw')
    with pytest.raises(ValueError,match='counter'):
        capture_backfill.execute_batches(files,counts,engine=None,engine_config='unopened',
            work=tmp_path/'work',table={},catalog_root=tmp_path/'catalog',
            validated_counter=tmp_path/'historical.parquet')
    assert not (tmp_path/'catalog').exists()
