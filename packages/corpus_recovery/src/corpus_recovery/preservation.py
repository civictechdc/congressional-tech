"""Read-only audit of completed import payloads and preserved baseline rows.

This checks saved readback evidence. The caller must separately verify actual
process exit and current remote index identities before publication.
"""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

BATCH_ROWS = 4096


def batches(path):
    return pq.ParquetFile(path).iter_batches(batch_size=BATCH_ROWS)


def compare_prefix(old_path, new_path, label):
    """Compare exact values/types/nulls/order across different row-group layouts."""
    old_file, new_file = pq.ParquetFile(old_path), pq.ParquetFile(new_path)
    if (not old_file.schema_arrow.equals(new_file.schema_arrow, check_metadata=False)
            or new_file.metadata.num_rows < old_file.metadata.num_rows):
        raise ValueError(f'Existing {label} changed')
    new_batches = iter(batches(new_path))
    current = None
    position = 0
    for old in batches(old_path):
        offset = 0
        while offset < len(old):
            if current is None or position == len(current):
                current = next(new_batches)
                position = 0
            count = min(len(old) - offset, len(current) - position)
            if not old.slice(offset, count).equals(current.slice(position, count), check_metadata=False):
                raise ValueError(f'Existing {label} changed')
            offset += count
            position += count
    return old_file.metadata.num_rows, new_file.metadata.num_rows


def unique_state_urls(path):
    # Only one Arrow string column enters memory; never materialize baseline rows
    # or a Python set of every URL. Count null as one value, matching dict semantics.
    urls = pq.read_table(path, columns=['url'])['url']
    if pc.count_distinct(urls, mode='all').as_py() != len(urls):
        raise ValueError('Duplicate download-state URLs')


def verify(destination):
    destination = Path(destination)
    payloads = destination / 'payloads'
    complete = json.loads((payloads / 'import-complete.json').read_text())
    events = [json.loads(line) for line in (destination / 'events.jsonl').read_text().splitlines()]
    finishes = [e['value'] for e in events if e['event'] == 'import_complete']
    if not complete.get('complete') or finishes != [complete]:
        raise ValueError('Missing or inconsistent completed import evidence')
    if any(e['event'] == 'failed_requires_reconciliation' for e in events):
        raise ValueError('Import requires reconciliation')
    intents = {e['value']['key']: e['value']['sha256'] for e in events if e['event'] == 'write_intent'}
    verified = Counter(e['value']['key'] for e in events if e['event'] == 'write_verified')
    if set(intents) != set(verified) or any(n != 1 for n in verified.values()):
        raise ValueError('Incomplete or repeated write readback evidence')
    for key, expected in intents.items():
        path = payloads / key
        if path.exists():
            with path.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                    raise ValueError(f'Changed proposed payload: {key}')
    old_capture_count, capture_count = compare_prefix(
        payloads / 'baseline/indexes/captures.parquet', payloads / 'indexes/captures.parquet', 'capture rows')
    old_state_path = payloads / 'baseline/indexes/download-state.parquet'
    state_path = payloads / 'indexes/download-state.parquet'
    old_count, new_count = compare_prefix(old_state_path, state_path, 'download state')
    unique_state_urls(old_state_path)
    unique_state_urls(state_path)
    expected = Counter()
    receipt_states = {}
    receipt_count = 0
    fields = ('body_key', 'sha256', 'context_url', 'stored_sha256', 'stored_bytes')
    for path in sorted((payloads / 'receipts').rglob('*.jsonl.gz')):
        key = path.relative_to(payloads).as_posix()
        if key not in verified:
            raise ValueError('Receipt lacks verified write evidence')
        with gzip.open(path, 'rt') as stream:
            for line, text in enumerate(stream, 1):
                receipt = json.loads(text)
                receipt_count += 1
                url = receipt['record']['url']
                if url in receipt_states and receipt_states[url] != receipt['download_state']:
                    raise ValueError('Receipt state differs from preserved state')
                receipt_states[url] = receipt['download_state']
                for cap in receipt['captures']:
                    expected[(key, line, json.dumps(cap['pointer']), *(cap[f] for f in fields))] += 1
    if capture_count - old_capture_count != sum(expected.values()) or capture_count - old_capture_count != complete['added_capture_rows']:
        raise ValueError('Receipt and index coverage differ')
    requested = pa.array(list(receipt_states), type=pq.ParquetFile(state_path).schema_arrow.field('url').type)
    found = set()
    position = 0
    for batch in batches(state_path):
        selected = batch.filter(pc.is_in(batch.column('url'), value_set=requested))
        for row in selected.to_pylist():
            if row != receipt_states[row['url']]:
                raise ValueError('Receipt state differs from preserved state')
            found.add(row['url'])
        # New rows occupy only the appended suffix; baseline bytes remain intact.
        for row in batch.slice(max(0, old_count-position)).to_pylist():
            if row['outcome'] != 'pending' or row['body_key'] is not None or row['attempts'] != 0:
                raise ValueError('New state incorrectly claims a live download')
        position += len(batch)
    if found != set(receipt_states):
        raise ValueError('Receipt state differs from preserved state')
    seen = Counter()
    position = 0
    for batch in batches(payloads / 'indexes/captures.parquet'):
        for cap in batch.slice(max(0, old_capture_count-position)).to_pylist():
            seen[(cap['receipt_key'], cap['receipt_line'], cap['pointer_json'], *(cap[f] for f in fields))] += 1
        position += len(batch)
    if seen != expected:
        raise ValueError('Receipt captures do not exactly match appended index rows')
    if old_count != complete['existing_download_states_preserved'] or new_count-old_count != complete['new_pending_states']:
        raise ValueError('State counts disagree with import result')
    return dict(local_preservation_verified=True, previous_capture_rows=old_capture_count,
                added_capture_rows=capture_count-old_capture_count, existing_states_preserved=old_count,
                new_pending_states=new_count-old_count, receipt_records=receipt_count,
                physical_exit_verified=False, fresh_remote_readback_verified=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    print(json.dumps(verify(parser.parse_args(argv).destination), indent=2))
