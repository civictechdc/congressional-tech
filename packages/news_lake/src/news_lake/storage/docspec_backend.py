"""DocSpec backend: news_lake records and bridge tables in `docspec-rs`.

This module is the maintained alternative backend for the news lake's raw
tables (Iceberg via ``storage.coordinator``) and derived views (Python via
``analysis.views``). The native engine (`docspec-rs`, a prebuilt local binary)
owns admission, versions, completion, concurrency and recovery for the datasets
it keeps; this module never duplicates those lifecycle decisions.

Three pieces:

- ``DocSpecClient`` — one interface over two transports to the same engine:
  one-shot CLI invocations with a per-request scratch directory, and a
  persistent loopback HTTP host (``docspec serve``) behind a context manager.
- ``merge_upsert_batch`` / ``DocSpecLake`` — C1 evidence-union upsert merging
  (``storage.coordinator._merge_upsert`` semantics) and record routing into
  ``news_*`` datasets, mirroring the contract's table routing and mutations.
- ``DocSpecNewsViews`` — the ``entity_roots`` / ``selected_mentions`` /
  ``survivor_items`` relational bridges (``analysis.bridges``) admitted as
  native datasets, then ``politician_articles`` (native join) and
  ``coverage_daily`` (native aggregate, including the undated NULL bucket)
  assembled back into the Python view shapes.

Deliberate representation choices:

- ``selected_mentions.occurrences`` is stored as a native
  ``list<struct<field, start, end>>`` column and projected directly through the
  native ``politician_articles`` join.
- ``coverage_daily.identical_text_group_ids`` is computed natively via
  ``AggregateFunction::CollectSet`` (``collect_set``) over
  ``survivor_items.identical_text_group_id``.
- Record datasets keep the contract's JSON value space (instants/dates stay
  canonical strings), so a native readback converts back to records losslessly
  by dropping absent-optional nulls.
"""
from contextlib import contextmanager
from hashlib import sha256
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import urllib.error
from urllib.parse import quote, urlsplit
import urllib.request

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from news_lake.analysis import bridges
from news_lake.analysis.export import export_release
from news_lake.analysis.views import _by_kind, _merge_spans
from news_lake.context import canonicalize_record_instants
from news_lake.contract.records import (
    CONTENT_TABLES,
    CONTRACT_VERSION,
    KIND_ORDER,
    KIND_TABLES,
    SCHEMA,
    TABLE_KINDS,
    TABLE_MUTATIONS,
    validate_shape,
)
from news_lake.contract.semantics import check_corpus
from docspec_client.docspec import NativeDatasets, cleanup_safe
from docspec_client.docspec_host import DocSpecFailure

from news_lake.identity.decisions import apply_decisions  # noqa: F401  (bridge input)
from news_lake.storage.coordinator import CommitError, _merge_upsert
from news_lake.storage.releases import ReleaseError, _redact_checkpoints

# One recipe identity for every news dataset; the schema is derived from the
# contract and never changes inside a workspace without a new definition.
DEFINITION = 'news-v1'
DEFAULT_LIFECYCLE_COMPACT_INTERVAL = 16
DEFAULT_COMPACT_FILE_THRESHOLD = 32
DEFAULT_COMPACT_TARGET_FILE_BYTES = 64 * 1024 * 1024


def _table_pin_parquet_objects(table_pin):
    """Return distinct active Parquet data file objects from a TablePin."""
    if not isinstance(table_pin, dict):
        return []
    objects = table_pin.get('objects') or ()
    seen = set()
    result = []
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        path = obj.get('path')
        if isinstance(path, str) and path.endswith('.parquet') and path not in seen:
            seen.add(path)
            result.append(obj)
    return result


def _source_parquet_objects(pin):
    """Return distinct active Parquet data file objects from a ReleasePin's source group."""
    if not isinstance(pin, dict):
        return []
    table_pin = pin.get('dataset', {}).get('groups', {}).get('source')
    return _table_pin_parquet_objects(table_pin)


def _undersized_parquet_files(table_pin, target_file_bytes=DEFAULT_COMPACT_TARGET_FILE_BYTES):
    """Return paths of active Parquet data files smaller than ``target_file_bytes``."""
    limit = (
        int(target_file_bytes)
        if target_file_bytes and int(target_file_bytes) > 0
        else DEFAULT_COMPACT_TARGET_FILE_BYTES
    )
    return [
        obj['path']
        for obj in _table_pin_parquet_objects(table_pin)
        if int(obj.get('bytes') or 0) < limit
    ]


class AppendCollisionError(CommitError, ValueError):
    """Conflicting ID reuse on an append-only dataset (both CommitError and ValueError)."""


# The storage-type mapping has one owner: docspec_client. Keep the historical
# news_lake name for callers and __all__ while delegating every decision there.
from docspec_client.docspec import native_storage_schema  # noqa: E402  (re-export)


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

    When ``expected_schema`` is supplied, ``Decimal128(20, 0)`` is restored to
    ``UInt64`` only where the declared application field is ``UInt64``; genuine
    ``Decimal128`` fields remain ``Decimal128``.
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


def sanitize_id(value, *, prefix='id'):
    """Fit an application name into the engine's bounded ASCII identifier rule.

    The engine accepts 1-128 ASCII letters, digits, underscores and hyphens
    (``Id::new``); dots and other punctuation are replaced so record tables
    (``news.outlets``) map to dataset ids (``news_outlets``).
    """
    cleaned = re.sub(r'[^A-Za-z0-9_-]+', '_', str(value)).strip('_')[:128]
    return cleaned or prefix


def dataset_id_for(table):
    """The native dataset id for a contract table or record kind name."""
    return sanitize_id(table.replace('.', '_'))


def version_ref(pin):
    """The exact consumed ``VersionRef`` of a release pin (engine input shape)."""
    dataset = pin['dataset']
    return {'dataset': dataset['dataset'], 'version': dataset['version'],
            'manifest': pin['manifest']}


def str_canonical(value):
    if value is None:
        return None
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False, default=str)


def content_digest(records):
    """A stable digest over record values, for replay-stable operation ids."""
    return sha256(str_canonical(records).encode('utf-8')).hexdigest()


def _resolve_ref(definition):
    while '$ref' in definition:
        definition = SCHEMA['$defs'][definition['$ref'].split('/')[-1]]
    return definition


def _arrow_type(definition):
    """Contract JSON-Schema types to Arrow, keeping the JSON value space.

    Strings stay strings (including the instant/date formats, which the
    contract already constrains to canonical renderings); objects become
    nullable structs in declaration order; arrays get non-null elements
    because the contract rejects explicit nulls anywhere.
    """
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
        return pa.struct([pa.field(name, _arrow_type(child), nullable=True)
                          for name, child in definition.get('properties', {}).items()])
    raise ValueError(f'unsupported contract type for the DocSpec backend: {definition!r}')


_KIND_SCHEMAS = {}


def kind_arrow_schema(kind):
    """The full physical Arrow schema for one record kind (contract-derived).

    Every declared property is a column, so a batch that omits optional
    fields produces the same schema as one that carries them; this is what
    keeps successive batches admissible without a schema change. The ``kind``
    column rides along so readback is self-describing.
    """
    if kind not in _KIND_SCHEMAS:
        definition = SCHEMA['$defs'][kind]
        _KIND_SCHEMAS[kind] = pa.schema([
            pa.field(name, _arrow_type(child), nullable=True)
            for name, child in definition['properties'].items()
        ])
    return _KIND_SCHEMAS[kind]


def records_to_arrow(kind, records):
    """Serialize records of one kind into the contract-derived Arrow schema."""
    return pa.Table.from_pylist(list(records), schema=kind_arrow_schema(kind))


def _strip_nulls(value):
    """Drop absent-optional nulls so a native readback equals the submitted record."""
    if isinstance(value, dict):
        return {key: _strip_nulls(child) for key, child in value.items() if child is not None}
    if isinstance(value, list):
        return [_strip_nulls(child) for child in value]
    return value


def table_records(table):
    """Convert a native readback table back into plain JSON values.

    Join/aggregate outputs carry ``__docspec_*`` position and provenance
    columns in their source group; they are engine metadata, not record
    fields, and are dropped here along with absent-optional nulls.
    """
    columns = [name for name in table.column_names if not name.startswith('__docspec_')]
    return [_strip_nulls(row) for row in table.select(columns).to_pylist()]


def merge_upsert_batch(existing_records, incoming_records):
    """Merge incoming upsert records into existing rows by ``id`` (C1).

    Each merged pair follows ``storage.coordinator._merge_upsert``: list
    evidence unions with dedup, scalars come from the more recent
    ``recorded_at`` poll, absent fields backfill, and ``first_seen_at`` keeps
    the earlier instant. Merged rows are re-validated against the contract.
    """
    by_id = {record['id']: record for record in existing_records}
    merged = []
    for record in incoming_records:
        prior = by_id.get(record['id'])
        candidate = _merge_upsert(prior, record) if prior is not None else record
        validate_shape(candidate)
        merged.append(candidate)
    return merged


def _file_digest(path):
    """Stream a SHA-256 digest so large exports are never materialized in memory."""
    digest = sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


class DocSpecClient:
    """Thin news adapter over the shared ``docspec_client`` transport.

    Readiness, deadlines, owned-host lifetime, exact-pin streaming, schema
    restoration and unknown-outcome producer custody all live in
    ``docspec_client``. This class keeps the historical news
    constructor and request-builder shape while adding no second transport.
    """

    def __init__(self, workspace, binary=None, *, timeout=120):
        resolved = (binary or os.environ.get('DOCSPEC_BINARY')
                    or shutil.which('docspec'))
        if not resolved:
            raise DocSpecFailure(
                ('docspec',),
                subprocess.CompletedProcess(
                    ('docspec',),
                    127,
                    stderr='no DocSpec runtime configured; set DOCSPEC_BINARY or install docspec',
                ),
            )
        self._native = NativeDatasets(resolved, workspace, timeout=timeout)
        self.binary = self._native.binary
        self.workspace = self._native.workspace
        self.timeout = timeout
        self._dataset_schemas = {}

    @classmethod
    def default_binary_path(cls):
        """The configured immutable runtime, never a mutable developer build."""
        return os.environ.get('DOCSPEC_BINARY') or shutil.which('docspec')

    @contextmanager
    def serve(self):
        """The shared transport owns one persistent host for this client."""
        yield self

    def close(self):
        self._native.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- operations ----------------------------------------------------------

    def hash_input(self, path):
        return self._native.hash_input(path)

    def latest(self, dataset):
        return self._native.latest(dataset)

    def try_latest(self, dataset):
        try:
            return self.latest(dataset)
        except DocSpecFailure as error:
            if error.code == 'no_release' or 'no_release' in error.stderr:
                return None
            raise

    def release(self, dataset, version):
        return self._native.release(dataset, version)

    def refresh(self, spec):
        return self._native.refresh(spec)

    def seal_generation(self, spec):
        return self._native.seal_generation(spec)

    def export(self, spec):
        return self._native.export(spec)

    def latest_export(self, dataset, channel):
        return self._native.latest_export(dataset, channel)

    def try_latest_export(self, dataset, channel):
        return self._native.try_latest_export(dataset, channel)

    def export_pin(self, dataset, operation):
        return self._native.export_pin(dataset, operation)

    def try_export_pin(self, dataset, operation):
        return self._native.try_export_pin(dataset, operation)

    def compact(self, spec, *, operation=None, version=None, group='source',
                files=(), target_file_bytes=DEFAULT_COMPACT_TARGET_FILE_BYTES):
        if isinstance(spec, str):
            return self._native.compact(
                spec,
                operation=operation,
                version=version,
                group=group,
                files=files,
                target_file_bytes=target_file_bytes,
            )
        return self._native.compact(spec)

    def compact_table(self, dataset, *, operation, version, group='source',
                      files=(), target_file_bytes=DEFAULT_COMPACT_TARGET_FILE_BYTES):
        return self._native.compact_table(
            dataset,
            operation=operation,
            version=version,
            group=group,
            files=files,
            target_file_bytes=target_file_bytes,
        )

    def compact_lifecycle(self, dataset):
        return self._native.compact_lifecycle(dataset)

    def read_arrow(self, release_pin, group='source', *, schema=None):
        dataset = release_pin['dataset']['dataset']
        if schema is None and group == 'source':
            schema = self._dataset_schemas.get(dataset)
        table = self._native.read_arrow(release_pin, group, schema=None)
        if schema is not None:
            return restore_application_schema(table, expected_schema=schema)
        return table

    def read_keys(self, release_pin, key, values, *, columns=None, schema=None):
        """Stream only rows matching ``values`` on ``key`` from an exact release pin."""
        dataset = release_pin['dataset']['dataset']
        if schema is None and columns is None:
            schema = self._dataset_schemas.get(dataset)
        elif schema is not None and columns is not None:
            schema = pa.schema([schema.field(name) for name in columns])
        table = self._native.read_keys(
            release_pin, key, values, columns=columns, schema=None
        )
        if schema is not None:
            return restore_application_schema(table, expected_schema=schema)
        return table

    def capture_inputs(self, inputs):
        return self._native.capture_inputs(inputs)

    def run_table(self, table, dataset, operation, definition=DEFINITION,
                  relationship=None, base=None):
        """Admit one caller-bounded Arrow table as a dataset build."""
        self._dataset_schemas[dataset] = table.schema
        return self._native.run_table(
            table,
            dataset=dataset,
            operation=operation,
            definition=definition,
            relationship=relationship,
            base=base,
        )

    def update_table(self, dataset, operation, base, keys, replacements_table,
                     deletions=None, definition=DEFINITION, relationship=None):
        """Replace or insert complete rows by key against the exact selected base."""
        self._dataset_schemas[dataset] = replacements_table.schema
        return self._native.update_table(
            replacements_table,
            dataset=dataset,
            operation=operation,
            definition=definition,
            base=base,
            keys=list(keys),
            deletions=deletions,
            relationship=relationship,
        )

    def retained_producer_inputs(self):
        return self._native.retained_producer_inputs()


class DocSpecLake:
    """Route news_lake records into native datasets, one per contract table.

    Upsert tables (outlets/items/entities) merge each incoming poll against
    the stored row for its id so earlier evidence survives (C1), then submit
    the merged rows as a complete-key update. Append tables admit the initial
    batch as a build and subsequent batches as complete-key updates against the
    exact prior version so earlier rows and unchanged files remain retained.
    """

    def __init__(self, client, workspace_suffix='', *,
                 lifecycle_compact_interval=DEFAULT_LIFECYCLE_COMPACT_INTERVAL,
                 compact_file_threshold=DEFAULT_COMPACT_FILE_THRESHOLD,
                 compact_target_file_bytes=DEFAULT_COMPACT_TARGET_FILE_BYTES):
        self.client = client
        self.workspace_suffix = sanitize_id(workspace_suffix) if workspace_suffix else ''
        self.lifecycle_compact_interval = lifecycle_compact_interval
        self.compact_file_threshold = compact_file_threshold
        self._compact_file_threshold = compact_file_threshold
        self.compact_target_file_bytes = compact_target_file_bytes
        self._compact_target_file_bytes = compact_target_file_bytes
        self.committed = self._load_committed_state()
        self._mutation_counts = self._load_mutation_counts()
        self._compacted_pins = {}
        self.last_lookup_stats = {}
        self.lifecycle_compactions = []
        self.table_compactions = []

    def _committed_state_path(self):
        suffix = f'-{self.workspace_suffix}' if self.workspace_suffix else ''
        return self.client.workspace / f'.news_lake_committed{suffix}.json'

    def _mutation_counts_path(self):
        suffix = f'-{self.workspace_suffix}' if self.workspace_suffix else ''
        return self.client.workspace / f'.news_lake_mutations{suffix}.json'

    def _release_manifest_path(self, release_id):
        suffix = f'-{self.workspace_suffix}' if self.workspace_suffix else ''
        return self.client.workspace / f'releases{suffix}' / f'{sanitize_id(release_id)}.json'

    def _load_committed_state(self):
        path = self._committed_state_path()
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text())
            return dict(data) if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _load_mutation_counts(self):
        path = self._mutation_counts_path()
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text())
            return {
                str(k): int(v)
                for k, v in data.items()
                if isinstance(v, int) and not isinstance(v, bool)
            } if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_committed_state(self):
        path = self._committed_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.json.tmp')
        tmp.write_text(
            json.dumps(self.committed, ensure_ascii=False, separators=(',', ':'), allow_nan=False, default=str)
        )
        tmp.replace(path)
        mpath = self._mutation_counts_path()
        mtmp = mpath.with_suffix('.json.tmp')
        mtmp.write_text(
            json.dumps(self._mutation_counts, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        )
        mtmp.replace(mpath)

    def compact_lifecycle(self, datasets=None):
        """Compact obsolete lifecycle revisions for local datasets."""
        if getattr(self.client._native, 'remote', None) is not None:
            return {}
        targets = list(self.committed if datasets is None else datasets)
        results = {}
        for dataset in targets:
            report = self.client.compact_lifecycle(dataset)
            self._mutation_counts[dataset] = 0
            entry = {'dataset': dataset, **(report if isinstance(report, dict) else {})}
            self.lifecycle_compactions.append(entry)
            results[dataset] = report
        if results:
            self._save_committed_state()
        return results

    def _record_dataset_mutation(self, dataset, prior_pin, new_pin):
        if new_pin is None:
            return False
        prior_ver = (prior_pin or {}).get('dataset', {}).get('version')
        new_ver = new_pin.get('dataset', {}).get('version')
        if prior_ver == new_ver:
            return False
        self._mutation_counts[dataset] = self._mutation_counts.get(dataset, 0) + 1
        return True

    def _maybe_compact_lifecycle(self, datasets):
        interval = self.lifecycle_compact_interval
        if not interval or interval < 1:
            return {}
        due = [
            ds for ds in datasets
            if self._mutation_counts.get(ds, 0) >= interval
        ]
        return self.compact_lifecycle(due) if due else {}

    def _effective_source_table_pin(self, dataset, pin):
        if not isinstance(pin, dict):
            return {}
        version = pin.get('dataset', {}).get('version')
        compacted = self._compacted_pins.get(dataset)
        if isinstance(compacted, dict) and compacted.get('version') == version:
            replacement = compacted.get('replacement')
            if isinstance(replacement, dict):
                return replacement
        return pin.get('dataset', {}).get('groups', {}).get('source') or {}

    def active_parquet_files(self, dataset, *, pin=None):
        """Return active Parquet data file objects for ``dataset``."""
        resolved_dataset = self._dataset(dataset)
        target_pin = (
            pin
            or self.committed.get(resolved_dataset)
            or self.client.try_latest(resolved_dataset)
        )
        if target_pin is None:
            return []
        table_pin = self._effective_source_table_pin(resolved_dataset, target_pin)
        return _table_pin_parquet_objects(table_pin)

    def compact_table(self, dataset, *, pin=None, target_file_bytes=None, force=True):
        """Run native table compaction on undersized Parquet files of ``dataset``."""
        if getattr(self.client._native, 'remote', None) is not None:
            return None
        resolved_dataset = self._dataset(dataset)
        target_pin = (
            pin
            or self.committed.get(resolved_dataset)
            or self.client.try_latest(resolved_dataset)
        )
        if target_pin is None:
            return None
        limit = (
            int(target_file_bytes)
            if target_file_bytes is not None
            else int(self.compact_target_file_bytes or DEFAULT_COMPACT_TARGET_FILE_BYTES)
        )
        if limit <= 0:
            limit = DEFAULT_COMPACT_TARGET_FILE_BYTES
        table_pin = self._effective_source_table_pin(resolved_dataset, target_pin)
        undersized = _undersized_parquet_files(table_pin, limit)
        if len(undersized) < 2:
            return None
        if not force:
            threshold = self.compact_file_threshold
            if not threshold or threshold < 1 or len(undersized) < threshold:
                return None
        version = target_pin['dataset']['version']
        operation = self._operation(
            f'compact-{resolved_dataset}',
            content_digest([version, undersized, limit]),
        )
        report = self.client.compact({
            'dataset': resolved_dataset,
            'operation': operation,
            'version': version,
            'group': 'source',
            'files': undersized,
            'target_file_bytes': limit,
        })
        if isinstance(report, dict) and isinstance(report.get('replacement'), dict):
            self._compacted_pins[resolved_dataset] = {
                'version': version,
                'replacement': report['replacement'],
            }
        input_files = list((report or {}).get('input_files') or undersized)
        output_files = list((report or {}).get('output_files') or ())
        entry = {
            'dataset': resolved_dataset,
            'version': version,
            'operation': operation,
            'group': 'source',
            'files_before': len(input_files),
            'files_after': len(output_files),
            'rewritten_files': len(input_files),
            'produced_files': len(output_files),
            **(report if isinstance(report, dict) else {}),
        }
        self.table_compactions.append(entry)
        return entry

    def compact_tables(self, datasets=None, *, target_file_bytes=None, force=True):
        """Run native table compaction across committed (or specified) datasets."""
        targets = list(self.committed if datasets is None else datasets)
        results = {}
        for dataset in targets:
            resolved = self._dataset(dataset)
            report = self.compact_table(
                resolved,
                target_file_bytes=target_file_bytes,
                force=force,
            )
            if report is not None:
                results[resolved] = report
        return results

    def _maybe_compact_table(self, dataset, pin, *, incoming_files=1):
        threshold = self.compact_file_threshold
        if not threshold or threshold < 1 or pin is None:
            return None
        resolved = self._dataset(dataset)
        limit = int(self.compact_target_file_bytes or DEFAULT_COMPACT_TARGET_FILE_BYTES)
        if limit <= 0:
            limit = DEFAULT_COMPACT_TARGET_FILE_BYTES
        table_pin = self._effective_source_table_pin(resolved, pin)
        undersized = _undersized_parquet_files(table_pin, limit)
        if len(undersized) < 2 or len(undersized) + int(incoming_files) < threshold:
            return None
        return self.compact_table(resolved, pin=pin, target_file_bytes=limit, force=True)

    def _dataset(self, kind_or_table):
        return dataset_id_for(KIND_TABLES.get(kind_or_table, kind_or_table))

    def _operation(self, label, digest):
        name = f'{label}-{digest[:16]}'
        if self.workspace_suffix:
            name = f'{name}-{self.workspace_suffix}'
        return sanitize_id(name)

    def _dedup_incoming(self, dataset, records, *, is_append):
        deduped = []
        by_id = {}
        for record in records:
            prior = by_id.get(record['id'])
            if prior is not None:
                if prior != record:
                    raise AppendCollisionError(
                        'append_collision' if is_append else 'batch_id_collision',
                        f'id {record["id"]} appears twice in the batch with different values on {dataset}',
                        record_id=record['id'],
                    )
                continue
            by_id[record['id']] = record
            deduped.append(record)
        return deduped

    def _existing_by_ids(self, pin, kind, ids):
        """Fetch only the rows matching ``ids`` from the exact ``pin`` via ``read_keys``."""
        id_list = sorted(set(ids))
        dataset = pin['dataset']['dataset']
        if not id_list:
            self.last_lookup_stats[dataset] = {
                'requested_ids': 0,
                'matched_rows': 0,
                'rows_transferred': 0,
                'total_rows': pin.get('dataset', {}).get('groups', {}).get('source', {}).get('rows', 0),
            }
            return {}
        table = self.client.read_keys(
            pin, 'id', id_list, schema=kind_arrow_schema(kind)
        )
        rows = table_records(table)
        self.last_lookup_stats[dataset] = {
            'requested_ids': len(id_list),
            'matched_rows': len(rows),
            'rows_transferred': table.num_rows,
            'total_rows': pin.get('dataset', {}).get('groups', {}).get('source', {}).get('rows', table.num_rows),
        }
        return {row['id']: row for row in rows}

    def commit_records(self, records, generation=None, family='news', *,
                       ensure_all_tables=False):
        """Validate and commit one batch; returns ``{dataset: latest ReleasePin}``.

        Records route by ``kind`` exactly as the contract's ``x-iceberg``
        annotations do for Iceberg: upsert datasets merge by ``id`` before an
        update, append datasets admit the initial batch as a build and
        subsequent batches as keyed updates preserving prior rows. With a
        ``generation``, every produced version declares the coupled producer
        relationship so the datasets can be sealed together afterwards.
        """
        relationship = ({'kind': 'coupled', 'family': family, 'generation': generation}
                        if generation is not None else None)
        batch = {}
        for record in records:
            validate_shape(record)
            canonical = canonicalize_record_instants(record)
            batch.setdefault(canonical['kind'], []).append(canonical)
        pins = dict(self.committed)
        mutated = []
        for kind in KIND_ORDER:
            if kind == 'release':
                continue
            records_of_kind = batch.get(kind)
            dataset = self._dataset(kind)
            prior = pins.get(dataset)
            if not records_of_kind:
                if prior is not None and relationship is not None:
                    pins[dataset] = self._advance_relationship(dataset, kind, prior, relationship)
                    if self._record_dataset_mutation(dataset, prior, pins[dataset]):
                        mutated.append(dataset)
                elif prior is None and ensure_all_tables:
                    operation = self._operation(
                        f'admit-empty-{kind}', content_digest([dataset, relationship])
                    )
                    pins[dataset] = self.client.run_table(
                        records_to_arrow(kind, ()), dataset, operation, relationship=relationship
                    )
                    if self._record_dataset_mutation(dataset, prior, pins[dataset]):
                        mutated.append(dataset)
                continue
            if TABLE_MUTATIONS[KIND_TABLES[kind]] == 'upsert':
                pins[dataset] = self._commit_upsert(dataset, kind, records_of_kind, relationship)
            else:
                pins[dataset] = self._commit_append(dataset, kind, records_of_kind, relationship)
            if self._record_dataset_mutation(dataset, prior, pins[dataset]):
                mutated.append(dataset)
        self.committed = pins
        self._save_committed_state()
        if mutated:
            self._maybe_compact_lifecycle(mutated)
        return dict(pins)

    def _advance_relationship(self, dataset, kind, prior, relationship):
        if relationship is None or prior.get('dataset', {}).get('relationship') == relationship:
            return prior
        base_version = prior['dataset']['version']
        operation = self._operation(
            f'rel-{kind}', content_digest([base_version, relationship])
        )
        return self.client.update_table(
            dataset,
            operation,
            base_version,
            ['id'],
            records_to_arrow(kind, ()),
            relationship=relationship,
        )

    def _commit_append(self, dataset, kind, records, relationship):
        records = self._dedup_incoming(dataset, records, is_append=True)
        prior = self.committed.get(dataset) or self.client.try_latest(dataset)
        if prior is None:
            operation = self._operation(f'admit-{kind}', content_digest(records))
            return self.client.run_table(
                records_to_arrow(kind, records), dataset, operation, relationship=relationship
            )
        existing = self._existing_by_ids(prior, kind, (record['id'] for record in records))
        new_records = []
        for record in records:
            stored = existing.get(record['id'])
            if stored is not None:
                if stored == record:
                    continue
                raise AppendCollisionError(
                    'append_collision',
                    f'id {record["id"]} already exists with different values on append-only {dataset}',
                    record_id=record['id'],
                )
            new_records.append(record)
        if not new_records:
            return self._advance_relationship(dataset, kind, prior, relationship)
        self._maybe_compact_table(dataset, prior, incoming_files=1)
        base_version = prior['dataset']['version']
        operation = self._operation(
            f'append-{kind}', content_digest([base_version, new_records, relationship])
        )
        return self.client.update_table(
            dataset,
            operation,
            base_version,
            ['id'],
            records_to_arrow(kind, new_records),
            relationship=relationship,
        )

    def _commit_upsert(self, dataset, kind, records, relationship):
        records = self._dedup_incoming(dataset, records, is_append=False)
        prior = self.committed.get(dataset) or self.client.try_latest(dataset)
        if prior is None:
            operation = self._operation(f'admit-{kind}', content_digest(records))
            return self.client.run_table(
                records_to_arrow(kind, records), dataset, operation, relationship=relationship
            )
        existing = self._existing_by_ids(prior, kind, (record['id'] for record in records))
        merged = merge_upsert_batch(list(existing.values()), records)
        changed = [row for row in merged if existing.get(row['id']) != row]
        if not changed:
            return self._advance_relationship(dataset, kind, prior, relationship)
        self._maybe_compact_table(dataset, prior, incoming_files=1)
        base_version = prior['dataset']['version']
        operation = self._operation(
            f'upsert-{kind}', content_digest([base_version, changed, relationship])
        )
        return self.client.update_table(
            dataset,
            operation,
            base_version,
            ['id'],
            records_to_arrow(kind, changed),
            relationship=relationship,
        )

    def seal(self, generation_id, family='news'):
        """Seal the committed datasets as one generation of ``family``.

        Members are the latest selected version of every dataset this lake
        committed; the first seal fixes the family's dataset membership, so
        every commit that participates must have declared the relationship.
        """
        if not self.committed:
            raise ValueError('seal requires committed datasets')
        members = {dataset: version_ref(pin) for dataset, pin in self.committed.items()}
        return self.client.seal_generation(
            {'family': family, 'generation': generation_id, 'members': members})

    def read_dataset(self, dataset):
        """Read a dataset's selected source group as an Arrow table."""
        pin = self.committed.get(dataset) or self.client.latest(dataset)
        return self.client.read_arrow(pin)

    def _table_uuid(self, table_name, pin=None):
        if pin is not None:
            meta_path = pin.get('dataset', {}).get('groups', {}).get('source', {}).get('metadata', {}).get('path')
            if isinstance(meta_path, str) and Path(meta_path).is_file():
                try:
                    meta = json.loads(Path(meta_path).read_text())
                    if isinstance(meta, dict) and isinstance(meta.get('table-uuid'), str):
                        return meta['table-uuid']
                except (OSError, ValueError):
                    pass
        from uuid import NAMESPACE_URL, uuid5
        return str(uuid5(NAMESPACE_URL, f'docspec-news-lake:{self.client.workspace}:{table_name}'))

    def build_release(self, release_id, recorded_at, selections, checkpoints, *, pins=None):
        """Build a contract-valid ``release`` record bound to exact ``DocSpecLake`` pins."""
        active_pins = dict(self.committed if pins is None else pins)
        snapshots = []
        for table_name in CONTENT_TABLES:
            dataset = dataset_id_for(table_name)
            pin = active_pins.get(dataset)
            entry = {
                'table': table_name,
                'table_uuid': self._table_uuid(table_name, pin=pin),
            }
            if pin is not None:
                snap = pin.get('dataset', {}).get('groups', {}).get('source', {}).get('snapshot')
                rows = pin.get('dataset', {}).get('groups', {}).get('source', {}).get('rows', 0)
                if snap is not None and rows > 0:
                    entry['snapshot_id'] = str(snap)
            snapshots.append(entry)
        return {
            'kind': 'release',
            'id': release_id,
            'recorded_at': recorded_at,
            'contract_version': CONTRACT_VERSION,
            'snapshots': snapshots,
            'selections': list(selections),
            'checkpoints': _redact_checkpoints(checkpoints),
        }

    def publish_release(self, control, records, *, release_id, recorded_at,
                        selections=(), checkpoints=(), epoch=None, faults=None):
        """Publish one release through ``DocSpecLake`` + ``ControlStore`` (I2/I3/I4)."""
        from news_lake.storage.coordinator import Faults
        faults = faults if faults is not None else Faults()
        if epoch is None:
            epoch = control.claim('docspec-news-writer')
        control.require_epoch(epoch)
        payload = {
            'records': list(records),
            'recorded_at': recorded_at,
            'selections': list(selections),
            'checkpoints': _redact_checkpoints(checkpoints),
        }
        faults.before('journal_write')
        stored = control.begin_cycle(release_id, payload, epoch=epoch)
        if stored is not None:
            payload = stored
        faults.after('journal_write')
        state = control.cycle_state(release_id)
        if state == 'done':
            return self.find_release(release_id)
        if state == 'abandoned':
            raise ReleaseError(
                'cycle_abandoned',
                f'cycle {release_id} was abandoned after failed validation; publish under a new release id',
                release_id=release_id,
            )
        gen_id = sanitize_id(f'rel-{release_id}')
        if state == 'intent':
            faults.before('table_commit')
            pins = self.commit_records(
                payload['records'],
                generation=gen_id,
                family='news',
                ensure_all_tables=True,
            )
            if pins:
                self.seal(gen_id, family='news')
            faults.after('table_commit')
            payload['dataset_pins'] = pins
            control.update_cycle_payload(release_id, payload, epoch=epoch)
            control.set_cycle_state(release_id, 'committed', epoch=epoch)
            state = 'committed'

        pins = payload.get('dataset_pins') or dict(self.committed)
        release = payload.get('release')
        if release is None:
            release = self.build_release(
                release_id,
                payload['recorded_at'],
                payload['selections'],
                payload['checkpoints'],
                pins=pins,
            )
            payload['release'] = release
            control.update_cycle_payload(release_id, payload, epoch=epoch)

        pinned_records = []
        table_pins = {}
        for entry in release['snapshots']:
            table_name = entry['table']
            dataset = dataset_id_for(table_name)
            pin = pins.get(dataset)
            if pin is not None:
                table_pins[table_name] = pin
            if 'snapshot_id' not in entry or pin is None:
                continue
            kind = TABLE_KINDS[table_name]
            pinned_records.extend(
                table_records(self.client.read_arrow(pin, schema=kind_arrow_schema(kind)))
            )
        check_corpus(pinned_records + [release])
        control.mark_snapshots_validated(
            [(entry['table'], entry['snapshot_id'])
             for entry in release['snapshots'] if 'snapshot_id' in entry],
            epoch=epoch,
        )
        if state == 'committed':
            control.set_cycle_state(release_id, 'validated', epoch=epoch)
            state = 'validated'
        if state == 'validated':
            faults.before('checkpoint_stage')
            for checkpoint in payload['checkpoints']:
                key = checkpoint['connector_key']
                faults.before(f'checkpoint_stage:{key}')
                control.stage_checkpoint(release_id, checkpoint, epoch=epoch)
                faults.after(f'checkpoint_stage:{key}')
            faults.after('checkpoint_stage')
            control.set_cycle_state(release_id, 'checkpoints_staged', epoch=epoch)
            state = 'checkpoints_staged'
        if state == 'checkpoints_staged':
            faults.before('release_append')
            manifest_path = self._release_manifest_path(release_id)
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = manifest_path.with_suffix('.json.tmp')
            tmp.write_text(
                json.dumps(
                    {
                        'release': release,
                        'dataset_pins': pins,
                        'table_pins': table_pins,
                        'generation': gen_id,
                    },
                    ensure_ascii=False,
                    separators=(',', ':'),
                    allow_nan=False,
                    default=str,
                )
            )
            tmp.replace(manifest_path)
            faults.after('release_append')
            control.set_cycle_state(release_id, 'released', epoch=epoch)
            state = 'released'
        if state == 'released':
            faults.before('cursor_advance')
            control.mark_available(release_id, epoch=epoch)
            control.activate_checkpoints(release_id, epoch=epoch)
            faults.after('cursor_advance')
            control.set_cycle_state(release_id, 'done', epoch=epoch)
        return release

    def find_release(self, release_id):
        manifest_path = self._release_manifest_path(release_id)
        if not manifest_path.is_file():
            return None
        try:
            data = json.loads(manifest_path.read_text())
            return data.get('release') if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

    def read_release(self, control, release_id, tables=None):
        """Read an exact published release from its pinned ``ReleasePin``s (never ``latest``)."""
        manifest_path = self._release_manifest_path(release_id)
        if not manifest_path.is_file():
            raise ReleaseError('unknown_release', 'no release record with this id', release_id=release_id)
        manifest = json.loads(manifest_path.read_text())
        record = manifest['release']
        table_pins = manifest.get('table_pins') or {}
        status = control.availability(release_id)
        if status is None:
            raise ReleaseError(
                'unreleased_release',
                'release record exists but publication never marked it available',
                release_id=release_id,
            )
        if status == 'retired':
            raise ReleaseError(
                'retired_release',
                'release is retired in the availability registry',
                release_id=release_id,
            )
        if status != 'available':
            raise ReleaseError('unreleased_release', f'release status is {status!r}', release_id=release_id)
        if record.get('contract_version') != CONTRACT_VERSION:
            raise ReleaseError(
                'contract_version_mismatch',
                f'release contract_version {record.get("contract_version")!r} does not match reader {CONTRACT_VERSION!r}',
                release_id=release_id,
            )
        entries = record['snapshots']
        if tables is not None:
            requested = set(tables)
            known = {entry['table'] for entry in entries}
            unknown = requested - known
            if unknown:
                raise ReleaseError(
                    'unknown_table',
                    f'requested tables are not pinned by this release: {sorted(unknown)}',
                    release_id=release_id,
                )
            entries = [entry for entry in entries if entry['table'] in requested]
        if table_pins:
            inputs = {
                pin['dataset']['dataset']: version_ref(pin)
                for pin in table_pins.values()
            }
            self.client.capture_inputs(inputs)
        result = {}
        for entry in entries:
            table_name = entry['table']
            if 'snapshot_id' not in entry:
                result[table_name] = []
                continue
            pin = table_pins.get(table_name)
            if pin is None:
                raise ReleaseError('missing_snapshot', f'{table_name} pin is missing', release_id=release_id)
            expected_uuid = self._table_uuid(table_name, pin=pin)
            if expected_uuid != entry['table_uuid']:
                raise ReleaseError('table_uuid_mismatch', f'{table_name} UUID differs from the release', release_id=release_id)
            kind = TABLE_KINDS[table_name]
            result[table_name] = table_records(
                self.client.read_arrow(pin, schema=kind_arrow_schema(kind))
            )
        return {
            'release': record,
            'tables': result,
            'dataset_pins': dict(table_pins),
        }


class DocSpecNewsViews:
    """Materialize the relational bridges natively and run the C9 views on them.

    ``materialize`` admits ``entity_roots``, ``selected_mentions`` and
    ``survivor_items`` (``analysis.bridges``) as datasets and records their
    exact ``ReleasePin``s in ``self.pins``; ``update_bridges`` diffs new bridge
    rows against the current pinned bridge tables and issues keyed
    ``update_table`` calls only for changed/removed keys;
    ``politician_articles`` refreshes a native join of ``selected_mentions``
    and ``entity_roots`` (projecting ``occurrences`` as a native
    ``list<struct>`` column) and assembles the Python row shape;
    ``coverage_daily`` refreshes a native Date32-keyed aggregate over
    ``survivor_items`` (the undated bucket is the NULL key group, and
    ``identical_text_group_ids`` is collected natively via ``collect_set``).
    """

    SELECTED_MENTIONS_SCHEMA = bridges.SELECTED_MENTIONS_SCHEMA

    def __init__(self, client, workspace_suffix='', *, pins=None,
                 lifecycle_compact_interval=DEFAULT_LIFECYCLE_COMPACT_INTERVAL,
                 compact_file_threshold=DEFAULT_COMPACT_FILE_THRESHOLD,
                 compact_target_file_bytes=DEFAULT_COMPACT_TARGET_FILE_BYTES):
        self.client = client
        self.workspace_suffix = sanitize_id(workspace_suffix) if workspace_suffix else ''
        self.lifecycle_compact_interval = lifecycle_compact_interval
        self.compact_file_threshold = compact_file_threshold
        self._compact_file_threshold = compact_file_threshold
        self.compact_target_file_bytes = compact_target_file_bytes
        self._compact_target_file_bytes = compact_target_file_bytes
        persisted_pins, persisted_rows, persisted_versions, persisted_mutations = self._load_views_state()
        self.pins = dict(pins) if pins is not None else persisted_pins
        self._bridge_rows = persisted_rows if pins is None else {}
        self._bridge_versions = persisted_versions if pins is None else {}
        self._mutation_counts = persisted_mutations if pins is None else {}
        self._compacted_pins = {}
        self.last_bridge_diff = {}
        self.lifecycle_compactions = []
        self.table_compactions = []

    def _views_state_path(self):
        suffix = f'-{self.workspace_suffix}' if self.workspace_suffix else ''
        return self.client.workspace / f'.news_lake_views{suffix}.json'

    def _load_views_state(self):
        path = self._views_state_path()
        if not path.is_file():
            return {}, {}, {}, {}
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict):
                return {}, {}, {}, {}
            return (
                dict(data.get('pins') or {}),
                dict(data.get('bridge_rows') or {}),
                dict(data.get('bridge_versions') or {}),
                {
                    str(k): int(v)
                    for k, v in (data.get('mutation_counts') or {}).items()
                    if isinstance(v, int) and not isinstance(v, bool)
                },
            )
        except (OSError, ValueError):
            return {}, {}, {}, {}

    def _save_views_state(self):
        path = self._views_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.json.tmp')
        tmp.write_text(
            json.dumps(
                {
                    'pins': self.pins,
                    'bridge_rows': self._bridge_rows,
                    'bridge_versions': self._bridge_versions,
                    'mutation_counts': self._mutation_counts,
                },
                ensure_ascii=False,
                separators=(',', ':'),
                allow_nan=False,
                default=str,
            )
        )
        tmp.replace(path)

    def compact_lifecycle(self, datasets=None):
        """Compact obsolete lifecycle revisions for local bridge and view datasets."""
        if getattr(self.client._native, 'remote', None) is not None:
            return {}
        targets = list(self.pins if datasets is None else datasets)
        results = {}
        for dataset in targets:
            report = self.client.compact_lifecycle(dataset)
            self._mutation_counts[dataset] = 0
            entry = {'dataset': dataset, **(report if isinstance(report, dict) else {})}
            self.lifecycle_compactions.append(entry)
            results[dataset] = report
        if results:
            self._save_views_state()
        return results

    def _record_view_mutation(self, dataset):
        self._mutation_counts[dataset] = self._mutation_counts.get(dataset, 0) + 1
        interval = self.lifecycle_compact_interval
        if interval and interval >= 1 and self._mutation_counts[dataset] >= interval:
            self.compact_lifecycle([dataset])

    def _effective_source_table_pin(self, dataset, pin):
        if not isinstance(pin, dict):
            return {}
        version = pin.get('dataset', {}).get('version')
        compacted = self._compacted_pins.get(dataset)
        if isinstance(compacted, dict) and compacted.get('version') == version:
            replacement = compacted.get('replacement')
            if isinstance(replacement, dict):
                return replacement
        return pin.get('dataset', {}).get('groups', {}).get('source') or {}

    def active_parquet_files(self, dataset, *, pin=None):
        """Return active Parquet data file objects for ``dataset``."""
        resolved = sanitize_id(dataset)
        target_pin = pin or self.pins.get(resolved) or self.client.try_latest(resolved)
        if target_pin is None:
            return []
        table_pin = self._effective_source_table_pin(resolved, target_pin)
        return _table_pin_parquet_objects(table_pin)

    def compact_table(self, dataset, *, pin=None, target_file_bytes=None, force=True):
        """Run native table compaction on undersized Parquet files of ``dataset``."""
        if getattr(self.client._native, 'remote', None) is not None:
            return None
        resolved = sanitize_id(dataset)
        target_pin = pin or self.pins.get(resolved) or self.client.try_latest(resolved)
        if target_pin is None:
            return None
        limit = (
            int(target_file_bytes)
            if target_file_bytes is not None
            else int(self.compact_target_file_bytes or DEFAULT_COMPACT_TARGET_FILE_BYTES)
        )
        if limit <= 0:
            limit = DEFAULT_COMPACT_TARGET_FILE_BYTES
        table_pin = self._effective_source_table_pin(resolved, target_pin)
        undersized = _undersized_parquet_files(table_pin, limit)
        if len(undersized) < 2:
            return None
        if not force:
            threshold = self.compact_file_threshold
            if not threshold or threshold < 1 or len(undersized) < threshold:
                return None
        version = target_pin['dataset']['version']
        operation = self._operation(
            f'compact-{resolved}',
            content_digest([version, undersized, limit]),
        )
        report = self.client.compact({
            'dataset': resolved,
            'operation': operation,
            'version': version,
            'group': 'source',
            'files': undersized,
            'target_file_bytes': limit,
        })
        if isinstance(report, dict) and isinstance(report.get('replacement'), dict):
            self._compacted_pins[resolved] = {
                'version': version,
                'replacement': report['replacement'],
            }
        input_files = list((report or {}).get('input_files') or undersized)
        output_files = list((report or {}).get('output_files') or ())
        entry = {
            'dataset': resolved,
            'version': version,
            'operation': operation,
            'group': 'source',
            'files_before': len(input_files),
            'files_after': len(output_files),
            'rewritten_files': len(input_files),
            'produced_files': len(output_files),
            **(report if isinstance(report, dict) else {}),
        }
        self.table_compactions.append(entry)
        return entry

    def compact_tables(self, datasets=None, *, target_file_bytes=None, force=True):
        """Run native table compaction across pinned (or specified) bridge/view datasets."""
        targets = list(self.pins if datasets is None else datasets)
        results = {}
        for dataset in targets:
            resolved = sanitize_id(dataset)
            report = self.compact_table(
                resolved,
                target_file_bytes=target_file_bytes,
                force=force,
            )
            if report is not None:
                results[resolved] = report
        return results

    def _maybe_compact_table(self, dataset, pin, *, incoming_files=1):
        threshold = self.compact_file_threshold
        if not threshold or threshold < 1 or pin is None:
            return None
        resolved = sanitize_id(dataset)
        limit = int(self.compact_target_file_bytes or DEFAULT_COMPACT_TARGET_FILE_BYTES)
        if limit <= 0:
            limit = DEFAULT_COMPACT_TARGET_FILE_BYTES
        table_pin = self._effective_source_table_pin(resolved, pin)
        undersized = _undersized_parquet_files(table_pin, limit)
        if len(undersized) < 2 or len(undersized) + int(incoming_files) < threshold:
            return None
        return self.compact_table(resolved, pin=pin, target_file_bytes=limit, force=True)

    # -- materialization & incremental bridge updates ------------------------

    def _operation(self, label, digest):
        name = f'{label}-{digest[:16]}'
        if self.workspace_suffix:
            name = f'{name}-{self.workspace_suffix}'
        return sanitize_id(name)

    @staticmethod
    def _unwrap(records_or_release_read, selections=None):
        """Accept a release read (``release`` + ``tables``) or flat records."""
        if isinstance(records_or_release_read, dict) and 'tables' in records_or_release_read:
            flat = [record for rows in records_or_release_read['tables'].values()
                    for record in rows]
            release = records_or_release_read['release']
            if selections is None:
                selections = release.get('selections', ())
            return flat, selections, release['id']
        return (list(records_or_release_read),
                (() if selections is None else selections), None)

    def _pin(self, dataset):
        pin = self.pins.get(dataset)
        if pin is None:
            pin = self.client.latest(dataset)
            self.pins[dataset] = pin
        return pin

    def _bridge_pin_for_refresh(self, dataset, view_dataset, mode):
        """Return the pinned bridge version; sync from client if updated directly before incremental."""
        pin = self._pin(dataset)
        if mode == 'incremental':
            view_pin = self.pins.get(view_dataset)
            if view_pin is not None:
                related = view_pin.get('dataset', {}).get('related') or {}
                consumed_inputs = (related.get('coverage') or {}).get('inputs') or {}
                consumed_ref = consumed_inputs.get(dataset)
                if consumed_ref == version_ref(pin):
                    latest_pin = self.client.try_latest(dataset)
                    if latest_pin is not None and version_ref(latest_pin) != version_ref(pin):
                        self.pins[dataset] = latest_pin
                        return latest_pin
        return pin

    def materialize(self, records_or_release_read, selections=None):
        """Admit the three bridge datasets; stores and returns ``{dataset: ReleasePin}``."""
        records, selections, _ = self._unwrap(records_or_release_read, selections)
        bridge_defs = {
            'entity_roots': (
                'entity_id',
                bridges.ENTITY_ROOTS_SCHEMA,
                bridges.entity_roots_rows(records),
            ),
            'selected_mentions': (
                'mention_id',
                bridges.SELECTED_MENTIONS_SCHEMA,
                bridges.selected_mentions_rows(records, selections),
            ),
            'survivor_items': (
                'item_id',
                bridges.SURVIVOR_ITEMS_SCHEMA,
                bridges.survivor_items_rows(records, selections),
            ),
        }
        pins = {}
        for dataset, (key_col, schema, rows) in bridge_defs.items():
            table = pa.Table.from_pylist(rows, schema=schema)
            stripped = _strip_nulls(rows)
            operation = self._operation(
                f'materialize-{dataset}', content_digest(stripped)
            )
            pin = self.client.run_table(table, dataset, operation)
            pins[dataset] = pin
            self._bridge_rows[dataset] = {row[key_col]: _strip_nulls(row) for row in rows}
            self._bridge_versions[dataset] = pin['dataset']['version']
        self.pins.update(pins)
        self._save_views_state()
        return dict(pins)

    def update_bridges(self, records_or_release_read, selections=None):
        """Diff new bridge rows against pinned bridge state and update only changed keys."""
        records, selections, _ = self._unwrap(records_or_release_read, selections)
        desired = {
            'entity_roots': (
                'entity_id',
                bridges.ENTITY_ROOTS_SCHEMA,
                bridges.entity_roots_rows(records),
            ),
            'selected_mentions': (
                'mention_id',
                bridges.SELECTED_MENTIONS_SCHEMA,
                bridges.selected_mentions_rows(records, selections),
            ),
            'survivor_items': (
                'item_id',
                bridges.SURVIVOR_ITEMS_SCHEMA,
                bridges.survivor_items_rows(records, selections),
            ),
        }
        updated_pins = {}
        diff_summary = {}
        for dataset, (key_col, schema, new_rows) in desired.items():
            prior_pin = self.pins.get(dataset) or self.client.try_latest(dataset)
            if prior_pin is None:
                table = pa.Table.from_pylist(new_rows, schema=schema)
                stripped = _strip_nulls(new_rows)
                operation = self._operation(
                    f'materialize-{dataset}', content_digest(stripped)
                )
                pin = self.client.run_table(table, dataset, operation)
                self.pins[dataset] = pin
                self._bridge_rows[dataset] = {row[key_col]: _strip_nulls(row) for row in new_rows}
                self._bridge_versions[dataset] = pin['dataset']['version']
                updated_pins[dataset] = pin
                diff_summary[dataset] = {
                    'changed_rows': len(new_rows),
                    'removed_keys': 0,
                    'full_table_reads': 0,
                    'updated': True,
                }
                continue
            prior_version = prior_pin['dataset']['version']
            if (
                dataset in self._bridge_rows
                and self._bridge_versions.get(dataset) == prior_version
            ):
                current_by_key = self._bridge_rows[dataset]
                full_reads = 0
            else:
                current_table = self.client.read_arrow(prior_pin, schema=schema)
                current_by_key = {
                    row[key_col]: row for row in table_records(current_table)
                }
                full_reads = 1
            changed_rows = [
                row for row in new_rows
                if str_canonical(current_by_key.get(row[key_col])) != str_canonical(_strip_nulls(row))
            ]
            new_keys = {row[key_col] for row in new_rows}
            removed_keys = sorted(set(current_by_key) - new_keys)
            diff_summary[dataset] = {
                'changed_rows': len(changed_rows),
                'removed_keys': len(removed_keys),
                'full_table_reads': full_reads,
                'updated': bool(changed_rows or removed_keys),
            }
            if not changed_rows and not removed_keys:
                self.pins[dataset] = prior_pin
                self._bridge_rows[dataset] = {row[key_col]: _strip_nulls(row) for row in new_rows}
                self._bridge_versions[dataset] = prior_version
                updated_pins[dataset] = prior_pin
                continue
            self._maybe_compact_table(
                dataset,
                prior_pin,
                incoming_files=1 if changed_rows else 0,
            )
            replacements_table = pa.Table.from_pylist(changed_rows, schema=schema)
            deletions_table = (
                pa.Table.from_pylist(
                    [{key_col: key} for key in removed_keys],
                    schema=pa.schema([schema.field(key_col)]),
                )
                if removed_keys
                else None
            )
            base_version = prior_version
            operation = self._operation(
                f'update-{dataset}',
                content_digest([base_version, _strip_nulls(changed_rows), removed_keys]),
            )
            pin = self.client.update_table(
                dataset,
                operation,
                base_version,
                [key_col],
                replacements_table,
                deletions=deletions_table,
            )
            self.pins[dataset] = pin
            self._bridge_rows[dataset] = {row[key_col]: _strip_nulls(row) for row in new_rows}
            self._bridge_versions[dataset] = pin['dataset']['version']
            updated_pins[dataset] = pin
            self._record_view_mutation(dataset)
        self.last_bridge_diff = diff_summary
        self._save_views_state()
        return dict(updated_pins)

    # -- native refreshes ----------------------------------------------------

    def _base_version(self, dataset, mode):
        if mode == 'full':
            return None
        pin = self.pins.get(dataset) or self.client.try_latest(dataset)
        if pin is None:
            raise ValueError(f"mode='incremental' requires a previous {dataset} version")
        self.pins[dataset] = pin
        return pin['dataset']['version']

    def _refresh_join_spec(self, base, mode, mentions_pin=None, roots_pin=None):
        if mentions_pin is None:
            mentions_pin = self._bridge_pin_for_refresh(
                'selected_mentions', 'politician_articles', mode
            )
        if roots_pin is None:
            roots_pin = self._bridge_pin_for_refresh(
                'entity_roots', 'politician_articles', mode
            )
        return dict(
            dataset='politician_articles', base=base, definition=DEFINITION, mode=mode,
            operation=self._operation(
                f'pa-{mode}',
                content_digest([base, mode, version_ref(mentions_pin), version_ref(roots_pin)])),
            transform={'kind': 'join',
                       'left': version_ref(mentions_pin),
                       'right': version_ref(roots_pin),
                       'join': {'keys': [{'left': 'entity_id', 'right': 'entity_id'}],
                                'kind': 'inner', 'nulls': 'never',
                                'cardinality': 'many_to_one',
                                'fields': [
                                    {'side': 'left', 'field': 'entity_id',
                                     'name': 'entity_id'},
                                    {'side': 'left', 'field': 'mention_id',
                                     'name': 'mention_id'},
                                    {'side': 'left', 'field': 'version_id',
                                     'name': 'version_id'},
                                    {'side': 'left', 'field': 'run_id', 'name': 'run_id'},
                                    {'side': 'left', 'field': 'surface', 'name': 'surface'},
                                    {'side': 'left', 'field': 'aboutness',
                                     'name': 'aboutness'},
                                    {'side': 'left', 'field': 'occurrences',
                                     'name': 'occurrences'},
                                    {'side': 'right', 'field': 'person_root_id',
                                     'name': 'person_root_id'},
                                    # entity_type of the root enables the person-only
                                    # filter during assembly (the join cannot filter).
                                    {'side': 'right', 'field': 'entity_type',
                                     'name': 'entity_type'},
                                ]}},
        )

    def politician_articles(self, records_or_release_read, mode='full', selections=None):
        """The ``politician_articles`` view through the native join.

        ``mode='incremental'`` replaces only the match groups the changed
        ``entity_roots`` / ``selected_mentions`` rows affect (requires a
        previous output version). Rows are assembled in Python from the joined
        output, the pinned ``survivor_items`` dataset and the release's
        versions, matching ``analysis.views.politician_articles`` field for field.
        """
        records, _, release_id = self._unwrap(records_or_release_read)
        base = self._base_version('politician_articles', mode)
        mentions_pin = self._bridge_pin_for_refresh(
            'selected_mentions', 'politician_articles', mode
        )
        roots_pin = self._bridge_pin_for_refresh(
            'entity_roots', 'politician_articles', mode
        )
        survivor_pin = self._pin('survivor_items')
        spec = self._refresh_join_spec(base, mode, mentions_pin=mentions_pin, roots_pin=roots_pin)
        pin = self.client.refresh(spec)
        self.pins['politician_articles'] = pin
        self._record_view_mutation('politician_articles')
        self._save_views_state()
        joined = table_records(self.client.read_arrow(pin))
        return self._assemble_politician_articles(records, release_id, joined, survivor_pin=survivor_pin)

    def _assemble_politician_articles(self, records, release_id, joined, *, survivor_pin=None):
        versions = _by_kind(list(records), 'version')
        if survivor_pin is None:
            survivor_pin = self._pin('survivor_items')
        needed_versions = sorted({
            row['version_id']
            for row in joined
            if row.get('entity_type') == 'person' and isinstance(row.get('version_id'), str)
        })
        if needed_versions:
            survivor_rows = table_records(
                self.client.read_keys(
                    survivor_pin,
                    'current_version_id',
                    needed_versions,
                    columns=['current_version_id', 'item_id'],
                    schema=bridges.SURVIVOR_ITEMS_SCHEMA,
                )
            )
        else:
            survivor_rows = []
        item_of_version = {row['current_version_id']: row['item_id']
                           for row in survivor_rows if 'current_version_id' in row}
        grouped = {}
        for row in joined:
            if row.get('entity_type') != 'person':
                continue
            version_id = row['version_id']
            item_id = item_of_version.get(version_id)
            if item_id is None:  # a mention of a non-survivor version asserts nothing
                continue
            key = (row['person_root_id'], item_id)
            entry = grouped.setdefault(key, {
                'release_id': release_id,
                'person_root_id': key[0],
                'entity_ids': set(), 'item_id': item_id, 'version_id': version_id,
                'run_ids': set(), 'aboutness': set(), 'surfaces': set(), '_spans': [],
            })
            entry['entity_ids'].add(row['entity_id'])
            entry['run_ids'].add(row['run_id'])
            entry['aboutness'].add(row['aboutness'])
            entry['surfaces'].add(row['surface'])
            entry['_spans'].extend(
                {'field': span['field'], 'surface': row['surface'],
                 'start': span['start'], 'end': span['end']}
                for span in row['occurrences'])
        result = []
        for entry in grouped.values():
            version = versions.get(entry['version_id'])
            result.append({
                'release_id': entry['release_id'],
                'person_root_id': entry['person_root_id'],
                'entity_ids': sorted(entry['entity_ids']),
                'item_id': entry['item_id'],
                'version_id': entry['version_id'],
                'run_ids': sorted(entry['run_ids']),
                'aboutness': sorted(entry['aboutness']),
                'surfaces': sorted(entry['surfaces']),
                'spans': _merge_spans(entry['_spans'], version=version),
            })
        return sorted(result, key=lambda row: (row['person_root_id'], row['item_id']))

    def _refresh_aggregate_spec(self, base, mode, survivor_pin=None):
        if survivor_pin is None:
            survivor_pin = self._bridge_pin_for_refresh(
                'survivor_items', 'coverage_daily', mode
            )
        return dict(
            dataset='coverage_daily', base=base, definition=DEFINITION, mode=mode,
            operation=self._operation(
                f'cov-{mode}',
                content_digest([base, mode, version_ref(survivor_pin)])),
            transform={'kind': 'aggregate',
                       'input': version_ref(survivor_pin),
                       'grouping': {'keys': ['effective_pub_date'],
                                    'aggregates': [
                                        {'name': 'rows',
                                         'function': {'kind': 'count_rows'}},
                                        {'name': 'items',
                                         'function': {'kind': 'count_distinct',
                                                      'field': 'item_id'}},
                                        {'name': 'outlets',
                                         'function': {'kind': 'count_distinct',
                                                      'field': 'outlet_id'}},
                                        {'name': 'stories',
                                         'function': {'kind': 'count_distinct',
                                                      'field': 'story_id'}},
                                        {'name': 'identical_text_group_ids',
                                         'function': {'kind': 'collect_set',
                                                      'field': 'identical_text_group_id'}},
                                    ]}},
        )

    def coverage_daily(self, records_or_release_read, mode='full', selections=None):
        """The ``coverage_daily`` view through the native aggregate.

        The grouping key is the ``survivor_items`` ``effective_pub_date``
        Date32 column; NULL keys form exactly one undated group. The native
        ``rows`` count is computed but not emitted (the Python view has no
        such field). ``identical_text_group_ids`` is collected natively via
        ``collect_set`` over ``identical_text_group_id``.
        """
        _, _, release_id = self._unwrap(records_or_release_read)
        base = self._base_version('coverage_daily', mode)
        survivor_pin = self._bridge_pin_for_refresh(
            'survivor_items', 'coverage_daily', mode
        )
        spec = self._refresh_aggregate_spec(base, mode, survivor_pin=survivor_pin)
        pin = self.client.refresh(spec)
        self.pins['coverage_daily'] = pin
        self._record_view_mutation('coverage_daily')
        self._save_views_state()
        aggregate = table_records(self.client.read_arrow(pin))
        return self._assemble_coverage_daily(release_id, aggregate)

    def _assemble_coverage_daily(self, release_id, aggregate):
        rows = []
        # The undated bucket's NULL key is absent after null-stripping, so
        # reads of the grouping key use .get.
        ordered = sorted(aggregate, key=lambda row: (
            row.get('effective_pub_date') is None,
            row['effective_pub_date'].isoformat()
            if row.get('effective_pub_date') is not None else ''))
        for row in ordered:
            day = row.get('effective_pub_date')
            bucket_date = day.isoformat() if day is not None else None
            rows.append({
                'release_id': release_id,
                'date': bucket_date,
                'undated': bucket_date is None,
                'items': row['items'],
                'outlets': row['outlets'],
                'stories': row['stories'],
                # Visibility for syndication, never an independent-reporting
                # count (C9): text groups that repeat across the corpus,
                # collected and sorted natively by AggregateFunction::CollectSet.
                'identical_text_group_ids': list(row.get('identical_text_group_ids') or ()),
            })
        return rows

    # -- C5-authorized native export -----------------------------------------

    @staticmethod
    def _ensure_release_read(records_or_release_read):
        if not (isinstance(records_or_release_read, dict)
                and 'tables' in records_or_release_read
                and isinstance(records_or_release_read.get('release'), dict)
                and records_or_release_read['release'].get('id')):
            raise ValueError(
                'authorized export requires an exact published release read; '
                'raw record lists are not a release identity')
        return records_or_release_read

    def export_authorized(self, records_or_release_read, destination_dir=None, *,
                          as_of=None, now=None, authorized=False, channel='public',
                          dataset_pins=None):
        """Apply C5 rights and capture-expiry rules, then run native Parquet exports.

        Enforces ``news_lake.analysis.export.export_release`` before admitting
        any export dataset version so restricted or expired captures/versions
        are downgraded to ``metadata_only`` and stripped of bodies prior to
        native ``ExportSpec`` materialization.

        ``dataset_pins`` optionally maps a release table name to the exact native
        ``ReleasePin`` that already retains those rows. When C5 filtering leaves a
        table unchanged, that pin is exported directly instead of re-admitting a
        duplicate staging dataset.
        """
        release_read = self._ensure_release_read(records_or_release_read)
        if dataset_pins is None and isinstance(release_read.get('dataset_pins'), dict):
            dataset_pins = dict(release_read['dataset_pins'])
        else:
            dataset_pins = dict(dataset_pins or {})
        effective_now = as_of if as_of is not None else now
        filtered = export_release(release_read, authorized=authorized, now=effective_now)
        dest_root = Path(destination_dir).resolve() if destination_dir is not None else None
        if dest_root is not None:
            dest_root.mkdir(parents=True, exist_ok=True)

        pins = {}
        files = {}
        for table_name, rows in sorted(filtered['tables'].items()):
            if not rows:
                continue
            kind = TABLE_KINDS[table_name]
            logical_dataset = dataset_id_for(table_name)
            export_dataset = sanitize_id(f'export_{logical_dataset}')
            arrow_table = records_to_arrow(kind, rows)
            unchanged = rows == release_read['tables'].get(table_name)
            pinned = dataset_pins.get(table_name)
            if unchanged and pinned is not None:
                source_pin = pinned
            else:
                admit_digest = content_digest([filtered['release']['id'], table_name, rows])
                admit_op = self._operation(f'admit-exp-{kind}', admit_digest)
                prior_pin = self.client.try_latest(export_dataset)
                if prior_pin is not None and prior_pin['dataset']['version'] == admit_op:
                    source_pin = prior_pin
                else:
                    source_pin = self.client.run_table(arrow_table, export_dataset, admit_op)

            columns = list(arrow_table.schema.names)
            channel_id = sanitize_id(channel)
            export_op = self._operation(
                f'exp-{kind}',
                content_digest([version_ref(source_pin), channel_id, columns]),
            )
            existing_export = self.client.try_export_pin(source_pin['dataset']['dataset'], export_op)
            if existing_export is not None:
                export_pin = existing_export
            else:
                current_channel = self.client.try_latest_export(
                    source_pin['dataset']['dataset'], channel_id)
                expected = current_channel['id'] if current_channel is not None else None
                export_spec = {
                    'dataset': source_pin['dataset']['dataset'],
                    'operation': export_op,
                    'source': version_ref(source_pin),
                    'channel': channel_id,
                    'expected': expected,
                    'policy': {
                        'group': 'source',
                        'rows': 'all',
                        'columns': columns,
                    },
                }
                export_pin = self.client.export(export_spec)

            pins[logical_dataset] = export_pin
            pins[table_name] = export_pin
            exported_path = Path(export_pin['object']['path'])
            if dest_root is not None:
                dest_file = dest_root / f'{logical_dataset}.parquet'
                if not dest_file.exists() or _file_digest(dest_file) != _file_digest(exported_path):
                    try:
                        if dest_file.exists():
                            dest_file.unlink()
                        os.link(exported_path, dest_file)
                    except OSError:
                        shutil.copyfile(exported_path, dest_file)
                files[logical_dataset] = str(dest_file)
                files[table_name] = str(dest_file)
            else:
                files[logical_dataset] = str(exported_path)
                files[table_name] = str(exported_path)

        result = {
            'release': filtered['release'],
            'tables': filtered['tables'],
            'pins': pins,
            'files': files,
        }
        for key, pin in pins.items():
            if not key.startswith('news.'):
                result[key] = pin
        return result


__all__ = [
    'AppendCollisionError',
    'DEFAULT_COMPACT_FILE_THRESHOLD',
    'DEFAULT_COMPACT_TARGET_FILE_BYTES',
    'DEFAULT_LIFECYCLE_COMPACT_INTERVAL',
    'DEFINITION',
    'DocSpecClient',
    'DocSpecFailure',
    'DocSpecLake',
    'DocSpecNewsViews',
    'application_schema',
    'content_digest',
    'dataset_id_for',
    'kind_arrow_schema',
    'merge_upsert_batch',
    'native_storage_schema',
    'records_to_arrow',
    'restore_application_schema',
    'sanitize_id',
    'table_records',
    'version_ref',
]
