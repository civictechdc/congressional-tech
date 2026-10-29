"""Only small receipt facts qualify expected old-index transformations."""
import pyarrow.parquet as pq
from test_captures_ingest import body,ingest


def test_private_comparison_proof_is_derived_once_and_never_appended(tmp_path):
    stage=ingest(tmp_path,[
        dict(record=dict(url='https://example.org/final',http_status=404),captures=[
            body(pointer=['prior_attempts',0,'body'],http_status=403)]),
        dict(record=dict(family='committee-reports',title='Retained metadata')),
        dict(family='documents',record=dict(url='https://example.org/other'),captures=[
            body(context_url='https://example.org/explicit',status_code=200,stored_bytes=10,family='specific')]),
    ],key='receipts/documents/undated/assemble-witness.jsonl.gz')
    a,b,c=pq.read_table(stage/'capture-evidence.parquet').to_pylist()
    assert (a['source_context_from_final'],a['source_entry_status'],a['source_final_status'])==(True,403,404)
    assert a['source_creating_size_absent'] is True and a['source_family_basis']=='receipt'
    assert b['source_retained_record'] is True and b['source_family_basis']=='record'
    assert c['source_context_from_final'] is False and c['source_creating_size_absent'] is False
    assert c['source_entry_status']==200 and c['source_final_status'] is None and c['source_family_basis']=='entry'
    public=pq.read_schema(stage/'captures.parquet').names
    assert not any(name.startswith('source_') for name in public)
    assert len(public)==34
