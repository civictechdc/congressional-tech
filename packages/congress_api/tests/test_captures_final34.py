"""Final owner exceptions: expected scalar evidence before implementation."""
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from test_captures_ingest import body, ingest
from test_captures_narrow import NARROW_COLUMNS


def test_approved_schema_names_order_and_original_field_ids():
    schema=json.loads((Path(__file__).resolve().parents[3]/'model/lake/captures.schema.json').read_text())
    assert [f['name'] for f in schema['fields']]==NARROW_COLUMNS
    fields={f['name']:f for f in schema['fields']}
    assert {k:fields[k]['id'] for k in ('expansion','sniffed_format','sniff_version','intact','writer_job','writer_commit')}==dict(
        expansion=16,sniffed_format=24,sniff_version=25,intact=26,writer_job=36,writer_commit=37)


def test_entry_readings_and_root_writer_repeat_without_inventing_older_readings(tmp_path):
    source=dict(writer=dict(job='capture',commit='a'*40,lockfile_digest='excluded-'*10000),
        http_status=200,outcome='saved',captures=[
            body(sniffed_format='pdf',sniff_version='v1',intact=False),
            body(sniffed_format='pdf',sniff_version='v1',intact=True),body()])
    stage=ingest(tmp_path,[source])
    table=pq.read_table(stage/'captures.parquet');rows=table.to_pylist()
    assert [(r['sniffed_format'],r['sniff_version'],r['intact']) for r in rows]==[
        ('pdf','v1',False),('pdf','v1',True),(None,None,None)]
    assert {(r['writer_job'],r['writer_commit']) for r in rows}=={('capture','a'*40)}
    assert table.schema.field('intact').type==pa.bool_()


def test_legacy_completeness_boundary_and_explicit_entry_precedence(tmp_path):
    rows=[dict(record=dict(outcome=outcome),captures=[dict(body(),bytes=size,**entry)])
        for outcome,size,entry in [('saved',123,{}),('saved',62<<20,{}),('saved',64<<20,{}),
        ('request_failed',123,{}),('resource_limit',123,{}),('saved',64<<20,dict(complete=True)),
        ('saved',123,dict(complete=False))]]
    stage=ingest(tmp_path,rows+[dict(record={})])
    assert pq.read_table(stage/'captures.parquet')['complete'].to_pylist()==[
        True,True,False,False,False,True,False,True]


@pytest.mark.parametrize('prefix',[[],[0],['0']])
def test_prior_pointer_does_not_borrow_final_complete_or_confirm_cutoff(tmp_path,prefix):
    source=dict(record=[dict(http_status=200,outcome='saved',complete=False)] if prefix else
        dict(http_status=200,outcome='saved',complete=False),captures=[
            dict(body(),bytes=64<<20,pointer=prefix+['prior_attempts',0,'content','body']),
            body(pointer=prefix+['content','body'])])
    stage=ingest(tmp_path,[source]);rows=pq.read_table(stage/'captures.parquet').to_pylist()
    assert [r['complete'] for r in rows]==[False,False]
    assert {r['outcome'] for r in rows}=={'stored'}


@pytest.mark.parametrize('error',['missing',None,{},'failure'])
def test_cutoff_requires_explicit_false_and_respects_generic_error_presence(tmp_path,error):
    record=dict(http_status=200,outcome='saved')
    if error != 'missing':record['error']=error
    stage=ingest(tmp_path,[dict(record=record,captures=[dict(body(),bytes=64<<20,complete=False)]),
        dict(record=dict(http_status=200,outcome='saved'),captures=[dict(body(),bytes=64<<20)]),
        dict(record=dict(http_status=200,outcome='saved'),captures=[dict(body(),bytes=64<<20,complete=False),
            body(complete=True)])])
    rows=pq.read_table(stage/'captures.parquet').to_pylist()
    assert [r['outcome'] for r in rows]==['size_limit' if error in ('missing',None) else 'stored','stored','stored','stored']


def test_expansion_inference_is_local_to_retained_member_attempt_and_context(tmp_path):
    source=dict(record=dict(url='https://example.test/final'),captures=[
        body(attempt=0,context_url='a'),body(attempt=0,context_url='a',member_path='a.pdf'),
        body(attempt=0,context_url='b'),dict(body(attempt=0,context_url='b',member_path='absent.pdf'),sha256=None),
        body(attempt=1,context_url='a'),
        body(attempt=1,context_url='c'),body(attempt=1,context_url='c',member_path='c.pdf'),
        body(attempt=0,context_url='a',expansion='encrypted_member')])
    stage=ingest(tmp_path,[source]);rows=pq.read_table(stage/'captures.parquet').to_pylist()
    assert [r['expansion'] for r in rows]==['expanded',None,None,None,None,'expanded',None,'encrypted_member']
