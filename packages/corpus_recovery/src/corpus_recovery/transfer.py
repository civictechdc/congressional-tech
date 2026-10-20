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
from congress_api.retention.immutable_metadata import encoded
from congress_api.retention.raw_storage import RawStorage, RawSnapshot, RAW_KEY
from congress_api.retention.raw_archive import (
    CAPTURE_SCHEMA, body_payload,
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


def import_batch(store, *, prepared, body_paths, raw_storage, operation, source_file,
                 receipt_prefix, guard, journal, save_payload, body_readback=None,
                 commit_guard=None, base=None):
    """Retain bodies/receipts, then select native captures and state in one CAS.

    The caller supplies the exact baseline and stable delivery identity. Guards
    precede every application object write, native candidate Run, and final raw
    selector CAS. DocSpec owns its internal object writes and completion.
    """
    commit_guard = commit_guard or guard
    if raw_storage.store is not store:
        raise ValueError('Recovery raw storage belongs to another object store')
    if not isinstance(operation, str) or not operation:
        raise ValueError('A stable recovery operation identity is required')
    current = raw_storage.snapshot()
    base = base or current
    if base.owner is not raw_storage:
        raise ValueError('Recovery baseline belongs to another raw owner')
    if current.version is None:
        raise RuntimeError('Explicit raw archive seed adoption is required before recovery import')
    request_id = hashlib.sha256(encoded([prepared, sorted(body_paths), source_file, receipt_prefix])).hexdigest()
    completed = current.completed_delivery(operation)
    if completed is not None:
        if completed['request_id'] != request_id:
            raise ValueError('Completed recovery operation has a different request')
        result = dict(completed['result'], already_applied=True, raw_identity=current.identity)
        save_payload(RAW_KEY, encoded(current.manifest))
        journal('raw_selection_reused', dict(key=RAW_KEY, sha256=current.identity))
        journal('import_complete', result)
        return result
    if base.version != current.version or base.identity != current.identity:
        raise ValueError('Stale recovery raw selection')

    class GuardedStore:
        def __getattr__(self, name):
            return getattr(store, name)

        def put(self, key, payload, *, immutable=False):
            save_payload(key, payload)
            return checked_put(store, key, payload, immutable=immutable,
                               guard=guard, journal=journal)

        def put_index_selector(self, key, payload, *, expected_version):
            save_payload(key, payload)
            commit_guard()
            journal('write_intent', dict(key=key, sha256=hashlib.sha256(payload).hexdigest()))
            reconcile_lost_acknowledgment(
                lambda: store.put_index_selector(key, payload, expected_version=expected_version),
                lambda: store.read(key), payload)
            if store.read(key) != payload:
                raise ValueError('Raw selector readback mismatch')
            journal('write_verified', dict(key=key))

    class GuardedNative:
        def __getattr__(self, name):
            return getattr(raw_storage.native, name)

        def run_table(self, table, **kwargs):
            guard()
            journal('native_candidate_intent', dict(dataset=kwargs['dataset'], rows=len(table)))
            pin = raw_storage.native.run_table(table, **kwargs)
            journal('native_candidate_complete', dict(release=pin))
            return pin

    selected_owner = RawStorage(GuardedStore(), GuardedNative(),
        max_state_rows=raw_storage.max_state_rows, max_state_bytes=raw_storage.max_state_bytes,
        max_capture_rows=raw_storage.max_capture_rows, max_capture_bytes=raw_storage.max_capture_bytes,
        state_schema=raw_storage.state_schema)
    selected_base = RawSnapshot(selected_owner, base.manifest, base.version)
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
    original_states = base.states_for(item['record']['url'] for item in prepared)
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
    if any(states[u] != old for u, old in original_states.items()):
        raise ValueError('Existing download state changed')
    result = dict(complete=True, operation=operation, receipt_records=len(receipts), added_capture_rows=len(additions),
                  distinct_bodies=len(body_info), body_objects_missing_before_put=uploaded,
                  previous_capture_rows=base.manifest['captures']['rows'],
                  capture_rows=base.manifest['captures']['rows'] + len(additions),
                  existing_download_states_preserved=base.manifest['state']['rows'],
                  new_pending_states=len(states.added), already_applied=False,
                  catalog_and_viewer_publication_complete=False)
    candidate = selected_owner.prepare(selected_base, operation=operation,
        captures=pa.Table.from_pylist(additions, schema=CAPTURE_SCHEMA),
        states=pa.Table.from_pylist(list(states.added.values()), schema=raw_storage.state_schema),
        indexed_receipts={row['receipt_key'] for row in additions},
        request_id=request_id, delivery_result=result)
    selected = selected_owner.publish(candidate)
    result['raw_identity'] = selected.identity
    journal('import_complete', result)
    return result
