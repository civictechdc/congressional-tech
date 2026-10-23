"""Contract schema, Arrow type mapping, merge specs, and pin utilities for docspec."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re
from typing import Any, Mapping

import pyarrow as pa

from news_lake.contract.records import (
    CONTENT_TABLES,
    KIND_TABLES,
    SCHEMA,
    validate_shape,
)
from news_lake.storage.coordinator import CommitError, _merge_upsert
from congress_shared.custody import canonical_json_bytes, verify_local_file
from docspec_client.docspec import (
    application_schema,
    build_update_merge_spec,
    native_storage_schema,
    restore_application_schema,
)

DEFINITION = 'news-v1'
DEFAULT_LIFECYCLE_COMPACT_INTERVAL = 16
DEFAULT_COMPACT_FILE_THRESHOLD = 32
DEFAULT_COMPACT_TARGET_FILE_BYTES = 64 * 1024 * 1024

APPEND_UPDATE_KEYS = {
    'capture': ('id',),
    'discovery': ('observed_at', 'id'),
    'version': ('recorded_at', 'id'),
    'mention': ('recorded_at', 'id'),
    'classification': ('recorded_at', 'id'),
    'identity_decision': ('recorded_at', 'id'),
    'run': ('finished_at', 'id'),
    'story': ('recorded_at', 'id'),
    'story_member': ('recorded_at', 'id'),
}


class AppendCollisionError(CommitError, ValueError):
    """Conflicting ID reuse on an append-only dataset (both CommitError and ValueError)."""


# -- Typed Pin Helpers (Eliminating nested dict train-wrecks) ----------------


def pin_version(pin: Mapping[str, Any] | None) -> str | None:
    """Extract dataset version identifier safely from a ReleasePin or TablePin."""
    if not isinstance(pin, dict):
        return None
    dataset = pin.get('dataset')
    if isinstance(dataset, dict) and dataset.get('version'):
        return str(dataset['version'])
    selected = pin.get('selected_version')
    if selected is not None:
        return str(selected)
    return pin.get('version')


def pin_group(pin: Mapping[str, Any] | None, group: str = 'source') -> dict[str, Any]:
    """Extract a named partition group safely from a pin."""
    if not isinstance(pin, dict):
        return {}
    dataset = pin.get('dataset')
    if isinstance(dataset, dict):
        groups = dataset.get('groups')
        if isinstance(groups, dict):
            grp = groups.get(group)
            if isinstance(grp, dict):
                return grp
    # Check if pin is already a TablePin
    if 'rows' in pin or 'objects' in pin:
        return dict(pin)
    return {}


def pin_metadata(pin: Mapping[str, Any] | None, group: str = 'source') -> dict[str, Any]:
    """Extract metadata dictionary from a pin group."""
    grp = pin_group(pin, group)
    meta = grp.get('metadata')
    return meta if isinstance(meta, dict) else {}


def pin_metadata_path(pin: Mapping[str, Any] | None, group: str = 'source') -> str | None:
    """Extract metadata file path from a pin group."""
    return pin_metadata(pin, group).get('path')


def pin_snapshot(pin: Mapping[str, Any] | None, group: str = 'source') -> Any:
    """Extract snapshot identifier from a pin group."""
    return pin_group(pin, group).get('snapshot')


def pin_rows(pin: Mapping[str, Any] | None, group: str = 'source') -> int:
    """Extract row count from a pin group."""
    return int(pin_group(pin, group).get('rows', 0) or 0)


def pin_objects(pin: Mapping[str, Any] | None, group: str = 'source') -> list[dict[str, Any]]:
    """Extract object descriptors from a pin group."""
    objs = pin_group(pin, group).get('objects')
    return [o for o in (objs or ()) if isinstance(o, dict)]


# -- Schema and Arrow serialization -----------------------------------------


def sanitize_id(value: Any, *, prefix: str = 'id') -> str:
    """Fit an application name into the engine's bounded ASCII identifier rule."""
    cleaned = re.sub(r'[^A-Za-z0-9_-]+', '_', str(value)).strip('_')[:128]
    return cleaned or prefix


def dataset_id_for(table: str) -> str:
    """The native dataset id for a contract table or record kind name."""
    return sanitize_id(table.replace('.', '_'))


def version_ref(pin: Mapping[str, Any]) -> dict[str, Any]:
    """The exact consumed ``VersionRef`` of a release pin (engine input shape)."""
    dataset = pin['dataset']
    return {
        'dataset': dataset['dataset'],
        'version': dataset['version'],
        'manifest': pin['manifest'],
    }


def str_canonical(value: Any) -> str | None:
    if value is None:
        return None
    return canonical_json_bytes(
        value, ensure_ascii=False, allow_nan=False, default=str
    ).decode('utf-8')


def content_digest(records: Any) -> str:
    """A stable digest over record values, for replay-stable operation ids."""
    return sha256(
        canonical_json_bytes(records, ensure_ascii=False, allow_nan=False, default=str)
    ).hexdigest()


def _resolve_ref(definition: dict[str, Any]) -> dict[str, Any]:
    while '$ref' in definition:
        definition = SCHEMA['$defs'][definition['$ref'].split('/')[-1]]
    return definition


def _arrow_type(definition: dict[str, Any]) -> pa.DataType:
    """Contract JSON-Schema types to Arrow, keeping the JSON value space."""
    definition = _resolve_ref(definition)
    if 'type' not in definition and ('const' in definition or 'enum' in definition):
        definition = {**definition, 'type': 'string'}
    kind = definition.get('type')
    if kind == 'string':
        return pa.string()
    if kind == 'integer':
        return pa.int64()
    if kind == 'number':
        return pa.float64()
    if kind == 'boolean':
        return pa.bool_()
    if kind == 'array':
        return pa.list_(pa.field('element', _arrow_type(definition['items']), nullable=False))
    if kind == 'object':
        return pa.struct([
            pa.field(name, _arrow_type(child), nullable=True)
            for name, child in definition.get('properties', {}).items()
        ])
    raise ValueError(f'unsupported contract type for the DocSpec backend: {definition!r}')


_KIND_SCHEMAS: dict[str, pa.Schema] = {}


def kind_arrow_schema(kind: str) -> pa.Schema:
    """The full physical Arrow schema for one record kind (contract-derived)."""
    if kind not in _KIND_SCHEMAS:
        definition = SCHEMA['$defs'][kind]
        _KIND_SCHEMAS[kind] = pa.schema([
            pa.field(name, _arrow_type(child), nullable=True)
            for name, child in definition['properties'].items()
        ])
    return _KIND_SCHEMAS[kind]


def records_to_arrow(kind: str, records: Any) -> pa.Table:
    """Serialize records of one kind into the contract-derived Arrow schema."""
    return pa.Table.from_pylist(list(records), schema=kind_arrow_schema(kind))


def _strip_nulls(value: Any) -> Any:
    """Drop absent-optional nulls so a native readback equals the submitted record."""
    if isinstance(value, dict):
        return {key: _strip_nulls(child) for key, child in value.items() if child is not None}
    if isinstance(value, list):
        return [_strip_nulls(child) for child in value]
    return value


def table_records(table: pa.Table) -> list[dict[str, Any]]:
    """Convert a native readback table back into plain JSON values."""
    columns = [name for name in table.column_names if not name.startswith('__docspec_')]
    return [_strip_nulls(row) for row in table.select(columns).to_pylist()]


def merge_upsert_batch(existing_records: list[dict[str, Any]], incoming_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge incoming upsert records into existing rows by ``id`` (C1)."""
    by_id = {record['id']: record for record in existing_records}
    merged = []
    for record in incoming_records:
        prior = by_id.get(record['id'])
        candidate = _merge_upsert(prior, record) if prior is not None else record
        validate_shape(candidate)
        merged.append(candidate)
    return merged


def upsert_merge_spec_for_kind(kind: str) -> dict[str, Any]:
    """Build a declarative ``UpdateMergeSpec`` for an upsert record ``kind`` (C1 / ss-023x)."""
    schema = kind_arrow_schema(kind)
    columns = {}
    for field in schema:
        if field.name == 'id':
            continue
        if field.name == 'recorded_at':
            columns[field.name] = 'max'
        elif field.name == 'first_seen_at':
            columns[field.name] = 'min'
        elif pa.types.is_list(field.type) or pa.types.is_large_list(field.type):
            columns[field.name] = 'set_union'
        else:
            columns[field.name] = 'latest_or_backfill'
    return build_update_merge_spec(order_by='recorded_at', columns=columns)


def build_c5_export_policy(
    kind: str,
    *,
    columns: list[str] | None = None,
    authorized: bool = False,
    as_of: Any = None,
    expired_capture_ids: Any = (),
) -> dict[str, Any]:
    """Build a declarative C5 ``ExportPolicy`` with ``computed_columns`` (ss-6gwu)."""
    if columns is None:
        cols = list(kind_arrow_schema(kind).names)
    else:
        cols = list(columns)
    base_policy: dict[str, Any] = {
        'group': 'source',
        'rows': 'all',
        'columns': cols,
    }
    if authorized or kind not in ('capture', 'version'):
        return base_policy

    expired_ids = sorted({str(cid) for cid in (expired_capture_ids or ()) if cid is not None})
    null_lit = {'kind': 'literal', 'value': None}
    if kind == 'capture':
        redact_preds: list[dict[str, Any]] = [{
            'kind': 'eq',
            'left': {'kind': 'column', 'name': 'access'},
            'right': {'kind': 'literal', 'value': 'restricted'},
        }]
        if as_of is not None:
            as_of_str = as_of if isinstance(as_of, str) else as_of.isoformat()
            redact_preds.append({
                'kind': 'and',
                'predicates': [
                    {
                        'kind': 'is_not_null',
                        'expr': {'kind': 'column', 'name': 'retain_until'},
                    },
                    {
                        'kind': 'lt',
                        'left': {'kind': 'column', 'name': 'retain_until'},
                        'right': {'kind': 'literal', 'value': as_of_str},
                    },
                ],
            })
        if expired_ids:
            redact_preds.append({
                'kind': 'in_list',
                'expr': {'kind': 'column', 'name': 'id'},
                'list': [{'kind': 'literal', 'value': cid} for cid in expired_ids],
            })
        redact_all_pred = (
            redact_preds[0]
            if len(redact_preds) == 1
            else {'kind': 'or', 'predicates': redact_preds}
        )
        redact_body_pred = {
            'kind': 'or',
            'predicates': [
                redact_all_pred,
                {
                    'kind': 'eq',
                    'left': {'kind': 'column', 'name': 'access'},
                    'right': {'kind': 'literal', 'value': 'metadata_only'},
                },
            ],
        }
        computed_columns: dict[str, Any] = {
            'access': {
                'kind': 'case_when',
                'branches': [
                    {
                        'when': redact_all_pred,
                        'then': {'kind': 'literal', 'value': 'metadata_only'},
                    }
                ],
                'else_expr': {'kind': 'column', 'name': 'access'},
            },
            'rights_basis': {
                'kind': 'case_when',
                'branches': [{'when': redact_all_pred, 'then': null_lit}],
                'else_expr': {'kind': 'column', 'name': 'rights_basis'},
            },
        }
        for col in ('payload_uri', 'payload_hash', 'media_type'):
            computed_columns[col] = {
                'kind': 'case_when',
                'branches': [{'when': redact_body_pred, 'then': null_lit}],
                'else_expr': {'kind': 'column', 'name': col},
            }
        return {**base_policy, 'computed_columns': computed_columns}

    # kind == 'version'
    redact_preds = [{
        'kind': 'eq',
        'left': {'kind': 'column', 'name': 'access'},
        'right': {'kind': 'literal', 'value': 'restricted'},
    }]
    if expired_ids:
        redact_preds.append({
            'kind': 'in_list',
            'expr': {'kind': 'column', 'name': 'capture_id'},
            'list': [{'kind': 'literal', 'value': cid} for cid in expired_ids],
        })
    redact_all_pred = (
        redact_preds[0]
        if len(redact_preds) == 1
        else {'kind': 'or', 'predicates': redact_preds}
    )
    redact_body_pred = {
        'kind': 'or',
        'predicates': [
            redact_all_pred,
            {
                'kind': 'eq',
                'left': {'kind': 'column', 'name': 'access'},
                'right': {'kind': 'literal', 'value': 'metadata_only'},
            },
        ],
    }
    computed_columns = {
        'access': {
            'kind': 'case_when',
            'branches': [
                {
                    'when': redact_all_pred,
                    'then': {'kind': 'literal', 'value': 'metadata_only'},
                }
            ],
            'else_expr': {'kind': 'column', 'name': 'access'},
        },
        'rights_basis': {
            'kind': 'case_when',
            'branches': [{'when': redact_all_pred, 'then': null_lit}],
            'else_expr': {'kind': 'column', 'name': 'rights_basis'},
        },
    }
    for col in ('text', 'text_hash'):
        computed_columns[col] = {
            'kind': 'case_when',
            'branches': [{'when': redact_body_pred, 'then': null_lit}],
            'else_expr': {'kind': 'column', 'name': col},
        }
    return {**base_policy, 'computed_columns': computed_columns}


def _file_digest(path: Path | str) -> str:
    """Stream a SHA-256 digest so large exports are never materialized in memory."""
    return verify_local_file(path).sha256
