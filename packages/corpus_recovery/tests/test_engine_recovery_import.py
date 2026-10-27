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


def reconciliation_inputs(tmp_path):
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
        dict(category=None,match_basis='verified_archive_capture',kind='recovered_document',import_category='recovered_document')]))
    return accepted,captures,registry


def test_native_reconciliation_preserves_both_sides_and_missing_imports(tmp_path):
    engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    accepted,captures,registry=reconciliation_inputs(tmp_path)
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


@pytest.mark.parametrize('category', ['unknown-category','ambiguous-category'])
def test_unknown_or_ambiguous_categories_refuse_staging(tmp_path,category):
    accepted,captures,registry=reconciliation_inputs(tmp_path)
    rows=pq.read_table(captures).to_pylist()
    if category=='unknown-category':rows[0]['recovery_category']='unlisted'
    else:rows.append(dict(rows[0],recovery_category='recovered_document'))
    pq.write_table(pa.Table.from_pylist(rows),captures)
    with pytest.raises(ValueError,match='unknown|ambiguous'):
        reconcile(accepted,captures,registry,output=tmp_path/'staged',
            engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
            decided_at=STAMP,decided_by='reconciliation')
    assert not (tmp_path/'staged'/'manifest.json').exists()


@pytest.mark.parametrize('retrieved_at',[None,'not-a-time','2019-01-01'])
def test_missing_original_time_is_reported_without_inventing_it(tmp_path,retrieved_at):
    accepted,captures,registry=reconciliation_inputs(tmp_path)
    rows=pq.read_table(captures).to_pylist();rows[1]['retrieved_at']=retrieved_at
    pq.write_table(pa.Table.from_pylist(rows),captures)
    result=reconcile(accepted,captures,registry,output=tmp_path/'staged',
        engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),decided_at=STAMP,decided_by='reconciliation')
    missing=pq.read_table(tmp_path/'staged'/result['missing_imports']).to_pylist()
    assert missing[0]['retrieved_at'] is None
    assert missing[0]['status']=='source_timestamp_not_established'


def test_legacy_projection_uses_native_capture_rows_and_recovery_fallbacks(tmp_path):
    from corpus_recovery.reconcile import project_legacy
    raw=tmp_path/'counter.parquet'
    first=dict(sha256='1'*64,bytes=12,media_type='text/plain',retrieved_at='2019-01-01T00:00:00Z',context_url='https://archive.example/a')
    second=dict(first,sha256='2'*64,bytes=20)
    rows=[dict(__receipt_key='receipts/legacy/2019-01-01/run.jsonl.gz',__receipt_line=1,
        mode=None,record=dict(url='https://archive.example/a',mode='retained_import',
            recovery_evidence=dict(acquisition=dict(body_path='original-statement.pdf')),
            source_associations=[dict(original_url='https://docs.house.gov/a',basis='verified_archive_capture')]),
        captures=[first,second],file_references=[])]
    pq.write_table(pa.Table.from_pylist(rows),raw)
    output=tmp_path/'projection';output.mkdir()
    projected=project_legacy(raw,output=output,engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']))
    captures=pq.read_table(projected).to_pylist()
    assert [row['sha256'] for row in captures]==['1'*64,'2'*64]
    assert [row['capture_index'] for row in captures]==[0,1]
    assert all(row['original_url']=='https://docs.house.gov/a' for row in captures)
    assert all(row['mode']=='retained_import' and row['match_basis']=='verified_archive_capture' for row in captures)
    assert all(row['recovered_filename']=='original-statement.pdf' for row in captures)


def test_existing_reference_import_uses_key_presence_without_body_reads(tmp_path):
    from congress_api.retention.body_store import WriteResult
    digest='a'*64
    class Adapter:
        def __init__(self):self.calls=[]
        def head(self,key):self.calls.append(('head',key));return dict(size=10,etag='stored')
        def create(self,key,source,**kwargs):
            self.calls.append(('create',key))
            assert key.startswith('receipts/')
            return True
    adapter=Adapter()
    writer=ReceiptWriter(BodyStore(adapter),identity=WRITER,run_id='reference-import',
                         write_date='2026-10-27',archive_limits=None)
    source=dict(original_url='https://docs.house.gov/missing.pdf',recovered_url='https://archive.example/copy.pdf',
        body_sha256=digest,bytes=100,stored_suffix='.gz',retrieved_at='2019-01-01T00:00:00Z',
        media_type='application/pdf',category='recovered_document',match_basis='verified_archive_capture',
        imported_at=STAMP,evidence_sha256='c'*64,retained_reference=True,
        sniffed_format=None,sniff_version=None,intact=None)
    key,line=import_retained(writer,source)
    assert adapter.calls==[('head',f'bodies/sha256/aa/{digest}.gz'),('create',key)]
    assert line['captures'][0]['stored_suffix']=='.gz'
    assert line['captures'][0]['bytes']==100 and line['captures'][0]['sniffed_format'] is None
    assert line['captures'][0]['fidelity']=='retained-file'


def test_missing_existing_reference_fails_without_receipt_or_upload(tmp_path):
    class Adapter:
        def head(self,key):return None
        def create(self,*args,**kwargs):raise AssertionError('Missing reference must not upload')
    writer=ReceiptWriter(BodyStore(Adapter()),identity=WRITER,run_id='missing-reference',
                         write_date='2026-10-27',archive_limits=None)
    source=dict(original_url='https://docs.house.gov/missing',recovered_url='https://archive.example/copy',
        body_sha256='a'*64,bytes=10,stored_suffix='.gz',retrieved_at=STAMP,
        category='recovered_document',match_basis='verified_archive_capture',imported_at=STAMP,
        retained_reference=True)
    with pytest.raises(ValueError,match='Missing retained body reference'):
        import_retained(writer,source)


def test_duplicate_accepted_original_link_refuses_without_losing_a_decision(tmp_path):
    accepted,captures,registry=reconciliation_inputs(tmp_path)
    value=json.loads(accepted.read_text());value['recoveries'].append(dict(value['recoveries'][0],body_key='bodies/sha256/22/'+'2'*64+'.gz'))
    accepted.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='accepted|ambiguous'):
        reconcile(accepted,captures,registry,output=tmp_path/'staged',
            engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),decided_at=STAMP,decided_by='reconciliation')
    assert not (tmp_path/'staged'/'manifest.json').exists()


def test_native_projection_filters_unrelated_fetches_but_keeps_all_recoveries(tmp_path):
    from corpus_recovery.reconcile import project_legacy
    raw=tmp_path/'counter.parquet'
    caps=[dict(sha256=digest*64,bytes=12,media_type='text/plain',retrieved_at=STAMP,context_url='https://archive.example/a') for digest in ('1','2')]
    record=dict(url='https://archive.example/a',mode='retained_import',source_associations=[dict(original_url='https://docs.house.gov/a',basis='verified_archive_capture')])
    rows=[dict(__receipt_key='receipts/legacy/run',__receipt_line=1,record=record,captures=caps,file_references=[]),
          dict(__receipt_key='receipts/fetch/run',__receipt_line=1,record=dict(record,mode='fetch',source_associations=[]),captures=caps,file_references=[])]
    pq.write_table(pa.Table.from_pylist(rows),raw)
    accepted=tmp_path/'accepted.json';accepted.write_text(json.dumps(dict(version=1,recoveries=[dict(body_key='bodies/sha256/11/'+'1'*64+'.gz')])))
    output=tmp_path/'projection';output.mkdir()
    path=project_legacy(raw,output=output,engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),accepted=accepted)
    selected=pq.read_table(path).to_pylist()
    assert len(selected)==3
    assert [row['sha256'] for row in selected if row['mode']=='fetch']==['1'*64]
    assert [row['sha256'] for row in selected if row['mode']=='retained_import']==['1'*64,'2'*64]


def test_explicit_import_category_is_not_replaced_by_display_kind(tmp_path):
    accepted,captures,registry=reconciliation_inputs(tmp_path)
    kinds=json.loads(registry.read_text())
    kinds.append(dict(category='retained-copy',match_basis=None,kind='recovered_document'))
    kinds[-2]['import_category']='retained-copy'
    registry.write_text(json.dumps(kinds))
    result=reconcile(accepted,captures,registry,output=tmp_path/'staged',
        engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),decided_at=STAMP,decided_by='reconciliation')
    missing=pq.read_table(tmp_path/'staged'/result['missing_imports']).to_pylist()
    assert missing[0]['category']=='retained-copy'
    assert missing[0]['category']!='recovered_document'
    assert missing[0]['status']=='ready_for_owner_import'


@pytest.mark.parametrize('import_category',[None,'not-a-registered-category'])
def test_basis_only_kind_cannot_invent_an_import_category(tmp_path,import_category):
    accepted,captures,registry=reconciliation_inputs(tmp_path)
    kinds=json.loads(registry.read_text());kinds[-1]['import_category']=import_category
    assert any(row['category']=='recovered_document' and row['kind']=='recovered_document' for row in kinds)
    registry.write_text(json.dumps(kinds))
    result=reconcile(accepted,captures,registry,output=tmp_path/'staged',
        engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),decided_at=STAMP,decided_by='reconciliation')
    missing=pq.read_table(tmp_path/'staged'/result['missing_imports']).to_pylist()
    assert missing[0]['category'] is None
    assert missing[0]['status']=='recovery_category_not_established'
    assert result['import_counts']==dict(ready=0,unresolved=1)


def test_canonical_registry_explicitly_admits_copy_imports(tmp_path):
    accepted,captures,_=reconciliation_inputs(tmp_path)
    registry=Path(__file__).parents[3]/'model/registries/recovery-kinds.json'
    kinds=json.loads(registry.read_text())
    for basis in ('user_accepted_url_variant','verified_archive_capture','official_document_identifier'):
        assert next(row for row in kinds if row['match_basis']==basis)['import_category']=='recovered_document'
    assert any(row['category']=='recovered_document' and row['kind']=='recovered_document' for row in kinds)
    result=reconcile(accepted,captures,registry,output=tmp_path/'staged',
        engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),decided_at=STAMP,decided_by='reconciliation')
    missing=pq.read_table(tmp_path/'staged'/result['missing_imports']).to_pylist()
    assert missing[0]['category']=='recovered_document'
    assert missing[0]['status']=='ready_for_owner_import'
    assert result['import_counts']==dict(ready=1,unresolved=0)


def test_source_category_controls_import_kind_and_preserves_excerpts(tmp_path):
    accepted,captures,registry=reconciliation_inputs(tmp_path)
    rows=pq.read_table(captures).to_pylist()
    # A source records that the retained material is an excerpt, even though
    # the accepted mapping's URL basis normally describes a recovered copy.
    rows[1]['recovery_category']='requested_content_in_official_hearing'
    pq.write_table(pa.Table.from_pylist(rows),captures)
    result=reconcile(accepted,captures,registry,output=tmp_path/'staged',
        engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
        decided_at=STAMP,decided_by='reconciliation')
    [request]=pq.read_table(tmp_path/'staged'/result['missing_imports']).to_pylist()
    assert request['category']==request['display_kind']=='requested_content_in_official_hearing'
    assert request['status']=='ready_for_owner_import'
    decisions=[json.loads(line) for line in (tmp_path/'staged'/result['provenance']).read_text().splitlines()]
    assert len(decisions)==2
    assert {row['kind'] for row in decisions}=={'requested_content_in_official_hearing'}
    assert not any(row['kind']=='rejected' for row in decisions)


@pytest.mark.parametrize('source_time',[None,'2019-01-01'])
def test_missing_exact_source_time_uses_earliest_valid_same_body_fetch(tmp_path,source_time):
    accepted,captures,registry=reconciliation_inputs(tmp_path)
    rows=pq.read_table(captures).to_pylist()
    source=rows[1]
    source['retrieved_at']=source_time
    rows.extend([
        dict(source,url='https://alias.example/earliest',retrieved_at='2020-01-01T00:00:00Z',
            receipt_key='receipts/earliest',receipt_line=2,capture_index=3),
        # Lexically earlier, but its UTC time is later than the chosen fetch.
        dict(source,url='https://alias.example/later',retrieved_at='2019-12-31T20:30:00-05:00',
            receipt_key='receipts/later'),
        dict(source,url='https://alias.example/invalid',retrieved_at='not-a-time'),
        dict(source,url='https://alias.example/date-only',retrieved_at='1900-01-01'),
        dict(source,url='https://alias.example/import',mode='retained_import',
            original_url='https://docs.house.gov/unrelated-import',retrieved_at='1990-01-01T00:00:00Z'),
        dict(source,url='https://alias.example/other-body',sha256='f'*64,retrieved_at='1980-01-01T00:00:00Z'),
    ])
    pq.write_table(pa.Table.from_pylist(list(reversed(rows))),captures)
    result=reconcile(accepted,captures,registry,output=tmp_path/'staged',
        engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
        decided_at=STAMP,decided_by='reconciliation')
    [request]=pq.read_table(tmp_path/'staged'/result['missing_imports']).to_pylist()
    assert request['retrieved_at']=='2020-01-01T00:00:00Z'
    assert (request['source_receipt_key'],request['source_receipt_line'],request['source_capture_index'])==(
        'receipts/earliest',2,3)
    assert request['status']=='ready_for_owner_import'
    assert result['import_counts']==dict(ready=1,unresolved=0)


def test_valid_exact_source_keeps_priority_over_same_body_alias(tmp_path):
    accepted,captures,registry=reconciliation_inputs(tmp_path)
    rows=pq.read_table(captures).to_pylist()
    rows.append(dict(rows[1],url='https://alias.example/older',retrieved_at='2010-01-01T00:00:00Z',
                     receipt_key='receipts/alias'))
    pq.write_table(pa.Table.from_pylist(rows),captures)
    result=reconcile(accepted,captures,registry,output=tmp_path/'staged',
        engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
        decided_at=STAMP,decided_by='reconciliation')
    [request]=pq.read_table(tmp_path/'staged'/result['missing_imports']).to_pylist()
    assert request['retrieved_at']=='2019-01-01T00:00:00Z'
    assert request['source_receipt_key']=='receipts/b'
