"""Declarative specification builders, normalizers, and relational merge engine."""
from collections.abc import Mapping, Sequence
from typing import Any

import pyarrow as pa

from .models import (
    VALID_UPDATE_MERGE_STRATEGIES,
    SortColumn,
    UpdateMergeSpec,
    UpdateMergeStrategy,
    VersionRef,
)


def _normalize_sort_column(item: Any) -> dict[str, Any]:
    norm = SortColumn.normalize(item)
    if 'nulls_first' not in norm:
        norm = dict(norm, nulls_first=False)
    return norm


def _normalize_scalar_expr(expr: Any) -> Any:
    if isinstance(expr, str):
        if not expr.strip():
            raise ValueError('ScalarExpr SQL string must not be empty')
        return expr
    if not isinstance(expr, Mapping):
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


def _normalize_computed_columns(computed_columns: Any) -> dict[str, Any]:
    if isinstance(computed_columns, Mapping):
        result: dict[str, Any] = {}
        for name, expr in computed_columns.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError('computed_columns keys must be non-empty column names')
            result[name] = _normalize_scalar_expr(expr)
        return result
    if isinstance(computed_columns, (list, tuple)):
        result = {}
        for item in computed_columns:
            if (
                not isinstance(item, Mapping)
                or not isinstance(item.get('name'), str)
                or not item['name'].strip()
                or 'expression' not in item
            ):
                raise ValueError('computed_columns list item requires name and expression')
            result[item['name']] = _normalize_scalar_expr(item['expression'])
        return result
    raise ValueError('computed_columns must be a dict mapping column_name -> ScalarExpr or a sequence of specs')


def _normalize_predicate(predicate: Any) -> Any:
    if isinstance(predicate, str):
        if not predicate.strip():
            raise ValueError('Predicate SQL string must not be empty')
        return predicate
    if not isinstance(predicate, Mapping):
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


def build_export_policy(
    *,
    group: str = 'source',
    groups: Sequence[str] = (),
    rows: str = 'all',
    columns: Sequence[str] = (),
    filter: Any = None,
    computed_columns: Any = None,
    order_by: Sequence[Any] = (),
    page_index_columns: Sequence[str] = (),
    browse_range_columns: Sequence[str] = (),
    row_group_rows: int | None = None,
) -> dict[str, Any]:
    """Build a canonical DocSpec ``ExportPolicy`` dictionary matching ``src/export.rs``."""
    resolved_groups = [str(g) for g in (groups or ()) if str(g).strip()]
    resolved_group = str(group or (resolved_groups[0] if resolved_groups else 'source'))
    if not resolved_group.strip():
        raise ValueError('ExportPolicy requires a non-empty group name')
    if rows != 'all':
        raise ValueError("ExportPolicy rows must be 'all'")
    resolved_columns = [str(c) for c in (columns or ()) if str(c).strip()]
    if not resolved_columns:
        inferred: list[str] = []
        for col in page_index_columns or ():
            if str(col) not in inferred:
                inferred.append(str(col))
        for item in order_by or ():
            col = item.get('column') if isinstance(item, Mapping) else None
            if col and str(col) not in inferred:
                inferred.append(str(col))
        for col in browse_range_columns or ():
            if str(col) not in inferred:
                inferred.append(str(col))
        if not inferred:
            raise ValueError('ExportPolicy requires non-empty columns')
        resolved_columns = inferred
    policy: dict[str, Any] = {
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
    if order_by:
        policy['order_by'] = [_normalize_sort_column(spec) for spec in order_by]
    if page_index_columns:
        policy['page_index_columns'] = [str(col) for col in page_index_columns]
    if browse_range_columns:
        policy['browse_range_columns'] = [str(col) for col in browse_range_columns]
    if row_group_rows is not None:
        resolved_rows = int(row_group_rows)
        if resolved_rows <= 0:
            raise ValueError('ExportPolicy row_group_rows must be positive')
        policy['row_group_rows'] = resolved_rows
    return policy


def _normalize_version_ref(pin: Any) -> dict[str, Any]:
    return VersionRef.normalize(pin)


def _resolve_version_ref(dataset: str, source_or_version: Any) -> dict[str, Any]:
    return VersionRef.resolve(dataset, source_or_version)


def build_update_merge_spec(*, order_by: str | None = 'recorded_at', columns: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Build a canonical DocSpec ``UpdateMergeSpec`` dictionary matching ``src/model.rs``."""
    return dict(UpdateMergeSpec(order_by=order_by, columns=columns))


def build_ipc_run_spec(
    dataset: str,
    *,
    operation: str,
    definition: str,
    sql: str = 'SELECT * FROM input',
    base: Any = None,
    relationship: Any = None,
    input: Any = None,
    expected_digest: Any = None,
) -> dict[str, Any]:
    """Build a canonical ``IpcRunSpec`` matching ``src/http/ipc.rs``."""
    spec: dict[str, Any] = {
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
    dataset: str,
    *,
    operation: str,
    definition: str,
    base: Any,
    keys: Sequence[str],
    replacement_path: Any = None,
    replacement_digest: Any = None,
    relationship: Any = None,
    merge: Any = None,
    replacements: Any = None,
    deletions: Any = None,
) -> dict[str, Any]:
    """Build a canonical ``IpcUpdateSpec`` matching ``src/http/ipc.rs``."""
    resolved_replacements: dict[str, Any] = dict(replacements) if isinstance(replacements, Mapping) else {}
    if replacement_path is not None:
        resolved_replacements['path'] = str(replacement_path)
    if replacement_digest is not None:
        resolved_replacements['digest'] = str(replacement_digest)
    spec: dict[str, Any] = {
        'dataset': str(dataset),
        'operation': str(operation),
        'definition': str(definition),
        'base': base['dataset']['version'] if isinstance(base, Mapping) and 'dataset' in base else str(base),
        'keys': [str(k) for k in keys],
        'replacements': resolved_replacements,
    }
    if relationship is not None:
        spec['relationship'] = dict(relationship)
    if deletions is not None:
        spec['deletions'] = dict(deletions) if isinstance(deletions, Mapping) else deletions
    if merge is not None:
        if hasattr(merge, 'to_dict'):
            merge = merge.to_dict()
        spec['merge'] = (
            build_update_merge_spec(
                order_by=merge.get('order_by'),
                columns=merge.get('columns'),
            )
            if isinstance(merge, Mapping)
            else merge
        )
    return spec


def build_export_spec(
    dataset: str,
    *,
    operation: str,
    source: Any = None,
    version: Any = None,
    channel: str = 'viewer',
    expected: Any = None,
    destination: Any = None,
    policy: Any = None,
    **policy_kwargs: Any,
) -> dict[str, Any]:
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


def parse_export_pin(pin: Any) -> dict[str, Any]:
    """Validate and normalize a completed DocSpec ``ExportPin`` response."""
    if not isinstance(pin, Mapping):
        raise ValueError('ExportPin must be a dictionary')
    for required in ('id', 'dataset'):
        if required not in pin:
            raise ValueError(f'ExportPin is missing required field {required!r}')
    if 'source' not in pin and not isinstance(pin.get('dataset'), Mapping):
        raise ValueError("ExportPin requires 'source' VersionRef")
    if 'object' not in pin and 'files' not in pin:
        raise ValueError("ExportPin requires 'object' ObjectRef")
    normalized = dict(pin)
    if 'object' in normalized and isinstance(normalized['object'], Mapping):
        obj = normalized['object']
        rows = int(normalized.get('rows', obj.get('rows', 0)))
        normalized['rows'] = rows
    elif isinstance(normalized.get('files'), list) and normalized['files']:
        first = normalized['files'][0]
        rows = sum(int(f.get('rows', 0)) for f in normalized['files'] if isinstance(f, Mapping))
        bytes_total = sum(int(f.get('bytes', 0)) for f in normalized['files'] if isinstance(f, Mapping))
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
    return normalized


def _merge_row_pair(
    existing_row: dict[str, Any],
    incoming_row: dict[str, Any],
    *,
    keys: Sequence[str],
    order_by: str | None,
    columns: Mapping[str, str],
    field_names: Sequence[str],
) -> dict[str, Any]:
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
    merged: dict[str, Any] = {}
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


def _iter_table_rows(table_or_rows: Any) -> Any:
    if isinstance(table_or_rows, pa.Table):
        for batch in table_or_rows.to_batches():
            yield from batch.to_pylist()
    elif isinstance(table_or_rows, pa.RecordBatch):
        yield from table_or_rows.to_pylist()
    elif table_or_rows is not None:
        yield from table_or_rows


def apply_update_merge_spec(
    existing_table: Any,
    incoming_table: Any,
    *,
    keys: Sequence[str],
    merge_spec: Any = None,
    merge: Any = None,
    deletions: Any = None,
    include_unmatched_existing: bool = True,
) -> Any:
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
    if schema is not None:
        field_names = list(schema.names)
    else:
        seen_fields: list[str] = []
        for r in _iter_table_rows(existing_table):
            for k in r:
                if k not in seen_fields:
                    seen_fields.append(k)
        for r in _iter_table_rows(incoming_table):
            for k in r:
                if k not in seen_fields:
                    seen_fields.append(k)
        field_names = seen_fields

    if field_names:
        columns = {k: v for k, v in columns.items() if k in field_names}
        if order_by is not None and order_by not in field_names:
            order_by = None

    def row_key(row: dict[str, Any]) -> tuple[Any, ...]:
        return tuple(row.get(k) for k in keys)

    deleted_keys: set[tuple[Any, ...]] = set()
    if deletions is not None:
        if isinstance(deletions, (pa.Table, pa.RecordBatch)):
            del_keys_table = deletions.select(keys) if all(k in deletions.schema.names for k in keys) else deletions
            for batch in (del_keys_table.to_batches() if isinstance(del_keys_table, pa.Table) else [del_keys_table]):
                for d in batch.to_pylist():
                    if isinstance(d, dict):
                        deleted_keys.add(row_key(d))
                    elif len(keys) == 1:
                        deleted_keys.add((d,))
        else:
            for d in deletions:
                if isinstance(d, dict):
                    deleted_keys.add(row_key(d))
                elif len(keys) == 1:
                    deleted_keys.add((d,))

    dedup_incoming: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in _iter_table_rows(incoming_table):
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

    existing_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in _iter_table_rows(existing_table):
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
        if len(merged_rows) > 16384:
            batches = [
                pa.RecordBatch.from_pylist(merged_rows[i:i + 16384], schema=schema)
                for i in range(0, len(merged_rows), 16384)
            ]
            return pa.Table.from_batches(batches, schema=schema)
        return pa.Table.from_pylist(merged_rows, schema=schema)
    return merged_rows
