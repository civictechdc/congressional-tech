"""Arrow schema adaptation and type restoration for native DocSpec datasets."""
from typing import Any
import pyarrow as pa


def native_storage_schema(schema_or_table: Any, *, native_types: bool = True) -> Any:
    """Use lossless Iceberg types for integer widths and binary offsets.

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

    def field(value: pa.Field) -> pa.Field:
        return value.with_type(data_type(value.type))

    def data_type(value: pa.DataType) -> pa.DataType:
        # Iceberg stores narrow integers as Int32 and UInt32 as Int64.
        # Widen producer arrays too, so writer fields and arrays agree.
        if (pa.types.is_int8(value) or pa.types.is_int16(value)
                or pa.types.is_uint8(value) or pa.types.is_uint16(value)):
            return pa.int32()
        if pa.types.is_uint32(value):
            return pa.int64()
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


def _merge_field_type(physical_type: pa.DataType, expected_type: pa.DataType) -> pa.DataType:
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
        if (
            (pa.types.is_int32(physical_type) and (pa.types.is_int16(expected_type) or pa.types.is_int8(expected_type) or pa.types.is_uint8(expected_type) or pa.types.is_uint16(expected_type)))
            or (pa.types.is_int64(physical_type) and (pa.types.is_uint32(expected_type) or pa.types.is_int16(expected_type) or pa.types.is_int32(expected_type)))
            or (pa.types.is_decimal(physical_type) and (pa.types.is_uint64(expected_type) or pa.types.is_uint32(expected_type) or pa.types.is_int64(expected_type)))
            or (pa.types.is_large_binary(physical_type) and pa.types.is_binary(expected_type))
            or (pa.types.is_large_string(physical_type) and pa.types.is_string(expected_type))
            or (pa.types.is_timestamp(physical_type) and pa.types.is_timestamp(expected_type) and physical_type.unit == expected_type.unit and bool(physical_type.tz) == bool(expected_type.tz))
            or ((pa.types.is_string(physical_type) or pa.types.is_large_string(physical_type)) and pa.types.is_timestamp(expected_type))
        ):
            return expected_type
        raise ValueError(
            f'Native source storage schema ({physical_type}) differs from '
            f'the selected application schema ({expected_type})'
        )
    return expected_type


def application_schema(schema: pa.Schema, expected_schema: pa.Schema | None = None) -> pa.Schema:
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

    def field(value: pa.Field) -> pa.Field:
        return value.with_type(data_type(value.type))

    def data_type(value: pa.DataType) -> pa.DataType:
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


def _cast_column(column: Any, target_type: pa.DataType) -> Any:
    if column.type.equals(target_type, check_metadata=True):
        return column
    if (pa.types.is_string(column.type) or pa.types.is_large_string(column.type)) and pa.types.is_timestamp(target_type):
        if column.null_count == len(column):
            return pa.nulls(len(column), type=target_type)
    try:
        return column.cast(target_type, safe=True)
    except pa.ArrowNotImplementedError:
        if isinstance(column, pa.ChunkedArray):
            chunks = [_cast_array(chunk, target_type) for chunk in column.chunks]
            return pa.chunked_array(chunks, type=target_type)
        return _cast_array(column, target_type)


def _cast_array(array: Any, target_type: pa.DataType) -> Any:
    if array.type.equals(target_type, check_metadata=True):
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


def restore_application_schema(table: pa.Table, expected_schema: pa.Schema | None = None) -> pa.Table:
    """Restore an Arrow Table from native storage types to ``expected_schema``."""
    target_schema = application_schema(table.schema, expected_schema=expected_schema)
    if expected_schema is not None and set(target_schema.names) == set(expected_schema.names):
        target_schema = expected_schema
    if table.schema.equals(target_schema, check_metadata=True):
        return table
    columns = [
        _cast_column(table.column(target_schema.field(i).name), target_schema.field(i).type)
        for i in range(len(target_schema))
    ]
    return pa.Table.from_arrays(columns, schema=target_schema)
