"""One-shot and whole-receipt batch rebuilding must preserve every public fact."""
import json
import os
from pathlib import Path

import pytest
from docspec_client.client import NativeDatasets


def metrics(key,cost,**changes):
    return dict(key=key,source_rows=1,uncompressed_bytes=cost,list_items=cost,
        expected_captures=1,max_line_bytes=1,max_line_items=1,**changes)


def test_equivalence_sample_includes_each_extreme_then_cheapest_not_top200():
    from congress_api.lake.capture_backfill_proof import select_sample
    keys=[f'receipts/test/2026-10-28/{i:04d}.jsonl.gz' for i in range(250)]
    files=[dict(key=key) for key in keys]
    counts=[metrics(key,i+1) for i,key in enumerate(keys)]
    counts[247]['max_line_bytes']=248
    counts[248]['max_line_items']=249
    selected=select_sample(files,counts,byte_target=100,item_target=100)
    assert len(selected['files'])==200
    assert set(selected['mandatory_keys'])==set(keys[-3:])
    assert {row['key'] for row in selected['files']}==set(keys[:197]+keys[-3:])
    assert selected['counts']==[r for r in counts if r['key'] in set(keys[:197]+keys[-3:])]


def test_equivalence_sample_uses_only_original_counter_receipts_and_is_order_independent():
    from congress_api.lake.capture_backfill_proof import select_sample
    files=[dict(key='receipts/test/2026-10-28/'+name+'.gz') for name in ['a','b','c','d']]
    counts=[metrics(row['key'],index+1) for index,row in enumerate(files)]
    files[2]['path']='/explicit/direct.gz';files[3]['prepared_stage']='/explicit/accepted'
    one=select_sample(files,counts,byte_target=10,item_target=10)
    two=select_sample(list(reversed(files)),list(reversed(counts)),byte_target=10,item_target=10)
    assert one==two
    assert one['files']==files[:2] and len(one['counts'])==2
    assert one['excluded_non_counter_keys']==[files[2]['key'],files[3]['key']]


@pytest.mark.parametrize('size',[0,False,1])
def test_invalid_or_too_small_sample_refuses_without_losing_required_extremes(size):
    from congress_api.lake.capture_backfill_proof import select_sample
    files=[dict(key='receipts/test/2026-10-28/'+name+'.gz') for name in ['a','b','c']]
    counts=[metrics(row['key'],10) for row in files]
    counts[0]['max_line_bytes']=10;counts[1]['max_line_items']=10
    counts[2]['uncompressed_bytes']=20
    with pytest.raises(ValueError):select_sample(files,counts,byte_target=10,item_target=10,sample_size=size)


def test_sample_refuses_missing_counts_or_no_original_counter_source():
    from congress_api.lake.capture_backfill_proof import select_sample
    row=dict(key='receipts/test/2026-10-28/a.gz')
    with pytest.raises(ValueError):select_sample([row],[],byte_target=10,item_target=10)
    with pytest.raises(ValueError,match='counter'):
        select_sample([dict(row,path='/direct.gz')],[metrics(row['key'],1)],byte_target=10,item_target=10)


def test_native_comparison_checks_every_public_field_and_both_directions(tmp_path):
    from congress_api.lake.capture_backfill_proof import compare_tables,EquivalenceMismatch
    from test_capture_backfill_guard import rows,source
    values=rows();left=tmp_path/'left';left.mkdir();right=tmp_path/'right';right.mkdir()
    left_path=source(left,values);right_path=source(right,values)
    native=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    report=compare_tables(left_path,right_path,engine=native,work=tmp_path/'equal')
    assert report['status']=='equivalent' and report['left_rows']==report['right_rows']==2
    assert report['left_only']==report['right_only']==0
    changed=[dict(r) for r in values];changed[1]['writer_commit']='changed-non-key-field'
    changed_path=source(right,changed)
    with pytest.raises(EquivalenceMismatch) as error:
        compare_tables(left_path,changed_path,engine=native,work=tmp_path/'changed')
    assert error.value.report['left_only']==error.value.report['right_only']==1
    assert error.value.report['status']=='rejected'
    job=json.loads((tmp_path/'changed/job.json').read_text())
    assert len(job['inputs'])==2 and all('EXCEPT' in q['sql'] for q in job['queries'] if q['name'].endswith('_only'))
    assert not (tmp_path/'changed/equivalent.json').exists()


def test_native_comparison_row_counts_prevent_distinct_only_false_equivalence(tmp_path):
    from congress_api.lake.capture_backfill_proof import compare_tables,EquivalenceMismatch
    from test_capture_backfill_guard import rows,source
    values=rows();left=tmp_path/'left';left.mkdir();right=tmp_path/'right';right.mkdir()
    with pytest.raises(EquivalenceMismatch) as error:
        compare_tables(source(left,values),source(right,values+[values[0]]),
            engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),work=tmp_path/'compare')
    assert error.value.report['left_only']==error.value.report['right_only']==0
    assert (error.value.report['left_rows'],error.value.report['right_rows'])==(2,3)
