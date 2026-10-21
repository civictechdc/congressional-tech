"""Prove the audit rejects state drift and missing appended capture evidence."""
import gzip
import hashlib
import json
from pathlib import Path
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from corpus_recovery.preservation import verify_legacy as verify


def fixture(root, *, drift=False, missing=False):
    p = root / 'payloads'
    baseline = p / 'baseline/indexes'
    baseline.mkdir(parents=True)
    (p / 'indexes').mkdir()
    old = dict(url='https://example.test/old', outcome='http_error', body_key=None, attempts=2)
    added = dict(url='https://example.test/new', outcome='pending', body_key=None, attempts=0)
    pq.write_table(pa.Table.from_pylist([old]), baseline / 'download-state.parquet')
    changed = dict(old, outcome='saved') if drift else old
    pq.write_table(pa.Table.from_pylist([changed, added]), p / 'indexes/download-state.parquet')
    cap = dict(body_key='bodies/test.gz', sha256='digest', context_url=added['url'],
               stored_sha256='stored', stored_bytes=10, pointer=['body'])
    key = 'receipts/documents/test.jsonl.gz'
    receipt = dict(record=dict(url=added['url']), download_state=added, captures=[cap])
    path = p / key
    path.parent.mkdir(parents=True)
    path.write_bytes(gzip.compress((json.dumps(receipt)+'\n').encode()))
    row = {k:v for k,v in cap.items() if k!='pointer'}
    row.update(receipt_key=key, receipt_line=1, pointer_json=json.dumps(cap['pointer']))
    table = pa.Table.from_pylist([row])
    pq.write_table(table.slice(0, 0), baseline / 'captures.parquet')
    pq.write_table(table.slice(0, 0) if missing else table, p / 'indexes/captures.parquet')
    complete = dict(complete=True, added_capture_rows=1, existing_download_states_preserved=1,new_pending_states=1)
    (p / 'import-complete.json').write_text(json.dumps(complete))
    events=[]
    for key in ['receipts/documents/test.jsonl.gz','indexes/captures.parquet','indexes/download-state.parquet']:
        events.extend([dict(event='write_intent',value=dict(key=key,sha256=hashlib.sha256((p/key).read_bytes()).hexdigest())),dict(event='write_verified',value=dict(key=key))])
    events.append(dict(event='import_complete',value=complete))
    (root / 'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))


def test_preservation(tmp_path):
    fixture(tmp_path)
    result=verify(tmp_path)
    assert result['local_preservation_verified']
    assert not result['fresh_remote_readback_verified']


def test_detects_state_change_even_with_matching_payload_hash(tmp_path):
    fixture(tmp_path, drift=True)
    with pytest.raises(ValueError, match='Existing download state changed'):
        verify(tmp_path)


def test_detects_missing_capture_despite_completion_marker(tmp_path):
    fixture(tmp_path, missing=True)
    with pytest.raises(ValueError, match='coverage differ'):
        verify(tmp_path)


def test_streaming_prefix_checks_cross_different_row_groups(tmp_path):
    from corpus_recovery.preservation import compare_prefix
    rows = pa.table({'value': pa.array([None, 2**64-1, 7, 7] * 2500, type=pa.uint64()),
                     'nested': pa.array([[b'x', None]] * 10000)})
    pq.write_table(rows, tmp_path / 'old.parquet', row_group_size=1001)
    pq.write_table(pa.concat_tables([rows, rows.slice(0, 3)]), tmp_path / 'new.parquet', row_group_size=2222)
    assert compare_prefix(tmp_path / 'old.parquet', tmp_path / 'new.parquet', 'rows') == (10000, 10003)
    pq.write_table(rows.set_column(0, 'value', pa.array([0] * 10000, type=pa.uint64())), tmp_path / 'new.parquet')
    with pytest.raises(ValueError, match='Existing rows changed'):
        compare_prefix(tmp_path / 'old.parquet', tmp_path / 'new.parquet', 'rows')


def test_duplicate_state_urls_fail_even_when_prefix_is_unchanged(tmp_path):
    from corpus_recovery.preservation import unique_state_urls
    for url in ('same', None):
        pq.write_table(pa.table({'url': pa.array([url, url], type=pa.string())}), tmp_path / 'states.parquet')
        with pytest.raises(ValueError, match='Duplicate'):
            unique_state_urls(tmp_path / 'states.parquet')
