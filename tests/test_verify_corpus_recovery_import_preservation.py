"""Prove the audit rejects state drift and missing appended capture evidence."""
import gzip
import hashlib
import json
from pathlib import Path
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from verify_corpus_recovery_import_preservation import verify


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
