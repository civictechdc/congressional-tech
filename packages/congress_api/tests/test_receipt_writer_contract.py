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


def test_frozen_receipt_cleanup_failure_precedes_upload_and_leaves_a_retry(tmp_path, monkeypatch):
    from tempfile import TemporaryDirectory
    from congress_api.models.raw_fetch import FetchResult
    from congress_api.retention import receipt_writer
    from congress_api.retention.body_store import BodyStore, LocalAdapter

    class CleanupFailure(TemporaryDirectory):
        def __exit__(self, *exc):
            super().__exit__(*exc)
            raise OSError('planted receipt scratch cleanup failure')

    monkeypatch.setattr(receipt_writer, 'TemporaryDirectory', CleanupFailure)
    root = tmp_path/'raw'
    writer = receipt_writer.ReceiptWriter(BodyStore(LocalAdapter(root)), identity=WRITER,
        run_id='run', write_date='2026-10-27', archive_limits=None)
    result = FetchResult(attempt(tmp_path))
    options = dict(family='documents', operation_id='op1', freeze_dir=tmp_path/'frozen')

    with pytest.raises(OSError, match='planted receipt scratch cleanup failure'):
        writer.write(result, **options)
    frozen = options['freeze_dir']/'op1'
    metadata = json.loads((frozen/'receipt.json').read_bytes())
    raw = (frozen/'receipt.gz').read_bytes()
    assert metadata['sha256'] == hashlib.sha256(raw).hexdigest()
    published = root/metadata['key']
    assert not published.exists()

    key, line = writer.write(result, **options)
    assert key == metadata['key']
    assert published.read_bytes() == raw
    assert json.loads(gzip.decompress(raw)) == line
    assert writer.write(result, **options) == (key, line)
    assert published.read_bytes() == raw


@pytest.mark.parametrize('has_metadata', [True, False], ids=['pinned', 'gzip-only'])
def test_frozen_receipt_reconciles_lost_ack_and_reuses_exact_bytes(tmp_path, has_metadata):
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
    frozen = tmp_path/'frozen'/'op1'
    if not has_metadata:
        (frozen/'receipt.json').unlink()
    fresh=ReceiptWriter(BodyStore(LocalAdapter(tmp_path/'raw')),identity=WRITER,run_id='different',
                        write_date='2026-10-28' if has_metadata else '2026-10-27',archive_limits=None)
    key2,line2=fresh.write(None,operation_id='op1',freeze_dir=tmp_path/'frozen')
    assert (key2,line2)==(key,line)
    assert (tmp_path/'raw'/key).read_bytes()==(frozen/'receipt.gz').read_bytes()==first
    assert json.loads((frozen/'receipt.json').read_bytes()) == dict(key=key, sha256=hashlib.sha256(first).hexdigest())


@pytest.mark.parametrize('lands_after,retry_fails,stored', [
    (2, False, True),      # the first attempt settles while we wait: no second create
    (None, False, True),   # it never lands: the one retry creates it
    (None, True, False),   # the retry fails too and nothing is stored: the original error stands
])
def test_an_unacknowledged_receipt_create_is_looked_for_as_it_settles_then_retried_once(tmp_path, monkeypatch, lands_after, retry_fails, stored):
    """Capture 44132068232: R2 refused the create as a concurrent request for the same object
    while an earlier attempt was still settling, and one immediate look was too early."""
    from congress_api.models.raw_fetch import FetchResult
    from congress_api.retention import receipt_writer
    from congress_api.retention.receipt_writer import ReceiptWriter
    from congress_api.retention.body_store import BodyStore, LocalAdapter
    waits, creates = [], []
    class Settling(LocalAdapter):
        """The first receipt create raises; its object appears only after `lands_after` looks."""
        pending = None
        def create(self, key, source, **facts):
            if not key.startswith('receipts/'):
                return super().create(key, source, **facts)
            creates.append(key)
            if len(creates) == 1:
                data = source.read() if hasattr(source, 'read') else Path(source).read_bytes()
                if hasattr(source, 'seek'):
                    source.seek(0)
                type(self).pending = (key, data)
                raise OSError('503 Reduce your concurrent request rate for the same object')
            if retry_fails:
                raise OSError('503 again')
            return super().create(key, source, **facts)
        def head(self, key):
            if lands_after is not None and self.pending and len(waits) > lands_after:
                target = self.root / self.pending[0]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(self.pending[1])
            return super().head(key)
    monkeypatch.setattr(receipt_writer.time, 'sleep', waits.append)
    writer = ReceiptWriter(BodyStore(Settling(tmp_path / 'raw')), identity=WRITER, run_id='run', write_date='2026-10-27', archive_limits=None)
    options = dict(family='documents', operation_id='op1', freeze_dir=tmp_path / 'frozen')
    if not stored:
        with pytest.raises(OSError, match='Reduce your concurrent request rate'):
            writer.write(FetchResult(attempt(tmp_path)), **options)
        assert waits == list(ReceiptWriter.SETTLE_SECONDS) and len(creates) == 2
        return
    key, line = writer.write(FetchResult(attempt(tmp_path)), **options)
    assert (tmp_path / 'raw' / key).read_bytes() == (tmp_path / 'frozen/op1/receipt.gz').read_bytes()
    if lands_after is not None:
        assert len(creates) == 1 and waits == list(ReceiptWriter.SETTLE_SECONDS[:lands_after + 1])
    else:
        assert len(creates) == 2 and waits == list(ReceiptWriter.SETTLE_SECONDS)


@pytest.mark.parametrize('has_metadata', [True, False], ids=['pinned', 'gzip-only'])
def test_frozen_receipt_refuses_a_nested_local_path_before_adapter_io(tmp_path, has_metadata):
    from unittest.mock import Mock
    from congress_api.models.raw_fetch import FetchResult
    from congress_api.retention.receipt_privacy import LocalPathRefused
    from congress_api.retention.receipt_writer import ReceiptWriter
    from congress_api.retention.body_store import BodyStore, LocalAdapter

    identity = dict(identity=WRITER, run_id='run', write_date='2026-10-27', archive_limits=None)
    result = FetchResult(attempt(tmp_path))
    original = ReceiptWriter(BodyStore(LocalAdapter(tmp_path/'original')), **identity)
    key, line = original.write(result, family='documents', mode='retained_import',
                               recovery_evidence=dict(acquisition=dict(body_path='safe.pdf')))
    operation = '000001'
    frozen = tmp_path/'frozen'/operation
    frozen.mkdir(parents=True)
    line['recovery_evidence']['acquisition']['body_path'] = '/srv/private/example.pdf'
    payload = gzip.compress((json.dumps(line)+'\n').encode(), mtime=0)
    (frozen/'receipt.gz').write_bytes(payload)
    if has_metadata:
        (frozen/'receipt.json').write_text(json.dumps(dict(key=key, sha256=hashlib.sha256(payload).hexdigest())))

    adapter = Mock(spec=LocalAdapter)
    # A matching object would let the lost-acknowledgment handler swallow a refusal.
    adapter.head.return_value = dict(size=len(payload), etag=hashlib.md5(payload).hexdigest())
    retry = ReceiptWriter(BodyStore(adapter), **identity)
    with pytest.raises(LocalPathRefused, match=r'recovery_evidence\.acquisition\.body_path'):
        retry.write(result, operation_id=operation, freeze_dir=frozen.parent)
    assert adapter.mock_calls == []
    assert (frozen/'receipt.gz').read_bytes() == payload


@pytest.mark.parametrize(('status','data','headers','outcome'), [
    (202,b'<html>challenge</html>',{},'failed'), (200,b'',{},'failed'), (204,b'',{},'failed'),
    (200,b'%PDF-1.7\n%%EOF',{},'stored'),
    (206,b'%PDF-1.7\n%%EOF',{'content-range':'bytes 0-13/14'},'stored'),
    (206,b'%PDF-1.7\n%%EOF',{'content-range':'bytes 0-13/4096'},'failed'),
    (206,b'%PDF-1.7\n%%EOF',{},'failed')])
def test_a_document_is_2xx_other_than_202_with_a_whole_body(tmp_path, status, data, headers, outcome):
    """ct-c6b0/ct-3l1c: the writer applies the one shared document rule; a 206 must cover it all."""
    from congress_api.models.raw_fetch import FetchResult
    from congress_api.retention.receipt_writer import ReceiptWriter
    from congress_api.retention.body_store import BodyStore, LocalAdapter
    writer = ReceiptWriter(BodyStore(LocalAdapter(tmp_path/'raw')), identity=WRITER, run_id='run',
                           write_date='2026-10-27', archive_limits=None)
    line = writer.write(FetchResult(replace(attempt(tmp_path, data=data, status=status), headers=headers)),
                        family='documents')[1]
    assert line['outcome'] == outcome and line['captures'][0]['bytes'] == len(data)
    assert line['response_headers'] == headers


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


def test_archive_member_names_are_never_refused(tmp_path, monkeypatch):
    """A member name is the archive's own string, not a local path: '~$x.docx' and '/a/b.pdf' are kept."""
    from congress_api.models.raw_fetch import BodyFile, FetchResult
    from congress_api.retention import receipt_writer
    from congress_api.retention.archive_expander import Expansion, ExpandedMember
    from congress_api.retention.body_store import BodyStore, LocalAdapter
    names = ['~$draft.docx', '/Users/someone/report.pdf']
    def expand(path, *, directory, limits):
        members = []
        for index, name in enumerate(names):
            member = tmp_path/f'member{index}.pdf'
            member.write_bytes(b'%PDF-1.7\n%%EOF' + bytes([index]))
            body = BodyFile(member, hashlib.sha256(member.read_bytes()).hexdigest(), member.stat().st_size,
                            'application/pdf', 'pdf', 'v1', True)
            members.append(ExpandedMember(name, index, body))
        return Expansion('expanded', tuple(members))
    monkeypatch.setattr(receipt_writer, 'expand_archive', expand)
    a = attempt(tmp_path, data=b'PK\x05\x06' + bytes(18))
    a = replace(a, body=replace(a.body, media_type='application/zip', sniffed_format='zip'))
    writer = receipt_writer.ReceiptWriter(BodyStore(LocalAdapter(tmp_path/'raw')), identity=WRITER, run_id='run',
                                          write_date='2026-10-27', archive_limits=object())
    line = writer.write(FetchResult(a), family='documents')[1]
    assert [c['member_path'] for c in line['captures'][1:]] == names


@pytest.mark.parametrize('value', ['/Users/me/x.pdf', 'C:\\data\\x.pdf', 'C:/data/x.pdf', '~/x.pdf', '\\\\host\\share\\x.pdf'])
def test_every_writer_shares_the_absolute_path_rule(value):
    from congress_api.retention.receipt_privacy import LocalPathRefused, refuse_local_paths
    with pytest.raises(LocalPathRefused, match='local path'):
        refuse_local_paths(dict(file_references=[dict(original_path=value)]))


@pytest.mark.parametrize('value', ['external-sources/a/b.xml', '~$draft.docx', 'C:report.pdf'])
def test_relative_paths_and_member_names_pass(value):
    from congress_api.retention.receipt_privacy import refuse_local_paths
    line = dict(original_path=value, url='https://x.gov/Users/a', captures=[dict(member_path='/abs/member.pdf')])
    assert refuse_local_paths(line) is line


def test_a_local_path_is_refused_before_any_body_is_stored(tmp_path):
    """A refused receipt leaves no body without its creating line (red-e1)."""
    from congress_api.models.raw_fetch import FetchResult
    from congress_api.retention.receipt_privacy import LocalPathRefused
    from congress_api.retention.receipt_writer import ReceiptWriter
    from congress_api.retention.body_store import BodyStore, LocalAdapter
    root = tmp_path/'raw'
    writer = ReceiptWriter(BodyStore(LocalAdapter(root)), identity=WRITER, run_id='run',
                           write_date='2026-10-27', archive_limits=None)
    evidence = dict(original_url=URL, acquisition=dict(body_path='/srv/cache/x.pdf'))
    with pytest.raises(LocalPathRefused, match='recovery_evidence.acquisition.body_path'):
        writer.write(FetchResult(attempt(tmp_path)), family='documents', mode='retained_import',
                     recovery_evidence=evidence)
    assert not root.exists() or not any(p.is_file() for p in root.rglob('*'))


def test_receipt_writer_reconciles_ambiguous_r2_body_and_receipt_creates(tmp_path, monkeypatch):
    """Capture 44395592746: an unacknowledged gzipped body PUT returns 503 while settling;
    confirming via HEAD emits a valid receipt with one PUT per object and no double wait."""
    import io
    import time
    from botocore.exceptions import ClientError
    from congress_api.models.raw_fetch import BodyFile, FetchAttempt, FetchResult
    from congress_api.retention.body_store import BodyStore, R2Adapter
    from congress_api.retention.receipt_writer import ReceiptWriter

    html = b'<html><body>hearing transcript</body></html>'
    buffer = io.BytesIO()
    with gzip.GzipFile(filename='', fileobj=buffer, mode='wb', compresslevel=6, mtime=0) as zipped:
        zipped.write(html)
    compressed = buffer.getvalue()
    sha = hashlib.sha256(html).hexdigest()
    body_key = f'bodies/sha256/{sha[:2]}/{sha}'
    body_path = tmp_path / 'page.html'
    body_path.write_bytes(html)
    fetched = FetchAttempt('https://docs.house.gov/page.html', 'https://docs.house.gov/page.html',
                           '2026-11-18T11:20:00Z', 'direct', 200, None, {'content-type': 'text/html'},
                           (), True, BodyFile(body_path, sha, len(html), 'text/html', 'html', 'v1', True))

    waits, puts, looks, stored = [], [], {}, {}

    def error(code, status):
        return ClientError({'Error': {'Code': code, 'Message': 'Reduce your concurrent request rate for the same object'},
                            'ResponseMetadata': {'HTTPStatusCode': status}}, 'PutObject')

    class Client:
        def head_object(self, *, Bucket, Key):
            if Key in stored:
                looks[Key] = looks.get(Key, 0) + 1
                if looks[Key] == 1:
                    raise error('404', 404)
                payload = stored[Key]
                return {'ContentLength': len(payload), 'ETag': '"' + hashlib.md5(payload).hexdigest() + '"'}
            raise error('404', 404)

        def put_object(self, **args):
            payload = args['Body'].read()
            puts.append((args['Key'], args.get('ContentEncoding'), len(payload)))
            stored[args['Key']] = payload
            raise error('ServiceUnavailable', 503)

    monkeypatch.setattr(time, 'sleep', waits.append)
    writer = ReceiptWriter(BodyStore(R2Adapter(Client(), 'raw')), identity=WRITER, run_id='run',
                           write_date='2026-11-18', archive_limits=None)
    receipt_key, line = writer.write(FetchResult(fetched), family='documents',
                                     operation_id='op1', freeze_dir=tmp_path / 'frozen')
    assert [item[:2] for item in puts] == [(body_key, 'gzip'), (receipt_key, None)]
    assert waits == [0, 2, 0, 2]
    assert gzip.decompress(stored[body_key]) == html
    assert json.loads(gzip.decompress(stored[receipt_key])) == line
    assert line['outcome'] == 'stored'
    assert line['captures'][0]['bytes'] == len(html)
    assert line['captures'][0]['stored_bytes'] == len(compressed)
    assert line['captures'][0]['stored_md5'] == hashlib.md5(compressed).hexdigest()


def test_ordinary_unfrozen_receipt_503_with_matching_object_does_not_report_stored(tmp_path, monkeypatch):
    import time
    from botocore.exceptions import ClientError
    from congress_api.models.raw_fetch import FetchResult
    from congress_api.retention.body_store import BodyStore, R2Adapter, RawNameCollision
    from congress_api.retention.receipt_writer import ReceiptWriter

    waits, receipt_puts, receipt_heads, stored = [], [], [], {}

    def error(code, status, operation='PutObject'):
        return ClientError({'Error': {'Code': code, 'Message': 'Reduce your concurrent request rate for the same object'},
                            'ResponseMetadata': {'HTTPStatusCode': status}}, operation)

    class Client:
        def head_object(self, *, Bucket, Key):
            if Key.startswith('receipts/'):
                receipt_heads.append(Key)
            if Key in stored:
                payload = stored[Key]
                return {'ContentLength': len(payload), 'ETag': '"' + hashlib.md5(payload).hexdigest() + '"'}
            raise error('404', 404, 'HeadObject')

        def put_object(self, **args):
            payload = args['Body'].read()
            key = args['Key']
            if key.startswith('bodies/'):
                stored[key] = payload
                return {'ETag': '"' + hashlib.md5(payload).hexdigest() + '"'}
            receipt_puts.append(key)
            # Simulate an already-existing identical receipt object from another writer.
            stored[key] = payload
            if len(receipt_puts) == 1:
                raise error('ServiceUnavailable', 503)
            raise error('PreconditionFailed', 412)

    monkeypatch.setattr(time, 'sleep', waits.append)
    store = BodyStore(R2Adapter(Client(), 'raw'))
    writer = ReceiptWriter(store, identity=WRITER, run_id='run', write_date='2026-11-18', archive_limits=None)
    with pytest.raises(ClientError, match='Reduce your concurrent request rate'):
        writer.write(FetchResult(attempt(tmp_path)), family='documents')
    assert len(receipt_puts) == 1
    assert receipt_heads == []
    assert waits == []

    duplicate_source = tmp_path / 'duplicate-receipt.jsonl.gz'
    duplicate_source.write_bytes(stored[receipt_puts[0]])
    with pytest.raises(RawNameCollision):
        store.put(receipt_puts[0], duplicate_source, 'application/x-ndjson')
    assert len(receipt_puts) == 2
    assert receipt_heads == []
    assert waits == []


def test_frozen_receipt_head_failures_and_shared_writer_budget(tmp_path, monkeypatch):
    import time
    from botocore.exceptions import ClientError
    from congress_api.models.raw_fetch import BodyFile, FetchAttempt, FetchResult
    from congress_api.retention.body_store import BodyStore, R2Adapter
    from congress_api.retention.receipt_writer import ReceiptWriter

    def service_error(code, status, operation, message):
        return ClientError({'Error': {'Code': code, 'Message': message},
                            'ResponseMetadata': {'HTTPStatusCode': status}}, operation)

    # 1. Persistent HEAD failure on a frozen receipt raises the original PUT error without replaying.
    waits, receipt_puts = [], []

    class FailingHeadClient:
        def head_object(self, *, Bucket, Key):
            if Key.startswith('bodies/'):
                raise service_error('404', 404, 'HeadObject', 'Not Found')
            raise service_error('ServiceUnavailable', 503, 'HeadObject', 'Receipt HEAD 503')

        def put_object(self, **args):
            payload = args['Body'].read()
            if args['Key'].startswith('bodies/'):
                return {'ETag': '"' + hashlib.md5(payload).hexdigest() + '"'}
            receipt_puts.append(args['Key'])
            raise service_error('ServiceUnavailable', 503, 'PutObject', 'Original receipt PutObject 503')

    monkeypatch.setattr(time, 'sleep', waits.append)
    writer = ReceiptWriter(BodyStore(R2Adapter(FailingHeadClient(), 'raw')), identity=WRITER,
                           run_id='run', write_date='2026-11-18', archive_limits=None)
    with pytest.raises(ClientError, match='Original receipt PutObject 503'):
        writer.write(FetchResult(attempt(tmp_path)), family='documents',
                     operation_id='op-head-fail', freeze_dir=tmp_path / 'frozen-a')
    assert len(receipt_puts) == 1
    assert waits == [0, 2, 5, 15]

    # 2. Body and frozen-receipt reconciliations share one 66s per-writer budget.
    waits.clear()
    puts, stored = {}, {}

    class AmbiguousClient:
        def head_object(self, *, Bucket, Key):
            if Key in stored:
                payload = stored[Key]
                return {'ContentLength': len(payload), 'ETag': '"' + hashlib.md5(payload).hexdigest() + '"'}
            raise service_error('404', 404, 'HeadObject', 'Not Found')

        def put_object(self, **args):
            payload = args['Body'].read()
            key = args['Key']
            puts[key] = puts.get(key, 0) + 1
            if puts[key] == 1:
                raise service_error('ServiceUnavailable', 503, 'PutObject', 'Ambiguous R2 write')
            stored[key] = payload
            return {'ETag': '"' + hashlib.md5(payload).hexdigest() + '"'}

    def make_attempt(index):
        pdf = b'%PDF-1.7\n' + f'item-{index}\n'.encode() + b'%%EOF'
        path = tmp_path / f'item-{index}.pdf'
        path.write_bytes(pdf)
        body = BodyFile(path, hashlib.sha256(pdf).hexdigest(), len(pdf), 'application/pdf', 'pdf', 'v1', True)
        return FetchAttempt(f'https://docs.house.gov/{index}.pdf', f'https://docs.house.gov/{index}.pdf',
                            '2026-11-18T11:20:00Z', 'direct', 200, None, {}, (), True, body)

    shared_writer = ReceiptWriter(BodyStore(R2Adapter(AmbiguousClient(), 'raw')), identity=WRITER,
                                  run_id='run', write_date='2026-11-18', archive_limits=None)
    first_key, first_line = shared_writer.write(FetchResult(make_attempt(1)), family='documents',
                                                operation_id='op1', freeze_dir=tmp_path / 'frozen-b')
    assert first_line['outcome'] == 'stored' and first_key in stored
    assert waits == [0, 2, 5, 15, 0, 2, 5, 15] and sum(waits) == 44

    with pytest.raises(ClientError, match='Ambiguous R2 write'):
        shared_writer.write(FetchResult(make_attempt(2)), family='documents',
                            operation_id='op2', freeze_dir=tmp_path / 'frozen-b')
    second_receipt_key = 'receipts/documents/2026-11-18/run-op2.jsonl.gz'
    assert puts[second_receipt_key] == 1 and second_receipt_key not in stored
    assert waits == [0, 2, 5, 15] * 3 and sum(waits) == 66
