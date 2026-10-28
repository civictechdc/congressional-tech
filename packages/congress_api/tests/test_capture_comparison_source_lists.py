"""Only proved source list items explain owner-authorized extra index rows."""
import os
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from docspec_client.client import NativeDatasets
from congress_api.lake.capture_comparison import compare_old

KEY='receipts/documents/2026-10-20/list.gz'


def compare(tmp_path,changes=None,*,proof=True,clone=False,old_line=1,extra_old=False):
    old=tmp_path/'old.parquet';new=tmp_path/'new.parquet'
    common=dict(receipt_key=KEY,receipt_line=1,pointer_json=None,context_url=None,bytes=None,
        stored_bytes=None,media_type=None,fidelity=None,http_status=None,retrieved_at=None)
    old_schema=pa.schema([(name,pa.int64() if name in {'receipt_line','bytes','stored_bytes','http_status'} else pa.string())
        for name in [*common,'sha256','reference_kind']])
    rows=[dict(common,receipt_line=old_line,sha256=None,reference_kind='metadata',pointer_json='[]')]
    if extra_old:rows.append(dict(rows[0],receipt_line=9,reference_kind='capture',sha256='a'*64,pointer_json='["body"]'))
    pq.write_table(pa.Table.from_pylist(rows,schema=old_schema),old)
    rows=[dict(common,sha256=None,reference_kind='line',capture_index=index,
        record_is_list=True,source_record_count=3,source_record_index=index) for index in range(3)]
    rows[1].update(changes or {})
    if clone:rows.append(dict(rows[2],capture_index=99))
    new_schema=pa.schema([(name,pa.binary(32) if name=='sha256' else pa.bool_() if name=='record_is_list' else
        pa.int64() if name in {'receipt_line','bytes','stored_bytes','http_status','capture_index','source_record_count','source_record_index'} else pa.string())
        for name in rows[0]])
    if not proof:new_schema=pa.schema([f for f in new_schema if f.name not in {'record_is_list','source_record_count','source_record_index'}])
    pq.write_table(pa.Table.from_pylist(rows,schema=new_schema),new)
    report=compare_old(new,old,engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),work=tmp_path/'comparison')
    return report,tmp_path/'comparison'


def test_proved_source_list_expansion_is_counted_and_reported_without_owner_gate(tmp_path):
    result,work=compare(tmp_path)
    assert result['new_only']==result['expected_new_only']==2
    assert result['unexplained_new_only']==result['old_only']==result['unexplained']==0
    assert result['matched']==1 and result['owner_gate'] is False
    assert pq.ParquetFile(work/'new-only.parquet').metadata.num_rows==2
    rows=pq.read_table(work/'expected-new-only.parquet').to_pylist()
    assert [r['source_record_index'] for r in rows]==[1,2]
    assert {r['reason'] for r in rows}=={'source_list_item_restored'}
    assert pq.ParquetFile(work/'unexplained-new-only.parquet').metadata.num_rows==0
    assert 'source_list_items' in result['rules']


@pytest.mark.parametrize('changes',[
    dict(record_is_list=False),dict(source_record_count=1),dict(source_record_index=-1),
    dict(source_record_index=3),dict(source_record_index=None),dict(record_is_list=None),
    dict(sha256=bytes.fromhex('a'*64)),dict(pointer_json='[1]'),dict(reference_kind='capture'),
])
def test_arbitrary_new_only_rows_are_not_blessed_by_neighbor_list_proof(tmp_path,changes):
    result,work=compare(tmp_path,changes)
    assert result['new_only']==2 and result['expected_new_only']==1
    assert result['unexplained_new_only']==1 and result['owner_gate'] is True
    assert pq.ParquetFile(work/'new-only.parquet').metadata.num_rows==2
    [row]=pq.read_table(work/'unexplained-new-only.parquet').to_pylist()
    assert row['capture_index']==1 and row['reason']=='unexplained_new_row'


@pytest.mark.parametrize('kwargs,expected,unexplained',[
    (dict(proof=False),0,2),(dict(old_line=2),0,3),(dict(clone=True),1,2),
    (dict(changes=dict(source_record_index=0)),1,1),
])
def test_missing_source_proof_or_duplicate_item_occurrences_remain_gates(tmp_path,kwargs,expected,unexplained):
    result,work=compare(tmp_path,**kwargs)
    assert result['expected_new_only']==expected and result['unexplained_new_only']==unexplained
    assert result['owner_gate'] is True
    assert pq.ParquetFile(work/'unexplained-new-only.parquet').metadata.num_rows==unexplained


def test_expected_new_list_items_do_not_dismiss_old_only_facts(tmp_path):
    result,work=compare(tmp_path,extra_old=True)
    assert result['expected_new_only']==2 and result['old_only']==1 and result['owner_gate'] is True
    [row]=pq.read_table(work/'old-only.parquet').to_pylist()
    assert row['receipt_line']==9 and row['sha256']=='a'*64 and row['reference_kind']=='capture'


@pytest.mark.parametrize('mixed',[False,True])
def test_raw_source_list_proof_comes_from_the_actual_ingest_not_a_guessed_index(tmp_path,mixed):
    from test_captures_ingest import ingest,body
    records=[dict(url='https://fixture.test/first'),dict(url='https://fixture.test/bodiless',status_code=404)]
    captures=[]
    if mixed:
        captures=[body(pointer=[0,'content','body']),
            dict(body(pointer=[0,'another','body']),sha256='b'*64,
                 body_key='bodies/sha256/bb/'+'b'*64+'.gz')]
    else:records.append(dict(url='https://fixture.test/third',status_code=503))
    staged=ingest(tmp_path/'source',[dict(source_file='owner-list',record=records,captures=captures)])
    evidence=staged/'capture-evidence.parquet'
    derived=pq.read_table(evidence).to_pylist()
    assert all(r['record_is_list'] is True and r['source_record_count']==len(records) for r in derived)
    originals=derived[:2] if mixed else derived[:1]
    old_rows=[]
    for row in originals:
        old={name:row[name] for name in ('receipt_key','receipt_line','context_url','bytes','stored_bytes',
            'media_type','fidelity','http_status','family')}
        old.update(source_file=row['run_id'],sha256=row['sha256'].hex() if row['sha256'] is not None else None,
            reference_kind='capture' if mixed else 'metadata',pointer_json=row['pointer_json'] if mixed else '[]',
            body_key=row['body_key'],retrieved_at=row['retrieved_at'].isoformat() if row['retrieved_at'] else None)
        old_rows.append(old)
    schema=pa.schema([(name,pa.int64() if name in {'receipt_line','bytes','stored_bytes','http_status'} else pa.string())
        for name in old_rows[0]])
    old=tmp_path/'old.parquet';pq.write_table(pa.Table.from_pylist(old_rows,schema=schema),old)
    result=compare_old(evidence,old,engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
        work=tmp_path/'comparison')
    assert result['new_only']==result['expected_new_only']==(1 if mixed else 2)
    assert result['old_only']==result['unexplained_new_only']==result['unexplained']==0
    assert result['owner_gate'] is False
    restored=pq.read_table(tmp_path/'comparison/expected-new-only.parquet').to_pylist()
    assert [r['source_record_index'] for r in restored]==([1] if mixed else [1,2])
    assert all(r['reference_kind']=='line' and r['body_sha'] is None and r['pointer'] is None for r in restored)
