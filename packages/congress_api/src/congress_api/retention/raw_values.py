"""Typed raw values at the native source-only storage boundary.

Capture order identifies observations, independently of body identity. Repeated
bodies and even repeated receipt locations therefore remain separate rows. Native
file iteration need not preserve the archive's existing observation order.
"""
import pyarrow as pa
import pyarrow.compute as pc

from congress_api.retention.raw_archive import (
    CAPTURE_SCHEMA,
    LEGACY_CAPTURE_SCHEMA,
    STATE_SCHEMA,
    LEGACY_STATE_SCHEMA,
    derive_body_key,
    format_sha256,
    format_timestamp,
)

ORDER = '_capture_order'
NATIVE_CAPTURE_SCHEMA = pa.schema([pa.field(ORDER, pa.int64(), nullable=False), *LEGACY_CAPTURE_SCHEMA])


def _to_legacy_capture_table(rows):
    if isinstance(rows, pa.Table):
        if rows.schema.equals(LEGACY_CAPTURE_SCHEMA, check_metadata=False):
            return rows
        is_capture_schema = rows.schema.equals(CAPTURE_SCHEMA, check_metadata=False) or (
            'body_key' in rows.column_names
            and rows.drop(['body_key']).schema.equals(CAPTURE_SCHEMA, check_metadata=False)
        )
        if not is_capture_schema:
            raise ValueError('Unexpected capture index schema')
        py_rows = []
        for r in rows.to_pylist():
            sha_hex = format_sha256(r.get('sha256'))
            bkey = r.get('body_key') or (derive_body_key(sha_hex, r.get('media_type')) if sha_hex else None)
            stored_sha = r.get('stored_sha256')
            if stored_sha is None and r.get('is_stored'):
                stored_sha = sha_hex
            py_rows.append({
                'family': r.get('family'),
                'capture_date': r.get('capture_date'),
                'source_file': r.get('source_file'),
                'source_line': r.get('source_line'),
                'receipt_key': r.get('receipt_key'),
                'receipt_line': r.get('receipt_line'),
                'reference_kind': r.get('reference_kind'),
                'pointer_json': r.get('pointer_json'),
                'context_url': r.get('context_url'),
                'body_key': bkey,
                'sha256': sha_hex,
                'bytes': r.get('bytes'),
                'stored_sha256': stored_sha,
                'stored_bytes': r.get('stored_bytes'),
                'fidelity': r.get('fidelity'),
                'media_type': r.get('media_type'),
                'retrieved_at': format_timestamp(r.get('retrieved_at')),
                'http_status': int(r['http_status']) if r.get('http_status') is not None else None,
                'resolution': r.get('resolution'),
                'original_path': r.get('original_path'),
            })
        return pa.Table.from_pylist(py_rows, schema=LEGACY_CAPTURE_SCHEMA)
    return pa.Table.from_pylist(rows, schema=LEGACY_CAPTURE_SCHEMA)


def capture_table(rows, *, first_order):
    """Attach immutable global ordinals to one already bounded capture batch."""
    if not isinstance(first_order, int) or first_order < 0:
        raise ValueError('Capture order must start at a nonnegative integer')
    table = _to_legacy_capture_table(rows)
    order = pa.array(range(first_order, first_order + len(table)), type=pa.int64())
    return pa.Table.from_arrays([order, *table.columns], schema=NATIVE_CAPTURE_SCHEMA)


def ordered_captures(table):
    """Restore original capture fields and order from one selected source batch."""
    if not table.schema.equals(NATIVE_CAPTURE_SCHEMA, check_metadata=False):
        raise ValueError('Unexpected native capture schema')
    order = table[ORDER]
    if (order.null_count or pc.count_distinct(order).as_py() != len(table)
            or (len(table) and pc.min(order).as_py() < 0)):
        raise ValueError('Invalid or repeated capture order')
    return table.take(pc.sort_indices(order)).select(LEGACY_CAPTURE_SCHEMA.names).cast(LEGACY_CAPTURE_SCHEMA)


def state_table(rows):
    """Retain keyed URL state values and reject ambiguous duplicate keys."""
    if isinstance(rows, pa.Table):
        if not (rows.schema.equals(STATE_SCHEMA, check_metadata=False)
                or rows.schema.equals(LEGACY_STATE_SCHEMA, check_metadata=False)):
            raise ValueError('Unexpected download state schema')
        table = rows
    else:
        table = pa.Table.from_pylist(rows, schema=LEGACY_STATE_SCHEMA)
    if pc.count_distinct(table['url'], mode='all').as_py() != len(table):
        raise ValueError('Duplicate URLs in download state')
    return table.cast(table.schema)
