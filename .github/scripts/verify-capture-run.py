"""Verify a completed capture checkpoint and immutable run evidence without writes."""
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import argparse
import gzip
from hashlib import sha256
import json
import os
from pathlib import Path
import re

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from congress_api.retention.capture_metadata import PREFIX, RESULT_COLUMNS, SCHEMA as METADATA_SCHEMA
from congress_api.retention.catalog_cache import capture_digest_matches
from congress_api.retention.raw_archive import CAPTURE_SCHEMA, STATE_SCHEMA
from congress_api.retention.r2 import R2Store


class VerificationError(ValueError):
    """The saved evidence does not agree with the completed run summary."""


def require(condition, message):
    if not condition:
        raise VerificationError(message)


def validate_summary(summary):
    """Reject incomplete summaries and unsafe run locators before storage reads."""
    require(isinstance(summary, dict), 'Summary must be a JSON object')
    require(summary.get('mode') == 'capture' and summary.get('acquisition_status') == 'completed',
            'Summary must describe a completed capture run')
    run_id = summary.get('run_id')
    require(isinstance(run_id, str) and re.fullmatch(r'\d{8}T\d{6}Z-[0-9a-f]{12}', run_id),
            'Invalid capture run ID')
    try:
        day = datetime.strptime(run_id[:16], '%Y%m%dT%H%M%SZ').date().isoformat()
    except ValueError as exc:
        raise VerificationError('Invalid capture run date') from exc
    accounting = summary.get('accounting')
    require(isinstance(accounting, dict), 'Missing capture accounting')
    for count in (summary.get('attempted'), accounting.get('capture_tasks_completed'), accounting.get('known_urls')):
        require(type(count) is int and count >= 0, 'Invalid expected attempt count')
    require(summary['attempted'] == accounting['capture_tasks_completed'],
            'Expected attempt counts disagree')
    families = accounting.get('urls_by_source_family')
    require(isinstance(families, dict), 'Missing source family accounting')
    require(all(isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*', name)
                for name in families), 'Invalid source family locator')
    state_counts = accounting.get('url_outcomes')
    require(isinstance(state_counts, dict)
            and all(isinstance(key, str) and type(count) is int and count >= 0 for key, count in state_counts.items())
            and all(type(count) is int and count >= 0 for count in families.values()),
            'Invalid saved-state accounting')
    counts = summary.get('body_metadata')
    require(isinstance(counts, dict) and all(type(v) is int and v >= 0 for v in counts.values()),
            'Invalid metadata accounting')
    require(isinstance(summary.get('bucket', 'congressional-tech-raw'), str)
            and bool(summary.get('bucket', 'congressional-tech-raw')), 'Invalid capture bucket')
    return run_id, day


def read_object(store, key):
    value = store.read(key)
    require(value is not None, f'Missing object: {key}')
    return value


def table_object(store, key):
    return pq.read_table(pa.BufferReader(read_object(store, key)))


def verify_run(store, summary):
    """Verify injected read/keys storage; do not acquire sources or mutate storage."""
    run_id, day = validate_summary(summary)
    source = f'ci/{run_id}'
    captures = table_object(store, 'indexes/captures.parquet')
    require(captures.schema.equals(CAPTURE_SCHEMA, check_metadata=False), 'Unexpected capture index schema')
    state_file = pq.ParquetFile(pa.BufferReader(read_object(store, 'indexes/download-state.parquet')))
    require(state_file.schema_arrow.equals(STATE_SCHEMA, check_metadata=False), 'Unexpected state schema')
    checkpoint = state_file.schema_arrow.metadata or {}
    require(checkpoint.get(b'capture_rows') == str(len(captures)).encode(), 'Capture checkpoint row count mismatch')
    require(capture_digest_matches(captures, checkpoint.get(b'capture_digest')),
            'Capture checkpoint digest mismatch')
    rows = captures.filter(pc.equal(captures['source_file'], source)).to_pylist()
    indexed = defaultdict(list)
    for row in rows:
        indexed[(row['receipt_key'], row['receipt_line'])].append(row)
    keys = {row['receipt_key'] for row in rows}
    for family in summary['accounting']['urls_by_source_family']:
        keys.update(store.keys(f'receipts/{family}/{day}/download-{run_id}-'))
    require(all(isinstance(key, str) and f'/{day}/download-{run_id}-' in key for key in keys),
            'Capture index references a different run receipt')
    receipts = []
    located = set()
    for key in sorted(keys):
        for line, data in enumerate(gzip.decompress(read_object(store, key)).splitlines(), 1):
            receipt = json.loads(data)
            require(receipt.get('source_file') == source, 'Receipt belongs to another capture run')
            refs = receipt.get('captures')
            require(isinstance(refs, list), 'Invalid receipt capture references')
            group = indexed.get((key, line), [])
            require(len(group) == max(1, len(refs)), 'Receipt/index capture count mismatch')
            state = receipt['download_state']
            record = receipt['record']
            require(record['outcome'] == state['outcome'], 'Receipt outcome disagreement')
            require(record['requested_url'] == state['url'], 'Receipt URL disagreement')
            require(all(row['context_url'] == state['url'] and row['resolution'] == state['outcome']
                        for row in group), 'Receipt/index state correspondence mismatch')
            expected_refs = Counter((json.dumps(cap.get('pointer', [])), cap.get('body_key'), cap.get('sha256'),
                                     cap.get('bytes'), cap.get('stored_sha256'), cap.get('stored_bytes'))
                                    for cap in refs or [{}])
            actual_refs = Counter((row['pointer_json'], row['body_key'], row['sha256'], row['bytes'],
                                   row['stored_sha256'], row['stored_bytes']) for row in group)
            require(expected_refs == actual_refs, 'Receipt/index body correspondence mismatch')
            located.add((key, line))
            receipts.append(receipt)
    require(set(indexed) == located, 'Capture index contains missing receipt locations')
    require(len(receipts) == summary['attempted'], 'Expected attempt count mismatch')
    outcomes = Counter(receipt['download_state']['outcome'] for receipt in receipts)
    require(all(summary.get(outcome, 0) == count for outcome, count in outcomes.items()),
            'Run outcome count mismatch')
    latest = {}
    fields = ('url', 'outcome', 'body_key', 'checked_at', 'next_attempt_at')
    for receipt in receipts:
        state = receipt['download_state']
        require(isinstance(state.get('checked_at'), str), 'Receipt state lacks checked_at')
        previous = latest.get(state['url'])
        if previous is None or state['checked_at'] > previous['checked_at']:
            latest[state['url']] = state
        elif state['checked_at'] == previous['checked_at']:
            require(all(state.get(field) == previous.get(field) for field in fields),
                    'Ambiguous latest receipt state')
    saved = {}
    state_outcomes, state_families = Counter(), Counter()
    for batch in state_file.iter_batches(batch_size=4096, columns=[*fields, 'family']):
        for state in batch.to_pylist():
            state_outcomes[state['outcome']] += 1
            state_families[state['family'] or 'unknown'] += 1
            if state['url'] in latest:
                require(state['url'] not in saved, 'Duplicate URL in saved state')
                saved[state['url']] = state
    require(dict(state_outcomes) == summary['accounting']['url_outcomes'],
            'Saved-state outcome accounting mismatch')
    require(dict(state_families) == summary['accounting']['urls_by_source_family'],
            'Saved-state family accounting mismatch')
    require(sum(state_outcomes.values()) == summary['accounting']['known_urls'],
            'Saved-state known URL accounting mismatch')
    require(set(saved) == set(latest), 'Run URL missing from saved state')
    require(all(all(saved[url].get(field) == state.get(field) for field in fields)
                for url, state in latest.items()), 'Saved state differs from latest run receipt')
    bodies = {}
    body_fields = ('sha256', 'bytes', 'stored_sha256', 'stored_bytes')
    for row in rows:
        if row['body_key']:
            previous = bodies.get(row['body_key'])
            require(previous is None or all(previous[field] == row[field] for field in body_fields),
                    'Conflicting body facts in capture index')
            bodies[row['body_key']] = row
    stable_hash = lambda key: (sha256(key.encode()).hexdigest(), key)
    sampled = set(sorted(bodies, key=stable_hash)[:200])
    sampled.update(sorted(bodies, key=lambda key: (-bodies[key]['bytes'], key))[:10])
    failed = {cap['body_key'] for receipt in receipts if receipt['record']['outcome'] != 'saved'
              for cap in receipt['captures']}
    sampled.update(sorted(failed, key=stable_hash)[:25])

    def verify_body(key):
        row = bodies[key]
        payload = read_object(store, key)
        require(len(payload) == row['stored_bytes'] and sha256(payload).hexdigest() == row['stored_sha256'],
                f'Stored body hash/length mismatch: {key}')
        data = gzip.decompress(payload)
        require(len(data) == row['bytes'] and sha256(data).hexdigest() == row['sha256'],
                f'Raw body hash/length mismatch: {key}')
        return len(data), len(payload)

    with ThreadPoolExecutor(max_workers=16) as pool:
        sizes = list(pool.map(verify_body, sorted(sampled)))
    parts = sorted(store.keys(f'{PREFIX}{run_id}/'))
    statuses = Counter()
    metadata_rows = 0
    for key in parts:
        require(re.fullmatch(r'\d{6}-[0-9a-f]{64}\.parquet', key.rsplit('/', 1)[-1]),
                'Invalid metadata part locator')
        payload = read_object(store, key)
        require(sha256(payload).hexdigest() == key.rsplit('-', 1)[-1].removesuffix('.parquet'),
                'Metadata part hash mismatch')
        file = pq.ParquetFile(pa.BufferReader(payload))
        schema = file.schema_arrow
        require((schema.metadata or {}).get(b'format_version') == METADATA_SCHEMA.metadata[b'format_version']
                and set(RESULT_COLUMNS) <= set(schema.names)
                and all(field.type == (pa.string() if field.name in RESULT_COLUMNS else pa.list_(pa.string()))
                        for field in schema), 'Unexpected metadata part schema')
        for batch in file.iter_batches(batch_size=256):
            for fact in batch.to_pylist():
                require(fact['body_key'] in bodies, 'Metadata refers to a body outside this run')
                statuses[fact['status']] += 1
                metadata_rows += 1
    expected_statuses = {status: count for status, count in summary['body_metadata'].items()
                         if status != 'reused' and count}
    require(dict(statuses) == expected_statuses, 'Metadata status/count mismatch')
    return dict(run_id=run_id, receipts=len(receipts), receipt_batches=len(keys), capture_references=len(rows),
                outcomes=dict(outcomes), latest_urls=len(latest), state_outcomes=dict(state_outcomes),
                pending_urls=state_outcomes['pending'], known_urls=sum(state_outcomes.values()),
                unique_bodies_retained=len(bodies),
                unique_bodies_verified=len(sampled), verified_body_keys=sorted(sampled),
                verified_raw_bytes=sum(size[0] for size in sizes), verified_stored_bytes=sum(size[1] for size in sizes),
                body_verification_scope='200 stable-hash-selected bodies plus 10 largest plus 25 failed; not every body',
                metadata_rows=metadata_rows, metadata_parts=len(parts), metadata_statuses=dict(statuses),
                state_matches_receipts=True, capture_index_checkpoint_matches=True, verified=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--summary', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    summary = json.loads(args.summary.read_text())
    validate_summary(summary)
    names = ('CLOUDFLARE_ACCOUNT_ID', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY')
    if not all(os.environ.get(name) for name in names):
        raise SystemExit(', '.join(names) + ' are required')
    import boto3
    from botocore.config import Config
    client = boto3.client('s3',
        endpoint_url=f'https://{os.environ[names[0]]}.r2.cloudflarestorage.com',
        aws_access_key_id=os.environ[names[1]], aws_secret_access_key=os.environ[names[2]], region_name='auto',
        config=Config(max_pool_connections=16, retries={'mode': 'standard', 'max_attempts': 3},
                      request_checksum_calculation='when_required', response_checksum_validation='when_required'))
    result = verify_run(R2Store(client, summary.get('bucket', 'congressional-tech-raw')), summary)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, separators=(',', ':')))


if __name__ == '__main__':
    main()
