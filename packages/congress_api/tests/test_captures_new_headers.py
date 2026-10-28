"""Actual writer download headers survive qualified D1 source selection."""
from dataclasses import replace
import os

import pyarrow.parquet as pq
import pytest
from docspec_client.client import NativeDatasets

from capture_qualification_helpers import write_qualified_bytes,created_qualifications
from test_captures_ingest import body,ingest
from test_captures_root_objects import minimal_counter
from test_receipt_writer_contract import attempt,WRITER


@pytest.mark.parametrize('counter',[False,True])
def test_actual_receipt_writer_download_header_survives_d1(tmp_path,counter):
    from congress_api.models.raw_fetch import FetchResult
    from congress_api.retention.body_store import BodyStore,LocalAdapter
    from congress_api.retention.receipt_writer import ReceiptWriter
    from congress_api.lake.captures import stage_captures
    root=tmp_path/'raw';qualifications={}
    class QualifiedAdapter(LocalAdapter):
        def create(self,key,source,**kwargs):
            if key.startswith('receipts/'):
                qualifications[key]=write_qualified_bytes(root/key,source.read())
                return True
            return super().create(key,source,**kwargs)
    writer=ReceiptWriter(BodyStore(QualifiedAdapter(root)),identity=WRITER,run_id='header',
        write_date='2026-10-28',archive_limits=None)
    value='attachment; filename="download-report.pdf"'
    key,line=writer.write(FetchResult(replace(attempt(tmp_path),headers={'content-disposition':value})),
        family='documents')
    assert line['response_headers']['content-disposition']==value and 'record' not in line
    files=[dict(key=key,path=str(root/key),qualification=qualifications[key])]
    options={}
    if counter:
        path=minimal_counter(tmp_path,[(key,line)],False)
        files=[dict(key=key)]
        options=dict(validated_counter=path,source_qualifications=created_qualifications(path))
    stage=stage_captures(files,engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
        work=tmp_path/'stage',**options)
    assert pq.read_table(stage/'captures.parquet')['h_content_disposition'].to_pylist()==[value]


@pytest.mark.parametrize('writer,root_headers,record_headers,expected',[
    (WRITER,{'content-disposition':'root-lower','Content-Disposition':'root-upper'},
        {'content-disposition':'record-lower','Content-Disposition':'record-upper'},'root-lower'),
    (WRITER,{'Content-Disposition':'root-upper'},{'content-disposition':'legacy'},'root-upper'),
    (WRITER,{'content-disposition':{},'Content-Disposition':'root-upper'},
        {'content-disposition':'legacy'},'root-upper'),
    (WRITER,{'content-disposition':None},{'content-disposition':'record-lower',
        'Content-Disposition':'record-upper'},'record-lower'),
    (WRITER,[{'name':'content-disposition','value':'excluded-array'}],
        {'Content-Disposition':'legacy'},'legacy'),
    (WRITER,None,{'Content-Disposition':'legacy'},'legacy'),
    (None,{'content-disposition':'unqualified-root'},None,None),
    ({'job':'capture'}, {'content-disposition':'unqualified-root'},None,None),
    ({'commit':'a'*40}, {'content-disposition':'unqualified-root'},None,None),
    ({'job':'capture','commit':{}},{'content-disposition':'unqualified-root'},
        {'content-disposition':'legacy'},'legacy'),
    (WRITER,{'content-disposition':[]},{'content-disposition':{}},None),
])
def test_writer_qualified_root_header_precedence_and_legacy_fallback(
        tmp_path,writer,root_headers,record_headers,expected):
    source=dict(response_headers=root_headers,writer=writer,
        record=dict(response_headers=record_headers),captures=[body()],
        response_header_items=[dict(name='Content-Disposition',value='excluded-array')],
        prior_attempts=[dict(response_headers={'content-disposition':'excluded-prior'})],
        source_metadata=dict(response_headers={'content-disposition':'excluded-copy'}))
    stage=ingest(tmp_path,[source])
    assert pq.read_table(stage/'captures.parquet')['h_content_disposition'].to_pylist()==[expected]
