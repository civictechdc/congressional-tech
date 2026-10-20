"""Exact content-addressed publication metadata, shared by native data readers."""
from hashlib import sha256
import json

from congress_api.retention.write_recovery import reconcile_lost_acknowledgment


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


class MetadataObjects:
    """Retain immutable JSON once and verify its exact identity at first read."""
    def __init__(self, store, namespace, *, max_bytes=1 << 20):
        if not namespace or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in namespace):
            raise ValueError('Invalid metadata namespace')
        self.store = store
        self.prefix = f'indexes/native-manifests/{namespace}/'
        self.max_bytes = max_bytes
        self._cache = {}

    def put(self, value):
        raw = encoded(value)
        if len(raw) > self.max_bytes:
            raise ValueError('Publication metadata exceeds the byte budget')
        digest = sha256(raw).hexdigest()
        key = self.prefix + digest + '.json'
        if key not in self._cache:
            reconcile_lost_acknowledgment(
                lambda: self.store.put(key, raw, immutable=True), lambda: self.store.read(key), raw)
            self._cache[key] = raw
        return dict(key=key, sha256=digest, bytes=len(raw))

    def read(self, reference):
        key = reference['key']
        raw = self._cache.get(key)
        if raw is None:
            raw = self.store.read(key)
        if (raw is None or len(raw) != reference['bytes'] or len(raw) > self.max_bytes
                or sha256(raw).hexdigest() != reference['sha256']
                or key != self.prefix + reference['sha256'] + '.json'):
            raise ValueError('Publication metadata identity mismatch')
        self._cache[key] = raw
        return json.loads(raw)
