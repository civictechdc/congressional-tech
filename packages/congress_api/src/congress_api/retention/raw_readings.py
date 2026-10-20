"""Bounded raw delivery references to existing immutable body reading parts.

Declared compressed bytes and row counts are checked before I/O; decoded Arrow
bytes are checked per batch before conversion to Python values. The injected
store may buffer a complete corrupt response, and Parquet decoding allocates a
batch before its byte check. This is not a hard transport/process-memory cap.
"""
from collections import defaultdict
from hashlib import sha256
from pathlib import PurePosixPath

import pyarrow as pa
import pyarrow.parquet as pq

from .immutable_metadata import encoded
from .partition_routing import RoutingPages, key_hash
from .capture_metadata import PREFIX, RESULT_COLUMNS

PART_BYTES = 32 << 20
PART_ROWS = 1000
LEAF_ENTRIES = 128


def part_rows(store, reference):
    key, size, digest, rows = (reference.get(name) for name in ('key', 'bytes', 'sha256', 'rows'))
    if (not isinstance(key, str) or not key.startswith(PREFIX) or '..' in PurePosixPath(key).parts
            or type(size) is not int or not 0 < size <= PART_BYTES
            or type(rows) is not int or not 0 < rows <= PART_ROWS
            or not isinstance(digest, str) or len(digest) != 64
            or any(char not in '0123456789abcdef' for char in digest)
            or not key.endswith('-' + digest + '.parquet')):
        raise ValueError('Retained reading part identity or bounds differ')
    raw = store.read(key)
    if raw is None or len(raw) != size or sha256(raw).hexdigest() != digest:
        raise ValueError('Retained reading part identity differs')
    file = pq.ParquetFile(pa.BufferReader(raw))
    schema = file.schema_arrow
    if (file.metadata.num_rows != rows or (schema.metadata or {}).get(b'format_version') != b'1'
            or not set(RESULT_COLUMNS) <= set(schema.names)
            or any(field.type != (pa.string() if field.name in RESULT_COLUMNS else pa.list_(pa.string()))
                   for field in schema)):
        raise ValueError('Unexpected selected reading part schema or count')
    decoded = 0
    for batch in file.iter_batches(batch_size=256):
        decoded += batch.nbytes
        if decoded > PART_BYTES:
            raise ValueError('Retained reading part exceeds its decoded-byte budget')
        yield from batch.to_pylist()


class RawReadings:
    """Index completed reading custody, never reader work or pending state."""
    def __init__(self, store):
        self.store = store
        self.routes = RoutingPages(store, 'raw-readings-v1')
        self.routes.objects.max_cache_entries = 32

    @staticmethod
    def _entries(prefix, value):
        entries = value.get('entries', {}) if value else {}
        if (not isinstance(entries, dict) or len(entries) > LEAF_ENTRIES
                or any(not isinstance(key, str) or not key or not key_hash(key).startswith(prefix)
                       or not isinstance(reference, dict) for key, reference in entries.items())):
            raise ValueError('Invalid selected reading reference leaf')
        return entries

    def lookup(self, root, body):
        prefix, value = self.routes.lookup(root, body)
        return self._entries(prefix, value).get(body)

    def prepare(self, root, parts, *, replace=()):
        updates = {}
        for supplied in parts:
            reference = {name: supplied[name] for name in ('key', 'bytes', 'sha256', 'rows')}
            for row in part_rows(self.store, reference):
                body = row['body_key']
                if not isinstance(body, str) or not body:
                    raise ValueError('Reading part lacks a body identity')
                updates.setdefault(body, reference)
        replace = set(replace)
        affected = {}
        for body, reference in updates.items():
            prefix, value = self.routes.lookup(root, body)
            entries = self._entries(prefix, value)
            if body not in entries or body in replace and entries[body] != reference:
                affected.setdefault(prefix, dict(entries))[body] = reference

        def split(prefix, entries):
            if len(entries) <= LEAF_ENTRIES and len(encoded(dict(entries=entries))) < (1 << 20) - 1024:
                yield prefix, dict(entries=entries)
                return
            if len(prefix) == 64:
                raise ValueError('Reading references exceed a bounded metadata leaf')
            for char in '0123456789abcdef':
                child = prefix + char
                selected = {key: value for key, value in entries.items() if key_hash(key).startswith(child)}
                if selected:
                    yield from split(child, selected)
        result = root
        for prefix, entries in sorted(affected.items()):
            result = self.routes.replace_stream(result, prefix, split(prefix, entries))
        return result

    def rows(self, root, bodies):
        selected = defaultdict(set)
        references = {}
        for body in dict.fromkeys(bodies):
            reference = self.lookup(root, body)
            if reference is not None:
                identity = reference['key']
                references[identity] = reference
                selected[identity].add(body)
        for key in sorted(selected):
            found = set()
            for row in part_rows(self.store, references[key]):
                if row['body_key'] in selected[key] and row['body_key'] not in found:
                    found.add(row['body_key'])
                    yield row
            if found != selected[key]:
                raise ValueError('Selected reading reference lacks its body row')
