"""Durable receipts for an explicitly requested publication continuation.

Receipts bind local inputs and accepted phase outputs. Remote writes are only
reused after current bytes and version agree; an uncertain request is never
resent until a later explicit invocation reconciles its outcome.
"""
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import threading
import uuid


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


MAX_STATE_BYTES = 32 * 1024**2
MAX_EVENTS = 16384
MAX_EVENT_BYTES = 1024**2
MAX_JOURNAL_BYTES = 64 * 1024**2
MAX_WRITES = 8192
MAX_PHASES = 64
MAX_PHASE_FILES = 32768


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


def apply_event(state, event, value):
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
        writes[value['key']] = dict(value, verified=False)
    elif event in ('publication_write_refused', 'publication_write_verified'):
        previous = writes.get(value.get('key'))
        if previous is None or previous.get('verified'):
            raise ValueError('Illegal publication write transition')
        if event == 'publication_write_refused':
            del writes[value['key']]
        else:
            write_value(value, verified=True)
            if any(previous[k] != value[k] for k in ('bytes', 'sha256')):
                raise ValueError('Publication verification differs from intent')
            previous.update(value, verified=True)
    else:
        return False  # Informational events are legitimate and retain their history.
    return True


class Continuation:
    def __init__(self, root, binding, *, resume=False):
        self.root = Path(root)
        self.path = self.root / 'continuation.json'
        self.lock = threading.RLock()
        # Ephemeral readback proofs never come from continuation JSON. Keeping the
        # client object alive also prevents object-id reuse from transferring proof.
        self._reconciled = {}
        if resume:
            self.value = validate_state(bounded_json(self.path))
            if self.value['binding'] != binding:
                raise ValueError('Publication continuation inputs changed')
        else:
            self.root.mkdir(parents=True, exist_ok=False)
            self.value = dict(version=1, binding=binding, phases={}, writes={}, versions={})
            self.flush()

    def flush(self):
        with self.lock:
            temporary = self.path.with_suffix('.tmp')
            with temporary.open('w') as stream:
                json.dump(self.value, stream, sort_keys=True, indent=2)
                stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
            if temporary.stat().st_size > MAX_STATE_BYTES:
                temporary.unlink()
                raise ValueError('Publication continuation exceeds state byte limit')
            temporary.replace(self.path)
            descriptor = os.open(self.root, os.O_RDONLY)
            try: os.fsync(descriptor)
            finally: os.close(descriptor)

    def save(self, name, raw, *, replace=False):
        path = self.root / relative_name(name)
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise ValueError('Publication saved path escapes attempt directory')
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and not replace:
            if path.read_bytes() != raw:
                raise ValueError('Publication artifact changed: ' + name)
            return
        temporary = path.with_name(path.name + '.partial')
        with temporary.open('wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        temporary.replace(path)

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
        self.value['phases'][name] = dict(result=result, files=hashes)
        self.flush()
        return result

    def record(self, event, value):
        with self.lock:
            if apply_event(self.value, event, value):
                self.flush()

    @staticmethod
    def read(client, bucket, key):
        from botocore.exceptions import ClientError
        try:
            response = client.get_object(Bucket=bucket, Key=key)
        except ClientError as error:
            if error.response['Error']['Code'] in {'NoSuchKey', '404'}:
                return None
            raise
        digest, size = hashlib.sha256(), 0
        with response['Body'] as stream:
            while chunk := stream.read(1024 * 1024):
                size += len(chunk); digest.update(chunk)
        if size != response['ContentLength']:
            raise ValueError('Incomplete reconciliation read: ' + key)
        return dict(bytes=size, sha256=digest.hexdigest(), etag=response['ETag'])

    def reconcile(self, client, bucket):
        """Read only: resolve uncertain requests before the first guard or write."""
        for key, intent in self.value['writes'].items():
            self._reconciled.pop((id(client), bucket, key), None)
            current = self.read(client, bucket, key)
            matches = current and all(current[name] == intent[name] for name in ('bytes', 'sha256'))
            if matches:
                if intent['verified'] and current['etag'] != intent['etag']:
                    raise ValueError('Verified publication version changed: ' + key)
                intent.update(current, verified=True)
                self._reconciled[(id(client), bucket, key)] = (client, dict(current))
                if key in self.value['versions']:
                    self.value['versions'][key] = current['etag']
            elif intent['verified']:
                raise ValueError('Verified publication bytes changed: ' + key)
            elif ((current is None and intent.get('if_none_match') == '*')
                  or (current and current['etag'] == intent.get('expected_etag'))):
                continue  # A later explicitly requested write can use its original condition.
            else:
                raise ValueError('Uncertain publication conflicts with current object: ' + key)
        self.flush()

    def replay(self, client, bucket, key, body, *, validation=None):
        """Return a current receipt for the same write, or require a normal write."""
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
        expected = {name: saved[name] for name in ('bytes', 'sha256', 'etag')}
        proof = self._reconciled.get((id(client), bucket, key))
        if proof is not None and proof[0] is client and proof[1] == expected and hasattr(client, 'head_object'):
            current = client.head_object(Bucket=bucket, Key=key)
            if current.get('ETag') != expected['etag'] or current.get('ContentLength') != expected['bytes']:
                raise ValueError('Continued publication object changed: ' + key)
        elif self.read(client, bucket, key) != expected:
            raise ValueError('Continued publication object changed: ' + key)
        return {'ETag': expected['etag']}


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
        restored = copy.deepcopy(self.continuation.value)
        restored['writes'] = {}
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
            apply_event(restored, event.get('event'), event.get('value'))
            accepted.append(raw)
            previous = hashlib.sha256(raw).hexdigest()
        validate_state(restored)
        # Local event files are retained evidence. Only derived continuation state
        # uses one serialized/fsynced checkpoint after complete prefix validation.
        for index, raw in enumerate(accepted):
            self.continuation.save(f'journal/{index:08d}.json', raw)
        self.continuation.value['writes'] = restored['writes']
        self.continuation.flush()
        self.previous, self.sequence, self.total_bytes = previous, len(keys), total

    def record(self, event, value):
        with self.lock:
            if self.sequence >= MAX_EVENTS:
                raise ValueError('Publication journal exceeds event count limit')
            candidate = {'writes': dict(self.continuation.value['writes'])}
            if isinstance(value, dict) and value.get('key') in candidate['writes']:
                candidate['writes'][value['key']] = dict(candidate['writes'][value['key']])
            apply_event(candidate, event, value)
            nonce = uuid.uuid4().hex
            item = {'version': 1, 'sequence': self.sequence, 'previous': self.previous,
                    'nonce': nonce, 'event': event, 'value': value}
            raw = json.dumps(item, sort_keys=True, separators=(',', ':')).encode()
            if len(raw) > MAX_EVENT_BYTES or self.total_bytes + len(raw) > MAX_JOURNAL_BYTES:
                raise ValueError('Publication journal exceeds event/total byte limit')
            key = self.prefix + f'{self.sequence:08d}.json'
            # Keep this writer's exact payload before attempting the remote PUT.
            # A unique nonce prevents an ambiguous acknowledgment from mistaking
            # another runner's otherwise identical event for this write.
            self.continuation.save(f'journal-intents/{self.sequence:08d}-{nonce}.json', raw)
            # Conditional creation is also a fence against two runners trying to
            # use the same explicit attempt concurrently.
            self.writer.put_object(Bucket=self.bucket, Key=key, Body=raw, ContentLength=len(raw),
                                   ContentType='application/json', IfNoneMatch='*')
            self.continuation.save(f'journal/{self.sequence:08d}.json', raw)
            self.sequence += 1
            self.total_bytes += len(raw)
            self.previous = hashlib.sha256(raw).hexdigest()
            self.continuation.record(event, value)
