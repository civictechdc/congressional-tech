"""Typed models and specifications for the DocSpec client."""
from collections.abc import Mapping
import json
from pathlib import Path
import re
from typing import Any


ARROW_STREAM_MIME = 'application/vnd.apache.arrow.stream'
VALID_UPDATE_MERGE_STRATEGIES = ('replace', 'latest_or_backfill', 'min', 'max', 'set_union')
SUPPORTED_PLATFORMS = ('linux-amd64', 'darwin-arm64', 'darwin-amd64')
PRODUCER_PARQUET_ROW_GROUP_SIZE = 2048

REQUIRED_LOOPBACK_CAPABILITIES = ('request-deadline', 'owned-stdin-eof')
RESPONSE_LIMIT = 1 << 20  # 1 MiB bounded metadata response limit

RUNTIME_PIN_FILE = Path(__file__).resolve().parents[4] / 'model/docspec-runtime-pin.json'
_HEX40 = re.compile(r'^[0-9a-f]{40}$')
_HEX64 = re.compile(r'^[0-9a-f]{64}$')


def load_runtime_pin(path: str | Path | None = None) -> dict[str, Any]:
    """Load and validate the committed native runtime pin file."""
    target = RUNTIME_PIN_FILE if path is None else Path(path)
    try:
        payload = json.loads(target.read_text(encoding='utf-8'))
    except OSError as error:
        raise ValueError('Native runtime pin file is unreadable: ' + str(target)) from error
    except ValueError as error:
        raise ValueError('Native runtime pin file is invalid JSON: ' + str(target)) from error
    if not isinstance(payload, dict) or payload.get('version') != 1:
        raise ValueError('Native runtime pin file must have version 1')
    revision = payload.get('source_revision')
    if not isinstance(revision, str) or not _HEX40.match(revision):
        raise ValueError('Native runtime pin source_revision must be a 40-char lowercase hex commit')
    features = payload.get('build_features')
    if not isinstance(features, list) or not features or not all(isinstance(v, str) and v for v in features):
        raise ValueError('Native runtime pin build_features must be a non-empty string list')
    capabilities = payload.get('required_capabilities')
    if not isinstance(capabilities, list) or not capabilities or not all(isinstance(v, str) and v for v in capabilities):
        raise ValueError('Native runtime pin required_capabilities must be a non-empty string list')
    platforms = payload.get('platforms')
    if not isinstance(platforms, dict) or not platforms:
        raise ValueError('Native runtime pin platforms must be a non-empty mapping')
    validated_platforms: dict[str, dict[str, str]] = {}
    for platform_name, entry in platforms.items():
        if not isinstance(platform_name, str) or not platform_name or not isinstance(entry, dict):
            raise ValueError('Native runtime pin platform entry must be an object')
        digest = entry.get('sha256')
        if not isinstance(digest, str) or not _HEX64.match(digest):
            raise ValueError(f'Native runtime pin sha256 for {platform_name} must be a 64-char lowercase hex digest')
        validated_platforms[platform_name] = {'sha256': digest}
    return {
        'version': 1,
        'source_revision': revision,
        'build_features': list(features),
        'required_capabilities': list(capabilities),
        'platforms': validated_platforms,
    }


def runtime_pin_digest(platform_name: str, *, pin_path: str | Path | None = None) -> str:
    """Return the committed SHA-256 digest for the given platform key."""
    pin = load_runtime_pin(pin_path)
    platforms = pin['platforms']
    if platform_name not in platforms:
        raise ValueError(f'Unsupported native runtime platform in pin file: {platform_name}')
    return platforms[platform_name]['sha256']


_PIN = load_runtime_pin()

QUALIFIED_DOCSPEC_RUNTIME = {
    'source_revision': _PIN['source_revision'],
    'darwin_arm64_binary_sha256': _PIN['platforms']['darwin-arm64']['sha256'],
    'linux_amd64_binary_sha256': _PIN['platforms']['linux-amd64']['sha256'],
    'platforms': {k: dict(v) for k, v in _PIN['platforms'].items()},
    'pin_file': str(RUNTIME_PIN_FILE),
    'build_features': tuple(_PIN['build_features']),
    'required_capabilities': tuple(_PIN['required_capabilities']),
    'safety_prerequisites': (
        'ct-3li2', 'ct-cpio', 'ct-xq1y', 'ct-5fkx', 'ct-gfv8', 'ct-q05l', 'ct-csyg',
        'ct-tuez', 'ct-nmjc', 'ct-13g5',
    ),
}

PRE_ADMISSION_ERROR_CODES = frozenset({
    'input_digest_mismatch',
    'invalid_correction',
    'release_mismatch',
    'invalid_request',
    'invalid_update',
    'invalid_schema',
    'invalid_definition',
    'invalid_sql',
    'invalid_id',
    'invalid_json',
    'invalid_operation',
    'invalid_base',
    'invalid_group',
    'invalid_relationship',
    'invalid_backfill',
    'invalid_comparison',
    'invalid_compaction',
    'invalid_export',
    'invalid_removal',
    'invalid_evidence',
    'missing_reason',
    'invalid_argument',
    'invalid_parameter',
    'invalid_spec',
    'invalid_request_timeout',
    'invalid_input',
    'operation_conflict',
    'validation',
})


class DocSpecFailure(RuntimeError, OSError):
    """Native refusal or host failure, retaining its original diagnostic."""

    def __init__(self, command: Any, result: Any) -> None:
        self.command = tuple(command)
        self.returncode = result.returncode if result is not None else 1
        self.stderr = result.stderr if result is not None else ''
        self.stdout = result.stdout if result is not None else ''
        self.completed: dict[str, Any] | None = None
        try:
            report = json.loads(self.stdout)
        except (TypeError, ValueError):
            report = None
        if isinstance(report, dict) and report.get('status') == 'failed' and isinstance(report.get('completed'), dict):
            self.completed = report['completed']
        self.status_code: int | None = None
        self.code: str | None = None
        self.pre_admission: bool | None = None
        try:
            payload = json.loads(self.stderr)
        except (TypeError, ValueError):
            payload = None
        if isinstance(payload, dict):
            if isinstance(payload.get('code'), str) and payload['code']:
                self.code = payload['code']
            if isinstance(payload.get('pre_admission'), bool):
                self.pre_admission = payload['pre_admission']
        super().__init__(self.stderr.strip() or f'DocSpec exited {self.returncode}')

    @property
    def status(self) -> int | None:
        return self.status_code

    @status.setter
    def status(self, value: int | None) -> None:
        self.status_code = value


class PartitionTransformSpec(dict):
    """Exact serde representation of ``docspec_core::PartitionTransformSpec``."""

    def __init__(self, kind: str = 'identity', **kwargs: Any) -> None:
        self._validate(kind, **kwargs)
        payload: dict[str, Any] = {'kind': kind}
        payload.update(kwargs)
        super().__init__(payload)

    @classmethod
    def _validate(cls, kind: str, **kwargs: Any) -> None:
        if kind == 'identity':
            if kwargs:
                raise ValueError(f'PartitionTransformSpec identity accepts no parameters: {kwargs!r}')
        elif kind == 'bucket':
            num_buckets = kwargs.get('num_buckets')
            if not isinstance(num_buckets, int) or isinstance(num_buckets, bool) or not 1 <= num_buckets <= 4096:
                raise ValueError(f'Bucket transform num_buckets must be an integer in 1..=4096, got: {num_buckets!r}')
            unknown = set(kwargs) - {'num_buckets'}
            if unknown:
                raise ValueError(f'Unknown bucket transform parameters: {sorted(unknown)!r}')
        elif kind in ('year', 'month', 'day'):
            if kwargs:
                raise ValueError(f'PartitionTransformSpec {kind} accepts no parameters: {kwargs!r}')
        elif kind == 'truncate':
            width = kwargs.get('width')
            if not isinstance(width, int) or isinstance(width, bool) or width <= 0:
                raise ValueError(f'PartitionTransformSpec truncate width must be a positive integer: {width!r}')
            unknown = set(kwargs) - {'width'}
            if unknown:
                raise ValueError(f'Unknown truncate transform parameters: {sorted(unknown)!r}')
        else:
            raise ValueError(f'Invalid PartitionTransformSpec kind: {kind!r}')

    @classmethod
    def normalize(cls, spec: Any) -> dict[str, Any]:
        if isinstance(spec, cls):
            return dict(spec)
        if isinstance(spec, str):
            return dict(cls(spec))
        if isinstance(spec, dict):
            return dict(cls(spec.get('kind', 'identity'), **{k: v for k, v in spec.items() if k != 'kind'}))
        raise ValueError(f'Invalid PartitionTransformSpec: {spec!r}')

    @classmethod
    def identity(cls) -> 'PartitionTransformSpec':
        return cls('identity')

    @classmethod
    def bucket(cls, num_buckets: int = 64) -> 'PartitionTransformSpec':
        return cls('bucket', num_buckets=num_buckets)

    @classmethod
    def year(cls) -> 'PartitionTransformSpec':
        return cls('year')

    @classmethod
    def month(cls) -> 'PartitionTransformSpec':
        return cls('month')

    @classmethod
    def day(cls) -> 'PartitionTransformSpec':
        return cls('day')

    @classmethod
    def truncate(cls, width: int) -> 'PartitionTransformSpec':
        return cls('truncate', width=width)

    def to_dict(self) -> dict[str, Any]:
        return dict(self)


class PartitionFieldSpec(dict):
    """Exact serde representation of ``docspec_core::PartitionFieldSpec``."""

    def __init__(self, column: str, transform: Any = 'identity', *, name: str | None = None) -> None:
        if not isinstance(column, str) or not column.strip():
            raise ValueError('PartitionFieldSpec column must be a non-empty string')
        payload: dict[str, Any] = {
            'column': str(column),
            'transform': PartitionTransformSpec.normalize(transform),
        }
        if name is not None:
            if not isinstance(name, str) or not name.strip():
                raise ValueError('PartitionFieldSpec name must be a non-empty string when provided')
            payload['name'] = str(name).strip()
        super().__init__(payload)

    @property
    def column(self) -> str:
        return self['column']

    @property
    def transform(self) -> dict[str, Any]:
        return self['transform']

    @property
    def name(self) -> str | None:
        return self.get('name')

    @classmethod
    def normalize(cls, spec: Any) -> dict[str, Any]:
        if isinstance(spec, cls):
            return dict(spec)
        if isinstance(spec, str):
            return dict(cls(spec))
        if isinstance(spec, (tuple, list)):
            if len(spec) == 2:
                return dict(cls(spec[0], spec[1]))
            if len(spec) == 3:
                return dict(cls(spec[0], spec[1], name=spec[2]))
            raise ValueError(f'PartitionFieldSpec tuple must have 2 or 3 elements: {spec!r}')
        if isinstance(spec, dict):
            unknown = set(spec) - {'column', 'transform', 'name'}
            if unknown:
                raise ValueError(f'Unknown PartitionFieldSpec fields: {sorted(unknown)!r}')
            if 'column' not in spec:
                raise ValueError('PartitionFieldSpec dict requires a "column" field')
            return dict(cls(spec['column'], spec.get('transform', 'identity'), name=spec.get('name')))
        raise ValueError(f'Invalid PartitionFieldSpec: {spec!r}')

    def to_dict(self) -> dict[str, Any]:
        return dict(self)


class PartitionSpec:
    """Builder methods for common ``PartitionFieldSpec`` configurations."""

    @staticmethod
    def identity(column: str, *, name: str | None = None) -> PartitionFieldSpec:
        return PartitionFieldSpec(column, PartitionTransformSpec.identity(), name=name)

    @staticmethod
    def bucket(column: str, num_buckets: int = 64, *, name: str | None = None) -> PartitionFieldSpec:
        return PartitionFieldSpec(column, PartitionTransformSpec.bucket(num_buckets), name=name)

    @staticmethod
    def year(column: str, *, name: str | None = None) -> PartitionFieldSpec:
        return PartitionFieldSpec(column, PartitionTransformSpec.year(), name=name)

    @staticmethod
    def month(column: str, *, name: str | None = None) -> PartitionFieldSpec:
        return PartitionFieldSpec(column, PartitionTransformSpec.month(), name=name)

    @staticmethod
    def day(column: str, *, name: str | None = None) -> PartitionFieldSpec:
        return PartitionFieldSpec(column, PartitionTransformSpec.day(), name=name)

    @staticmethod
    def truncate(column: str, width: int, *, name: str | None = None) -> PartitionFieldSpec:
        return PartitionFieldSpec(column, PartitionTransformSpec.truncate(width), name=name)

    @staticmethod
    def normalize(partition_by: Any) -> list[dict[str, Any]] | None:
        if partition_by is None:
            return None
        if isinstance(partition_by, (str, dict, PartitionFieldSpec)):
            return [PartitionFieldSpec.normalize(partition_by)]
        if isinstance(partition_by, (list, tuple)):
            return [PartitionFieldSpec.normalize(item) for item in partition_by]
        raise ValueError(f'Invalid partition_by specification: {partition_by!r}')


class UpdateMergeStrategy:
    """Valid column merge strategies for ``UpdateMergeSpec``."""

    REPLACE = 'replace'
    LATEST_OR_BACKFILL = 'latest_or_backfill'
    MIN = 'min'
    MAX = 'max'
    SET_UNION = 'set_union'
    ALL = frozenset({REPLACE, LATEST_OR_BACKFILL, MIN, MAX, SET_UNION})


class UpdateMergeSpec(dict):
    """Exact serde representation of ``docspec_core::UpdateMergeSpec``."""

    def __init__(self, order_by: str | None = None, columns: Mapping[str, str] | None = None) -> None:
        payload: dict[str, Any] = {}
        if order_by is not None:
            if not isinstance(order_by, str) or not order_by.strip():
                raise ValueError('UpdateMergeSpec order_by must be a non-empty string when provided')
            payload['order_by'] = order_by
        normalized_cols: dict[str, str] = {}
        if columns is not None:
            if not isinstance(columns, Mapping):
                raise ValueError('UpdateMergeSpec columns must be a mapping of column -> strategy')
            for col, strategy in columns.items():
                if not isinstance(col, str) or not col.strip():
                    raise ValueError(f'UpdateMergeSpec column name must be a non-empty string: {col!r}')
                if isinstance(strategy, dict) and 'kind' in strategy:
                    strategy = strategy['kind']
                strat_str = str(strategy).lower()
                if strat_str not in UpdateMergeStrategy.ALL:
                    raise ValueError(f'Invalid UpdateMergeStrategy {strategy!r} for column {col!r}')
                normalized_cols[col] = strat_str
        payload['columns'] = normalized_cols
        super().__init__(payload)

    @property
    def order_by(self) -> str | None:
        return self.get('order_by')

    @property
    def columns(self) -> dict[str, str]:
        return self['columns']

    @classmethod
    def first_seen(cls, columns: Mapping[str, str] | None = None) -> 'UpdateMergeSpec':
        return cls(order_by=None, columns=columns)

    @classmethod
    def max_by(cls, order_by: str, columns: Mapping[str, str] | None = None) -> 'UpdateMergeSpec':
        return cls(order_by=order_by, columns=columns)

    @classmethod
    def latest_or_backfill(cls, order_by: str, *column_names: str) -> 'UpdateMergeSpec':
        return cls(
            order_by=order_by,
            columns={col: UpdateMergeStrategy.LATEST_OR_BACKFILL for col in column_names},
        )

    @classmethod
    def normalize(cls, spec: Any) -> dict[str, Any] | None:
        if spec is None:
            return None
        if isinstance(spec, cls):
            return dict(spec)
        if isinstance(spec, dict):
            unknown = set(spec) - {'order_by', 'columns'}
            if unknown:
                raise ValueError(f'Unknown UpdateMergeSpec fields: {sorted(unknown)!r}')
            return dict(cls(order_by=spec.get('order_by'), columns=spec.get('columns')))
        raise ValueError(f'Invalid UpdateMergeSpec: {spec!r}')

    def to_dict(self) -> dict[str, Any]:
        return dict(self)


class SortDirection:
    ASC = 'asc'
    DESC = 'desc'
    ALL = frozenset({ASC, DESC})


class SortColumn(dict):
    """Exact serde representation of ``docspec_core::SortColumn``."""

    def __init__(self, column: str, direction: str = SortDirection.ASC, *, nulls_first: bool | None = None) -> None:
        if not isinstance(column, str) or not column.strip():
            raise ValueError('SortColumn column must be a non-empty string')
        if not isinstance(direction, str):
            raise ValueError(f'SortColumn direction must be one of {sorted(SortDirection.ALL)!r}')
        dir_lower = direction.lower()
        if dir_lower not in SortDirection.ALL:
            raise ValueError(f'SortColumn direction must be one of {sorted(SortDirection.ALL)!r}')
        payload: dict[str, Any] = {'column': column.strip(), 'direction': dir_lower}
        if nulls_first is not None:
            payload['nulls_first'] = bool(nulls_first)
        super().__init__(payload)

    @property
    def column(self) -> str:
        return self['column']

    @property
    def direction(self) -> str:
        return self['direction']

    @property
    def nulls_first(self) -> bool:
        return self.get('nulls_first', False)

    @classmethod
    def normalize(cls, spec: Any) -> dict[str, Any]:
        if isinstance(spec, cls):
            return dict(spec)
        if isinstance(spec, str):
            return dict(cls(spec, SortDirection.ASC))
        if isinstance(spec, (tuple, list)):
            if len(spec) == 2:
                return dict(cls(spec[0], spec[1]))
            if len(spec) == 3:
                return dict(cls(spec[0], spec[1], nulls_first=spec[2]))
        if isinstance(spec, dict):
            col = spec.get('column') if 'column' in spec else spec.get('field')
            direction = spec.get('direction')
            if direction is None:
                direction = SortDirection.DESC if spec.get('descending', False) else SortDirection.ASC
            nulls_first = spec.get('nulls_first')
            if nulls_first is not None:
                return dict(cls(str(col), str(direction), nulls_first=bool(nulls_first)))
            return dict(cls(str(col), str(direction)))
        raise ValueError(f'Invalid SortColumn: {spec!r}')


class VersionRef(dict):
    """Normalized reference to a dataset version and its manifest pin."""

    def __init__(self, dataset: str, version: str, manifest: Any = None) -> None:
        res: dict[str, Any] = {'dataset': str(dataset), 'version': str(version)}
        if manifest is not None:
            res['manifest'] = dict(manifest) if isinstance(manifest, Mapping) else manifest
        super().__init__(res)

    @property
    def dataset(self) -> str:
        return self['dataset']

    @property
    def version(self) -> str:
        return self['version']

    @property
    def manifest(self) -> Any:
        return self.get('manifest')

    @classmethod
    def normalize(cls, pin: Any) -> dict[str, Any]:
        """Normalize a ReleasePin or VersionRef structure."""
        if isinstance(pin, cls):
            return dict(pin)
        if isinstance(pin, Mapping) and set(pin.keys()) <= {'dataset', 'version', 'manifest'} and 'dataset' in pin and 'version' in pin:
            res = dict(dataset=str(pin['dataset']), version=str(pin['version']))
            manifest = pin.get('manifest')
            if manifest is not None:
                res['manifest'] = dict(manifest) if isinstance(manifest, Mapping) else str(manifest)
            return res
        if isinstance(pin, Mapping) and 'id' in pin and isinstance(pin.get('dataset'), Mapping) and 'dataset' in pin['dataset']:
            res = dict(dataset=str(pin['dataset']['dataset']), version=str(pin['id']))
            manifest = pin.get('manifest')
            if manifest is not None:
                res['manifest'] = dict(manifest) if isinstance(manifest, Mapping) else str(manifest)
            return res
        raise ValueError(f'Expected a ReleasePin or VersionRef dict, got: {pin!r}')

    @classmethod
    def resolve(cls, dataset: str, source_or_version: Any) -> dict[str, Any]:
        """Resolve a version string, dictionary, or ReleasePin into a canonical VersionRef dict."""
        if isinstance(source_or_version, Mapping):
            if {'dataset', 'version', 'manifest'} <= source_or_version.keys() and isinstance(source_or_version['dataset'], str):
                return {
                    'dataset': str(source_or_version['dataset']),
                    'version': str(source_or_version['version']),
                    'manifest': dict(source_or_version['manifest']),
                }
            ds_field = source_or_version.get('dataset')
            resolved_ds = ds_field.get('dataset') if isinstance(ds_field, Mapping) else (ds_field if isinstance(ds_field, str) else dataset)
            resolved_ver = (
                ds_field.get('version')
                if isinstance(ds_field, Mapping) and 'version' in ds_field
                else source_or_version.get('id') or source_or_version.get('version')
            )
            manifest = source_or_version.get('manifest')
            if not isinstance(manifest, Mapping) or not {'owner', 'path', 'digest', 'bytes'} <= manifest.keys():
                raw_digest = (manifest or {}).get('digest', '0' * 64) if isinstance(manifest, Mapping) else '0' * 64
                raw_bytes = int((manifest or {}).get('bytes', (manifest or {}).get('size', 0))) if isinstance(manifest, Mapping) else 0
                raw_path = (manifest or {}).get('path', f'versions/{resolved_ver}/manifest.json') if isinstance(manifest, Mapping) else f'versions/{resolved_ver}/manifest.json'
                manifest = {
                    'owner': str(resolved_ver or resolved_ds),
                    'path': str(raw_path),
                    'digest': str(raw_digest),
                    'bytes': raw_bytes,
                }
            return {
                'dataset': str(resolved_ds),
                'version': str(resolved_ver),
                'manifest': dict(manifest),
            }
        if isinstance(source_or_version, str) and source_or_version.strip():
            ver = source_or_version.strip()
            return {
                'dataset': str(dataset),
                'version': ver,
                'manifest': {
                    'owner': ver,
                    'path': f'versions/{ver}/manifest.json',
                    'digest': '0' * 64,
                    'bytes': 0,
                },
            }
        raise ValueError(f'Invalid source or version specification: {source_or_version!r}')
