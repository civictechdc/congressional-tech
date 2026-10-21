"""Exact content-addressed publication metadata, shared by native data readers."""
from hashlib import sha256
from collections import OrderedDict
import json

from congress_shared.custody import canonical_json_bytes
from congress_api.retention.write_recovery import reconcile_lost_acknowledgment


def encoded(value):
    return canonical_json_bytes(value, ensure_ascii=True, allow_nan=False)


class MetadataObjects:
    """Retain immutable JSON once and verify its exact identity at first read.

    The byte budget limits writes and declared references before I/O. The
    injected store.read may buffer a complete corrupt response before its actual
    length can be rejected; this class does not claim a hard transport bound.
    """
    def __init__(self, store, namespace, *, max_bytes=1 << 20, max_cache_entries=None):
        if not namespace or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in namespace):
            raise ValueError('Invalid metadata namespace')
        self.store = store
        self.prefix = f'indexes/native-manifests/{namespace}/'
        self.max_bytes = max_bytes
        if max_cache_entries is not None and (type(max_cache_entries) is not int or max_cache_entries < 1):
            raise ValueError('Metadata cache size must be a positive integer')
        self.max_cache_entries = max_cache_entries
        self._cache = OrderedDict()

    def _remember(self, key, raw):
        self._cache[key] = raw
        self._cache.move_to_end(key)
        if self.max_cache_entries is not None and len(self._cache) > self.max_cache_entries:
            self._cache.popitem(last=False)

    def put(self, value):
        raw = encoded(value)
        if len(raw) > self.max_bytes:
            raise ValueError('Publication metadata exceeds the byte budget')
        digest = sha256(raw).hexdigest()
        key = self.prefix + digest + '.json'
        if key not in self._cache:
            reconcile_lost_acknowledgment(
                lambda: self.store.put(key, raw, immutable=True), lambda: self.store.read(key), raw)
            self._remember(key, raw)
        return dict(key=key, sha256=digest, bytes=len(raw))

    def read(self, reference):
        if not isinstance(reference, dict):
            raise ValueError('Publication metadata reference identity mismatch')
        digest, size, key = (reference.get(name) for name in ('sha256', 'bytes', 'key'))
        if (not isinstance(digest, str) or len(digest) != 64
                or any(char not in '0123456789abcdef' for char in digest)
                or not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= self.max_bytes
                or key != self.prefix + digest + '.json'):
            raise ValueError('Publication metadata reference identity mismatch')
        raw = self._cache.get(key)
        if raw is None:
            raw = self.store.read(key)
        if (raw is None or len(raw) != reference['bytes'] or len(raw) > self.max_bytes
                or sha256(raw).hexdigest() != reference['sha256']
                or key != self.prefix + reference['sha256'] + '.json'):
            raise ValueError('Publication metadata identity mismatch')
        self._remember(key, raw)
        return json.loads(raw)
