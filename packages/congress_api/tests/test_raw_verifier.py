"""B9/B12: LIST is the inventory; native joins and measured bytes establish integrity."""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.retention.raw_verifier import verify, check_body
from docspec_client.client import NativeDatasets


class Store:
    def __init__(self, values):
        self.values, self.list_calls, self.reads = values, 0, []

    def listing(self):
        self.list_calls += 1
        for key, (data, encoding) in self.values.items():
            yield dict(key=key, size=len(data), etag=hashlib.md5(data).hexdigest())

    def get(self, key):
        self.reads.append(key)
        data, encoding = self.values[key]
        return dict(Body=io.BytesIO(data), ContentLength=len(data),
                    ETag=hashlib.md5(data).hexdigest(), ContentEncoding=encoding)


def key(data, suffix='.gz'):
    sha = hashlib.sha256(data).hexdigest()
    return f'bodies/sha256/{sha[:2]}/{sha}{suffix}'


def engine():
    return NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])


def inputs(tmp_path, rows, receipts=(), previous=()):
    captures = tmp_path / 'captures.parquet'
    schema = pa.schema([('body_key',pa.string()),('stored_bytes',pa.int64()),
                        ('stored_sha256',pa.string()),('receipt_key',pa.string()),
                        ('receipt_line',pa.int64()),('pointer_json',pa.string())])
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), captures)
    receipt = tmp_path / 'receipts.jsonl.gz'
    verification = tmp_path / 'verification.jsonl.gz'
    for path, records in [(receipt,receipts),(verification,previous)]:
        with gzip.open(path,'wt') as out:
            for row in records:
                out.write(json.dumps(row)+'\n')
    return captures,[dict(key='receipts/f/2026-10-27/run.jsonl.gz',path=str(receipt))], [dict(key='provenance/verification/old.jsonl',path=str(verification))]


def test_sample_orphan_dedup_and_original_gzip_is_not_transfer_encoding(tmp_path):
    original = gzip.compress(b'WARC/1.0 source',mtime=0)
    store = Store({key(original,''):(original,None)})
    captures,receipts,previous = inputs(tmp_path,[])
    result = verify(store,captures=captures,receipts=receipts,previous=previous,
                    engine=engine(),work=tmp_path/'job',checked_at='2026-10-27T00:00:00Z',seed='fixed')
    assert result['valid'] and result['listed'] == 1 and result['checked'] == 1
    assert store.list_calls == 1 and store.reads == [key(original,'')]
    [record] = [json.loads(line) for line in Path(result['records']).read_text().splitlines()]
    assert record['sha256_verified'] is True and record['key'] == key(original,'')


def test_missing_size_conflict_and_baseline_replacement_refuse_success(tmp_path):
    data = b'one source'
    physical = key(data)
    stored = gzip.compress(data,mtime=0)
    missing = key(b'absent')
    captures,receipts,previous = inputs(tmp_path,[dict(body_key=physical,stored_bytes=len(stored)+1),
                                                   dict(body_key=missing,stored_bytes=12)],
        previous=[dict(key=physical,size=len(stored),etag='replaced',sha256_verified=False,
                       checked_at='2026-10-26T00:00:00Z',job='old')])
    result=verify(Store({physical:(stored,None)}),captures=captures,receipts=receipts,previous=previous,
                  engine=engine(),work=tmp_path/'job',checked_at='2026-10-27T00:00:00Z',seed='fixed')
    assert not result['valid'] and result['missing'] == 1 and result['mismatches'] == 1
    assert not Path(result['records']).exists()


def test_receipt_size_preferred_and_wrong_stored_digest_reported_untouched(tmp_path):
    data=b'original'
    stored=gzip.compress(data,mtime=0)
    physical=key(data)
    captures,receipts,previous=inputs(tmp_path,[dict(body_key=physical,stored_bytes=None,
        stored_sha256='a'*64,receipt_key='receipts/f/2026-10-27/run.jsonl.gz',receipt_line=1,pointer_json='["content","body"]')],
        receipts=[dict(captures=[dict(body_key=physical,stored_bytes=len(stored),
                                     stored_sha256=hashlib.sha256(stored).hexdigest())])])
    result=verify(Store({physical:(stored,None)}),captures=captures,receipts=receipts,previous=previous,
                  engine=engine(),work=tmp_path/'job',checked_at='2026-10-27T00:00:00Z',seed='fixed')
    assert result['digest_repairs'] == 1
    assert pq.read_table(captures)['stored_sha256'].to_pylist() == ['a'*64]
    [repair]=pq.read_table(tmp_path/'job/digest-repairs.parquet').to_pylist()
    assert repair['stored_sha256'] == hashlib.sha256(stored).hexdigest()


def test_whole_check_detects_corruption_and_reads_no_head():
    data=b'valid'
    store=Store({key(data):(gzip.compress(b'wrong',mtime=0),None)})
    [listing]=list(store.listing())
    result=check_body(store,listing,checked_at='2026-10-27T00:00:00Z')
    assert result['sha256_verified'] is False and result['error'] == 'identity_mismatch'
