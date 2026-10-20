"""Typed raw values at the native source-only storage boundary.

Capture order identifies observations, independently of body identity. Repeated
bodies and even repeated receipt locations therefore remain separate rows. Native
file iteration need not preserve the archive's existing observation order.
"""
import pyarrow as pa
import pyarrow.compute as pc

from congress_api.retention.raw_archive import CAPTURE_SCHEMA, STATE_SCHEMA

ORDER = '_capture_order'
NATIVE_CAPTURE_SCHEMA = pa.schema([pa.field(ORDER, pa.int64(), nullable=False), *CAPTURE_SCHEMA])


def capture_table(rows, *, first_order):
    """Attach immutable global ordinals to one already bounded capture batch."""
    if not isinstance(first_order, int) or first_order < 0:
        raise ValueError('Capture order must start at a nonnegative integer')
    table = rows if isinstance(rows, pa.Table) else pa.Table.from_pylist(rows, schema=CAPTURE_SCHEMA)
    if not table.schema.equals(CAPTURE_SCHEMA, check_metadata=False):
        raise ValueError('Unexpected capture index schema')
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
    return table.take(pc.sort_indices(order)).select(CAPTURE_SCHEMA.names).cast(CAPTURE_SCHEMA)


def state_table(rows):
    """Retain keyed URL state values and reject ambiguous duplicate keys."""
    table = rows if isinstance(rows, pa.Table) else pa.Table.from_pylist(rows, schema=STATE_SCHEMA)
    if not table.schema.equals(STATE_SCHEMA, check_metadata=False):
        raise ValueError('Unexpected download state schema')
    if pc.count_distinct(table['url'], mode='all').as_py() != len(table):
        raise ValueError('Duplicate URLs in download state')
    return table.cast(STATE_SCHEMA)
