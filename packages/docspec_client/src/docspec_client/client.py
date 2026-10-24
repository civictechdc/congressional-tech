"""Main client interface for native DocSpec operations and dataset custody."""
import base64
from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from hashlib import file_digest
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import mkdtemp
import threading
import time
from typing import Any
from urllib.parse import quote
import weakref

import pyarrow as pa
import pyarrow.parquet as pq

try:
    import blake3 as _blake3_ext
except ImportError:
    _blake3_ext = None

from .binary import resolve_docspec_binary
from .host import ArrowResponse, Host, acquire_host
from .models import (
    ARROW_STREAM_MIME,
    PRE_ADMISSION_ERROR_CODES,
    PRODUCER_PARQUET_ROW_GROUP_SIZE,
    REQUIRED_LOOPBACK_CAPABILITIES,
    SUPPORTED_PLATFORMS,
    DocSpecFailure,
    PartitionSpec,
    UpdateMergeSpec,
    UpdateMergeStrategy,
)
from .schema import (
    application_schema,
    native_storage_schema,
    restore_application_schema,
)
from .specs import (
    apply_update_merge_spec,
    build_export_spec,
    build_ipc_run_spec,
    build_ipc_update_spec,
    build_update_merge_spec,
    parse_export_pin,
)
from .transport import (
    _write_producer_parquet,
    blake3_hex,
    encode_arrow_ipc_stream,
    producer_input_entry,
)


def cleanup_safe(error: Any) -> bool:
    """Only deterministic pre-admission refusals prove producer independence."""
    if not isinstance(error, DocSpecFailure) or error.status is None:
        return False
    if error.status >= 500:
        return False
    if error.code in {'worker', 'custody_quarantined', 'timeout', 'request_timeout', 'host_unavailable'}:
        return False
    if getattr(error, 'pre_admission', None) is not None:
        return bool(error.pre_admission) and error.status in (400, 409, 422)
    return error.status in (400, 409, 422) and error.code in PRE_ADMISSION_ERROR_CODES


def _cleanup_dataset_client(host: Host, responses: set[Any]) -> None:
    for response in tuple(responses):
        try:
            response.close()
        except Exception:
            pass
    responses.clear()
    host.release()


_VERIFIED_BINARY_CACHE: dict[tuple[str, int, int, int], tuple[str, bytes]] = {}


class NativeDatasets:
    """Invoke the configured native owner; do not duplicate lifecycle decisions."""

    def __init__(
        self,
        binary: Path | str | None = None,
        workspace: Path | str | None = None,
        *,
        remote: Path | str | None = None,
        limits: Path | str | None = None,
        timeout: float = 120,
        source_revision: str | None = None,
        platform: str | None = None,
        build_features: Sequence[str] | None = None,
        binary_sha256: str | None = None,
        required_capabilities: Sequence[str] = REQUIRED_LOOPBACK_CAPABILITIES,
    ) -> None:
        if binary is None:
            self.binary = str(resolve_docspec_binary())
        else:
            try:
                self.binary = str(resolve_docspec_binary(binary))
            except FileNotFoundError:
                self.binary = str(Path(binary).resolve())
        self.workspace = Path(workspace).resolve() if workspace is not None else Path.cwd()
        self.remote = Path(remote).resolve() if remote is not None else None
        self.limits = Path(limits).resolve() if limits is not None else None
        self.timeout = timeout
        self.source_revision = self._validate_revision(source_revision)
        self.platform = self._validate_platform(platform)
        self.build_features = self._validate_features(build_features, remote=self.remote is not None)
        self.binary_sha256 = self._validate_sha256(binary_sha256)
        self.required_capabilities = self._validate_capabilities(required_capabilities)
        self._remote_secrets: dict[str, str] = {}
        self._host: Host | None = None
        self._finalizer: Any = None
        self._closed = False
        self._host_lock = threading.RLock()
        self._responses: set[Any] = set()
        self._configuration_path: Path | None = None
        self.last_evidence_plan: dict[str, Any] | None = None
        self._verified_pins: set[tuple[str, str, str]] = set()

    @staticmethod
    def _validate_revision(value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or re.fullmatch(r'[0-9a-f]{40}', value) is None:
            raise ValueError('DocSpec runtime source_revision must be a 40-character hex commit SHA')
        return value

    @staticmethod
    def _validate_platform(value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or value not in SUPPORTED_PLATFORMS:
            raise ValueError(f'DocSpec runtime platform must be one of {SUPPORTED_PLATFORMS}')
        return value

    @staticmethod
    def _validate_features(value: Any, *, remote: bool = False) -> tuple[str, ...] | None:
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
    def _validate_sha256(value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or re.fullmatch(r'[0-9a-f]{64}', value) is None:
            raise ValueError('DocSpec runtime binary_sha256 must be a 64-character hex SHA-256 digest')
        return value

    @staticmethod
    def _validate_capabilities(value: Any) -> tuple[str, ...]:
        if (not isinstance(value, (list, tuple)) or not value
                or any(not isinstance(item, str) or not item.strip() for item in value)):
            raise ValueError('DocSpec runtime required_capabilities must be a non-empty list of capability names')
        capabilities = tuple(dict.fromkeys(value))
        if not set(REQUIRED_LOOPBACK_CAPABILITIES).issubset(capabilities):
            raise ValueError('DocSpec runtime requires request-deadline and owned-stdin-eof capabilities')
        return capabilities

    def verify_runtime(
        self,
        *,
        expected_sha256: str | None = None,
        expected_platform: str | None = None,
        expected_source_revision: str | None = None,
        required_features: Sequence[str] = (),
        required_capabilities: Sequence[str] = REQUIRED_LOOPBACK_CAPABILITIES,
    ) -> dict[str, Any]:
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
        st = binary.stat()
        cache_key = (str(binary), st.st_ino, st.st_mtime_ns, st.st_size)
        cached = _VERIFIED_BINARY_CACHE.get(cache_key)
        if cached is not None:
            actual_sha, header = cached
        else:
            with binary.open('rb') as source:
                header = source.read(4)
                source.seek(0)
                actual_sha = file_digest(source, 'sha256').hexdigest()
            if len(_VERIFIED_BINARY_CACHE) < 32:
                _VERIFIED_BINARY_CACHE[cache_key] = (actual_sha, header)
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
    def from_config(cls, path: Path | str) -> 'NativeDatasets':
        """Load explicit paths and remote secrets without connecting or writing."""
        p = Path(path).resolve()
        settings = json.loads(p.read_text())
        fields = {'version', 'binary', 'workspace', 'remote', 'limits',
                  'credentials', 'timeout_seconds', 'source_revision',
                  'platform', 'build_features', 'binary_sha256',
                  'required_capabilities'}
        if (not isinstance(settings, dict) or settings.get('version') != 1
                or type(settings.get('version')) is not int or set(settings) - fields):
            raise ValueError('Invalid DocSpec runtime configuration')

        def location(name: str) -> Path:
            value = settings.get(name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f'DocSpec runtime requires an explicit {name} path')
            return (p.parent / value).resolve()

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
        client._configuration_path = p
        return client

    def execution_files(self) -> tuple[Path, ...]:
        """Name immutable executable/configuration inputs for caller guards."""
        return tuple(dict.fromkeys(value for value in (self._configuration_path,
            Path(self.binary), self.remote, self.limits) if value is not None))

    def _command(self, *, remote: bool = True) -> list[str]:
        command = [self.binary, '--workspace', str(self.workspace)]
        if self.limits is not None:
            command += ['--limits', str(self.limits)]
        if remote and self.remote is not None:
            command += ['--remote', str(self.remote)]
        return command

    def _has_runtime_pins(self) -> bool:
        return any(value is not None for value in (
            self.binary_sha256, self.platform, self.source_revision, self.build_features))

    def _call(self, *args: Any, remote: bool = False) -> Any:
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

    def _execution_host(self) -> Host:
        with self._host_lock:
            return self._acquire_host()

    def _acquire_host(self) -> Host:
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
            self._finalizer = weakref.finalize(self, _cleanup_dataset_client, self._host, self._responses)
        return self._host

    def close(self) -> None:
        """Cancel this client's reads; its last owner also stops the native host."""
        with self._host_lock:
            self._closed = True
            if self._finalizer is not None:
                self._finalizer()
            else:
                for response in tuple(self._responses):
                    try:
                        response.close()
                    except Exception:
                        pass
                self._responses.clear()

    def __enter__(self) -> 'NativeDatasets':
        if self._closed:
            raise RuntimeError('DocSpec client is closed')
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _request(self, path: str, request: Any, *, dispatch: dict[str, Any] | None = None) -> Any:
        payload = json.dumps(request, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        return self._host_request('POST', path, content=payload,
            headers={'content-type': 'application/json'}, dispatch=dispatch)

    def _request_ipc(
        self,
        path: str,
        ipc_bytes: bytes,
        spec: Any,
        *,
        blake3_digest: str | None = None,
        dispatch: dict[str, Any] | None = None,
    ) -> Any:
        """Send an Arrow IPC stream POST with base64-encoded JSON spec and BLAKE3 digest headers."""
        spec_json = json.dumps(spec, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        spec_b64 = base64.b64encode(spec_json.encode('utf-8')).decode('ascii')
        headers = {
            'content-type': ARROW_STREAM_MIME,
            'x-docspec-spec-base64': spec_b64,
        }
        if blake3_digest is not None:
            headers['x-docspec-input-blake3'] = str(blake3_digest)
        return self._host_request(
            'POST',
            path,
            content=bytes(ipc_bytes),
            headers=headers,
            dispatch=dispatch,
        )

    def _host_request(self, method: str, path: str, **kwargs: Any) -> Any:
        deadline = time.monotonic() + self.timeout
        return self._execution_host().request(method, path, deadline=deadline, **kwargs)

    def hash_input(self, path: Path | str) -> dict[str, Any]:
        """Hash a local producer file without opening the configured remote host."""
        resolved = Path(path).resolve()
        if _blake3_ext is not None and resolved.is_file():
            if self._closed:
                raise RuntimeError('DocSpec client is closed')
            if self._has_runtime_pins():
                self.verify_runtime()
            data = resolved.read_bytes()
            return dict(digest=_blake3_ext.blake3(data).hexdigest(), bytes=len(data))
        return self._call('hash', resolved, remote=False)

    def run(self, request: Any) -> Any:
        return self._request('/run', request)

    def run_ipc(
        self,
        table: pa.Table,
        *,
        dataset: str,
        operation: str,
        definition: str,
        sql: str = 'SELECT * FROM input',
        relationship: Any = None,
        base: Any = None,
        native_types: bool = False,
    ) -> Any:
        """Stream one caller-bounded Arrow table directly to ``POST /run`` as an Arrow IPC stream."""
        ipc_bytes = encode_arrow_ipc_stream(table, native_types=native_types)
        digest = blake3_hex(ipc_bytes)
        spec = build_ipc_run_spec(
            dataset,
            operation=operation,
            definition=definition,
            sql=sql,
            relationship=relationship,
        )
        spec['expected_digest'] = digest
        if base is not None:
            spec['base'] = base
        return self._request_ipc('/run', ipc_bytes, spec, blake3_digest=digest)

    def run_table(
        self,
        table: pa.Table,
        *,
        dataset: str,
        operation: str,
        definition: str,
        relationship: Any = None,
        base: Any = None,
        partition_by: Any = None,
        stream_ipc: bool = False,
        native_types: bool = False,
        row_group_size: int | None = PRODUCER_PARQUET_ROW_GROUP_SIZE,
    ) -> Any:
        """Pass one caller-bounded Arrow source table to the native Run API."""
        normalized_partition_by = PartitionSpec.normalize(partition_by) if partition_by is not None else None
        if normalized_partition_by and isinstance(table, pa.Table):
            normalized_partition_by = [
                pf for pf in normalized_partition_by if pf['column'] in table.schema.names
            ] or None
        if stream_ipc and not normalized_partition_by:
            try:
                return self.run_ipc(
                    table,
                    dataset=dataset,
                    operation=operation,
                    definition=definition,
                    relationship=relationship,
                    base=base,
                    native_types=native_types,
                )
            except DocSpecFailure as error:
                status = getattr(error, 'status', None) or getattr(error, 'status_code', None)
                if status != 415:
                    raise

        self.workspace.mkdir(parents=True, exist_ok=True)
        directory = Path(mkdtemp(prefix='request-', dir=self.workspace))
        dispatch: dict[str, Any] = {}
        retained = False
        try:
            source = directory / 'source.parquet'
            _write_producer_parquet(table, source, row_group_size=row_group_size)
            digest = self.hash_input(source)['digest']
            request: dict[str, Any] = dict(dataset=dataset, operation=operation, definition=definition,
                input=str(source), expected_digest=digest, sql='SELECT * FROM input')
            if base is not None:
                request['base'] = base
            if relationship is not None:
                request['relationship'] = relationship
            if normalized_partition_by:
                request['partition_by'] = normalized_partition_by
            (directory / 'request.json').write_text(
                json.dumps(request, ensure_ascii=False, allow_nan=False))
            active_request = request
            used_legacy_rgs = False
            attempt = 0
            while attempt < 4:
                try:
                    return self._request('/run', active_request, dispatch=dispatch)
                except Exception as exc:
                    import httpx
                    if isinstance(exc, httpx.TransportError) and not isinstance(exc, httpx.TimeoutException) and not dispatch.get('submitted'):
                        if attempt < 3:
                            time.sleep(1.0 * (2 ** attempt))
                            attempt += 1
                            continue
                        raise
                    if not isinstance(exc, DocSpecFailure):
                        raise
                    msg = str(exc).lower()
                    if normalized_partition_by and 'unknown field' in msg and 'partition_by' in msg:
                        active_request = {k: v for k, v in active_request.items() if k != 'partition_by'}
                        normalized_partition_by = None
                        (directory / 'request.json').write_text(
                            json.dumps(active_request, ensure_ascii=False, allow_nan=False))
                        dispatch.clear()
                        continue
                    if row_group_size is None and not used_legacy_rgs and 'operation_conflict' in msg:
                        used_legacy_rgs = True
                        _write_producer_parquet(
                            table,
                            source,
                            row_group_size=None,
                            _legacy_row_group_sizing=True,
                        )
                        legacy_digest = self.hash_input(source)['digest']
                        active_request = dict(active_request, expected_digest=legacy_digest)
                        (directory / 'request.json').write_text(
                            json.dumps(active_request, ensure_ascii=False, allow_nan=False))
                        dispatch.clear()
                        continue
                    transient = any(
                        token in msg
                        for token in (
                            'commit state is unknown',
                            'gateway',
                            'remote_unconfirmed',
                            '502',
                            '503',
                            '504',
                        )
                    )
                    if transient and attempt < 3:
                        time.sleep(1.0 * (2 ** attempt))
                        dispatch.clear()
                        attempt += 1
                        continue
                    raise
        except BaseException as error:
            cleanup_ok = cleanup_safe(error)
            if dispatch.get('submitted') and not cleanup_ok:
                retained = True
                request_path = directory / 'request.json'
                try:
                    entry = producer_input_entry(request_path)
                    size = entry['bytes'] if entry is not None else None
                    setattr(error, 'retained_input', dict(
                        input=str(source),
                        request=str(request_path),
                        bytes=size,
                        files=entry['files'] if entry is not None else [],
                    ))
                    if hasattr(error, 'add_note'):
                        error.add_note(f'DocSpec producer input retained: {source} ({size} bytes); '
                                       f'exact replay request: {request_path}')
                except OSError as diagnostic:
                    if hasattr(error, 'add_note'):
                        error.add_note(f'DocSpec producer directory retained at {directory}; '
                                       f'could not save its diagnostic: {diagnostic}')
            raise
        finally:
            if not retained:
                shutil.rmtree(directory)

    def retained_producer_inputs(self) -> list[dict[str, Any]]:
        """Inspect unresolved local producer files without inferring native completion."""
        inputs = []
        for request in sorted(self.workspace.glob('request-*/request.json')):
            entry = producer_input_entry(request)
            if entry is not None:
                inputs.append(entry)
        return inputs

    def update_ipc(
        self,
        table: pa.Table,
        *,
        dataset: str,
        operation: str,
        definition: str,
        base: Any,
        keys: Sequence[str],
        deletions: Any = None,
        relationship: Any = None,
        merge: Any = None,
        native_types: bool = False,
    ) -> Any:
        """Stream one replacement Arrow table directly to ``POST /updates/run`` as an Arrow IPC stream."""
        ipc_bytes = encode_arrow_ipc_stream(table, native_types=native_types)
        digest = blake3_hex(ipc_bytes)
        spec = build_ipc_update_spec(
            dataset,
            operation=operation,
            definition=definition,
            base=base,
            keys=keys,
            replacement_digest=digest,
            relationship=relationship,
            deletions=deletions,
            merge=merge,
        )
        return self._request_ipc('/updates/run', ipc_bytes, spec, blake3_digest=digest)

    def update_table(
        self,
        table: pa.Table | None = None,
        *,
        dataset: str,
        operation: str,
        definition: str,
        base: Any,
        keys: Sequence[str],
        replacements: Any = None,
        deletions: Any = None,
        relationship: Any = None,
        merge: Any = None,
        stream_ipc: bool = False,
        native_types: bool = False,
    ) -> Any:
        """Submit one ``UpdateSpec`` with pre-persisted producer custody."""
        normalized_merge = None
        if merge is not None:
            if hasattr(merge, 'to_dict'):
                merge = merge.to_dict()
            normalized_merge = (
                build_update_merge_spec(
                    order_by=merge.get('order_by'),
                    columns=merge.get('columns'),
                )
                if isinstance(merge, Mapping)
                else UpdateMergeSpec.normalize(merge)
            )
            if isinstance(table, pa.Table):
                filtered_merge: dict[str, Any] = {}
                ord_col = normalized_merge.get('order_by')
                if isinstance(ord_col, str) and ord_col in table.schema.names:
                    filtered_merge['order_by'] = ord_col
                elif isinstance(ord_col, (list, tuple)):
                    filtered_merge['order_by'] = list(ord_col)
                filtered_cols: dict[str, str] = {}
                for k, v in (normalized_merge.get('columns') or {}).items():
                    if k not in table.schema.names:
                        continue
                    field_type = table.schema.field(k).type
                    if v == UpdateMergeStrategy.SET_UNION and not (
                        pa.types.is_list(field_type) or pa.types.is_large_list(field_type)
                    ):
                        v = UpdateMergeStrategy.MAX
                    filtered_cols[k] = v
                if filtered_cols:
                    filtered_merge['columns'] = filtered_cols
                normalized_merge = filtered_merge
        if stream_ipc and replacements is None and deletions is None and table is not None:
            try:
                return self.update_ipc(
                    table,
                    dataset=dataset,
                    operation=operation,
                    definition=definition,
                    base=base,
                    keys=keys,
                    relationship=relationship,
                    merge=normalized_merge,
                    native_types=native_types,
                )
            except DocSpecFailure as error:
                status = getattr(error, 'status', None) or getattr(error, 'status_code', None)
                if status != 415:
                    raise
        self.workspace.mkdir(parents=True, exist_ok=True)
        directory = Path(mkdtemp(prefix='request-', dir=self.workspace))
        dispatch: dict[str, Any] = {}
        retained = False
        primary = None
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
            if normalized_merge is not None:
                request['merge'] = normalized_merge
            (directory / 'request.json').write_text(
                json.dumps(request, ensure_ascii=False, allow_nan=False))
            primary = Path(replacements_spec['path'])
            active_request = request
            for attempt in range(4):
                try:
                    return self._request('/updates/run', active_request, dispatch=dispatch)
                except Exception as exc:
                    import httpx
                    if isinstance(exc, httpx.TransportError) and not isinstance(exc, httpx.TimeoutException) and not dispatch.get('submitted'):
                        if attempt < 3:
                            time.sleep(1.0 * (2 ** attempt))
                            attempt += 1
                            continue
                        raise
                    if not isinstance(exc, DocSpecFailure):
                        raise
                    msg = str(exc).lower()
                    if normalized_merge is not None and 'unknown field' in str(exc) and 'merge' in str(exc):
                        base_pin = self.release(dataset, base)
                        with self.source_batches(base_pin) as reader:
                            existing_table = pa.Table.from_batches(list(reader), schema=reader.schema)
                        incoming_table = table if isinstance(table, pa.Table) else pq.read_table(primary)
                        merged_table = apply_update_merge_spec(
                            existing_table,
                            incoming_table,
                            keys=list(keys),
                            merge_spec=normalized_merge,
                            include_unmatched_existing=False,
                        )
                        merged_path = directory / 'replacements.parquet'
                        _write_producer_parquet(merged_table, merged_path)
                        merged_digest = self.hash_input(merged_path)['digest']
                        active_request = {k: v for k, v in active_request.items() if k != 'merge'}
                        active_request['replacements'] = dict(path=str(merged_path), digest=merged_digest)
                        normalized_merge = None
                        (directory / 'request.json').write_text(
                            json.dumps(active_request, ensure_ascii=False, allow_nan=False))
                        primary = merged_path
                        dispatch.clear()
                        continue
                    transient = any(
                        token in msg
                        for token in (
                            'commit state is unknown',
                            'gateway',
                            'remote_unconfirmed',
                            '502',
                            '503',
                            '504',
                        )
                    )
                    if transient and attempt < 3:
                        time.sleep(1.0 * (2 ** attempt))
                        dispatch.clear()
                        continue
                    raise
        except BaseException as error:
            if dispatch.get('submitted') and not cleanup_safe(error):
                retained = True
                try:
                    entry = producer_input_entry(directory / 'request.json')
                    size = entry['bytes'] if entry is not None else None
                    setattr(error, 'retained_input', dict(
                        input=str(primary),
                        request=str(directory / 'request.json'),
                        bytes=size,
                        files=entry['files'] if entry is not None else [],
                    ))
                    if hasattr(error, 'add_note'):
                        error.add_note(
                            f'DocSpec producer inputs retained under {directory} ({size} bytes); '
                            f'exact replay request: {directory / "request.json"}'
                        )
                except OSError as diagnostic:
                    if hasattr(error, 'add_note'):
                        error.add_note(f'DocSpec producer directory retained at {directory}; '
                                       f'could not save its diagnostic: {diagnostic}')
            raise
        finally:
            if not retained:
                shutil.rmtree(directory)

    def request(self, path: str, request: Any) -> Any:
        """Submit one typed native request on an explicit route."""
        return self._request(path, request)

    def refresh(self, request: Any) -> Any:
        return self._request('/refreshes/run', request)

    def plan_refresh(self, request: Any) -> Any:
        return self._request('/refreshes/plan', request)

    def seal_generation(self, request: Any) -> Any:
        return self._request('/generations/seal', request)

    def capture_inputs(self, inputs: Any) -> Any:
        return self._request('/inputs/capture', inputs)

    def correct_dependencies(self, request: Any) -> Any:
        return self._request('/dependencies/corrections', request)

    def plan_schema(self, request: Any) -> Any:
        return self._request('/schemas/plan', request)

    def evolve_schema(self, request: Any) -> Any:
        return self._request('/schemas/run', request)

    def plan_backfill(self, request: Any) -> Any:
        return self._request('/backfills/plan', request)

    def backfill(self, request: Any) -> Any:
        return self._request('/backfills/run', request)

    def plan_continuous_backfill(self, request: Any) -> Any:
        return self._request('/plan-continuous-backfill', request)

    def continuous_backfill(self, request: Any) -> Any:
        return self._request('/continuous-backfill', request)

    def plan_evidence(self, request: Any) -> Any:
        return self._request('/receipts/plan', request)

    def update_evidence(self, request: Any) -> Any:
        return self._request('/receipts/run', request)

    def update_evidence_table(
        self,
        table: pa.Table | None = None,
        *,
        dataset: str,
        operation: str,
        definition: str,
        base: Any,
        replacements: Any = None,
        deletions: Any = None,
        return_plan: bool = False,
    ) -> Any:
        """Submit one ``EvidenceSpec`` with pre-persisted producer custody."""
        self.workspace.mkdir(parents=True, exist_ok=True)
        directory = Path(mkdtemp(prefix='request-', dir=self.workspace))
        dispatch: dict[str, Any] = {}
        retained = False
        primary = None
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
                    setattr(error, 'retained_input', dict(
                        input=str(primary),
                        request=str(directory / 'request.json'),
                        bytes=size,
                        files=entry['files'] if entry is not None else [],
                    ))
                    if hasattr(error, 'add_note'):
                        error.add_note(
                            f'DocSpec producer inputs retained under {directory} ({size} bytes); '
                            f'exact replay request: {directory / "request.json"}'
                        )
                except OSError as diagnostic:
                    if hasattr(error, 'add_note'):
                        error.add_note(f'DocSpec producer directory retained at {directory}; '
                                       f'could not save its diagnostic: {diagnostic}')
            raise
        finally:
            if not retained:
                shutil.rmtree(directory)

    def compare(self, before: Any, after: Any, *, group: str = 'source', identity: str = 'values', force_full: bool = False) -> Any:
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
    def changes_batches(
        self,
        before: Any,
        after: Any,
        *,
        group: str = 'source',
        identity: str = 'occurrences',
        force_full: bool = False,
    ) -> Generator[tuple[Any, pa.RecordBatchReader], None, None]:
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

                    def batches() -> Generator[pa.RecordBatch, None, None]:
                        for batch in reader:
                            yield batch
                        stream.finish()

                    with pa.RecordBatchReader.from_batches(reader.schema, batches()) as restored:
                        yield descriptor, restored
            finally:
                self._responses.discard(response)

    def read_changes(
        self,
        before: Any,
        after: Any,
        *,
        group: str = 'source',
        identity: str = 'occurrences',
        force_full: bool = False,
    ) -> dict[str, Any]:
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

    def _verify_pin(self, host: Host, release_path: str, pin: Any, deadline: float) -> None:
        pin_key = json.dumps(pin, sort_keys=True, separators=(',', ':'), default=str)
        cache_entry = (release_path, str(pin.get('id')), pin_key)
        if cache_entry in self._verified_pins:
            return
        if host.request('GET', release_path, deadline=deadline) != pin:
            raise ValueError('Native release differs from the selected exact pin')
        if len(self._verified_pins) < 8192:
            self._verified_pins.add(cache_entry)

    def read_keys(
        self,
        pin: Any,
        key: str,
        values: Sequence[Any],
        *,
        columns: Sequence[str] | None = None,
        schema: pa.Schema | None = None,
    ) -> pa.Table:
        """Stream only rows matching ``values`` on ``key`` from an exact release pin."""
        started = time.monotonic()
        deadline = started + self.timeout
        dataset, version = pin['dataset']['dataset'], pin['id']
        host = self._execution_host()
        release_path = f'/datasets/{quote(dataset, safe="")}/versions/{quote(version, safe="")}'
        self._verify_pin(host, release_path, pin, deadline)
        spec: dict[str, Any] = dict(key=key, values=[str(v) for v in values])
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

    def _read_pin_endpoint(self, pin: Any, suffix: str, *, schema: pa.Schema | None = None) -> pa.Table:
        started = time.monotonic()
        deadline = started + self.timeout
        dataset, version = pin['dataset']['dataset'], pin['id']
        host = self._execution_host()
        release_path = f'/datasets/{quote(dataset, safe="")}/versions/{quote(version, safe="")}'
        self._verify_pin(host, release_path, pin, deadline)
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

    def read_receipts(self, pin: Any, *, schema: pa.Schema | None = None) -> pa.Table:
        return self._read_pin_endpoint(pin, '/receipts', schema=schema)

    def read_evidence(self, pin: Any, *, schema: pa.Schema | None = None) -> pa.Table:
        return self._read_pin_endpoint(pin, '/evidence', schema=schema)

    def read_occurrences(self, pin: Any, *, schema: pa.Schema | None = None) -> pa.Table:
        return self._read_pin_endpoint(pin, '/occurrences', schema=schema)

    def export(
        self,
        request: Any,
        *,
        operation: str | None = None,
        source: Any = None,
        version: Any = None,
        channel: str = 'viewer',
        expected: Any = None,
        destination: Any = None,
        policy: Any = None,
        **policy_kwargs: Any,
    ) -> dict[str, Any]:
        if isinstance(request, str):
            return self.export_table(
                request,
                operation=operation,  # type: ignore[arg-type]
                source=source,
                version=version,
                channel=channel,
                expected=expected,
                destination=destination,
                policy=policy,
                **policy_kwargs,
            )
        return parse_export_pin(self._request('/exports/run', request))

    def export_table(
        self,
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
        """Submit one declarative ``ExportSpec`` and return its normalized ``ExportPin``."""
        spec = build_export_spec(
            dataset,
            operation=operation,
            source=source,
            version=version,
            channel=channel,
            expected=expected,
            destination=destination,
            policy=policy,
            **policy_kwargs,
        )
        return self.export(spec)

    def compact(
        self,
        request: Any,
        *,
        operation: str | None = None,
        version: Any = None,
        group: str = 'source',
        files: Sequence[str] = (),
        target_file_bytes: int = 64 * 1024 * 1024,
    ) -> Any:
        if isinstance(request, str):
            resolved_version = (
                version['dataset']['version']
                if isinstance(version, dict)
                else version
            )
            if not operation or not resolved_version:
                raise ValueError('compact(dataset, ...) requires operation and version')
            request = {
                'dataset': request,
                'operation': operation,
                'version': resolved_version,
                'group': group,
                'files': list(files or ()),
                'target_file_bytes': int(target_file_bytes),
            }
        return self._request('/compactions/run', request)

    def compact_table(
        self,
        dataset: str,
        *,
        operation: str,
        version: Any,
        group: str = 'source',
        files: Sequence[str] = (),
        target_file_bytes: int = 64 * 1024 * 1024,
    ) -> Any:
        return self.compact(
            dataset,
            operation=operation,
            version=version,
            group=group,
            files=files,
            target_file_bytes=target_file_bytes,
        )

    def compact_lifecycle(self, dataset: str) -> Any:
        return self._host_request(
            'POST', f'/datasets/{quote(dataset, safe="")}/lifecycle/compact')

    def latest_export(self, dataset: str, channel: str) -> Any:
        return self._host_request(
            'GET',
            f'/datasets/{quote(dataset, safe="")}/exports/channels/{quote(channel, safe="")}')

    def export_pin(self, dataset: str, operation: str) -> Any:
        return self._host_request(
            'GET', f'/datasets/{quote(dataset, safe="")}/exports/{quote(operation, safe="")}')

    def try_latest_export(self, dataset: str, channel: str) -> Any:
        try:
            return self.latest_export(dataset, channel)
        except DocSpecFailure as error:
            if error.code == 'no_export' or 'no_export' in error.stderr:
                return None
            raise

    def try_export_pin(self, dataset: str, operation: str) -> Any:
        try:
            return self.export_pin(dataset, operation)
        except DocSpecFailure as error:
            if error.code == 'no_export' or 'no_export' in error.stderr:
                return None
            raise

    def read_arrow(
        self,
        pin: Any,
        group: str = 'source',
        *,
        columns: Sequence[str] | None = None,
        schema: pa.Schema | None = None,
    ) -> pa.Table:
        """Read one exact retained group as an Arrow table."""
        if group == 'source':
            with self.source_batches(pin, schema=schema, columns=columns) as batches:
                return pa.Table.from_batches(list(batches), schema=batches.schema)
        started = time.monotonic()
        deadline = started + self.timeout
        dataset, version = pin['dataset']['dataset'], pin['id']
        host = self._execution_host()
        release_path = f'/datasets/{quote(dataset, safe="")}/versions/{quote(version, safe="")}'
        self._verify_pin(host, release_path, pin, deadline)
        projected_cols = list(columns) if columns is not None else None
        if projected_cols is not None and not projected_cols:
            raise ValueError('Projected column list must not be empty')
        query = (
            '?columns=' + ','.join(quote(col, safe='') for col in projected_cols)
            if projected_cols
            else ''
        )
        path = f'{release_path}/arrow/{quote(group, safe="")}{query}'
        target_schema = (
            pa.schema([schema.field(name) for name in projected_cols], metadata=schema.metadata)
            if (schema is not None and projected_cols is not None)
            else schema
        )
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
                try:
                    with ArrowResponse(response, deadline=deadline) as stream, \
                            pa.ipc.open_stream(stream) as reader:
                        table = reader.read_all()
                        stream.finish()
                except (pa.ArrowInvalid, pa.ArrowIOError) as exc:
                    diagnostic = json.dumps({
                        'code': 'request_timeout',
                        'message': f'DocSpec Arrow IPC stream truncated: {exc}',
                        'pre_admission': False,
                    })
                    cmd = [response.request.method, response.request.url.path]
                    err = DocSpecFailure(cmd, subprocess.CompletedProcess(cmd, 504, stderr=diagnostic))
                    err.status_code = 504
                    err.code = 'request_timeout'
                    err.pre_admission = False
                    raise err from exc
                return table if target_schema is None else table.cast(target_schema, safe=True)
            finally:
                self._responses.discard(response)

    def plan(self, request: Any) -> Any:
        return self._request('/plan', request)

    def update(self, request: Any) -> Any:
        return self._request('/updates/run', request)

    def plan_update(self, request: Any) -> Any:
        return self._request('/updates/plan', request)

    def latest(self, dataset: str) -> Any:
        return self._host_request('GET', f'/datasets/{quote(dataset, safe="")}/latest')

    def try_latest(self, dataset: str) -> Any:
        try:
            return self.latest(dataset)
        except DocSpecFailure as error:
            if getattr(error, 'status_code', None) == 404 or error.code == 'no_release' or 'no_release' in error.stderr:
                return None
            raise

    def release(self, dataset: str, operation: str) -> Any:
        return self._host_request('GET',
            f'/datasets/{quote(dataset, safe="")}/versions/{quote(operation, safe="")}')

    def inspect(self, dataset: str) -> Any:
        return self._host_request('GET', f'/datasets/{quote(dataset, safe="")}')

    def inspect_retention(self, request: Any) -> Any:
        return self._request('/retention/inspect', request)

    def plan_removal(self, request: Any) -> Any:
        return self._request('/retention/removal/plan', request)

    @contextmanager
    def source_batches(
        self,
        pin: Any,
        *,
        schema: pa.Schema | None = None,
        columns: Sequence[str] | None = None,
    ) -> Generator[pa.RecordBatchReader, None, None]:
        """Stream one exact pin, retaining HTTP custody for the reader's lifetime."""
        started = time.monotonic()
        deadline = started + self.timeout
        dataset, version = pin['dataset']['dataset'], pin['id']
        host = self._execution_host()
        release_path = f'/datasets/{quote(dataset, safe="")}/versions/{quote(version, safe="")}'
        self._verify_pin(host, release_path, pin, deadline)
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
                    if target_schema is not None:
                        application_schema(effective_reader_schema, expected_schema=target_schema)

                    def batches() -> Generator[pa.RecordBatch, None, None]:
                        for batch in reader:
                            if extra_supplied:
                                batch = pa.RecordBatch.from_arrays(
                                    [batch.column(reader.schema.get_field_index(f.name)) for f in effective_reader_schema],
                                    schema=effective_reader_schema,
                                )
                            if target_schema is not None:
                                tbl = restore_application_schema(
                                    pa.Table.from_batches([batch], schema=batch.schema),
                                    expected_schema=target_schema,
                                )
                                yield from tbl.to_batches()
                            else:
                                yield batch
                        stream.finish()

                    with pa.RecordBatchReader.from_batches(
                            reader.schema if target_schema is None else target_schema, batches()) as restored:
                        yield restored
            finally:
                self._responses.discard(response)
