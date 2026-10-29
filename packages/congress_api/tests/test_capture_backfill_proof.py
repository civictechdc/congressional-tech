"""One-shot and whole-receipt batch rebuilding must preserve every public fact."""
import json
import os
from pathlib import Path

import pytest
from docspec_client.client import NativeDatasets


def metrics(key,cost,**changes):
    return dict(key=key,source_rows=1,uncompressed_bytes=cost,list_items=cost,
        expected_captures=1,max_line_bytes=1,max_line_items=1,**changes)


def sample_sources():
    keys=[f'receipts/house/pages/2026-10-28/{i:04d}.jsonl.gz' for i in range(250)]
    files=[dict(key=key,path='/original/'+str(i)+'.gz',qualification='/authority/'+str(i)+'.json')
           for i,key in enumerate(keys)]
    counts=[metrics(key,i+1) for i,key in enumerate(keys)]
    # Family line extremes are mandatory; aggregate receipt weight is not.
    files[247]['key']=counts[247]['key']='receipts/senate/pages/undated/assemble.gz'
    files[248]['key']=counts[248]['key']='receipts/youtube/metadata/undated/assemble.gz'
    for i in (246,247,248):counts[i]['max_line_bytes']=counts[i]['uncompressed_bytes']
    counts[249]['uncompressed_bytes']=10000
    return files,counts


def test_equivalence_sample_includes_family_lines_required_shapes_and_cheapest():
    from congress_api.lake.capture_backfill_proof import select_sample
    files,counts=sample_sources();required=[files[240]['key']]
    selected=select_sample(files,counts,byte_target=100,item_target=100,required_keys=required,
                           proof_bytes=30000)
    expected={files[i]['key'] for i in list(range(196))+[240,246,247,248]}
    assert len(selected['files'])==200
    assert set(selected['mandatory_keys'])=={files[i]['key'] for i in (240,246,247,248)}
    assert {row['key'] for row in selected['files']}==expected
    assert selected['counts']==sorted([r for r in counts if r['key'] in expected],key=lambda r:r['key'])
    assert selected['logical_bytes']==sum(r['uncompressed_bytes'] for r in selected['counts'])
    assert selected['proof_bytes']==30000
    assert selected['family_largest_lines']['house']['key']==files[246]['key']
    assert selected['required_keys']==required
    assert files[249]['key'] not in expected


def test_equivalence_sample_is_order_independent_and_cap_keeps_receipts_whole():
    from congress_api.lake.capture_backfill_proof import select_sample
    files,counts=sample_sources()
    options=dict(byte_target=10,item_target=10,proof_bytes=750,sample_size=200)
    one=select_sample(files,counts,**options)
    assert one==select_sample(files[::-1],counts[::-1],**options)
    assert one['logical_bytes']<=750 and len(one['files'])<200
    assert one['logical_bytes']==sum(r['uncompressed_bytes'] for r in one['counts'])
    assert set(one['mandatory_keys'])=={files[i]['key'] for i in (246,247,248)}


@pytest.mark.parametrize('size',[0,False,1])
def test_invalid_or_too_small_sample_refuses_without_losing_required_extremes(size):
    from congress_api.lake.capture_backfill_proof import select_sample
    files,counts=sample_sources()
    with pytest.raises(ValueError):select_sample(files,counts,byte_target=10,item_target=10,sample_size=size)


@pytest.mark.parametrize('change',['missing_counts','counter','prepared','unqualified',
    'missing_required','duplicate_required','cap','bad_cap'])
def test_sample_refuses_invalid_sources_requirements_or_mandatory_overflow(change):
    from congress_api.lake.capture_backfill_proof import select_sample
    files,counts=sample_sources();options={}
    if change=='missing_counts':counts=[]
    elif change=='counter':files[0].pop('path')
    elif change=='prepared':files[0]['prepared_stage']='/accepted'
    elif change=='unqualified':files[0].pop('qualification')
    elif change=='missing_required':options['required_keys']=['receipts/missing.gz']
    elif change=='duplicate_required':options['required_keys']=[files[0]['key']]*2
    elif change=='cap':options['proof_bytes']=743
    elif change=='bad_cap':options['proof_bytes']=True
    with pytest.raises(ValueError):select_sample(files,counts,byte_target=10,item_target=10,**options)


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
    assert len(job['inputs'])==2
    assert all('EXCEPT' not in q['sql'] for q in job['queries'])
    assert any('GROUP BY' in step['sql'] for step in job['steps'])
    from test_capture_comparison_hashkeys import explain_step
    physical=explain_step(job,'compared_values',native=native,work=tmp_path/'explain')
    assert 'AggregateExec:' in physical
    assert 'HashJoinExec:' not in physical and 'WindowAggExec:' not in physical
    assert not (tmp_path/'changed/equivalent.json').exists()


def test_native_comparison_row_counts_prevent_distinct_only_false_equivalence(tmp_path):
    from congress_api.lake.capture_backfill_proof import compare_tables,EquivalenceMismatch
    from test_capture_backfill_guard import rows,source
    values=rows();left=tmp_path/'left';left.mkdir();right=tmp_path/'right';right.mkdir()
    with pytest.raises(EquivalenceMismatch) as error:
        compare_tables(source(left,values),source(right,values+[values[0]]),
            engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),work=tmp_path/'compare')
    assert (error.value.report['left_only'],error.value.report['right_only'])==(0,1)
    assert (error.value.report['left_rows'],error.value.report['right_rows'])==(2,3)


def test_native_multiset_comparison_detects_duplicate_distribution_and_differing_row(tmp_path):
    """Equal totals and equal distinct values cannot hide unequal multiplicities."""
    from congress_api.lake.capture_backfill_proof import compare_tables,EquivalenceMismatch
    from test_capture_backfill_guard import rows,source
    a,b=rows();left=tmp_path/'left';left.mkdir();right=tmp_path/'right';right.mkdir()
    native=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    with pytest.raises(EquivalenceMismatch) as error:
        compare_tables(source(left,[a,a,b]),source(right,[a,b,b]),engine=native,work=tmp_path/'duplicates')
    assert (error.value.report['left_rows'],error.value.report['right_rows'])==(3,3)
    assert (error.value.report['left_only'],error.value.report['right_only'])==(1,1)
    changed=dict(b,writer_commit='different')
    with pytest.raises(EquivalenceMismatch) as error:
        compare_tables(source(left,[a,a,b]),source(right,[a,changed,changed]),engine=native,work=tmp_path/'different')
    assert (error.value.report['left_only'],error.value.report['right_only'])==(2,2)
    assert compare_tables(source(left,[]),source(right,[]),engine=native,work=tmp_path/'empty')['status']=='equivalent'


def test_three_original_gzip_receipts_rebuild_equally_in_fresh_native_generations(tmp_path):
    from congress_api.lake.capture_backfill_proof import prove_equivalence
    from test_captures_ingest import body,files as receipt_files
    keys=['receipts/documents/2026-10-28/'+name+'.gz' for name in ('a','b','c')]
    records=[dict(run_id='proof',record=dict(url='https://example.org/a',http_status=200),captures=[body()]),
        dict(run_id='proof',record=[dict(url='https://example.org/b',status_code=404),
            dict(url='https://example.org/b2',status_code=404)],captures=[]),
        dict(run_id='proof',record=dict(url='https://example.org/c',http_status=503),captures=[body()])]
    files=[]
    for index,(key,record) in enumerate(zip(keys,records)):
        files+=receipt_files(tmp_path/'original'/str(index),[record],key)
    counts=[]
    for key,record,items in zip(keys,records,[1,2,1]):
        size=len(json.dumps(record).encode())
        counts.append(dict(key=key,source_rows=1,uncompressed_bytes=size,list_items=items,
            expected_captures=items,max_line_bytes=size,max_line_items=items))
    report=prove_equivalence(files,counts,
        engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
        engine_config=os.environ['DOCSPEC_JOB_CONFIG'],work=tmp_path/'proof',
        table=dict(namespace=['archive'],name='captures'),catalog_root=tmp_path/'catalog',
        location=tmp_path/'tables/captures',byte_target=1,item_target=1,
        required_keys=keys,proof_bytes=1<<20)
    assert report['status']=='equivalent' and report['qualified_for_downstream'] is False
    assert len(report['generations']['one_shot']['batches'])==1
    assert len(report['generations']['batched']['batches'])==3
    assert report['comparison']['left_rows']==report['comparison']['right_rows']==4
    assert report['comparison']['left_only']==report['comparison']['right_only']==0
    pins=[value['pin'] for value in report['generations'].values()]
    assert pins[0]['table_uuid']!=pins[1]['table_uuid']
    compare=json.loads((tmp_path/'proof/comparison/job.json').read_text())
    assert len(compare['inputs'])==2 and all(v['kind']=='native_table' for v in compare['inputs'])
    identity=report['identity']
    assert identity['mapping_digest'] and identity['proof_definition'] and len(identity['sources'])==3
    assert identity['engine']['binary_sha256'] and identity['sources'][0]['qualification']['sha256']
    assert json.loads((tmp_path/'proof/proof.json').read_text())['status']=='equivalent'
    from congress_api.lake.capture_backfill_proof import resume_comparison
    original=(tmp_path/'proof/proof.json').read_bytes()
    resumed=resume_comparison(tmp_path/'proof/proof.json',
        engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
        engine_config=os.environ['DOCSPEC_JOB_CONFIG'],work=tmp_path/'resumed')
    assert resumed['status']=='equivalent' and resumed['generations']==json.loads(original)['generations']
    assert resumed['identity']==report['identity']
    assert (tmp_path/'proof/proof.json').read_bytes()==original
    assert not (tmp_path/'resumed/one_shot').exists() and not (tmp_path/'resumed/batched').exists()
    bad=dict(report,identity=dict(report['identity'],mapping_digest='wrong'))
    bad_path=tmp_path/'bad.json';bad_path.write_text(json.dumps(bad))
    with pytest.raises(ValueError,match='identity'):
        resume_comparison(bad_path,engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
            engine_config=os.environ['DOCSPEC_JOB_CONFIG'],work=tmp_path/'refused')
    assert not (tmp_path/'refused').exists()


def test_proof_identity_binds_selected_raw_authorities_without_counter(tmp_path):
    from congress_api.lake.capture_backfill_proof import proof_identity
    from test_captures_ingest import files as receipt_files
    files=receipt_files(tmp_path/'raw',[dict(record={})])
    identity=proof_identity(engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
        engine_config=os.environ['DOCSPEC_JOB_CONFIG'],files=files)
    assert len(identity['sources'])==1
    assert identity['sources'][0]['path']==files[0]['path']
    assert identity['sources'][0]['qualification']['path']==files[0]['qualification']


@pytest.mark.parametrize('kind',['relative','traversal','duplicate_alias'])
def test_proof_external_qualification_keys_preserve_path_guards(tmp_path,kind):
    from congress_api.lake.capture_backfill_proof import proof_identity
    from test_captures_ingest import files as receipt_files
    files=receipt_files(tmp_path/'raw',[dict(record={})])
    path=files[0]['path'];authority=files[0]['qualification']
    if kind=='relative':bindings={'relative/receipt.gz':authority}
    elif kind=='traversal':bindings={str(tmp_path/'raw'/'..'/'raw'/'receipt.gz'):authority}
    else:bindings={path:authority,str(Path(path).parent)+'/./'+Path(path).name:authority}
    with pytest.raises(ValueError,match='absolute|Duplicate'):
        proof_identity(engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
            engine_config=os.environ['DOCSPEC_JOB_CONFIG'],files=files,source_qualifications=bindings)
