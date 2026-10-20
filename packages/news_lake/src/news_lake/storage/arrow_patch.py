"""Seam for pyiceberg 0.12: nullable list<struct> columns lose SQL NULL.

ArrowProjectionVisitor.list rebuilds list-of-struct arrays with
from_arrays(offsets, values) — its workaround for apache/arrow#38809 — which
drops the validity bitmap, so a NULL list is written to Parquet as an empty
list. That collapses "optional field absent" with "recorded empty array",
which the contract keeps distinct (and would corrupt classification exports
where value_strings must stay omitted). Until upstream carries the mask, we
patch that single rebuild to preserve nullability; everything else is stock
pyiceberg. The round-trip tests fail if this drifts; remove when fixed
upstream.
"""
import pyarrow as pa
import pyiceberg
from pyiceberg.io.pyarrow import ArrowProjectionVisitor

SUPPORTED_PREFIX = '0.12.'
_UNPATCHED = ArrowProjectionVisitor.list


def _list_preserving_nullability(self, list_type, list_array, value_array):
    if isinstance(list_array, (pa.ListArray, pa.LargeListArray, pa.FixedSizeListArray)) and value_array is not None:
        list_initializer = pa.large_list if isinstance(list_array, pa.LargeListArray) else pa.list_
        if isinstance(value_array, pa.StructArray):
            list_array = pa.LargeListArray.from_arrays(
                list_array.offsets, value_array, mask=list_array.is_null()
            )
        value_array = self._cast_if_needed(list_type.element_field, value_array)
        arrow_field = list_initializer(self._construct_field(list_type.element_field, value_array.type))
        return list_array.cast(arrow_field)
    return None


def apply():
    if not pyiceberg.__version__.startswith(SUPPORTED_PREFIX):
        return
    if ArrowProjectionVisitor.list is not _list_preserving_nullability:
        ArrowProjectionVisitor.list = _list_preserving_nullability


apply()
