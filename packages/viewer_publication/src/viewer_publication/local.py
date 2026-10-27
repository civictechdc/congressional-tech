"""Local recovery authority: synced events, with disposable phase checkpoints.

No remote journal or artifact service participates in this deliberately local
route. A partial event is a refusal; it is never silently truncated or retried.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from congress_shared.custody import canonical_json_bytes

from . import continuation as state

MAX_LOCAL_EVENTS = state.MAX_EVENTS + state.MAX_PHASES + 2
MAX_LOCAL_JOURNAL_BYTES = state.MAX_JOURNAL_BYTES + 2 * state.MAX_STATE_BYTES
MAX_LOCAL_RECORD_BYTES = state.MAX_STATE_BYTES + 1024


def encoded(value):
    return canonical_json_bytes(value, ensure_ascii=True)


class LegacyLocalJournal(ValueError):
    """An older informational journal does not own recovery state."""


def read_local_journal(path):
    """Validate a bounded local history without modifying files or granting proof."""
    sequence, previous, total_bytes = 0, None, 0
    value = None
    with Path(path).open('rb') as stream:
        while raw := stream.readline(MAX_LOCAL_RECORD_BYTES + 1):
            if (len(raw) > MAX_LOCAL_RECORD_BYTES or not raw.endswith(b'\n')
                    or sequence >= MAX_LOCAL_EVENTS or total_bytes + len(raw) > MAX_LOCAL_JOURNAL_BYTES):
                raise ValueError('Incomplete or oversized local publication journal')
            record = json.loads(raw)
            if sequence == 0 and isinstance(record, dict) and 'sequence' not in record and record.get('event') != 'local_checkpoint':
                raise LegacyLocalJournal('Legacy local journal has no event authority snapshot')
            if (not isinstance(record, dict) or type(record.get('version')) is not int or record['version'] != 1
                    or type(record.get('sequence')) is not int or record['sequence'] != sequence
                    or record.get('previous') != previous):
                raise ValueError('Invalid local publication journal chain')
            event, detail = record.get('event'), record.get('value')
            if event == 'local_checkpoint':
                candidate = state.validate_state(detail)
                if len(encoded(candidate)) + 1 > state.MAX_STATE_BYTES:
                    raise ValueError('Publication continuation exceeds state byte limit')
                if value is not None and candidate['binding'] != value['binding']:
                    raise ValueError('Local publication journal binding changed')
                value = candidate
            else:
                if value is None or len(raw) > state.MAX_EVENT_BYTES:
                    raise ValueError('Invalid local publication journal event')
                # Replay into unpublished state without copying the full ledger.
                changed = state.apply_event(value, event, detail)
                if changed and event == 'publication_write_verified' and detail['key'] in value['versions']:
                    value['versions'][detail['key']] = detail['etag']
            sequence += 1
            total_bytes += len(raw)
            previous = hashlib.sha256(raw).hexdigest()
    if value is None:
        raise ValueError('Missing local publication journal checkpoint')
    state_bytes = len(encoded(state.validate_state(value))) + 1
    if state_bytes > state.MAX_STATE_BYTES:
        raise ValueError('Publication continuation exceeds state byte limit')
    return value, dict(events=sequence, bytes=total_bytes, previous=previous, state_bytes=state_bytes)

class LocalContinuation(state.Continuation):
    """events.jsonl owns recovery; continuation.json is a derived checkpoint."""
    def __init__(self, root, binding, *, resume=False):
        self.sequence = 0
        self.previous = None
        self.total_bytes = 0
        self._failed = False
        super().__init__(root, binding, resume=resume)

    @property
    def journal_path(self):
        return self.root / 'events.jsonl'

    def _append(self, event, value):
        if self._failed:
            raise ValueError('Local publication journal requires explicit resume')
        record = dict(version=1, sequence=self.sequence, previous=self.previous,
                      at=datetime.now(timezone.utc).isoformat(), event=event, value=value)
        raw = encoded(record) + b'\n'
        limit = MAX_LOCAL_RECORD_BYTES if event == 'local_checkpoint' else state.MAX_EVENT_BYTES
        if len(raw) > limit or self.sequence >= MAX_LOCAL_EVENTS or self.total_bytes + len(raw) > MAX_LOCAL_JOURNAL_BYTES:
            raise ValueError('Local publication journal exceeds limit')
        try:
            with self.journal_path.open('ab') as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            if self.sequence == 0:
                descriptor = os.open(self.root, os.O_RDONLY)
                try: os.fsync(descriptor)
                finally: os.close(descriptor)
        except BaseException:
            self._failed = True
            raise
        self.sequence += 1
        self.total_bytes += len(raw)
        self.previous = hashlib.sha256(raw).hexdigest()

    def _restore(self):
        value, receipt = read_local_journal(self.journal_path)
        self.sequence, self.previous = receipt['events'], receipt['previous']
        self.total_bytes, self._state_bytes = receipt['bytes'], receipt['state_bytes']
        return value

    def flush(self):
        with self.lock:
            state.validate_state(self.value)
            size = len(encoded(self.value)) + 1
            if size > state.MAX_STATE_BYTES:
                raise ValueError('Publication continuation exceeds state byte limit')
            self._append('local_checkpoint', self.value)
            self._state_bytes = size
            super().flush()

    def record(self, event, value):
        with self.lock:
            if event == 'local_checkpoint':
                raise ValueError('Reserved local publication event')
            change, size = self.checked_event(event, value)
            self._append(event, value)
            if change is not None:
                key, write = change
                if write is not None:
                    self.value['writes'][key] = write
                else:
                    del self.value['writes'][key]
                # Guards share this map; never expose an empty intermediate map.
                if event == 'publication_write_verified' and key in self.value['versions']:
                    self.value['versions'][key] = value['etag']
            self._state_bytes = size
