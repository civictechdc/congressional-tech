"""The driver calls the incremental CLI and only releases a guarded generation."""
import json
import os

import pytest
from docspec_client.client import NativeDatasets

from congress_api.lake import capture_backfill
from test_captures_ingest import files as receipts


def inputs(tmp_path):
    files=[];counts=[]
    for index in range(2):
        key=f'receipts/documents/2026-10-28/batch-{index}.jsonl.gz'
        files+=receipts(tmp_path/str(index),[dict(run_id='batch-fixture',mode='fetch',outcome='failed',
            family='documents',http_status=404,url=f'https://fixture.test/{index}',record={})],key)
        counts.append(dict(key=key,source_rows=1,expected_captures=1,uncompressed_bytes=200,
            list_items=1,max_line_bytes=200,max_line_items=1))
    return files,counts


def test_real_two_batch_append_then_fresh_retry_never_reopens_raw(tmp_path):
    files,counts=inputs(tmp_path/'input')
    engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    common=dict(engine=engine,engine_config=os.environ['DOCSPEC_JOB_CONFIG'],
        table=dict(namespace=['batch_fixture'],name='captures_v1_gtest'),
        catalog_root=tmp_path/'catalog',location=tmp_path/'table',byte_target=1000,item_target=1)
    first=capture_backfill.execute_batches(files,counts,work=tmp_path/'first',
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


def test_driver_refuses_missing_counter_before_any_catalog_effect(tmp_path):
    key='receipts/documents/2026-10-28/no-counter.gz'
    counts=[dict(key=key,source_rows=1,expected_captures=1,uncompressed_bytes=1,list_items=1,
        max_line_bytes=1,max_line_items=1)]
    with pytest.raises(ValueError,match='counter'):
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
