"""Durable receipts for an explicitly requested publication continuation.

Receipts bind local inputs and accepted phase outputs. Remote writes are only
reused after current bytes and version agree; an uncertain request is never
resent until a later explicit invocation reconciles its outcome.
"""
import hashlib
import json
import os
from pathlib import Path
import threading


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class Continuation:
    def __init__(self, root, binding, *, resume=False):
        self.root = Path(root)
        self.path = self.root / 'continuation.json'
        self.lock = threading.RLock()
        if resume:
            self.value = json.loads(self.path.read_text())
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
            temporary.replace(self.path)
            descriptor = os.open(self.root, os.O_RDONLY)
            try: os.fsync(descriptor)
            finally: os.close(descriptor)

    def save(self, name, raw, *, replace=False):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and not replace:
            if path.read_bytes() != raw:
                raise ValueError('Publication artifact changed: ' + name)
            return
        temporary = path.with_name(path.name + '.partial')
        with temporary.open('wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        temporary.replace(path)

    def phase(self, name, action, *, files):
        saved = self.value['phases'].get(name)
        if saved is not None:
            for relative, expected in saved['files'].items():
                if sha256(self.root / relative) != expected:
                    raise ValueError('Accepted publication phase changed: ' + name)
            return saved['result']
        result = action()
        self.value['phases'][name] = dict(result=result, files={
            str(path.relative_to(self.root)): sha256(path) for path in files()})
        self.flush()
        return result

    def record(self, event, value):
        with self.lock:
            if event == 'publication_write_intent':
                self.value['writes'][value['key']] = dict(value, verified=False)
            elif event == 'publication_write_refused':
                self.value['writes'].pop(value['key'], None)
            elif event == 'publication_write_verified':
                self.value['writes'][value['key']].update(value, verified=True)
            else:
                return
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
            current = self.read(client, bucket, key)
            matches = current and all(current[name] == intent[name] for name in ('bytes', 'sha256'))
            if matches:
                if intent['verified'] and current['etag'] != intent['etag']:
                    raise ValueError('Verified publication version changed: ' + key)
                intent.update(current, verified=True)
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

    def replay(self, client, bucket, key, body):
        """Return a current receipt for the same write, or require a normal write."""
        saved = self.value['writes'].get(key)
        if not saved or not saved['verified']:
            return None
        if isinstance(body, bytes):
            size, digest = len(body), hashlib.sha256(body).hexdigest()
        else:
            start = body.tell(); digestor = hashlib.sha256(); size = 0
            while chunk := body.read(1024 * 1024):
                size += len(chunk); digestor.update(chunk)
            body.seek(start); digest = digestor.hexdigest()
        if (size, digest) != (saved['bytes'], saved['sha256']):
            raise ValueError('Continued publication write differs: ' + key)
        current = self.read(client, bucket, key)
        if current != {name: saved[name] for name in ('bytes', 'sha256', 'etag')}:
            raise ValueError('Continued publication object changed: ' + key)
        return {'ETag': current['etag']}
