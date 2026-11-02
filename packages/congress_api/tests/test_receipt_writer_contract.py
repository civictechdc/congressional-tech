"""B2 receipt fixtures: exact public fields, independent attempts, bodies first."""
from dataclasses import replace
import gzip
import hashlib
import json
from pathlib import Path

import pytest

URL = 'https://docs.house.gov/a.pdf'
WRITER = dict(job='capture', commit='a'*40, lockfile_digest='b'*64)


def attempt(tmp_path, *, data=b'%PDF-1.7\n%%EOF', status=200, complete=True, transport='direct'):
    from congress_api.models.raw_fetch import BodyFile, FetchAttempt
    path = tmp_path / (transport + '.body')
    path.write_bytes(data)
    body = BodyFile(path, hashlib.sha256(data).hexdigest(), len(data), 'application/pdf', 'pdf', 'v1', True)
    return FetchAttempt(URL, URL, '2026-10-27T10:00:00Z', transport, status, None, {}, (), complete, body)


def test_receipt_is_flat_and_bodies_precede_receipt(tmp_path):
    from congress_api.models.raw_fetch import FetchResult
    from congress_api.retention.receipt_writer import ReceiptWriter
    from congress_api.retention.body_store import BodyStore, LocalAdapter
    first = attempt(tmp_path, data=b'partial', complete=False)
    final = attempt(tmp_path, transport='zyte', status=201)
    root = tmp_path / 'raw'
    writer = ReceiptWriter(BodyStore(LocalAdapter(root)), identity=WRITER, run_id='run',
                           write_date='2026-10-27', archive_limits=None)
    key, line = writer.write(FetchResult(final, (first,)), family='documents')
    assert key == 'receipts/documents/2026-10-27/run-000001.jsonl.gz'
    assert json.loads(gzip.decompress((root / key).read_bytes())) == line
    assert set(line) == {'run_id','mode','family','requested_url','url','retrieved_at','http_status',
                         'provider_status','outcome','transport','response_headers','redirects','prior_attempts',
                         'source_context','writer','captures'}
    assert line['http_status'] == 201 and line['outcome'] == 'stored'
    assert [c['complete'] for c in line['captures']] == [True, False]
    assert [c['attempt'] for c in line['captures']] == [0, 1]
    assert line['prior_attempts'][0]['http_status'] == 200
    assert not {'http_status','retrieved_at','family','body_key'} & line['captures'][0].keys()
    for cap in line['captures']:
        assert (root / f"bodies/sha256/{cap['sha256'][:2]}/{cap['sha256']}{cap['stored_suffix']}").is_file()


@pytest.mark.parametrize(('status','complete','headers','error','outcome'), [
    (201,True,{},None,'stored'), (204,True,{},None,'stored'),
    (404,True,{},None,'failed'), (429,True,{},None,'retry_later'),
    (503,True,{},None,'retry_later'), (200,True,{'retry-after':'120'},None,'retry_later'),
    (200,False,{},'size_limit','size_limit'), (200,False,{},'body_error','request_failed')])
def test_six_outcomes_come_from_transfer_facts(tmp_path, status, complete, headers, error, outcome):
    from congress_api.models.raw_fetch import FetchResult
    from congress_api.retention.receipt_writer import ReceiptWriter
    from congress_api.retention.body_store import BodyStore, LocalAdapter
    a = replace(attempt(tmp_path,status=status,complete=complete), headers=headers, error=error)
    writer = ReceiptWriter(BodyStore(LocalAdapter(tmp_path/'raw')), identity=WRITER, run_id='run',
                           write_date='2026-10-27', archive_limits=None)
    assert writer.write(FetchResult(a),family='documents')[1]['outcome'] == outcome


def test_unsafe_receipt_is_refused_before_any_body_write(tmp_path):
    from congress_api.models.raw_fetch import FetchResult
    from congress_api.retention.receipt_writer import ReceiptWriter
    from congress_api.retention.body_store import BodyStore, LocalAdapter
    root = tmp_path/'raw'
    a = replace(attempt(tmp_path), requested_url=URL+'?token=secret')
    writer = ReceiptWriter(BodyStore(LocalAdapter(root)), identity=WRITER, run_id='run',
                           write_date='2026-10-27', archive_limits=None)
    with pytest.raises(ValueError, match='[Cc]redential'): writer.write(FetchResult(a), family='documents')
    assert not root.exists()


def test_stable_transfer_and_sniff_failure_codes_are_preserved(tmp_path):
    from congress_api.models.raw_fetch import FetchResult
    from congress_api.retention.receipt_writer import ReceiptWriter
    from congress_api.retention.body_store import BodyStore, LocalAdapter
    a=attempt(tmp_path,complete=False)
    a=replace(a,error='body_error',body=replace(a.body,sniff_error='pdf_reader_size_limit'))
    writer=ReceiptWriter(BodyStore(LocalAdapter(tmp_path/'raw')),identity=WRITER,run_id='run',
                         write_date='2026-10-27',archive_limits=None)
    line=writer.write(FetchResult(a),family='documents')[1]
    assert line['error_type']=='body_error'
    assert line['captures'][0]['sniff_error']=='pdf_reader_size_limit'


def test_error_codes_cannot_contain_paths_or_exception_messages(tmp_path):
    from congress_api.models.raw_fetch import FetchResult
    from congress_api.retention.receipt_writer import ReceiptWriter
    from congress_api.retention.body_store import BodyStore, LocalAdapter
    root=tmp_path/'raw'
    a=replace(attempt(tmp_path),error='failure at /Users/person/private')
    writer=ReceiptWriter(BodyStore(LocalAdapter(root)),identity=WRITER,run_id='run',
                         write_date='2026-10-27',archive_limits=None)
    with pytest.raises(ValueError,match='error code'):writer.write(FetchResult(a),family='documents')
    assert not root.exists()


@pytest.mark.parametrize(('status','headers'),[(206,[]),(200,[{'name':'Content-Range','value':'bytes 0-1/10'}])])
def test_provider_partial_response_stays_incomplete_in_published_receipt(tmp_path,status,headers):
    import base64
    from congress_api.acquisition.fetcher import Fetcher
    from congress_api.models.raw_fetch import Transfer
    from congress_api.transport.raw_adapters import ProviderAdapter
    from congress_api.retention.receipt_writer import ReceiptWriter
    from congress_api.retention.body_store import BodyStore,LocalAdapter
    class Direct:
        def hop(self,url,destination,**kwargs):
            destination.write_bytes(b'cut off direct body')
            return Transfer(destination,url,200,{},False,'body_error')
    class Response:
        status_code=200
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_content(self,chunk_size):
            yield json.dumps({'url':URL,'statusCode':status,'httpResponseHeaders':headers,
                              'httpResponseBody':base64.b64encode(b'ab').decode()}).encode()
    fetcher=Fetcher(scope=lambda url:url==URL,direct=Direct(),provider=ProviderAdapter(lambda _:Response()),
                    pace=lambda *args:None,directory=tmp_path/'spool',spool_limit=5000)
    result=fetcher.fetch(URL)
    root=tmp_path/'raw'
    writer=ReceiptWriter(BodyStore(LocalAdapter(root)),identity=WRITER,run_id='run',
                         write_date='2026-10-27',archive_limits=None)
    key,line=writer.write(result,family='documents')
    published=json.loads(gzip.decompress((root/key).read_bytes()))
    assert published==line and line['outcome']=='request_failed'
    assert line['error_type']=='partial_response' and line['http_status']==status
    assert not line['captures'][0]['complete'] and not line['captures'][1]['complete']
    assert result.final.body.path.read_bytes()==b'ab'


def test_frozen_receipt_reconciles_lost_ack_and_reuses_exact_bytes(tmp_path):
    from congress_api.models.raw_fetch import FetchResult
    from congress_api.retention.receipt_writer import ReceiptWriter
    from congress_api.retention.body_store import BodyStore, LocalAdapter
    class LostAck(LocalAdapter):
        def create(self,key,source,**facts):
            created=super().create(key,source,**facts)
            if key.startswith('receipts/') and created:
                raise OSError('lost acknowledgment')
            return created
    store=BodyStore(LostAck(tmp_path/'raw'))
    writer=ReceiptWriter(store,identity=WRITER,run_id='run',write_date='2026-10-27',archive_limits=None)
    key,line=writer.write(FetchResult(attempt(tmp_path)),family='documents',operation_id='op1',freeze_dir=tmp_path/'frozen')
    first=(tmp_path/'raw'/key).read_bytes()
    fresh=ReceiptWriter(BodyStore(LocalAdapter(tmp_path/'raw')),identity=WRITER,run_id='different',
                        write_date='2026-10-28',archive_limits=None)
    key2,line2=fresh.write(None,operation_id='op1',freeze_dir=tmp_path/'frozen')
    assert (key2,line2)==(key,line)
    assert (tmp_path/'raw'/key).read_bytes()==first


@pytest.mark.parametrize(('status','data','outcome'), [
    (202,b'<html>challenge</html>','failed'), (200,b'','failed'), (204,b'','failed'),
    (200,b'%PDF-1.7\n%%EOF','stored')])
def test_a_document_is_2xx_other_than_202_with_a_body(tmp_path, status, data, outcome):
    """ct-c6b0/ct-3l1c: the writer applies the one shared document rule."""
    from congress_api.models.raw_fetch import FetchResult
    from congress_api.retention.receipt_writer import ReceiptWriter
    from congress_api.retention.body_store import BodyStore, LocalAdapter
    writer = ReceiptWriter(BodyStore(LocalAdapter(tmp_path/'raw')), identity=WRITER, run_id='run',
                           write_date='2026-10-27', archive_limits=None)
    line = writer.write(FetchResult(attempt(tmp_path, data=data, status=status)), family='documents')[1]
    assert line['outcome'] == outcome and line['captures'][0]['bytes'] == len(data)


def test_document_rule_has_one_definition_in_python_and_sql(tmp_path):
    """The SQL rendering the mapping uses agrees with the writer's Python rule on every case."""
    import os
    from congress_api.lake.receipt_metadata import (EMPTY_SHA256, document_status, document_status_sql,
                                                    empty_body, empty_body_sql)
    from congress_api.retention.provenance import json_input, run_job
    from docspec_client.client import NativeDatasets
    cases = [dict(status=s, size=n, sha=(EMPTY_SHA256 if n == 0 else None if n is None else 'ab'*32))
             for s in (None,199,200,201,202,204,206,299,300,304,404,429,503) for n in (None,0,1)]
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        rows = run_job(tmp_path, engine, inputs=[json_input(tmp_path, 'cases', cases, status='Int64', size='Int64', sha='Utf8')],
            steps=[], outputs=[], queries=[dict(name='rule', sql=f"""SELECT status,size,sha,
                coalesce({document_status_sql('status')},false) AS document,{empty_body_sql('sha','size')} AS empty
                FROM cases ORDER BY status NULLS FIRST,size NULLS FIRST""")])['rule']
    assert len(rows) == len(cases)
    for row in rows:
        assert row['document'] == document_status(row['status']), row
        assert row['empty'] == empty_body(row['sha'], row['size']), row


def test_a_local_path_is_refused_at_write(tmp_path, monkeypatch):
    """Receipts are immutable: an absolute path can only be kept out when the line is written."""
    from congress_api.models.raw_fetch import BodyFile, FetchResult
    from congress_api.retention import receipt_writer
    from congress_api.retention.archive_expander import Expansion, ExpandedMember
    from congress_api.retention.body_store import BodyStore, LocalAdapter
    member = tmp_path/'member.pdf'
    member.write_bytes(b'%PDF-1.7\n%%EOF')
    def expand(path, *, directory, limits):
        body = BodyFile(member, hashlib.sha256(member.read_bytes()).hexdigest(), member.stat().st_size,
                        'application/pdf', 'pdf', 'v1', True)
        return Expansion('expanded', (ExpandedMember('/Users/someone/report.pdf', 0, body),))
    monkeypatch.setattr(receipt_writer, 'expand_archive', expand)
    a = attempt(tmp_path, data=b'PK\x05\x06' + bytes(18))
    a = replace(a, body=replace(a.body, media_type='application/zip', sniffed_format='zip'))
    root = tmp_path/'raw'
    writer = receipt_writer.ReceiptWriter(BodyStore(LocalAdapter(root)), identity=WRITER, run_id='run',
                                          write_date='2026-10-27', archive_limits=object())
    with pytest.raises(ValueError, match='local path at captures.1.member_path'):
        writer.write(FetchResult(a), family='documents')
    assert not list(root.glob('receipts/**/*.gz'))


@pytest.mark.parametrize('value', ['/Users/me/x.pdf', 'C:\\data\\x.pdf', '~/x.pdf'])
def test_every_writer_shares_the_relative_path_rule(value):
    from congress_api.retention.receipt_privacy import refuse_local_paths
    with pytest.raises(ValueError, match='local path'):
        refuse_local_paths(dict(file_references=[dict(original_path=value)]))
    assert refuse_local_paths(dict(original_path='external-sources/a/b.xml', url='https://x.gov/Users/a'))
