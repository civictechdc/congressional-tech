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
from datetime import date
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
from news_lake.analysis.cluster import text_group_key
from news_lake.analysis.export import export_release
from news_lake.analysis.views import _by_kind, _merge_spans, _publication_date
from news_lake.context import canonicalize_record_instants, parse_instant
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
from congress_shared.custody import canonical_json_bytes, verify_local_file, write_atomic_bytes
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

# Physical Update keys per append-only record kind (ct-xu1o).
# The contract logical key stays ['id'] everywhere (stored ids and C1-C9
# semantics are unchanged). Prepending an input-derived deterministic time
# column that clusters by poll lets docspec-rs per-column point pruning
# (src/engine/write/key_points.rs: exact Point::String for canonical ISO-8601
# UTC instant strings in kind_arrow_schema, or Point::Int(i64) for
# Timestamp(Microsecond, UTC) in native scale benchmarks) skip older Parquet
# files whose [min, max] time bounds precede the incoming poll, even though
# deterministic uuid5 ids span the full key range:
# - capture (news.captures): ('id',) — keeps ['id'] because AdapterContext
#   mints RFC 9562 time-ordered UUIDv7 ids (ct-ur2y) that already cluster by
#   poll time.
# - discovery (news.discoveries): ('observed_at', 'id') — derived from capture
#   observed_at / fetched_at (RssAdapter.ingest, MediaCloudAdapter.parse_page,
#   GdeltAdapter.parse_page), never commit wall-clock time.
# - version (news.versions): ('recorded_at', 'id') — contract version records
#   store the capture's observed_at / fetched_at in recorded_at
#   (RssAdapter.ingest sets version['recorded_at'] = capture['observed_at']).
# - mention (news.mentions): ('recorded_at', 'id') — contract mention records
#   store their creation timestamp in recorded_at, copied deterministically
#   from the producing linking run's recorded_at (identity.linking.link_mentions).
# - classification (news.classifications): ('recorded_at', 'id') — contract
#   classification records store their creation timestamp in recorded_at,
#   copied from the producing classification run's recorded_at
#   (analysis.labels.classify).
# - identity_decision (news.identity_decisions): ('recorded_at', 'id') —
#   contract identity_decision records store their decision timestamp in
#   recorded_at, which defines canonical C6 application order
#   (identity.decisions._decision_order).
# - run (news.runs): ('started_at', 'id') — the run's pinned started_at
#   instant (context.build_run).
# - story (news.stories): ('recorded_at', 'id') — contract story records store
#   their creation timestamp in recorded_at, copied from the producing
#   clustering run's recorded_at (analysis.cluster.cluster).
# - story_member (news.story_members): ('recorded_at', 'id') — contract
#   story_member records store their addition timestamp in recorded_at, copied
#   from the producing clustering run's recorded_at (analysis.cluster.cluster).
APPEND_UPDATE_KEYS = {
    'capture': ('id',),
    'discovery': ('observed_at', 'id'),
    'version': ('recorded_at', 'id'),
    'identity_decision': ('recorded_at', 'id'),
    'run': ('started_at', 'id'),
    'mention': ('recorded_at', 'id'),
    'classification': ('recorded_at', 'id'),
    'story': ('recorded_at', 'id'),
    'story_member': ('recorded_at', 'id'),
}


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
    return canonical_json_bytes(
        value, ensure_ascii=False, allow_nan=False, default=str
    ).decode('utf-8')


def content_digest(records):
    """A stable digest over record values, for replay-stable operation ids."""
    return sha256(
        canonical_json_bytes(records, ensure_ascii=False, allow_nan=False, default=str)
    ).hexdigest()


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
    return verify_local_file(path).sha256


class DocSpecClient:
    """Thin news adapter over the shared ``docspec_client`` transport.

    Readiness, deadlines, owned-host lifetime, exact-pin streaming, schema
    restoration and unknown-outcome producer custody all live in
    ``docspec_client``. This class keeps the historical news
    constructor and request-builder shape while adding no second transport.
    """

    def __init__(self, workspace, binary=None, *, timeout=120, limits=None):
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
        self._native = NativeDatasets(resolved, workspace, timeout=timeout, limits=limits)
        self.binary = self._native.binary
        self.workspace = self._native.workspace
        self.limits = self._native.limits
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

    def inspect(self, dataset):
        return self._native.inspect(dataset)

    def refresh(self, spec):
        return self._native.refresh(spec)

    def plan_refresh(self, spec):
        return self._native.plan_refresh(spec)

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

    def _projected_schema(self, dataset, columns, schema, group='source'):
        if schema is None and group == 'source':
            schema = self._dataset_schemas.get(dataset)
        if schema is not None and columns is not None:
            return pa.schema([schema.field(name) for name in columns], metadata=schema.metadata)
        return schema

    @contextmanager
    def source_batches(self, release_pin, *, columns=None, schema=None):
        """Stream projected Arrow RecordBatches from an exact release pin."""
        dataset = release_pin['dataset']['dataset']
        target_schema = self._projected_schema(dataset, columns, schema, group='source')
        with self._native.source_batches(release_pin, columns=columns, schema=None) as reader:
            if target_schema is None:
                yield reader
            else:
                def restored_batches():
                    for batch in reader:
                        tbl = restore_application_schema(
                            pa.Table.from_batches([batch], schema=reader.schema),
                            expected_schema=target_schema,
                        )
                        yield from tbl.to_batches()

                with pa.RecordBatchReader.from_batches(target_schema, restored_batches()) as restored:
                    yield restored

    def iter_records(self, release_pin, *, columns=None, schema=None):
        """Stream projected records batch-by-batch without materializing a full table."""
        with self.source_batches(release_pin, columns=columns, schema=schema) as reader:
            for batch in reader:
                if batch.num_rows == 0:
                    continue
                yield from table_records(pa.Table.from_batches([batch], schema=reader.schema))

    def read_arrow(self, release_pin, group='source', *, columns=None, schema=None):
        dataset = release_pin['dataset']['dataset']
        target_schema = self._projected_schema(dataset, columns, schema, group=group)
        table = self._native.read_arrow(release_pin, group, columns=columns, schema=None)
        if target_schema is not None:
            return restore_application_schema(table, expected_schema=target_schema)
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

    @contextmanager
    def changes_batches(self, before, after, *, group='source', identity='occurrences',
                        force_full=False):
        """Stream one exact change stream and its ``docspec.change`` descriptor."""
        with self._native.changes_batches(
            before, after, group=group, identity=identity, force_full=force_full
        ) as result:
            yield result

    def read_changes(self, before, after, *, group='source', identity='occurrences',
                     force_full=False):
        """Consume one change stream, returning ``dict(descriptor, table, ...)``."""
        return self._native.read_changes(
            before, after, group=group, identity=identity, force_full=force_full
        )

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
        self._compacted_pins = {}
        self.committed = self._load_committed_state()
        self._mutation_counts = self._load_mutation_counts()
        self._known_ids = {}
        self._pending_lifecycle_compactions = set()
        self.last_lookup_stats = {}
        self.lifecycle_compactions = []
        self.table_compactions = []

    def _committed_state_path(self):
        suffix = f'-{self.workspace_suffix}' if self.workspace_suffix else ''
        return self.client.workspace / f'.news_lake_committed{suffix}.json'

    def _mutation_counts_path(self):
        suffix = f'-{self.workspace_suffix}' if self.workspace_suffix else ''
        return self.client.workspace / f'.news_lake_mutations{suffix}.json'

    def _compacted_pins_path(self):
        suffix = f'-{self.workspace_suffix}' if self.workspace_suffix else ''
        return self.client.workspace / f'.news_lake_compacted{suffix}.json'

    def _release_manifest_path(self, release_id):
        return self._releases_dir() / f'{sanitize_id(release_id)}.json'

    def _releases_dir(self):
        suffix = f'-{self.workspace_suffix}' if self.workspace_suffix else ''
        return self.client.workspace / f'releases{suffix}'

    def _has_any_release_manifest(self):
        releases_dir = self._releases_dir()
        if not releases_dir.is_dir():
            return False
        return any(
            p.is_file() and not p.name.endswith('.tmp')
            for p in releases_dir.glob('*.json')
        )

    def _load_committed_state(self):
        path = self._committed_state_path()
        committed = {}
        if path.is_file():
            try:
                data = json.loads(path.read_text())
                if isinstance(data, dict):
                    committed = dict(data)
            except (OSError, ValueError):
                committed = {}
        cpath = self._compacted_pins_path()
        compacted_pins = {}
        if cpath.is_file():
            try:
                raw_compacted = json.loads(cpath.read_text())
                if isinstance(raw_compacted, dict):
                    for ds, entry in raw_compacted.items():
                        if not isinstance(entry, dict) or not isinstance(entry.get('replacement'), dict):
                            continue
                        pin = committed.get(ds)
                        selected_ver = (
                            (pin or {}).get('dataset', {}).get('version')
                            or (pin or {}).get('selected_version')
                        )
                        if selected_ver and entry.get('version') == selected_ver:
                            compacted_pins[str(ds)] = {
                                'version': selected_ver,
                                'replacement': entry['replacement'],
                            }
            except (OSError, ValueError):
                compacted_pins = {}
        self._compacted_pins = compacted_pins
        return committed

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
        write_atomic_bytes(
            path,
            json.dumps(self.committed, ensure_ascii=False, separators=(',', ':'), allow_nan=False, default=str).encode('utf-8'),
            temp_mode='fixed',
            fsync=False,
        )
        mpath = self._mutation_counts_path()
        write_atomic_bytes(
            mpath,
            json.dumps(self._mutation_counts, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8'),
            temp_mode='fixed',
            fsync=False,
        )
        valid_compacted = {}
        for ds, entry in self._compacted_pins.items():
            if not isinstance(entry, dict) or not isinstance(entry.get('replacement'), dict):
                continue
            pin = self.committed.get(ds)
            selected_ver = (
                (pin or {}).get('dataset', {}).get('version')
                or (pin or {}).get('selected_version')
            )
            if selected_ver is None or entry.get('version') == selected_ver:
                valid_compacted[ds] = entry
        self._compacted_pins = valid_compacted
        cpath = self._compacted_pins_path()
        write_atomic_bytes(
            cpath,
            json.dumps(self._compacted_pins, ensure_ascii=False, separators=(',', ':'), allow_nan=False, default=str).encode('utf-8'),
            temp_mode='fixed',
            fsync=False,
        )

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
            self._pending_lifecycle_compactions.clear()
            return {}
        due = [
            ds for ds in datasets
            if self._mutation_counts.get(ds, 0) >= interval
            or ds in self._pending_lifecycle_compactions
        ]
        for ds in due:
            self._pending_lifecycle_compactions.discard(ds)
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

    def compact_table(self, dataset, *, pin=None, target_file_bytes=None,
                      compact_file_threshold=None, force=True):
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
        if compact_file_threshold is not None or not force:
            threshold = (
                self.compact_file_threshold
                if compact_file_threshold is None
                else compact_file_threshold
            )
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
            self._save_committed_state()
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

    def compact_tables(self, datasets=None, *, target_file_bytes=None,
                       compact_file_threshold=None, force=True):
        """Run native table compaction across committed (or specified) datasets."""
        targets = list(self.committed if datasets is None else datasets)
        results = {}
        for dataset in targets:
            resolved = self._dataset(dataset)
            report = self.compact_table(
                resolved,
                target_file_bytes=target_file_bytes,
                compact_file_threshold=compact_file_threshold,
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
                'requested_keys': 0,
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
            'requested_keys': len(id_list),
            'matched_rows': len(rows),
            'rows_transferred': table.num_rows,
            'total_rows': pin.get('dataset', {}).get('groups', {}).get('source', {}).get('rows', table.num_rows),
        }
        return {row['id']: row for row in rows}

    def _existing_for_append(self, pin, kind, records):
        """Fetch existing rows for an append batch using its physical update key (ct-xu1o).

        For time-keyed append tables (``keys = [time_col, 'id']``), queries
        ``read_keys`` on ``time_col`` so ``docspec-rs`` prunes every historical
        Parquet file whose ``time_col`` min/max bounds exclude the incoming
        poll's timestamps, then filters to the incoming ``id``s.
        """
        keys = self._update_keys_for(kind)
        if len(keys) <= 1:
            found = self._existing_by_ids(pin, kind, (record['id'] for record in records))
            dataset = pin['dataset']['dataset']
            self._known_ids.setdefault(dataset, set()).update(found.keys())
            return found

        time_col = keys[0]
        id_list = sorted({record['id'] for record in records})
        id_set = set(id_list)
        dataset = pin['dataset']['dataset']
        total_rows = pin.get('dataset', {}).get('groups', {}).get('source', {}).get('rows', 0)
        if not id_list:
            self.last_lookup_stats[dataset] = {
                'requested_ids': 0,
                'requested_keys': 0,
                'matched_rows': 0,
                'rows_transferred': 0,
                'total_rows': total_rows,
            }
            return {}
        time_values = sorted({str(record[time_col]) for record in records})
        table = self.client.read_keys(
            pin, time_col, time_values, schema=kind_arrow_schema(kind)
        )
        rows = table_records(table)
        found = {row['id']: row for row in rows if row['id'] in id_set}
        rows_transferred = int(table.num_rows)
        known = self._known_ids.setdefault(dataset, set())
        known.update(found.keys())
        missing_known = (id_set & known) - set(found)
        if missing_known:
            fallback_table = self.client.read_keys(
                pin, 'id', sorted(missing_known), schema=kind_arrow_schema(kind)
            )
            for row in table_records(fallback_table):
                if row['id'] in id_set:
                    found[row['id']] = row
            rows_transferred += int(fallback_table.num_rows)
        self.last_lookup_stats[dataset] = {
            'requested_ids': len(id_list),
            'requested_keys': len(id_list),
            'matched_rows': len(found),
            'rows_transferred': rows_transferred,
            'total_rows': total_rows,
        }
        return found

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

    @staticmethod
    def _update_keys_for(kind):
        """Physical Update keys for ``kind`` (ct-xu1o).

        Upsert tables and ``capture`` keep ``['id']``; other append-only tables
        prepend their deterministic input-derived instant column so ``docspec-rs``
        point pruning skips older Parquet files while logical key checks stay on
        ``id``.
        """
        if TABLE_MUTATIONS.get(KIND_TABLES.get(kind)) == 'append':
            return list(APPEND_UPDATE_KEYS.get(kind, ('id',)))
        return ['id']

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
            self._update_keys_for(kind),
            records_to_arrow(kind, ()),
            relationship=relationship,
        )

    def _commit_append(self, dataset, kind, records, relationship):
        records = self._dedup_incoming(dataset, records, is_append=True)
        prior = self.committed.get(dataset) or self.client.try_latest(dataset)
        if prior is None:
            operation = self._operation(f'admit-{kind}', content_digest(records))
            pin = self.client.run_table(
                records_to_arrow(kind, records), dataset, operation, relationship=relationship
            )
            self._known_ids.setdefault(dataset, set()).update(r['id'] for r in records)
            return pin
        existing = self._existing_for_append(prior, kind, records)
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
        if self._maybe_compact_table(dataset, prior, incoming_files=1) is not None:
            self._pending_lifecycle_compactions.add(dataset)
        base_version = prior['dataset']['version']
        operation = self._operation(
            f'append-{kind}', content_digest([base_version, new_records, relationship])
        )
        pin = self.client.update_table(
            dataset,
            operation,
            base_version,
            self._update_keys_for(kind),
            records_to_arrow(kind, new_records),
            relationship=relationship,
        )
        self._known_ids.setdefault(dataset, set()).update(r['id'] for r in new_records)
        return pin

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
        if self._maybe_compact_table(dataset, prior, incoming_files=1) is not None:
            self._pending_lifecycle_compactions.add(dataset)
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
            write_atomic_bytes(
                manifest_path,
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
                ).encode('utf-8'),
                temp_mode='fixed',
                fsync=False,
            )
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

    def abandon_cycle(self, control, cycle_id, *, epoch=None, faults=None):
        """Policy rollback of one failed publication cycle on ``DocSpecLake`` (I2/I3/I4).

        Restores each content dataset that drifted from the latest available
        release manifest (``releases/<id>.json`` ``dataset_pins``) via a
        base-bound ``update_table`` (0 replacement rows when no baseline rows
        were mutated; baseline row replacements plus dirty-key deletions when
        the failed cycle mutated or added rows), or explicitly refuses with
        ``CommitError('no_available_baseline', ...)`` if a dirtied dataset has
        no pinned baseline. Never deletes retained native generations; discards
        staged checkpoints for ``cycle_id`` and marks the cycle ``abandoned``.
        """
        if epoch is None:
            epoch = control.claim('docspec-news-writer')
        control.require_epoch(epoch)
        row = control.cycle(cycle_id)
        if row is None:
            raise CommitError('unknown_cycle', f'no journal entry for cycle {cycle_id}')
        if row['state'] == 'abandoned':
            return  # idempotent no-op
        if row['state'] in ('released', 'done'):
            raise CommitError('cycle_released', f'cycle {cycle_id} is {row["state"]} and cannot be abandoned')
        if self.find_release(cycle_id) is not None:
            raise CommitError(
                'cycle_release_appended',
                f'cycle {cycle_id} already appended its release record; run recover() instead',
            )

        baseline_release_id = control.latest_available_release()
        if baseline_release_id is None:
            if self._has_any_release_manifest():
                raise CommitError(
                    'no_available_baseline',
                    'release records exist but none is available; refusing to wipe the warehouse to empty',
                )
            baseline_pins_by_table = {}
        else:
            manifest_path = self._release_manifest_path(baseline_release_id)
            if not manifest_path.is_file():
                raise CommitError(
                    'no_available_baseline',
                    f'latest available release {baseline_release_id} manifest is missing at {manifest_path}',
                )
            try:
                manifest = json.loads(manifest_path.read_text())
            except (OSError, ValueError) as exc:
                raise CommitError(
                    'no_available_baseline',
                    f'latest available release {baseline_release_id} manifest is unreadable: {exc}',
                ) from exc
            dataset_pins = manifest.get('dataset_pins') if isinstance(manifest.get('dataset_pins'), dict) else {}
            table_pins = manifest.get('table_pins') if isinstance(manifest.get('table_pins'), dict) else {}
            has_dataset_pins_key = isinstance(manifest.get('dataset_pins'), dict)
            baseline_pins_by_table = {}
            for table_name in CONTENT_TABLES:
                dataset = dataset_id_for(table_name)
                pin = dataset_pins.get(dataset) or dataset_pins.get(table_name)
                if pin is None and not has_dataset_pins_key:
                    pin = table_pins.get(table_name) or table_pins.get(dataset)
                if pin is not None:
                    baseline_pins_by_table[table_name] = pin

        work_plan = []
        for table_name in CONTENT_TABLES:
            dataset = dataset_id_for(table_name)
            kind = TABLE_KINDS[table_name]
            current_pin = self.client.try_latest(dataset) or self.committed.get(dataset)
            baseline_pin = baseline_pins_by_table.get(table_name)
            if current_pin is None and baseline_pin is None:
                continue
            if baseline_pin is None:
                raise CommitError(
                    'no_available_baseline',
                    f'cannot abandon cycle {cycle_id}: dataset {dataset} ({table_name}) '
                    f'has no pinned baseline ReleasePin in the latest available release manifest',
                )
            if current_pin is None:
                raise CommitError(
                    'no_available_baseline',
                    f'cannot abandon cycle {cycle_id}: dataset {dataset} ({table_name}) '
                    f'is missing from workspace but pinned in release {baseline_release_id}',
                )
            work_plan.append((table_name, dataset, kind, current_pin, baseline_pin))

        control.discard_staged_checkpoints(cycle_id, epoch=epoch)

        new_committed = dict(self.committed)
        mutated = []
        for table_name, dataset, kind, current_pin, baseline_pin in work_plan:
            control.require_epoch(epoch)
            current_version = current_pin['dataset']['version']
            baseline_version = baseline_pin['dataset']['version']
            if current_version == baseline_version:
                new_committed[dataset] = baseline_pin
                self._known_ids.pop(dataset, None)
                continue
            current_source = current_pin.get('dataset', {}).get('groups', {}).get('source', {})
            baseline_source = baseline_pin.get('dataset', {}).get('groups', {}).get('source', {})
            current_parquet = [
                (o.get('path'), o.get('digest'), o.get('bytes'))
                for o in (current_source.get('objects') or ())
                if str(o.get('path', '')).endswith('.parquet')
            ]
            baseline_parquet = [
                (o.get('path'), o.get('digest'), o.get('bytes'))
                for o in (baseline_source.get('objects') or ())
                if str(o.get('path', '')).endswith('.parquet')
            ]
            current_rel = current_pin.get('dataset', {}).get('relationship')
            relationship = baseline_pin.get('dataset', {}).get('relationship')
            same_data = (
                current_parquet == baseline_parquet
                and current_source.get('rows', 0) == baseline_source.get('rows', 0)
            )
            if same_data and current_rel == relationship:
                new_committed[dataset] = current_pin
                self._known_ids.pop(dataset, None)
                continue
            schema = kind_arrow_schema(kind)
            keys = self._update_keys_for(kind)
            if same_data:
                to_restore = []
                deleted_rows = []
                replacements_table = records_to_arrow(kind, ())
                deletions_table = None
            else:
                baseline_rows = table_records(self.client.read_arrow(baseline_pin, schema=schema))
                current_rows = table_records(self.client.read_arrow(current_pin, schema=schema))
                baseline_by_id = {r['id']: r for r in baseline_rows}
                current_by_id = {r['id']: r for r in current_rows}
                to_restore = [rec for rid, rec in baseline_by_id.items() if current_by_id.get(rid) != rec]
                deleted_rows = [rec for rid, rec in current_by_id.items() if rid not in baseline_by_id]
                replacements_table = records_to_arrow(kind, to_restore)
                if deleted_rows:
                    del_schema = pa.schema([schema.field(col) for col in keys])
                    deletions_table = pa.Table.from_pylist(
                        [{col: r[col] for col in keys} for r in deleted_rows],
                        schema=del_schema,
                    )
                else:
                    deletions_table = None
            operation = self._operation(
                f'abandon-{kind}',
                content_digest([
                    cycle_id,
                    current_version,
                    baseline_version,
                    to_restore,
                    [r['id'] for r in deleted_rows],
                    relationship,
                ]),
            )
            restored_pin = self.client.update_table(
                dataset,
                operation,
                current_version,
                keys,
                replacements_table,
                deletions=deletions_table,
                relationship=relationship,
            )
            new_committed[dataset] = restored_pin
            self._known_ids.pop(dataset, None)
            if self._record_dataset_mutation(dataset, current_pin, restored_pin):
                mutated.append(dataset)

        self.committed = new_committed
        self._save_committed_state()
        if mutated:
            self._maybe_compact_lifecycle(mutated)
        control.set_cycle_state(cycle_id, 'abandoned', epoch=epoch)

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
        all_entries = record['snapshots']
        for entry in all_entries:
            if 'snapshot_id' not in entry:
                continue
            table_name = entry['table']
            pin = table_pins.get(table_name)
            if pin is None:
                raise ReleaseError('missing_snapshot', f'{table_name} pin is missing', release_id=release_id)
            expected_uuid = self._table_uuid(table_name, pin=pin)
            if expected_uuid != entry['table_uuid']:
                raise ReleaseError('table_uuid_mismatch', f'{table_name} UUID differs from the release', release_id=release_id)
        entries = all_entries
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
            pin = table_pins[table_name]
            kind = TABLE_KINDS[table_name]
            result[table_name] = table_records(
                self.client.read_arrow(pin, schema=kind_arrow_schema(kind))
            )
        return {
            'release': record,
            'tables': result,
            'dataset_pins': dict(table_pins),
        }


def _compact_run_meta(run):
    return {
        'id': run['id'],
        'processor': run['processor'],
        'processor_version': run['processor_version'],
        'config_hash': run['config_hash'],
        'status': run['status'],
        'finished_at': run['finished_at'],
    }


def _is_run_eligible(run, pinned_triples):
    return (
        isinstance(run, dict)
        and run.get('status') == 'succeeded'
        and (run.get('processor'), run.get('processor_version'), run.get('config_hash')) in pinned_triples
    )


def _run_rank(run):
    return (parse_instant(run['finished_at']), run['id'])


def _select_version_assignments(runs_by_id, selections):
    pinned = {
        (s['processor'], s['processor_version'], s['config_hash'])
        for s in (selections or ())
    }
    best = {}
    for run in runs_by_id.values():
        if not _is_run_eligible(run, pinned):
            continue
        rank = _run_rank(run)
        for ref in run.get('inputs', ()):
            if ref.get('kind') != 'version':
                continue
            key = f"{run['processor']}:{ref['id']}"
            if key not in best or rank > best[key][0]:
                best[key] = (rank, run['id'])
    return {key: run_id for key, (_, run_id) in best.items()}


_DATASET_TO_TABLE = {dataset_id_for(t): t for t in CONTENT_TABLES}


class DocSpecNewsViews:
    """Materialize the relational bridges natively and run the C9 views on them.

    ``materialize`` admits ``entity_roots``, ``selected_mentions`` and
    ``survivor_items`` (``analysis.bridges``) as datasets and records their
    exact ``ReleasePin``s in ``self.pins``; ``update_bridges`` derives changed
    and removed bridge keys incrementally from pinned source dataset deltas and
    targeted ``read_keys`` lookups without full-corpus Python scans;
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
        self._compacted_pins = {}
        state = self._load_views_state()
        self.pins = dict(pins) if pins is not None else state['pins']
        self._bridge_versions = state['bridge_versions'] if pins is None else {}
        self._mutation_counts = state['mutation_counts'] if pins is None else {}
        self._source_pins = state['source_pins'] if pins is None else {}
        self._selections = state['selections'] if pins is None else []
        self._decisions = state['decisions'] if pins is None else {}
        self._decision_roots = state['decision_roots'] if pins is None else {}
        self._runs = state['runs'] if pins is None else {}
        if pins is not None:
            self._compacted_pins = {}
        self._pending_lifecycle_compactions = set()
        self.last_bridge_diff = {}
        self.lifecycle_compactions = []
        self.table_compactions = []

    def _views_state_path(self):
        suffix = f'-{self.workspace_suffix}' if self.workspace_suffix else ''
        return self.client.workspace / f'.news_lake_views{suffix}.json'

    def _committed_state_path(self):
        suffix = f'-{self.workspace_suffix}' if self.workspace_suffix else ''
        return self.client.workspace / f'.news_lake_committed{suffix}.json'

    def _load_views_state(self):
        empty = {
            'pins': {},
            'bridge_versions': {},
            'mutation_counts': {},
            'source_pins': {},
            'selections': [],
            'decisions': {},
            'decision_roots': {},
            'runs': {},
        }
        path = self._views_state_path()
        if not path.is_file():
            self._compacted_pins = {}
            return empty
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict):
                self._compacted_pins = {}
                return empty
            pins = dict(data.get('pins') or {})
            compacted_pins = {}
            raw_compacted = data.get('compacted_pins')
            if isinstance(raw_compacted, dict):
                for ds, entry in raw_compacted.items():
                    if not isinstance(entry, dict) or not isinstance(entry.get('replacement'), dict):
                        continue
                    pin = pins.get(ds)
                    selected_ver = (
                        (pin or {}).get('dataset', {}).get('version')
                        or (pin or {}).get('selected_version')
                    )
                    if selected_ver and entry.get('version') == selected_ver:
                        compacted_pins[str(ds)] = {
                            'version': selected_ver,
                            'replacement': entry['replacement'],
                        }
            self._compacted_pins = compacted_pins
            return {
                'pins': pins,
                'bridge_versions': dict(data.get('bridge_versions') or {}),
                'mutation_counts': {
                    str(k): int(v)
                    for k, v in (data.get('mutation_counts') or {}).items()
                    if isinstance(v, int) and not isinstance(v, bool)
                },
                'source_pins': dict(data.get('source_pins') or {}),
                'selections': list(data.get('selections') or ()),
                'decisions': dict(data.get('decisions') or {}),
                'decision_roots': dict(data.get('decision_roots') or {}),
                'runs': dict(data.get('runs') or {}),
            }
        except (OSError, ValueError):
            self._compacted_pins = {}
            return empty

    def _save_views_state(self):
        path = self._views_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        valid_compacted = {}
        for ds, entry in self._compacted_pins.items():
            if not isinstance(entry, dict) or not isinstance(entry.get('replacement'), dict):
                continue
            pin = self.pins.get(ds)
            selected_ver = (
                (pin or {}).get('dataset', {}).get('version')
                or (pin or {}).get('selected_version')
            )
            if selected_ver is None or entry.get('version') == selected_ver:
                valid_compacted[ds] = entry
        self._compacted_pins = valid_compacted
        write_atomic_bytes(
            path,
            json.dumps(
                {
                    'pins': self.pins,
                    'bridge_versions': self._bridge_versions,
                    'mutation_counts': self._mutation_counts,
                    'source_pins': self._source_pins,
                    'selections': self._selections,
                    'decisions': self._decisions,
                    'decision_roots': self._decision_roots,
                    'runs': self._runs,
                    'compacted_pins': self._compacted_pins,
                },
                ensure_ascii=False,
                separators=(',', ':'),
                allow_nan=False,
                default=str,
            ).encode('utf-8'),
            temp_mode='fixed',
            fsync=False,
        )

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

    def _record_view_mutation(self, dataset, *, is_bridge=False):
        self._mutation_counts[dataset] = self._mutation_counts.get(dataset, 0) + 1
        interval = self.lifecycle_compact_interval
        if not is_bridge and interval and interval >= 1 and (
            self._mutation_counts[dataset] >= interval
        ):
            self.compact_lifecycle([dataset])

    def _flush_pending_bridge_compactions(self, datasets):
        interval = self.lifecycle_compact_interval
        if not interval or interval < 1:
            for ds in datasets:
                self._pending_lifecycle_compactions.discard(ds)
            return {}
        due = [ds for ds in datasets if ds in self._pending_lifecycle_compactions]
        for ds in due:
            self._pending_lifecycle_compactions.discard(ds)
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
        resolved = sanitize_id(dataset)
        target_pin = pin or self.pins.get(resolved) or self.client.try_latest(resolved)
        if target_pin is None:
            return []
        table_pin = self._effective_source_table_pin(resolved, target_pin)
        return _table_pin_parquet_objects(table_pin)

    def compact_table(self, dataset, *, pin=None, target_file_bytes=None,
                      compact_file_threshold=None, force=True):
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
        if compact_file_threshold is not None or not force:
            threshold = (
                self.compact_file_threshold
                if compact_file_threshold is None
                else compact_file_threshold
            )
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
            self._save_views_state()
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

    def compact_tables(self, datasets=None, *, target_file_bytes=None,
                       compact_file_threshold=None, force=True):
        """Run native table compaction across pinned (or specified) bridge/view datasets."""
        targets = list(self.pins if datasets is None else datasets)
        results = {}
        for dataset in targets:
            resolved = sanitize_id(dataset)
            report = self.compact_table(
                resolved,
                target_file_bytes=target_file_bytes,
                compact_file_threshold=compact_file_threshold,
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

    @staticmethod
    def _extract_release_meta(records_or_release_read, selections=None):
        if isinstance(records_or_release_read, dict) and 'release' in records_or_release_read:
            release = records_or_release_read['release']
            if selections is None:
                selections = release.get('selections', ())
            return list(selections), release.get('id')
        return list(() if selections is None else selections), None

    def _resolve_source_pins(self, records_or_release_read=None):
        """Return ``{table_name: ReleasePin}`` from release_read or committed lake state."""
        raw_pins = None
        if isinstance(records_or_release_read, dict) and isinstance(records_or_release_read.get('dataset_pins'), dict):
            raw_pins = records_or_release_read['dataset_pins']
        if not raw_pins:
            cpath = self._committed_state_path()
            if cpath.is_file():
                try:
                    loaded = json.loads(cpath.read_text())
                    if isinstance(loaded, dict):
                        raw_pins = loaded
                except (OSError, ValueError):
                    raw_pins = None
        if not raw_pins:
            return {}
        resolved = {}
        for key, pin in raw_pins.items():
            if not isinstance(pin, dict):
                continue
            table_name = key if key in TABLE_KINDS else _DATASET_TO_TABLE.get(key)
            if table_name is not None:
                resolved[table_name] = pin
        return resolved

    @staticmethod
    def _summarize_source_pins(source_pins):
        summary = {}
        for table_name, pin in (source_pins or {}).items():
            source_group = pin.get('dataset', {}).get('groups', {}).get('source', {})
            objects = [
                obj.get('path') for obj in (source_group.get('objects') or ())
                if isinstance(obj, dict) and isinstance(obj.get('path'), str)
            ]
            summary[table_name] = {
                'version': pin.get('dataset', {}).get('version'),
                'rows': source_group.get('rows', 0),
                'objects': objects,
            }
        return summary

    def _read_table_delta(self, table_name, new_pin, prior_info):
        """Fetch only the changed/added records for ``table_name`` since ``prior_info`` via ``/changes``."""
        if new_pin is None:
            return []
        source_group = new_pin.get('dataset', {}).get('groups', {}).get('source', {})
        new_version = new_pin.get('dataset', {}).get('version')
        new_rows = source_group.get('rows', 0)
        new_objects = [
            obj.get('path') for obj in (source_group.get('objects') or ())
            if isinstance(obj, dict) and isinstance(obj.get('path'), str)
        ]
        if new_rows == 0:
            return []
        prior_version = (prior_info or {}).get('version')
        prior_rows = (prior_info or {}).get('rows', 0)
        prior_objects = (prior_info or {}).get('objects') or []
        if prior_version is not None and (
            new_version == prior_version
            or (new_objects == prior_objects and new_rows == prior_rows)
        ):
            return []

        dataset = dataset_id_for(table_name)
        kind = TABLE_KINDS[table_name]
        schema = kind_arrow_schema(kind)
        if prior_version is None or prior_rows == 0:
            return table_records(self.client.read_arrow(new_pin, schema=schema))
        try:
            prior_pin = self.client.release(dataset, prior_version)
            with self.client.changes_batches(
                prior_pin,
                new_pin,
                group='source',
                identity='occurrences',
                force_full=False,
            ) as (descriptor, reader):
                if isinstance(descriptor, dict) and descriptor.get('path') in ('forward_changes', 'unchanged'):
                    batches = list(reader)
                    change_table = pa.Table.from_batches(batches, schema=reader.schema)
                else:
                    change_table = None
            if change_table is not None:
                if change_table.num_rows == 0:
                    return []
                after_table = change_table.filter(pc.equal(change_table['side'], 'after'))
                if after_table.num_rows == 0:
                    return []
                values_col = after_table['values'].combine_chunks()
                unpacked = pa.Table.from_batches([pa.RecordBatch.from_struct_array(values_col)])
                restored = restore_application_schema(unpacked, expected_schema=schema)
                by_id = {}
                for row in table_records(restored):
                    by_id[row['id']] = row
                return list(by_id.values())
        except DocSpecFailure:
            pass

        # Fallback if prior_version is unavailable or not forward_changes: read newly added Parquet objects
        added_paths = [
            p for p in new_objects
            if p.endswith('.parquet') and p not in set(prior_objects)
        ]
        if added_paths and all(Path(p).is_file() for p in added_paths):
            tables = [
                restore_application_schema(pq.read_table(p), expected_schema=schema)
                for p in added_paths
            ]
            by_id = {}
            for tbl in tables:
                for row in table_records(tbl):
                    by_id[row['id']] = row
            return list(by_id.values())
        return table_records(self.client.read_arrow(new_pin, schema=schema))

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

    def _init_incremental_state(self, records, selections, source_pins):
        self._source_pins = self._summarize_source_pins(source_pins)
        self._selections = [dict(s) for s in (selections or ())]
        self._decisions = {
            r['id']: r for r in records if r.get('kind') == 'identity_decision'
        }
        decision_eids = set()
        for dec in self._decisions.values():
            for field in ('left_id', 'right_id'):
                if field in dec:
                    decision_eids.add(dec[field])
        if self._decisions:
            decision_result = apply_decisions(records)
            roots = decision_result.get('roots', {})
            self._decision_roots = {eid: roots.get(eid, eid) for eid in sorted(decision_eids)}
        else:
            self._decision_roots = {}
        self._runs = {
            r['id']: _compact_run_meta(r)
            for r in records
            if r.get('kind') == 'run'
            and r.get('processor') != 'extract'
            and r.get('status') == 'succeeded'
        }

    def materialize(self, records_or_release_read, selections=None):
        """Admit the three bridge datasets; stores and returns ``{dataset: ReleasePin}``."""
        source_pins = self._resolve_source_pins(records_or_release_read)
        if (
            isinstance(records_or_release_read, dict)
            and 'tables' in records_or_release_read
            and not records_or_release_read['tables']
            and source_pins
        ):
            selections, _ = self._extract_release_meta(records_or_release_read, selections)
            records = []
            for table_name, pin in source_pins.items():
                kind = TABLE_KINDS[table_name]
                records.extend(
                    table_records(self.client.read_arrow(pin, schema=kind_arrow_schema(kind)))
                )
        else:
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
            self._bridge_versions[dataset] = pin['dataset']['version']
            self._compacted_pins.pop(dataset, None)
        self.pins.update(pins)
        self._init_incremental_state(records, selections, source_pins)
        self._save_views_state()
        return dict(pins)

    def _apply_bridge_delta(self, dataset, key_col, schema, prior_pin,
                            candidate_rows, removed_keys, prior_by_key, rows_recomputed):
        prior_version = prior_pin['dataset']['version']
        changed_rows = [
            row for row in candidate_rows
            if str_canonical(prior_by_key.get(row[key_col])) != str_canonical(_strip_nulls(row))
        ]
        removed_keys = sorted(k for k in set(removed_keys) if k in prior_by_key)
        stats = {
            'rows_recomputed': rows_recomputed,
            'changed_rows': len(changed_rows),
            'removed_keys': len(removed_keys),
            'full_table_reads': 0,
            'updated': bool(changed_rows or removed_keys),
        }
        if not changed_rows and not removed_keys:
            self.pins[dataset] = prior_pin
            self._bridge_versions[dataset] = prior_version
            return prior_pin, stats
        compacted = self._maybe_compact_table(
            dataset,
            prior_pin,
            incoming_files=1 if changed_rows else 0,
        )
        interval = self.lifecycle_compact_interval
        if interval and interval >= 1 and (
            compacted is not None
            or self._mutation_counts.get(dataset, 0) + 1 >= interval
        ):
            self.compact_lifecycle([dataset])
            self._pending_lifecycle_compactions.add(dataset)
        replacements_table = pa.Table.from_pylist(changed_rows, schema=schema)
        deletions_table = (
            pa.Table.from_pylist(
                [{key_col: key} for key in removed_keys],
                schema=pa.schema([schema.field(key_col)]),
            )
            if removed_keys
            else None
        )
        operation = self._operation(
            f'update-{dataset}',
            content_digest([prior_version, _strip_nulls(changed_rows), removed_keys]),
        )
        pin = self.client.update_table(
            dataset,
            operation,
            prior_version,
            [key_col],
            replacements_table,
            deletions=deletions_table,
        )
        self.pins[dataset] = pin
        self._bridge_versions[dataset] = pin['dataset']['version']
        self._compacted_pins.pop(dataset, None)
        self._record_view_mutation(dataset, is_bridge=True)
        return pin, stats

    def _update_entity_roots_incremental(self, prior_pin, source_pins, delta_entities, delta_decisions):
        if not delta_entities and not delta_decisions:
            return self._apply_bridge_delta(
                'entity_roots', 'entity_id', bridges.ENTITY_ROOTS_SCHEMA,
                prior_pin, [], [], {}, 0
            )
        entities_pin = source_pins.get('news.entities')
        delta_entities_by_id = {r['id']: r for r in delta_entities}
        for dec in delta_decisions:
            self._decisions[dec['id']] = dec

        decision_eids = set()
        for dec in self._decisions.values():
            for field in ('left_id', 'right_id'):
                if field in dec:
                    decision_eids.add(dec[field])

        new_decision_roots = dict(self._decision_roots)
        if self._decisions and (delta_decisions or (decision_eids & set(delta_entities_by_id))):
            missing_dec_eids = sorted(decision_eids - set(delta_entities_by_id))
            dec_entities = dict(delta_entities_by_id)
            if missing_dec_eids and entities_pin is not None:
                fetched = table_records(
                    self.client.read_keys(
                        entities_pin, 'id', missing_dec_eids, schema=kind_arrow_schema('entity')
                    )
                )
                for ent in fetched:
                    dec_entities[ent['id']] = ent
            decision_result = apply_decisions(
                list(dec_entities.values()) + list(self._decisions.values())
            )
            roots_map = decision_result.get('roots', {})
            new_decision_roots = {eid: roots_map.get(eid, eid) for eid in sorted(decision_eids)}

        affected_eids = set(delta_entities_by_id)
        for eid in set(self._decision_roots) | set(new_decision_roots):
            if self._decision_roots.get(eid, eid) != new_decision_roots.get(eid, eid):
                affected_eids.add(eid)
        for eid, root_id in new_decision_roots.items():
            if root_id in delta_entities_by_id:
                affected_eids.add(eid)
        self._decision_roots = new_decision_roots

        needed_entity_ids = set(affected_eids) | {
            self._decision_roots.get(eid, eid) for eid in affected_eids
        }
        entity_map = dict(delta_entities_by_id)
        missing_entity_ids = sorted(needed_entity_ids - set(entity_map))
        if missing_entity_ids and entities_pin is not None:
            fetched = table_records(
                self.client.read_keys(
                    entities_pin, 'id', missing_entity_ids, schema=kind_arrow_schema('entity')
                )
            )
            for ent in fetched:
                entity_map[ent['id']] = ent

        prior_by_key = {}
        if affected_eids:
            prior_rows = table_records(
                self.client.read_keys(
                    prior_pin, 'entity_id', sorted(affected_eids),
                    schema=bridges.ENTITY_ROOTS_SCHEMA,
                )
            )
            prior_by_key = {row['entity_id']: _strip_nulls(row) for row in prior_rows}

        candidate_rows = []
        for eid in sorted(affected_eids):
            entity = entity_map.get(eid)
            if entity is None:
                continue
            root_id = self._decision_roots.get(eid, eid)
            root_entity = entity_map.get(root_id, entity)
            candidate_rows.append({
                'entity_id': eid,
                'person_root_id': root_id,
                'entity_type': root_entity.get('entity_type', entity['entity_type']),
                'name': root_entity.get('name', entity['name']),
            })
        return self._apply_bridge_delta(
            'entity_roots', 'entity_id', bridges.ENTITY_ROOTS_SCHEMA,
            prior_pin, candidate_rows, [], prior_by_key, len(candidate_rows)
        )

    def _update_selected_mentions_incremental(
        self, prior_pin, source_pins, delta_mentions, reassigned_mention_versions,
        pinned_processors, is_winning_run
    ):
        if not delta_mentions and not reassigned_mention_versions:
            return self._apply_bridge_delta(
                'selected_mentions', 'mention_id', bridges.SELECTED_MENTIONS_SCHEMA,
                prior_pin, [], [], {}, 0
            )
        mentions_pin = source_pins.get('news.mentions')
        candidate_mentions = {m['id']: m for m in delta_mentions}
        prior_by_key = {}
        removed_keys = set()

        if reassigned_mention_versions:
            prior_ver_rows = table_records(
                self.client.read_keys(
                    prior_pin, 'version_id', sorted(reassigned_mention_versions),
                    schema=bridges.SELECTED_MENTIONS_SCHEMA,
                )
            )
            for row in prior_ver_rows:
                prior_by_key[row['mention_id']] = _strip_nulls(row)
                removed_keys.add(row['mention_id'])
            if mentions_pin is not None:
                source_ver_mentions = table_records(
                    self.client.read_keys(
                        mentions_pin, 'version_id', sorted(reassigned_mention_versions),
                        schema=kind_arrow_schema('mention'),
                    )
                )
                for m in source_ver_mentions:
                    candidate_mentions[m['id']] = m

        lookup_mids = sorted(set(candidate_mentions) - set(prior_by_key))
        if lookup_mids:
            existing_rows = table_records(
                self.client.read_keys(
                    prior_pin, 'mention_id', lookup_mids,
                    schema=bridges.SELECTED_MENTIONS_SCHEMA,
                )
            )
            for row in existing_rows:
                prior_by_key[row['mention_id']] = _strip_nulls(row)

        candidate_rows = []
        for mid in sorted(candidate_mentions):
            record = candidate_mentions[mid]
            if record.get('resolution') != 'resolved' or record.get('entity_id') is None:
                continue
            run = self._runs.get(record['run_id'])
            if run is None or run['processor'] not in pinned_processors:
                continue
            if not is_winning_run(run['processor'], record['version_id'], record['run_id']):
                continue
            removed_keys.discard(mid)
            candidate_rows.append({
                'mention_id': mid,
                'version_id': record['version_id'],
                'run_id': record['run_id'],
                'entity_id': record['entity_id'],
                'surface': record['surface'],
                'aboutness': record['aboutness'],
                'occurrences': [
                    {'field': span['field'], 'start': span['start'], 'end': span['end']}
                    for span in record['occurrences']
                ],
            })
        return self._apply_bridge_delta(
            'selected_mentions', 'mention_id', bridges.SELECTED_MENTIONS_SCHEMA,
            prior_pin, candidate_rows, removed_keys, prior_by_key, len(candidate_mentions)
        )

    def _update_survivor_items_incremental(
        self, prior_pin, source_pins, delta_items, delta_versions,
        delta_discoveries, delta_story_members, reassigned_cluster_versions,
        pinned_processors, is_winning_run
    ):
        if (
            not delta_items
            and not delta_versions
            and not delta_discoveries
            and not delta_story_members
            and not reassigned_cluster_versions
        ):
            return self._apply_bridge_delta(
                'survivor_items', 'item_id', bridges.SURVIVOR_ITEMS_SCHEMA,
                prior_pin, [], [], {}, 0
            )
        items_pin = source_pins.get('news.items')
        versions_pin = source_pins.get('news.versions')
        discoveries_pin = source_pins.get('news.discoveries')
        story_members_pin = source_pins.get('news.story_members')

        directly_affected_item_ids = (
            {r['id'] for r in delta_items}
            | {r['item_id'] for r in delta_versions}
            | {r['item_id'] for r in delta_discoveries}
        )
        story_affected_vids = (
            {r['version_id'] for r in delta_story_members}
            | set(reassigned_cluster_versions)
        )
        prior_by_key = {}
        if story_affected_vids:
            ver_survivors = table_records(
                self.client.read_keys(
                    prior_pin, 'current_version_id', sorted(story_affected_vids),
                    schema=bridges.SURVIVOR_ITEMS_SCHEMA,
                )
            )
            for row in ver_survivors:
                directly_affected_item_ids.add(row['item_id'])
                prior_by_key[row['item_id']] = _strip_nulls(row)

        missing_prior_iids = sorted(directly_affected_item_ids - set(prior_by_key))
        if missing_prior_iids:
            fetched_prior = table_records(
                self.client.read_keys(
                    prior_pin, 'item_id', missing_prior_iids,
                    schema=bridges.SURVIVOR_ITEMS_SCHEMA,
                )
            )
            for row in fetched_prior:
                prior_by_key[row['item_id']] = _strip_nulls(row)

        items_by_id = {
            r['id']: r for r in delta_items if r['id'] in directly_affected_item_ids
        }
        missing_item_ids = sorted(directly_affected_item_ids - set(items_by_id))
        if missing_item_ids and items_pin is not None:
            fetched_items = table_records(
                self.client.read_keys(
                    items_pin, 'id', missing_item_ids, schema=kind_arrow_schema('item')
                )
            )
            for item in fetched_items:
                items_by_id[item['id']] = item

        removed_keys = set()
        active_survivors = []
        for iid in sorted(directly_affected_item_ids):
            item = items_by_id.get(iid)
            if item is None or item.get('superseded_by'):
                if iid in prior_by_key:
                    removed_keys.add(iid)
                continue
            active_survivors.append(item)

        needed_vids = {
            item['current_version_id']
            for item in active_survivors
            if item.get('current_version_id') is not None
        }
        versions_by_id = {
            r['id']: r for r in delta_versions if r['id'] in needed_vids
        }
        missing_vids = sorted(needed_vids - set(versions_by_id))
        if missing_vids and versions_pin is not None:
            fetched_versions = table_records(
                self.client.read_keys(
                    versions_pin, 'id', missing_vids, schema=kind_arrow_schema('version')
                )
            )
            for ver in fetched_versions:
                versions_by_id[ver['id']] = ver

        items_needing_discoveries = []
        for item in active_survivors:
            vid = item.get('current_version_id')
            ver = versions_by_id.get(vid) if vid is not None else None
            if ver is None or _publication_date(ver.get('publication')) is None:
                items_needing_discoveries.append(item['id'])
        discoveries_by_item = {}
        if items_needing_discoveries:
            if discoveries_pin is not None:
                fetched_disc = table_records(
                    self.client.read_keys(
                        discoveries_pin, 'item_id', sorted(items_needing_discoveries),
                        schema=kind_arrow_schema('discovery'),
                    )
                )
                for d in fetched_disc:
                    discoveries_by_item.setdefault(d['item_id'], []).append(d)
            else:
                for d in delta_discoveries:
                    discoveries_by_item.setdefault(d['item_id'], []).append(d)

        story_by_version = {}
        vids_needing_story_lookup = set()
        for item in active_survivors:
            vid = item.get('current_version_id')
            if vid is None:
                continue
            prior_row = prior_by_key.get(item['id'])
            if (
                prior_row is not None
                and prior_row.get('current_version_id') == vid
                and vid not in story_affected_vids
            ):
                if 'story_id' in prior_row:
                    story_by_version[vid] = prior_row['story_id']
            else:
                vids_needing_story_lookup.add(vid)

        if vids_needing_story_lookup:
            story_members = []
            if story_members_pin is not None:
                story_members = table_records(
                    self.client.read_keys(
                        story_members_pin, 'version_id', sorted(vids_needing_story_lookup),
                        schema=kind_arrow_schema('story_member'),
                    )
                )
            else:
                story_members = [
                    m for m in delta_story_members if m['version_id'] in vids_needing_story_lookup
                ]
            for record in story_members:
                run = self._runs.get(record['run_id'])
                if run is None or run['processor'] not in pinned_processors:
                    continue
                if is_winning_run(run['processor'], record['version_id'], record['run_id']):
                    story_by_version.setdefault(record['version_id'], record['story_id'])

        candidate_by_id = {}
        for item in active_survivors:
            iid = item['id']
            vid = item.get('current_version_id')
            ver = versions_by_id.get(vid) if vid is not None else None
            pub_date_str = _publication_date(ver.get('publication')) if ver is not None else None
            if pub_date_str is None:
                discovery_dates = {
                    d
                    for discovery in discoveries_by_item.get(iid, ())
                    if (d := _publication_date(discovery.get('reported_publication'))) is not None
                }
                if len(discovery_dates) == 1:
                    pub_date_str = discovery_dates.pop()
            effective_pub_date = date.fromisoformat(pub_date_str) if pub_date_str is not None else None
            story_id = story_by_version.get(ver['id']) if ver is not None else None
            text_group_id = (
                text_group_key(ver['text'])
                if (ver is not None and isinstance(ver.get('text'), str))
                else None
            )
            candidate_by_id[iid] = {
                'item_id': iid,
                'outlet_id': item.get('outlet_id'),
                'current_version_id': ver['id'] if ver is not None else None,
                'effective_pub_date': effective_pub_date,
                'story_id': story_id,
                'text_group_id': text_group_id,
                'identical_text_group_id': None,
            }

        # Resolve cross-date syndication for all affected text_group_ids via read_keys
        affected_text_groups = {
            row['text_group_id']
            for row in candidate_by_id.values()
            if row.get('text_group_id') is not None
        } | {
            row['text_group_id']
            for row in prior_by_key.values()
            if row.get('text_group_id') is not None
        }
        untouched_peers_by_id = {}
        if affected_text_groups:
            peer_rows = table_records(
                self.client.read_keys(
                    prior_pin, 'text_group_id', sorted(affected_text_groups),
                    schema=bridges.SURVIVOR_ITEMS_SCHEMA,
                )
            )
            for peer in peer_rows:
                pid = peer['item_id']
                if pid not in prior_by_key:
                    prior_by_key[pid] = _strip_nulls(peer)
                if pid not in directly_affected_item_ids:
                    untouched_peers_by_id[pid] = {
                        'item_id': pid,
                        'outlet_id': peer.get('outlet_id'),
                        'current_version_id': peer.get('current_version_id'),
                        'effective_pub_date': peer.get('effective_pub_date'),
                        'story_id': peer.get('story_id'),
                        'text_group_id': peer.get('text_group_id'),
                        'identical_text_group_id': peer.get('identical_text_group_id'),
                    }

            group_counts = {}
            for row in list(candidate_by_id.values()) + list(untouched_peers_by_id.values()):
                tg = row.get('text_group_id')
                if tg is not None:
                    group_counts[tg] = group_counts.get(tg, 0) + 1

            for row in candidate_by_id.values():
                tg = row.get('text_group_id')
                row['identical_text_group_id'] = (
                    tg if (tg is not None and group_counts.get(tg, 0) > 1) else None
                )
            for pid, peer_row in untouched_peers_by_id.items():
                tg = peer_row.get('text_group_id')
                new_identical = tg if (tg is not None and group_counts.get(tg, 0) > 1) else None
                if peer_row.get('identical_text_group_id') != new_identical:
                    peer_row['identical_text_group_id'] = new_identical
                    candidate_by_id[pid] = peer_row

        candidate_rows = [candidate_by_id[iid] for iid in sorted(candidate_by_id)]
        rows_recomputed = len(active_survivors) + len(
            [pid for pid in untouched_peers_by_id if pid in candidate_by_id]
        )
        return self._apply_bridge_delta(
            'survivor_items', 'item_id', bridges.SURVIVOR_ITEMS_SCHEMA,
            prior_pin, candidate_rows, removed_keys, prior_by_key, rows_recomputed
        )

    def update_bridges(self, records_or_release_read, selections=None):
        """Derive incremental bridge updates from pinned release deltas and ``read_keys``."""
        prior_pins = {
            dataset: (self.pins.get(dataset) or self.client.try_latest(dataset))
            for dataset in ('entity_roots', 'selected_mentions', 'survivor_items')
        }
        if any(pin is None for pin in prior_pins.values()):
            pins = self.materialize(records_or_release_read, selections=selections)
            self.last_bridge_diff = {
                ds: {
                    'rows_recomputed': pin.get('dataset', {}).get('groups', {}).get('source', {}).get('rows', 0),
                    'changed_rows': pin.get('dataset', {}).get('groups', {}).get('source', {}).get('rows', 0),
                    'removed_keys': 0,
                    'full_table_reads': 0,
                    'updated': True,
                }
                for ds, pin in pins.items()
            }
            return pins

        source_pins = self._resolve_source_pins(records_or_release_read)
        selections_list, _ = self._extract_release_meta(records_or_release_read, selections)

        bridge_source_tables = (
            'news.entities',
            'news.identity_decisions',
            'news.runs',
            'news.mentions',
            'news.items',
            'news.versions',
            'news.discoveries',
            'news.story_members',
        )
        delta_tables = {
            table_name: self._read_table_delta(
                table_name,
                source_pins.get(table_name),
                self._source_pins.get(table_name),
            )
            for table_name in bridge_source_tables
        }
        if not isinstance(records_or_release_read, dict):
            raw_records, _, _ = self._unwrap(records_or_release_read, selections)
            for table_name in bridge_source_tables:
                if not delta_tables[table_name]:
                    kind = TABLE_KINDS[table_name]
                    delta_tables[table_name] = [
                        r for r in raw_records if isinstance(r, dict) and r.get('kind') == kind
                    ]

        prior_runs = dict(self._runs)
        delta_runs = delta_tables['news.runs']
        for run in delta_runs:
            if run.get('processor') != 'extract' and run.get('status') == 'succeeded':
                self._runs[run['id']] = _compact_run_meta(run)

        normalized_selections = [dict(s) for s in selections_list]
        pinned_triples = {
            (s['processor'], s['processor_version'], s['config_hash'])
            for s in normalized_selections
        }
        pinned_processors = {s['processor'] for s in normalized_selections}
        delta_version_ids = {r['id'] for r in delta_tables['news.versions']}

        max_prior_rank_by_proc = {}
        for r in prior_runs.values():
            if _is_run_eligible(r, pinned_triples):
                proc = r['processor']
                rank = _run_rank(r)
                if proc not in max_prior_rank_by_proc or rank > max_prior_rank_by_proc[proc]:
                    max_prior_rank_by_proc[proc] = rank

        max_eligible_rank_by_proc = dict(max_prior_rank_by_proc)
        eligible_delta_runs = []
        has_backdated_delta_run = False
        for run in delta_runs:
            if not _is_run_eligible(run, pinned_triples):
                continue
            eligible_delta_runs.append(run)
            proc = run['processor']
            rank = _run_rank(run)
            if proc in max_prior_rank_by_proc and rank < max_prior_rank_by_proc[proc]:
                has_backdated_delta_run = True
            if proc not in max_eligible_rank_by_proc or rank > max_eligible_rank_by_proc[proc]:
                max_eligible_rank_by_proc[proc] = rank

        reassigned_mention_versions = set()
        reassigned_cluster_versions = set()
        delta_selected_runs = {}
        full_selected_runs = [None]

        def _load_full_selected_runs():
            if full_selected_runs[0] is not None:
                return full_selected_runs[0]
            runs_pin = source_pins.get('news.runs')
            if runs_pin is not None:
                all_runs = {
                    r['id']: r
                    for r in table_records(
                        self.client.read_arrow(runs_pin, schema=kind_arrow_schema('run'))
                    )
                    if r.get('processor') != 'extract' and r.get('status') == 'succeeded'
                }
            else:
                all_runs = {r['id']: r for r in delta_runs if r.get('processor') != 'extract'}
            full_selected_runs[0] = _select_version_assignments(all_runs, normalized_selections)
            return full_selected_runs[0]

        if normalized_selections != self._selections or has_backdated_delta_run:
            runs_pin = source_pins.get('news.runs')
            if runs_pin is not None:
                all_runs = {
                    r['id']: r
                    for r in table_records(
                        self.client.read_arrow(runs_pin, schema=kind_arrow_schema('run'))
                    )
                    if r.get('processor') != 'extract' and r.get('status') == 'succeeded'
                }
            else:
                all_runs = {r['id']: r for r in delta_runs if r.get('processor') != 'extract'}
            old_selected = _select_version_assignments(
                {rid: all_runs[rid] for rid in prior_runs if rid in all_runs},
                self._selections,
            )
            new_selected = _select_version_assignments(all_runs, normalized_selections)
            full_selected_runs[0] = new_selected
            for slot_key in set(old_selected) | set(new_selected):
                old_run = old_selected.get(slot_key)
                new_run = new_selected.get(slot_key)
                if old_run != new_run:
                    proc, vid = slot_key.split(':', 1)
                    if proc == 'mentions' and (old_run is not None or vid not in delta_version_ids):
                        reassigned_mention_versions.add(vid)
                    elif proc == 'cluster':
                        reassigned_cluster_versions.add(vid)
        else:
            for run in sorted(eligible_delta_runs, key=_run_rank):
                proc = run['processor']
                for ref in run.get('inputs', ()):
                    if not isinstance(ref, dict) or ref.get('kind') != 'version':
                        continue
                    vid = ref['id']
                    delta_selected_runs[f"{proc}:{vid}"] = run['id']
                    if vid not in delta_version_ids:
                        if proc == 'mentions':
                            reassigned_mention_versions.add(vid)
                        elif proc == 'cluster':
                            reassigned_cluster_versions.add(vid)

        def is_winning_run(processor, version_id, run_id):
            run = self._runs.get(run_id)
            if not _is_run_eligible(run, pinned_triples):
                return False
            if full_selected_runs[0] is not None:
                return full_selected_runs[0].get(f"{processor}:{version_id}") == run_id
            slot_key = f"{processor}:{version_id}"
            if slot_key in delta_selected_runs:
                return delta_selected_runs[slot_key] == run_id
            if _run_rank(run) == max_eligible_rank_by_proc.get(processor):
                return True
            return _load_full_selected_runs().get(slot_key) == run_id

        self._selections = normalized_selections

        updated_pins = {}
        diff_summary = {}

        roots_pin, roots_stats = self._update_entity_roots_incremental(
            prior_pins['entity_roots'],
            source_pins,
            delta_tables['news.entities'],
            delta_tables['news.identity_decisions'],
        )
        updated_pins['entity_roots'] = roots_pin
        diff_summary['entity_roots'] = roots_stats

        mentions_pin, mentions_stats = self._update_selected_mentions_incremental(
            prior_pins['selected_mentions'],
            source_pins,
            delta_tables['news.mentions'],
            reassigned_mention_versions,
            pinned_processors,
            is_winning_run,
        )
        updated_pins['selected_mentions'] = mentions_pin
        diff_summary['selected_mentions'] = mentions_stats

        survivor_pin, survivor_stats = self._update_survivor_items_incremental(
            prior_pins['survivor_items'],
            source_pins,
            delta_tables['news.items'],
            delta_tables['news.versions'],
            delta_tables['news.discoveries'],
            delta_tables['news.story_members'],
            reassigned_cluster_versions,
            pinned_processors,
            is_winning_run,
        )
        updated_pins['survivor_items'] = survivor_pin
        diff_summary['survivor_items'] = survivor_stats

        if source_pins:
            self._source_pins = self._summarize_source_pins(source_pins)
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
        _, release_id = self._extract_release_meta(records_or_release_read, selections)
        source_pins = self._resolve_source_pins(records_or_release_read)
        versions_pin = source_pins.get('news.versions')
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
        self._flush_pending_bridge_compactions(('selected_mentions', 'entity_roots'))
        self._record_view_mutation('politician_articles')
        self._save_views_state()
        join_cols = [
            'entity_id', 'mention_id', 'version_id', 'run_id',
            'surface', 'aboutness', 'occurrences', 'person_root_id', 'entity_type',
        ]
        joined = list(self.client.iter_records(pin, columns=join_cols))
        return self._assemble_politician_articles(
            records_or_release_read,
            release_id,
            joined,
            survivor_pin=survivor_pin,
            versions_pin=versions_pin,
        )

    def _assemble_politician_articles(self, records_or_release_read, release_id, joined, *,
                                      survivor_pin=None, versions_pin=None):
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
        grouped_version_ids = sorted({entry['version_id'] for entry in grouped.values()})
        if not grouped_version_ids:
            versions = {}
        elif versions_pin is not None:
            ver_rows = table_records(
                self.client.read_keys(
                    versions_pin,
                    'id',
                    grouped_version_ids,
                    columns=['id', 'title', 'text'],
                    schema=kind_arrow_schema('version'),
                )
            )
            versions = {row['id']: row for row in ver_rows}
        else:
            records, _, _ = self._unwrap(records_or_release_read)
            versions = _by_kind(records, 'version')
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
        _, release_id = self._extract_release_meta(records_or_release_read, selections)
        base = self._base_version('coverage_daily', mode)
        survivor_pin = self._bridge_pin_for_refresh(
            'survivor_items', 'coverage_daily', mode
        )
        spec = self._refresh_aggregate_spec(base, mode, survivor_pin=survivor_pin)
        pin = self.client.refresh(spec)
        self.pins['coverage_daily'] = pin
        self._flush_pending_bridge_compactions(('survivor_items',))
        self._record_view_mutation('coverage_daily')
        self._save_views_state()
        cov_cols = [
            'effective_pub_date', 'items', 'outlets', 'stories', 'identical_text_group_ids',
        ]
        aggregate = list(self.client.iter_records(pin, columns=cov_cols))
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
    'APPEND_UPDATE_KEYS',
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
