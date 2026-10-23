"""JSONL record loading, shape validation, and schema-derived table routing.

The schema copy shipped as package data is the single structural authority;
a test keeps it byte-identical to packages/news-lake/docs/schema, which stays
the packet's contract authority. Routing (kind -> table, table -> mutation) is
derived from the schema's x-iceberg annotations and never hand-duplicated.
"""
import json
import math
from importlib import resources
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from news_lake.contract.errors import ContractError

SCHEMA = json.loads(
    (resources.files('news_lake.contract') / 'schema' / 'news-lake.schema.json').read_text(encoding='utf-8')
)
CONTRACT_VERSION = SCHEMA['$id'].rsplit(':', 1)[-1]
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())

ICEBERG_ANNOTATIONS = {
    kind: definition['x-iceberg']
    for kind, definition in SCHEMA['$defs'].items()
    if 'x-iceberg' in definition
}
# Schema definition order; deterministic table commit order for a batch.
KIND_ORDER = list(ICEBERG_ANNOTATIONS)
KIND_TABLES = {kind: annotation['table'] for kind, annotation in ICEBERG_ANNOTATIONS.items()}
TABLE_KINDS = {table: kind for kind, table in KIND_TABLES.items()}
TABLE_MUTATIONS = {annotation['table']: annotation['mutation'] for annotation in ICEBERG_ANNOTATIONS.values()}
# The twelve non-release tables a release must pin, in schema order.
CONTENT_TABLES = [table for table in KIND_TABLES.values() if table != 'news.releases']
UPSERT_TABLES = {table for table, mutation in TABLE_MUTATIONS.items() if mutation == 'upsert'}


def _reject_constant(token):
    raise ContractError('non_finite_number', f'JSON constant {token} is not a finite number')


def _reject_nulls(value, path='$'):
    if value is None:
        raise ContractError('json_null', f'explicit null at {path}')
    if isinstance(value, dict):
        for key, child in value.items():
            _reject_nulls(child, f'{path}.{key}')
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_nulls(child, f'{path}[{index}]')


def _reject_non_finite(value, path='$'):
    if isinstance(value, float) and not math.isfinite(value):
        raise ContractError('non_finite_number', f'non-finite number at {path}')
    if isinstance(value, dict):
        for key, child in value.items():
            _reject_non_finite(child, f'{path}.{key}')
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_non_finite(child, f'{path}[{index}]')


def _allowed_extra_fields(record, allowed_extra):
    """Top-level fields permitted by a storage table but absent from the schema.

    Evolved optional Iceberg columns are not part of the contract's closed JSON
    Schema. They are accepted only when the caller names them from the table's
    authoritative schema; they are stripped before JSON Schema validation so
    the record's declared shape is still checked exactly.
    """
    definition = SCHEMA['$defs'].get(record.get('kind'))
    if not isinstance(definition, dict):
        return set()
    declared = set(definition.get('properties', {}))
    extra = set(record) - declared
    if not extra:
        return set()
    allowed = set(allowed_extra or ())
    unexpected = sorted(extra - allowed)
    if unexpected:
        identifier = record.get('id') if isinstance(record.get('id'), str) else None
        raise ContractError(
            'shape', f'additional property {unexpected[0]!r} is not allowed', record_id=identifier
        )
    return extra


def validate_shape(record, allowed_extra=()):
    """Validate one record against the JSON Schema, formats included.

    ``allowed_extra`` names top-level fields supplied by an evolved storage
    schema; they are stripped before validation so the contract remains the
    single owner of every declared field.
    """
    if not isinstance(record, dict):
        raise ContractError('shape', f'record is {type(record).__name__}, not an object')
    _reject_nulls(record)
    _reject_non_finite(record)
    extra = _allowed_extra_fields(record, allowed_extra)
    candidate = {name: value for name, value in record.items() if name not in extra}
    errors = sorted(VALIDATOR.iter_errors(candidate), key=lambda error: error.json_path)
    if errors:
        first = errors[0]
        identifier = record.get('id') if isinstance(record.get('id'), str) else None
        raise ContractError('shape', f'{first.json_path}: {first.message}', record_id=identifier)
    return record


def parse_jsonl(text):
    """Parse JSONL text into shape-valid records; reject duplicates by id."""
    records = []
    seen = {}
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line, parse_constant=_reject_constant)
        except json.JSONDecodeError as error:
            raise ContractError('json_syntax', f'line {number}: {error.msg}') from error
        try:
            validate_shape(record)
        except ContractError as error:
            raise ContractError(error.rule, f'line {number}: {error.detail}', record_id=error.record_id) from error
        prior = seen.get(record['id'])
        if prior is not None:
            raise ContractError('duplicate_record_id', f'line {number} repeats id from line {prior}', record_id=record['id'])
        seen[record['id']] = number
        records.append(record)
    return records


def load_jsonl(path):
    """Load and validate a JSONL record file."""
    return parse_jsonl(Path(path).read_text(encoding='utf-8'))


