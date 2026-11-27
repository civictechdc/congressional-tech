"""Additive zero-copy DDK + Iceberg v2 publication sidecar bound to BodyTextSSOT (`ct-0a35`)."""
from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from copy import deepcopy
from hashlib import sha256
import importlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile
from typing import Any
from urllib.parse import urlsplit

from . import archive_odcs, body_text_export, client as publication_client

DEFAULT_PUBLIC_ORIGIN = 'https://congressional-data.spicygov.ai'
DEFAULT_BUCKET = 'congressional-tech-raw'
DEFAULT_SIDECAR_PREFIX = 'ddk-catalogs/congressional-tech'
PUBLIC_RELEASE_PREFIX = 'viewer-publications/releases'
DEFAULT_DATASET = 'congressional-tech'
DEFAULT_CATALOG_ID = 'urn:congressional-tech:catalog:archive'
DEFAULT_PROJECT_ID = 'urn:congressional-tech:project:archive'
DEFAULT_AUTHORITY_ID = 'urn:congressional-tech:authority:archive'
DEFAULT_SCHEMA_VERSION = 'ddk-external-generation/v1'
CT_0A35_TICKET = 'ct-0a35'
SERENEDB_ITERATOR_SYMBOL = 'viewer_publication.body_text_ssot.BodyTextSSOT.iter_serenedb_documents'
_HEX64_RE = re.compile(r'^[0-9a-f]{64}$')
_HEX32_RE = re.compile(r'^[0-9a-f]{32}$')
_SAFE_PART_RE = re.compile(r'^[A-Za-z0-9._-]+$')
_RESERVED_ARCHIVE_PREFIXES = ('viewer-publications', 'derived')
_SENTINEL = object()

DOCUMENTED_LIVE_SQL_DRIFT: dict[str, dict[str, Any]] = {
    'organization_ids': {
        'kind': 'extra_columns',
        'extra_columns': {'evidence': 'string'},
        'note': archive_odcs.LIVE_PARQUET_PARITY_NOTES['producerSqlDriftInLiveRelease']['organization_ids']['note'],
    },
    'witness_organizations': {
        'kind': 'extra_columns',
        'extra_columns': {'method': 'string', 'score': 'float64', 'evidence': 'string'},
        'note': archive_odcs.LIVE_PARQUET_PARITY_NOTES['producerSqlDriftInLiveRelease']['witness_organizations']['note'],
    },
    'roll_call_votes': {
        'kind': 'extra_struct_fields',
        'field': 'documents',
        'extra_struct_fields': {'nomination_id': 'string'},
        'note': archive_odcs.LIVE_PARQUET_PARITY_NOTES['producerSqlDriftInLiveRelease']['roll_call_votes']['note'],
    },
}


class SchemaDriftError(ValueError):
    """Raised when observed Parquet schema drifts outside canonical contracts and documented SQL drift."""


class _FallbackCatalogError(RuntimeError):
    """Fallback error matching ``ddk.catalog_access.CatalogError`` when ``ddk`` is not installed."""

    def __init__(self, code: str, message: str):
        super().__init__(f'{code}: {message}')
        self.code = code
        self.message = message


def _catalog_error_cls() -> type[Exception]:
    try:
        mod = importlib.import_module('ddk.catalog_access')
        err = getattr(mod, 'CatalogError', None)
        if isinstance(err, type) and issubclass(err, Exception):
            return err
    except ImportError:
        pass
    return _FallbackCatalogError


def _load_ddk_publication() -> Any:
    """Lazily import ``ddk.publication`` so CT offline environments need no ``ddk`` package."""
    try:
        mod = importlib.import_module('ddk.publication')
    except ImportError as exc:
        raise RuntimeError(
            'ddk.publication is unavailable; install data-design-kit or add its src directory to PYTHONPATH'
        ) from exc
    if not hasattr(mod, 'build_external_generation_bundle'):
        raise RuntimeError('Imported ddk.publication does not expose build_external_generation_bundle')
    return mod


def ddk_bridge_available() -> bool:
    """Return True when ``ddk.publication`` external-generation bridge APIs are importable."""
    try:
        _load_ddk_publication()
    except RuntimeError:
        return False
    return True


def _safe_rel_path(value: str, *, label: str = 'key') -> str:
    if not isinstance(value, str) or not value or value.startswith('/') or '\\' in value:
        raise ValueError(f'Unsafe {label}: {value!r}')
    parts = value.split('/')
    if any(not p or p in {'.', '..'} or not _SAFE_PART_RE.fullmatch(p) for p in parts):
        raise ValueError(f'Unsafe {label} segment in {value!r}')
    return '/'.join(parts)


def validate_public_origin(origin: str, *, allow_insecure_http: bool = False) -> str:
    """Validate and normalize the public HTTPS origin (or loopback HTTP when explicitly permitted)."""
    if not isinstance(origin, str) or not origin.strip():
        raise ValueError(f'public_origin must be a nonempty URL, got {origin!r}')
    raw = origin.strip().rstrip('/')
    parts = urlsplit(raw)
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError(f'public_origin must not contain credentials, query, or fragment: {origin!r}')
    if not parts.netloc:
        raise ValueError(f'public_origin requires host: {origin!r}')
    scheme = parts.scheme.lower()
    if scheme == 'https':
        return raw
    if scheme == 'http' and allow_insecure_http:
        host = (parts.hostname or '').lower()
        if host in {'127.0.0.1', 'localhost', '::1'}:
            return raw
        raise ValueError(f'allow_insecure_http only permits loopback origins, got {origin!r}')
    raise ValueError(f'public_origin must use https (or loopback http with allow_insecure_http=True): {origin!r}')


def validate_sidecar_prefix(prefix: str) -> str:
    """Ensure sidecar prefix is safe and isolated from immutable archive releases and body_text SSOT."""
    clean = _safe_rel_path(prefix.strip('/'), label='sidecar_prefix')
    top = clean.split('/', 1)[0]
    if top in _RESERVED_ARCHIVE_PREFIXES:
        raise ValueError(
            f'sidecar_prefix {clean!r} must be isolated outside reserved prefixes {_RESERVED_ARCHIVE_PREFIXES!r}'
        )
    return clean


def _clean_etag(etag: Any) -> str | None:
    if etag is None:
        return None
    text = str(etag).strip()
    if text.startswith('W/'):
        text = text[2:].strip()
    text = text.strip('"')
    return text or None


def _http_status_from_client_error(exc: Exception) -> int | None:
    resp = getattr(exc, 'response', None)
    if not isinstance(resp, Mapping):
        return None
    meta = resp.get('ResponseMetadata')
    if isinstance(meta, Mapping) and isinstance(meta.get('HTTPStatusCode'), int):
        return meta['HTTPStatusCode']
    err = resp.get('Error')
    if isinstance(err, Mapping):
        code = str(err.get('Code', ''))
        if code in {'404', 'NoSuchKey', 'NotFound'}:
            return 404
        if code in {'412', 'PreconditionFailed', 'ConditionalRequestConflict'}:
            return 412
    return None


class _BotoSidecarStorage:
    """DDK ``ObjectStoragePort`` adapter over a boto3 client enforcing zero ``.parquet`` PUTs and prefix isolation."""

    def __init__(
        self,
        client: Any,
        *,
        bucket: str,
        sidecar_prefix: str = DEFAULT_SIDECAR_PREFIX,
        pointer_key: str | None = None,
        require_single_attempt: bool = True,
    ):
        if require_single_attempt:
            publication_client.require_publication_client(client)
        if not callable(getattr(client, 'head_object', None)):
            raise TypeError('S3/R2 publication client requires head_object')
        if not isinstance(bucket, str) or not bucket.strip():
            raise ValueError(f'Invalid bucket: {bucket!r}')
        self.client = client
        self.bucket = bucket.strip()
        self.sidecar_prefix = validate_sidecar_prefix(sidecar_prefix)
        self.pointer_key = _safe_rel_path(pointer_key, label='pointer_key') if pointer_key else f'{self.sidecar_prefix}/current.json'
        self.put_keys: list[str] = []

    def _error(self, code: str, message: str) -> Exception:
        return _catalog_error_cls()(code, message)

    def head_object(self, key: str) -> dict[str, Any]:
        safe_key = _safe_rel_path(key)
        try:
            resp = self.client.head_object(Bucket=self.bucket, Key=safe_key)
        except Exception as exc:
            if _http_status_from_client_error(exc) == 404:
                raise self._error('CATALOG-OBJECT-MISSING', f'Remote object missing: {safe_key}') from exc
            raise
        return {
            'key': safe_key,
            'etag': _clean_etag(resp.get('ETag')),
            'size': resp.get('ContentLength'),
            'contentType': resp.get('ContentType'),
        }

    def get_bytes(
        self,
        key: str,
        *,
        byte_range: tuple[int, int] | None = None,
        if_match: str | None = None,
    ) -> bytes:
        safe_key = _safe_rel_path(key)
        kwargs: dict[str, Any] = {'Bucket': self.bucket, 'Key': safe_key}
        if byte_range is not None:
            start, end = byte_range
            if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end < start:
                raise ValueError(f'Invalid byte_range for {safe_key!r}: {byte_range!r}')
            kwargs['Range'] = f'bytes={start}-{end}'
        if if_match is not None:
            kwargs['IfMatch'] = _clean_etag(if_match) or if_match
        try:
            resp = self.client.get_object(**kwargs)
        except Exception as exc:
            status = _http_status_from_client_error(exc)
            if status == 404:
                raise self._error('CATALOG-OBJECT-MISSING', f'Remote object missing: {safe_key}') from exc
            if status == 412:
                raise self._error('CATALOG-UPSTREAM-MUTATED', f'Precondition failed reading {safe_key}') from exc
            raise
        body = resp['Body']
        try:
            return body.read()
        finally:
            close = getattr(body, 'close', None)
            if callable(close):
                close()

    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str = 'application/octet-stream',
        if_match: str | None = None,
        if_none_match: bool = False,
    ) -> dict[str, Any]:
        safe_key = _safe_rel_path(key)
        if safe_key.lower().endswith('.parquet'):
            raise ValueError(f'Zero-copy sidecar forbids writing Parquet objects: {safe_key!r}')
        if not safe_key.startswith(f'{self.sidecar_prefix}/'):
            prefix_slash = f'{self.sidecar_prefix}/'
            raise ValueError(
                f'Sidecar storage refuses write outside isolated prefix {prefix_slash!r}: {safe_key!r}'
            )
        if if_match is not None and if_none_match:
            raise ValueError('Cannot specify both if_match and if_none_match')
        payload = bytes(data)
        cache_control = 'no-store' if safe_key == self.pointer_key else 'public,max-age=31536000,immutable'
        kwargs: dict[str, Any] = {
            'Bucket': self.bucket,
            'Key': safe_key,
            'Body': payload,
            'ContentType': content_type,
            'CacheControl': cache_control,
        }
        if if_match is not None:
            kwargs['IfMatch'] = _clean_etag(if_match) or if_match
        if if_none_match:
            kwargs['IfNoneMatch'] = '*'
        try:
            resp = self.client.put_object(**kwargs)
        except Exception as exc:
            if _http_status_from_client_error(exc) == 412:
                raise self._error('CATALOG-REMOTE-CONFLICT', f'CAS precondition failed writing {safe_key}') from exc
            raise
        self.put_keys.append(safe_key)
        return {
            'key': safe_key,
            'etag': _clean_etag(resp.get('ETag')),
            'sha256': sha256(payload).hexdigest(),
            'bytes': len(payload),
        }


def _load_json_input(source: Mapping[str, Any] | Path | str, *, label: str) -> dict[str, Any]:
    if isinstance(source, Mapping):
        return deepcopy(dict(source))
    if isinstance(source, (Path, str)):
        path = Path(source)
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError(f'{label} at {path} must be a JSON object')
        return data
    raise TypeError(f'{label} must be a mapping or file path, got {type(source).__name__}')


def resolve_release_manifest(
    manifest_or_dir: Mapping[str, Any] | Path | str,
    *,
    release_id: str | None = None,
) -> tuple[dict[str, Any], Path | None]:
    """Load an archive release ``manifest.json`` from a directory, file path, or mapping."""
    release_dir: Path | None = None
    if isinstance(manifest_or_dir, (Path, str)):
        p = Path(manifest_or_dir)
        if p.is_dir():
            release_dir = p
            manifest_path = p / 'manifest.json'
        else:
            manifest_path = p
            release_dir = p.parent
        manifest = _load_json_input(manifest_path, label='manifest.json')
    else:
        manifest = _load_json_input(manifest_or_dir, label='manifest')

    m_release_id = manifest.get('release_id')
    if not isinstance(m_release_id, str) or not _HEX64_RE.fullmatch(m_release_id):
        raise ValueError(f'Manifest requires 64-hex release_id, got {m_release_id!r}')
    if release_id is not None and release_id != m_release_id:
        raise ValueError(f'Manifest release_id {m_release_id!r} does not match expected {release_id!r}')
    files = manifest.get('files')
    if not isinstance(files, list) or not files:
        raise ValueError('Manifest requires a nonempty files list')
    return manifest, release_dir


def detect_capture_profile_v2(
    manifest: Mapping[str, Any],
    *,
    release_dir: Path | None = None,
    capture_profile: Mapping[str, Any] | Path | str | None = None,
    include_capture_eligibility: bool | None = None,
    storage: Any | None = None,
) -> dict[str, Any]:
    """Detect whether ``capture_profile.json`` v2 applies (`url_state` capture eligibility extension)."""
    if include_capture_eligibility is not None:
        enabled = bool(include_capture_eligibility)
        return {
            'version': 2 if enabled else None,
            'include_capture_eligibility': enabled,
            'source': 'explicit',
        }

    profile_obj: dict[str, Any] | None = None
    source: str | None = None
    if capture_profile is not None:
        profile_obj = _load_json_input(capture_profile, label='capture_profile')
        source = 'argument'
    elif isinstance(manifest.get('capture_profile'), Mapping):
        profile_obj = deepcopy(dict(manifest['capture_profile']))
        source = 'manifest'
    elif release_dir is not None and (release_dir / 'capture_profile.json').is_file():
        profile_obj = _load_json_input(release_dir / 'capture_profile.json', label='capture_profile.json')
        source = str(release_dir / 'capture_profile.json')
    elif storage is not None and callable(getattr(storage, 'get_bytes', None)):
        key = f'{PUBLIC_RELEASE_PREFIX}/{manifest["release_id"]}/capture_profile.json'
        try:
            raw = storage.get_bytes(key)
        except Exception:
            raw = None
        if raw is not None:
            parsed = json.loads(raw.decode('utf-8'))
            if isinstance(parsed, dict):
                profile_obj = parsed
                source = f'storage:{key}'

    version = profile_obj.get('version') if isinstance(profile_obj, dict) else None
    enabled = version == 2
    return {
        'version': version,
        'include_capture_eligibility': enabled,
        'source': source,
        'profile': profile_obj,
    }


def _find_manifest_detail_entry(manifest: Mapping[str, Any]) -> dict[str, Any] | None:
    for entry in manifest.get('files', []):
        if isinstance(entry, Mapping) and entry.get('name') == 'detail.parquet':
            return dict(entry)
    return None


def validate_body_text_ssot_binding(
    body_text_pointer: Mapping[str, Any] | Path | str | None,
    *,
    release_id: str,
    manifest: Mapping[str, Any],
    public_origin: str = DEFAULT_PUBLIC_ORIGIN,
    pointer_key: str = body_text_export.load_definition()['pointer'],
    storage: Any | None = None,
    verify_storage_object: bool = False,
) -> dict[str, Any] | None:
    """Validate release binding for a ``BodyTextSSOT`` pointer (`ct-0a35`) without copying its Parquet."""
    if body_text_pointer is None:
        return None
    if not _HEX64_RE.fullmatch(release_id):
        raise ValueError(f'Invalid release_id for BodyTextSSOT binding: {release_id!r}')

    if isinstance(body_text_pointer, Mapping):
        pointer = deepcopy(dict(body_text_pointer))
        resolved_pointer_ref = pointer_key
    elif isinstance(body_text_pointer, (Path, str)):
        p = Path(body_text_pointer)
        if p.is_file():
            pointer = _load_json_input(p, label='body_text pointer')
            resolved_pointer_ref = pointer_key
        elif isinstance(body_text_pointer, str) and storage is not None and callable(getattr(storage, 'get_bytes', None)):
            raw_key = _safe_rel_path(body_text_pointer, label='body_text_pointer')
            pointer = json.loads(storage.get_bytes(raw_key).decode('utf-8'))
            resolved_pointer_ref = raw_key
        else:
            raise FileNotFoundError(f'body_text pointer file not found: {body_text_pointer!r}')
    else:
        raise TypeError(f'body_text_pointer must be a mapping or file path, got {type(body_text_pointer).__name__}')

    if pointer.get('release_id') != release_id:
        raise ValueError(
            f'BodyTextSSOT pointer release_id {pointer.get("release_id")!r} does not bind to release {release_id!r}'
        )

    digest = pointer.get('sha256')
    key = pointer.get('key')
    byte_count = pointer.get('bytes')
    if not isinstance(digest, str) or not _HEX64_RE.fullmatch(digest):
        raise ValueError(f'BodyTextSSOT pointer requires 64-hex sha256, got {digest!r}')

    definition = body_text_export.load_definition()
    expected_key = f"{definition['prefix']}{digest}.parquet"
    if key != expected_key:
        raise ValueError(f'BodyTextSSOT pointer key {key!r} must equal {expected_key!r}')
    _safe_rel_path(key, label='body_text key')

    if type(byte_count) is not int or byte_count < 0:
        raise ValueError(f'BodyTextSSOT pointer bytes must be non-negative int, got {byte_count!r}')
    rows = pointer.get('rows')
    if rows is not None and (type(rows) is not int or rows < 0):
        raise ValueError(f'BodyTextSSOT pointer rows must be non-negative int, got {rows!r}')
    footer_sha256 = pointer.get('footer_sha256')
    if footer_sha256 is not None and (not isinstance(footer_sha256, str) or not _HEX64_RE.fullmatch(footer_sha256)):
        raise ValueError(f'BodyTextSSOT pointer footer_sha256 must be 64-hex, got {footer_sha256!r}')

    detail_entry = _find_manifest_detail_entry(manifest)
    if detail_entry is not None:
        expected_detail = {'sha256': detail_entry['sha256'], 'size': detail_entry['size']}
        if pointer.get('detail') != expected_detail:
            raise ValueError(
                f'BodyTextSSOT detail pin {pointer.get("detail")!r} disagrees with manifest detail.parquet {expected_detail!r}'
            )

    if verify_storage_object and storage is not None and callable(getattr(storage, 'head_object', None)):
        head = storage.head_object(key)
        if head.get('size') != byte_count:
            raise ValueError(f'BodyTextSSOT object {key} size {head.get("size")!r} disagrees with pointer {byte_count!r}')

    clean_origin = public_origin.rstrip('/')
    return {
        'ticket': CT_0A35_TICKET,
        'version': pointer.get('version'),
        'pointer_key': resolved_pointer_ref,
        'key': key,
        'public_url': f'{clean_origin}/{key}',
        'sha256': digest,
        'bytes': byte_count,
        'rows': rows,
        'footer_sha256': footer_sha256,
        'release_id': release_id,
        'detail': deepcopy(pointer.get('detail')),
        'selection': deepcopy(pointer.get('selection')),
        'coverage': deepcopy(pointer.get('coverage')),
        'serenedb': {
            'ticket': CT_0A35_TICKET,
            'release_id': release_id,
            'iterator': SERENEDB_ITERATOR_SYMBOL,
            'body_text_key': key,
            'body_text_sha256': digest,
            'body_text_url': f'{clean_origin}/{key}',
            'zero_copy_sidecar_only': True,
        },
    }


def _import_pyarrow() -> Any:
    import pyarrow as pa
    return pa


def _unwrap_dictionary_type(arrow_type: Any, pa: Any) -> Any:
    while pa.types.is_dictionary(arrow_type):
        arrow_type = arrow_type.value_type
    return arrow_type


def _matches_documented_arrow_type(arrow_type: Any, expected_kind: str, pa: Any) -> bool:
    unwrapped = _unwrap_dictionary_type(arrow_type, pa)
    if expected_kind == 'string':
        return bool(pa.types.is_string(unwrapped) or pa.types.is_large_string(unwrapped))
    if expected_kind == 'float64':
        return bool(pa.types.is_float64(unwrapped))
    return False


def _odcs_type_for_documented_kind(expected_kind: str) -> dict[str, str]:
    if expected_kind == 'string':
        return {'logicalType': 'string', 'physicalType': 'Utf8'}
    if expected_kind == 'float64':
        return {'logicalType': 'number', 'physicalType': 'double'}
    raise ValueError(f'Unsupported documented drift kind: {expected_kind!r}')


def _read_parquet_arrow_schema(
    parquet_source: Any,
    *,
    storage: Any | None = None,
    remote_key: str | None = None,
) -> Any:
    import io
    pa = _import_pyarrow()
    import pyarrow.parquet as pq

    if hasattr(parquet_source, 'names') and hasattr(parquet_source, 'field'):
        return parquet_source
    if isinstance(parquet_source, (Path, str)) and Path(parquet_source).is_file():
        return pq.read_schema(Path(parquet_source))
    if storage is not None and remote_key is not None and callable(getattr(storage, 'get_bytes', None)):
        raw = storage.get_bytes(remote_key)
        return pq.read_schema(io.BytesIO(raw))
    raise FileNotFoundError(f'Cannot read Parquet schema from {parquet_source!r}')


def _build_drift_annotated_contract(
    canonical_contract: Mapping[str, Any],
    *,
    table_name: str,
    divergences: Sequence[dict[str, Any]],
    canonical_issues: Sequence[str],
) -> dict[str, Any]:
    """Create a deep-copied ODCS contract annotated for documented SQL drift without mutating canonical."""
    contract = deepcopy(dict(canonical_contract))
    schema_obj = contract['schema'][0]
    props = schema_obj.setdefault('properties', [])
    spec = DOCUMENTED_LIVE_SQL_DRIFT[table_name]

    if spec['kind'] == 'extra_columns':
        existing = {p.get('name') for p in props if isinstance(p, Mapping)}
        for div in divergences:
            col = div['column']
            if col in existing:
                continue
            props.append({
                'name': col,
                'required': False,
                **_odcs_type_for_documented_kind(div['type']),
                'description': f'Documented live producer SQL drift column ({spec["note"]})',
                'customProperties': [
                    {'property': 'documentedProducerSqlDrift', 'value': True},
                    {'property': 'absentFromCanonicalReleaseSchema', 'value': True},
                ],
            })
    elif spec['kind'] == 'extra_struct_fields':
        target_field = spec['field']
        for prop in props:
            if not isinstance(prop, dict) or prop.get('name') != target_field:
                continue
            items = prop.setdefault('items', {})
            nested_props = items.setdefault('properties', [])
            existing_nested = {np.get('name') for np in nested_props if isinstance(np, Mapping)}
            for div in divergences:
                sub = div['struct_field']
                if sub in existing_nested:
                    continue
                nested_props.append({
                    'name': sub,
                    'required': False,
                    **_odcs_type_for_documented_kind(div['type']),
                    'description': f'Documented live producer SQL drift struct field ({spec["note"]})',
                    'customProperties': [
                        {'property': 'documentedProducerSqlDrift', 'value': True},
                        {'property': 'absentFromCanonicalReleaseSchema', 'value': True},
                    ],
                })

    custom = schema_obj.setdefault('customProperties', [])
    if not isinstance(custom, list):
        custom = []
        schema_obj['customProperties'] = custom
    custom.extend([
        {'property': 'canonicalContractParity', 'value': 'divergent_documented_sql_extra_columns'},
        {'property': 'documentedProducerSqlDrift', 'value': list(divergences)},
        {'property': 'canonicalParityIssues', 'value': list(canonical_issues)},
    ])
    return contract


def _schema_object_from_contract(contract: Mapping[str, Any], table_name: str | None = None) -> dict[str, Any]:
    schemas = contract.get('schema')
    if not isinstance(schemas, list) or not schemas:
        raise ValueError('ODCS contract must define nonempty schema list')
    if table_name is not None:
        for item in schemas:
            if isinstance(item, Mapping) and item.get('name') == table_name:
                return dict(item)
    return dict(schemas[0])


def inspect_table_schema_parity(
    table_name: str,
    actual_source_or_schema: Any,
    canonical_contract: Mapping[str, Any],
    *,
    storage: Any | None = None,
    remote_key: str | None = None,
) -> dict[str, Any]:
    """Validate Parquet schema parity against canonical ODCS contract and handle the 3 documented SQL drifts."""
    schema_obj = _schema_object_from_contract(canonical_contract, table_name)
    pa = _import_pyarrow()
    actual_schema = _read_parquet_arrow_schema(actual_source_or_schema, storage=storage, remote_key=remote_key)

    canonical_issues = archive_odcs.compare_parquet_schema_parity(
        schema_obj,
        actual_schema,
        check_order=False,
        check_nullability=False,
        normalize_arrow_encodings=True,
    )
    if not canonical_issues:
        return {
            'table_name': table_name,
            'status': 'passed',
            'canonical_parity_passed': True,
            'canonical_issues': [],
            'documented_divergences': [],
            'contract_for_sidecar': deepcopy(dict(canonical_contract)),
        }

    drift_spec = DOCUMENTED_LIVE_SQL_DRIFT.get(table_name)
    if drift_spec is None:
        raise SchemaDriftError(
            f'Unexpected Parquet schema drift on {table_name!r}: {"; ".join(canonical_issues)}'
        )

    expected_schema = archive_odcs.odcs_object_to_arrow_schema(schema_obj, pa=pa)
    observed_divergences: list[dict[str, Any]] = []

    if drift_spec['kind'] == 'extra_columns':
        doc_cols = drift_spec['extra_columns']
        expected_names = set(expected_schema.names)
        actual_names = [f.name for f in actual_schema]
        extra_names = [name for name in actual_names if name not in expected_names]
        unexpected_extra = [name for name in extra_names if name not in doc_cols]
        if unexpected_extra or not extra_names:
            raise SchemaDriftError(
                f'Unexpected Parquet schema drift on {table_name!r}: {"; ".join(canonical_issues)}'
            )
        for name in extra_names:
            field_type = actual_schema.field(name).type
            expected_kind = doc_cols[name]
            if not _matches_documented_arrow_type(field_type, expected_kind, pa):
                raise SchemaDriftError(
                    f'Documented SQL drift column {table_name}.{name} has unexpected Arrow type {field_type!r} (expected {expected_kind})'
                )
            observed_divergences.append({
                'table_name': table_name,
                'column': name,
                'type': expected_kind,
                'observed_arrow_type': str(field_type),
                'source': 'producerSqlDriftInLiveRelease',
                'note': drift_spec['note'],
            })
        stripped_schema = pa.schema([f for f in actual_schema if f.name not in set(extra_names)])

    elif drift_spec['kind'] == 'extra_struct_fields':
        target_field = drift_spec['field']
        doc_subfields = drift_spec['extra_struct_fields']
        if target_field not in actual_schema.names:
            raise SchemaDriftError(
                f'Unexpected Parquet schema drift on {table_name!r}: missing {target_field!r}'
            )
        idx = actual_schema.get_field_index(target_field)
        list_field = actual_schema.field(idx)
        list_type = _unwrap_dictionary_type(list_field.type, pa)
        if not (pa.types.is_list(list_type) or pa.types.is_large_list(list_type)):
            raise SchemaDriftError(
                f'Unexpected Parquet schema drift on {table_name}.{target_field}: expected list, got {list_field.type!r}'
            )
        elem_field = list_type.value_field
        elem_type = elem_field.type
        if not pa.types.is_struct(elem_type):
            raise SchemaDriftError(
                f'Unexpected Parquet schema drift on {table_name}.{target_field}[]: expected struct, got {elem_type!r}'
            )
        extra_sub = [sf for sf in elem_type if sf.name in doc_subfields]
        if not extra_sub:
            raise SchemaDriftError(
                f'Unexpected Parquet schema drift on {table_name!r}: {"; ".join(canonical_issues)}'
            )
        for sf in extra_sub:
            expected_kind = doc_subfields[sf.name]
            if not _matches_documented_arrow_type(sf.type, expected_kind, pa):
                raise SchemaDriftError(
                    f'Documented SQL drift field {table_name}.{target_field}[].{sf.name} has unexpected Arrow type {sf.type!r}'
                )
            observed_divergences.append({
                'table_name': table_name,
                'field': f'{target_field}[]',
                'struct_field': sf.name,
                'type': expected_kind,
                'observed_arrow_type': str(sf.type),
                'source': 'producerSqlDriftInLiveRelease',
                'note': drift_spec['note'],
            })
        stripped_struct = pa.struct([sf for sf in elem_type if sf.name not in doc_subfields])
        stripped_elem = pa.field(elem_field.name, stripped_struct, nullable=elem_field.nullable)
        stripped_list_type = pa.large_list(stripped_elem) if pa.types.is_large_list(list_type) else pa.list_(stripped_elem)
        stripped_fields = [
            pa.field(f.name, stripped_list_type, nullable=f.nullable) if i == idx else f
            for i, f in enumerate(actual_schema)
        ]
        stripped_schema = pa.schema(stripped_fields)
    else:
        raise SchemaDriftError(f'Unsupported drift kind on {table_name!r}')

    remaining_issues = archive_odcs.compare_parquet_schema_parity(
        schema_obj,
        stripped_schema,
        check_order=False,
        check_nullability=False,
        normalize_arrow_encodings=True,
    )
    if remaining_issues:
        raise SchemaDriftError(
            f'Unexpected Parquet schema drift on {table_name!r} beyond documented SQL drift: {"; ".join(remaining_issues)}'
        )

    adjusted_contract = _build_drift_annotated_contract(
        canonical_contract,
        table_name=table_name,
        divergences=observed_divergences,
        canonical_issues=canonical_issues,
    )
    return {
        'table_name': table_name,
        'status': 'documented_sql_drift',
        'canonical_parity_passed': False,
        'canonical_issues': list(canonical_issues),
        'documented_divergences': observed_divergences,
        'contract_for_sidecar': adjusted_contract,
    }


def _format_semver_version(raw: Any) -> str:
    if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
        return f'{raw}.0.0'
    if isinstance(raw, str):
        text = raw.strip()
        if re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:[-+][0-9A-Za-z.-]+)?', text):
            return text
        if text.isdigit():
            return f'{int(text)}.0.0'
    return '1.0.0'


def _manifest_table_name(entry: Mapping[str, Any], canonical_tables: Mapping[str, Any]) -> tuple[str, str] | None:
    filename = str(entry.get('name') or '')
    _safe_rel_path(filename, label='manifest file name')
    if not filename.endswith('.parquet'):
        return None
    if filename == 'export.parquet':
        raise ValueError('BodyTextSSOT export.parquet must not be packaged as a regular archive table')
    explicit = entry.get('table_name') or entry.get('table')
    if isinstance(explicit, str) and explicit:
        tname = explicit
    else:
        tname = PurePosixPath(filename).stem
    if tname not in canonical_tables:
        raise SchemaDriftError(f'Manifest Parquet object {filename!r} (table {tname!r}) has no canonical ODCS contract')
    return tname, filename


def _normalize_port_alias(table_name: str) -> str:
    return re.sub(r'[^a-z0-9-]+', '-', table_name.lower()).strip('-')


def _build_odps_product(
    *,
    release_id: str,
    table_contracts: Sequence[tuple[str, Mapping[str, Any]]],
    schema_version: Any,
    capture_profile_version: int | None,
    include_capture_eligibility: bool,
    body_text_binding: Mapping[str, Any] | None,
    parity_summary: Mapping[str, Any],
    public_origin: str,
    sidecar_prefix: str,
) -> dict[str, Any]:
    output_ports = [
        {
            'name': _normalize_port_alias(tname),
            'version': str(contract.get('version') or '1.0.0'),
            'contractId': str(contract.get('id') or f'urn:congressional-tech:archive:table:{tname}'),
        }
        for tname, contract in table_contracts
    ]
    verified_statements = [
        {
            'question': 'How are archive Parquet payloads referenced by this DDK catalog?',
            'answer': (
                f'Zero-copy sidecar under {sidecar_prefix}/ pinning directly to immutable Parquet objects '
                f'under {PUBLIC_RELEASE_PREFIX}/{release_id}/ at {public_origin} without copying archive .parquet or export.parquet bytes.'
            ),
            'tags': ['zero-copy', 'release-binding', f'release:{release_id}'],
        },
        {
            'question': 'What capture profile schema governs url_state in this release?',
            'answer': (
                f'capture_profile.json version={capture_profile_version!r} '
                f'(include_capture_eligibility={include_capture_eligibility}).'
            ),
            'tags': ['capture-profile', 'odcs'],
        },
    ]
    if parity_summary['documented_sql_drift_tables']:
        verified_statements.append({
            'question': 'Do any tables in this release exhibit known producer SQL extra-column drift vs canonical release-schema.json?',
            'answer': (
                'Documented producer SQL drift observed without faking canonical parity on tables: '
                + ', '.join(parity_summary['documented_sql_drift_tables'])
            ),
            'tags': ['schema-drift', 'producer-sql-drift'],
        })
    constraints = [
        {
            'constraint': f'Immutable archive release_id MUST equal {release_id} across all tables.',
            'tags': ['release-binding'],
        },
        {
            'constraint': 'Sidecar publication MUST emit zero .parquet object writes.',
            'tags': ['zero-copy'],
        },
    ]
    instructions = [
        f'Read archive tables directly via HTTPS URLs under {public_origin}/{PUBLIC_RELEASE_PREFIX}/{release_id}/.',
    ]
    if body_text_binding is not None:
        bt_key = body_text_binding['key']
        bt_sha = body_text_binding['sha256']
        bt_bytes = body_text_binding['bytes']
        bt_rows = body_text_binding.get('rows')
        instructions.append(
            f'Use ct-0a35 SereneDB/BodyTextSSOT corpus bound to release {release_id}: '
            f'{public_origin}/{bt_key} (sha256={bt_sha}, bytes={bt_bytes}, rows={bt_rows}, '
            f'iterator={SERENEDB_ITERATOR_SYMBOL}).'
        )
        verified_statements.append({
            'question': 'Which BodyTextSSOT / SereneDB (ct-0a35) snapshot is bound to this archive release?',
            'answer': (
                f'ct-0a35 BodyTextSSOT pointer {body_text_binding["pointer_key"]} binds release {release_id} '
                f'to {bt_key} (sha256={bt_sha}, bytes={bt_bytes}, rows={bt_rows}) via {SERENEDB_ITERATOR_SYMBOL} without copying export.parquet.'
            ),
            'tags': [CT_0A35_TICKET, 'body-text-ssot', 'serenedb', f'release:{release_id}'],
        })
        constraints.append({
            'constraint': f'BodyTextSSOT ({CT_0A35_TICKET}) sha256 {bt_sha} and key {bt_key} MUST only be paired with release {release_id}.',
            'tags': [CT_0A35_TICKET, 'body-text-ssot', 'serenedb'],
        })

    custom_properties: list[dict[str, Any]] = [
        {'property': 'archiveReleaseId', 'value': release_id},
        {'property': 'sidecarPrefix', 'value': sidecar_prefix},
        {'property': 'zeroCopySidecar', 'value': True},
        {'property': 'captureProfileVersion', 'value': capture_profile_version},
        {'property': 'includeCaptureEligibility', 'value': include_capture_eligibility},
        {'property': 'canonicalSchemaParityStatus', 'value': parity_summary['status']},
        {'property': 'documentedProducerSqlDriftTables', 'value': list(parity_summary['documented_sql_drift_tables'])},
    ]
    if body_text_binding is not None:
        custom_properties.append({'property': 'bodyTextSsot', 'value': deepcopy(body_text_binding)})
        custom_properties.append({'property': 'sereneDbBinding', 'value': deepcopy(body_text_binding['serenedb'])})

    return {
        'apiVersion': 'v1.1.0',
        'kind': 'DataProduct',
        'id': f'urn:congressional-tech:product:archive:{release_id[:16]}',
        'name': 'Congressional Tech Archive',
        'version': _format_semver_version(schema_version),
        'status': 'published',
        'domain': 'congressional-tech',
        'description': {
            'purpose': (
                f'Zero-copy DDK and Apache Iceberg v2 publication sidecar for Congressional Tech archive release {release_id}.'
            ),
            'usage': 'Query immutable Parquet release objects or consume Iceberg v2/DCAT/JSON-LD discovery sidecars.',
            'limitations': (
                'Sidecar never duplicates archive .parquet or BodyTextSSOT export.parquet payloads; '
                'any documented producer SQL extra columns are reported explicitly without claiming canonical parity.'
            ),
        },
        'outputPorts': output_ports,
        'context': {
            'instructions': ' '.join(instructions),
            'verifiedStatements': verified_statements,
            'constraints': constraints,
        },
        'customProperties': custom_properties,
    }


def build_sidecar_descriptor(
    manifest_or_dir: Mapping[str, Any] | Path | str,
    *,
    release_id: str | None = None,
    public_origin: str = DEFAULT_PUBLIC_ORIGIN,
    sidecar_prefix: str = DEFAULT_SIDECAR_PREFIX,
    bucket: str = DEFAULT_BUCKET,
    body_text_pointer: Mapping[str, Any] | Path | str | None = None,
    capture_profile: Mapping[str, Any] | Path | str | None = None,
    include_capture_eligibility: bool | None = None,
    tables: Sequence[str] | None = None,
    allow_insecure_http: bool = False,
    storage: Any | None = None,
    verify_local_schemas: bool = True,
    verify_storage_schemas: bool = False,
    verify_body_text_storage: bool = False,
    observed_at: str | None = None,
    local_parquet_paths: Mapping[str, Path | str] | None = None,
) -> dict[str, Any]:
    """Deterministically build a zero-copy DDK external-generation descriptor and parity report."""
    manifest, release_dir = resolve_release_manifest(manifest_or_dir, release_id=release_id)
    eff_release_id = str(manifest['release_id'])
    clean_origin = validate_public_origin(public_origin, allow_insecure_http=allow_insecure_http)
    clean_prefix = validate_sidecar_prefix(sidecar_prefix)
    if not isinstance(bucket, str) or not bucket.strip():
        raise ValueError(f'bucket must be a nonempty string, got {bucket!r}')
    clean_bucket = bucket.strip()

    profile_info = detect_capture_profile_v2(
        manifest,
        release_dir=release_dir,
        capture_profile=capture_profile,
        include_capture_eligibility=include_capture_eligibility,
        storage=storage,
    )
    eff_capture_eligibility = bool(profile_info['include_capture_eligibility'])
    contracts_bundle = archive_odcs.export_odcs_contracts(
        include_capture_eligibility=eff_capture_eligibility
    )
    canonical_tables: dict[str, dict[str, Any]] = contracts_bundle['table_contracts']

    body_text_binding = validate_body_text_ssot_binding(
        body_text_pointer,
        release_id=eff_release_id,
        manifest=manifest,
        public_origin=clean_origin,
        storage=storage,
        verify_storage_object=verify_body_text_storage,
    )

    selected_filter = set(tables) if tables is not None else None
    grouped_members: dict[str, list[tuple[Mapping[str, Any], str]]] = {}
    for entry in manifest['files']:
        if not isinstance(entry, Mapping):
            raise ValueError(f'Invalid manifest file entry: {entry!r}')
        parsed_entry = _manifest_table_name(entry, canonical_tables)
        if parsed_entry is None:
            continue
        tname, filename = parsed_entry
        if selected_filter is not None and tname not in selected_filter:
            continue
        grouped_members.setdefault(tname, []).append((entry, filename))

    if selected_filter is not None:
        missing_tables = sorted(selected_filter - set(grouped_members))
        if missing_tables:
            raise ValueError(f'Requested tables missing from manifest: {missing_tables!r}')
    if not grouped_members:
        raise ValueError('No archive Parquet tables selected from manifest')

    explicit_local_paths = {k: Path(v) for k, v in (local_parquet_paths or {}).items()}
    table_descriptors: list[dict[str, Any]] = []
    parity_by_table: dict[str, dict[str, Any]] = {}
    documented_drift_tables: list[str] = []
    resolved_local_paths: dict[str, str] = {}

    for tname in sorted(grouped_members):
        canonical_contract = canonical_tables[tname]
        contract_for_sidecar = deepcopy(canonical_contract)
        table_parity: dict[str, Any] = {
            'table_name': tname,
            'status': 'not_verified_locally',
            'canonical_parity_passed': None,
            'canonical_issues': [],
            'documented_divergences': [],
        }

        members_desc: list[dict[str, Any]] = []
        entries_sorted = sorted(grouped_members[tname], key=lambda item: item[1])
        multi = len(entries_sorted) > 1
        for idx, (entry, filename) in enumerate(entries_sorted):
            remote_key = f'{PUBLIC_RELEASE_PREFIX}/{eff_release_id}/{filename}'
            sha = entry.get('sha256')
            size = entry.get('size')
            rows = entry.get('rows')
            if not isinstance(sha, str) or not _HEX64_RE.fullmatch(sha):
                raise ValueError(f'Manifest file {filename!r} requires 64-hex sha256, got {sha!r}')
            if type(size) is not int or size <= 0:
                raise ValueError(f'Manifest file {filename!r} requires positive int size, got {size!r}')
            if type(rows) is not int or rows < 0:
                raise ValueError(f'Manifest file {filename!r} requires non-negative int rows, got {rows!r}')
            md5 = entry.get('md5')
            if md5 is not None and (not isinstance(md5, str) or not _HEX32_RE.fullmatch(md5)):
                raise ValueError(f'Manifest file {filename!r} requires 32-hex md5, got {md5!r}')

            member_dict: dict[str, Any] = {
                'remote_key': remote_key,
                'url': f'{clean_origin}/{remote_key}',
                'sha256': sha,
                'size': size,
                'rows': rows,
                'output_name': f'{tname}__{idx}' if multi else tname,
                'allow_insecure_http': allow_insecure_http,
            }
            if md5 is not None:
                member_dict['md5'] = md5
            if entry.get('footer_sha256') is not None:
                member_dict['footer_sha256'] = entry['footer_sha256']
            members_desc.append(member_dict)

            candidate_path: Path | None = None
            if remote_key in explicit_local_paths:
                candidate_path = explicit_local_paths[remote_key]
            elif release_dir is not None and (release_dir / filename).is_file():
                candidate_path = release_dir / filename
            if candidate_path is not None:
                resolved_local_paths[remote_key] = str(candidate_path)

            if verify_local_schemas and candidate_path is not None:
                checked = inspect_table_schema_parity(tname, candidate_path, canonical_contract)
            elif verify_storage_schemas and storage is not None:
                checked = inspect_table_schema_parity(
                    tname, remote_key, canonical_contract, storage=storage, remote_key=remote_key,
                )
            else:
                checked = None

            if checked is not None:
                if (
                    table_parity['status'] != 'not_verified_locally'
                    and checked['status'] != table_parity['status']
                ):
                    raise SchemaDriftError(f'Inconsistent shard schemas on table {tname!r}')
                table_parity = {k: v for k, v in checked.items() if k != 'contract_for_sidecar'}
                contract_for_sidecar = checked['contract_for_sidecar']

        if table_parity['status'] == 'documented_sql_drift':
            documented_drift_tables.append(tname)

        parity_by_table[tname] = table_parity
        table_descriptors.append({
            'table_name': tname,
            'contract_object': tname,
            'contract': contract_for_sidecar,
            'members': members_desc,
            'normalize_arrow_encodings': True,
            'check_column_order': False,
            'canonical_parity_status': table_parity['status'],
            'canonical_parity_passed': table_parity['canonical_parity_passed'],
            'documented_divergences': list(table_parity['documented_divergences']),
        })

    if any(v['status'] == 'documented_sql_drift' for v in parity_by_table.values()):
        overall_parity_status = 'documented_sql_drift'
        overall_canonical_passed = False
    elif all(v['status'] == 'passed' for v in parity_by_table.values()):
        overall_parity_status = 'passed'
        overall_canonical_passed = True
    else:
        overall_parity_status = 'unverified_remote_metadata_only'
        overall_canonical_passed = None

    parity_summary = {
        'status': overall_parity_status,
        'canonical_parity_passed': overall_canonical_passed,
        'total_tables': len(table_descriptors),
        'passed_tables': sorted(t for t, v in parity_by_table.items() if v['status'] == 'passed'),
        'documented_sql_drift_tables': sorted(documented_drift_tables),
        'unverified_tables': sorted(t for t, v in parity_by_table.items() if v['status'] == 'not_verified_locally'),
        'tables': parity_by_table,
    }

    product = _build_odps_product(
        release_id=eff_release_id,
        table_contracts=[(td['table_name'], td['contract']) for td in table_descriptors],
        schema_version=manifest.get('schema_version', '1'),
        capture_profile_version=profile_info['version'],
        include_capture_eligibility=eff_capture_eligibility,
        body_text_binding=body_text_binding,
        parity_summary=parity_summary,
        public_origin=clean_origin,
        sidecar_prefix=clean_prefix,
    )

    descriptor: dict[str, Any] = {
        'schema_version': DEFAULT_SCHEMA_VERSION,
        'dataset': DEFAULT_DATASET,
        'catalog_id': DEFAULT_CATALOG_ID,
        'project_id': DEFAULT_PROJECT_ID,
        'version': _format_semver_version(manifest.get('schema_version', 1)),
        'authority': DEFAULT_AUTHORITY_ID,
        'purpose': 'zero-copy-public-sidecar',
        'audience': 'public',
        'release_id': eff_release_id,
        'base_url': clean_origin,
        'bucket': clean_bucket,
        'sidecar_prefix': clean_prefix,
        'public_release_prefix': f'{PUBLIC_RELEASE_PREFIX}/{eff_release_id}',
        'zero_copy': True,
        'normalize_arrow_encodings': True,
        'check_column_order': False,
        'capture_profile': {
            'version': profile_info['version'],
            'include_capture_eligibility': eff_capture_eligibility,
            'source': profile_info['source'],
        },
        'body_text_ssot': body_text_binding,
        'ct_0a35_binding': deepcopy(body_text_binding['serenedb']) if body_text_binding is not None else None,
        'product': product,
        'parity_summary': parity_summary,
        'local_parquet_paths': resolved_local_paths,
        'tables': table_descriptors,
    }
    if observed_at is not None:
        descriptor['observed_at'] = observed_at
    return descriptor


def make_remote_destination(
    *,
    bucket: str = DEFAULT_BUCKET,
    sidecar_prefix: str = DEFAULT_SIDECAR_PREFIX,
    public_origin: str = DEFAULT_PUBLIC_ORIGIN,
    allow_insecure_http: bool = False,
) -> Any:
    """Create a DDK ``RemoteDestination`` pointing at an isolated additive sidecar prefix."""
    dp = _load_ddk_publication()
    clean_prefix = validate_sidecar_prefix(sidecar_prefix)
    clean_origin = validate_public_origin(public_origin, allow_insecure_http=allow_insecure_http)
    return dp.RemoteDestination(
        owned_prefix=f's3://{bucket.strip()}/{clean_prefix}',
        properties={'public_base_url': clean_origin},
        release_prefix=f'{clean_prefix}/releases',
        pointer_key=f'{clean_prefix}/current.json',
    )


def build_sidecar_bundle(
    descriptor: Mapping[str, Any],
    *,
    output_dir: Path | str,
    bundle_dir: Path | str | None = None,
    expected_prior_release_id: Any = _SENTINEL,
    expected_pointer: Any | None = None,
    storage: Any | None = None,
    allow_insecure_http: bool = False,
    verify_schema_parity: bool = True,
    synthesize_iceberg: bool = True,
    observed_at: str | None = None,
    local_parquet_paths: Mapping[str, Path | str] | None = None,
) -> Any:
    """Assemble a DDK + Iceberg v2 external-generation bundle from a CT sidecar descriptor."""
    dp = _load_ddk_publication()
    destination = make_remote_destination(
        bucket=str(descriptor.get('bucket') or DEFAULT_BUCKET),
        sidecar_prefix=str(descriptor.get('sidecar_prefix') or DEFAULT_SIDECAR_PREFIX),
        public_origin=str(descriptor.get('base_url') or DEFAULT_PUBLIC_ORIGIN),
        allow_insecure_http=allow_insecure_http,
    )
    merged_local_paths = dict(descriptor.get('local_parquet_paths') or {})
    if local_parquet_paths:
        merged_local_paths.update({k: str(v) for k, v in local_parquet_paths.items()})

    kwargs: dict[str, Any] = {
        'descriptor': descriptor,
        'destination': destination,
        'output_dir': Path(output_dir),
        'bundle_dir': Path(bundle_dir) if bundle_dir is not None else None,
        'product': descriptor.get('product'),
        'verify_schema_parity': verify_schema_parity,
        'normalize_arrow_encodings': True,
        'check_column_order': False,
        'synthesize_iceberg': synthesize_iceberg,
        'storage': storage,
        'local_parquet_paths': merged_local_paths or None,
        'allow_insecure_http': allow_insecure_http,
        'observed_at': observed_at or descriptor.get('observed_at'),
    }
    if expected_pointer is not None:
        kwargs['expected_pointer'] = expected_pointer
    if expected_prior_release_id is not _SENTINEL:
        kwargs['expected_prior_release_id'] = expected_prior_release_id
    return dp.build_external_generation_bundle(**kwargs)


def dry_run_sidecar(
    bundle: Any,
    *,
    storage: Any | None = None,
    destination: Any | None = None,
    expected_prior_release_id: Any = _SENTINEL,
    live_pointer_bytes: bytes | None = None,
    live_pointer_etag: str | None = None,
    member_paths: Mapping[str, Path | str] | None = None,
    verify_schema_parity: bool = True,
    verify_member_bytes: bool = True,
    allow_insecure_http: bool = False,
) -> dict[str, Any]:
    """Run DDK dry-run verification (CAS + zero-copy manifest/schema/byte audit) over a sidecar bundle."""
    dp = _load_ddk_publication()
    kwargs: dict[str, Any] = {
        'storage': storage,
        'destination': destination if destination is not None else getattr(bundle, 'destination', None),
        'live_pointer_bytes': live_pointer_bytes,
        'live_pointer_etag': live_pointer_etag,
        'member_paths': member_paths,
        'verify_schema_parity': verify_schema_parity,
        'verify_member_bytes': verify_member_bytes,
        'allow_insecure_http': allow_insecure_http,
        'normalize_arrow_encodings': True,
        'check_column_order': False,
        'schema_check_order': False,
        'schema_check_nullability': False,
    }
    if expected_prior_release_id is not _SENTINEL:
        kwargs['expected_prior_release_id'] = expected_prior_release_id
    return dp.dry_run_remote_publication(bundle, **kwargs)


def publish_sidecar(
    bundle: Any,
    *,
    storage: Any,
    destination: Any | None = None,
    expected_prior_release_id: Any = _SENTINEL,
    expected_prior_etag: str | None = None,
    require_prior_when_live: bool = True,
    anonymous_fetch: Any | None = None,
    fetch_public_object: Any | None = None,
    verify_schema_parity: bool = True,
    verify_member_bytes: bool = True,
    run_native_readback: bool = True,
    allow_insecure_http: bool = False,
    allow_authenticated_readback: bool = False,
) -> dict[str, Any]:
    """Publish sidecar metadata only (0 Parquet PUTs) and run anonymous readback verification."""
    dp = _load_ddk_publication()
    external_keys = set(getattr(bundle.plan, 'external_member_keys', ()))
    for key in getattr(bundle.plan, 'remote_keys', ()):
        if key not in external_keys and str(key).lower().endswith('.parquet'):
            raise ValueError(f'Sidecar plan illegally attempts to upload Parquet object {key!r}')
    kwargs: dict[str, Any] = {
        'storage': storage,
        'destination': destination if destination is not None else getattr(bundle, 'destination', None),
        'expected_prior_etag': expected_prior_etag,
        'require_prior_when_live': require_prior_when_live,
        'anonymous_fetch': anonymous_fetch,
        'fetch_public_object': fetch_public_object,
        'verify_schema_parity': verify_schema_parity,
        'verify_member_bytes': verify_member_bytes,
        'run_native_readback': run_native_readback,
        'allow_insecure_http': allow_insecure_http,
        'allow_authenticated_readback': allow_authenticated_readback,
        'normalize_arrow_encodings': True,
        'check_column_order': False,
        'schema_check_order': False,
        'schema_check_nullability': False,
    }
    if expected_prior_release_id is not _SENTINEL:
        kwargs['expected_prior_release_id'] = expected_prior_release_id
    return dp.publish_and_verify_remote_publication(bundle, **kwargs)


def _create_boto_client_from_env() -> Any:
    import os
    import boto3
    from botocore.config import Config

    endpoint_url = os.environ.get('CONGRESS_ARCHIVE_S3_ENDPOINT') or os.environ.get('R2_ENDPOINT_URL')
    kwargs: dict[str, Any] = {'config': Config(retries={'total_max_attempts': 1})}
    if endpoint_url:
        kwargs['endpoint_url'] = endpoint_url
    return boto3.client('s3', **kwargs)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Build, dry-run, or publish a zero-copy DDK + Iceberg v2 sidecar bound to BodyTextSSOT (ct-0a35).'
    )
    parser.add_argument('--release-dir', required=True, type=Path, help='Directory containing archive manifest.json (and optional capture_profile.json / .parquet files).')
    parser.add_argument('--release-id', default=None, help='Expected 64-hex archive release_id (verified against manifest.json).')
    parser.add_argument('--body-text-pointer', default=None, help='Path or storage key to release-bound derived/body_text/current.json pointer.')
    parser.add_argument('--public-origin', default=DEFAULT_PUBLIC_ORIGIN, help=f'Public HTTPS origin (default: {DEFAULT_PUBLIC_ORIGIN}).')
    parser.add_argument('--sidecar-prefix', default=DEFAULT_SIDECAR_PREFIX, help=f'Isolated additive sidecar prefix (default: {DEFAULT_SIDECAR_PREFIX}).')
    parser.add_argument('--bucket', default=DEFAULT_BUCKET, help=f'Target S3/R2 bucket name (default: {DEFAULT_BUCKET}).')
    parser.add_argument('--expected-prior-release-id', default=None, help='Expected live sidecar release_id for CAS writes (use empty string or --expect-absent when uninitialized).')
    parser.add_argument('--expect-absent', action='store_true', help='Require the live sidecar current.json pointer to be absent.')
    parser.add_argument('--dry-run', action='store_true', help='Validate descriptor, schema parity, and DDK dry-run plan without publishing.')
    parser.add_argument('--publish', action='store_true', help='Publish sidecar metadata only (0 Parquet PUTs) and run readback verification.')
    parser.add_argument('--allow-insecure-http', action='store_true', help='Permit http://127.0.0.1 / localhost / ::1 origins for local testing.')
    parser.add_argument('--require-ddk', action='store_true', help='Fail closed in --dry-run if ddk.publication is not importable.')
    parser.add_argument('--out', type=Path, default=None, help='Write machine-readable JSON output to this file.')
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.dry_run and args.publish:
        parser.error('Cannot specify both --dry-run and --publish')

    if args.expect_absent:
        exp_prior: Any = None
    elif args.expected_prior_release_id is not None:
        exp_prior = args.expected_prior_release_id or None
    else:
        exp_prior = _SENTINEL

    descriptor = build_sidecar_descriptor(
        args.release_dir,
        release_id=args.release_id,
        public_origin=args.public_origin,
        sidecar_prefix=args.sidecar_prefix,
        bucket=args.bucket,
        body_text_pointer=args.body_text_pointer,
        allow_insecure_http=args.allow_insecure_http,
    )

    result: dict[str, Any] = {
        'mode': 'publish' if args.publish else ('dry_run' if args.dry_run else 'descriptor'),
        'release_id': descriptor['release_id'],
        'sidecar_prefix': descriptor['sidecar_prefix'],
        'bucket': descriptor['bucket'],
        'public_origin': descriptor['base_url'],
        'zero_copy': True,
        'ddk_available': ddk_bridge_available(),
        'capture_profile': descriptor['capture_profile'],
        'body_text_ssot': descriptor['body_text_ssot'],
        'parity_summary': descriptor['parity_summary'],
        'descriptor': descriptor,
    }

    if args.publish:
        _load_ddk_publication()
        boto_client = _create_boto_client_from_env()
        storage = _BotoSidecarStorage(
            boto_client,
            bucket=descriptor['bucket'],
            sidecar_prefix=descriptor['sidecar_prefix'],
        )
        with tempfile.TemporaryDirectory(prefix='ct-ddk-sidecar-') as tmpdir:
            tmp_path = Path(tmpdir)
            bundle = build_sidecar_bundle(
                descriptor,
                output_dir=tmp_path / 'catalog',
                bundle_dir=tmp_path / 'bundle',
                expected_prior_release_id=exp_prior,
                storage=storage,
                allow_insecure_http=args.allow_insecure_http,
            )
            pub_receipt = publish_sidecar(
                bundle,
                storage=storage,
                expected_prior_release_id=exp_prior,
                allow_insecure_http=args.allow_insecure_http,
            )
        result['publication'] = pub_receipt
        result['put_keys'] = list(storage.put_keys)
    elif args.dry_run:
        if not result['ddk_available']:
            if args.require_ddk:
                _load_ddk_publication()
            result['sidecar_status'] = 'descriptor_verified_ddk_unavailable'
        else:
            with tempfile.TemporaryDirectory(prefix='ct-ddk-sidecar-') as tmpdir:
                tmp_path = Path(tmpdir)
                local_paths = descriptor.get('local_parquet_paths') or None
                bundle = build_sidecar_bundle(
                    descriptor,
                    output_dir=tmp_path / 'catalog',
                    bundle_dir=tmp_path / 'bundle',
                    expected_prior_release_id=None if exp_prior is _SENTINEL else exp_prior,
                    allow_insecure_http=args.allow_insecure_http,
                    verify_schema_parity=bool(local_paths),
                    local_parquet_paths=local_paths,
                )
                dry_receipt = dry_run_sidecar(
                    bundle,
                    expected_prior_release_id=None if exp_prior is _SENTINEL else exp_prior,
                    live_pointer_bytes=None if exp_prior in {_SENTINEL, None} else json.dumps({'release_id': exp_prior}).encode('utf-8'),
                    member_paths=local_paths,
                    verify_schema_parity=bool(local_paths),
                    verify_member_bytes=bool(local_paths),
                    allow_insecure_http=args.allow_insecure_http,
                )
            result['sidecar_status'] = 'dry_run_passed'
            result['dry_run'] = dry_receipt

    encoded = json.dumps(result, indent=2, sort_keys=True) + '\n'
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding='utf-8')
    else:
        sys.stdout.write(encoded)
    return 0


__all__ = [
    'CT_0A35_TICKET',
    'DEFAULT_BUCKET',
    'DEFAULT_PUBLIC_ORIGIN',
    'DEFAULT_SIDECAR_PREFIX',
    'DOCUMENTED_LIVE_SQL_DRIFT',
    'PUBLIC_RELEASE_PREFIX',
    'SERENEDB_ITERATOR_SYMBOL',
    'SchemaDriftError',
    '_BotoSidecarStorage',
    'build_arg_parser',
    'build_sidecar_bundle',
    'build_sidecar_descriptor',
    'ddk_bridge_available',
    'detect_capture_profile_v2',
    'dry_run_sidecar',
    'inspect_table_schema_parity',
    'main',
    'make_remote_destination',
    'publish_sidecar',
    'resolve_release_manifest',
    'validate_body_text_ssot_binding',
    'validate_public_origin',
    'validate_sidecar_prefix',
]
