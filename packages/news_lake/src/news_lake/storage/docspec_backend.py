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
import io
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
import time
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
from news_lake.identity.decisions import apply_decisions  # noqa: F401  (bridge input)
from news_lake.storage.coordinator import CommitError, _merge_upsert

DEFAULT_BINARY = '/Users/mikewolfd/Work/spicy-stack/docspec-rs/target/debug/docspec'
# One recipe identity for every news dataset; the schema is derived from the
# contract and never changes inside a workspace without a new definition.
DEFINITION = 'news-v1'
_SERVE_LOG = '.news_lake_serve.log'
_INDETERMINATE_CODES = frozenset({
    'worker',
    'custody_quarantined',
    'timeout',
    'host_unavailable',
    'request_timeout',
    'injected_failure',
})
_ARROW_STREAM_EOS = b'\xff\xff\xff\xff\x00\x00\x00\x00'


class AppendCollisionError(CommitError, ValueError):
    """Conflicting ID reuse on an append-only dataset (both CommitError and ValueError)."""


class DocSpecFailure(RuntimeError):
    """The native engine refused or failed; its original diagnostic is retained."""

    def __init__(self, command, returncode, stderr, *, status_code=None, code=None):
        self.command = tuple(command)
        self.returncode = returncode
        self.stderr = stderr
        self.status_code = status_code
        self.retained_input = None
        if code is None and isinstance(stderr, str):
            code = self._parse_code(stderr)
        self.code = code
        super().__init__(stderr.strip() or f'DocSpec exited {returncode}')

    @staticmethod
    def _parse_code(stderr):
        text = stderr.strip()
        if not text:
            return None
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get('code'), str) and payload['code']:
            return payload['code']
        for line in text.splitlines():
            match = re.match(r'^(?:Error:\s*)?([a-z][a-z0-9_]*):\s', line.strip())
            if match:
                return match.group(1)
        return None

    @property
    def status(self):
        return self.status_code

    @status.setter
    def status(self, value):
        self.status_code = value


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


def _merge_field_type(physical_type, expected_type):
    """Validate and resolve a physical Arrow type against an expected application type."""
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


class _ArrowHttpStream(io.RawIOBase):
    """Expose an HTTP body as a bounded blocking Arrow IPC stream without staging."""

    def __init__(self, response, *, deadline=None):
        super().__init__()
        self._response = response
        self._deadline = deadline
        self._tail = b''

    def _check_deadline(self):
        if self._deadline is not None and time.monotonic() >= self._deadline:
            raise TimeoutError('DocSpec response exceeded its wall-time limit')

    def readable(self):
        return True

    def readinto(self, target):
        view = memoryview(target)
        count = 0
        while count < len(view):
            self._check_deadline()
            chunk = self._response.read(min(1 << 20, len(view) - count))
            self._check_deadline()
            if not chunk:
                break
            length = len(chunk)
            view[count:count + length] = chunk
            self._tail = (self._tail + chunk)[-8:]
            count += length
        return count

    def verify_eos(self):
        """Require both Arrow's stream terminator and complete HTTP framing."""
        if self.read(1) or self._tail != _ARROW_STREAM_EOS:
            raise OSError('DocSpec Arrow response lacks a complete stream terminator')


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
        self._host = '127.0.0.1'
        self._dataset_schemas = {}

    @classmethod
    def default_binary_path(cls):
        """The last-resort prebuilt engine binary used when nothing else is configured."""
        return DEFAULT_BINARY

    # -- transports ----------------------------------------------------------

    def _base_command(self):
        self.workspace.mkdir(parents=True, exist_ok=True)
        return [self.binary, '--workspace', str(self.workspace)]

    def _call(self, *args, dispatch=None):
        command = self._base_command() + [str(arg) for arg in args]
        if dispatch is not None:
            dispatch['submitted'] = True
        result = subprocess.run(command, capture_output=True, text=True, timeout=self.timeout)
        if result.returncode:
            raise DocSpecFailure(args, result.returncode, result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else None

    @contextmanager
    def _scratch(self):
        self.workspace.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='request-', dir=self.workspace) as directory:
            yield Path(directory)

    def _deadline_headers(self, deadline=None):
        remaining = self.timeout if deadline is None else (deadline - time.monotonic())
        if remaining <= 0:
            raise TimeoutError('DocSpec response exceeded its wall-time limit')
        budget_ms = str(max(1, math.ceil(remaining * 1000)))
        return {
            'docspec-timeout-ms': budget_ms,
            'X-DocSpec-Deadline-Ms': budget_ms,
        }

    def _http(self, method, path, json_body=None, *, dispatch=None, deadline=None):
        """One loopback HTTP call returning decoded JSON."""
        data = None
        headers = self._deadline_headers(deadline=deadline)
        if json_body is not None:
            data = json.dumps(json_body, ensure_ascii=False, separators=(',', ':'),
                              allow_nan=False, default=str).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(
            f'http://{self._host}:{self._port}{path}', data=data, headers=headers, method=method)
        if dispatch is not None:
            dispatch['submitted'] = True
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode('utf-8', 'replace')
            code = None
            message = detail
            try:
                payload = json.loads(detail)
                if isinstance(payload, dict):
                    code = payload.get('code') if isinstance(payload.get('code'), str) else None
                    message = payload.get('message', detail)
            except json.JSONDecodeError:
                pass
            raise DocSpecFailure(
                (method, path), error.code, message, status_code=error.code, code=code
            ) from None
        return json.loads(body) if body.strip() else None

    def _dispatch(self, command, request, http_method, http_path, *, dispatch=None):
        if self._port is not None:
            return self._http(http_method, http_path, json_body=request, dispatch=dispatch)
        return self._request(command, request, dispatch=dispatch)

    def _request(self, command, request, *, dispatch=None):
        with self._scratch() as directory:
            path = directory / 'request.json'
            path.write_text(json.dumps(request, ensure_ascii=False, separators=(',', ':'),
                                       allow_nan=False, default=str))
            return self._call(command, path, dispatch=dispatch)

    @staticmethod
    def _validate_readiness(value, *, expected_pid=None):
        """Validate the native loopback readiness record (protocol v1)."""
        if not isinstance(value, dict):
            raise ValueError('DocSpec readiness record must be a JSON object')
        proto_ok = (
            (value.get('protocol') == 'docspec-loopback'
             and type(value.get('version')) is int
             and value['version'] == 1)
            or (type(value.get('protocol')) is int and value['protocol'] == 1)
        )
        capabilities = value.get('capabilities')
        if (not proto_ok
                or not isinstance(capabilities, list)
                or any(not isinstance(item, str) for item in capabilities)
                or not {'request-deadline', 'owned-stdin-eof'}.issubset(capabilities)):
            raise ValueError(
                'DocSpec loopback protocol 1 with request-deadline and owned-stdin-eof '
                'support is required'
            )
        if expected_pid is not None and 'pid' in value:
            if type(value['pid']) is not int or value['pid'] != expected_pid:
                raise ValueError('DocSpec readiness pid does not match the owned child process')
        address = value.get('address')
        if isinstance(address, str):
            parsed = urlsplit(f'http://{address}')
            if (parsed.username is not None or parsed.password is not None or parsed.path
                    or parsed.query or parsed.fragment or not parsed.port
                    or not ipaddress.ip_address(parsed.hostname).is_loopback):
                raise ValueError('DocSpec readiness requires an explicit bound loopback address')
            return parsed.hostname, parsed.port
        if type(value.get('port')) is int and value['port'] > 0:
            host = value.get('host', '127.0.0.1')
            if not ipaddress.ip_address(host).is_loopback:
                raise ValueError('DocSpec readiness requires a loopback host')
            return host, value['port']
        raise ValueError('DocSpec readiness requires an explicit bound loopback address')

    @contextmanager
    def serve(self, port=0, host='127.0.0.1', wait_seconds=60):
        """Run the persistent loopback host; this client uses HTTP inside the block.

        Uses the native readiness record (``--ready-file``) and owned-stdin EOF
        shutdown (``--shutdown-on-stdin-eof``) instead of free-port probing.
        """
        if self._port is not None:
            raise RuntimeError('serve() is already active for this client')
        self._call('init')  # idempotent; the host needs an initialized host state
        self.workspace.mkdir(parents=True, exist_ok=True)
        log_path = self.workspace / _SERVE_LOG
        with tempfile.TemporaryDirectory(prefix='docspec-host-') as ready_dir:
            os.chmod(ready_dir, 0o700)
            ready_path = Path(ready_dir) / 'ready.json'
            cmd = self._base_command() + [
                'serve',
                '--bind', f'{host}:{port}',
                '--ready-file', str(ready_path),
                '--shutdown-on-stdin-eof',
            ]
            with log_path.open('wb') as log:
                process = subprocess.Popen(
                    cmd, stdin=subprocess.PIPE, stdout=log, stderr=log
                )
                try:
                    deadline = time.monotonic() + wait_seconds
                    bound_host, bound_port = None, None
                    while True:
                        if process.poll() is not None:
                            log.flush()
                            tail = log_path.read_text(errors='replace')[-2000:]
                            raise DocSpecFailure(('serve', host, port), process.returncode, tail)
                        try:
                            mode = ready_path.lstat().st_mode
                            if not stat.S_ISREG(mode) or (mode & 0o077):
                                raise ValueError(
                                    'DocSpec readiness record must be a private regular file'
                                )
                            encoded = ready_path.read_bytes()
                            if len(encoded) > 4096:
                                raise ValueError(
                                    'DocSpec readiness record exceeds its metadata allowance'
                                )
                            record = json.loads(encoded)
                        except (FileNotFoundError, json.JSONDecodeError):
                            record = None
                        if record is not None:
                            bound_host, bound_port = self._validate_readiness(
                                record, expected_pid=process.pid
                            )
                            break
                        if time.monotonic() >= deadline:
                            if process.stdin is not None:
                                process.stdin.close()
                            process.terminate()
                            process.wait(timeout=self.timeout)
                            raise TimeoutError(f'docspec serve did not become ready on {host}:{port}')
                        time.sleep(0.01)
                    self._host = bound_host
                    self._port = bound_port
                    yield self
                finally:
                    self._port = None
                    self._host = '127.0.0.1'
                    if process.stdin is not None and not process.stdin.closed:
                        process.stdin.close()
                    if process.poll() is None:
                        try:
                            process.wait(timeout=min(self.timeout, 5))
                        except subprocess.TimeoutExpired:
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

    def run(self, spec, *, dispatch=None):
        """Submit one ``RunSpec``; returns the selected ``ReleasePin``."""
        return self._dispatch('run', spec, 'POST', '/run', dispatch=dispatch)

    def update(self, spec, *, dispatch=None):
        """Submit one ``UpdateSpec``; returns the selected ``ReleasePin``."""
        return self._dispatch('update', spec, 'POST', '/updates/run', dispatch=dispatch)

    def refresh(self, spec):
        """Submit one ``RefreshSpec`` (join or aggregate); returns the ``ReleasePin``."""
        return self._dispatch('refresh', spec, 'POST', '/refreshes/run')

    def seal_generation(self, spec):
        """Seal one ``GenerationSeal``; an identical retry returns the original."""
        return self._dispatch('seal-generation', spec, 'POST', '/generations/seal')

    def export(self, spec):
        """Submit one ``ExportSpec``; returns the ``ExportPin``."""
        return self._dispatch('export', spec, 'POST', '/exports/run')

    def latest_export(self, dataset, channel):
        """Resolve one export channel to its selected ``ExportPin``."""
        if self._port is not None:
            return self._http(
                'GET',
                f'/datasets/{quote(dataset, safe="")}/exports/channels/{quote(channel, safe="")}',
            )
        return self._call('latest-export', dataset, channel)

    def try_latest_export(self, dataset, channel):
        """The selected ``ExportPin`` on ``channel``, or ``None`` when absent."""
        try:
            return self.latest_export(dataset, channel)
        except DocSpecFailure as error:
            if error.code == 'no_export' or 'no_export' in error.stderr:
                return None
            raise

    def export_pin(self, dataset, operation):
        """Resolve one completed historical ``ExportPin`` by operation id."""
        if self._port is not None:
            return self._http(
                'GET',
                f'/datasets/{quote(dataset, safe="")}/exports/{quote(operation, safe="")}',
            )
        return self._call('export-pin', dataset, operation)

    def try_export_pin(self, dataset, operation):
        """Resolve one completed ``ExportPin`` by operation id, or ``None``."""
        try:
            return self.export_pin(dataset, operation)
        except DocSpecFailure as error:
            if error.code == 'no_export' or 'no_export' in error.stderr:
                return None
            raise

    def compact(self, spec):
        """Submit one ``CompactionSpec``; returns the ``CompactionResult``."""
        return self._dispatch('compact', spec, 'POST', '/compactions/run')

    def latest(self, dataset):
        """The selected ``ReleasePin`` of a dataset; raises when absent."""
        if self._port is not None:
            return self._http('GET', f'/datasets/{quote(dataset, safe="")}/latest')
        return self._call('latest', dataset)

    def try_latest(self, dataset):
        """The selected ``ReleasePin``, or ``None`` when nothing is selected."""
        try:
            return self.latest(dataset)
        except DocSpecFailure as error:
            if error.code == 'no_release' or 'no_release' in error.stderr:
                return None
            raise

    def release(self, dataset, version):
        """Resolve one exact historical ``ReleasePin`` by version id."""
        if self._port is not None:
            return self._http(
                'GET', f'/datasets/{quote(dataset, safe="")}/versions/{quote(version, safe="")}'
            )
        return self._call('release', dataset, version)

    def read_arrow(self, release_pin, group='source', *, schema=None):
        """Stream one retained group as Arrow (CLI file or HTTP stream) into a Table."""
        dataset = release_pin['dataset']['dataset']
        version = release_pin['dataset']['version']
        if schema is None and group == 'source':
            schema = self._dataset_schemas.get(dataset)
        if self._port is not None:
            deadline = time.monotonic() + self.timeout
            headers = self._deadline_headers(deadline=deadline)
            path = (
                f'/datasets/{quote(dataset, safe="")}'
                f'/versions/{quote(version, safe="")}/arrow/{quote(group, safe="")}'
            )
            request = urllib.request.Request(
                f'http://{self._host}:{self._port}{path}', headers=headers, method='GET'
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    expected_headers = {
                        'docspec-dataset': dataset,
                        'docspec-version': version,
                        'docspec-manifest-blake3': release_pin['manifest']['digest'],
                        'content-type': 'application/vnd.apache.arrow.stream',
                    }
                    for key, expected_val in expected_headers.items():
                        actual_val = response.headers.get(key)
                        if actual_val is not None and actual_val != expected_val:
                            raise ValueError('Native stream differs from the selected exact pin')
                    stream = _ArrowHttpStream(response, deadline=deadline)
                    with pa.ipc.open_stream(stream) as reader:
                        table = reader.read_all()
                        stream.verify_eos()
            except urllib.error.HTTPError as error:
                detail = error.read().decode('utf-8', 'replace')
                code = None
                message = detail
                try:
                    payload = json.loads(detail)
                    if isinstance(payload, dict):
                        code = payload.get('code') if isinstance(payload.get('code'), str) else None
                        message = payload.get('message', detail)
                except json.JSONDecodeError:
                    pass
                raise DocSpecFailure(
                    ('GET', path), error.code, message, status_code=error.code, code=code
                ) from None
        else:
            with self._scratch() as directory:
                output = directory / 'group.arrow'
                pin = directory / 'release.json'
                pin.write_text(json.dumps(release_pin, ensure_ascii=False,
                                          separators=(',', ':'), allow_nan=False, default=str))
                if output.exists():
                    output.unlink()
                self._call('read', pin, output, '--group', group)
                with output.open('rb') as stream:
                    with pa.ipc.open_stream(stream) as reader:
                        table = reader.read_all()
        if schema is not None:
            return restore_application_schema(table, expected_schema=schema)
        return table

    def _stage(self, directory, name, table):
        """Write one zstd Parquet producer file and its trusted digest."""
        source = directory / name
        physical = native_storage_schema(table.schema)
        stored = (
            table
            if physical.equals(table.schema, check_metadata=True)
            else table.cast(physical, safe=True)
        )
        pq.write_table(stored, source, compression='zstd')
        return source, self.hash_input(source)['digest']

    def _request_directory(self, operation):
        directory = self.workspace / 'requests' / f'request-{sanitize_id(operation)}'
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    @staticmethod
    def _is_cleanup_safe(error):
        if not isinstance(error, DocSpecFailure):
            return False
        if not error.code or error.code in _INDETERMINATE_CODES:
            return False
        if error.status is not None:
            return 400 <= error.status < 500
        return True

    def _submit_with_custody(self, directory, source, spec, submit_fn):
        """Persist ``request.json`` before submitting; retain producer input on unknown outcome."""
        request_path = directory / 'request.json'
        request_path.write_text(
            json.dumps(spec, ensure_ascii=False, separators=(',', ':'), allow_nan=False, default=str)
        )
        dispatch = {}
        retained = False
        try:
            return submit_fn(spec, dispatch)
        except BaseException as error:
            if dispatch.get('submitted') and not self._is_cleanup_safe(error):
                retained = True
                try:
                    size = source.stat().st_size
                    retained_info = {
                        'input': str(source),
                        'request': str(request_path),
                        'bytes': size,
                    }
                    if isinstance(error, DocSpecFailure):
                        error.retained_input = retained_info
                    if hasattr(error, 'add_note'):
                        error.add_note(
                            f'DocSpec producer input retained: {source} ({size} bytes); '
                            f'exact replay request: {request_path}'
                        )
                except OSError:
                    pass
            raise
        finally:
            if not retained:
                shutil.rmtree(directory, ignore_errors=True)

    def retained_producer_inputs(self):
        """Inspect unresolved local producer files without inferring native completion."""
        inputs = []
        seen = set()
        for pattern in ('requests/request-*/request.json', 'request-*/request.json'):
            for request_path in sorted(self.workspace.glob(pattern)):
                resolved = request_path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                source = request_path.parent / 'source.parquet'
                try:
                    size = source.stat().st_size
                except FileNotFoundError:
                    size = None
                inputs.append({
                    'input': str(source),
                    'request': str(request_path),
                    'bytes': size,
                })
        return inputs

    def run_table(self, table, dataset, operation, definition=DEFINITION,
                  relationship=None, base=None):
        """Admit one caller-bounded Arrow table as a dataset build.

        The caller owns candidate identity, schema and completeness; the input
        path is a locator and the retained expected digest selects the bytes.
        """
        self._dataset_schemas[dataset] = table.schema
        directory = self._request_directory(operation)
        source, digest = self._stage(directory, 'source.parquet', table)
        spec = dict(dataset=dataset, operation=operation, input=str(source),
                    expected_digest=digest, sql='SELECT * FROM input',
                    definition=definition)
        if base is not None:
            spec['base'] = base
        if relationship is not None:
            spec['relationship'] = relationship
        return self._submit_with_custody(
            directory,
            source,
            spec,
            lambda payload, dispatch: (
                self._http('POST', '/run', json_body=payload, dispatch=dispatch)
                if self._port is not None
                else self._call('run', directory / 'request.json', dispatch=dispatch)
            ),
        )

    def update_table(self, dataset, operation, base, keys, replacements_table,
                     deletions=None, definition=DEFINITION, relationship=None):
        """Replace/insert complete rows by key against the exact selected base."""
        self._dataset_schemas[dataset] = replacements_table.schema
        directory = self._request_directory(operation)
        source, digest = self._stage(directory, 'source.parquet', replacements_table)
        spec = dict(dataset=dataset, operation=operation, definition=definition,
                    base=base, keys=list(keys),
                    replacements={'path': str(source), 'digest': digest})
        if deletions is not None:
            deletion_path, deletion_digest = self._stage(directory, 'deletions.parquet', deletions)
            spec['deletions'] = {'path': str(deletion_path), 'digest': deletion_digest}
        if relationship is not None:
            spec['relationship'] = relationship
        return self._submit_with_custody(
            directory,
            source,
            spec,
            lambda payload, dispatch: (
                self._http('POST', '/updates/run', json_body=payload, dispatch=dispatch)
                if self._port is not None
                else self._call('update', directory / 'request.json', dispatch=dispatch)
            ),
        )


class DocSpecLake:
    """Route news_lake records into native datasets, one per contract table.

    Upsert tables (outlets/items/entities) merge each incoming poll against
    the stored row for its id so earlier evidence survives (C1), then submit
    the merged rows as a complete-key update. Append tables admit the initial
    batch as a build and subsequent batches as complete-key updates against the
    exact prior version so earlier rows and unchanged files remain retained.
    """

    def __init__(self, client, workspace_suffix=''):
        self.client = client
        self.workspace_suffix = sanitize_id(workspace_suffix) if workspace_suffix else ''
        self.committed = {}
        self.last_lookup_stats = {}

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
        """Fetch only the rows matching ``ids`` from the exact ``pin``."""
        id_list = sorted(set(ids))
        dataset = pin['dataset']['dataset']
        if not id_list:
            self.last_lookup_stats[dataset] = {'requested_ids': 0, 'matched_rows': 0}
            return {}
        table = self.client.read_arrow(pin, schema=kind_arrow_schema(kind))
        id_set = pa.array(id_list, type=pa.string())
        mask = pc.is_in(table['id'], value_set=id_set)
        filtered = table.filter(mask)
        rows = table_records(filtered)
        self.last_lookup_stats[dataset] = {
            'requested_ids': len(id_list),
            'matched_rows': len(rows),
            'total_rows': table.num_rows,
        }
        return {row['id']: row for row in rows}

    def commit_records(self, records, generation=None, family='news'):
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
            return prior
        base_version = prior['dataset']['version']
        operation = self._operation(f'append-{kind}', content_digest([base_version, new_records]))
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
            return prior
        base_version = prior['dataset']['version']
        operation = self._operation(f'upsert-{kind}', content_digest([base_version, changed]))
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

    def __init__(self, client, workspace_suffix='', *, pins=None):
        self.client = client
        self.workspace_suffix = sanitize_id(workspace_suffix) if workspace_suffix else ''
        self.pins = dict(pins or {})
        self.last_bridge_diff = {}

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
        tables = {
            'entity_roots': bridges.entity_roots_arrow(records),
            'selected_mentions': bridges.selected_mentions_arrow(records, selections),
            'survivor_items': bridges.survivor_items_arrow(records, selections),
        }
        pins = {}
        for dataset, table in tables.items():
            operation = self._operation(f'materialize-{dataset}',
                                        content_digest(table_records(table)))
            pins[dataset] = self.client.run_table(table, dataset, operation)
        self.pins.update(pins)
        return dict(pins)

    def update_bridges(self, records_or_release_read, selections=None):
        """Diff new bridge rows against pinned bridge tables and update only changed keys."""
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
                operation = self._operation(
                    f'materialize-{dataset}', content_digest(table_records(table))
                )
                pin = self.client.run_table(table, dataset, operation)
                self.pins[dataset] = pin
                updated_pins[dataset] = pin
                diff_summary[dataset] = {
                    'changed_rows': len(new_rows),
                    'removed_keys': 0,
                    'updated': True,
                }
                continue
            current_table = self.client.read_arrow(prior_pin, schema=schema)
            current_by_key = {
                row[key_col]: row for row in table_records(current_table)
            }
            changed_rows = [
                row for row in new_rows
                if current_by_key.get(row[key_col]) != _strip_nulls(row)
            ]
            new_keys = {row[key_col] for row in new_rows}
            removed_keys = sorted(set(current_by_key) - new_keys)
            diff_summary[dataset] = {
                'changed_rows': len(changed_rows),
                'removed_keys': len(removed_keys),
                'updated': bool(changed_rows or removed_keys),
            }
            if not changed_rows and not removed_keys:
                self.pins[dataset] = prior_pin
                updated_pins[dataset] = prior_pin
                continue
            replacements_table = pa.Table.from_pylist(changed_rows, schema=schema)
            deletions_table = (
                pa.Table.from_pylist(
                    [{key_col: key} for key in removed_keys],
                    schema=pa.schema([schema.field(key_col)]),
                )
                if removed_keys
                else None
            )
            base_version = prior_pin['dataset']['version']
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
            updated_pins[dataset] = pin
        self.last_bridge_diff = diff_summary
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
        joined = table_records(self.client.read_arrow(pin))
        return self._assemble_politician_articles(records, release_id, joined, survivor_pin=survivor_pin)

    def _assemble_politician_articles(self, records, release_id, joined, *, survivor_pin=None):
        versions = _by_kind(list(records), 'version')
        if survivor_pin is None:
            survivor_pin = self._pin('survivor_items')
        survivor_rows = table_records(
            self.client.read_arrow(survivor_pin, schema=bridges.SURVIVOR_ITEMS_SCHEMA)
        )
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
    def _ensure_release_read(records_or_release_read, selections=None):
        if isinstance(records_or_release_read, dict) and 'tables' in records_or_release_read:
            return records_or_release_read
        records = list(records_or_release_read)
        release = next((r for r in records if r.get('kind') == 'release'), None)
        tables = {}
        for record in records:
            if record.get('kind') == 'release':
                continue
            tables.setdefault(KIND_TABLES[record['kind']], []).append(record)
        if release is None:
            recorded_at = max(
                (r['recorded_at'] for r in records if 'recorded_at' in r),
                default='2026-01-01T00:00:00Z',
            )
            release = {
                'kind': 'release',
                'id': '00000000-0000-5000-8000-000000000000',
                'recorded_at': recorded_at,
                'contract_version': CONTRACT_VERSION,
                'snapshots': [
                    {'table': table, 'table_uuid': '00000000-0000-5000-8000-000000000001'}
                    for table in CONTENT_TABLES
                ],
                'selections': list(() if selections is None else selections),
                'checkpoints': [],
            }
        return {'release': release, 'tables': tables}

    def export_authorized(self, records_or_release_read, destination_dir=None, *,
                          as_of=None, now=None, authorized=False, channel='public'):
        """Apply C5 rights and capture-expiry rules, then run native Parquet exports.

        Enforces ``news_lake.analysis.export.export_release`` before admitting
        any export dataset version so restricted or expired captures/versions
        are downgraded to ``metadata_only`` and stripped of bodies prior to
        native ``ExportSpec`` materialization.
        """
        release_read = self._ensure_release_read(records_or_release_read)
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
            existing_export = self.client.try_export_pin(export_dataset, export_op)
            if existing_export is not None:
                export_pin = existing_export
            else:
                current_channel = self.client.try_latest_export(export_dataset, channel_id)
                expected = current_channel['id'] if current_channel is not None else None
                export_spec = {
                    'dataset': export_dataset,
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
                if (not dest_file.exists()
                        or dest_file.stat().st_size != exported_path.stat().st_size
                        or sha256(dest_file.read_bytes()).hexdigest()
                        != sha256(exported_path.read_bytes()).hexdigest()):
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
    'restore_application_schema',
    'sanitize_id',
    'table_records',
    'version_ref',
]
