"""Receipt shape and storage contradictions refuse before public acceptance."""
import pyarrow.parquet as pq
import pytest
from test_captures_ingest import ingest, body


@pytest.mark.parametrize('field,left,right',[
    ('stored_bytes',12,13),('stored_md5','a'*32,'b'*32),('stored_suffix','','.gz'),
])
def test_primary_and_matching_secondary_storage_disagreement_refuses(tmp_path,field,left,right):
    row=dict(source_file='run',record={},captures=[body(**{field:left})],
        file_references=[body(**{field:right})])
    with pytest.raises(ValueError,match='storage conflict'):
        ingest(tmp_path,[row])
    assert not (tmp_path/'stage/captures.parquet').exists()
    assert not (tmp_path/'stage/ingested-receipts.json').exists()


@pytest.mark.parametrize('name',['captures','file_references'])
def test_present_object_body_reference_list_never_becomes_a_bodiless_success(tmp_path,name):
    row=dict(source_file='run',record={},**{name:body()})
    with pytest.raises(ValueError,match='reference list shape'):
        ingest(tmp_path,[row])
    assert not (tmp_path/'stage/captures.parquet').exists()
    assert not (tmp_path/'stage/ingested-receipts.json').exists()


@pytest.mark.parametrize('value',[None,[]])
def test_null_and_empty_reference_lists_keep_the_bodiless_row(tmp_path,value):
    work=ingest(tmp_path,[dict(source_file='run',record={},captures=value,file_references=value)],
        key='receipts/documents/2026-10-20/assemble-empty-references.jsonl.gz')
    [row]=pq.read_table(work/'captures.parquet').to_pylist()
    assert row['capture_index']==0 and row['sha256'] is None


@pytest.mark.parametrize('component',['not_archive_members','archive_members_suffix','a"archive_members"b'])
def test_literal_pointer_names_do_not_borrow_member_paths_or_mark_containers(tmp_path,component):
    second=dict(body(),sha256='b'*64,body_key='bodies/sha256/bb/'+'b'*64+'.gz',
        original_path='never-a-member.pdf',pointer=[component,0,'content','body'])
    work=ingest(tmp_path,[dict(source_file='run',record={'url':'https://example.org/archive','http_status':200},
        captures=[body(pointer=['content','body']),second])])
    rows=pq.read_table(work/'captures.parquet').to_pylist()
    assert [row['member_path'] for row in rows]==[None,None]
    assert [row['expansion'] for row in rows]==[None,None]
