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
