"""Thin persistent-host transport for maintained DocSpec source-only dataset operations.

Callers supply exact native requests, stable operation identities, and partition
routing. DocSpec owns admission, versions, completion, concurrency and recovery.
Application publication must select a coherent set of exact completed pins;
independent native latest results are preparation, not an application snapshot.
"""
import base64
from collections.abc import Mapping
from contextlib import contextmanager
from hashlib import file_digest
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import threading
import time
import weakref
from urllib.parse import quote
from tempfile import mkdtemp

import pyarrow as pa
import pyarrow.parquet as pq

try:
    import blake3 as _blake3_ext
except ImportError:
    _blake3_ext = None

from .docspec_host import (
    REQUIRED_LOOPBACK_CAPABILITIES,
    ArrowResponse,
    DocSpecFailure,
    acquire_host,
)

ARROW_STREAM_MIME = 'application/vnd.apache.arrow.stream'
VALID_UPDATE_MERGE_STRATEGIES = ('replace', 'latest_or_backfill', 'min', 'max', 'set_union')
SUPPORTED_PLATFORMS = ('linux-amd64', 'darwin-arm64', 'darwin-amd64')
PRODUCER_PARQUET_ROW_GROUP_SIZE = 2048
QUALIFIED_DOCSPEC_RUNTIME = {
    'source_revision': 'c949c6762f001845d2933e55cb9d7cf237e80810',
    'darwin_arm64_binary_sha256': 'c7d936227bafcedd9c58e2cea1c52221b8a254e914d9f0fad9c60ce104de951b',
    'build_features': ('remote',),
    'required_capabilities': REQUIRED_LOOPBACK_CAPABILITIES,
    'safety_prerequisites': (
        'ct-3li2', 'ct-cpio', 'ct-xq1y', 'ct-5fkx', 'ct-gfv8', 'ct-q05l', 'ct-csyg',
        'ct-tuez', 'ct-nmjc', 'ct-13g5',
    ),
}

_BLAKE3_IV = (
    0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A,
    0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19,
)
_BLAKE3_MSG_PERMUTATION = (2, 6, 3, 10, 7, 0, 4, 13, 1, 11, 12, 5, 9, 14, 15, 8)
_BLAKE3_CHUNK_START = 1
_BLAKE3_CHUNK_END = 2
_BLAKE3_PARENT = 4
_BLAKE3_ROOT = 8

def _blake3_rotr32(x, n):
    return ((x >> n) | ((x << (32 - n)) & 0xFFFFFFFF)) & 0xFFFFFFFF


def _blake3_g(state, a, b, c, d, mx, my):
    state[a] = (state[a] + state[b] + mx) & 0xFFFFFFFF
    state[d] = _blake3_rotr32(state[d] ^ state[a], 16)
    state[c] = (state[c] + state[d]) & 0xFFFFFFFF
    state[b] = _blake3_rotr32(state[b] ^ state[c], 12)
    state[a] = (state[a] + state[b] + my) & 0xFFFFFFFF
    state[d] = _blake3_rotr32(state[d] ^ state[a], 8)
    state[c] = (state[c] + state[d]) & 0xFFFFFFFF
    state[b] = _blake3_rotr32(state[b] ^ state[c], 7)


def _blake3_round(state, m):
    _blake3_g(state, 0, 4, 8, 12, m[0], m[1])
    _blake3_g(state, 1, 5, 9, 13, m[2], m[3])
    _blake3_g(state, 2, 6, 10, 14, m[4], m[5])
    _blake3_g(state, 3, 7, 11, 15, m[6], m[7])
    _blake3_g(state, 0, 5, 10, 15, m[8], m[9])
    _blake3_g(state, 1, 6, 11, 12, m[10], m[11])
    _blake3_g(state, 2, 7, 8, 13, m[12], m[13])
    _blake3_g(state, 3, 4, 9, 14, m[14], m[15])


def _blake3_compress(cv, block_words, counter, block_len, flags):
    state = [
        cv[0], cv[1], cv[2], cv[3],
        cv[4], cv[5], cv[6], cv[7],
        _BLAKE3_IV[0], _BLAKE3_IV[1], _BLAKE3_IV[2], _BLAKE3_IV[3],
        counter & 0xFFFFFFFF, (counter >> 32) & 0xFFFFFFFF, block_len, flags,
    ]
    m = list(block_words)
    for r in range(7):
        _blake3_round(state, m)
        if r < 6:
            m = [m[i] for i in _BLAKE3_MSG_PERMUTATION]
    for i in range(8):
        state[i] ^= state[i + 8]
        state[i + 8] ^= cv[i]
    return state


def _blake3_chunk_output(chunk_bytes, chunk_counter, flags):
    cv = list(_BLAKE3_IV)
    num_blocks = max(1, (len(chunk_bytes) + 63) // 64)
    for b in range(num_blocks):
        start = b * 64
        block = chunk_bytes[start:start + 64]
        block_len = len(block)
        if block_len < 64:
            block = block + b'\x00' * (64 - block_len)
        words = struct.unpack('<16I', block)
        b_flags = flags
        if b == 0:
            b_flags |= _BLAKE3_CHUNK_START
        if b == num_blocks - 1:
            b_flags |= _BLAKE3_CHUNK_END
            return (cv, words, chunk_counter, block_len, b_flags)
        cv = _blake3_compress(cv, words, chunk_counter, block_len, b_flags)[:8]


def blake3_hex(data):
    """Compute the 64-character lowercase hex BLAKE3 digest of ``data`` in memory."""
    raw = bytes(data)
    if _blake3_ext is not None:
        return _blake3_ext.blake3(raw).hexdigest()
    num_chunks = max(1, (len(raw) + 1023) // 1024)
    cv_stack = []
    for c in range(num_chunks):
        chunk = raw[c * 1024:(c + 1) * 1024]
        out = _blake3_chunk_output(chunk, c, 0)
        if num_chunks == 1:
            words = _blake3_compress(out[0], out[1], out[2], out[3], out[4] | _BLAKE3_ROOT)[:8]
            return struct.pack('<8I', *words).hex()
        cv = _blake3_compress(*out)[:8]
        total_chunks = c + 1
        while (total_chunks & 1) == 0 and (len(cv_stack) > 1 or c + 1 < num_chunks):
            left_cv = cv_stack.pop()
            block_words = tuple(left_cv) + tuple(cv)
            cv = _blake3_compress(_BLAKE3_IV, block_words, 0, 64, _BLAKE3_PARENT)[:8]
            total_chunks >>= 1
        cv_stack.append(cv)
    while len(cv_stack) > 1:
        right_cv = cv_stack.pop()
        left_cv = cv_stack.pop()
        block_words = tuple(left_cv) + tuple(right_cv)
        fl = _BLAKE3_PARENT | (_BLAKE3_ROOT if not cv_stack else 0)
        if fl & _BLAKE3_ROOT:
            words = _blake3_compress(_BLAKE3_IV, block_words, 0, 64, fl)[:8]
            return struct.pack('<8I', *words).hex()
        cv_stack.append(_blake3_compress(_BLAKE3_IV, block_words, 0, 64, fl)[:8])


def _normalize_version_ref(pin):
    if isinstance(pin, Mapping) and set(pin.keys()) <= {'dataset', 'version', 'manifest'} and 'dataset' in pin and 'version' in pin:
        res = dict(dataset=str(pin['dataset']), version=str(pin['version']))
        manifest = pin.get('manifest')
        if manifest is not None:
            res['manifest'] = dict(manifest) if isinstance(manifest, Mapping) else str(manifest)
        return res
    if isinstance(pin, Mapping) and 'id' in pin and isinstance(pin.get('dataset'), Mapping) and 'dataset' in pin['dataset']:
        res = dict(dataset=str(pin['dataset']['dataset']), version=str(pin['id']))
        manifest = pin.get('manifest')
        if manifest is not None:
            res['manifest'] = dict(manifest) if isinstance(manifest, Mapping) else str(manifest)
        return res
    raise ValueError(f'Expected a ReleasePin or VersionRef dict, got: {pin!r}')


class PartitionTransformSpec(dict):
    """Exact serde representation of ``docspec_core::PartitionTransformSpec``."""

    VALID_KINDS = frozenset({'identity', 'bucket', 'year', 'month', 'day', 'truncate'})

    def __init__(self, kind='identity', **kwargs):
        normalized = self._validate(kind, **kwargs)
        super().__init__(normalized)

    @classmethod
    def _validate(cls, kind, **kwargs):
        if isinstance(kind, dict):
            if kwargs:
                raise ValueError('Cannot pass extra keyword arguments when normalizing a transform dict')
            raw = dict(kind)
            kind_name = raw.pop('kind', None)
            return cls._validate(kind_name, **raw)
        if not isinstance(kind, str) or kind not in cls.VALID_KINDS:
            raise ValueError(f'Invalid PartitionTransformSpec kind: {kind!r}')
        if kind in {'identity', 'year', 'month', 'day'}:
            if kwargs:
                raise ValueError(f'Transform {kind!r} does not accept extra fields: {sorted(kwargs)!r}')
            return dict(kind=kind)
        if kind == 'bucket':
            if set(kwargs) != {'num_buckets'}:
                raise ValueError(f'Bucket transform requires only num_buckets, got: {sorted(kwargs)!r}')
            num_buckets = kwargs['num_buckets']
            if type(num_buckets) is not int or not 1 <= num_buckets <= 4096:
                raise ValueError('Bucket transform num_buckets must be an integer in 1..=4096')
            return dict(kind='bucket', num_buckets=num_buckets)
        if kind == 'truncate':
            if set(kwargs) != {'width'}:
                raise ValueError(f'Truncate transform requires only width, got: {sorted(kwargs)!r}')
            width = kwargs['width']
            if type(width) is not int or width < 1:
                raise ValueError('Truncate transform width must be a positive integer')
            return dict(kind='truncate', width=width)
        raise ValueError(f'Unhandled PartitionTransformSpec kind: {kind!r}')

    @classmethod
    def normalize(cls, spec):
        if isinstance(spec, cls):
            return dict(spec)
        if isinstance(spec, str):
            return dict(cls(spec))
        if isinstance(spec, dict):
            return dict(cls(spec))
        raise ValueError(f'Invalid partition transform specification: {spec!r}')

    @classmethod
    def identity(cls):
        return cls('identity')

    @classmethod
    def bucket(cls, num_buckets=64):
        return cls('bucket', num_buckets=num_buckets)

    @classmethod
    def year(cls):
        return cls('year')

    @classmethod
    def month(cls):
        return cls('month')

    @classmethod
    def day(cls):
        return cls('day')

    @classmethod
    def truncate(cls, width):
        return cls('truncate', width=width)

    def to_dict(self):
        return dict(self)


class PartitionFieldSpec(dict):
    """Exact serde representation of ``docspec_core::PartitionFieldSpec``."""

    def __init__(self, column, transform='identity', *, name=None):
        if not isinstance(column, str) or not column.strip():
            raise ValueError('PartitionFieldSpec column must be a non-empty string')
        payload = dict(
            column=column,
            transform=PartitionTransformSpec.normalize(transform),
        )
        if name is not None:
            if not isinstance(name, str) or not name.strip():
                raise ValueError('PartitionFieldSpec name must be a non-empty string when provided')
            payload['name'] = name
        super().__init__(payload)

    @property
    def column(self):
        return self['column']

    @property
    def transform(self):
        return self['transform']

    @property
    def name(self):
        return self.get('name')

    @classmethod
    def normalize(cls, spec):
        if isinstance(spec, cls):
            return dict(spec)
        if isinstance(spec, dict):
            allowed = {'column', 'transform', 'name'}
            unknown = set(spec) - allowed
            if unknown:
                raise ValueError(f'Unknown PartitionFieldSpec fields: {sorted(unknown)!r}')
            if 'column' not in spec:
                raise ValueError('PartitionFieldSpec requires column')
            return dict(
                cls(
                    spec['column'],
                    spec.get('transform', 'identity'),
                    name=spec.get('name'),
                )
            )
        raise ValueError(f'Invalid PartitionFieldSpec: {spec!r}')

    def to_dict(self):
        return dict(self)


class PartitionSpec:
    """Declarative builder for ``RunSpec.partition_by`` specifications."""

    @staticmethod
    def identity(column, *, name=None):
        return PartitionFieldSpec(column, PartitionTransformSpec.identity(), name=name)

    @staticmethod
    def bucket(column, num_buckets=64, *, name=None):
        return PartitionFieldSpec(column, PartitionTransformSpec.bucket(num_buckets), name=name)

    @staticmethod
    def year(column, *, name=None):
        return PartitionFieldSpec(column, PartitionTransformSpec.year(), name=name)

    @staticmethod
    def month(column, *, name=None):
        return PartitionFieldSpec(column, PartitionTransformSpec.month(), name=name)

    @staticmethod
    def day(column, *, name=None):
        return PartitionFieldSpec(column, PartitionTransformSpec.day(), name=name)

    @staticmethod
    def truncate(column, width, *, name=None):
        return PartitionFieldSpec(column, PartitionTransformSpec.truncate(width), name=name)

    @staticmethod
    def normalize(partition_by):
        if partition_by is None:
            return None
        if isinstance(partition_by, (PartitionFieldSpec, dict)):
            items = [partition_by]
        elif isinstance(partition_by, (list, tuple)):
            items = list(partition_by)
        else:
            raise ValueError(f'Invalid partition_by specification: {partition_by!r}')
        return [PartitionFieldSpec.normalize(item) for item in items]


class UpdateMergeStrategy:
    """Valid column merge strategies for ``UpdateMergeSpec``."""

    REPLACE = 'replace'
    LATEST_OR_BACKFILL = 'latest_or_backfill'
    MIN = 'min'
    MAX = 'max'
    SET_UNION = 'set_union'
    ALL = frozenset({REPLACE, LATEST_OR_BACKFILL, MIN, MAX, SET_UNION})


class UpdateMergeSpec(dict):
    """Exact serde representation of ``docspec_core::UpdateMergeSpec``."""

    def __init__(self, order_by=None, columns=None):
        payload = {}
        if order_by is not None:
            if not isinstance(order_by, str) or not order_by.strip():
                raise ValueError('UpdateMergeSpec order_by must be a non-empty string when provided')
            payload['order_by'] = order_by
        normalized_cols = {}
        if columns is not None:
            if not isinstance(columns, dict):
                raise ValueError('UpdateMergeSpec columns must be a mapping of column -> strategy')
            for col, strategy in columns.items():
                if not isinstance(col, str) or not col.strip():
                    raise ValueError(f'UpdateMergeSpec column name must be a non-empty string: {col!r}')
                if not isinstance(strategy, str) or strategy not in UpdateMergeStrategy.ALL:
                    raise ValueError(f'Invalid UpdateMergeStrategy {strategy!r} for column {col!r}')
                normalized_cols[col] = strategy
        payload['columns'] = normalized_cols
        super().__init__(payload)

    @property
    def order_by(self):
        return self.get('order_by')

    @property
    def columns(self):
        return self['columns']

    @classmethod
    def first_seen(cls, columns=None):
        return cls(order_by=None, columns=columns)

    @classmethod
    def max_by(cls, order_by, columns=None):
        return cls(order_by=order_by, columns=columns)

    @classmethod
    def latest_or_backfill(cls, order_by, *column_names):
        return cls(
            order_by=order_by,
            columns={col: UpdateMergeStrategy.LATEST_OR_BACKFILL for col in column_names},
        )

    @classmethod
    def normalize(cls, spec):
        if spec is None:
            return None
        if isinstance(spec, cls):
            return dict(spec)
        if isinstance(spec, dict):
            unknown = set(spec) - {'order_by', 'columns'}
            if unknown:
                raise ValueError(f'Unknown UpdateMergeSpec fields: {sorted(unknown)!r}')
            return dict(cls(order_by=spec.get('order_by'), columns=spec.get('columns')))
        raise ValueError(f'Invalid UpdateMergeSpec: {spec!r}')

    def to_dict(self):
        return dict(self)


def _merge_row_pair(existing_row, incoming_row, *, keys, order_by, columns, field_names):
    if order_by is not None and (order_by in existing_row or order_by in incoming_row):
        ev = existing_row.get(order_by)
        iv = incoming_row.get(order_by)
        if ev is None:
            incoming_is_newer = True
        elif iv is None:
            incoming_is_newer = False
        else:
            incoming_is_newer = iv >= ev
    else:
        incoming_is_newer = True

    winner = incoming_row if incoming_is_newer else existing_row
    loser = existing_row if incoming_is_newer else incoming_row
    key_set = set(keys)
    merged = {}
    for col in field_names:
        if col in key_set:
            merged[col] = incoming_row.get(col) if col in incoming_row else existing_row.get(col)
            continue
        strategy = columns.get(col, UpdateMergeStrategy.REPLACE)
        if strategy == UpdateMergeStrategy.REPLACE:
            merged[col] = winner[col] if col in winner else loser.get(col)
        elif strategy == UpdateMergeStrategy.LATEST_OR_BACKFILL:
            w_val = winner.get(col)
            merged[col] = w_val if w_val is not None else loser.get(col)
        elif strategy == UpdateMergeStrategy.MIN:
            a, b = existing_row.get(col), incoming_row.get(col)
            if a is None:
                merged[col] = b
            elif b is None:
                merged[col] = a
            else:
                merged[col] = a if a <= b else b
        elif strategy == UpdateMergeStrategy.MAX:
            a, b = existing_row.get(col), incoming_row.get(col)
            if a is None:
                merged[col] = b
            elif b is None:
                merged[col] = a
            else:
                merged[col] = a if a >= b else b
        elif strategy == UpdateMergeStrategy.SET_UNION:
            a_list = existing_row.get(col)
            b_list = incoming_row.get(col)
            if a_list is None and b_list is None:
                merged[col] = None
            elif isinstance(a_list, bool) or isinstance(b_list, bool):
                merged[col] = bool(a_list) or bool(b_list)
            else:
                items = [x for x in (a_list or ()) if x is not None] + [
                    x for x in (b_list or ()) if x is not None
                ]
                merged[col] = sorted(set(items))
        else:
            raise ValueError(f'Unknown merge strategy: {strategy!r}')
    return merged


def apply_update_merge_spec(
    existing_table,
    incoming_table,
    *,
    keys,
    merge_spec=None,
    merge=None,
    deletions=None,
    include_unmatched_existing=True,
):
    """Apply ``UpdateMergeSpec`` semantics deterministically over Arrow tables or row lists."""
    spec = merge_spec if merge_spec is not None else merge
    normalized = UpdateMergeSpec.normalize(spec)
    if normalized is None:
        normalized = {'order_by': None, 'columns': {}}
    order_by = normalized.get('order_by')
    columns = normalized.get('columns', {})
    schema = incoming_table.schema if isinstance(incoming_table, pa.Table) else (
        existing_table.schema if isinstance(existing_table, pa.Table) else None
    )
    existing_rows = existing_table.to_pylist() if isinstance(existing_table, pa.Table) else list(existing_table or ())
    incoming_rows = incoming_table.to_pylist() if isinstance(incoming_table, pa.Table) else list(incoming_table or ())
    if schema is not None:
        field_names = list(schema.names)
    else:
        seen_fields = []
        for r in existing_rows + incoming_rows:
            for k in r:
                if k not in seen_fields:
                    seen_fields.append(k)
        field_names = seen_fields

    if field_names:
        columns = {k: v for k, v in columns.items() if k in field_names}
        if order_by is not None and order_by not in field_names:
            order_by = None

    def row_key(row):
        return tuple(row.get(k) for k in keys)

    deleted_keys = set()
    if deletions is not None:
        del_rows = deletions.to_pylist() if isinstance(deletions, pa.Table) else list(deletions or ())
        for d in del_rows:
            if isinstance(d, dict):
                deleted_keys.add(row_key(d))
            elif len(keys) == 1:
                deleted_keys.add((d,))

    # 1. Intra-batch deduplication of incoming_rows
    dedup_incoming = {}
    for row in incoming_rows:
        k = row_key(row)
        if k in deleted_keys:
            continue
        norm_row = dict(row)
        for col, strategy in columns.items():
            val = norm_row.get(col)
            if strategy == UpdateMergeStrategy.SET_UNION and val is not None and not isinstance(val, bool):
                norm_row[col] = sorted({x for x in val if x is not None})
        if k in dedup_incoming:
            dedup_incoming[k] = _merge_row_pair(
                dedup_incoming[k],
                norm_row,
                keys=keys,
                order_by=order_by,
                columns=columns,
                field_names=field_names,
            )
        else:
            dedup_incoming[k] = norm_row

    # 2. Merge against matching rows in existing_rows
    existing_by_key = {}
    for row in existing_rows:
        k = row_key(row)
        if k in deleted_keys:
            continue
        if k in existing_by_key:
            existing_by_key[k] = _merge_row_pair(
                existing_by_key[k],
                row,
                keys=keys,
                order_by=order_by,
                columns=columns,
                field_names=field_names,
            )
        else:
            existing_by_key[k] = dict(row)

    if include_unmatched_existing:
        out_by_key = dict(existing_by_key)
        for k, inc_row in dedup_incoming.items():
            if k in out_by_key:
                out_by_key[k] = _merge_row_pair(
                    out_by_key[k],
                    inc_row,
                    keys=keys,
                    order_by=order_by,
                    columns=columns,
                    field_names=field_names,
                )
            else:
                out_by_key[k] = inc_row
        merged_rows = list(out_by_key.values())
    else:
        merged_rows = []
        for k, inc_row in dedup_incoming.items():
            if k in existing_by_key:
                merged_rows.append(
                    _merge_row_pair(
                        existing_by_key[k],
                        inc_row,
                        keys=keys,
                        order_by=order_by,
                        columns=columns,
                        field_names=field_names,
                    )
                )
            else:
                merged_rows.append(inc_row)

    if schema is not None:
        return pa.Table.from_pylist(merged_rows, schema=schema)
    return merged_rows


class ConnectedEdgeSpec(dict):
    """Exact serde representation of ``docspec_core::ConnectedEdgeSpec``."""

    def __init__(self, namespace, column):
        if not isinstance(namespace, str) or not namespace.strip():
            raise ValueError('ConnectedEdgeSpec namespace must be a non-empty string')
        if not isinstance(column, str) or not column.strip():
            raise ValueError('ConnectedEdgeSpec column must be a non-empty string')
        super().__init__(namespace=namespace, column=column)

    @classmethod
    def normalize(cls, spec):
        if isinstance(spec, cls):
            return dict(spec)
        if isinstance(spec, (tuple, list)) and len(spec) == 2:
            return dict(cls(spec[0], spec[1]))
        if isinstance(spec, dict):
            unknown = set(spec) - {'namespace', 'column'}
            if unknown:
                raise ValueError(f'Unknown ConnectedEdgeSpec fields: {sorted(unknown)!r}')
            return dict(cls(spec.get('namespace'), spec.get('column')))
        raise ValueError(f'Invalid ConnectedEdgeSpec: {spec!r}')


class SortDirection:
    ASC = 'asc'
    DESC = 'desc'
    ALL = frozenset({ASC, DESC})


class SortColumn(dict):
    """Exact serde representation of ``docspec_core::SortColumn``."""

    def __init__(self, column, direction=SortDirection.ASC):
        if not isinstance(column, str) or not column.strip():
            raise ValueError('SortColumn column must be a non-empty string')
        if not isinstance(direction, str) or direction not in SortDirection.ALL:
            raise ValueError(f'SortColumn direction must be one of {sorted(SortDirection.ALL)!r}')
        super().__init__(column=column, direction=direction)

    @classmethod
    def normalize(cls, spec):
        if isinstance(spec, cls):
            return dict(spec)
        if isinstance(spec, str):
            return dict(cls(spec, SortDirection.ASC))
        if isinstance(spec, (tuple, list)) and len(spec) == 2:
            return dict(cls(spec[0], spec[1]))
        if isinstance(spec, dict):
            unknown = set(spec) - {'column', 'field', 'direction'}
            if unknown:
                raise ValueError(f'Unknown SortColumn fields: {sorted(unknown)!r}')
            col = spec.get('column') if 'column' in spec else spec.get('field')
            return dict(cls(col, spec.get('direction', SortDirection.ASC)))
        raise ValueError(f'Invalid SortColumn: {spec!r}')


class AggregateSpec:
    """Builders for ``docspec_core::AggregateColumn``."""

    VALID_KINDS = frozenset({
        'count_rows', 'count_distinct', 'sum', 'min', 'max', 'collect_set', 'first_value',
    })

    @staticmethod
    def count_rows(name='total_rows'):
        return dict(name=str(name), function=dict(kind='count_rows'))

    @staticmethod
    def count(name_or_field='total_rows', field=None, *, name=None):
        if name is not None:
            return dict(name=str(name), function=dict(kind='count_rows'))
        return dict(name=str(name_or_field), function=dict(kind='count_rows'))

    @staticmethod
    def count_distinct(name_or_field, field=None, *, name=None):
        if name is not None:
            return dict(name=str(name), function=dict(kind='count_distinct', field=str(name_or_field)))
        return dict(name=str(name_or_field), function=dict(kind='count_distinct', field=str(field or name_or_field)))

    @staticmethod
    def sum(name_or_field, field=None, *, name=None):
        if name is not None:
            return dict(name=str(name), function=dict(kind='sum', field=str(name_or_field)))
        return dict(name=str(name_or_field), function=dict(kind='sum', field=str(field or name_or_field)))

    @staticmethod
    def min(name_or_field, field=None, *, name=None):
        if name is not None:
            return dict(name=str(name), function=dict(kind='min', field=str(name_or_field)))
        return dict(name=str(name_or_field), function=dict(kind='min', field=str(field or name_or_field)))

    @staticmethod
    def max(name_or_field, field=None, *, name=None):
        if name is not None:
            return dict(name=str(name), function=dict(kind='max', field=str(name_or_field)))
        return dict(name=str(name_or_field), function=dict(kind='max', field=str(field or name_or_field)))

    @staticmethod
    def collect_set(name_or_field, field=None, *, name=None):
        if name is not None:
            return dict(name=str(name), function=dict(kind='collect_set', field=str(name_or_field)))
        return dict(name=str(name_or_field), function=dict(kind='collect_set', field=str(field or name_or_field)))

    @staticmethod
    def first_value(name_or_field, field=None, *, name=None):
        if name is not None:
            return dict(name=str(name), function=dict(kind='first_value', field=str(name_or_field)))
        return dict(name=str(name_or_field), function=dict(kind='first_value', field=str(field or name_or_field)))

    @classmethod
    def normalize(cls, spec):
        if not isinstance(spec, dict):
            raise ValueError(f'Invalid AggregateColumn specification: {spec!r}')
        unknown = set(spec) - {'name', 'function'}
        if unknown:
            raise ValueError(f'Unknown AggregateColumn fields: {sorted(unknown)!r}')
        name = spec.get('name')
        fn = spec.get('function')
        if not isinstance(name, str) or not name.strip() or not isinstance(fn, dict):
            raise ValueError(f'Invalid AggregateColumn specification: {spec!r}')
        kind = fn.get('kind')
        if kind not in cls.VALID_KINDS:
            raise ValueError(f'Invalid AggregateFunction kind: {kind!r}')
        if kind == 'count_rows':
            if set(fn) != {'kind'}:
                raise ValueError('count_rows aggregate does not take extra fields')
            return dict(name=name, function=dict(kind='count_rows'))
        if set(fn) != {'kind', 'field'} or not isinstance(fn.get('field'), str) or not fn['field'].strip():
            raise ValueError(f'AggregateFunction {kind!r} requires a non-empty field name')
        return dict(name=name, function=dict(kind=kind, field=fn['field']))


class ConnectedComponentsTransform(dict):
    """Exact serde representation of ``RefreshTransform::ConnectedComponents``."""

    def __init__(
        self,
        input_pin=None,
        *,
        row_key='source_id',
        entity_key=None,
        edges=(
            dict(namespace='canonical', column='canonical_key'),
            dict(namespace='body', column='connectable_body_key'),
        ),
        order_by=('priority_rank', 'source_id'),
        document_id_column='document_id',
        component_id_column=None,
        aggregates=(),
        outputs=None,
    ):
        effective_row_key = entity_key if entity_key is not None else row_key
        effective_doc_id = component_id_column if component_id_column is not None else document_id_column
        effective_aggregates = outputs if outputs is not None else aggregates
        if not isinstance(effective_row_key, str) or not effective_row_key.strip():
            raise ValueError('ConnectedComponentsTransform row_key must be a non-empty string')
        if not isinstance(effective_doc_id, str) or not effective_doc_id.strip():
            raise ValueError('ConnectedComponentsTransform document_id_column must be a non-empty string')
        normalized_edges = [ConnectedEdgeSpec.normalize(e) for e in (edges or ())]
        if not normalized_edges:
            raise ValueError('ConnectedComponentsTransform requires at least one edge specification')
        normalized_order_by = [SortColumn.normalize(c) for c in (order_by or ())]
        normalized_aggregates = [AggregateSpec.normalize(a) for a in (effective_aggregates or ())]
        payload = dict(
            kind='connected_components',
            row_key=effective_row_key,
            edges=normalized_edges,
            order_by=normalized_order_by,
            document_id_column=effective_doc_id,
            aggregates=normalized_aggregates,
        )
        if input_pin is not None:
            payload['input'] = _normalize_version_ref(input_pin)
        super().__init__(payload)

    def to_dict(self):
        return dict(self)


def native_storage_schema(schema_or_table, *, native_types=False):
    """Use lossless Iceberg types for unsigned values and binary offsets.

    The application retains the original schema in its immutable selection.
    Native pins describe the physical representation; schema-bound reads restore
    application types with Arrow's checked cast. UInt64 uses Decimal128(20, 0);
    Binary uses LargeBinary to match the native nested writer unless ``native_types=True``
    is requested for a Wave 1D+ runtime.
    """
    is_table = isinstance(schema_or_table, pa.Table)
    schema = schema_or_table.schema if is_table else schema_or_table
    if native_types:
        return schema_or_table if is_table else schema

    def field(value):
        return value.with_type(data_type(value.type))

    def data_type(value):
        if pa.types.is_uint64(value):
            return pa.decimal128(20, 0)
        if pa.types.is_binary(value):
            return pa.large_binary()
        if pa.types.is_struct(value):
            return pa.struct([field(child) for child in value])
        if pa.types.is_list(value):
            return pa.list_(field(value.value_field))
        if pa.types.is_large_list(value):
            return pa.large_list(field(value.value_field))
        if pa.types.is_fixed_size_list(value):
            return pa.list_(field(value.value_field), value.list_size)
        if pa.types.is_map(value):
            return pa.map_(field(value.key_field), field(value.item_field),
                           keys_sorted=value.keys_sorted)
        return value

    target_schema = pa.schema([field(value) for value in schema], metadata=schema.metadata)
    if is_table:
        return (
            schema_or_table
            if target_schema.equals(schema_or_table.schema, check_metadata=True)
            else schema_or_table.cast(target_schema, safe=True)
        )
    return target_schema


def _merge_field_type(physical_type, expected_type):
    """Validate and resolve a physical Arrow type against an expected application type."""
    if pa.types.is_struct(physical_type) and pa.types.is_struct(expected_type):
        if physical_type.num_fields != expected_type.num_fields:
            raise ValueError(
                f'Native source storage schema ({physical_type}) differs from '
                f'the selected application schema ({expected_type})'
            )
        for i in range(expected_type.num_fields):
            _merge_field_type(physical_type[i].type, expected_type[i].type)
        return expected_type
    if (pa.types.is_list(physical_type) or pa.types.is_large_list(physical_type)) and (
            pa.types.is_list(expected_type) or pa.types.is_large_list(expected_type)):
        _merge_field_type(physical_type.value_type, expected_type.value_type)
        return expected_type
    expected_physical = native_storage_schema(pa.schema([pa.field('x', expected_type)])).field(0).type
    if physical_type != expected_physical and physical_type != expected_type:
        raise ValueError(
            f'Native source storage schema ({physical_type}) differs from '
            f'the selected application schema ({expected_type})'
        )
    return expected_type


def application_schema(schema, expected_schema=None):
    """Inverse of :func:`native_storage_schema` for checked readback casts.

    Supports both Wave 1D+ native ``UInt64`` / ``Binary`` columns and legacy
    ``Decimal128(20, 0)`` / ``LargeBinary`` columns. When ``expected_schema`` is
    supplied, ``Decimal128(20, 0)`` is restored to ``UInt64`` only where the
    declared application field is ``UInt64``; genuine ``Decimal128`` fields
    remain ``Decimal128``.
    """
    if expected_schema is not None:
        fields = []
        expected_by_name = {f.name: f for f in expected_schema}
        for physical_field in schema:
            if physical_field.name.startswith('__docspec_') and physical_field.name not in expected_by_name:
                fields.append(physical_field)
                continue
            target_field = expected_by_name.get(physical_field.name)
            if target_field is None:
                raise ValueError(
                    f'Unexpected field {physical_field.name!r} not in expected application schema'
                )
            _merge_field_type(physical_field.type, target_field.type)
            fields.append(target_field)
        return pa.schema(fields, metadata=expected_schema.metadata)

    def field(value):
        return value.with_type(data_type(value.type))

    def data_type(value):
        if pa.types.is_decimal128(value) and value.precision == 20 and value.scale == 0:
            return pa.uint64()
        if pa.types.is_large_binary(value):
            return pa.binary()
        if pa.types.is_struct(value):
            return pa.struct([field(child) for child in value])
        if pa.types.is_list(value) or pa.types.is_large_list(value):
            return pa.list_(field(value.value_field))
        if pa.types.is_fixed_size_list(value):
            return pa.list_(field(value.value_field), value.list_size)
        if pa.types.is_map(value):
            return pa.map_(field(value.key_field), field(value.item_field),
                           keys_sorted=value.keys_sorted)
        return value

    return pa.schema([field(value) for value in schema], metadata=schema.metadata)


def _cast_column(column, target_type):
    if column.type == target_type:
        return column
    try:
        return column.cast(target_type, safe=True)
    except pa.ArrowNotImplementedError:
        if isinstance(column, pa.ChunkedArray):
            chunks = [_cast_array(chunk, target_type) for chunk in column.chunks]
            return pa.chunked_array(chunks, type=target_type)
        return _cast_array(column, target_type)


def _cast_array(array, target_type):
    if array.type == target_type:
        return array
    if pa.types.is_struct(target_type):
        children = [
            _cast_array(array.field(i), target_type[i].type)
            for i in range(target_type.num_fields)
        ]
        return pa.StructArray.from_arrays(
            children,
            fields=list(target_type),
            mask=array.is_null() if array.null_count else None,
        )
    if pa.types.is_list(target_type) or pa.types.is_large_list(target_type):
        values = _cast_array(array.values, target_type.value_type)
        if pa.types.is_large_list(target_type):
            return pa.LargeListArray.from_arrays(array.offsets, values, type=target_type)
        return pa.ListArray.from_arrays(array.offsets, values, type=target_type)
    return array.cast(target_type, safe=True)


def restore_application_schema(table, expected_schema=None):
    """Restore an Arrow Table from native storage types to ``expected_schema``."""
    target_schema = application_schema(table.schema, expected_schema=expected_schema)
    if table.schema.equals(target_schema, check_metadata=True):
        return table
    columns = [
        _cast_column(table.column(i), target_schema.field(i).type)
        for i in range(len(target_schema))
    ]
    return pa.Table.from_arrays(columns, schema=target_schema)


def encode_arrow_ipc_stream(table, *, native_types=False):
    """Serialize an Arrow Table, RecordBatch, or RecordBatchReader into an Arrow IPC stream."""
    if isinstance(table, pa.RecordBatch):
        table = pa.Table.from_batches([table])
    elif isinstance(table, pa.RecordBatchReader):
        table = table.read_all()
    if not isinstance(table, pa.Table):
        raise TypeError('encode_arrow_ipc_stream requires a pyarrow.Table, RecordBatch, or RecordBatchReader')
    prepared = table if native_types else native_storage_schema(table)
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, prepared.schema) as writer:
        writer.write_table(prepared)
    return sink.getvalue().to_pybytes()


def build_update_merge_spec(*, order_by='recorded_at', columns=None):
    """Build a canonical DocSpec ``UpdateMergeSpec`` dictionary matching ``src/model.rs``."""
    spec = {}
    if order_by is not None:
        if isinstance(order_by, str):
            if not order_by.strip():
                raise ValueError('UpdateMergeSpec order_by must be a non-empty column name or None')
            spec['order_by'] = order_by
        elif isinstance(order_by, (list, tuple)):
            if not order_by:
                raise ValueError('UpdateMergeSpec order_by list must not be empty')
            spec['order_by'] = list(order_by)
        else:
            raise ValueError('UpdateMergeSpec order_by must be a non-empty column name, list, or None')
    if columns is not None:
        if not isinstance(columns, dict):
            raise ValueError('UpdateMergeSpec columns must be a dict mapping column_name -> strategy')
        normalized_cols = {}
        for col_name, strategy in columns.items():
            if not isinstance(col_name, str) or not col_name.strip():
                raise ValueError('UpdateMergeSpec column names must be non-empty strings')
            if isinstance(strategy, dict) and 'kind' in strategy:
                strategy = strategy['kind']
            strategy_str = str(strategy).lower()
            if strategy_str not in VALID_UPDATE_MERGE_STRATEGIES:
                raise ValueError(
                    f'Invalid UpdateMergeStrategy {strategy!r}; expected one of {VALID_UPDATE_MERGE_STRATEGIES}'
                )
            normalized_cols[col_name] = strategy_str
        if normalized_cols:
            spec['columns'] = normalized_cols
    return spec


def build_ipc_run_spec(
    dataset,
    *,
    operation,
    definition,
    sql='SELECT * FROM input',
    base=None,
    relationship=None,
    input=None,
    expected_digest=None,
):
    """Build a canonical ``IpcRunSpec`` matching ``src/http/ipc.rs``."""
    spec = {
        'dataset': str(dataset),
        'operation': str(operation),
        'definition': str(definition),
        'sql': str(sql),
    }
    if base is not None:
        spec['base'] = str(base)
    if relationship is not None:
        spec['relationship'] = dict(relationship)
    if input is not None:
        spec['input'] = str(input)
    if expected_digest is not None:
        spec['expected_digest'] = str(expected_digest)
    return spec


def build_ipc_update_spec(
    dataset,
    *,
    operation,
    definition,
    base,
    keys,
    replacement_path=None,
    replacement_digest=None,
    relationship=None,
    deletions=None,
    merge=None,
):
    """Build a canonical ``IpcUpdateSpec`` matching ``src/http/ipc.rs``."""
    replacements = {}
    if replacement_path is not None:
        replacements['path'] = str(replacement_path)
    if replacement_digest is not None:
        replacements['digest'] = str(replacement_digest)
    spec = {
        'dataset': str(dataset),
        'operation': str(operation),
        'definition': str(definition),
        'base': str(base),
        'keys': [str(k) for k in keys],
        'replacements': replacements,
    }
    if relationship is not None:
        spec['relationship'] = dict(relationship)
    if deletions is not None:
        spec['deletions'] = dict(deletions)
    if merge is not None:
        if hasattr(merge, 'to_dict'):
            merge = merge.to_dict()
        spec['merge'] = (
            build_update_merge_spec(
                order_by=merge.get('order_by'),
                columns=merge.get('columns'),
            )
            if isinstance(merge, dict)
            else merge
        )
    return spec


def _write_producer_parquet(table, path, *, row_group_size=PRODUCER_PARQUET_ROW_GROUP_SIZE):
    """Write producer Parquet inputs with bounded row groups so zero-copy Arrow slices stay within max_batch_bytes."""
    physical = native_storage_schema(table.schema)
    stored = table if physical.equals(table.schema, check_metadata=True) else table.cast(physical, safe=True)
    if row_group_size is None and stored.nbytes <= 8_388_608:
        pq.write_table(stored, path, compression='zstd')
        return
    effective_rg = row_group_size or 4096
    if stored.num_rows > 1 and stored.nbytes > 4_000_000:
        avg_row_bytes = max(1, stored.nbytes // stored.num_rows)
        default_step = max(1, min(effective_rg, 1_500_000 // avg_row_bytes))
        with pq.ParquetWriter(path, physical, compression='zstd') as writer:
            offset = 0
            total_rows = stored.num_rows
            while offset < total_rows:
                step = min(default_step, total_rows - offset)
                chunk = stored.slice(offset, step)
                while step > 1 and chunk.nbytes > 1_500_000:
                    step = max(1, step // 2)
                    chunk = stored.slice(offset, step)
                writer.write_table(chunk, row_group_size=step)
                offset += step
        return
    if stored.num_rows > 1 and stored.nbytes > 1_500_000:
        avg_row_bytes = max(1, stored.nbytes // stored.num_rows)
        effective_rg = max(1, min(effective_rg, 1_500_000 // avg_row_bytes))
    pq.write_table(stored, path, compression='zstd', row_group_size=effective_rg)


def producer_input_entry(request_path):
    """Return the producer files referenced by a retained request, with total bytes."""
    try:
        request = json.loads(Path(request_path).read_text())
    except (OSError, ValueError):
        request = None
    if not isinstance(request, dict):
        return None
    paths = []
    for value in (request.get('input'),
                  (request.get('replacements') or {}).get('path')
                  if isinstance(request.get('replacements'), dict) else None,
                  (request.get('deletions') or {}).get('path')
                  if isinstance(request.get('deletions'), dict) else None):
        if isinstance(value, str) and value and value not in paths:
            paths.append(value)
    if not paths:
        return None
    files = []
    total = 0
    for path in paths:
        try:
            size = Path(path).stat().st_size
        except FileNotFoundError:
            size = None
        else:
            total += size
        files.append(dict(path=path, bytes=size))
    return dict(input=paths[0], request=str(request_path), bytes=total, files=files)


def _normalize_sort_column(item):
    if not isinstance(item, dict) or not isinstance(item.get('column'), str) or not item['column'].strip():
        raise ValueError('SortColumn requires a non-empty column name')
    direction = item.get('direction')
    if direction is None:
        direction = 'desc' if item.get('descending', False) else 'asc'
    direction = str(direction).lower()
    if direction not in ('asc', 'desc'):
        raise ValueError("SortColumn direction must be 'asc' or 'desc'")
    return {
        'column': item['column'],
        'direction': direction,
        'nulls_first': bool(item.get('nulls_first', False)),
    }


def _normalize_scalar_expr(expr):
    if isinstance(expr, str):
        if not expr.strip():
            raise ValueError('ScalarExpr SQL string must not be empty')
        return expr
    if not isinstance(expr, dict):
        raise ValueError('ScalarExpr must be a SQL string or a tagged AST dict')
    if 'kind' in expr:
        return dict(expr)
    if expr.get('fn') == 'count_non_null' and isinstance(expr.get('columns'), (list, tuple)):
        cols = [str(c) for c in expr['columns'] if str(c).strip()]
        if not cols:
            return '0'
        terms = [f'CASE WHEN "{c}" IS NOT NULL THEN 1 ELSE 0 END' for c in cols]
        return ' + '.join(terms)
    if 'sql' in expr and isinstance(expr['sql'], str):
        return {'kind': 'sql', 'expression': expr['sql']}
    if 'expression' in expr and isinstance(expr['expression'], str):
        return {'kind': 'sql', 'expression': expr['expression']}
    raise ValueError('ScalarExpr dict requires a valid kind or SQL expression')


def _normalize_computed_columns(computed_columns):
    if isinstance(computed_columns, dict):
        result = {}
        for name, expr in computed_columns.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError('computed_columns keys must be non-empty column names')
            result[name] = _normalize_scalar_expr(expr)
        return result
    if isinstance(computed_columns, (list, tuple)):
        result = {}
        for item in computed_columns:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get('name'), str)
                or not item['name'].strip()
                or 'expression' not in item
            ):
                raise ValueError('computed_columns list item requires name and expression')
            result[item['name']] = _normalize_scalar_expr(item['expression'])
        return result
    raise ValueError('computed_columns must be a dict mapping column_name -> ScalarExpr or a sequence of specs')


def _normalize_fold_readings(fold_readings):
    if isinstance(fold_readings, (list, tuple)):
        if len(fold_readings) != 1:
            raise ValueError('fold_readings must be a single ReadingsFoldSpec dict')
        fold_readings = fold_readings[0]
    if not isinstance(fold_readings, dict):
        raise ValueError('fold_readings must be a ReadingsFoldSpec dict')
    target_column = fold_readings.get('target_column') or fold_readings.get('name')
    if not isinstance(target_column, str) or not target_column.strip():
        raise ValueError('ReadingsFoldSpec requires a non-empty target_column')
    raw_cols = fold_readings.get('columns') if 'columns' in fold_readings else fold_readings.get('fields', ())
    columns = [str(c) for c in (raw_cols or ()) if str(c).strip()]
    include_suffixes = [str(s) for s in (fold_readings.get('include_suffixes') or ()) if str(s).strip()]
    include_prefixes = [str(p) for p in (fold_readings.get('include_prefixes') or ()) if str(p).strip()]
    if not columns and not include_suffixes and not include_prefixes:
        raise ValueError('ReadingsFoldSpec requires non-empty columns, include_suffixes, or include_prefixes')
    spec = {
        'target_column': target_column,
        'strip_suffix': bool(fold_readings.get('strip_suffix', False)),
        'drop_source_columns': bool(fold_readings.get('drop_source_columns', True)),
    }
    if columns:
        spec['columns'] = columns
    if include_suffixes:
        spec['include_suffixes'] = include_suffixes
    if include_prefixes:
        spec['include_prefixes'] = include_prefixes
    return spec


def _normalize_predicate(predicate):
    if isinstance(predicate, str):
        if not predicate.strip():
            raise ValueError('Predicate SQL string must not be empty')
        return predicate
    if not isinstance(predicate, dict):
        raise ValueError('Predicate must be a SQL string or a tagged AST dict')
    if 'kind' in predicate:
        return dict(predicate)
    op = predicate.get('op')
    col = predicate.get('column')
    if op in ('is_not_null', 'is_null') and isinstance(col, str) and col.strip():
        return {'kind': op, 'expr': {'kind': 'column', 'name': col}}
    if 'sql' in predicate and isinstance(predicate['sql'], str):
        return {'kind': 'sql', 'expression': predicate['sql']}
    raise ValueError('Predicate dict requires a valid kind')


def _normalize_facet_sets(facet_sets):
    if not isinstance(facet_sets, (list, tuple)):
        raise ValueError('facet_sets must be a list of grouping column lists')
    normalized = []
    for item in facet_sets:
        if isinstance(item, str) and item.strip():
            normalized.append([item])
        elif isinstance(item, (list, tuple)):
            cols = [str(col) for col in item if isinstance(col, str) and col.strip()]
            if not cols:
                raise ValueError('facet_sets grouping list must not be empty')
            normalized.append(cols)
        elif isinstance(item, dict) and isinstance(item.get('columns'), (list, tuple)):
            cols = [str(col) for col in item['columns'] if isinstance(col, str) and col.strip()]
            if not cols:
                raise ValueError('FacetSetSpec columns must not be empty')
            for col in cols:
                if [col] not in normalized:
                    normalized.append([col])
        else:
            raise ValueError('Each facet_sets entry must be a non-empty list of column names')
    return normalized


def _normalize_child_table_spec(spec):
    if not isinstance(spec, dict):
        raise ValueError('ChildTableExportSpec must be a dict')
    list_column = spec.get('list_column') or 'source_occurrences'
    parent_key_columns = [
        str(c) for c in (spec.get('parent_key_columns') or ('source_id',)) if str(c).strip()
    ]
    child_key_columns = [
        str(c) for c in (spec.get('child_key_columns') or ('owner_id',)) if str(c).strip()
    ]
    ordinal_column = str(spec.get('ordinal_column') or 'occurrence_order')
    row_group_rows = int(spec.get('row_group_rows', PRODUCER_PARQUET_ROW_GROUP_SIZE))
    if row_group_rows <= 0:
        raise ValueError('ChildTableExportSpec row_group_rows must be positive')
    normalized = {
        'list_column': str(list_column),
        'parent_key_columns': parent_key_columns,
        ' ordinal_column'.strip(): ordinal_column,
        'row_group_rows': row_group_rows,
        'drop_parent_column': bool(spec.get('drop_parent_column', True)),
    }
    if child_key_columns:
        normalized['child_key_columns'] = child_key_columns
    struct_cols = spec.get('struct_columns')
    if struct_cols is None and spec.get('columns'):
        excluded = set(parent_key_columns) | set(child_key_columns) | {ordinal_column, 'occurrence_is_null'}
        struct_cols = [str(c) for c in spec['columns'] if str(c) not in excluded]
    if struct_cols is not None:
        normalized['struct_columns'] = [str(c) for c in struct_cols]
    if spec.get('replace_with_count_column') is not None:
        normalized['replace_with_count_column'] = str(spec['replace_with_count_column'])
    return normalized


def _normalize_child_tables(child_tables):
    if isinstance(child_tables, dict):
        result = {}
        for name, spec in child_tables.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError('child_tables key must be a non-empty table name')
            result[name] = _normalize_child_table_spec(spec)
        return result
    if isinstance(child_tables, (list, tuple)):
        result = {}
        for item in child_tables:
            if not isinstance(item, dict) or not isinstance(item.get('name'), str) or not item['name'].strip():
                raise ValueError('child_tables list item requires a non-empty name')
            result[item['name']] = _normalize_child_table_spec(item)
        return result
    raise ValueError('child_tables must be a dict mapping name -> ChildTableExportSpec')


def build_export_policy(
    *,
    group='source',
    groups=(),
    rows='all',
    columns=(),
    filter=None,
    computed_columns=None,
    fold_readings=None,
    order_by=(),
    page_index_columns=(),
    facet_sets=(),
    browse_range_columns=(),
    child_tables=None,
    row_group_rows=None,
):
    """Build a canonical DocSpec ``ExportPolicy`` dictionary matching ``src/export.rs``."""
    resolved_groups = [str(g) for g in (groups or ()) if str(g).strip()]
    resolved_group = str(group or (resolved_groups[0] if resolved_groups else 'source'))
    if not resolved_group.strip():
        raise ValueError('ExportPolicy requires a non-empty group name')
    if rows != 'all':
        raise ValueError("ExportPolicy rows must be 'all'")
    resolved_columns = [str(c) for c in (columns or ()) if str(c).strip()]
    if not resolved_columns:
        inferred = []
        for col in page_index_columns or ():
            if str(col) not in inferred:
                inferred.append(str(col))
        for item in order_by or ():
            col = item.get('column') if isinstance(item, dict) else None
            if col and str(col) not in inferred:
                inferred.append(str(col))
        for col in browse_range_columns or ():
            if str(col) not in inferred:
                inferred.append(str(col))
        resolved_columns = inferred or ['source_id']
    policy = {
        'group': resolved_group,
        'rows': 'all',
        'columns': resolved_columns,
    }
    if resolved_groups:
        policy['groups'] = resolved_groups
    if filter is not None:
        policy['filter'] = _normalize_predicate(filter)
    if computed_columns:
        policy['computed_columns'] = _normalize_computed_columns(computed_columns)
    if fold_readings:
        policy['fold_readings'] = _normalize_fold_readings(fold_readings)
    if order_by:
        policy['order_by'] = [_normalize_sort_column(spec) for spec in order_by]
    if page_index_columns:
        policy['page_index_columns'] = [str(col) for col in page_index_columns]
    if facet_sets:
        policy['facet_sets'] = _normalize_facet_sets(facet_sets)
    if browse_range_columns:
        policy['browse_range_columns'] = [str(col) for col in browse_range_columns]
    if child_tables:
        policy['child_tables'] = _normalize_child_tables(child_tables)
    if row_group_rows is not None:
        resolved_rows = int(row_group_rows)
        if resolved_rows <= 0:
            raise ValueError('ExportPolicy row_group_rows must be positive')
        policy['row_group_rows'] = resolved_rows
    return policy


def _resolve_version_ref(dataset, source_or_version):
    if isinstance(source_or_version, dict):
        if {'dataset', 'version', 'manifest'} <= source_or_version.keys() and isinstance(source_or_version['dataset'], str):
            return {
                'dataset': source_or_version['dataset'],
                'version': source_or_version['version'],
                'manifest': dict(source_or_version['manifest']),
            }
        ds_field = source_or_version.get('dataset')
        resolved_ds = ds_field.get('dataset') if isinstance(ds_field, dict) else (ds_field if isinstance(ds_field, str) else dataset)
        resolved_ver = (
            ds_field.get('version')
            if isinstance(ds_field, dict) and 'version' in ds_field
            else source_or_version.get('id') or source_or_version.get('version')
        )
        manifest = source_or_version.get('manifest')
        if not isinstance(manifest, dict) or not {'owner', 'path', 'digest', 'bytes'} <= manifest.keys():
            raw_digest = (manifest or {}).get('digest', '0' * 64) if isinstance(manifest, dict) else '0' * 64
            raw_bytes = int((manifest or {}).get('bytes', (manifest or {}).get('size', 0))) if isinstance(manifest, dict) else 0
            raw_path = (manifest or {}).get('path', f'versions/{resolved_ver}/manifest.json') if isinstance(manifest, dict) else f'versions/{resolved_ver}/manifest.json'
            manifest = {
                'owner': str(resolved_ver or resolved_ds),
                'path': str(raw_path),
                'digest': str(raw_digest),
                'bytes': raw_bytes,
            }
        return {
            'dataset': str(resolved_ds),
            'version': str(resolved_ver),
            'manifest': manifest,
        }
    if isinstance(source_or_version, str) and source_or_version.strip():
        ver = source_or_version.strip()
        return {
            'dataset': str(dataset),
            'version': ver,
            'manifest': {
                'owner': ver,
                'path': f'versions/{ver}/manifest.json',
                'digest': '0' * 64,
                'bytes': 0,
            },
        }
    raise ValueError('ExportSpec requires a valid source VersionRef, ReleasePin, or version identifier')


def build_export_spec(
    dataset,
    *,
    operation,
    source=None,
    version=None,
    channel='viewer',
    expected=None,
    destination=None,
    policy=None,
    **policy_kwargs,
):
    """Build a canonical DocSpec ``ExportSpec`` request dictionary matching ``src/export.rs``."""
    if not isinstance(dataset, str) or not dataset.strip():
        raise ValueError('ExportSpec requires a non-empty dataset name')
    if not isinstance(operation, str) or not operation.strip():
        raise ValueError('ExportSpec requires a non-empty operation identifier')
    if not isinstance(channel, str) or not channel.strip():
        raise ValueError('ExportSpec requires a non-empty channel name')
    resolved_source = _resolve_version_ref(dataset, source if source is not None else version)
    if policy is None:
        resolved_policy = build_export_policy(**policy_kwargs)
    elif policy_kwargs:
        merged = {**policy, **policy_kwargs}
        resolved_policy = build_export_policy(**merged)
    else:
        resolved_policy = build_export_policy(**policy)
    return {
        'dataset': dataset,
        'operation': operation,
        'source': resolved_source,
        'channel': channel,
        'expected': expected,
        'policy': resolved_policy,
    }


def parse_export_pin(pin):
    """Validate and normalize a completed DocSpec ``ExportPin`` response."""
    if not isinstance(pin, dict):
        raise ValueError('ExportPin must be a dictionary')
    for required in ('id', 'dataset'):
        if required not in pin:
            raise ValueError(f'ExportPin is missing required field {required!r}')
    if 'source' not in pin and not isinstance(pin.get('dataset'), dict):
        raise ValueError("ExportPin requires 'source' VersionRef")
    if 'object' not in pin and 'files' not in pin:
        raise ValueError("ExportPin requires 'object' ObjectRef")
    normalized = dict(pin)
    if 'object' in normalized and isinstance(normalized['object'], dict):
        obj = normalized['object']
        rows = int(normalized.get('rows', obj.get('rows', 0)))
        normalized['rows'] = rows
    elif isinstance(normalized.get('files'), list) and normalized['files']:
        first = normalized['files'][0]
        rows = sum(int(f.get('rows', 0)) for f in normalized['files'] if isinstance(f, dict))
        bytes_total = sum(int(f.get('bytes', 0)) for f in normalized['files'] if isinstance(f, dict))
        normalized.setdefault(
            'object',
            {
                'owner': str(normalized['id']),
                'path': str(first.get('path', '')),
                'digest': str(first.get('digest') or first.get('sha256') or ''),
                'bytes': bytes_total,
            },
        )
        normalized.setdefault('rows', rows)
    normalized.setdefault('facets', [])
    normalized.setdefault('browse_ranges', [])
    normalized.setdefault('child_tables', {})
    return normalized


def facet_summary(pin, *, facet_set=None, column=None):
    """Project ``FacetCountEntry`` items from an ``ExportPin`` into a lookup map."""
    if isinstance(pin, dict):
        entries = list(pin.get('facets') or ())
    else:
        entries = list(pin or ())
    by_column = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        count = int(entry.get('count', 0))
        if 'grouping' in entry and isinstance(entry.get('values'), dict):
            grouping = entry.get('grouping') or []
            values_map = entry['values']
            if len(grouping) == 1:
                col_name = str(grouping[0])
                if column is not None and col_name != column:
                    continue
                bucket = by_column.setdefault(col_name, {'values': {}, 'null_count': 0})
                val = values_map.get(col_name)
                if val is None:
                    bucket['null_count'] += count
                else:
                    bucket['values'][str(val)] = bucket['values'].get(str(val), 0) + count
            elif column is not None and column in values_map:
                bucket = by_column.setdefault(column, {'values': {}, 'null_count': 0})
                val = values_map.get(column)
                if val is None:
                    bucket['null_count'] += count
                else:
                    bucket['values'][str(val)] = bucket['values'].get(str(val), 0) + count
        else:
            col_name = entry.get('column')
            if not col_name or (column is not None and col_name != column):
                continue
            bucket = by_column.setdefault(col_name, {'values': {}, 'null_count': 0})
            val = entry.get('value')
            if val is None:
                bucket['null_count'] += count
            else:
                bucket['values'][str(val)] = bucket['values'].get(str(val), 0) + count
    if column is not None:
        return by_column.get(column, {'values': {}, 'null_count': 0})
    if facet_set is not None:
        return by_column
    return by_column


def cleanup_safe(error):
    """Only deterministic pre-admission refusals prove producer independence."""
    return (
        isinstance(error, DocSpecFailure)
        and error.status is not None
        and 400 <= error.status < 500
        and bool(error.code)
        and error.code not in {'worker', 'custody_quarantined', 'timeout', 'host_unavailable'}
    )


class NativeDatasets:
    """Invoke the configured native owner; do not duplicate lifecycle decisions."""

    def __init__(self, binary, workspace, *, remote=None, limits=None, timeout=120,
                 source_revision=None, platform=None, build_features=None,
                 binary_sha256=None, required_capabilities=REQUIRED_LOOPBACK_CAPABILITIES):
        self.binary = str(Path(binary).resolve())
        self.workspace = Path(workspace).resolve()
        self.remote = Path(remote).resolve() if remote is not None else None
        self.limits = Path(limits).resolve() if limits is not None else None
        self.timeout = timeout
        self.source_revision = self._validate_revision(source_revision)
        self.platform = self._validate_platform(platform)
        self.build_features = self._validate_features(build_features, remote=self.remote is not None)
        self.binary_sha256 = self._validate_sha256(binary_sha256)
        self.required_capabilities = self._validate_capabilities(required_capabilities)
        self._remote_secrets = {}
        self._host = None
        self._finalizer = None
        self._closed = False
        self._host_lock = threading.RLock()
        self._responses = set()
        self._configuration_path = None

    @staticmethod
    def _validate_revision(value):
        if value is None:
            return None
        if not isinstance(value, str) or re.fullmatch(r'[0-9a-f]{40}', value) is None:
            raise ValueError('DocSpec runtime source_revision must be a 40-character hex commit SHA')
        return value

    @staticmethod
    def _validate_platform(value):
        if value is None:
            return None
        if not isinstance(value, str) or value not in SUPPORTED_PLATFORMS:
            raise ValueError(f'DocSpec runtime platform must be one of {SUPPORTED_PLATFORMS}')
        return value

    @staticmethod
    def _validate_features(value, *, remote=False):
        if value is None:
            return None
        if (not isinstance(value, (list, tuple)) or not value
                or any(not isinstance(item, str) or not item.strip() for item in value)):
            raise ValueError('DocSpec runtime build_features must be a non-empty list of feature names')
        features = tuple(dict.fromkeys(value))
        if remote and 'remote' not in features:
            raise ValueError('Remote DocSpec configuration requires the remote build feature')
        return features

    @staticmethod
    def _validate_sha256(value):
        if value is None:
            return None
        if not isinstance(value, str) or re.fullmatch(r'[0-9a-f]{64}', value) is None:
            raise ValueError('DocSpec runtime binary_sha256 must be a 64-character hex SHA-256 digest')
        return value

    @staticmethod
    def _validate_capabilities(value):
        if (not isinstance(value, (list, tuple)) or not value
                or any(not isinstance(item, str) or not item.strip() for item in value)):
            raise ValueError('DocSpec runtime required_capabilities must be a non-empty list of capability names')
        capabilities = tuple(dict.fromkeys(value))
        if not set(REQUIRED_LOOPBACK_CAPABILITIES).issubset(capabilities):
            raise ValueError('DocSpec runtime requires request-deadline and owned-stdin-eof capabilities')
        return capabilities

    def verify_runtime(self, *, expected_sha256=None, expected_platform=None,
                       expected_source_revision=None, required_features=(),
                       required_capabilities=REQUIRED_LOOPBACK_CAPABILITIES):
        """Verify binary existence, permissions, digest, platform, features and capabilities before execution."""
        expected_sha = self._validate_sha256(expected_sha256) if expected_sha256 is not None else self.binary_sha256
        if expected_sha256 is not None and self.binary_sha256 is not None and expected_sha != self.binary_sha256:
            raise ValueError('Configured binary_sha256 differs from its approved SHA-256')
        target_platform = self._validate_platform(expected_platform) if expected_platform is not None else self.platform
        if expected_platform is not None and self.platform is not None and target_platform != self.platform:
            raise ValueError('Configured native binary platform differs from expected platform')
        target_revision = (self._validate_revision(expected_source_revision)
                           if expected_source_revision is not None else self.source_revision)
        if (expected_source_revision is not None and self.source_revision is not None
                and target_revision != self.source_revision):
            raise ValueError('Configured source_revision differs from expected source revision')
        capabilities = self._validate_capabilities(required_capabilities)
        if not set(capabilities).issubset(self.required_capabilities):
            raise ValueError('Configured DocSpec runtime capabilities do not satisfy required capabilities')
        needed_features = set(required_features) | ({'remote'} if self.remote is not None else set())
        if self.build_features is not None:
            if not needed_features.issubset(self.build_features):
                raise ValueError('DocSpec runtime is missing required build features')
            features = self.build_features
        elif required_features:
            raise ValueError('DocSpec runtime is missing required build features')
        else:
            features = ('remote',) if self.remote is not None else ()
        binary = Path(self.binary)
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise ValueError('The configured native binary is missing or not executable')
        with binary.open('rb') as source:
            header = source.read(4)
            source.seek(0)
            actual_sha = file_digest(source, 'sha256').hexdigest()
        if expected_sha is not None and actual_sha != expected_sha:
            raise ValueError('The configured native binary is missing or differs from its approved SHA-256')
        if target_platform == 'linux-amd64' and not header.startswith(b'\x7fELF'):
            raise ValueError('The configured native binary platform does not match linux-amd64')
        if (target_platform in ('darwin-arm64', 'darwin-amd64')
                and header[:4] not in {b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe'}):
            raise ValueError(f'The configured native binary platform does not match {target_platform}')
        return dict(
            verified=True,
            binary_sha256=actual_sha,
            platform=target_platform,
            source_revision=target_revision,
            build_features=features,
            required_capabilities=self.required_capabilities,
        )

    @classmethod
    def from_config(cls, path):
        """Load explicit paths and remote secrets without connecting or writing.

        Relative paths belong to the configuration directory. Credentials are a
        separate private JSON file mapping the remote config's DOCSPEC_* secret
        references to values. Only remote child processes receive these values;
        constructing a client never selects a production namespace or dataset.
        """
        path = Path(path).resolve()
        settings = json.loads(path.read_text())
        fields = {'version', 'binary', 'workspace', 'remote', 'limits',
                  'credentials', 'timeout_seconds', 'source_revision',
                  'platform', 'build_features', 'binary_sha256',
                  'required_capabilities'}
        if (not isinstance(settings, dict) or settings.get('version') != 1
                or type(settings.get('version')) is not int or set(settings) - fields):
            raise ValueError('Invalid DocSpec runtime configuration')

        def location(name):
            value = settings.get(name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f'DocSpec runtime requires an explicit {name} path')
            return (path.parent / value).resolve()

        timeout = settings.get('timeout_seconds', 120)
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('DocSpec runtime timeout must be a positive finite number')
        remote = location('remote') if 'remote' in settings else None
        limits = location('limits') if 'limits' in settings else None
        client = cls(
            location('binary'),
            location('workspace'),
            remote=remote,
            limits=limits,
            timeout=timeout,
            source_revision=settings.get('source_revision'),
            platform=settings.get('platform'),
            build_features=settings.get('build_features'),
            binary_sha256=settings.get('binary_sha256'),
            required_capabilities=settings.get('required_capabilities', REQUIRED_LOOPBACK_CAPABILITIES),
        )
        if remote is not None:
            configuration = json.loads(remote.read_text())
            references = configuration.get('secret_env') if isinstance(configuration, dict) else None
            if (not isinstance(references, dict) or not references
                    or any(not isinstance(name, str)
                           or re.fullmatch(r'DOCSPEC_[A-Z0-9_]+', name) is None
                           for name in references.values())):
                raise ValueError('Remote secrets require explicit DOCSPEC_ environment references')
            credential_path = location('credentials')
            if credential_path.stat().st_mode & 0o077:
                raise ValueError('DocSpec credentials require private file permissions (0600)')
            credentials = json.loads(credential_path.read_text())
            if (not isinstance(credentials, dict) or set(credentials) != set(references.values())
                    or any(not isinstance(value, str) or not value or '\0' in value
                           for value in credentials.values())):
                raise ValueError('DocSpec credentials must match all declared secret references')
            client._remote_secrets = credentials
        elif 'credentials' in settings:
            raise ValueError('DocSpec credentials require an explicit remote configuration')
        client._configuration_path = path
        return client

    def execution_files(self):
        """Name immutable executable/configuration inputs for caller guards.

        Workspace/request files are mutable native state. Credentials are loaded
        once into the private child environment and are never returned here.
        """
        return tuple(dict.fromkeys(value for value in (self._configuration_path,
            Path(self.binary), self.remote, self.limits) if value is not None))

    def _command(self, *, remote=True):
        command = [self.binary, '--workspace', str(self.workspace)]
        if self.limits is not None:
            command += ['--limits', str(self.limits)]
        if remote and self.remote is not None:
            command += ['--remote', str(self.remote)]
        return command

    def _has_runtime_pins(self):
        return any(value is not None for value in (
            self.binary_sha256, self.platform, self.source_revision, self.build_features))

    def _call(self, *args, remote=False):
        """Only local file hashing needs a separate native process."""
        if self._closed:
            raise RuntimeError('DocSpec client is closed')
        if self._has_runtime_pins():
            self.verify_runtime()
        command = [*self._command(remote=remote), *map(str, args)]
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=self.timeout)
        if result.returncode:
            raise DocSpecFailure(command, result)
        return json.loads(result.stdout) if result.stdout.strip() else None

    def _execution_host(self):
        with self._host_lock:
            return self._acquire_host()

    def _acquire_host(self):
        if self._closed:
            raise RuntimeError('DocSpec client is closed')
        if self._host is None:
            if self._has_runtime_pins():
                self.verify_runtime()
            environment = ({**os.environ, **self._remote_secrets}
                           if self.remote is not None and self._remote_secrets else None)
            self._host = acquire_host(self._command(), environment,
                                      self.workspace, self.timeout,
                                      required_capabilities=self.required_capabilities)
            self._finalizer = weakref.finalize(self, self._host.release)
        return self._host

    def close(self):
        """Cancel this client's reads; its last owner also stops the native host."""
        with self._host_lock:
            self._closed = True
            for response in tuple(self._responses):
                response.close()
            self._responses.clear()
            if self._finalizer is not None:
                self._finalizer()

    def __enter__(self):
        if self._closed:
            raise RuntimeError('DocSpec client is closed')
        return self

    def __exit__(self, *exc):
        self.close()

    def _request(self, path, request, *, dispatch=None):
        # Match CLI JSON validation before any host startup or native work.
        payload = json.dumps(request, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        return self._host_request('POST', path, content=payload,
            headers={'content-type': 'application/json'}, dispatch=dispatch)

    def _request_ipc(self, path, ipc_bytes, spec, *, blake3_digest=None, dispatch=None):
        """Send an Arrow IPC stream POST with base64-encoded JSON spec and BLAKE3 digest headers."""
        spec_json = json.dumps(spec, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        spec_b64 = base64.b64encode(spec_json.encode('utf-8')).decode('ascii')
        headers = {
            'content-type': ARROW_STREAM_MIME,
            'x-docspec-spec-base64': spec_b64,
        }
        if blake3_digest is not None:
            headers['x-docspec-input-blake3'] = str(blake3_digest)
        return self._host_request(
            'POST',
            path,
            content=bytes(ipc_bytes),
            headers=headers,
            dispatch=dispatch,
        )

    def _host_request(self, method, path, **kwargs):
        deadline = time.monotonic() + self.timeout
        return self._execution_host().request(method, path, deadline=deadline, **kwargs)

    def hash_input(self, path):
        """Hash a local producer file without opening the configured remote host."""
        return self._call('hash', Path(path).resolve(), remote=False)

    def run(self, request):
        return self._request('/run', request)

    def run_ipc(self, table, *, dataset, operation, definition, sql='SELECT * FROM input',
                relationship=None, base=None, native_types=False):
        """Stream one caller-bounded Arrow table directly to ``POST /run`` as an Arrow IPC stream."""
        ipc_bytes = encode_arrow_ipc_stream(table, native_types=native_types)
        digest = blake3_hex(ipc_bytes)
        spec = build_ipc_run_spec(
            dataset,
            operation=operation,
            definition=definition,
            sql=sql,
            base=base,
            relationship=relationship,
            expected_digest=digest,
        )
        return self._request_ipc('/run', ipc_bytes, spec, blake3_digest=digest)

    def run_table(self, table, *, dataset, operation, definition, relationship=None,
                  base=None, partition_by=None, stream_ipc=False, native_types=False,
                  row_group_size=PRODUCER_PARQUET_ROW_GROUP_SIZE):
        """Pass one caller-bounded Arrow source table to the native Run API.

        The caller owns candidate identity, schema and completeness. Input paths
        are locators; native retained expected-digest identity controls replay.
        ``relationship``, ``base``, and ``partition_by`` are optional source-declaration fields.
        When ``stream_ipc=True``, streams the table directly over HTTP as an
        Arrow IPC stream (falling back to staged Parquet if the runtime rejects
        the Arrow stream content-type).
        """
        normalized_partition_by = PartitionSpec.normalize(partition_by) if partition_by is not None else None
        if normalized_partition_by and isinstance(table, pa.Table):
            normalized_partition_by = [
                pf for pf in normalized_partition_by if pf['column'] in table.schema.names
            ] or None
        if stream_ipc and not normalized_partition_by:
            try:
                return self.run_ipc(
                    table,
                    dataset=dataset,
                    operation=operation,
                    definition=definition,
                    relationship=relationship,
                    base=base,
                    native_types=native_types,
                )
            except DocSpecFailure as error:
                status = getattr(error, 'status', None) or getattr(error, 'status_code', None)
                if status != 415:
                    raise
        self.workspace.mkdir(parents=True, exist_ok=True)
        directory = Path(mkdtemp(prefix='request-', dir=self.workspace))
        dispatch = {}
        retained = False
        request = None
        try:
            source = directory / 'source.parquet'
            _write_producer_parquet(table, source, row_group_size=row_group_size)
            digest = self.hash_input(source)['digest']
            request = dict(dataset=dataset, operation=operation, definition=definition,
                input=str(source), expected_digest=digest, sql='SELECT * FROM input')
            if base is not None:
                request['base'] = base
            if relationship is not None:
                request['relationship'] = relationship
            if normalized_partition_by:
                request['partition_by'] = normalized_partition_by
            # Persist replay inputs before sending: process death cannot run the
            # exception handler that diagnoses an indeterminate submission.
            (directory / 'request.json').write_text(
                json.dumps(request, ensure_ascii=False, allow_nan=False))
            try:
                return self._request('/run', request, dispatch=dispatch)
            except DocSpecFailure as exc:
                if normalized_partition_by and 'unknown field' in str(exc) and 'partition_by' in str(exc):
                    fallback_request = {k: v for k, v in request.items() if k != 'partition_by'}
                    (directory / 'request.json').write_text(
                        json.dumps(fallback_request, ensure_ascii=False, allow_nan=False))
                    dispatch.clear()
                    return self._request('/run', fallback_request, dispatch=dispatch)
                raise
        except BaseException as error:
            cleanup_ok = cleanup_safe(error)
            if dispatch.get('submitted') and not cleanup_ok:
                # The native task may still need this producer file. Neither a
                # response timeout, worker/quarantine failure, nor a later host
                # exit proves durable admission or producer independence.
                retained = True
                request_path = directory / 'request.json'
                try:
                    entry = producer_input_entry(request_path)
                    size = entry['bytes'] if entry is not None else None
                    error.retained_input = dict(
                        input=str(source),
                        request=str(request_path),
                        bytes=size,
                        files=entry['files'] if entry is not None else [],
                    )
                    error.add_note(f'DocSpec producer input retained: {source} ({size} bytes); '
                                   f'exact replay request: {request_path}')
                except OSError as diagnostic:
                    error.add_note(f'DocSpec producer directory retained at {directory}; '
                                   f'could not save its diagnostic: {diagnostic}')
            raise
        finally:
            if not retained:
                shutil.rmtree(directory)

    def retained_producer_inputs(self):
        """Inspect unresolved local producer files without inferring native completion.

        Unknown attempts accumulate until explicitly reconciled. Sizes describe
        actual local source files, not a bound on their count or aggregate bytes.
        Every producer file referenced by ``request.json`` is reported, including
        an Update's replacements and deletions. Closing the client or host never
        deletes these recovery inputs.
        """
        inputs = []
        for request in sorted(self.workspace.glob('request-*/request.json')):
            entry = producer_input_entry(request)
            if entry is not None:
                inputs.append(entry)
        return inputs

    def update_ipc(self, table, *, dataset, operation, definition, base, keys,
                   deletions=None, relationship=None, merge=None, native_types=False):
        """Stream one replacement Arrow table directly to ``POST /updates/run`` as an Arrow IPC stream."""
        ipc_bytes = encode_arrow_ipc_stream(table, native_types=native_types)
        digest = blake3_hex(ipc_bytes)
        spec = build_ipc_update_spec(
            dataset,
            operation=operation,
            definition=definition,
            base=base,
            keys=keys,
            replacement_digest=digest,
            relationship=relationship,
            deletions=deletions,
            merge=merge,
        )
        return self._request_ipc('/updates/run', ipc_bytes, spec, blake3_digest=digest)

    def update_table(self, table=None, *, dataset, operation, definition, base, keys,
                     replacements=None, deletions=None, relationship=None,
                     merge=None, stream_ipc=False, native_types=False):
        """Submit one ``UpdateSpec`` with pre-persisted producer custody.

        Accepts either an Arrow ``table`` (and optional Arrow ``deletions`` table)
        staged into this request's temporary directory, or pre-staged
        ``replacements`` / ``deletions`` ``InputSpec`` dicts. Both replacement and
        deletion Parquet files are referenced by ``request.json`` before submission,
        so an indeterminate outcome can be replayed and every referenced file
        survives caller cleanup.
        """
        normalized_merge = None
        if merge is not None:
            if hasattr(merge, 'to_dict'):
                merge = merge.to_dict()
            normalized_merge = (
                build_update_merge_spec(
                    order_by=merge.get('order_by'),
                    columns=merge.get('columns'),
                )
                if isinstance(merge, dict)
                else UpdateMergeSpec.normalize(merge)
            )
            if isinstance(table, pa.Table):
                filtered_merge = {}
                ord_col = normalized_merge.get('order_by')
                if isinstance(ord_col, str) and ord_col in table.schema.names:
                    filtered_merge['order_by'] = ord_col
                elif isinstance(ord_col, (list, tuple)):
                    filtered_merge['order_by'] = list(ord_col)
                filtered_cols = {}
                for k, v in (normalized_merge.get('columns') or {}).items():
                    if k not in table.schema.names:
                        continue
                    field_type = table.schema.field(k).type
                    if v == UpdateMergeStrategy.SET_UNION and not (
                        pa.types.is_list(field_type) or pa.types.is_large_list(field_type)
                    ):
                        v = UpdateMergeStrategy.MAX
                    filtered_cols[k] = v
                if filtered_cols:
                    filtered_merge['columns'] = filtered_cols
                normalized_merge = filtered_merge
        if stream_ipc and replacements is None and deletions is None and table is not None:
            try:
                return self.update_ipc(
                    table,
                    dataset=dataset,
                    operation=operation,
                    definition=definition,
                    base=base,
                    keys=keys,
                    relationship=relationship,
                    merge=normalized_merge,
                    native_types=native_types,
                )
            except DocSpecFailure as error:
                status = getattr(error, 'status', None) or getattr(error, 'status_code', None)
                if status != 415:
                    raise
        self.workspace.mkdir(parents=True, exist_ok=True)
        directory = Path(mkdtemp(prefix='request-', dir=self.workspace))
        dispatch = {}
        retained = False
        try:
            if replacements is None:
                if table is None:
                    raise ValueError('update_table requires either table or replacements')
                source = directory / 'replacements.parquet'
                _write_producer_parquet(table, source)
                digest = self.hash_input(source)['digest']
                replacements_spec = dict(path=str(source), digest=digest)
            else:
                replacements_spec = dict(replacements)
            deletions_spec = None
            if isinstance(deletions, pa.Table):
                deletion_path = directory / 'deletions.parquet'
                _write_producer_parquet(deletions, deletion_path)
                deletion_digest = self.hash_input(deletion_path)['digest']
                deletions_spec = dict(path=str(deletion_path), digest=deletion_digest)
            elif deletions is not None:
                deletions_spec = dict(deletions)
            request = dict(dataset=dataset, operation=operation, definition=definition,
                           base=base, keys=list(keys), replacements=replacements_spec)
            if relationship is not None:
                request['relationship'] = relationship
            if deletions_spec is not None:
                request['deletions'] = deletions_spec
            if normalized_merge is not None:
                request['merge'] = normalized_merge
            (directory / 'request.json').write_text(
                json.dumps(request, ensure_ascii=False, allow_nan=False))
            primary = Path(replacements_spec['path'])
            try:
                return self._request('/updates/run', request, dispatch=dispatch)
            except DocSpecFailure as exc:
                if normalized_merge is not None and 'unknown field' in str(exc) and 'merge' in str(exc):
                    base_pin = self.release(dataset, base)
                    with self.source_batches(base_pin) as reader:
                        existing_table = pa.Table.from_batches(list(reader), schema=reader.schema)
                    incoming_table = table if isinstance(table, pa.Table) else pq.read_table(primary)
                    merged_table = apply_update_merge_spec(
                        existing_table,
                        incoming_table,
                        keys=list(keys),
                        merge_spec=normalized_merge,
                        include_unmatched_existing=False,
                    )
                    merged_path = directory / 'replacements.parquet'
                    _write_producer_parquet(merged_table, merged_path)
                    merged_digest = self.hash_input(merged_path)['digest']
                    fallback_request = {k: v for k, v in request.items() if k != 'merge'}
                    fallback_request['replacements'] = dict(path=str(merged_path), digest=merged_digest)
                    (directory / 'request.json').write_text(
                        json.dumps(fallback_request, ensure_ascii=False, allow_nan=False))
                    primary = merged_path
                    dispatch.clear()
                    return self._request('/updates/run', fallback_request, dispatch=dispatch)
                raise
        except BaseException as error:
            if dispatch.get('submitted') and not cleanup_safe(error):
                retained = True
                try:
                    entry = producer_input_entry(directory / 'request.json')
                    size = entry['bytes'] if entry is not None else None
                    error.retained_input = dict(
                        input=str(primary),
                        request=str(directory / 'request.json'),
                        bytes=size,
                        files=entry['files'] if entry is not None else [],
                    )
                    error.add_note(
                        f'DocSpec producer inputs retained under {directory} ({size} bytes); '
                        f'exact replay request: {directory / "request.json"}'
                    )
                except OSError as diagnostic:
                    error.add_note(f'DocSpec producer directory retained at {directory}; '
                                   f'could not save its diagnostic: {diagnostic}')
            raise
        finally:
            if not retained:
                shutil.rmtree(directory)

    def request(self, path, request):
        """Submit one typed native request on an explicit route."""
        return self._request(path, request)

    def refresh(self, request):
        return self._request('/refreshes/run', request)

    def plan_refresh(self, request):
        return self._request('/refreshes/plan', request)

    def seal_generation(self, request):
        return self._request('/generations/seal', request)

    def capture_inputs(self, inputs):
        return self._request('/inputs/capture', inputs)

    def correct_dependencies(self, request):
        return self._request('/dependencies/corrections', request)

    def plan_schema(self, request):
        return self._request('/schemas/plan', request)

    def evolve_schema(self, request):
        return self._request('/schemas/run', request)

    def plan_backfill(self, request):
        return self._request('/backfills/plan', request)

    def backfill(self, request):
        return self._request('/backfills/run', request)

    def plan_continuous_backfill(self, request):
        return self._request('/plan-continuous-backfill', request)

    def continuous_backfill(self, request):
        return self._request('/continuous-backfill', request)

    def plan_evidence(self, request):
        return self._request('/receipts/plan', request)

    def update_evidence(self, request):
        return self._request('/receipts/run', request)

    def update_evidence_table(self, table=None, *, dataset, operation, definition, base,
                              replacements=None, deletions=None, return_plan=False):
        """Submit one ``EvidenceSpec`` with pre-persisted producer custody."""
        self.workspace.mkdir(parents=True, exist_ok=True)
        directory = Path(mkdtemp(prefix='request-', dir=self.workspace))
        dispatch = {}
        retained = False
        try:
            if replacements is None:
                if table is None:
                    raise ValueError('update_evidence_table requires either table or replacements')
                source = directory / 'replacements.parquet'
                _write_producer_parquet(table, source)
                digest = self.hash_input(source)['digest']
                replacements_spec = dict(path=str(source), digest=digest)
            else:
                replacements_spec = dict(replacements)
            deletions_spec = None
            if isinstance(deletions, pa.Table):
                deletion_path = directory / 'deletions.parquet'
                _write_producer_parquet(deletions, deletion_path)
                deletion_digest = self.hash_input(deletion_path)['digest']
                deletions_spec = dict(path=str(deletion_path), digest=deletion_digest)
            elif deletions is not None:
                deletions_spec = dict(deletions)
            request = dict(dataset=dataset, operation=operation, definition=definition,
                           base=base, replacements=replacements_spec)
            if deletions_spec is not None:
                request['deletions'] = deletions_spec
            (directory / 'request.json').write_text(
                json.dumps(request, ensure_ascii=False, allow_nan=False))
            primary = Path(replacements_spec['path'])
            plan = self.plan_evidence(request)
            if not isinstance(plan, dict) or plan.get('dataset') != dataset or plan.get('operation') != operation:
                raise ValueError('Planned evidence receipt update differs from the requested dataset or operation')
            self.last_evidence_plan = plan
            pin = self._request('/receipts/run', request, dispatch=dispatch)
            return (plan, pin) if return_plan else pin
        except BaseException as error:
            if dispatch.get('submitted') and not cleanup_safe(error):
                retained = True
                try:
                    entry = producer_input_entry(directory / 'request.json')
                    size = entry['bytes'] if entry is not None else None
                    error.retained_input = dict(
                        input=str(primary),
                        request=str(directory / 'request.json'),
                        bytes=size,
                        files=entry['files'] if entry is not None else [],
                    )
                    error.add_note(
                        f'DocSpec producer inputs retained under {directory} ({size} bytes); '
                        f'exact replay request: {directory / "request.json"}'
                    )
                except OSError as diagnostic:
                    error.add_note(f'DocSpec producer directory retained at {directory}; '
                                   f'could not save its diagnostic: {diagnostic}')
            raise
        finally:
            if not retained:
                shutil.rmtree(directory)

    def compare(self, before, after, *, group='source', identity='values', force_full=False):
        """Compare two exact releases without streaming row payloads."""
        return self._request(
            '/compare',
            dict(
                before=before,
                after=after,
                group=group,
                options=dict(identity=identity, force_full=bool(force_full)),
            ),
        )

    @contextmanager
    def changes_batches(self, before, after, *, group='source', identity='occurrences',
                        force_full=False):
        """Stream one exact change stream and its ``docspec.change`` descriptor."""
        started = time.monotonic()
        deadline = started + self.timeout
        host = self._execution_host()
        payload = json.dumps(
            dict(
                before=before,
                after=after,
                group=group,
                options=dict(identity=identity, force_full=bool(force_full)),
            ),
            ensure_ascii=False,
            separators=(',', ':'),
            allow_nan=False,
        )
        with host.stream(
            'POST',
            '/changes',
            deadline=deadline,
            content=payload,
            headers={'content-type': 'application/json'},
        ) as (response, deadline):
            self._responses.add(response)
            try:
                host.check_response(response)
                with ArrowResponse(response, deadline=deadline) as stream, \
                        pa.ipc.open_stream(stream) as reader:
                    raw_meta = (reader.schema.metadata or {}).get(b'docspec.change')
                    descriptor = json.loads(raw_meta.decode('utf-8')) if raw_meta else None

                    def batches():
                        for batch in reader:
                            yield batch
                        stream.finish()

                    with pa.RecordBatchReader.from_batches(reader.schema, batches()) as restored:
                        yield descriptor, restored
            finally:
                self._responses.discard(response)

    def read_changes(self, before, after, *, group='source', identity='occurrences',
                     force_full=False):
        """Consume one change stream, returning ``(descriptor, table, summary)``."""
        with self.changes_batches(
            before, after, group=group, identity=identity, force_full=force_full
        ) as (descriptor, reader):
            batches = list(reader)
            table = pa.Table.from_batches(batches, schema=reader.schema)
        added_rows = 0
        removed_rows = 0
        if 'side' in table.column_names:
            for side in table['side'].to_pylist():
                if side in ('after', 'added', '+1', 1):
                    added_rows += 1
                elif side in ('before', 'removed', '-1', -1):
                    removed_rows += 1
        return dict(
            descriptor=descriptor,
            table=table,
            added_rows=added_rows,
            removed_rows=removed_rows,
            total_rows=table.num_rows,
        )

    def read_keys(self, pin, key, values, *, columns=None, schema=None):
        """Stream only rows matching ``values`` on ``key`` from an exact release pin."""
        started = time.monotonic()
        deadline = started + self.timeout
        dataset, version = pin['dataset']['dataset'], pin['id']
        host = self._execution_host()
        release_path = f'/datasets/{quote(dataset, safe="")}/versions/{quote(version, safe="")}'
        if host.request('GET', release_path, deadline=deadline) != pin:
            raise ValueError('Native release differs from the selected exact pin')
        spec = dict(key=key, values=[str(v) for v in values])
        if columns is not None:
            spec['columns'] = list(columns)
        payload = json.dumps(spec, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        path = release_path + '/keys'
        with host.stream(
            'POST',
            path,
            deadline=deadline,
            content=payload,
            headers={'content-type': 'application/json'},
        ) as (response, deadline):
            self._responses.add(response)
            try:
                host.check_response(response)
                expected = {
                    'docspec-dataset': dataset,
                    'docspec-version': version,
                    'docspec-manifest-blake3': pin['manifest']['digest'],
                    'content-type': 'application/vnd.apache.arrow.stream',
                }
                if any(response.headers.get(k) != v for k, v in expected.items()):
                    raise ValueError('Native stream differs from the selected exact pin')
                with ArrowResponse(response, deadline=deadline) as stream, \
                        pa.ipc.open_stream(stream) as reader:
                    table = reader.read_all()
                    stream.finish()
                return table if schema is None else table.cast(schema, safe=True)
            finally:
                self._responses.discard(response)

    def _read_pin_endpoint(self, pin, suffix, *, schema=None):
        started = time.monotonic()
        deadline = started + self.timeout
        dataset, version = pin['dataset']['dataset'], pin['id']
        host = self._execution_host()
        release_path = f'/datasets/{quote(dataset, safe="")}/versions/{quote(version, safe="")}'
        if host.request('GET', release_path, deadline=deadline) != pin:
            raise ValueError('Native release differs from the selected exact pin')
        path = release_path + suffix
        with host.stream('GET', path, deadline=deadline) as (response, deadline):
            self._responses.add(response)
            try:
                host.check_response(response)
                expected = {
                    'docspec-dataset': dataset,
                    'docspec-version': version,
                    'docspec-manifest-blake3': pin['manifest']['digest'],
                    'content-type': 'application/vnd.apache.arrow.stream',
                }
                if any(response.headers.get(k) != v for k, v in expected.items()):
                    raise ValueError('Native stream differs from the selected exact pin')
                with ArrowResponse(response, deadline=deadline) as stream, \
                        pa.ipc.open_stream(stream) as reader:
                    table = reader.read_all()
                    stream.finish()
                return table if schema is None else table.cast(schema, safe=True)
            finally:
                self._responses.discard(response)

    def read_receipts(self, pin, *, schema=None):
        return self._read_pin_endpoint(pin, '/receipts', schema=schema)

    def read_evidence(self, pin, *, schema=None):
        return self._read_pin_endpoint(pin, '/evidence', schema=schema)

    def read_occurrences(self, pin, *, schema=None):
        return self._read_pin_endpoint(pin, '/occurrences', schema=schema)

    def export(self, request, *, operation=None, source=None, version=None, channel='viewer',
               expected=None, destination=None, policy=None, **policy_kwargs):
        if isinstance(request, str):
            request = build_export_spec(
                request,
                operation=operation,
                source=source,
                version=version,
                channel=channel,
                expected=expected,
                destination=destination,
                policy=policy,
                **policy_kwargs,
            )
        return parse_export_pin(self._request('/exports/run', request))

    def export_table(self, dataset, *, operation, source=None, version=None, channel='viewer',
                     expected=None, destination=None, policy=None, **policy_kwargs):
        """Submit one declarative ``ExportSpec`` and return its normalized ``ExportPin``."""
        spec = build_export_spec(
            dataset,
            operation=operation,
            source=source,
            version=version,
            channel=channel,
            expected=expected,
            destination=destination,
            policy=policy,
            **policy_kwargs,
        )
        return self.export(spec)

    def compact(self, request, *, operation=None, version=None, group='source',
                files=(), target_file_bytes=64 * 1024 * 1024):
        if isinstance(request, str):
            resolved_version = (
                version['dataset']['version']
                if isinstance(version, dict)
                else version
            )
            if not operation or not resolved_version:
                raise ValueError('compact(dataset, ...) requires operation and version')
            request = {
                'dataset': request,
                'operation': operation,
                'version': resolved_version,
                'group': group,
                'files': list(files or ()),
                'target_file_bytes': int(target_file_bytes),
            }
        return self._request('/compactions/run', request)

    def compact_table(self, dataset, *, operation, version, group='source',
                      files=(), target_file_bytes=64 * 1024 * 1024):
        return self.compact(
            dataset,
            operation=operation,
            version=version,
            group=group,
            files=files,
            target_file_bytes=target_file_bytes,
        )

    def compact_lifecycle(self, dataset):
        return self._host_request(
            'POST', f'/datasets/{quote(dataset, safe="")}/lifecycle/compact')

    def latest_export(self, dataset, channel):
        return self._host_request(
            'GET',
            f'/datasets/{quote(dataset, safe="")}/exports/channels/{quote(channel, safe="")}')

    def export_pin(self, dataset, operation):
        return self._host_request(
            'GET', f'/datasets/{quote(dataset, safe="")}/exports/{quote(operation, safe="")}')

    def try_latest_export(self, dataset, channel):
        try:
            return self.latest_export(dataset, channel)
        except DocSpecFailure as error:
            if error.code == 'no_export' or 'no_export' in error.stderr:
                return None
            raise

    def try_export_pin(self, dataset, operation):
        try:
            return self.export_pin(dataset, operation)
        except DocSpecFailure as error:
            if error.code == 'no_export' or 'no_export' in error.stderr:
                return None
            raise

    def read_arrow(self, pin, group='source', *, columns=None, schema=None):
        """Read one exact retained group as an Arrow table."""
        if group == 'source':
            with self.source_batches(pin, schema=schema, columns=columns) as batches:
                return pa.Table.from_batches(list(batches), schema=batches.schema)
        dataset, version = pin['dataset']['dataset'], pin['id']
        projected_cols = list(columns) if columns is not None else None
        query = (
            '?columns=' + ','.join(quote(col, safe='') for col in projected_cols)
            if projected_cols
            else ''
        )
        path = (f'/datasets/{quote(dataset, safe="")}'
                f'/versions/{quote(version, safe="")}/arrow/{quote(group, safe="")}'
                f'{query}')
        target_schema = (
            pa.schema([schema.field(name) for name in projected_cols], metadata=schema.metadata)
            if (schema is not None and projected_cols is not None)
            else schema
        )
        deadline = time.monotonic() + self.timeout
        with self._execution_host().stream('GET', path, deadline=deadline) as (response, deadline):
            self._responses.add(response)
            try:
                self._execution_host().check_response(response)
                with ArrowResponse(response, deadline=deadline) as stream, \
                        pa.ipc.open_stream(stream) as reader:
                    table = reader.read_all()
                    stream.finish()
                return table if target_schema is None else table.cast(target_schema, safe=True)
            finally:
                self._responses.discard(response)

    def plan(self, request):
        return self._request('/plan', request)

    def update(self, request):
        return self._request('/updates/run', request)

    def plan_update(self, request):
        return self._request('/updates/plan', request)

    def latest(self, dataset):
        return self._host_request('GET', f'/datasets/{quote(dataset, safe="")}/latest')

    def try_latest(self, dataset):
        try:
            return self.latest(dataset)
        except DocSpecFailure as error:
            if getattr(error, 'status_code', None) == 404 or error.code == 'no_release' or 'no_release' in error.stderr:
                return None
            raise

    def release(self, dataset, operation):
        return self._host_request('GET',
            f'/datasets/{quote(dataset, safe="")}/versions/{quote(operation, safe="")}')

    def inspect(self, dataset):
        return self._host_request('GET', f'/datasets/{quote(dataset, safe="")}')

    def inspect_retention(self, request):
        return self._request('/retention/inspect', request)

    def plan_removal(self, request):
        return self._request('/retention/removal/plan', request)

    @contextmanager
    def source_batches(self, pin, *, schema=None, columns=None):
        """Stream one exact pin, retaining HTTP custody for the reader's lifetime.

        Resolve and compare the complete pin before reading; stream headers bind
        the body to that same version and manifest. Application schema restoration
        remains a checked cast from the lossless native storage representation.
        Leaving early cancels the response instead of draining it to a scratch file.
        One request deadline covers release lookup and the Arrow response. The
        required native protocol enforces that budget around handlers and bodies,
        so stalled and periodic reads both stop without killing shared work.
        """
        started = time.monotonic()
        deadline = started + self.timeout
        dataset, version = pin['dataset']['dataset'], pin['id']
        host = self._execution_host()
        release_path = f'/datasets/{quote(dataset, safe="")}/versions/{quote(version, safe="")}'
        if host.request('GET', release_path, deadline=deadline) != pin:
            raise ValueError('Native release differs from the selected exact pin')
        projected_cols = list(columns) if columns is not None else None
        if projected_cols is not None and (schema is None or projected_cols != list(schema.names)):
            if not projected_cols:
                raise ValueError('Projected column list must not be empty')
            query = '?columns=' + ','.join(quote(col, safe='') for col in projected_cols)
        else:
            query = ''
        path = release_path + '/arrow/source' + query
        target_schema = (
            pa.schema([schema.field(name) for name in projected_cols], metadata=schema.metadata)
            if (schema is not None and projected_cols is not None)
            else schema
        )
        with host.stream('GET', path, deadline=deadline) as (response, deadline):
            self._responses.add(response)
            try:
                host.check_response(response)
                expected = {'docspec-dataset': dataset, 'docspec-version': version,
                            'docspec-manifest-blake3': pin['manifest']['digest'],
                            'content-type': 'application/vnd.apache.arrow.stream'}
                if any(response.headers.get(key) != value for key, value in expected.items()):
                    raise ValueError('Native stream differs from the selected exact pin')
                with ArrowResponse(response, deadline=deadline) as stream, \
                        pa.ipc.open_stream(stream) as reader:
                    physical = native_storage_schema(target_schema) if target_schema is not None else None
                    extra_supplied = (
                        [f.name for f in reader.schema if f.name.startswith('__docspec_supplied_') and f.name not in physical.names]
                        if physical is not None else []
                    )
                    effective_reader_schema = (
                        pa.schema([f for f in reader.schema if f.name not in extra_supplied], metadata=reader.schema.metadata)
                        if extra_supplied else reader.schema
                    )
                    if (
                        extra_supplied
                        and physical is not None
                        and set(effective_reader_schema.names) == set(physical.names)
                        and all(effective_reader_schema.field(f.name).equals(f, check_metadata=False) for f in physical)
                    ):
                        effective_reader_schema = physical
                    if target_schema is not None:
                        application_schema(effective_reader_schema, expected_schema=target_schema)

                    def batches():
                        for batch in reader:
                            if extra_supplied:
                                batch = pa.RecordBatch.from_arrays(
                                    [batch.column(reader.schema.get_field_index(f.name)) for f in effective_reader_schema],
                                    schema=effective_reader_schema,
                                )
                            if target_schema is not None:
                                tbl = restore_application_schema(
                                    pa.Table.from_batches([batch], schema=batch.schema),
                                    expected_schema=target_schema,
                                )
                                yield from tbl.to_batches()
                            else:
                                yield batch
                        stream.finish()

                    with pa.RecordBatchReader.from_batches(
                            reader.schema if target_schema is None else target_schema, batches()) as restored:
                        yield restored
            finally:
                self._responses.discard(response)
