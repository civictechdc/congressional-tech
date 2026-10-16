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

import pyarrow.parquet as pq


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
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f'Changed proposed payload: {key}')
    old_captures = pq.read_table(payloads / 'baseline/indexes/captures.parquet')
    captures = pq.read_table(payloads / 'indexes/captures.parquet')
    if not captures.slice(0, len(old_captures)).equals(old_captures):
        raise ValueError('Existing capture rows changed')
    old_state = pq.read_table(payloads / 'baseline/indexes/download-state.parquet')
    state = pq.read_table(payloads / 'indexes/download-state.parquet')
    old = {r['url']: r for r in old_state.to_pylist()}
    new = {r['url']: r for r in state.to_pylist()}
    if len(old) != len(old_state) or len(new) != len(state):
        raise ValueError('Duplicate download-state URLs')
    if any(new.get(url) != row for url, row in old.items()):
        raise ValueError('Existing download state changed')
    if any(row['outcome'] != 'pending' or row['body_key'] is not None
           or row['attempts'] != 0 for url, row in new.items() if url not in old):
        raise ValueError('New state incorrectly claims a live download')
    receipts = {}
    for path in sorted((payloads / 'receipts').rglob('*.jsonl.gz')):
        key = path.relative_to(payloads).as_posix()
        if key not in verified:
            raise ValueError('Receipt lacks verified write evidence')
        receipts[key] = [json.loads(line) for line in gzip.decompress(path.read_bytes()).splitlines()]
    additions = captures.slice(len(old_captures)).to_pylist()
    expected_rows = sum(len(r['captures']) for rows in receipts.values() for r in rows)
    if len(additions) != expected_rows or len(additions) != complete['added_capture_rows']:
        raise ValueError('Receipt and index coverage differ')
    seen = Counter()
    expected = Counter()
    fields = ('body_key', 'sha256', 'context_url', 'stored_sha256', 'stored_bytes')
    for key, rows in receipts.items():
        for line, receipt in enumerate(rows, 1):
            if receipt['download_state'] != new[receipt['record']['url']]:
                raise ValueError('Receipt state differs from preserved state')
            for cap in receipt['captures']:
                expected[(key, line, json.dumps(cap['pointer']), *(cap[f] for f in fields))] += 1
    for cap in additions:
        seen[(cap['receipt_key'], cap['receipt_line'], cap['pointer_json'], *(cap[f] for f in fields))] += 1
    if seen != expected:
        raise ValueError('Receipt captures do not exactly match appended index rows')
    if len(old) != complete['existing_download_states_preserved'] or len(new)-len(old) != complete['new_pending_states']:
        raise ValueError('State counts disagree with import result')
    return dict(local_preservation_verified=True, previous_capture_rows=len(old_captures),
                added_capture_rows=len(additions), existing_states_preserved=len(old),
                new_pending_states=len(new)-len(old), receipt_records=sum(map(len, receipts.values())),
                physical_exit_verified=False, fresh_remote_readback_verified=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    print(json.dumps(verify(parser.parse_args().destination), indent=2))
