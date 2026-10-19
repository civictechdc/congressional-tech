"""Import an already sealed batch through an injected, guarded object store.

The caller owns the exclusive lock, fresh baseline, cloud-writer check, input
pins, and one-shot dispatch. Every write calls its guard. This module never
selects a catalog or publishes viewer mappings.
"""
import gzip
import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc

from corpus_recovery.assemble import assemble, index_rows
from corpus_recovery.acknowledge import reconcile_lost_acknowledgment
from corpus_recovery.inventory import head_body, reusable_result
from congress_api.retention.catalog_cache import capture_digest
from congress_api.retention.raw_archive import (
    CAPTURE_SCHEMA, CAPTURES_KEY, STATE_KEY, body_payload, encode_table,
)


def checked_put(store, key, payload, *, immutable, guard, journal):
    """Do not repeat an uncertain PUT; reconcile its exact bytes read-only."""
    guard()
    journal('write_intent', dict(key=key, sha256=hashlib.sha256(payload).hexdigest()))
    remote = None

    def read():
        nonlocal remote
        remote = store.read(key)
        return remote

    reconciled = reconcile_lost_acknowledgment(
        lambda: store.put(key, payload, immutable=immutable), read, payload)
    if reconciled:
        journal('acknowledgment_reconciled', dict(key=key))
    else:
        remote = store.read(key)
    if remote != payload:
        raise ValueError(f'Write readback mismatch: {key}')
    journal('write_verified', dict(key=key))
    return remote


def import_batch(store, *, prepared, body_paths, captures, state, source_file,
                 receipt_prefix, guard, journal, save_payload, body_readback=None,
                 commit_guard=None):
    """Retain bodies and receipts, then conditionally replace the raw index pair.

Use R2Store after reading both indexes to establish conditional versions.
save_payload must durably save each proposed index or receipt before its PUT.
Any failure requires evidence reconciliation, not automatic restart.
body_readback, when supplied, must have its file digest pinned by the caller.
"""
    commit_guard = commit_guard or guard
    if pc.count_distinct(state['url'], mode='all').as_py() != len(state):
        raise ValueError('Duplicate URLs in baseline download state')
    # Reject changed local bytes before the first remote write.
    for key, path in body_paths.items():
        with Path(path).open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if key != f'bodies/sha256/{digest[:2]}/{digest}.gz':
            raise ValueError(f'Local body identity mismatch: {key}')
    body_info = {}
    uploaded = 0
    for key, path in body_paths.items():
        raw = Path(path).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        info = dict(body_key=key, sha256=digest, bytes=len(raw))
        if key != f'bodies/sha256/{digest[:2]}/{digest}.gz':
            raise ValueError('Local body changed during import')
        prior = (body_readback or {}).get('results', {}).get(key, {})
        if reusable_result(key, info, prior):
            current = head_body(store, key)
            if current and (current['ETag'], current['ContentLength']) == (prior['etag'], prior['stored_bytes']):
                info.update(stored_sha256=prior['stored_sha256'], stored_bytes=prior['stored_bytes'])
                body_info[key] = info
                journal('body_verification_reused', dict(key=key, etag=prior['etag'], **info))
                continue
        remote = store.read(key)
        if remote is None:
            payload, info = body_payload(raw)
            remote = checked_put(store, key, payload, immutable=True, guard=guard, journal=journal)
            uploaded += 1
        if gzip.decompress(remote) != raw:
            raise ValueError(f'Retained body conflict: {key}')
        info.update(stored_sha256=hashlib.sha256(remote).hexdigest(), stored_bytes=len(remote))
        body_info[key] = info
    requested_urls = pa.array(list(dict.fromkeys(item['record']['url'] for item in prepared)),
                              type=state.schema.field('url').type)
    selected = state.filter(pc.is_in(state['url'], value_set=requested_urls))
    original_states = {r['url']: r for r in selected.to_pylist()}
    receipts, states = assemble(prepared, original_states, body_info, source_file)
    additions = []
    for offset in range(0, len(receipts), 100):
        batch = receipts[offset:offset + 100]
        key = f'{receipt_prefix}-{offset // 100 + 1:06d}.jsonl.gz'
        payload = gzip.compress((''.join(json.dumps(r, separators=(',', ':')) + '\n'
                                       for r in batch)).encode(), mtime=0)
        save_payload(key, payload)
        checked_put(store, key, payload, immutable=True, guard=guard, journal=journal)
        additions.extend(index_rows(batch, key))
    combined = pa.concat_tables([captures, pa.Table.from_pylist(additions, schema=CAPTURE_SCHEMA)])
    if any(states[u] != old for u, old in original_states.items()):
        raise ValueError('Existing download state changed')
    metadata = dict(state.schema.metadata or {})
    metadata.update({b'capture_rows': str(len(combined)).encode(),
                     b'capture_digest': capture_digest(combined).encode()})
    appended = pa.Table.from_pylist(list(states.added.values()), schema=state.schema)
    newstate = pa.concat_tables([state, appended]).replace_schema_metadata(metadata)
    payloads = {STATE_KEY: encode_table(newstate), CAPTURES_KEY: encode_table(combined)}
    for key, payload in payloads.items():
        save_payload(key, payload)
    for key, payload in payloads.items():
        checked_put(store, key, payload, immutable=False, guard=commit_guard, journal=journal)
    # Recheck the pair after both updates; never report completion for a partial pair.
    commit_guard()
    if any(store.read(key) != payload for key, payload in payloads.items()):
        raise ValueError('Final raw index pair mismatch')
    result = dict(complete=True, receipt_records=len(receipts), added_capture_rows=len(additions),
                  distinct_bodies=len(body_info), body_objects_missing_before_put=uploaded,
                  previous_capture_rows=len(captures), capture_rows=len(combined),
                  existing_download_states_preserved=len(state),
                  new_pending_states=len(states.added),
                  catalog_and_viewer_publication_complete=False)
    journal('import_complete', result)
    return result
