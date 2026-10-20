"""JSON -> Iceberg mapping (I1), Arrow row conversion, and JSON export.

Types follow the profile: strings/hashes/URLs/enums -> string, date-time ->
timestamptz (microseconds), date -> date, integer -> long, number -> double,
boolean -> boolean, object -> struct, homogeneous array -> list with non-null
elements. Required record fields become required columns; absent optionals
become SQL NULL and are omitted on JSON export. Field ids at build time are
placeholders: the catalog assigns the persisted ids, and the table's own
schema (see catalog.Lake.arrow_schema) is authoritative for writes so ids are
never regenerated from column order.

The table schema can evolve beyond the JSON Schema (for example an added
optional Iceberg column). When an Arrow schema is supplied for a write, extra
top-level record fields present in it are converted by their Arrow type rather
than dropped; on export, extra row keys are converted back and NULLs are
omitted, with no need to teach the JSON Schema about the column.
"""
from datetime import date, datetime, timezone

import pyarrow as pa
from pyiceberg.schema import Schema
from pyiceberg.types import (
    BooleanType,
    DateType,
    DoubleType,
    ListType,
    LongType,
    NestedField,
    StringType,
    StructType,
    TimestamptzType,
)

from news_lake.contract.records import SCHEMA
from news_lake.context import format_instant, parse_instant

_SCHEMAS = {}


def _resolve(definition):
    """Follow chained local $refs, rejecting cycles instead of looping."""
    visited = set()
    while '$ref' in definition:
        name = definition['$ref'].split('/')[-1]
        if name in visited:
            raise ValueError(f'circular $ref in JSON Schema: {name!r}')
        visited.add(name)
        definition = SCHEMA['$defs'][name]
    return definition


class _Ids:
    def __init__(self):
        self.next = 0

    def take(self):
        self.next += 1
        return self.next


def _field(ids, name, definition, required):
    field_type = _type_of(ids, _resolve(definition))
    return NestedField(ids.take(), name, field_type, required=required)


def _type_of(ids, definition):
    kind = definition.get('type')
    if kind is None and 'const' in definition:
        kind = {str: 'string', int: 'integer', float: 'number', bool: 'boolean'}[type(definition['const'])]
    if kind == 'string':
        if definition.get('format') == 'date-time':
            return TimestamptzType()
        if definition.get('format') == 'date':
            return DateType()
        return StringType()
    if kind == 'integer':
        return LongType()
    if kind == 'number':
        return DoubleType()
    if kind == 'boolean':
        return BooleanType()
    if kind == 'array':
        return ListType(element_id=ids.take(), element_type=_type_of(ids, _resolve(definition['items'])), element_required=True)
    if kind == 'object':
        required = set(definition.get('required', ()))
        return StructType(*[
            _field(ids, name, child, name in required) for name, child in definition.get('properties', {}).items()
        ])
    raise ValueError(f'unsupported JSON Schema type for Iceberg mapping: {definition!r}')


def _kind_definition(kind):
    try:
        return SCHEMA['$defs'][kind]
    except KeyError:
        raise ValueError(f'unknown record kind: {kind!r}') from None


def iceberg_schema(kind):
    """Build the Iceberg schema for a record kind; `kind` itself is not a column."""
    if kind not in _SCHEMAS:
        definition = _kind_definition(kind)
        required = set(definition.get('required', ()))
        ids = _Ids()
        _SCHEMAS[kind] = Schema(*[
            _field(ids, name, child, name in required)
            for name, child in definition['properties'].items()
            if name != 'kind'
        ])
    return _SCHEMAS[kind]


def _to_storage(definition, value):
    if value is None:
        return None
    definition = _resolve(definition)
    kind = definition.get('type')
    if kind == 'string' and definition.get('format') == 'date-time':
        return parse_instant(value).astimezone(timezone.utc)
    if kind == 'string' and definition.get('format') == 'date':
        return date.fromisoformat(value)
    if kind == 'array':
        return [_to_storage(definition['items'], item) for item in value]
    if kind == 'object':
        return {
            name: _to_storage(child, value.get(name))
            for name, child in definition.get('properties', {}).items()
        }
    return value


def _to_json(definition, value):
    if value is None:
        return None
    definition = _resolve(definition)
    kind = definition.get('type')
    if kind == 'string' and definition.get('format') == 'date-time':
        return format_instant(value)
    if kind == 'string' and definition.get('format') == 'date':
        return value.isoformat()
    if kind == 'array':
        return [_to_json(definition['items'], item) for item in value]
    if kind == 'object':
        return {
            name: _to_json(child, value.get(name))
            for name, child in definition.get('properties', {}).items()
            if value.get(name) is not None
        }
    return value


def _storage_extra(field_type, value):
    """Convert an evolved-column value from its JSON form to its Arrow form."""
    if value is None:
        return None
    if pa.types.is_timestamp(field_type):
        return parse_instant(value).astimezone(timezone.utc) if isinstance(value, str) else value
    if pa.types.is_date32(field_type) or pa.types.is_date64(field_type):
        return date.fromisoformat(value) if isinstance(value, str) else value
    if pa.types.is_list(field_type) or pa.types.is_large_list(field_type):
        return [_storage_extra(field_type.value_type, item) for item in value]
    if pa.types.is_struct(field_type):
        return {
            field.name: _storage_extra(field.type, value.get(field.name))
            for field in field_type
        }
    return value


def _json_extra(value):
    """Convert an evolved-column value from Arrow's form to canonical JSON."""
    if isinstance(value, datetime):
        return format_instant(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return [_json_extra(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _json_extra(child)
            for key, child in value.items()
            if child is not None
        }
    return value


def record_to_row(record, arrow_schema=None):
    """Convert one JSON record into an Arrow-compatible row (kind dropped).

    Extra top-level fields are kept only when the supplied Arrow schema knows
    them; their values convert by the Arrow field type rather than by the JSON
    Schema, so evolved optional columns survive a write.
    """
    definition = _kind_definition(record['kind'])
    properties = definition['properties']
    row = {
        name: _to_storage(child, record.get(name))
        for name, child in properties.items()
        if name != 'kind'
    }
    if arrow_schema is not None:
        for field in arrow_schema:
            if field.name in properties:
                continue
            row[field.name] = _storage_extra(field.type, record.get(field.name))
    return row


def row_to_record(kind, row):
    """Convert one storage row back to a JSON record; NULLs are omitted.

    Row keys outside the JSON Schema definition are evolved columns: they are
    converted recursively and exported so schema evolution is readable without
    editing the contract.
    """
    definition = _kind_definition(kind)
    properties = definition['properties']
    record = {'kind': kind}
    for name, child in properties.items():
        if name == 'kind':
            continue
        value = _to_json(child, row.get(name))
        if value is not None:
            record[name] = value
    for name, value in row.items():
        if name in properties:
            continue
        value = _json_extra(value)
        if value is not None:
            record[name] = value
    return record


def to_arrow_table(kind, records, arrow_schema):
    return pa.Table.from_pylist(
        [record_to_row(record, arrow_schema) for record in records], schema=arrow_schema
    )


def from_arrow_table(kind, table):
    return [row_to_record(kind, row) for row in table.to_pylist()]
