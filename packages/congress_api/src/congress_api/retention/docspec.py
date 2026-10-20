"""Thin persistent-host transport for maintained DocSpec source-only dataset operations.

Callers supply exact native requests, stable operation identities, and partition
routing. DocSpec owns admission, versions, completion, concurrency and recovery.
Application publication must select a coherent set of exact completed pins;
independent native latest results are preparation, not an application snapshot.
"""
from contextlib import contextmanager
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

from .docspec_host import ArrowResponse, DocSpecFailure, acquire_host


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


class NativeDatasets:
    """Invoke the configured native owner; do not duplicate lifecycle decisions."""

    def __init__(self, binary, workspace, *, remote=None, limits=None, timeout=120):
        self.binary = str(Path(binary).resolve())
        self.workspace = Path(workspace).resolve()
        self.remote = Path(remote).resolve() if remote is not None else None
        self.limits = Path(limits).resolve() if limits is not None else None
        self.timeout = timeout
        self._remote_secrets = {}
        self._host = None
        self._finalizer = None
        self._closed = False
        self._host_lock = threading.RLock()
        self._responses = set()
        self._configuration_path = None

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
                  'credentials', 'timeout_seconds'}
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
        client = cls(location('binary'), location('workspace'),
                     remote=remote, limits=limits, timeout=timeout)
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

    def _call(self, *args, remote=False):
        """Only local file hashing needs a separate native process."""
        if self._closed:
            raise RuntimeError('DocSpec client is closed')
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
            environment = ({**os.environ, **self._remote_secrets}
                           if self.remote is not None and self._remote_secrets else None)
            self._host = acquire_host(self._command(), environment,
                                      self.workspace, self.timeout)
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

    def run_table(self, table, *, dataset, operation, definition):
        """Pass one caller-bounded Arrow source table to the native Run API.

        The caller owns candidate identity, schema and completeness. Input paths
        are locators; native retained expected-digest identity controls replay.
        """
        self.workspace.mkdir(parents=True, exist_ok=True)
        directory = Path(mkdtemp(prefix='request-', dir=self.workspace))
        dispatch = {}
        retained = False
        request = None
        try:
            source = directory / 'source.parquet'
            physical = native_storage_schema(table.schema)
            stored = table if physical.equals(table.schema, check_metadata=True) else table.cast(physical, safe=True)
            pq.write_table(stored, source, compression='zstd')
            digest = self.hash_input(source)['digest']
            request = dict(dataset=dataset, operation=operation, definition=definition,
                input=str(source), expected_digest=digest, sql='SELECT * FROM input')
            # Persist replay inputs before sending: process death cannot run the
            # exception handler that diagnoses an indeterminate submission.
            (directory / 'request.json').write_text(
                json.dumps(request, ensure_ascii=False, allow_nan=False))
            return self._request('/run', request, dispatch=dispatch)
        except BaseException as error:
            cleanup_safe = (
                isinstance(error, DocSpecFailure)
                and error.status is not None
                and 400 <= error.status < 500
                and bool(error.code)
                and error.code not in {'worker', 'custody_quarantined', 'timeout', 'host_unavailable'}
            )
            if dispatch.get('submitted') and not cleanup_safe:
                # The native task may still need this producer file. Neither a
                # response timeout, worker/quarantine failure, nor a later host
                # exit proves durable admission or producer independence.
                retained = True
                request_path = directory / 'request.json'
                try:
                    size = source.stat().st_size
                    error.retained_input = dict(input=str(source), request=str(request_path), bytes=size)
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
        Closing the client or host never deletes these recovery inputs.
        """
        inputs = []
        for request in sorted(self.workspace.glob('request-*/request.json')):
            source = request.parent / 'source.parquet'
            try:
                size = source.stat().st_size
            except FileNotFoundError:
                size = None
            inputs.append(dict(input=str(source), request=str(request),
                               bytes=size))
        return inputs

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
    def source_batches(self, pin, *, schema=None):
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
        path = release_path + '/arrow/source'
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
                    physical = native_storage_schema(schema) if schema is not None else None
                    if physical is not None and not reader.schema.equals(physical, check_metadata=False):
                        raise ValueError('Native source storage schema differs from the selected application schema')

                    def batches():
                        for batch in reader:
                            yield batch if schema is None else batch.cast(schema, safe=True)
                        stream.finish()

                    with pa.RecordBatchReader.from_batches(
                            reader.schema if schema is None else schema, batches()) as restored:
                        yield restored
            finally:
                self._responses.discard(response)
