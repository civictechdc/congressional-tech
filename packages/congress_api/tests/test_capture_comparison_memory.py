"""Oracle comparison retains evidence while releasing consumed native tables."""
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.lake.capture_comparison import compare_old
from docspec_client.client import NativeDatasets
from docspec_client.models import DocSpecFailure


def limited_engine(tmp_path):
    config = json.loads(Path(os.environ['DOCSPEC_JOB_CONFIG']).read_text())
    limits = json.loads(Path(config['limits']).read_text())
    limits.update(memory_bytes=192 << 20, scratch_bytes=256 << 20,
                  batch_rows=32, max_batch_bytes=1 << 20, max_metadata_bytes=1 << 20)
    limit_path = tmp_path/'limits.json'
    limit_path.write_text(json.dumps(limits))
    config.update(limits=str(limit_path), workspace=str(tmp_path/'workspace'), timeout_seconds=120)
    config_path = tmp_path/'runtime.json'
    config_path.write_text(json.dumps(config))
    return NativeDatasets.from_config(config_path)


def test_comparison_completes_with_bounded_native_memory(tmp_path):
    engine=limited_engine(tmp_path)
    count = 2048
    rows = [dict(receipt_key='receipts/documents/2026-10-20/large-contexts.gz',
                 receipt_line=index + 1, pointer_json='["body"]',
                 context_url='https://example.org/' + str(index) + '/' + 'x'*8192,
                 bytes=100, stored_bytes=42, media_type='application/pdf',
                 fidelity='exact-bytes', http_status=200,
                 retrieved_at='2026-10-20T00:00:00Z') for index in range(count)]
    old = tmp_path/'old.parquet'
    new = tmp_path/'new.parquet'
    pq.write_table(pa.Table.from_pylist([
        dict(row, sha256='a'*64, reference_kind='capture') for row in rows]), old,
        row_group_size=64)
    pq.write_table(pa.Table.from_pylist([
        dict(row, sha256=bytes.fromhex('a'*64), capture_index=0,
             reference_kind='capture') for row in rows]), new, row_group_size=64)
    result = compare_old(new, old, engine=engine,
                         work=tmp_path/'comparison')
    assert result['old_rows'] == result['new_rows'] == result['matched'] == count
    assert result['old_only'] == result['new_only'] == result['secondary_duplicates'] == 0
    assert result['unexplained'] == result['expected_changes'] == 0
    assert result['owner_gate'] is False
    for name in ('old-only', 'new-only', 'expected-new-only',
                 'unexplained-new-only', 'changed-fields'):
        assert pq.read_metadata(tmp_path/'comparison'/(name + '.parquet')).num_rows == 0


@pytest.mark.parametrize('count',[2048,pytest.param(8192,marks=pytest.mark.xfail(
    strict=True,raises=DocSpecFailure,
    reason='docspec-rs dec-eog7: retained tables exhaust sort headroom; remove after native fix'))])
def test_full_comparison_preserves_file_references_and_restorations_at_four_times_rows(tmp_path,count):
    """The signed pivot must preserve counts and old evidence under one budget."""
    engine=limited_engine(tmp_path)
    key='receipts/documents/2026-10-20/scaled.gz'
    sha='a'*64
    body_key='bodies/sha256/aa/'+sha+'.gz'
    old_rows=[dict(receipt_key=key,receipt_line=i+1,sha256=sha,pointer_json='["body"]',
        reference_kind='capture',context_url='https://fixture.test/'+str(i)+'/'+'x'*8192,
        bytes=100,stored_bytes=42,body_key=body_key,media_type='application/pdf',
        fidelity='exact-bytes',http_status=None if i==0 else 200,
        retrieved_at='2026-10-20T00:00:00Z',original_note='preserved') for i in range(count)]
    old_rows += [dict(old_rows[0],reference_kind='file',pointer_json='["old-file"]'),
        dict(old_rows[0],reference_kind='retained-file',pointer_json='["contradiction"]',
             stored_bytes=43,original_note='must survive unchanged'),
        dict(old_rows[0],receipt_line=count+1,sha256=None,pointer_json='[]',reference_kind='metadata',
             context_url=None,body_key=None,bytes=None,stored_bytes=None,media_type=None,
             fidelity=None,http_status=None)]
    new_rows=[]
    for row in old_rows[:count]:
        new={k:v for k,v in row.items() if k not in {'body_key','original_note'}}
        new.update(sha256=bytes.fromhex(sha),capture_index=0,http_status=200,
            stored_suffix='.gz',record_is_list=False,source_record_count=0,source_record_index=None)
        new_rows.append(new)
    for index in (0,1):
        new_rows.append(dict(new_rows[0],receipt_line=count+1,sha256=None,pointer_json=None,
            reference_kind='line',context_url=None,bytes=None,stored_bytes=None,media_type=None,
            fidelity=None,http_status=None,capture_index=index,record_is_list=True,
            source_record_count=2,source_record_index=index))
    new_rows.append(dict(new_rows[1],receipt_line=count+2,sha256=bytes.fromhex('b'*64)))
    integers={'receipt_line','capture_index','bytes','stored_bytes','http_status',
              'source_record_count','source_record_index'}
    def write(path,rows,binary=False):
        fields=[pa.field(name,pa.binary(32) if name=='sha256' and binary else
            pa.int64() if name in integers else pa.bool_() if name=='record_is_list' else pa.string())
            for name in rows[0]]
        pq.write_table(pa.Table.from_pylist(rows,schema=pa.schema(fields)),path,row_group_size=64)
    old=tmp_path/'old.parquet';new=tmp_path/'new.parquet'
    write(old,old_rows);write(new,new_rows,True)
    try:
        result=compare_old(new,old,engine=engine,work=tmp_path/'comparison')
    except DocSpecFailure as error:
        # Only the measured native reservation failure is expected. Invalid SQL,
        # input refusals, or a different resource failure must remain red.
        assert 'Not enough memory to continue external sort' in str(error)
        assert any(name in str(error) for name in ('for ExternalSorter[','for ExternalSorterMerge['))
        assert 'Resources exhausted:' in str(error) and 'remain available for the total pool' in str(error)
        raise
    expected=dict(old_rows=count+3,new_rows=count+3,secondary_duplicates=1,old_only=1,
        new_only=2,expected_new_only=1,unexplained_new_only=1,unexplained=0,
        expected_changes=1,matched=count+1,owner_gate=True)
    assert {name:result[name] for name in expected}==expected
    [kept]=pq.read_table(tmp_path/'comparison/old-only.parquet').to_pylist()
    assert kept['original_note']=='must survive unchanged' and kept['stored_bytes']==43
    [restored]=pq.read_table(tmp_path/'comparison/expected-new-only.parquet').to_pylist()
    assert restored['reason']=='source_list_item_restored'
    assert (restored['receipt_line'],restored['source_record_index'])==(count+1,1)

