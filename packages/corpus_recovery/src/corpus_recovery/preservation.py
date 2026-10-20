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


def _evidence(destination):
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
    return payloads, complete, events, verified


def verify_legacy(destination):
    payloads, complete, events, verified = _evidence(destination)
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


def _read_raw(path):
    with path.open('rb') as source:
        raw = source.read((1 << 20) + 1)
    if len(raw) > 1 << 20:
        raise ValueError('Raw preservation selector exceeds the byte budget')
    return raw


def _capture_prefix(pages, old, new):
    if old is None:
        return
    while new is not None:
        if new == old:
            return
        page = pages._read(new)
        if new['first_order'] == old['first_order']:
            prior = pages._read(old)
            if (page['previous'] == prior['previous']
                    and page['batches'][:len(prior['batches'])] == prior['batches']):
                return
            break
        if new['first_order'] < old['first_order']:
            break
        new = page['previous']
    raise ValueError('Existing capture batch references changed')


def _unchanged_routes(routes, old, new, allowed, prefix=''):
    if old == new or prefix in allowed:
        return
    if not any(value.startswith(prefix) for value in allowed):
        raise ValueError('Unrelated download-state routing changed')
    before = routes._read(old, prefix) if old is not None else None
    after = routes._read(new, prefix) if new is not None else None
    if any(page is not None and 'children' not in page for page in (before, after)):
        raise ValueError('Unexpected download-state routing change')
    children_old = before['children'] if before else {}
    children_new = after['children'] if after else {}
    for char in set(children_old) | set(children_new):
        _unchanged_routes(routes, children_old.get(char), children_new.get(char), allowed, prefix + char)


def _state_scope(routes, root, target):
    def walk(reference, prefix):
        if reference is None:
            return
        page = routes._read(reference, prefix)
        if 'value' in page:
            if not prefix.startswith(target):
                raise ValueError('Selected state scope no longer has its original route')
            yield page['value']
        elif target.startswith(prefix) and len(prefix) < len(target):
            char = target[len(prefix)]
            yield from walk(page['children'].get(char), prefix + char)
        else:
            for char, child in page['children'].items():
                yield from walk(child, prefix + char)
    yield from walk(root, '')


def verify(destination, *, raw_storage):
    """Check saved exact native selections, reading only affected native leaves."""
    from congress_api.retention.raw_storage import RawSnapshot, RAW_KEY, state_key
    payloads, complete, events, verified = _evidence(destination)
    before_raw = _read_raw(payloads / 'baseline' / RAW_KEY)
    after_raw = _read_raw(payloads / RAW_KEY)
    if hashlib.sha256(after_raw).hexdigest() != complete.get('raw_identity'):
        raise ValueError('Completed raw selector identity differs from saved payload')
    before = RawSnapshot(raw_storage, json.loads(before_raw), None)
    after = RawSnapshot(raw_storage, json.loads(after_raw), None)
    if any(snapshot.manifest['basis'] != raw_storage.basis for snapshot in (before, after)):
        raise ValueError('Preservation raw schema or routing basis changed')
    delivery = after.completed_delivery(complete['operation'])
    if delivery is None or dict(delivery['result'], already_applied=complete['already_applied'],
                                raw_identity=after.identity) != complete:
        raise ValueError('Import completion differs from selected delivery evidence')
    if complete['already_applied']:
        if before.identity != after.identity:
            raise ValueError('Completed delivery reuse changed the selected raw archive')
        first, end = delivery['first_order'], delivery['first_order'] + delivery['capture_rows']
        entries = [entry for entry in after.owner.capture_pages.entries_since(after.manifest['captures']['head'], first)
                   if entry['first_order'] < end]
        changes = []
    else:
        changes = list(after.changes_since(before.identity))
        if (len(changes) != 1 or changes[0]['capture_start'] != before.manifest['captures']['rows']
                or changes[0]['capture_end'] != after.manifest['captures']['rows']
                or changes[0]['capture_head'] != after.manifest['captures']['head']
                or changes[0]['old_state_root'] != before.manifest['state']['root']
                or changes[0]['new_state_root'] != after.manifest['state']['root']):
            raise ValueError('Raw import does not extend its exact captured baseline')
        _capture_prefix(raw_storage.capture_pages, before.manifest['captures']['head'], after.manifest['captures']['head'])
        entries = list(after.changed_capture_batches(changes[0]))
    captures = [row for entry in entries for row in after.capture_batch(entry).to_pylist()]
    if len(captures) != complete['added_capture_rows']:
        raise ValueError('Receipt and native capture coverage differ')
    keys = sorted({row['receipt_key'] for row in captures})
    expected, receipt_states, receipt_count = Counter(), {}, 0
    fields = ('body_key', 'sha256', 'context_url', 'stored_sha256', 'stored_bytes')
    for key in keys:
        path = payloads / key
        if path.exists():
            if key not in verified:
                raise ValueError('Receipt lacks verified write evidence')
            raw = path.read_bytes()
        elif complete['already_applied'] and after.has_receipt(key):
            raw = raw_storage.store.read(key)
        else:
            raise ValueError('Missing saved recovery receipt')
        for line, text in enumerate(gzip.decompress(raw).splitlines(), 1):
            receipt = json.loads(text)
            receipt_count += 1
            url = receipt['record']['url']
            normalized = pa.Table.from_pylist([receipt['download_state']], schema=raw_storage.state_schema).to_pylist()[0]
            if url in receipt_states and receipt_states[url] != normalized:
                raise ValueError('Receipt state differs from preserved state')
            receipt_states[url] = normalized
            for cap in receipt['captures']:
                expected[(key, line, json.dumps(cap['pointer']), *(cap[f] for f in fields))] += 1
    seen = Counter((row['receipt_key'], row['receipt_line'], row['pointer_json'], *(row[f] for f in fields))
                   for row in captures)
    if seen != expected or receipt_count != complete['receipt_records']:
        raise ValueError('Receipt captures do not exactly match native delivery rows')
    if after.states_for(receipt_states) != receipt_states:
        raise ValueError('Receipt state differs from preserved state')
    if not complete['already_applied']:
        changed_urls = list(after.changed_state_urls(changes[0]))
        scopes = {}
        for url in changed_urls:
            prefix, reference = raw_storage.state_routes.lookup(before.manifest['state']['root'], state_key(url))
            scopes[prefix] = reference
        _unchanged_routes(raw_storage.state_routes, before.manifest['state']['root'],
                          after.manifest['state']['root'], set(scopes))
        added = 0
        for prefix, reference in scopes.items():
            original = (raw_storage._read_states(reference) if reference else
                        pa.Table.from_pylist([], schema=raw_storage.state_native_schema))
            parts = [raw_storage._read_states(value) for value in
                     _state_scope(raw_storage.state_routes, after.manifest['state']['root'], prefix)]
            final = pa.concat_tables(parts) if parts else original.slice(0, 0)
            old = {row['url']: row for row in original.to_pylist()}
            new = {row['url']: row for row in final.to_pylist()}
            if len(new) != len(final) or any(new.get(url) != row for url, row in old.items()):
                raise ValueError('Existing download state changed')
            for url in set(new) - set(old):
                row = new[url]
                if (url not in changed_urls or row['outcome'] != 'pending'
                        or row['body_key'] is not None or row['attempts'] != 0):
                    raise ValueError('New state incorrectly claims a live download')
                added += 1
        if (added != complete['new_pending_states']
                or after.manifest['state']['rows'] - before.manifest['state']['rows'] != added
                or before.manifest['state']['rows'] != complete['existing_download_states_preserved']):
            raise ValueError('State counts disagree with import result')
    return dict(local_preservation_verified=True, previous_capture_rows=delivery['first_order'],
                added_capture_rows=len(captures), existing_states_preserved=complete['existing_download_states_preserved'],
                new_pending_states=complete['new_pending_states'], receipt_records=receipt_count,
                already_applied=complete['already_applied'], raw_identity=after.identity,
                verification_scope='exact delivery captures, affected state leaves and unchanged immutable references',
                physical_exit_verified=False, fresh_remote_readback_verified=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--legacy', action='store_true', help='Audit explicit pre-adoption Parquet evidence.')
    parser.add_argument('--native-config', type=Path)
    parser.add_argument('--r2-config', type=Path)
    args = parser.parse_args(argv)
    if args.legacy:
        result = verify_legacy(args.destination)
    else:
        if args.native_config is None or args.r2_config is None:
            parser.error('--native-config and --r2-config are required for native evidence')
        import configparser
        import boto3
        from botocore.config import Config
        from congress_api.retention.docspec import NativeDatasets
        from congress_api.retention.raw_storage import RawStorage, RAW_KEY
        from congress_api.retention.r2 import R2Store
        configuration = configparser.ConfigParser()
        configuration.read(args.r2_config)
        account = configuration['congressionalraw']
        store = R2Store(boto3.client('s3', endpoint_url=account['endpoint'], region_name='auto',
            aws_access_key_id=account['access_key_id'], aws_secret_access_key=account['secret_access_key'],
            config=Config(retries={'total_max_attempts': 1})), 'congressional-tech-raw')
        owner = RawStorage.from_selection(store, NativeDatasets.from_config(args.native_config),
                                         _read_raw(args.destination / 'payloads' / RAW_KEY))
        result = verify(args.destination, raw_storage=owner)
    print(json.dumps(result, indent=2))
