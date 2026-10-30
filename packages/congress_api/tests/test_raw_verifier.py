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
    assert result['orphans']==1
    assert pq.read_table(tmp_path/'job/orphans.parquet')['key'].to_pylist()==[key(original,'')]
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


def test_only_25_referenced_bodies_are_read_and_listing_is_one_traversal(tmp_path):
    originals=[f'source-{n}'.encode() for n in range(30)]
    values={key(data):(gzip.compress(data,mtime=0),None) for data in originals}
    store=Store(values)
    captures,receipts,previous=inputs(tmp_path,[dict(body_key=k,stored_bytes=len(v[0])) for k,v in values.items()])
    result=verify(store,captures=captures,receipts=receipts,previous=previous,engine=engine(),
                  work=tmp_path/'job',checked_at='2026-10-27T00:00:00Z',seed='fixed')
    assert result['valid'] and result['checked']==25 and result['listed']==30
    assert result['orphans']==0
    assert store.list_calls==1 and len(store.reads)==len(set(store.reads))==25


def test_failed_listing_never_claims_a_verified_baseline(tmp_path):
    class Broken(Store):
        def listing(self):
            yield dict(key=key(b'x'),size=1,etag='untrusted')
            raise OSError('listing interrupted')
    captures,receipts,previous=inputs(tmp_path,[])
    with pytest.raises(OSError,match='listing interrupted'):
        verify(Broken({}),captures=captures,receipts=receipts,previous=previous,engine=engine(),
               work=tmp_path/'job',checked_at='2026-10-27T00:00:00Z',seed='fixed')
    assert not (tmp_path/'job/verification.jsonl').exists()


def test_staged_verification_is_create_only_and_bound_to_accepted_bytes(tmp_path):
    from congress_api.cli.raw_verify import apply_staged
    from congress_api.retention.body_store import BodyStore,LocalAdapter
    data=b'local sample'
    captures,receipts,previous=inputs(tmp_path,[])
    result=verify(Store({key(data):(gzip.compress(data,mtime=0),None)}),captures=captures,
        receipts=receipts,previous=previous,engine=engine(),work=tmp_path/'job',
        checked_at='2026-10-27T00:00:00Z',seed='fixed')
    store=BodyStore(LocalAdapter(tmp_path/'raw'))
    applied=apply_staged(tmp_path/'job',store)
    assert (tmp_path/'raw'/applied['provenance']).is_file()
    with pytest.raises(RuntimeError,match='reused'):
        apply_staged(tmp_path/'job',store)
    Path(result['records']).write_text('{}\n')
    with pytest.raises(ValueError,match='changed'):
        apply_staged(tmp_path/'job',store)


def test_receipt_cleanup_verification_records_are_not_expected_bodies(tmp_path):
    data=b'body and receipt have different verification roles'
    stored=gzip.compress(data,mtime=0)
    captures,receipts,previous=inputs(tmp_path,[dict(body_key=key(data),stored_bytes=len(stored))],
        previous=[dict(key='receipts/f/2026-10-27/cleaned.jsonl.gz',size=200,etag='receipt-etag',
                       sha256_verified=False,checked_at='2026-10-26T00:00:00Z',job='receipt-cleanup')])
    result=verify(Store({key(data):(stored,None)}),captures=captures,receipts=receipts,previous=previous,
        engine=engine(),work=tmp_path/'job',checked_at='2026-10-27T00:00:00Z',seed='fixed')
    assert result['valid'] and result['listed']==1 and result['missing']==0


def test_null_identity_rows_do_not_fabricate_body_references(tmp_path):
    captures,receipts,previous=inputs(tmp_path,[],receipts=[dict(captures=[{}])])
    schema=pa.schema([('sha256',pa.binary(32)),('stored_sha256',pa.binary(32)),
                      ('stored_bytes',pa.int64()),('receipt_key',pa.string()),
                      ('receipt_line',pa.int64()),('pointer_json',pa.string())])
    pq.write_table(pa.Table.from_pylist([dict(receipt_key='metadata-only',receipt_line=1)],schema=schema),captures)
    data=b'known orphan'
    result=verify(Store({key(data):(gzip.compress(data,mtime=0),None)}),captures=captures,
        receipts=receipts,previous=previous,engine=engine(),work=tmp_path/'job',
        checked_at='2026-10-27T00:00:00Z',seed='fixed')
    assert result['valid'] and result['missing']==0 and result['orphans']==1


def test_equal_index_digest_does_not_hide_conflicting_receipt_evidence(tmp_path):
    data=b'conflicted receipt facts'
    stored=gzip.compress(data,mtime=0)
    locator='receipts/f/2026-10-27/run.jsonl.gz'
    captures,receipts,previous=inputs(tmp_path,[dict(body_key=key(data),stored_bytes=len(stored),
        stored_sha256='1'*64,receipt_key=locator,receipt_line=1,pointer_json='["body"]')],
        receipts=[dict(captures=[dict(body_key=key(data),stored_sha256='1'*64,stored_bytes=len(stored)),
                                 dict(body_key=key(data),stored_sha256='2'*64,stored_bytes=len(stored))])])
    result=verify(Store({key(data):(stored,None)}),captures=captures,receipts=receipts,previous=previous,
        engine=engine(),work=tmp_path/'job',checked_at='2026-10-27T00:00:00Z',seed='fixed')
    assert not result['valid'] and result['digest_conflicts']==1 and result['digest_repairs']==0
    assert pq.read_table(tmp_path/'job/digest-repairs.parquet').num_rows==0


def test_full_rehash_hashes_all_unverified_and_skips_sha256_verified(tmp_path):
    originals=[f'rehash-body-{i}'.encode() for i in range(30)]
    values={key(data):(gzip.compress(data,mtime=0),None) for data in originals}
    pdf_data=b'%PDF-1.7\nverified by b13\n%%EOF\n'
    pdf_gz_key=key(pdf_data,'.gz')
    pdf_copy_key=key(pdf_data,'.pdf')
    pdf_gz_bytes=gzip.compress(pdf_data,mtime=0)
    values[pdf_gz_key]=(pdf_gz_bytes,None)
    values[pdf_copy_key]=(pdf_data,None)

    rows=[dict(body_key=k,stored_bytes=len(v[0])) for k,v in values.items() if not k.endswith('.pdf')]
    prior=[
        dict(key=pdf_gz_key,size=len(pdf_gz_bytes),etag=hashlib.md5(pdf_gz_bytes).hexdigest(),
             sha256_verified=True,stored_sha256=hashlib.sha256(pdf_gz_bytes).hexdigest(),
             checked_at='2026-10-26T00:00:00Z',job='pdf-backfill'),
        dict(key=pdf_copy_key,size=len(pdf_data),etag=hashlib.md5(pdf_data).hexdigest(),
             sha256_verified=True,stored_sha256=hashlib.sha256(pdf_data).hexdigest(),
             intact=True,checked_at='2026-10-26T00:00:00Z',job='pdf-backfill'),
    ]
    for k,(stored,_) in list(values.items())[:10]:
        prior.append(dict(key=k,size=len(stored),etag=hashlib.md5(stored).hexdigest(),
                          sha256_verified=False,stored_sha256=None,
                          checked_at='2026-10-26T00:00:00Z',job='raw-verifier'))

    captures,receipts,previous=inputs(tmp_path,rows,previous=prior)
    with pytest.raises(ValueError,match='full_rehash'):
        verify(Store(values),captures=captures,receipts=receipts,previous=previous,
               engine=engine(),work=tmp_path/'bad-flag',checked_at='2026-10-27T00:00:00Z',full_rehash='yes')

    store=Store(values)
    result=verify(store,captures=captures,receipts=receipts,previous=previous,
                  engine=engine(),work=tmp_path/'rehash-1',checked_at='2026-10-27T00:00:00Z',
                  seed='fixed',full_rehash=True)
    assert result['valid'] and result['full_rehash'] is True
    assert result['listed']==32 and result['checked']==30 and result['accepted_records']==30
    assert pdf_gz_key not in store.reads and pdf_copy_key not in store.reads
    emitted=[json.loads(line) for line in Path(result['records']).read_text().splitlines()]
    assert len(emitted)==30 and all(row['sha256_verified'] is True and row['stored_sha256'] for row in emitted)

    all_history=tmp_path/'all-verification.jsonl.gz'
    with gzip.open(all_history,'wt') as out:
        for row in prior+emitted:
            out.write(json.dumps(row)+'\n')
    store2=Store(values)
    second=verify(store2,captures=captures,receipts=receipts,
                  previous=[dict(key='provenance/verification/all.jsonl',path=str(all_history))],
                  engine=engine(),work=tmp_path/'rehash-2',checked_at='2026-10-28T00:00:00Z',
                  seed='fixed',full_rehash=True)
    assert second['valid'] and second['checked']==0 and second['accepted_records']==0
    assert store2.reads==[]


def test_d1_captures_schema_with_stored_suffix_and_binary_digests(tmp_path):
    gz_body=b'compressed html body'
    gz_stored=gzip.compress(gz_body,mtime=0)
    bare_body=b'%PDF-1.7\nbare pdf body\n%%EOF\n'
    values={
        key(gz_body,'.gz'):(gz_stored,None),
        key(bare_body,''):(bare_body,None),
    }
    captures=tmp_path/'d1-captures.parquet'
    schema=pa.schema([
        ('sha256',pa.binary(32)),
        ('stored_suffix',pa.string()),
        ('stored_bytes',pa.int64()),
        ('stored_md5',pa.binary(16)),
        ('receipt_key',pa.string()),
        ('receipt_line',pa.int64()),
        ('capture_index',pa.int32()),
    ])
    pq.write_table(pa.Table.from_pylist([
        dict(sha256=hashlib.sha256(gz_body).digest(),stored_suffix='.gz',stored_bytes=len(gz_stored),
             stored_md5=hashlib.md5(gz_stored).digest(),receipt_key='receipts/a/1.jsonl.gz',
             receipt_line=1,capture_index=0),
        dict(sha256=hashlib.sha256(bare_body).digest(),stored_suffix='',stored_bytes=len(bare_body),
             stored_md5=hashlib.md5(bare_body).digest(),receipt_key='receipts/a/1.jsonl.gz',
             receipt_line=2,capture_index=0),
    ],schema=schema),captures)
    aux=tmp_path/'aux';aux.mkdir()
    _,receipts,previous=inputs(aux,[])
    store=Store(values)
    result=verify(store,captures=captures,receipts=receipts,previous=previous,
                  engine=engine(),work=tmp_path/'d1-job',checked_at='2026-10-27T00:00:00Z',seed='fixed')
    assert result['valid'] and result['listed']==2 and result['missing']==0 and result['orphans']==0
    assert result['mismatches']==0
