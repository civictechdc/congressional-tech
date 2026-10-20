"""Thin CLI transport for maintained DocSpec source-only dataset operations.

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
import subprocess
from tempfile import TemporaryDirectory

import pyarrow as pa
import pyarrow.parquet as pq


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


class DocSpecFailure(RuntimeError):
    """The maintained CLI refused or failed; its original diagnostic is retained."""

    def __init__(self, command, result):
        self.command = tuple(command)
        self.returncode = result.returncode
        self.stderr = result.stderr
        super().__init__(result.stderr.strip() or f'DocSpec exited {result.returncode}')


class NativeDatasets:
    """Invoke the configured native owner; do not duplicate lifecycle decisions."""

    def __init__(self, binary, workspace, *, remote=None, limits=None, timeout=120):
        self.binary = str(Path(binary).resolve())
        self.workspace = Path(workspace).resolve()
        self.remote = Path(remote).resolve() if remote is not None else None
        self.limits = Path(limits).resolve() if limits is not None else None
        self.timeout = timeout
        self._remote_secrets = {}
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

    def _call(self, *args, remote=True):
        command = [self.binary, '--workspace', str(self.workspace)]
        if self.limits is not None:
            command += ['--limits', str(self.limits)]
        if remote and self.remote is not None:
            command += ['--remote', str(self.remote)]
        command += list(map(str, args))
        environment = ({**os.environ, **self._remote_secrets}
                       if remote and self.remote is not None and self._remote_secrets else None)
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=self.timeout, env=environment)
        if result.returncode:
            raise DocSpecFailure(command, result)
        return json.loads(result.stdout) if result.stdout.strip() else None

    @contextmanager
    def _scratch(self):
        self.workspace.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix='request-', dir=self.workspace) as directory:
            yield Path(directory)

    def _request(self, command, request):
        with self._scratch() as directory:
            path = directory / 'request.json'
            path.write_text(json.dumps(request, ensure_ascii=False, separators=(',', ':'), allow_nan=False))
            return self._call(command, path)

    def hash_input(self, path):
        """Hash a local producer file without opening the configured remote host."""
        return self._call('hash', Path(path).resolve(), remote=False)

    def run(self, request):
        return self._request('run', request)

    def run_table(self, table, *, dataset, operation, definition):
        """Pass one caller-bounded Arrow source table to the native Run API.

        The caller owns candidate identity, schema and completeness. Input paths
        are locators; native retained expected-digest identity controls replay.
        """
        with self._scratch() as directory:
            source = directory / 'source.parquet'
            physical = native_storage_schema(table.schema)
            stored = table if physical.equals(table.schema, check_metadata=True) else table.cast(physical, safe=True)
            pq.write_table(stored, source, compression='zstd')
            digest = self.hash_input(source)['digest']
            return self.run(dict(dataset=dataset, operation=operation, definition=definition,
                input=str(source), expected_digest=digest, sql='SELECT * FROM input'))

    def plan(self, request):
        return self._request('plan', request)

    def update(self, request):
        return self._request('update', request)

    def plan_update(self, request):
        return self._request('plan-update', request)

    def latest(self, dataset):
        return self._call('latest', dataset)

    def release(self, dataset, operation):
        return self._call('release', dataset, operation)

    @contextmanager
    def source_batches(self, pin, *, schema=None):
        """Read one exact bounded partition pin through the configured native host.

        Native reading supplies the logical source fields, including nested
        values. Callers retain any application Arrow schema metadata separately;
        the native representation replaces application field metadata with native IDs.
        An explicit application schema restores losslessly mapped storage types.
        Other native types must match it exactly; arbitrary coercion is refused.
        The temporary Arrow IPC file remains alive while the reader is open.
        """
        with self._scratch() as directory:
            release, output = directory / 'release.json', directory / 'source.arrow'
            release.write_text(json.dumps(pin, ensure_ascii=False, separators=(',', ':'), allow_nan=False))
            self._call('read', release, output, '--group', 'source')
            with output.open('rb') as stream:
                with pa.ipc.open_stream(stream) as reader:
                    if schema is None:
                        yield reader
                    else:
                        physical = native_storage_schema(schema)
                        if not reader.schema.equals(physical, check_metadata=False):
                            raise ValueError('Native source storage schema differs from the selected application schema')
                        with pa.RecordBatchReader.from_batches(
                                schema, (batch.cast(schema, safe=True) for batch in reader)) as restored:
                            yield restored
