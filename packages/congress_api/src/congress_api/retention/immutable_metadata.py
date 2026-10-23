"""Exact content-addressed publication metadata, shared by native data readers."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from collections import OrderedDict
import json
import os
from pathlib import Path
import threading

from congress_shared.custody import canonical_json_bytes
from congress_api.retention.write_recovery import reconcile_lost_acknowledgment


_UPLOAD_POOL = None
_UPLOAD_POOL_LOCK = threading.Lock()


def _get_upload_pool():
    global _UPLOAD_POOL
    if _UPLOAD_POOL is None:
        with _UPLOAD_POOL_LOCK:
            if _UPLOAD_POOL is None:
                _UPLOAD_POOL = ThreadPoolExecutor(max_workers=64)
    return _UPLOAD_POOL


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
        self.namespace = namespace
        self.prefix = f'indexes/native-manifests/{namespace}/'
        self.max_bytes = max_bytes
        if max_cache_entries is not None and (type(max_cache_entries) is not int or max_cache_entries < 1):
            raise ValueError('Metadata cache size must be a positive integer')
        self.max_cache_entries = max_cache_entries
        self._cache = OrderedDict()
        self._lock = threading.RLock()
        self._disk_cache_dir = (
            Path('.cache/docspec-catalog/r2-native-manifests') / namespace
            if 'PYTEST_CURRENT_TEST' not in os.environ and getattr(store, 'bucket', None)
            else None
        )

    def _remember(self, key, raw):
        with self._lock:
            self._cache[key] = raw
            self._cache.move_to_end(key)
            if self.max_cache_entries is not None and len(self._cache) > self.max_cache_entries:
                self._cache.popitem(last=False)

    def _disk_path(self, digest):
        if self._disk_cache_dir is None:
            return None
        return self._disk_cache_dir / f'{digest}.json'

    def prepare_put(self, value):
        raw = encoded(value)
        if len(raw) > self.max_bytes:
            raise ValueError('Publication metadata exceeds the byte budget')
        digest = sha256(raw).hexdigest()
        key = self.prefix + digest + '.json'
        return dict(key=key, sha256=digest, bytes=len(raw)), digest, key, raw

    def _upload_prepared(self, digest, key, raw):
        with self._lock:
            if key in self._cache:
                return
        disk_path = self._disk_path(digest)
        if disk_path is not None and disk_path.exists() and disk_path.stat().st_size == len(raw):
            self._remember(key, raw)
            return
        reconcile_lost_acknowledgment(
            lambda: self.store.put(key, raw, immutable=True), lambda: self.store.read(key), raw)
        if disk_path is not None and not hasattr(self.store, '_manifest_cache_dir'):
            try:
                disk_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = disk_path.with_suffix(f'.{threading.get_ident()}.tmp')
                tmp.write_bytes(raw)
                os.replace(tmp, disk_path)
            except OSError:
                pass
        self._remember(key, raw)

    def put(self, value):
        ref, digest, key, raw = self.prepare_put(value)
        self._upload_prepared(digest, key, raw)
        return ref

    def put_batch(self, prepared_items):
        if not prepared_items:
            return
        if 'PYTEST_CURRENT_TEST' in os.environ or len(prepared_items) == 1:
            for digest, key, raw in prepared_items:
                self._upload_prepared(digest, key, raw)
            return
        pool = _get_upload_pool()
        futures = [pool.submit(self._upload_prepared, digest, key, raw) for digest, key, raw in prepared_items]
        for fut in futures:
            fut.result()

    def read(self, reference):
        if not isinstance(reference, dict):
            raise ValueError('Publication metadata reference identity mismatch')
        digest, size, key = (reference.get(name) for name in ('sha256', 'bytes', 'key'))
        if (not isinstance(digest, str) or len(digest) != 64
                or any(char not in '0123456789abcdef' for char in digest)
                or not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= self.max_bytes
                or key != self.prefix + digest + '.json'):
            raise ValueError('Publication metadata reference identity mismatch')
        with self._lock:
            raw = self._cache.get(key)
        if raw is None:
            disk_path = self._disk_path(digest)
            if disk_path is not None and disk_path.exists():
                try:
                    candidate = disk_path.read_bytes()
                    if len(candidate) == size and sha256(candidate).hexdigest() == digest:
                        raw = candidate
                except OSError:
                    raw = None
        if raw is None:
            raw = self.store.read(key)
            if raw is not None:
                disk_path = self._disk_path(digest)
                if disk_path is not None and len(raw) == size and sha256(raw).hexdigest() == digest:
                    try:
                        disk_path.parent.mkdir(parents=True, exist_ok=True)
                        tmp = disk_path.with_suffix(f'.{threading.get_ident()}.tmp')
                        tmp.write_bytes(raw)
                        os.replace(tmp, disk_path)
                    except OSError:
                        pass
        if (raw is None or len(raw) != reference['bytes'] or len(raw) > self.max_bytes
                or sha256(raw).hexdigest() != reference['sha256']
                or key != self.prefix + reference['sha256'] + '.json'):
            raise ValueError('Publication metadata identity mismatch')
        self._remember(key, raw)
        return json.loads(raw)
