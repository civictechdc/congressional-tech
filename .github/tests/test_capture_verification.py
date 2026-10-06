"""Verify checkpoint/receipt/body/metadata seams using only an injected store."""
from copy import deepcopy
import gzip
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.models.content import RawContent
from congress_api.retention.capture_metadata import MetadataWriter, PREFIX
from congress_api.retention.catalog_cache import capture_digest
from congress_api.retention.raw_archive import Archive, CAPTURE_SCHEMA, encode_table


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/verify-capture-run.py'
SPEC = importlib.util.spec_from_file_location('capture_verifier', SCRIPT)
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)
RUN = '20261006T010203Z-0123456789ab'


class MemoryStore:
    def __init__(self):
        self.objects = {'indexes/captures.parquet': encode_table(pa.Table.from_pylist([], schema=CAPTURE_SCHEMA))}
        self.writes = []
        self.reads = []

    def read(self, key):
        self.reads.append(key)
        return self.objects.get(key)

    def keys(self, prefix):
        return sorted(key for key in self.objects if key.startswith(prefix))

    def put(self, key, data, *, immutable=False):
        if immutable and key in self.objects:
            assert self.objects[key] == data
        self.objects[key] = data
        self.writes.append(key)


def response(url, data=None, *, error=None):
    result = dict(requested_url=url, url=url, retrieved_at='2026-10-06T01:02:03+00:00',
                  transport='direct', complete=error is None, http_status=200, error=error)
    if data is not None:
        result['content'] = RawContent.from_bytes(data, 'text/plain').source_dict()
    return result


@pytest.fixture
def checkpoint():
    store = MemoryStore()
    archive = Archive(store, RUN)
    url = 'https://example.gov/retried.txt'
    archive.record(response(url, b'partial', error='timeout'), outcome='timeout', links=[])
    archive.record(response(url, b'complete'), outcome='saved', links=[])
    archive.record(response('https://example.gov/failure.txt', error='connection_error'),
                   outcome='request_failed', links=[])
    archive.seed({'url': 'https://example.gov/next.txt'})
    archive.save()
    body_key = archive.state[url]['body_key']
    with MetadataWriter(store, RUN, max_rows=1) as writer:
        writer.append(dict(body_key=body_key, parser_fingerprint='reader', status='completed'))
    summary = dict(mode='capture', acquisition_status='completed', run_id=RUN,
                   attempted=3, timeout=1, saved=1, request_failed=1,
                   accounting=dict(capture_tasks_completed=3, known_urls=3, urls_by_source_family={'external/provider-responses': 3},
                                   url_outcomes={'saved': 1, 'request_failed': 1, 'pending': 1}),
                   body_metadata={'completed': 1, 'reused': 0})
    store.reads.clear()
    return store, summary


def rehash_checkpoint(store):
    captures = pq.read_table(pa.BufferReader(store.objects['indexes/captures.parquet']))
    state = pq.read_table(pa.BufferReader(store.objects['indexes/download-state.parquet']))
    metadata = dict(state.schema.metadata or {})
    metadata[b'capture_digest'] = capture_digest(captures).encode()
    store.objects['indexes/download-state.parquet'] = encode_table(state.replace_schema_metadata(metadata))


def test_completed_run_matches_latest_receipt_without_any_storage_writes(checkpoint):
    store, summary = checkpoint
    before = dict(store.objects)
    writes = list(store.writes)
    result = verifier.verify_run(store, summary)
    assert result['verified']
    assert result['receipts'] == 3 and result['latest_urls'] == 2
    assert result['outcomes'] == {'timeout': 1, 'saved': 1, 'request_failed': 1}
    assert result['pending_urls'] == 1 and result['known_urls'] == 3
    assert result['capture_references'] == 3  # Includes the no-body failed receipt.
    assert result['unique_bodies_verified'] == 2
    assert result['metadata_rows'] == result['metadata_parts'] == 1
    assert result['metadata_statuses'] == {'completed': 1}
    assert store.objects == before and store.writes == writes
    assert store.reads.count('indexes/captures.parquet') == 1


@pytest.mark.parametrize('damage', ['incomplete', 'mode', 'run_id', 'run_date', 'count', 'family'])
def test_invalid_summary_is_rejected_before_reads(checkpoint, damage):
    store, original = checkpoint
    summary = deepcopy(original)
    if damage == 'incomplete': summary['acquisition_status'] = 'failed'
    elif damage == 'mode': summary['mode'] = 'update'
    elif damage == 'run_id': summary['run_id'] = '../receipt'
    elif damage == 'run_date': summary['run_id'] = '20261306T010203Z-0123456789ab'
    elif damage == 'count': summary['attempted'] = True
    else: summary['accounting']['urls_by_source_family'] = {'../../other': 1}
    with pytest.raises(verifier.VerificationError):
        verifier.verify_run(store, summary)
    assert store.reads == []


def test_complete_checkpoint_digest_is_checked_including_other_runs(checkpoint):
    store, summary = checkpoint
    table = pq.read_table(pa.BufferReader(store.objects['indexes/captures.parquet']))
    rows = table.to_pylist()
    rows.append({**rows[0], 'source_file': 'ci/older-run'})
    store.objects['indexes/captures.parquet'] = encode_table(pa.Table.from_pylist(rows, schema=CAPTURE_SCHEMA))
    state = pq.read_table(pa.BufferReader(store.objects['indexes/download-state.parquet']))
    metadata = dict(state.schema.metadata)
    metadata[b'capture_rows'] = str(len(rows)).encode()  # Only the full digest can detect this.
    store.objects['indexes/download-state.parquet'] = encode_table(state.replace_schema_metadata(metadata))
    with pytest.raises(verifier.VerificationError, match='checkpoint digest'):
        verifier.verify_run(store, summary)


def test_expected_attempt_count_must_include_all_run_receipts(checkpoint):
    store, summary = checkpoint
    summary['attempted'] = summary['accounting']['capture_tasks_completed'] = 4
    with pytest.raises(verifier.VerificationError, match='Expected attempt count mismatch'):
        verifier.verify_run(store, summary)


def test_latest_state_not_an_older_same_url_receipt_is_required(checkpoint):
    store, summary = checkpoint
    table = pq.read_table(pa.BufferReader(store.objects['indexes/download-state.parquet']))
    rows = table.to_pylist()
    rows[0]['outcome'] = 'timeout'
    store.objects['indexes/download-state.parquet'] = encode_table(
        pa.Table.from_pylist(rows, schema=table.schema))
    with pytest.raises(verifier.VerificationError, match='Saved-state outcome accounting|latest run receipt'):
        verifier.verify_run(store, summary)


def test_sample_checks_stored_body_hash(checkpoint):
    store, summary = checkpoint
    key = next(key for key in store.objects if key.startswith('bodies/'))
    store.objects[key] = gzip.compress(b'corrupted', mtime=0)
    with pytest.raises(verifier.VerificationError, match='Stored body hash/length'):
        verifier.verify_run(store, summary)


def test_receipt_index_body_correspondence_is_checked(checkpoint):
    store, summary = checkpoint
    table = pq.read_table(pa.BufferReader(store.objects['indexes/captures.parquet']))
    rows = table.to_pylist()
    rows[0]['sha256'] = '0' * 64
    store.objects['indexes/captures.parquet'] = encode_table(pa.Table.from_pylist(rows, schema=CAPTURE_SCHEMA))
    rehash_checkpoint(store)
    with pytest.raises(verifier.VerificationError, match='body correspondence'):
        verifier.verify_run(store, summary)


@pytest.mark.parametrize('damage', ['hash', 'status', 'body'])
def test_every_metadata_part_is_verified(checkpoint, damage):
    store, summary = checkpoint
    key = next(key for key in store.objects if key.startswith(PREFIX))
    if damage == 'hash':
        store.objects[key] += b'corrupt'
        expected = 'Metadata part hash mismatch'
    else:
        table = pq.read_table(pa.BufferReader(store.objects[key]))
        rows = table.to_pylist()
        if damage == 'status': rows[0]['status'] = 'failed'
        else: rows[0]['body_key'] = 'bodies/outside-run.gz'
        payload = encode_table(pa.Table.from_pylist(rows, schema=table.schema))
        del store.objects[key]
        store.objects[key.rsplit('-', 1)[0] + '-' + sha256(payload).hexdigest() + '.parquet'] = payload
        expected = 'Metadata status/count mismatch' if damage == 'status' else 'outside this run'
    with pytest.raises(verifier.VerificationError, match=expected):
        verifier.verify_run(store, summary)


def test_body_sample_is_deterministic_and_includes_largest_and_failed():
    store = MemoryStore()
    archive = Archive(store, RUN)
    keys = []
    failed = set()
    largest = set()
    for number in range(280):
        # Last ten bodies are uniquely largest; last thirty are failed captures.
        data = str(number).encode() + b'x' * (number + 1)
        is_failed = number >= 250
        url = f'https://example.gov/{number}.txt'
        archive.record(response(url, data, error='timeout' if is_failed else None),
                       outcome='timeout' if is_failed else 'saved', links=[])
        key = archive.state[url]['body_key']
        keys.append(key)
        if is_failed: failed.add(key)
        if number >= 270: largest.add(key)
    archive.save()
    summary = dict(mode='capture', acquisition_status='completed', run_id=RUN,
                   attempted=280, timeout=30, saved=250,
                   accounting=dict(capture_tasks_completed=280, known_urls=280, urls_by_source_family={'external/provider-responses': 280},
                                   url_outcomes={'saved': 250, 'timeout': 30}),
                   body_metadata={'reused': 250})
    result = verifier.verify_run(store, summary)
    selected = set(result['verified_body_keys'])
    hashed = sorted(keys, key=lambda key: sha256(key.encode()).hexdigest())[:200]
    failed_sample = sorted(failed, key=lambda key: sha256(key.encode()).hexdigest())[:25]
    assert selected == set(hashed) | largest | set(failed_sample)
    assert len(selected) < 280
    assert result['unique_bodies_retained'] == 280
    # Hash selection stays independent of storage/list order.
    store.objects = dict(reversed(list(store.objects.items())))
    assert verifier.verify_run(store, summary)['verified_body_keys'] == result['verified_body_keys']


@pytest.mark.parametrize('damage', ['pending', 'known_urls', 'families'])
def test_saved_state_accounting_must_match_actual_checkpoint(checkpoint, damage):
    store, summary = checkpoint
    if damage == 'pending': summary['accounting']['url_outcomes']['pending'] += 1
    elif damage == 'known_urls': summary['accounting']['known_urls'] += 1
    else: summary['accounting']['urls_by_source_family']['external/provider-responses'] += 1
    with pytest.raises(verifier.VerificationError, match='Saved-state .* accounting mismatch'):
        verifier.verify_run(store, summary)


def test_sample_checks_raw_hash_even_when_stored_facts_agree(checkpoint):
    store, summary = checkpoint
    key = next(key for key in store.objects if key.startswith('bodies/'))
    payload = gzip.compress(b'changed', mtime=0)
    store.objects[key] = payload
    facts = dict(stored_sha256=sha256(payload).hexdigest(), stored_bytes=len(payload))
    table = pq.read_table(pa.BufferReader(store.objects['indexes/captures.parquet']))
    rows = table.to_pylist()
    for row in rows:
        if row['body_key'] == key: row.update(facts)
    store.objects['indexes/captures.parquet'] = encode_table(pa.Table.from_pylist(rows, schema=CAPTURE_SCHEMA))
    for receipt_key in list(store.objects):
        if receipt_key.startswith('receipts/'):
            receipts = [json.loads(line) for line in gzip.decompress(store.objects[receipt_key]).splitlines()]
            for receipt in receipts:
                for cap in receipt['captures']:
                    if cap['body_key'] == key: cap.update(facts)
            store.objects[receipt_key] = gzip.compress(
                ''.join(json.dumps(receipt) + '\n' for receipt in receipts).encode(), mtime=0)
    rehash_checkpoint(store)
    with pytest.raises(verifier.VerificationError, match='Raw body hash/length'):
        verifier.verify_run(store, summary)
