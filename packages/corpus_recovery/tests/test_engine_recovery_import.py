"""B7 target: native reconciliation and thin, create-only recovery imports."""
from hashlib import sha256
import gzip
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from docspec_client.client import NativeDatasets
from corpus_recovery.reconcile import reconcile, import_retained
from congress_api.retention.body_store import BodyStore, LocalAdapter
from congress_api.retention.receipt_writer import ReceiptWriter

STAMP = '2026-10-27T12:00:00Z'
WRITER = dict(job='recovery', commit='a'*40, lockfile_digest='b'*64)


def test_import_uses_common_writer_and_keeps_original_time(tmp_path):
    data = b'<html><title>Recovered source</title></html>'
    body = tmp_path/'retained.html'; body.write_bytes(data)
    store = BodyStore(LocalAdapter(tmp_path/'raw'))
    writer = ReceiptWriter(store, identity=WRITER, run_id='recovery-test',
                           write_date='2026-10-27', archive_limits=None)
    source = dict(original_url='https://docs.house.gov/missing.html',
        recovered_url='https://archive.example/copy.html',body_path=str(body),
        body_sha256=sha256(data).hexdigest(),retrieved_at='2019-10-01T12:00:00Z',
        media_type='text/html',category='recovered_document',match_basis='verified_archive_capture',
        imported_at=STAMP,evidence_sha256='c'*64)
    key,line = import_retained(writer,source)
    assert key.startswith('receipts/documents/2026-10-27/recovery-test-')
    assert line['retrieved_at']=='2019-10-01T12:00:00Z'
    assert line['mode']=='retained_import' and line['publisher_requested'] is False
    assert line['writer']==WRITER and line['http_status']==200
    assert line['recovery_evidence']['original_url']==source['original_url']
    assert line['recovery_evidence']['acquisition']['prior_access_category']=='recovered_document'
    assert line['recovery_evidence']['acquisition']['body_path']=='retained.html'
    assert '/Users/' not in json.dumps(line)
    assert gzip.decompress((tmp_path/'raw'/key).read_bytes()).endswith(b'\n')


@pytest.mark.parametrize('field,value', [('retrieved_at',None),('category',None),
                                       ('body_sha256','f'*64)])
def test_invalid_recovery_refused_before_any_raw_write(tmp_path,field,value):
    body=tmp_path/'body';body.write_bytes(b'content')
    source=dict(original_url='https://docs.house.gov/missing',recovered_url='https://archive.example/copy',
        body_path=str(body),body_sha256=sha256(b'content').hexdigest(),retrieved_at=STAMP,
        media_type='text/plain',category='recovered_document',match_basis='verified_archive_capture',
        imported_at=STAMP,evidence_sha256='c'*64)
    source[field]=value
    class Writer:
        def write(self,*args,**kwargs):
            raise AssertionError('Invalid source reached receipt writer')
    with pytest.raises(ValueError):
        import_retained(Writer(),source)


def test_native_reconciliation_preserves_both_sides_and_missing_imports(tmp_path):
    engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    one,two,three='1'*64,'2'*64,'3'*64
    accepted=tmp_path/'accepted.json'
    accepted.write_text(json.dumps(dict(version=1,recoveries=[
        dict(original_url='https://docs.house.gov/a',recovered_url='https://archive.example/a',
             body_key=f'bodies/sha256/11/{one}.gz',kind='pdf',recovery_status='recovered',recovery_basis='verified_archive_capture'),
        dict(original_url='https://docs.house.gov/b',recovered_url='https://archive.example/b',
             body_key=f'bodies/sha256/22/{two}.gz',kind='pdf',recovery_status='recovered',recovery_basis='verified_archive_capture') ])))
    captures=tmp_path/'captures.parquet'
    rows=[dict(sha256=one,mode='retained_import',original_url='https://docs.house.gov/a',
        recovered_url='https://archive.example/a',match_basis='verified_archive_capture',
        recovery_category='requested_content_in_official_hearing',url='https://archive.example/a',
        retrieved_at=STAMP,receipt_key='receipts/a',receipt_line=1,capture_index=0,bytes=12,media_type='application/pdf'),
        dict(sha256=two,mode='fetch',original_url=None,recovered_url=None,match_basis=None,
        recovery_category=None,url='https://archive.example/b',retrieved_at='2019-01-01T00:00:00Z',
        receipt_key='receipts/b',receipt_line=1,capture_index=0,bytes=20,media_type='application/pdf'),
        dict(sha256=three,mode='retained_import',original_url='https://docs.house.gov/receipt-only',
        recovered_url='https://archive.example/c',match_basis='verified_archive_capture',
        recovery_category='recovered_document',url='https://archive.example/c',retrieved_at=STAMP,
        receipt_key='receipts/c',receipt_line=1,capture_index=0,bytes=30,media_type='application/pdf')]
    pq.write_table(pa.Table.from_pylist(rows),captures)
    registry=tmp_path/'kinds.json';registry.write_text(json.dumps([
        dict(category='requested_content_in_official_hearing',match_basis=None,kind='requested_content_in_official_hearing'),
        dict(category='recovered_document',match_basis=None,kind='recovered_document'),
        dict(category=None,match_basis='verified_archive_capture',kind='recovered_document')]))
    result=reconcile(accepted,captures,registry,output=tmp_path/'staged',engine=engine,
                     decided_at=STAMP,decided_by='accepted-mapping-reconciliation')
    assert result['counts']==dict(accepted=2,matched=1,accepted_only=1,receipt_only=1,
                                 basis_differences=0,url_differences=0)
    records=[json.loads(line) for line in (tmp_path/'staged'/result['provenance']).read_text().splitlines()]
    assert len(records)==2 and records[0]['kind']=='requested_content_in_official_hearing'
    assert records[1]['kind']=='recovered_document'
    missing=pq.read_table(tmp_path/'staged'/'missing-imports.parquet').to_pylist()
    assert len(missing)==1 and missing[0]['original_url']=='https://docs.house.gov/b'
    assert missing[0]['retrieved_at']=='2019-01-01T00:00:00Z'
