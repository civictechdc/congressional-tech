"""Durable receipts for an explicitly requested publication continuation.

Receipts bind local inputs and accepted phase outputs. Successful upload
acknowledgments are reusable without remote readback. An uncertain request is
never resent until its original outcome has been reconciled.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import threading
import uuid

from congress_shared.custody import VerifiedFile, canonical_json_bytes, write_atomic_bytes


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


# The modeled full 1.24M-document v6 release has roughly 100K assets: hash-routed
# component pages, sorted browse pages, shared physical chunks and inventories.
# Count and byte limits remain independent: unusually long names/values can hit
# a byte limit first. See the capacity fixture and evidence note for sizing.
MAX_PHASE_FILES = 131072
MAX_PHASES = 64
MAX_WRITES = MAX_PHASE_FILES + 256  # Immutable assets plus release/control writes.
MAX_EVENTS = 2 * MAX_WRITES + 2 * MAX_PHASES  # Parallel completion need not coalesce.
MAX_STATE_BYTES = 128 * 1024**2  # Includes the retained ~9.6MB accepted-recovery input.
MAX_EVENT_BYTES = 1024**2
MAX_JOURNAL_BYTES = 256 * 1024**2
JOURNAL_CHECKPOINT_EVENTS = 1024


def bounded_json(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_STATE_BYTES + 1)
    if len(raw) > MAX_STATE_BYTES:
        raise ValueError('Publication continuation exceeds state byte limit')
    return json.loads(raw)


def relative_name(name):
    if (not isinstance(name, str) or not name or len(name) > 2048 or '\\' in name
            or PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts
            or name in ('.', './') or str(PurePosixPath(name)) != name):
        raise ValueError('Invalid publication saved name')
    return name


def write_value(value, *, verified=False):
    if (not isinstance(value, dict) or not isinstance(value.get('key'), str) or not value['key']
            or len(value['key']) > 2048 or type(value.get('bytes')) is not int or value['bytes'] < 0
            or not isinstance(value.get('sha256'), str) or len(value['sha256']) != 64
            or any(c not in '0123456789abcdef' for c in value['sha256'])):
        raise ValueError('Invalid publication write identity')
    if verified:
        if not isinstance(value.get('etag'), str) or not value['etag']:
            raise ValueError('Invalid verified publication ETag')
    elif (value.get('expected_etag') is not None and not isinstance(value['expected_etag'], str)
          or (bool(value.get('expected_etag')) == (value.get('if_none_match') == '*'))
          or value.get('if_none_match') not in (None, '*')):
        raise ValueError('Invalid publication write condition')


def validate_state(value):
    if not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] != 1:
        raise ValueError('Unsupported publication continuation version')
    if (not isinstance(value.get('binding'), dict) or not isinstance(value.get('phases'), dict)
            or not isinstance(value.get('writes'), dict) or not isinstance(value.get('versions'), dict)):
        raise ValueError('Malformed publication continuation fields')
    if len(value['phases']) > MAX_PHASES or len(value['writes']) > MAX_WRITES or len(value['versions']) > MAX_WRITES:
        raise ValueError('Publication continuation exceeds state count limit')
    total_files = 0
    for name, phase in value['phases'].items():
        relative_name(name)
        if not isinstance(phase, dict) or not isinstance(phase.get('files'), dict) or 'result' not in phase:
            raise ValueError('Malformed accepted publication phase')
        total_files += len(phase['files'])
        if total_files > MAX_PHASE_FILES:
            raise ValueError('Publication continuation exceeds phase file limit')
        for name, digest in phase['files'].items():
            relative_name(name)
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                raise ValueError('Invalid accepted phase digest')
    for key, write in value['writes'].items():
        if not isinstance(write, dict) or type(write.get('verified')) is not bool or key != write.get('key'):
            raise ValueError('Malformed publication write state')
        write_value(write)
        if write['verified']:
            write_value(write, verified=True)
    if any(not isinstance(key, str) or (etag is not None and (not isinstance(etag, str) or not etag))
           for key, etag in value['versions'].items()):
        raise ValueError('Malformed protected publication versions')
    return value


def write_transition(state, event, value):
    if not isinstance(event, str) or not event or len(event) > 128 or not isinstance(value, dict):
        raise ValueError('Malformed publication event')
    writes = state['writes']
    if event == 'publication_write_intent':
        write_value(value)
        previous = writes.get(value['key'])
        if previous is not None and (previous.get('verified') or any(previous.get(k) != value.get(k)
                for k in ('bytes', 'sha256', 'expected_etag', 'if_none_match'))):
            raise ValueError('Illegal publication intent transition')
        if previous is None and len(writes) >= MAX_WRITES:
            raise ValueError('Publication continuation exceeds write limit')
        return value['key'], dict(value, verified=False)
    elif event in ('publication_write_refused', 'publication_write_verified'):
        previous = writes.get(value.get('key'))
        if previous is None or previous.get('verified'):
            raise ValueError('Illegal publication write transition')
        if event == 'publication_write_refused':
            return value['key'], None
        else:
            write_value(value, verified=True)
            if any(previous[k] != value[k] for k in ('bytes', 'sha256')):
                raise ValueError('Publication verification differs from intent')
            return value['key'], dict(previous | value, verified=True)
    else:
        return None  # Informational events are legitimate and retain their history.


def apply_event(state, event, value):
    change = write_transition(state, event, value)
    if change is None:
        return False
    key, write = change
    if write is None:
        del state['writes'][key]
    else:
        state['writes'][key] = write
    return True


class Continuation:
    def __init__(self, root, binding, *, resume=False):
        self.root = Path(root)
        self.path = self.root / 'continuation.json'
        self.lock = threading.RLock()
        self._state_bytes = None
        if resume:
            self.value = self._restore()
            if self.value['binding'] != binding:
                raise ValueError('Publication continuation inputs changed')
            self._state_bytes = len(canonical_json_bytes(self.value, ensure_ascii=True)) + 1
            if self._state_bytes > MAX_STATE_BYTES:
                raise ValueError('Publication continuation exceeds state byte limit')
        else:
            self.root.mkdir(parents=True, exist_ok=False)
            self.value = dict(version=1, binding=binding, phases={}, writes={}, versions={})
            self.flush()

    def _restore(self):
        return validate_state(bounded_json(self.path))

    def flush(self):
        with self.lock:
            raw = canonical_json_bytes(self.value, ensure_ascii=True, trailing_newline=True)
            if len(raw) > MAX_STATE_BYTES:
                raise ValueError('Publication continuation exceeds state byte limit')
            write_atomic_bytes(
                self.path,
                raw,
                temp_path=self.path.with_suffix('.tmp'),
                fsync=True,
                fsync_dir=True,
            )
            self._state_bytes = len(raw)

    def save(self, name, raw, *, replace=False):
        path = self.root / relative_name(name)
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise ValueError('Publication saved path escapes attempt directory')
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and not replace:
            if path.read_bytes() != raw:
                raise ValueError('Publication artifact changed: ' + name)
            return
        write_atomic_bytes(
            path,
            raw,
            temp_path=path.with_name(path.name + '.partial'),
            fsync=True,
            fsync_dir=False,
        )

    def phase(self, name, action, *, files, inventory=None):
        relative_name(name)
        saved = self.value['phases'].get(name)
        if saved is not None:
            if inventory is not None:
                proof = inventory()
                from congress_api.retention.viewer_inventory import InventoryValidation
                if not isinstance(proof, InventoryValidation):
                    raise ValueError('Publication phase requires issued inventory proof')
                proof.require(self.root)
                if {relative: item['sha256'] for relative, item in proof.files.items()} != saved['files']:
                    raise ValueError('Accepted publication phase inventory differs: ' + name)
                return saved['result']
            for relative, expected in saved['files'].items():
                path = self.root / relative
                if path.is_symlink() or not path.resolve().is_relative_to(self.root.resolve()):
                    raise ValueError('Accepted publication phase path escapes root')
                if sha256(path) != expected:
                    raise ValueError('Accepted publication phase changed: ' + name)
            return saved['result']
        if len(self.value['phases']) >= MAX_PHASES:
            raise ValueError('Publication continuation exceeds phase count limit')
        result = action()
        if inventory is not None:
            proof = inventory()
            from congress_api.retention.viewer_inventory import InventoryValidation
            if not isinstance(proof, InventoryValidation):
                raise ValueError('Publication phase requires issued inventory proof')
            proof.require(self.root)
            hashes = {relative: item['sha256'] for relative, item in proof.files.items()}
        else:
            hashes = {}
            for path in files():
                if len(hashes) >= MAX_PHASE_FILES:
                    raise ValueError('Publication continuation exceeds phase file limit')
                relative = relative_name(str(path.relative_to(self.root)))
                if path.is_symlink() or not path.resolve().is_relative_to(self.root.resolve()):
                    raise ValueError('Accepted publication phase path escapes root')
                hashes[relative] = sha256(path)
        total_files = len(hashes) + sum(len(phase['files']) for phase in self.value['phases'].values())
        if total_files > MAX_PHASE_FILES:
            raise ValueError('Publication continuation exceeds phase file limit')
        for relative, digest in hashes.items():
            relative_name(relative)
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                raise ValueError('Invalid accepted phase digest')
        accepted = dict(result=result, files=hashes)
        size = (self._state_bytes + len(canonical_json_bytes(name, ensure_ascii=True)) + 1
                + len(canonical_json_bytes(accepted, ensure_ascii=True)) + bool(self.value['phases']))
        if size > MAX_STATE_BYTES:
            raise ValueError('Publication continuation exceeds state byte limit')
        self.value['phases'][name] = accepted
        self.flush()
        return result

    def checked_event(self, event, value):
        """Validate one change and its exact serialized size before any PUT.

        Only one write and (at most) one protected version change per event.
        Counting their JSON deltas avoids copying/serializing the entire growing
        release for every asset; flush remeasures at each durable checkpoint.
        """
        change = write_transition(self.value, event, value)
        size = self._state_bytes
        if change is not None:
            key, new = change
            old = self.value['writes'].get(key)
            def length(item):
                return len(canonical_json_bytes(item, ensure_ascii=True))
            if old is None:
                size += length(key) + 1 + length(new) + bool(self.value['writes'])
            elif new is None:
                size -= length(key) + 1 + length(old) + (len(self.value['writes']) > 1)
            else:
                size += length(new) - length(old)
            if event == 'publication_write_verified' and key in self.value['versions']:
                size += length(value['etag']) - length(self.value['versions'][key])
            if size > MAX_STATE_BYTES:
                raise ValueError('Publication continuation exceeds state byte limit')
        return change, size

    def record(self, event, value, *, checkpoint=True):
        with self.lock:
            change, size = self.checked_event(event, value)
            if change is not None:
                key, write = change
                if write is None:
                    del self.value['writes'][key]
                else:
                    self.value['writes'][key] = write
                if event == 'publication_write_verified' and key in self.value['versions']:
                    self.value['versions'][key] = value['etag']
                self._state_bytes = size
                if checkpoint:
                    self.flush()

    @staticmethod
    def read(client, bucket, key, *, progress=None):
        from .reconciliation import MAX_READ_UPDATES
        from botocore.exceptions import ClientError
        try:
            response = client.get_object(Bucket=bucket, Key=key)
        except ClientError as error:
            if error.response['Error']['Code'] in {'NoSuchKey', '404'}:
                return None
            raise
        digest, size = hashlib.sha256(), 0
        total, updates, last_reported = response.get('ContentLength'), 0, -1
        def report():
            nonlocal last_reported
            if progress is not None and last_reported != size:
                try: progress(size, total)
                except Exception: pass
                last_reported = size
        try:
            with response['Body'] as stream:
                if type(total) is not int or total < 0:
                    raise ValueError('Invalid reconciliation ContentLength')
                step = max(1024 * 1024, (total + MAX_READ_UPDATES - 1) // MAX_READ_UPDATES)
                next_report = step
                report()
                while chunk := stream.read(1024 * 1024):
                    size += len(chunk); digest.update(chunk)
                    if updates < MAX_READ_UPDATES and size >= next_report:
                        report(); updates += 1; next_report = size + step
        finally:
            report()
        if size != response['ContentLength']:
            raise ValueError('Incomplete reconciliation read: ' + key)
        return dict(bytes=size, sha256=digest.hexdigest(), etag=response['ETag'])

    def reconcile(self, client, bucket, *, progress=None):
        """Resolve uncertain requests; acknowledged uploads need no remote read."""
        from .reconciliation import NEXT_CHECK, ReconciliationProgress
        observer = progress if progress is not None else ReconciliationProgress(self.root, self.value['binding'])
        for key, write in self.value['writes'].items():
            if write['verified'] and key in self.value['versions']:
                self.value['versions'][key] = write['etag']
        uncertain = [(key, write) for key, write in self.value['writes'].items() if not write['verified']]
        observed = dict(key=None, object_index=0, total_objects=len(uncertain),
                        checked_objects=0, bytes_read=0, declared_bytes=None, observation_only=True,
                        resume_authorized=False, current_readback_proof=False, public_readback='not_checked')
        def report(state):
            try:
                observer(dict(observed, state=state, next_check=NEXT_CHECK[state]))
            except Exception:
                # Observation failures cannot replace the original read/checkpoint
                # outcome, confer proof, or change write conditions.
                pass
        report('starting')
        conflict = False
        try:
            for index, (key, intent) in enumerate(uncertain, 1):
                observed.update(key=key, object_index=index, bytes_read=0, declared_bytes=None)
                report('reading')
                def reading(size, total):
                    observed.update(bytes_read=size, declared_bytes=total if type(total) is int and total >= 0 else None)
                    report('reading')
                current = self.read(client, bucket, key, progress=reading)
                matches = current and all(current[name] == intent[name] for name in ('bytes', 'sha256'))
                if matches:
                    intent.update(current, verified=True)
                    if key in self.value['versions']:
                        self.value['versions'][key] = current['etag']
                    outcome = 'reconciled'
                elif ((current is None and intent.get('if_none_match') == '*')
                      or (current and current['etag'] == intent.get('expected_etag'))):
                    outcome = 'uncommitted'  # A later write must retain its original condition.
                else:
                    conflict = True
                    raise ValueError('Uncertain publication conflicts with current object: ' + key)
                observed['checked_objects'] = index
                report(outcome)
            self.flush()
        except BaseException:
            report('conflict' if conflict else 'failed')
            raise
        report('complete')

    def replay(self, client, bucket, key, body, *, validation=None):
        """Reuse an acknowledged upload for the same bytes and original condition."""
        saved = self.value['writes'].get(key)
        if not saved or not saved['verified']:
            return None
        if isinstance(body, bytes):
            size, digest = len(body), hashlib.sha256(body).hexdigest()
        elif validation is not None:
            from congress_api.retention.derived_files import VerifiedFile
            if not isinstance(validation, VerifiedFile) or body.tell() != 0:
                raise ValueError('Invalid continued local file proof')
            validation.require(body.name)
            size, digest = validation['bytes'], validation['sha256']
        else:
            start = body.tell(); digestor = hashlib.sha256(); size = 0
            while chunk := body.read(1024 * 1024):
                size += len(chunk); digestor.update(chunk)
            body.seek(start); digest = digestor.hexdigest()
        if (size, digest) != (saved['bytes'], saved['sha256']):
            raise ValueError('Continued publication write differs: ' + key)
        return {'ETag': saved['etag']}


class MissingPublicationJournal(ValueError):
    """No durable attempt event exists; no publication write could have started."""


class DurableJournal:
    """Append-only, conditionally created events that survive abrupt runner loss.

    Each event binds the preceding payload digest. Restoring an attempt reads the
    whole bounded prefix, validates the chain, and reconstructs local write state.
    The journal's guarded immutable PUT has no recursive journal callback.
    """
    def __init__(self, client, bucket, continuation, attempt, binding, *, resume=False):
        import re
        from viewer_publication.client import GuardedPublicationClient
        if not re.fullmatch(r'[a-zA-Z0-9-]{1,160}', attempt):
            raise ValueError('Invalid publication attempt identity')
        self.client, self.bucket, self.continuation = client, bucket, continuation
        self.prefix = 'viewer-publications/attempts/' + attempt + '/'
        self.binding = binding
        self.sequence = 0
        self.previous = None
        self.total_bytes = 0
        self.pending_verified = None
        self.checkpoint_sequence = 0
        self.lock = threading.RLock()
        self.writer = GuardedPublicationClient(client, guard=lambda: None,
                                               journal=lambda *args: None, after_write=lambda *args: None, strict_conditions=True)
        if resume:
            self.restore()
        else:
            # A named attempt may only start once, including when acknowledgment
            # of its first event was lost. Explicit resume owns reconciliation.
            if Continuation.read(client, bucket, self.prefix + '00000000.json') is not None:
                raise ValueError('Publication attempt exists; explicit resume required')
            self.record('attempt_started', {'binding': binding})

    def restore(self):
        pages = self.client.get_paginator('list_objects_v2').paginate(Bucket=self.bucket, Prefix=self.prefix)
        keys = []
        for page in pages:
            rows = page.get('Contents', [])
            if not isinstance(rows, list):
                raise ValueError('Malformed publication journal listing')
            for item in rows:
                if len(keys) >= MAX_EVENTS:
                    raise ValueError('Publication journal exceeds event count limit')
                if (not isinstance(item, dict) or not isinstance(item.get('Key'), str)
                        or len(item['Key']) != len(self.prefix) + 13):
                    raise ValueError('Malformed publication journal key')
                keys.append(item['Key'])
        keys.sort()
        if not keys:
            raise MissingPublicationJournal('Publication attempt journal is missing')
        # Reconstruct write state from the full accepted prefix, not stale local
        # writes. No checkpoint or accepted journal file is changed until every
        # event has passed version/chain/binding/transition and byte limits.
        restored = dict(self.continuation.value, writes={})
        previous, total, accepted = None, 0, []
        for index, key in enumerate(keys):
            if key != self.prefix + f'{index:08d}.json':
                raise ValueError('Publication attempt journal has a gap or foreign object')
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            with response['Body'] as stream:
                declared = response.get('ContentLength')
                if type(declared) is not int or not 0 <= declared <= MAX_EVENT_BYTES:
                    raise ValueError('Publication journal exceeds event byte limit')
                if total + declared > MAX_JOURNAL_BYTES:
                    raise ValueError('Publication journal exceeds total byte limit')
                raw = stream.read(min(MAX_EVENT_BYTES, MAX_JOURNAL_BYTES - total) + 1)
            total += len(raw)
            if len(raw) > MAX_EVENT_BYTES or total > MAX_JOURNAL_BYTES:
                raise ValueError('Publication journal exceeds byte limit')
            if len(raw) != declared:
                raise ValueError('Incomplete publication journal read')
            event = json.loads(raw)
            if not isinstance(event, dict) or type(event.get('version')) is not int or event['version'] != 1:
                raise ValueError('Unsupported publication journal version')
            if (type(event.get('sequence')) is not int or event['sequence'] != index or event.get('previous') != previous
                    or not isinstance(event.get('nonce'), str) or len(event['nonce']) != 32
                    or any(c not in '0123456789abcdef' for c in event['nonce'])):
                raise ValueError('Publication attempt journal chain or nonce differs')
            if not isinstance(event.get('value'), dict):
                raise ValueError('Malformed publication event value')
            if index == 0 and (event.get('event') != 'attempt_started' or event.get('value', {}).get('binding') != self.binding):
                raise ValueError('Publication attempt preparation binding differs')
            if 'verified_write' in event:
                apply_event(restored, 'publication_write_verified', event['verified_write'])
            apply_event(restored, event.get('event'), event.get('value'))
            accepted.append(raw)
            previous = hashlib.sha256(raw).hexdigest()
        validate_state(restored)
        if len(canonical_json_bytes(restored, ensure_ascii=True)) + 1 > MAX_STATE_BYTES:
            raise ValueError('Publication continuation exceeds state byte limit')
        # Local event files are retained evidence. Only derived continuation state
        # uses one serialized/fsynced checkpoint after complete prefix validation.
        for index, raw in enumerate(accepted):
            self.continuation.save(f'journal/{index:08d}.json', raw)
        self.continuation.value['writes'] = restored['writes']
        self.continuation.flush()
        self.previous, self.sequence, self.total_bytes = previous, len(keys), total
        self.checkpoint_sequence = self.sequence

    def record(self, event, value):
        with self.lock:
            self.continuation.checked_event(event, value)
            if event == 'publication_write_verified':
                # Keep one fact until the next append. Its original durable intent
                # supports full-body reconciliation after runner loss. Consecutive
                # verifications flush the older fact even during parallel uploads.
                if self.pending_verified is not None:
                    self._append('publication_write_verified', self.pending_verified)
                    self.pending_verified = None
                self.continuation.record(event, value, checkpoint=False)
                self.pending_verified = dict(value)
            else:
                self._append(event, value, verified_write=self.pending_verified)
                self.pending_verified = None
                self.continuation.record(event, value, checkpoint=False)
            # The cloud chain owns write recovery, including uncertain intents.
            # continuation.json is a derived cache. Phase acceptance and direct
            # Continuation.record calls still checkpoint immediately.
            if (self.sequence - self.checkpoint_sequence >= JOURNAL_CHECKPOINT_EVENTS
                    or not event.startswith('publication_write_')):
                self.continuation.flush()
                self.checkpoint_sequence = self.sequence

    def _append(self, event, value, *, verified_write=None):
        # Called only while record owns the journal lock. Advance nothing until
        # conditional creation and complete journal readback both succeed.
        if self.sequence >= MAX_EVENTS:
            raise ValueError('Publication journal exceeds event count limit')
        nonce = uuid.uuid4().hex
        item = {'version': 1, 'sequence': self.sequence, 'previous': self.previous,
                'nonce': nonce, 'event': event, 'value': value}
        if verified_write is not None:
            item['verified_write'] = verified_write
        raw = json.dumps(item, sort_keys=True, separators=(',', ':')).encode()
        if len(raw) > MAX_EVENT_BYTES or self.total_bytes + len(raw) > MAX_JOURNAL_BYTES:
            raise ValueError('Publication journal exceeds event/total byte limit')
        key = self.prefix + f'{self.sequence:08d}.json'
        # Retain the exact nonce-bound request before mutation. Conditional
        # creation fences competing runners at every pre-mutation intent.
        self.continuation.save(f'journal-intents/{self.sequence:08d}-{nonce}.json', raw)
        self.writer.put_object(Bucket=self.bucket, Key=key, Body=raw, ContentLength=len(raw),
                               ContentType='application/json', IfNoneMatch='*')
        self.continuation.save(f'journal/{self.sequence:08d}.json', raw)
        self.sequence += 1
        self.total_bytes += len(raw)
        self.previous = hashlib.sha256(raw).hexdigest()
