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

Deliberate representation choices (documented deviations):

- ``selected_mentions.occurrences`` is stored as a JSON string column rather
  than a native list<struct> so the join projection stays flat scalar fields
  (the native reader exposes join position columns and the flat form keeps
  the join simple); ``politician_articles`` parses it back to spans.
- ``coverage_daily.identical_text_group_ids`` is computed in Python from the
  ``survivor_items`` dataset: the native aggregate has scalar functions only
  (no collect-set-style distinct-value listing yet).
- Record datasets keep the contract's JSON value space (instants/dates stay
  canonical strings), so a native readback converts back to records losslessly
  by dropping absent-optional nulls.
"""
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

import pyarrow as pa
import pyarrow.parquet as pq

from news_lake.analysis import bridges
from news_lake.analysis.views import _by_kind, _merge_spans
from news_lake.context import canonicalize_record_instants
from news_lake.contract.records import (
    KIND_ORDER,
    KIND_TABLES,
    SCHEMA,
    TABLE_MUTATIONS,
    validate_shape,
)
from news_lake.identity.decisions import apply_decisions  # noqa: F401  (bridge input)
from news_lake.storage.coordinator import _merge_upsert

DEFAULT_BINARY = '/Users/mikewolfd/Work/spicy-stack/docspec-rs/target/debug/docspec'
# One recipe identity for every news dataset; the schema is derived from the
# contract and never changes inside a workspace without a new definition.
DEFINITION = 'news-v1'
_SERVE_LOG = '.news_lake_serve.log'


class DocSpecFailure(RuntimeError):
    """The native engine refused or failed; its original diagnostic is retained."""

    def __init__(self, command, returncode, stderr):
        self.command = tuple(command)
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(stderr.strip() or f'DocSpec exited {returncode}')


def native_storage_schema(schema):
    """Lossless native storage types for unsigned values and binary offsets.

    Copied from ``congress_api.retention.docspec``: UInt64 becomes
    Decimal128(20, 0) and Binary becomes LargeBinary to match the native
    nested writer; composites recurse. The application retains its original
    schema and casts readbacks back with Arrow's checked cast.
    """
    def field(value):
        return value.with_type(data_type(value.type))

    def data_type(value):
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

    return pa.schema([field(value) for value in schema], metadata=schema.metadata)


def application_schema(schema):
    """Inverse of :func:`native_storage_schema` for checked readback casts."""
    def field(value):
        return value.with_type(data_type(value.type))

    def data_type(value):
        if pa.types.is_decimal(value):
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


def content_digest(records):
    """A stable digest over record values, for replay-stable operation ids."""
    payload = json.dumps(records, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False, allow_nan=False, default=str)
    return sha256(payload.encode('utf-8')).hexdigest()


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


class DocSpecClient:
    """One engine interface over the one-shot CLI and the loopback HTTP host.

    CLI calls spawn the binary per request with a scratch directory under the
    workspace. ``serve()`` starts ``docspec serve`` bound to loopback and
    routes the same operations over HTTP until the context exits; hashing
    stays a CLI call in both transports because the engine exposes it as a
    workspace-independent reader.
    """

    def __init__(self, workspace, binary=None, *, timeout=120):
        if binary is None:
            binary = os.environ.get('DOCSPEC_BINARY') or shutil.which('docspec') or DEFAULT_BINARY
        self.binary = str(Path(binary).resolve())
        self.workspace = Path(workspace).resolve()
        self.timeout = timeout
        self._port = None

    @classmethod
    def default_binary_path(cls):
        """The last-resort prebuilt engine binary used when nothing else is configured."""
        return DEFAULT_BINARY

    # -- transports ----------------------------------------------------------

    def _base_command(self):
        self.workspace.mkdir(parents=True, exist_ok=True)
        return [self.binary, '--workspace', str(self.workspace)]

    def _call(self, *args):
        result = subprocess.run(self._base_command() + [str(arg) for arg in args],
                                capture_output=True, text=True, timeout=self.timeout)
        if result.returncode:
            raise DocSpecFailure(args, result.returncode, result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else None

    @contextmanager
    def _scratch(self):
        self.workspace.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='request-', dir=self.workspace) as directory:
            yield Path(directory)

    def _http(self, method, path, json_body=None, stream_to=None):
        """One loopback HTTP call; JSON in/out, or Arrow streamed to a file."""
        data = None
        headers = {}
        if json_body is not None:
            data = json.dumps(json_body, ensure_ascii=False, separators=(',', ':'),
                              allow_nan=False, default=str).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(
            f'http://127.0.0.1:{self._port}{path}', data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                if stream_to is not None:
                    with open(stream_to, 'wb') as sink:
                        while True:
                            chunk = response.read(1 << 20)
                            if not chunk:
                                break
                            sink.write(chunk)
                    return None
                body = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode('utf-8', 'replace')
            try:
                message = json.loads(detail).get('message', detail)
            except json.JSONDecodeError:
                message = detail
            raise DocSpecFailure((method, path), error.code, message) from None
        return json.loads(body) if body.strip() else None

    def _dispatch(self, command, request, http_method, http_path):
        if self._port is not None:
            return self._http(http_method, http_path, json_body=request)
        return self._request(command, request)

    def _request(self, command, request):
        with self._scratch() as directory:
            path = directory / 'request.json'
            path.write_text(json.dumps(request, ensure_ascii=False, separators=(',', ':'),
                                       allow_nan=False, default=str))
            return self._call(command, path)

    @contextmanager
    def serve(self, port=0, host='127.0.0.1', wait_seconds=60):
        """Run the persistent loopback host; this client uses HTTP inside the block.

        The engine owns a workspace exclusively per process, so CLI callers
        must stay idle while the host runs (hashing is workspace-independent
        and remains available). A port of 0 picks a free loopback port.
        """
        if self._port is not None:
            raise RuntimeError('serve() is already active for this client')
        self._call('init')  # idempotent; the host needs an initialized host state
        if port == 0:
            probe = socket.socket()
            try:
                probe.bind((host, 0))
                port = probe.getsockname()[1]
            finally:
                probe.close()
        self.workspace.mkdir(parents=True, exist_ok=True)
        log_path = self.workspace / _SERVE_LOG
        with log_path.open('wb') as log:
            process = subprocess.Popen(self._base_command() + ['serve', '--bind', f'{host}:{port}'],
                                       stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + wait_seconds
                while True:
                    if process.poll() is not None:
                        log.flush()
                        tail = log_path.read_text(errors='replace')[-2000:]
                        raise DocSpecFailure(('serve', host, port), process.returncode, tail)
                    try:
                        with socket.create_connection((host, port), timeout=0.25):
                            break
                    except OSError:
                        if time.monotonic() > deadline:
                            process.terminate()
                            process.wait(timeout=self.timeout)
                            raise TimeoutError(f'docspec serve did not accept on {host}:{port}')
                        time.sleep(0.05)
                self._port = port
                yield self
            finally:
                self._port = None
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=15)
        try:
            log_path.unlink()
        except FileNotFoundError:
            pass

    # -- operations ----------------------------------------------------------

    def hash_input(self, path):
        """Hash a local producer file (workspace-independent in both transports)."""
        return self._call('hash', Path(path).resolve())

    def run(self, spec):
        """Submit one ``RunSpec``; returns the selected ``ReleasePin``."""
        return self._dispatch('run', spec, 'POST', '/run')

    def update(self, spec):
        """Submit one ``UpdateSpec``; returns the selected ``ReleasePin``."""
        return self._dispatch('update', spec, 'POST', '/updates/run')

    def refresh(self, spec):
        """Submit one ``RefreshSpec`` (join or aggregate); returns the ``ReleasePin``."""
        return self._dispatch('refresh', spec, 'POST', '/refreshes/run')

    def seal_generation(self, spec):
        """Seal one ``GenerationSeal``; an identical retry returns the original."""
        return self._dispatch('seal-generation', spec, 'POST', '/generations/seal')

    def export(self, spec):
        """Submit one ``ExportSpec``; returns the ``ExportPin``."""
        return self._dispatch('export', spec, 'POST', '/exports/run')

    def compact(self, spec):
        """Submit one ``CompactionSpec``; returns the ``CompactionResult``."""
        return self._dispatch('compact', spec, 'POST', '/compactions/run')

    def latest(self, dataset):
        """The selected ``ReleasePin`` of a dataset; raises when absent."""
        if self._port is not None:
            return self._http('GET', f'/datasets/{dataset}/latest')
        return self._call('latest', dataset)

    def try_latest(self, dataset):
        """The selected ``ReleasePin``, or ``None`` when nothing is selected."""
        try:
            return self.latest(dataset)
        except DocSpecFailure as error:
            if 'no_release' in error.stderr:
                return None
            raise

    def release(self, dataset, version):
        """Resolve one exact historical ``ReleasePin`` by version id."""
        if self._port is not None:
            return self._http('GET', f'/datasets/{dataset}/versions/{version}')
        return self._call('release', dataset, version)

    def read_arrow(self, release_pin, group='source'):
        """Stream one retained group as Arrow (CLI file or HTTP stream) into a Table."""
        with self._scratch() as directory:
            output = directory / 'group.arrow'
            if self._port is not None:
                dataset = release_pin['dataset']['dataset']
                version = release_pin['dataset']['version']
                self._http('GET', f'/datasets/{dataset}/versions/{version}/arrow/{group}',
                           stream_to=output)
            else:
                pin = directory / 'release.json'
                pin.write_text(json.dumps(release_pin, ensure_ascii=False,
                                          separators=(',', ':'), allow_nan=False, default=str))
                if output.exists():
                    output.unlink()
                self._call('read', pin, output, '--group', group)
            with output.open('rb') as stream:
                with pa.ipc.open_stream(stream) as reader:
                    return reader.read_all()

    def _stage(self, directory, name, table):
        """Write one zstd Parquet producer file and its trusted digest."""
        source = directory / name
        physical = native_storage_schema(table.schema)
        stored = table if physical.equals(table.schema, check_metadata=True) else table.cast(physical, safe=True)
        pq.write_table(stored, source, compression='zstd')
        return source, self.hash_input(source)['digest']

    def run_table(self, table, dataset, operation, definition=DEFINITION, relationship=None):
        """Admit one caller-bounded Arrow table as a dataset build.

        The caller owns candidate identity, schema and completeness; the input
        path is a locator and the retained expected digest selects the bytes.
        """
        with self._scratch() as directory:
            source, digest = self._stage(directory, 'source.parquet', table)
            spec = dict(dataset=dataset, operation=operation, input=str(source),
                        expected_digest=digest, sql='SELECT * FROM input',
                        definition=definition)
            if relationship is not None:
                spec['relationship'] = relationship
            return self.run(spec)

    def update_table(self, dataset, operation, base, keys, replacements_table,
                     deletions=None, definition=DEFINITION):
        """Replace/insert complete rows by key against the exact selected base."""
        with self._scratch() as directory:
            source, digest = self._stage(directory, 'replacements.parquet', replacements_table)
            spec = dict(dataset=dataset, operation=operation, definition=definition,
                        base=base, keys=list(keys),
                        replacements={'path': str(source), 'digest': digest})
            if deletions is not None:
                deletion_path, deletion_digest = self._stage(directory, 'deletions.parquet',
                                                             deletions)
                spec['deletions'] = {'path': str(deletion_path), 'digest': deletion_digest}
            return self.update(spec)


class DocSpecLake:
    """Route news_lake records into native datasets, one per contract table.

    Upsert tables (outlets/items/entities) merge each incoming poll against
    the stored row for its id so earlier evidence survives (C1), then submit
    the merged rows as a complete-key update. Append tables admit each batch
    as its own build whose operation id derives from the batch content, so a
    replayed identical batch returns the original release. Every record is
    validated against the contract before submission.
    """

    def __init__(self, client, workspace_suffix=''):
        self.client = client
        self.workspace_suffix = sanitize_id(workspace_suffix) if workspace_suffix else ''
        self.committed = {}

    def _dataset(self, kind_or_table):
        return dataset_id_for(KIND_TABLES.get(kind_or_table, kind_or_table))

    def _operation(self, label, digest):
        name = f'{label}-{digest[:16]}'
        if self.workspace_suffix:
            name = f'{name}-{self.workspace_suffix}'
        return sanitize_id(name)

    def commit_records(self, records, generation=None, family='news'):
        """Validate and commit one batch; returns ``{dataset: latest ReleasePin}``.

        Records route by ``kind`` exactly as the contract's ``x-iceberg``
        annotations do for Iceberg: upsert datasets merge by ``id`` before an
        update, append datasets admit the batch as one build. With a
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
        for kind in KIND_ORDER:
            records_of_kind = batch.get(kind)
            if not records_of_kind:
                continue
            dataset = self._dataset(kind)
            if TABLE_MUTATIONS[KIND_TABLES[kind]] == 'upsert':
                pins[dataset] = self._commit_upsert(dataset, kind, records_of_kind, relationship)
            else:
                pins[dataset] = self._commit_append(dataset, kind, records_of_kind, relationship)
        self.committed = pins
        return dict(pins)

    def _commit_append(self, dataset, kind, records, relationship):
        operation = self._operation(f'admit-{kind}', content_digest(records))
        self.client.run_table(records_to_arrow(kind, records), dataset, operation,
                              relationship=relationship)
        return self.client.latest(dataset)

    def _commit_upsert(self, dataset, kind, records, relationship):
        pin = self.client.try_latest(dataset)
        if pin is None:
            return self._commit_append(dataset, kind, records, relationship)
        existing = {record['id']: record
                    for record in table_records(self.client.read_arrow(pin))}
        replacements = []
        for record in records:
            prior = existing.get(record['id'])
            if prior is None:
                replacements.append(record)
                continue
            if prior == record:
                continue  # replayed identical row: no-op in both backends
            merged = _merge_upsert(prior, record)
            validate_shape(merged)
            if merged != prior:
                replacements.append(merged)
        if replacements:
            operation = self._operation(f'upsert-{kind}', content_digest(replacements))
            self.client.update_table(dataset, operation, pin['dataset']['version'], ['id'],
                                     records_to_arrow(kind, replacements))
        return self.client.latest(dataset)

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
        return self.client.read_arrow(self.client.latest(dataset))


class DocSpecNewsViews:
    """Materialize the relational bridges natively and run the C9 views on them.

    ``materialize`` admits ``entity_roots``, ``selected_mentions`` and
    ``survivor_items`` (``analysis.bridges``) as datasets;
    ``politician_articles`` refreshes a native join of the first two and
    assembles the Python row shape; ``coverage_daily`` refreshes a native
    Date32-keyed aggregate over ``survivor_items`` (the undated bucket is the
    NULL key group) and adds the identical-text group ids in Python.
    """

    #: ``occurrences`` rides as a JSON string column (see module docstring).
    SELECTED_MENTIONS_SCHEMA = pa.schema([
        pa.field('mention_id', pa.string(), nullable=False),
        pa.field('version_id', pa.string(), nullable=False),
        pa.field('run_id', pa.string(), nullable=False),
        pa.field('entity_id', pa.string(), nullable=False),
        pa.field('surface', pa.string(), nullable=False),
        pa.field('aboutness', pa.string(), nullable=False),
        pa.field('occurrences', pa.string(), nullable=False),
    ])

    def __init__(self, client, workspace_suffix=''):
        self.client = client
        self.workspace_suffix = sanitize_id(workspace_suffix) if workspace_suffix else ''

    # -- materialization -----------------------------------------------------

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

    def _selected_mentions_table(self, rows):
        serialized = [dict(row, occurrences=json.dumps(
            row['occurrences'], ensure_ascii=False, separators=(',', ':')))
            for row in rows]
        return pa.Table.from_pylist(serialized, schema=self.SELECTED_MENTIONS_SCHEMA)

    def materialize(self, records_or_release_read, selections=None):
        """Admit the three bridge datasets; returns ``{dataset: ReleasePin}``."""
        records, selections, _ = self._unwrap(records_or_release_read, selections)
        tables = {
            'entity_roots': bridges.entity_roots_arrow(records),
            'selected_mentions': self._selected_mentions_table(
                bridges.selected_mentions_rows(records, selections)),
            'survivor_items': bridges.survivor_items_arrow(records, selections),
        }
        pins = {}
        for dataset, table in tables.items():
            operation = self._operation(f'materialize-{dataset}',
                                        content_digest(table_records(table)))
            pins[dataset] = self.client.run_table(table, dataset, operation)
        return pins

    # -- native refreshes ----------------------------------------------------

    def _base_version(self, dataset, mode):
        if mode == 'full':
            return None
        pin = self.client.try_latest(dataset)
        if pin is None:
            raise ValueError(f"mode='incremental' requires a previous {dataset} version")
        return pin['dataset']['version']

    def _refresh_join_spec(self, base, mode):
        return dict(
            dataset='politician_articles', base=base, definition=DEFINITION, mode=mode,
            operation=self._operation(
                f'pa-{mode}',
                content_digest([base, mode, self.client.latest('selected_mentions'),
                                self.client.latest('entity_roots')])),
            transform={'kind': 'join',
                       'left': version_ref(self.client.latest('selected_mentions')),
                       'right': version_ref(self.client.latest('entity_roots')),
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
        ``entity_roots`` rows affect (requires a previous output version).
        Rows are assembled in Python from the joined output, the survivor
        items dataset and the release's versions, matching
        ``analysis.views.politician_articles`` field for field.
        """
        records, _, release_id = self._unwrap(records_or_release_read)
        base = self._base_version('politician_articles', mode)
        spec = self._refresh_join_spec(base, mode)
        pin = self.client.refresh(spec)
        joined = table_records(self.client.read_arrow(pin))
        return self._assemble_politician_articles(records, release_id, joined)

    def _assemble_politician_articles(self, records, release_id, joined):
        versions = _by_kind(list(records), 'version')
        survivor_rows = table_records(
            self.client.read_arrow(self.client.latest('survivor_items')))
        item_of_version = {row['current_version_id']: row['item_id']
                           for row in survivor_rows}
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
                for span in json.loads(row['occurrences']))
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

    def _refresh_aggregate_spec(self, base, mode):
        return dict(
            dataset='coverage_daily', base=base, definition=DEFINITION, mode=mode,
            operation=self._operation(
                f'cov-{mode}',
                content_digest([base, mode, self.client.latest('survivor_items')])),
            transform={'kind': 'aggregate',
                       'input': version_ref(self.client.latest('survivor_items')),
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
                                    ]}},
        )

    def coverage_daily(self, records_or_release_read, mode='full', selections=None):
        """The ``coverage_daily`` view through the native aggregate.

        The grouping key is the ``survivor_items`` ``effective_pub_date``
        Date32 column; NULL keys form exactly one undated group. The native
        ``rows`` count is computed but not emitted (the Python view has no
        such field). ``identical_text_group_ids`` is computed Python-side from
        the survivor items dataset because the aggregate has no collect-set.
        """
        records, _, release_id = self._unwrap(records_or_release_read)
        base = self._base_version('coverage_daily', mode)
        spec = self._refresh_aggregate_spec(base, mode)
        pin = self.client.refresh(spec)
        aggregate = table_records(self.client.read_arrow(pin))
        return self._assemble_coverage_daily(records, release_id, aggregate)

    def _assemble_coverage_daily(self, records, release_id, aggregate):
        survivor_rows = table_records(
            self.client.read_arrow(self.client.latest('survivor_items')))
        corpus_groups, bucket_groups = {}, {}
        for row in survivor_rows:
            key = row.get('text_group_id')
            if key is None:
                continue
            corpus_groups.setdefault(key, set()).add(row['item_id'])
            day = row.get('effective_pub_date')
            bucket_groups.setdefault(day.isoformat() if day is not None else None,
                                     set()).add(key)
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
            groups = bucket_groups.get(bucket_date, set())
            rows.append({
                'release_id': release_id,
                'date': bucket_date,
                'undated': bucket_date is None,
                'items': row['items'],
                'outlets': row['outlets'],
                'stories': row['stories'],
                # Visibility for syndication, never an independent-reporting
                # count (C9): text groups that repeat across the corpus.
                'identical_text_group_ids': sorted(
                    key for key in groups if len(corpus_groups[key]) > 1),
            })
        return rows


__all__ = [
    'DEFINITION',
    'DEFAULT_BINARY',
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
    'sanitize_id',
    'table_records',
    'version_ref',
]
