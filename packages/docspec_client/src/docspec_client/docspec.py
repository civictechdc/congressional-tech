"""Thin persistent-host transport for maintained DocSpec source-only dataset operations.

Callers supply exact native requests, stable operation identities, and partition
routing. DocSpec owns admission, versions, completion, concurrency and recovery.
Application publication must select a coherent set of exact completed pins;
independent native latest results are preparation, not an application snapshot.
"""
from contextlib import contextmanager
from hashlib import file_digest
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import weakref
from urllib.parse import quote
from tempfile import mkdtemp

import pyarrow as pa
import pyarrow.parquet as pq

from .docspec_host import (
    REQUIRED_LOOPBACK_CAPABILITIES,
    ArrowResponse,
    DocSpecFailure,
    acquire_host,
)

SUPPORTED_PLATFORMS = ('linux-amd64', 'darwin-arm64', 'darwin-amd64')
PRODUCER_PARQUET_ROW_GROUP_SIZE = 2048
QUALIFIED_DOCSPEC_RUNTIME = {
    'source_revision': '270a8b627405bfe5819bf41485f8e3848d5be328',
    'darwin_arm64_binary_sha256': '28d3a2a76e7ba9901e08cedfa8e1ba8039134049fc5e08d7827eaea035ea4ef0',
    'build_features': ('remote',),
    'required_capabilities': REQUIRED_LOOPBACK_CAPABILITIES,
    'safety_prerequisites': (
        'ct-3li2', 'ct-cpio', 'ct-xq1y', 'ct-5fkx', 'ct-gfv8', 'ct-q05l', 'ct-csyg',
        'ct-tuez', 'ct-nmjc', 'ct-13g5',
    ),
}


def native_storage_schema(schema):
    """Use lossless Iceberg types for unsigned values and binary offsets.

    The application retains the original schema in its immutable selection.
    Native pins describe the physical representation; schema-bound reads restore
    application types with Arrow's checked cast. UInt64 uses Decimal128(20, 0);
    Binary uses LargeBinary to match the native nested writer. No floating-point
    value occurs. Native storage can therefore use wider buffers than the input.
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


def _write_producer_parquet(table, path, *, row_group_size=PRODUCER_PARQUET_ROW_GROUP_SIZE):
    """Write producer Parquet inputs with bounded row groups so zero-copy Arrow slices stay within max_batch_bytes."""
    physical = native_storage_schema(table.schema)
    stored = table if physical.equals(table.schema, check_metadata=True) else table.cast(physical, safe=True)
    pq.write_table(stored, path, compression='zstd', row_group_size=row_group_size)


def producer_input_entry(request_path):
    """Return the producer files referenced by a retained request, with total bytes."""
    try:
        request = json.loads(Path(request_path).read_text())
    except (OSError, ValueError):
        request = None
    if not isinstance(request, dict):
        return None
    paths = []
    for value in (request.get('input'),
                  (request.get('replacements') or {}).get('path')
                  if isinstance(request.get('replacements'), dict) else None,
                  (request.get('deletions') or {}).get('path')
                  if isinstance(request.get('deletions'), dict) else None):
        if isinstance(value, str) and value and value not in paths:
            paths.append(value)
    if not paths:
        return None
    files = []
    total = 0
    for path in paths:
        try:
            size = Path(path).stat().st_size
        except FileNotFoundError:
            size = None
        else:
            total += size
        files.append(dict(path=path, bytes=size))
    return dict(input=paths[0], request=str(request_path), bytes=total, files=files)


def cleanup_safe(error):
    """Only deterministic pre-admission refusals prove producer independence."""
    return (
        isinstance(error, DocSpecFailure)
        and error.status is not None
        and 400 <= error.status < 500
        and bool(error.code)
        and error.code not in {'worker', 'custody_quarantined', 'timeout', 'host_unavailable'}
    )


class NativeDatasets:
    """Invoke the configured native owner; do not duplicate lifecycle decisions."""

    def __init__(self, binary, workspace, *, remote=None, limits=None, timeout=120,
                 source_revision=None, platform=None, build_features=None,
                 binary_sha256=None, required_capabilities=REQUIRED_LOOPBACK_CAPABILITIES):
        self.binary = str(Path(binary).resolve())
        self.workspace = Path(workspace).resolve()
        self.remote = Path(remote).resolve() if remote is not None else None
        self.limits = Path(limits).resolve() if limits is not None else None
        self.timeout = timeout
        self.source_revision = self._validate_revision(source_revision)
        self.platform = self._validate_platform(platform)
        self.build_features = self._validate_features(build_features, remote=self.remote is not None)
        self.binary_sha256 = self._validate_sha256(binary_sha256)
        self.required_capabilities = self._validate_capabilities(required_capabilities)
        self._remote_secrets = {}
        self._host = None
        self._finalizer = None
        self._closed = False
        self._host_lock = threading.RLock()
        self._responses = set()
        self._configuration_path = None

    @staticmethod
    def _validate_revision(value):
        if value is None:
            return None
        if not isinstance(value, str) or re.fullmatch(r'[0-9a-f]{40}', value) is None:
            raise ValueError('DocSpec runtime source_revision must be a 40-character hex commit SHA')
        return value

    @staticmethod
    def _validate_platform(value):
        if value is None:
            return None
        if not isinstance(value, str) or value not in SUPPORTED_PLATFORMS:
            raise ValueError(f'DocSpec runtime platform must be one of {SUPPORTED_PLATFORMS}')
        return value

    @staticmethod
    def _validate_features(value, *, remote=False):
        if value is None:
            return None
        if (not isinstance(value, (list, tuple)) or not value
                or any(not isinstance(item, str) or not item.strip() for item in value)):
            raise ValueError('DocSpec runtime build_features must be a non-empty list of feature names')
        features = tuple(dict.fromkeys(value))
        if remote and 'remote' not in features:
            raise ValueError('Remote DocSpec configuration requires the remote build feature')
        return features

    @staticmethod
    def _validate_sha256(value):
        if value is None:
            return None
        if not isinstance(value, str) or re.fullmatch(r'[0-9a-f]{64}', value) is None:
            raise ValueError('DocSpec runtime binary_sha256 must be a 64-character hex SHA-256 digest')
        return value

    @staticmethod
    def _validate_capabilities(value):
        if (not isinstance(value, (list, tuple)) or not value
                or any(not isinstance(item, str) or not item.strip() for item in value)):
            raise ValueError('DocSpec runtime required_capabilities must be a non-empty list of capability names')
        capabilities = tuple(dict.fromkeys(value))
        if not set(REQUIRED_LOOPBACK_CAPABILITIES).issubset(capabilities):
            raise ValueError('DocSpec runtime requires request-deadline and owned-stdin-eof capabilities')
        return capabilities

    def verify_runtime(self, *, expected_sha256=None, expected_platform=None,
                       expected_source_revision=None, required_features=(),
                       required_capabilities=REQUIRED_LOOPBACK_CAPABILITIES):
        """Verify binary existence, permissions, digest, platform, features and capabilities before execution."""
        expected_sha = self._validate_sha256(expected_sha256) if expected_sha256 is not None else self.binary_sha256
        if expected_sha256 is not None and self.binary_sha256 is not None and expected_sha != self.binary_sha256:
            raise ValueError('Configured binary_sha256 differs from its approved SHA-256')
        target_platform = self._validate_platform(expected_platform) if expected_platform is not None else self.platform
        if expected_platform is not None and self.platform is not None and target_platform != self.platform:
            raise ValueError('Configured native binary platform differs from expected platform')
        target_revision = (self._validate_revision(expected_source_revision)
                           if expected_source_revision is not None else self.source_revision)
        if (expected_source_revision is not None and self.source_revision is not None
                and target_revision != self.source_revision):
            raise ValueError('Configured source_revision differs from expected source revision')
        capabilities = self._validate_capabilities(required_capabilities)
        if not set(capabilities).issubset(self.required_capabilities):
            raise ValueError('Configured DocSpec runtime capabilities do not satisfy required capabilities')
        needed_features = set(required_features) | ({'remote'} if self.remote is not None else set())
        if self.build_features is not None:
            if not needed_features.issubset(self.build_features):
                raise ValueError('DocSpec runtime is missing required build features')
            features = self.build_features
        elif required_features:
            raise ValueError('DocSpec runtime is missing required build features')
        else:
            features = ('remote',) if self.remote is not None else ()
        binary = Path(self.binary)
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise ValueError('The configured native binary is missing or not executable')
        with binary.open('rb') as source:
            header = source.read(4)
            source.seek(0)
            actual_sha = file_digest(source, 'sha256').hexdigest()
        if expected_sha is not None and actual_sha != expected_sha:
            raise ValueError('The configured native binary is missing or differs from its approved SHA-256')
        if target_platform == 'linux-amd64' and not header.startswith(b'\x7fELF'):
            raise ValueError('The configured native binary platform does not match linux-amd64')
        if (target_platform in ('darwin-arm64', 'darwin-amd64')
                and header[:4] not in {b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe'}):
            raise ValueError(f'The configured native binary platform does not match {target_platform}')
        return dict(
            verified=True,
            binary_sha256=actual_sha,
            platform=target_platform,
            source_revision=target_revision,
            build_features=features,
            required_capabilities=self.required_capabilities,
        )

    @classmethod
    def from_config(cls, path):
        """Load explicit paths and remote secrets without connecting or writing.

        Relative paths belong to the configuration directory. Credentials are a
        separate private JSON file mapping the remote config's DOCSPEC_* secret
        references to values. Only remote child processes receive these values;
        constructing a client never selects a production namespace or dataset.
        """
        path = Path(path).resolve()
        settings = json.loads(path.read_text())
        fields = {'version', 'binary', 'workspace', 'remote', 'limits',
                  'credentials', 'timeout_seconds', 'source_revision',
                  'platform', 'build_features', 'binary_sha256',
                  'required_capabilities'}
        if (not isinstance(settings, dict) or settings.get('version') != 1
                or type(settings.get('version')) is not int or set(settings) - fields):
            raise ValueError('Invalid DocSpec runtime configuration')

        def location(name):
            value = settings.get(name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f'DocSpec runtime requires an explicit {name} path')
            return (path.parent / value).resolve()

        timeout = settings.get('timeout_seconds', 120)
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('DocSpec runtime timeout must be a positive finite number')
        remote = location('remote') if 'remote' in settings else None
        limits = location('limits') if 'limits' in settings else None
        client = cls(
            location('binary'),
            location('workspace'),
            remote=remote,
            limits=limits,
            timeout=timeout,
            source_revision=settings.get('source_revision'),
            platform=settings.get('platform'),
            build_features=settings.get('build_features'),
            binary_sha256=settings.get('binary_sha256'),
            required_capabilities=settings.get('required_capabilities', REQUIRED_LOOPBACK_CAPABILITIES),
        )
        if remote is not None:
            configuration = json.loads(remote.read_text())
            references = configuration.get('secret_env') if isinstance(configuration, dict) else None
            if (not isinstance(references, dict) or not references
                    or any(not isinstance(name, str)
                           or re.fullmatch(r'DOCSPEC_[A-Z0-9_]+', name) is None
                           for name in references.values())):
                raise ValueError('Remote secrets require explicit DOCSPEC_ environment references')
            credential_path = location('credentials')
            if credential_path.stat().st_mode & 0o077:
                raise ValueError('DocSpec credentials require private file permissions (0600)')
            credentials = json.loads(credential_path.read_text())
            if (not isinstance(credentials, dict) or set(credentials) != set(references.values())
                    or any(not isinstance(value, str) or not value or '\0' in value
                           for value in credentials.values())):
                raise ValueError('DocSpec credentials must match all declared secret references')
            client._remote_secrets = credentials
        elif 'credentials' in settings:
            raise ValueError('DocSpec credentials require an explicit remote configuration')
        client._configuration_path = path
        return client

    def execution_files(self):
        """Name immutable executable/configuration inputs for caller guards.

        Workspace/request files are mutable native state. Credentials are loaded
        once into the private child environment and are never returned here.
        """
        return tuple(dict.fromkeys(value for value in (self._configuration_path,
            Path(self.binary), self.remote, self.limits) if value is not None))

    def _command(self, *, remote=True):
        command = [self.binary, '--workspace', str(self.workspace)]
        if self.limits is not None:
            command += ['--limits', str(self.limits)]
        if remote and self.remote is not None:
            command += ['--remote', str(self.remote)]
        return command

    def _has_runtime_pins(self):
        return any(value is not None for value in (
            self.binary_sha256, self.platform, self.source_revision, self.build_features))

    def _call(self, *args, remote=False):
        """Only local file hashing needs a separate native process."""
        if self._closed:
            raise RuntimeError('DocSpec client is closed')
        if self._has_runtime_pins():
            self.verify_runtime()
        command = [*self._command(remote=remote), *map(str, args)]
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=self.timeout)
        if result.returncode:
            raise DocSpecFailure(command, result)
        return json.loads(result.stdout) if result.stdout.strip() else None

    def _execution_host(self):
        with self._host_lock:
            return self._acquire_host()

    def _acquire_host(self):
        if self._closed:
            raise RuntimeError('DocSpec client is closed')
        if self._host is None:
            if self._has_runtime_pins():
                self.verify_runtime()
            environment = ({**os.environ, **self._remote_secrets}
                           if self.remote is not None and self._remote_secrets else None)
            self._host = acquire_host(self._command(), environment,
                                      self.workspace, self.timeout,
                                      required_capabilities=self.required_capabilities)
            self._finalizer = weakref.finalize(self, self._host.release)
        return self._host

    def close(self):
        """Cancel this client's reads; its last owner also stops the native host."""
        with self._host_lock:
            self._closed = True
            for response in tuple(self._responses):
                response.close()
            self._responses.clear()
            if self._finalizer is not None:
                self._finalizer()

    def __enter__(self):
        if self._closed:
            raise RuntimeError('DocSpec client is closed')
        return self

    def __exit__(self, *exc):
        self.close()

    def _request(self, path, request, *, dispatch=None):
        # Match CLI JSON validation before any host startup or native work.
        payload = json.dumps(request, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        return self._host_request('POST', path, content=payload,
            headers={'content-type': 'application/json'}, dispatch=dispatch)

    def _host_request(self, method, path, **kwargs):
        deadline = time.monotonic() + self.timeout
        return self._execution_host().request(method, path, deadline=deadline, **kwargs)

    def hash_input(self, path):
        """Hash a local producer file without opening the configured remote host."""
        return self._call('hash', Path(path).resolve(), remote=False)

    def run(self, request):
        return self._request('/run', request)

    def run_table(self, table, *, dataset, operation, definition, relationship=None,
                  base=None):
        """Pass one caller-bounded Arrow source table to the native Run API.

        The caller owns candidate identity, schema and completeness. Input paths
        are locators; native retained expected-digest identity controls replay.
        ``relationship`` and ``base`` are optional source-declaration fields.
        """
        self.workspace.mkdir(parents=True, exist_ok=True)
        directory = Path(mkdtemp(prefix='request-', dir=self.workspace))
        dispatch = {}
        retained = False
        request = None
        try:
            source = directory / 'source.parquet'
            _write_producer_parquet(table, source)
            digest = self.hash_input(source)['digest']
            request = dict(dataset=dataset, operation=operation, definition=definition,
                input=str(source), expected_digest=digest, sql='SELECT * FROM input')
            if base is not None:
                request['base'] = base
            if relationship is not None:
                request['relationship'] = relationship
            # Persist replay inputs before sending: process death cannot run the
            # exception handler that diagnoses an indeterminate submission.
            (directory / 'request.json').write_text(
                json.dumps(request, ensure_ascii=False, allow_nan=False))
            return self._request('/run', request, dispatch=dispatch)
        except BaseException as error:
            cleanup_ok = cleanup_safe(error)
            if dispatch.get('submitted') and not cleanup_ok:
                # The native task may still need this producer file. Neither a
                # response timeout, worker/quarantine failure, nor a later host
                # exit proves durable admission or producer independence.
                retained = True
                request_path = directory / 'request.json'
                try:
                    entry = producer_input_entry(request_path)
                    size = entry['bytes'] if entry is not None else None
                    error.retained_input = dict(
                        input=str(source),
                        request=str(request_path),
                        bytes=size,
                        files=entry['files'] if entry is not None else [],
                    )
                    error.add_note(f'DocSpec producer input retained: {source} ({size} bytes); '
                                   f'exact replay request: {request_path}')
                except OSError as diagnostic:
                    error.add_note(f'DocSpec producer directory retained at {directory}; '
                                   f'could not save its diagnostic: {diagnostic}')
            raise
        finally:
            if not retained:
                shutil.rmtree(directory)

    def retained_producer_inputs(self):
        """Inspect unresolved local producer files without inferring native completion.

        Unknown attempts accumulate until explicitly reconciled. Sizes describe
        actual local source files, not a bound on their count or aggregate bytes.
        Every producer file referenced by ``request.json`` is reported, including
        an Update's replacements and deletions. Closing the client or host never
        deletes these recovery inputs.
        """
        inputs = []
        for request in sorted(self.workspace.glob('request-*/request.json')):
            entry = producer_input_entry(request)
            if entry is not None:
                inputs.append(entry)
        return inputs

    def update_table(self, table=None, *, dataset, operation, definition, base, keys,
                     replacements=None, deletions=None, relationship=None):
        """Submit one ``UpdateSpec`` with pre-persisted producer custody.

        Accepts either an Arrow ``table`` (and optional Arrow ``deletions`` table)
        staged into this request's temporary directory, or pre-staged
        ``replacements`` / ``deletions`` ``InputSpec`` dicts. Both replacement and
        deletion Parquet files are referenced by ``request.json`` before submission,
        so an indeterminate outcome can be replayed and every referenced file
        survives caller cleanup.
        """
        self.workspace.mkdir(parents=True, exist_ok=True)
        directory = Path(mkdtemp(prefix='request-', dir=self.workspace))
        dispatch = {}
        retained = False
        try:
            if replacements is None:
                if table is None:
                    raise ValueError('update_table requires either table or replacements')
                source = directory / 'replacements.parquet'
                _write_producer_parquet(table, source)
                digest = self.hash_input(source)['digest']
                replacements_spec = dict(path=str(source), digest=digest)
            else:
                replacements_spec = dict(replacements)
            deletions_spec = None
            if isinstance(deletions, pa.Table):
                deletion_path = directory / 'deletions.parquet'
                _write_producer_parquet(deletions, deletion_path)
                deletion_digest = self.hash_input(deletion_path)['digest']
                deletions_spec = dict(path=str(deletion_path), digest=deletion_digest)
            elif deletions is not None:
                deletions_spec = dict(deletions)
            request = dict(dataset=dataset, operation=operation, definition=definition,
                           base=base, keys=list(keys), replacements=replacements_spec)
            if relationship is not None:
                request['relationship'] = relationship
            if deletions_spec is not None:
                request['deletions'] = deletions_spec
            (directory / 'request.json').write_text(
                json.dumps(request, ensure_ascii=False, allow_nan=False))
            primary = Path(replacements_spec['path'])
            return self._request('/updates/run', request, dispatch=dispatch)
        except BaseException as error:
            if dispatch.get('submitted') and not cleanup_safe(error):
                retained = True
                try:
                    entry = producer_input_entry(directory / 'request.json')
                    size = entry['bytes'] if entry is not None else None
                    error.retained_input = dict(
                        input=str(primary),
                        request=str(directory / 'request.json'),
                        bytes=size,
                        files=entry['files'] if entry is not None else [],
                    )
                    error.add_note(
                        f'DocSpec producer inputs retained under {directory} ({size} bytes); '
                        f'exact replay request: {directory / "request.json"}'
                    )
                except OSError as diagnostic:
                    error.add_note(f'DocSpec producer directory retained at {directory}; '
                                   f'could not save its diagnostic: {diagnostic}')
            raise
        finally:
            if not retained:
                shutil.rmtree(directory)

    def request(self, path, request):
        """Submit one typed native request on an explicit route."""
        return self._request(path, request)

    def refresh(self, request):
        return self._request('/refreshes/run', request)

    def plan_refresh(self, request):
        return self._request('/refreshes/plan', request)

    def seal_generation(self, request):
        return self._request('/generations/seal', request)

    def capture_inputs(self, inputs):
        return self._request('/inputs/capture', inputs)

    def correct_dependencies(self, request):
        return self._request('/dependencies/corrections', request)

    def plan_schema(self, request):
        return self._request('/schemas/plan', request)

    def evolve_schema(self, request):
        return self._request('/schemas/run', request)

    def plan_backfill(self, request):
        return self._request('/backfills/plan', request)

    def backfill(self, request):
        return self._request('/backfills/run', request)

    def plan_continuous_backfill(self, request):
        return self._request('/plan-continuous-backfill', request)

    def continuous_backfill(self, request):
        return self._request('/continuous-backfill', request)

    def plan_evidence(self, request):
        return self._request('/receipts/plan', request)

    def update_evidence(self, request):
        return self._request('/receipts/run', request)

    def update_evidence_table(self, table=None, *, dataset, operation, definition, base,
                              replacements=None, deletions=None, return_plan=False):
        """Submit one ``EvidenceSpec`` with pre-persisted producer custody."""
        self.workspace.mkdir(parents=True, exist_ok=True)
        directory = Path(mkdtemp(prefix='request-', dir=self.workspace))
        dispatch = {}
        retained = False
        try:
            if replacements is None:
                if table is None:
                    raise ValueError('update_evidence_table requires either table or replacements')
                source = directory / 'replacements.parquet'
                _write_producer_parquet(table, source)
                digest = self.hash_input(source)['digest']
                replacements_spec = dict(path=str(source), digest=digest)
            else:
                replacements_spec = dict(replacements)
            deletions_spec = None
            if isinstance(deletions, pa.Table):
                deletion_path = directory / 'deletions.parquet'
                _write_producer_parquet(deletions, deletion_path)
                deletion_digest = self.hash_input(deletion_path)['digest']
                deletions_spec = dict(path=str(deletion_path), digest=deletion_digest)
            elif deletions is not None:
                deletions_spec = dict(deletions)
            request = dict(dataset=dataset, operation=operation, definition=definition,
                           base=base, replacements=replacements_spec)
            if deletions_spec is not None:
                request['deletions'] = deletions_spec
            (directory / 'request.json').write_text(
                json.dumps(request, ensure_ascii=False, allow_nan=False))
            primary = Path(replacements_spec['path'])
            plan = self.plan_evidence(request)
            if not isinstance(plan, dict) or plan.get('dataset') != dataset or plan.get('operation') != operation:
                raise ValueError('Planned evidence receipt update differs from the requested dataset or operation')
            self.last_evidence_plan = plan
            pin = self._request('/receipts/run', request, dispatch=dispatch)
            return (plan, pin) if return_plan else pin
        except BaseException as error:
            if dispatch.get('submitted') and not cleanup_safe(error):
                retained = True
                try:
                    entry = producer_input_entry(directory / 'request.json')
                    size = entry['bytes'] if entry is not None else None
                    error.retained_input = dict(
                        input=str(primary),
                        request=str(directory / 'request.json'),
                        bytes=size,
                        files=entry['files'] if entry is not None else [],
                    )
                    error.add_note(
                        f'DocSpec producer inputs retained under {directory} ({size} bytes); '
                        f'exact replay request: {directory / "request.json"}'
                    )
                except OSError as diagnostic:
                    error.add_note(f'DocSpec producer directory retained at {directory}; '
                                   f'could not save its diagnostic: {diagnostic}')
            raise
        finally:
            if not retained:
                shutil.rmtree(directory)

    def compare(self, before, after, *, group='source', identity='values', force_full=False):
        """Compare two exact releases without streaming row payloads."""
        return self._request(
            '/compare',
            dict(
                before=before,
                after=after,
                group=group,
                options=dict(identity=identity, force_full=bool(force_full)),
            ),
        )

    @contextmanager
    def changes_batches(self, before, after, *, group='source', identity='occurrences',
                        force_full=False):
        """Stream one exact change stream and its ``docspec.change`` descriptor."""
        started = time.monotonic()
        deadline = started + self.timeout
        host = self._execution_host()
        payload = json.dumps(
            dict(
                before=before,
                after=after,
                group=group,
                options=dict(identity=identity, force_full=bool(force_full)),
            ),
            ensure_ascii=False,
            separators=(',', ':'),
            allow_nan=False,
        )
        with host.stream(
            'POST',
            '/changes',
            deadline=deadline,
            content=payload,
            headers={'content-type': 'application/json'},
        ) as (response, deadline):
            self._responses.add(response)
            try:
                host.check_response(response)
                with ArrowResponse(response, deadline=deadline) as stream, \
                        pa.ipc.open_stream(stream) as reader:
                    raw_meta = (reader.schema.metadata or {}).get(b'docspec.change')
                    descriptor = json.loads(raw_meta.decode('utf-8')) if raw_meta else None

                    def batches():
                        for batch in reader:
                            yield batch
                        stream.finish()

                    with pa.RecordBatchReader.from_batches(reader.schema, batches()) as restored:
                        yield descriptor, restored
            finally:
                self._responses.discard(response)

    def read_changes(self, before, after, *, group='source', identity='occurrences',
                     force_full=False):
        """Consume one change stream, returning ``(descriptor, table, summary)``."""
        with self.changes_batches(
            before, after, group=group, identity=identity, force_full=force_full
        ) as (descriptor, reader):
            batches = list(reader)
            table = pa.Table.from_batches(batches, schema=reader.schema)
        added_rows = 0
        removed_rows = 0
        if 'side' in table.column_names:
            for side in table['side'].to_pylist():
                if side in ('after', 'added', '+1', 1):
                    added_rows += 1
                elif side in ('before', 'removed', '-1', -1):
                    removed_rows += 1
        return dict(
            descriptor=descriptor,
            table=table,
            added_rows=added_rows,
            removed_rows=removed_rows,
            total_rows=table.num_rows,
        )

    def read_keys(self, pin, key, values, *, columns=None, schema=None):
        """Stream only rows matching ``values`` on ``key`` from an exact release pin."""
        started = time.monotonic()
        deadline = started + self.timeout
        dataset, version = pin['dataset']['dataset'], pin['id']
        host = self._execution_host()
        release_path = f'/datasets/{quote(dataset, safe="")}/versions/{quote(version, safe="")}'
        if host.request('GET', release_path, deadline=deadline) != pin:
            raise ValueError('Native release differs from the selected exact pin')
        spec = dict(key=key, values=[str(v) for v in values])
        if columns is not None:
            spec['columns'] = list(columns)
        payload = json.dumps(spec, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        path = release_path + '/keys'
        with host.stream(
            'POST',
            path,
            deadline=deadline,
            content=payload,
            headers={'content-type': 'application/json'},
        ) as (response, deadline):
            self._responses.add(response)
            try:
                host.check_response(response)
                expected = {
                    'docspec-dataset': dataset,
                    'docspec-version': version,
                    'docspec-manifest-blake3': pin['manifest']['digest'],
                    'content-type': 'application/vnd.apache.arrow.stream',
                }
                if any(response.headers.get(k) != v for k, v in expected.items()):
                    raise ValueError('Native stream differs from the selected exact pin')
                with ArrowResponse(response, deadline=deadline) as stream, \
                        pa.ipc.open_stream(stream) as reader:
                    table = reader.read_all()
                    stream.finish()
                return table if schema is None else table.cast(schema, safe=True)
            finally:
                self._responses.discard(response)

    def _read_pin_endpoint(self, pin, suffix, *, schema=None):
        started = time.monotonic()
        deadline = started + self.timeout
        dataset, version = pin['dataset']['dataset'], pin['id']
        host = self._execution_host()
        release_path = f'/datasets/{quote(dataset, safe="")}/versions/{quote(version, safe="")}'
        if host.request('GET', release_path, deadline=deadline) != pin:
            raise ValueError('Native release differs from the selected exact pin')
        path = release_path + suffix
        with host.stream('GET', path, deadline=deadline) as (response, deadline):
            self._responses.add(response)
            try:
                host.check_response(response)
                expected = {
                    'docspec-dataset': dataset,
                    'docspec-version': version,
                    'docspec-manifest-blake3': pin['manifest']['digest'],
                    'content-type': 'application/vnd.apache.arrow.stream',
                }
                if any(response.headers.get(k) != v for k, v in expected.items()):
                    raise ValueError('Native stream differs from the selected exact pin')
                with ArrowResponse(response, deadline=deadline) as stream, \
                        pa.ipc.open_stream(stream) as reader:
                    table = reader.read_all()
                    stream.finish()
                return table if schema is None else table.cast(schema, safe=True)
            finally:
                self._responses.discard(response)

    def read_receipts(self, pin, *, schema=None):
        return self._read_pin_endpoint(pin, '/receipts', schema=schema)

    def read_evidence(self, pin, *, schema=None):
        return self._read_pin_endpoint(pin, '/evidence', schema=schema)

    def read_occurrences(self, pin, *, schema=None):
        return self._read_pin_endpoint(pin, '/occurrences', schema=schema)

    def export(self, request):
        return self._request('/exports/run', request)

    def compact(self, request):
        return self._request('/compactions/run', request)

    def compact_lifecycle(self, dataset):
        return self._host_request(
            'POST', f'/datasets/{quote(dataset, safe="")}/lifecycle/compact')

    def latest_export(self, dataset, channel):
        return self._host_request(
            'GET',
            f'/datasets/{quote(dataset, safe="")}/exports/channels/{quote(channel, safe="")}')

    def export_pin(self, dataset, operation):
        return self._host_request(
            'GET', f'/datasets/{quote(dataset, safe="")}/exports/{quote(operation, safe="")}')

    def try_latest_export(self, dataset, channel):
        try:
            return self.latest_export(dataset, channel)
        except DocSpecFailure as error:
            if error.code == 'no_export' or 'no_export' in error.stderr:
                return None
            raise

    def try_export_pin(self, dataset, operation):
        try:
            return self.export_pin(dataset, operation)
        except DocSpecFailure as error:
            if error.code == 'no_export' or 'no_export' in error.stderr:
                return None
            raise

    def read_arrow(self, pin, group='source', *, schema=None):
        """Read one exact retained group as an Arrow table."""
        if group == 'source':
            with self.source_batches(pin, schema=schema) as batches:
                return pa.Table.from_batches(list(batches))
        dataset, version = pin['dataset']['dataset'], pin['id']
        path = (f'/datasets/{quote(dataset, safe="")}'
                f'/versions/{quote(version, safe="")}/arrow/{quote(group, safe="")}')
        deadline = time.monotonic() + self.timeout
        with self._execution_host().stream('GET', path, deadline=deadline) as (response, deadline):
            self._responses.add(response)
            try:
                self._execution_host().check_response(response)
                with ArrowResponse(response, deadline=deadline) as stream, \
                        pa.ipc.open_stream(stream) as reader:
                    table = reader.read_all()
                    stream.finish()
                return table if schema is None else table.cast(schema, safe=True)
            finally:
                self._responses.discard(response)

    def plan(self, request):
        return self._request('/plan', request)

    def update(self, request):
        return self._request('/updates/run', request)

    def plan_update(self, request):
        return self._request('/updates/plan', request)

    def latest(self, dataset):
        return self._host_request('GET', f'/datasets/{quote(dataset, safe="")}/latest')

    def release(self, dataset, operation):
        return self._host_request('GET',
            f'/datasets/{quote(dataset, safe="")}/versions/{quote(operation, safe="")}')

    def inspect(self, dataset):
        return self._host_request('GET', f'/datasets/{quote(dataset, safe="")}')

    def inspect_retention(self, request):
        return self._request('/retention/inspect', request)

    def plan_removal(self, request):
        return self._request('/retention/removal/plan', request)

    @contextmanager
    def source_batches(self, pin, *, schema=None, columns=None):
        """Stream one exact pin, retaining HTTP custody for the reader's lifetime.

        Resolve and compare the complete pin before reading; stream headers bind
        the body to that same version and manifest. Application schema restoration
        remains a checked cast from the lossless native storage representation.
        Leaving early cancels the response instead of draining it to a scratch file.
        One request deadline covers release lookup and the Arrow response. The
        required native protocol enforces that budget around handlers and bodies,
        so stalled and periodic reads both stop without killing shared work.
        """
        started = time.monotonic()
        deadline = started + self.timeout
        dataset, version = pin['dataset']['dataset'], pin['id']
        host = self._execution_host()
        release_path = f'/datasets/{quote(dataset, safe="")}/versions/{quote(version, safe="")}'
        if host.request('GET', release_path, deadline=deadline) != pin:
            raise ValueError('Native release differs from the selected exact pin')
        projected_cols = list(columns) if columns is not None else None
        if projected_cols is not None and (schema is None or projected_cols != list(schema.names)):
            if not projected_cols:
                raise ValueError('Projected column list must not be empty')
            query = '?columns=' + ','.join(quote(col, safe='') for col in projected_cols)
        else:
            query = ''
        path = release_path + '/arrow/source' + query
        target_schema = (
            pa.schema([schema.field(name) for name in projected_cols], metadata=schema.metadata)
            if (schema is not None and projected_cols is not None)
            else schema
        )
        with host.stream('GET', path, deadline=deadline) as (response, deadline):
            self._responses.add(response)
            try:
                host.check_response(response)
                expected = {'docspec-dataset': dataset, 'docspec-version': version,
                            'docspec-manifest-blake3': pin['manifest']['digest'],
                            'content-type': 'application/vnd.apache.arrow.stream'}
                if any(response.headers.get(key) != value for key, value in expected.items()):
                    raise ValueError('Native stream differs from the selected exact pin')
                with ArrowResponse(response, deadline=deadline) as stream, \
                        pa.ipc.open_stream(stream) as reader:
                    physical = native_storage_schema(target_schema) if target_schema is not None else None
                    extra_supplied = (
                        [f.name for f in reader.schema if f.name.startswith('__docspec_supplied_') and f.name not in physical.names]
                        if physical is not None else []
                    )
                    effective_reader_schema = (
                        pa.schema([f for f in reader.schema if f.name not in extra_supplied], metadata=reader.schema.metadata)
                        if extra_supplied else reader.schema
                    )
                    if (
                        extra_supplied
                        and physical is not None
                        and set(effective_reader_schema.names) == set(physical.names)
                        and all(effective_reader_schema.field(f.name).equals(f, check_metadata=False) for f in physical)
                    ):
                        effective_reader_schema = physical
                    if physical is not None and not effective_reader_schema.equals(physical, check_metadata=False):
                        raise ValueError('Native source storage schema differs from the selected application schema')

                    def batches():
                        for batch in reader:
                            if extra_supplied:
                                batch = pa.RecordBatch.from_arrays(
                                    [batch.column(reader.schema.get_field_index(f.name)) for f in effective_reader_schema],
                                    schema=effective_reader_schema,
                                )
                            yield batch if target_schema is None else batch.cast(target_schema, safe=True)
                        stream.finish()

                    with pa.RecordBatchReader.from_batches(
                            reader.schema if target_schema is None else target_schema, batches()) as restored:
                        yield restored
            finally:
                self._responses.discard(response)
