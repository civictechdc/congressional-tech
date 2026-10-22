"""Declarative ExportSpec policies, folded filename_readings, and flat occurrences.parquet assets."""
from hashlib import sha256
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from docspec_client import (
    build_export_policy,
    build_export_spec,
    facet_summary,
    parse_export_pin,
)
from viewer_publication.filename_budget import (
    DEFAULT_DECODED_POLICY,
    DecodedBudgetExceeded,
    failure_receipt,
)
from viewer_publication.filename_compression import (
    DEFAULT_COMPRESSION_POLICY,
    validate_compression,
)
from viewer_publication.filename_details import (
    CORE,
    FRAGMENT,
    NON_FILENAME,
    ORIGIN,
    READINGS,
    RETAINED_PAGE,
    TYPES,
    typed_value,
)
from viewer_publication.filename_observations import (
    observation_rows,
    observation_values,
)
from viewer_publication.filename_resources import owned_resources

OCCURRENCE_ROW_GROUP_ROWS = 2048

DEFAULT_SOURCE_READING_FIELDS = (
    'raw_leaf',
    'normalized_leaf',
    'header_leaf',
    'recovered_leaf',
    'candidate_leaf',
    'canonical_leaf',
)

DEFAULT_SOURCE_FACET_COLUMNS = (
    'congress',
    'document_family',
    'document_kind',
    'format',
)

DEFAULT_COMPONENT_FACET_COLUMNS = (
    'congress',
    'document_family',
    'document_kind',
    'format',
)


def visible_reading_fields(schema_names):
    """Select the visible filename reading columns folded into ``filename_readings``."""
    readings = [
        name
        for name in schema_names
        if name not in NON_FILENAME and not name.startswith(('source_', 'content_'))
    ]
    visible = [
        name
        for name in readings
        if not FRAGMENT.search(name)
        or name in {'date_token_candidates', 'measure_token', 'measure_token_code'}
    ]
    visible = list(
        dict.fromkeys(
            visible
            + [
                name
                for name in readings
                if name.endswith('_label') or name in {'measure_type', 'measure_number'}
            ]
        )
    )
    return readings, visible


def build_source_export_policy(
    *,
    destination_dir=None,
    reading_fields=DEFAULT_SOURCE_READING_FIELDS,
    facet_columns=DEFAULT_SOURCE_FACET_COLUMNS,
    occurrence_columns=None,
    row_group_rows=OCCURRENCE_ROW_GROUP_ROWS,
):
    """Build the declarative ``ExportPolicy`` for ``filename-sources``."""
    fields = [str(f) for f in (reading_fields or DEFAULT_SOURCE_READING_FIELDS)]
    facets = [str(c) for c in (facet_columns or DEFAULT_SOURCE_FACET_COLUMNS)]
    occ_dest = (
        str(Path(destination_dir) / 'occurrences.parquet')
        if destination_dir is not None
        else 'occurrences.parquet'
    )
    child_spec = {
        'name': 'occurrences',
        'group': 'occurrences',
        'destination': occ_dest,
        'order_by': [
            {'column': 'owner_id', 'descending': False, 'nulls_first': False},
            {'column': 'occurrence_order', 'descending': False, 'nulls_first': False},
        ],
        'browse_range_columns': ['owner_id'],
        'row_group_rows': int(row_group_rows),
    }
    if occurrence_columns:
        child_spec['columns'] = [str(c) for c in occurrence_columns]
    return build_export_policy(
        groups=('source',),
        computed_columns=[
            {
                'name': 'filename_field_count',
                'expression': {
                    'fn': 'count_non_null',
                    'columns': fields,
                },
            }
        ],
        fold_readings=[
            {
                'name': 'filename_readings',
                'fields': fields,
            }
        ],
        order_by=[
            {'column': 'source_id', 'descending': False, 'nulls_first': False},
        ],
        page_index_columns=['source_id', 'document_id', 'filename'],
        facet_sets=[
            {
                'name': 'sources_facets',
                'columns': facets,
            }
        ],
        browse_range_columns=['source_id', 'document_id'],
        child_tables=[child_spec],
        row_group_rows=int(row_group_rows),
    )


def build_component_export_policy(
    *,
    destination_dir=None,
    facet_columns=DEFAULT_COMPONENT_FACET_COLUMNS,
    occurrence_columns=None,
    row_group_rows=OCCURRENCE_ROW_GROUP_ROWS,
):
    """Build the declarative ``ExportPolicy`` for ``filename-components``."""
    facets = [str(c) for c in (facet_columns or DEFAULT_COMPONENT_FACET_COLUMNS)]
    occ_dest = (
        str(Path(destination_dir) / 'document_occurrences.parquet')
        if destination_dir is not None
        else 'document_occurrences.parquet'
    )
    child_spec = {
        'name': 'occurrences',
        'group': 'occurrences',
        'destination': occ_dest,
        'order_by': [
            {'column': 'owner_id', 'descending': False, 'nulls_first': False},
            {'column': 'occurrence_order', 'descending': False, 'nulls_first': False},
        ],
        'browse_range_columns': ['owner_id'],
        'row_group_rows': int(row_group_rows),
    }
    if occurrence_columns:
        child_spec['columns'] = [str(c) for c in occurrence_columns]
    return build_export_policy(
        groups=('source',),
        order_by=[
            {'column': 'filename', 'descending': False, 'nulls_first': False},
            {'column': 'document_id', 'descending': False, 'nulls_first': False},
        ],
        page_index_columns=['filename', 'document_id', 'source_id'],
        facet_sets=[
            {
                'name': 'components_facets',
                'columns': facets,
            }
        ],
        browse_range_columns=['filename', 'document_id'],
        child_tables=[child_spec],
        row_group_rows=int(row_group_rows),
    )


def build_source_export_spec(
    dataset,
    *,
    operation,
    version,
    destination,
    channel='viewer',
    reading_fields=DEFAULT_SOURCE_READING_FIELDS,
    facet_columns=DEFAULT_SOURCE_FACET_COLUMNS,
    occurrence_columns=None,
    row_group_rows=OCCURRENCE_ROW_GROUP_ROWS,
):
    policy = build_source_export_policy(
        destination_dir=destination,
        reading_fields=reading_fields,
        facet_columns=facet_columns,
        occurrence_columns=occurrence_columns,
        row_group_rows=row_group_rows,
    )
    return build_export_spec(
        dataset,
        operation=operation,
        version=version,
        channel=channel,
        destination=destination,
        policy=policy,
    )


def build_component_export_spec(
    dataset,
    *,
    operation,
    version,
    destination,
    channel='viewer',
    facet_columns=DEFAULT_COMPONENT_FACET_COLUMNS,
    occurrence_columns=None,
    row_group_rows=OCCURRENCE_ROW_GROUP_ROWS,
):
    policy = build_component_export_policy(
        destination_dir=destination,
        facet_columns=facet_columns,
        occurrence_columns=occurrence_columns,
        row_group_rows=row_group_rows,
    )
    return build_export_spec(
        dataset,
        operation=operation,
        version=version,
        channel=channel,
        destination=destination,
        policy=policy,
    )


def occurrence_flat_schema(kind):
    """Build the flat Parquet schema for ``occurrences.parquet`` from the occurrence struct type."""
    return pa.schema(
        [
            pa.field('owner_id', pa.string(), nullable=False),
            pa.field('occurrence_order', pa.int64(), nullable=False),
            pa.field('occurrence_is_null', pa.bool_(), nullable=False),
            *[pa.field(field.name, field.type, nullable=True) for field in kind],
        ]
    )


def publish_occurrence_parquet(
    source,
    path,
    *,
    owner_ids=None,
    policy=DEFAULT_DECODED_POLICY,
    metrics=None,
    compression_policy=DEFAULT_COMPRESSION_POLICY,
    row_group_rows=OCCURRENCE_ROW_GROUP_ROWS,
):
    """Write flat ``occurrences.parquet`` with 2,048-row groups, PageIndex, and ``ExportKeyRange`` metadata."""
    metrics = metrics if metrics is not None else {}
    compression = validate_compression(compression_policy)
    path = Path(path)
    try:
        with owned_resources() as owned:
            return _publish_occurrence_parquet(
                source,
                path,
                owned,
                owner_ids=owner_ids,
                policy=policy,
                metrics=metrics,
                compression=compression,
                row_group_rows=int(row_group_rows),
            )
    except DecodedBudgetExceeded as error:
        failure_receipt(path.parent, error, policy, metrics)
        raise


def _adapt_occurrence_source(source):
    if isinstance(source, pa.Table):
        from types import SimpleNamespace
        from viewer_publication.filename_observations import ObservationSequence

        table = source
        occ_col = table['source_occurrences']

        class _TableSource:
            schema_arrow = table.schema
            metadata = SimpleNamespace(num_rows=len(table))

            def observation_rows(self):
                for scalar in occ_col:
                    if not scalar.is_valid:
                        yield None
                    else:
                        values = scalar.values
                        yield ObservationSequence(len(values), lambda values=values: iter((values,)))

        return _TableSource()
    return source


def _publish_occurrence_parquet(
    source,
    path,
    owned,
    *,
    owner_ids,
    policy,
    metrics,
    compression,
    row_group_rows,
):
    source = _adapt_occurrence_source(source)
    schema_arrow = getattr(source, 'schema_arrow', None) or getattr(source, 'schema')
    kind = schema_arrow.field('source_occurrences').type.value_type
    fields = [field.name for field in kind]
    flat_schema = occurrence_flat_schema(kind)
    resolved_owners = (
        list(owner_ids)
        if owner_ids is not None
        else list(getattr(source, 'owner_ids', None) or ())
    )

    row_slices = []
    browse_ranges = []
    pending_rows = []
    total_occurrences = 0
    row_group_index = 0
    row_group_start = 0

    def flush_pending(writer):
        nonlocal row_group_index, row_group_start
        if not pending_rows:
            return
        table = pa.Table.from_pylist(pending_rows, schema=flat_schema)
        writer.write_table(table, row_group_size=len(pending_rows))
        owners_col = [row['owner_id'] for row in pending_rows]
        browse_ranges.append(
            {
                'group': 'occurrences',
                'path': path.name,
                'row_group': row_group_index,
                'row_offset': row_group_start,
                'rows': len(pending_rows),
                'column': 'owner_id',
                'min': min(owners_col),
                'max': max(owners_col),
                'null_count': 0,
            }
        )
        row_group_index += 1
        row_group_start += len(pending_rows)
        pending_rows.clear()

    with pq.ParquetWriter(
        path,
        flat_schema,
        compression=compression.codec,
        compression_level=compression.level,
        write_page_index=True,
        write_statistics=True,
    ) as writer:
        for parent_idx, values in enumerate(
            observation_rows(source, policy=policy, metrics=metrics, stage='occurrences_parquet')
        ):
            owner_id = (
                str(resolved_owners[parent_idx])
                if parent_idx < len(resolved_owners)
                else f'row-{parent_idx:08d}'
            )
            if values is None:
                row_slices.append([total_occurrences, -1])
                continue
            if len(values) == 0:
                row_slices.append([total_occurrences, 0])
                continue
            start_offset = total_occurrences
            count_for_owner = 0
            for occ_order, observation in enumerate(
                observation_values(
                    values,
                    policy=policy,
                    metrics=metrics,
                    stage='occurrences_parquet',
                    kind=kind,
                )
            ):
                if observation is None:
                    flat_row = {
                        'owner_id': owner_id,
                        'occurrence_order': occ_order,
                        'occurrence_is_null': True,
                        **{name: None for name in fields},
                    }
                else:
                    flat_row = {
                        'owner_id': owner_id,
                        'occurrence_order': occ_order,
                        'occurrence_is_null': False,
                        **{name: observation.get(name) for name in fields},
                    }
                pending_rows.append(flat_row)
                total_occurrences += 1
                count_for_owner += 1
                if len(pending_rows) >= row_group_rows:
                    flush_pending(writer)
            row_slices.append([start_offset, count_for_owner])
        flush_pending(writer)

    with pq.ParquetFile(path) as written:
        if written.metadata.num_rows != total_occurrences:
            raise ValueError('Flat occurrences.parquet row count differs from emitted count')

    return {
        'rows': total_occurrences,
        'parent_rows': len(row_slices),
        'fields': fields,
        'row_slices': row_slices,
        'browse_ranges': browse_ranges,
    }


def compute_browse_ranges(parquet_path, columns, *, group='source'):
    """Extract per-row-group ``ExportKeyRange`` statistics from a written Parquet file."""
    ranges = []
    parquet_path = Path(parquet_path)
    with pq.ParquetFile(parquet_path) as pf:
        meta = pf.metadata
        schema_names = pf.schema_arrow.names
        target_cols = [col for col in columns if col in schema_names]
        row_offset = 0
        for rg_idx in range(meta.num_row_groups):
            rg = meta.row_group(rg_idx)
            rg_rows = rg.num_rows
            rg_table = pf.read_row_group(rg_idx, columns=target_cols) if target_cols else None
            for col_name in target_cols:
                values = [v for v in rg_table[col_name].to_pylist() if v is not None]
                null_count = rg_rows - len(values)
                min_val = str(min(values)) if values else None
                max_val = str(max(values)) if values else None
                ranges.append(
                    {
                        'group': group,
                        'path': parquet_path.name,
                        'row_group': rg_idx,
                        'row_offset': row_offset,
                        'rows': rg_rows,
                        'column': col_name,
                        'min': min_val,
                        'max': max_val,
                        'null_count': null_count,
                    }
                )
            row_offset += rg_rows
    return ranges


def compute_facet_entries(table_or_rows, columns, *, facet_set):
    """Compute ``FacetCountEntry`` list across ``columns`` matching ``docspec-rs``."""
    rows = table_or_rows.to_pylist() if isinstance(table_or_rows, pa.Table) else list(table_or_rows)
    entries = []
    for col in columns:
        counts = {}
        null_count = 0
        for row in rows:
            val = row.get(col)
            if val is None or val == []:
                null_count += 1
            elif isinstance(val, list):
                non_empty = [str(item.lower() if col == 'format' and isinstance(item, str) else item) for item in val if item]
                if not non_empty:
                    null_count += 1
                else:
                    for item in non_empty:
                        counts[item] = counts.get(item, 0) + 1
            else:
                norm = str(val.lower() if col == 'format' and isinstance(val, str) else val)
                counts[norm] = counts.get(norm, 0) + 1
        for value in sorted(counts):
            entries.append(
                {
                    'facet_set': facet_set,
                    'column': col,
                    'value': value,
                    'count': counts[value],
                }
            )
        if null_count > 0:
            entries.append(
                {
                    'facet_set': facet_set,
                    'column': col,
                    'value': None,
                    'count': null_count,
                }
            )
    return entries


def fold_source_readings_table(table, *, has_observations_list=None):
    """Fold ``filename_readings``, ``fact_alternatives``, and ``filename_field_count`` onto a source Arrow table."""
    from congress_api.retention.saved_responses import saved_response

    names = table.schema.names
    core = [name for name in CORE + ORIGIN if name in names]
    core += [name for name in names if name.startswith('content_')]
    readings, visible = visible_reading_fields(names)
    typed = [name for name in TYPES if name in names]

    base_fields = []
    seen = set()
    readings_set = set(readings)
    for name in ['source_id', 'document_id', *core]:
        if name in names and name not in seen and name not in readings_set and name not in TYPES:
            base_fields.append(table.schema.field(name))
            seen.add(name)
    for field in table.schema:
        if (
            field.name not in seen
            and field.name != 'source_occurrences'
            and field.name not in TYPES
            and field.name not in readings_set
        ):
            base_fields.append(field)
            seen.add(field.name)

    out_schema = pa.schema(
        base_fields
        + [pa.field(name, TYPES[name]) for name in typed]
        + [
            pa.field('fact_alternatives', READINGS),
            pa.field('filename_readings', READINGS),
            pa.field('filename_field_count', pa.uint16()),
        ],
        metadata=table.schema.metadata,
    )

    py_rows = table.to_pylist()
    out_rows = []
    for idx, row in enumerate(py_rows):
        has_obs = bool(has_observations_list[idx]) if has_observations_list is not None else bool(row.get('source_occurrences'))
        record = {}
        for field in base_fields:
            name = field.name
            if name in ORIGIN and name not in RETAINED_PAGE and has_obs:
                record[name] = None
            else:
                record[name] = row.get(name)
        if 'body_key' in record and not saved_response(row):
            record['body_key'] = None
        record['fact_alternatives'] = []
        for name in typed:
            value = typed_value(name, row.get(name))
            record[name] = value
            if value is None and row.get(name) is not None:
                record['fact_alternatives'].append({'field': name, 'values': row[name]})
        record['filename_readings'] = [
            {'field': name, 'values': row[name]}
            for name in visible
            if row.get(name)
        ]
        record['filename_field_count'] = sum(bool(row.get(name)) for name in readings)
        out_rows.append(record)

    return pa.Table.from_pylist(out_rows, schema=out_schema)


def build_export_pin_descriptor(
    *,
    dataset,
    version,
    operation,
    channel,
    destination,
    policy,
    primary_file,
    facets=(),
    browse_ranges=(),
    child_tables=None,
):
    """Construct a normalized ``ExportPin`` dictionary matching ``docspec-rs``."""
    policy_bytes = json.dumps(policy, sort_keys=True, separators=(',', ':')).encode('utf-8')
    policy_digest = sha256(policy_bytes).hexdigest()
    manifest_bytes = json.dumps(
        {
            'dataset': dataset,
            'version': version,
            'operation': operation,
            'primary_file': primary_file,
        },
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    return parse_export_pin(
        {
            'id': operation,
            'operation': operation,
            'channel': channel,
            'dataset': {'dataset': dataset, 'version': version},
            'manifest': {
                'path': f'{destination}/manifest.json',
                'digest': sha256(manifest_bytes).hexdigest(),
                'size': len(manifest_bytes),
            },
            'policy_digest': policy_digest,
            'destination': str(destination),
            'files': [primary_file],
            'total_rows': int(primary_file['rows']),
            'total_bytes': int(primary_file['bytes']),
            'facets': list(facets),
            'browse_ranges': list(browse_ranges),
            'child_tables': dict(child_tables or {}),
        }
    )


def _sort_sources_table(table):
    if 'source_id' not in table.schema.names or len(table) <= 1:
        return table
    ids = table['source_id'].to_pylist()
    order = sorted(range(len(ids)), key=lambda idx: ids[idx] or '')
    return table.take(pa.array(order, type=pa.int64()))


def _sort_components_table(table):
    if len(table) <= 1:
        return table
    rows = table.to_pylist()
    order = sorted(
        range(len(rows)),
        key=lambda idx: (
            rows[idx].get('filename') is None,
            rows[idx].get('filename') or '',
            rows[idx].get('document_id') or '',
        ),
    )
    return table.take(pa.array(order, type=pa.int64()))


def export_viewer_pins(
    sources_table,
    components_table,
    target_dir,
    *,
    catalog_id='export-pin-catalog',
    version='v-export-01',
    channel='viewer',
    compression_policy=DEFAULT_COMPRESSION_POLICY,
    policy=DEFAULT_DECODED_POLICY,
    row_group_rows=OCCURRENCE_ROW_GROUP_ROWS,
):
    """Materialize sorted ``sources.parquet``, ``components.parquet``, and flat ``occurrences.parquet`` with ``ExportPin`` metadata."""
    from datetime import datetime, timezone
    from congress_api.retention.derived_files import file_identity

    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    compression = validate_compression(compression_policy)

    sorted_sources = _sort_sources_table(sources_table)
    sorted_components = _sort_components_table(components_table)

    source_occ_child = {}
    has_source_obs = None
    if 'source_occurrences' in sorted_sources.schema.names:
        occ_path = target_dir / 'occurrences.parquet'
        occ_info = publish_occurrence_parquet(
            sorted_sources,
            occ_path,
            owner_ids=sorted_sources['source_id'].to_pylist(),
            policy=policy,
            compression_policy=compression,
            row_group_rows=row_group_rows,
        )
        has_source_obs = [count > 0 for _, count in occ_info['row_slices']]
        occ_ident = file_identity(occ_path)
        source_occ_child['occurrences'] = {
            'name': 'occurrences',
            'group': 'occurrences',
            'file': {
                'group': 'occurrences',
                'path': 'occurrences.parquet',
                'digest': occ_ident['sha256'],
                'sha256': occ_ident['sha256'],
                'bytes': occ_ident['bytes'],
                'rows': occ_info['rows'],
                'parent_rows': occ_info['parent_rows'],
                'fields': occ_info['fields'],
                'row_slices': occ_info['row_slices'],
            },
            'total_rows': occ_info['rows'],
            'total_bytes': occ_ident['bytes'],
            'browse_ranges': occ_info['browse_ranges'],
        }

    folded_sources = fold_source_readings_table(sorted_sources, has_observations_list=has_source_obs)
    sources_path = target_dir / 'sources.parquet'
    pq.write_table(
        folded_sources,
        sources_path,
        compression=compression.codec,
        compression_level=compression.level,
        row_group_size=int(row_group_rows),
        write_page_index=True,
        write_statistics=True,
    )
    sources_ident = file_identity(sources_path)
    _, visible_fields = visible_reading_fields(sorted_sources.schema.names)
    source_policy = build_source_export_policy(
        destination_dir=target_dir,
        reading_fields=visible_fields or DEFAULT_SOURCE_READING_FIELDS,
        row_group_rows=row_group_rows,
    )
    source_facets = compute_facet_entries(
        sorted_sources,
        [c for c in DEFAULT_SOURCE_FACET_COLUMNS if c in sorted_sources.schema.names],
        facet_set='sources_facets',
    )
    source_ranges = compute_browse_ranges(
        sources_path,
        ['source_id', 'document_id'],
        group='source',
    )
    sources_pin = build_export_pin_descriptor(
        dataset='filename-sources',
        version=version,
        operation=f'exp-sources-{version}',
        channel=channel,
        destination=target_dir,
        policy=source_policy,
        primary_file={
            'group': 'source',
            'path': 'sources.parquet',
            'digest': sources_ident['sha256'],
            'sha256': sources_ident['sha256'],
            'bytes': sources_ident['bytes'],
            'rows': len(folded_sources),
        },
        facets=source_facets,
        browse_ranges=source_ranges,
        child_tables=source_occ_child,
    )

    comp_occ_child = {}
    if 'source_occurrences' in sorted_components.schema.names:
        doc_occ_path = target_dir / 'document_occurrences.parquet'
        doc_occ_info = publish_occurrence_parquet(
            sorted_components,
            doc_occ_path,
            owner_ids=sorted_components['document_id'].to_pylist(),
            policy=policy,
            compression_policy=compression,
            row_group_rows=row_group_rows,
        )
        doc_occ_ident = file_identity(doc_occ_path)
        comp_occ_child['occurrences'] = {
            'name': 'occurrences',
            'group': 'occurrences',
            'file': {
                'group': 'occurrences',
                'path': 'document_occurrences.parquet',
                'digest': doc_occ_ident['sha256'],
                'sha256': doc_occ_ident['sha256'],
                'bytes': doc_occ_ident['bytes'],
                'rows': doc_occ_info['rows'],
                'parent_rows': doc_occ_info['parent_rows'],
                'fields': doc_occ_info['fields'],
                'row_slices': doc_occ_info['row_slices'],
            },
            'total_rows': doc_occ_info['rows'],
            'total_bytes': doc_occ_ident['bytes'],
            'browse_ranges': doc_occ_info['browse_ranges'],
        }

    comp_core_schema = pa.schema(
        [f for f in sorted_components.schema if f.name != 'source_occurrences'],
        metadata=sorted_components.schema.metadata,
    )
    comp_core_table = sorted_components.select(comp_core_schema.names)
    components_path = target_dir / 'components.parquet'
    pq.write_table(
        comp_core_table,
        components_path,
        compression=compression.codec,
        compression_level=compression.level,
        row_group_size=int(row_group_rows),
        write_page_index=True,
        write_statistics=True,
    )
    components_ident = file_identity(components_path)
    component_policy = build_component_export_policy(
        destination_dir=target_dir,
        row_group_rows=row_group_rows,
    )
    component_facets = compute_facet_entries(
        comp_core_table,
        [c for c in DEFAULT_COMPONENT_FACET_COLUMNS if c in comp_core_table.schema.names],
        facet_set='components_facets',
    )
    component_ranges = compute_browse_ranges(
        components_path,
        ['filename', 'document_id'],
        group='source',
    )
    components_pin = build_export_pin_descriptor(
        dataset='filename-components',
        version=version,
        operation=f'exp-components-{version}',
        channel=channel,
        destination=target_dir,
        policy=component_policy,
        primary_file={
            'group': 'source',
            'path': 'components.parquet',
            'digest': components_ident['sha256'],
            'sha256': components_ident['sha256'],
            'bytes': components_ident['bytes'],
            'rows': len(comp_core_table),
        },
        facets=component_facets,
        browse_ranges=component_ranges,
        child_tables=comp_occ_child,
    )

    facets_map = {}
    for col in DEFAULT_SOURCE_FACET_COLUMNS:
        col_summary = facet_summary(sources_pin, facet_set='sources_facets', column=col)
        facets_map[col] = sorted(col_summary['values'])

    manifest = {
        'version': 6,
        'published_at': datetime.now(timezone.utc).isoformat(),
        'info': {
            'catalog_id': catalog_id,
            'rows': len(folded_sources),
            'entries': len(comp_core_table),
            'documents': len(comp_core_table),
            'capture_records': 0,
            'api_reference_groups': 0,
            'video_reference_groups': 0,
            'fields': list(sorted_sources.schema.names),
            'document_fields': list(sorted_components.schema.names),
            'facets': facets_map,
            'bytes': sources_ident['bytes'] + components_ident['bytes'],
            'generation': version,
            'house_naming_version': 'export-pin-v1',
        },
        'exports': {
            'sources': sources_pin,
            'components': components_pin,
        },
    }
    (target_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    return {
        'manifest': manifest,
        'sources': sources_pin,
        'components': components_pin,
        'specs': {
            'sources': build_source_export_spec(
                'filename-sources',
                operation=f'exp-sources-{version}',
                version=version,
                destination=target_dir,
                channel=channel,
                reading_fields=visible_fields or DEFAULT_SOURCE_READING_FIELDS,
                row_group_rows=row_group_rows,
            ),
            'components': build_component_export_spec(
                'filename-components',
                operation=f'exp-components-{version}',
                version=version,
                destination=target_dir,
                channel=channel,
                row_group_rows=row_group_rows,
            ),
        },
    }

