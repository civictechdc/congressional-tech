"""Typed models and specifications for the DocSpec client."""
from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any


ARROW_STREAM_MIME = 'application/vnd.apache.arrow.stream'
VALID_UPDATE_MERGE_STRATEGIES = ('replace', 'latest_or_backfill', 'min', 'max', 'set_union')
SUPPORTED_PLATFORMS = ('linux-amd64', 'darwin-arm64', 'darwin-amd64')
PRODUCER_PARQUET_ROW_GROUP_SIZE = 2048

REQUIRED_LOOPBACK_CAPABILITIES = ('request-deadline', 'owned-stdin-eof')
RESPONSE_LIMIT = 1 << 20  # 1 MiB bounded metadata response limit

QUALIFIED_DOCSPEC_RUNTIME = {
    'source_revision': 'c949c6762f001845d2933e55cb9d7cf237e80810',
    'darwin_arm64_binary_sha256': 'f2ba93a6cea4bccd95bf7dc6cfbfff587482f2ea29aa096c6527371991dddfb6',
    'build_features': ('remote',),
    'required_capabilities': REQUIRED_LOOPBACK_CAPABILITIES,
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


class ConnectedEdgeSpec(dict):
    """Exact serde representation of a connected-components edge projection."""

    def __init__(self, namespace: str, column: str) -> None:
        if not isinstance(namespace, str) or not namespace.strip():
            raise ValueError('ConnectedEdgeSpec namespace must be a non-empty string')
        if not isinstance(column, str) or not column.strip():
            raise ValueError('ConnectedEdgeSpec column must be a non-empty string')
        super().__init__(namespace=namespace.strip(), column=column.strip())

    @classmethod
    def normalize(cls, spec: Any) -> dict[str, Any]:
        if isinstance(spec, cls):
            return dict(spec)
        if isinstance(spec, (tuple, list)) and len(spec) == 2:
            return dict(cls(spec[0], spec[1]))
        if isinstance(spec, dict):
            unknown = set(spec) - {'namespace', 'column'}
            if unknown:
                raise ValueError(f'Unknown ConnectedEdgeSpec fields: {sorted(unknown)!r}')
            return dict(cls(spec.get('namespace', ''), spec.get('column', '')))
        raise ValueError(f'Invalid ConnectedEdgeSpec: {spec!r}')


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


class AggregateSpec:
    """Builder methods for supported target-column aggregation specifications."""

    VALID_KINDS = frozenset({
        'count_rows', 'count_distinct', 'sum', 'min', 'max', 'collect_set', 'first_value', 'count',
    })

    @staticmethod
    def count_rows(name: str = 'total_rows') -> dict[str, Any]:
        return {'name': str(name), 'function': {'kind': 'count_rows'}}

    @staticmethod
    def count(name_or_field: str = 'total_rows', field: str | None = None, *, name: str | None = None) -> dict[str, Any]:
        if name is not None:
            return {'name': str(name), 'function': {'kind': 'count_rows'}}
        return {'name': str(name_or_field), 'function': {'kind': 'count_rows'}}

    @staticmethod
    def count_distinct(name_or_field: str, field: str | None = None, *, name: str | None = None) -> dict[str, Any]:
        if name is not None:
            return {'name': str(name), 'function': {'kind': 'count_distinct', 'field': str(name_or_field)}}
        return {'name': str(name_or_field), 'function': {'kind': 'count_distinct', 'field': str(field or name_or_field)}}

    @staticmethod
    def sum(name_or_field: str, field: str | None = None, *, name: str | None = None) -> dict[str, Any]:
        if name is not None:
            return {'name': str(name), 'function': {'kind': 'sum', 'field': str(name_or_field)}}
        return {'name': str(name_or_field), 'function': {'kind': 'sum', 'field': str(field or name_or_field)}}

    @staticmethod
    def min(name_or_field: str, field: str | None = None, *, name: str | None = None) -> dict[str, Any]:
        if name is not None:
            return {'name': str(name), 'function': {'kind': 'min', 'field': str(name_or_field)}}
        return {'name': str(name_or_field), 'function': {'kind': 'min', 'field': str(field or name_or_field)}}

    @staticmethod
    def max(name_or_field: str, field: str | None = None, *, name: str | None = None) -> dict[str, Any]:
        if name is not None:
            return {'name': str(name), 'function': {'kind': 'max', 'field': str(name_or_field)}}
        return {'name': str(name_or_field), 'function': {'kind': 'max', 'field': str(field or name_or_field)}}

    @staticmethod
    def collect_set(name_or_field: str, field: str | None = None, *, name: str | None = None) -> dict[str, Any]:
        if name is not None:
            return {'name': str(name), 'function': {'kind': 'collect_set', 'field': str(name_or_field)}}
        return {'name': str(name_or_field), 'function': {'kind': 'collect_set', 'field': str(field or name_or_field)}}

    @staticmethod
    def first_value(name_or_field: str, field: str | None = None, *, name: str | None = None) -> dict[str, Any]:
        if name is not None:
            return {'name': str(name), 'function': {'kind': 'first_value', 'field': str(name_or_field)}}
        return {'name': str(name_or_field), 'function': {'kind': 'first_value', 'field': str(field or name_or_field)}}

    @classmethod
    def normalize(cls, spec: Any) -> dict[str, Any]:
        if not isinstance(spec, dict):
            raise ValueError(f'Invalid AggregateColumn specification: {spec!r}')
        if 'kind' in spec and 'field' in spec and 'name' in spec:
            return {'name': str(spec['name']), 'function': {'kind': str(spec['kind']), 'field': str(spec['field'])}}
        if 'kind' in spec and 'name' in spec and len(spec) == 2:
            return {'name': str(spec['name']), 'function': {'kind': str(spec['kind'])}}
        unknown = set(spec) - {'name', 'function'}
        if unknown:
            raise ValueError(f'Unknown AggregateColumn fields: {sorted(unknown)!r}')
        name = spec.get('name')
        fn = spec.get('function')
        if not isinstance(name, str) or not name.strip() or not isinstance(fn, dict):
            raise ValueError(f'Invalid AggregateColumn specification: {spec!r}')
        kind = fn.get('kind')
        if kind not in cls.VALID_KINDS:
            raise ValueError(f'Invalid AggregateFunction kind: {kind!r}')
        if kind == 'count_rows':
            if set(fn) != {'kind'}:
                raise ValueError('count_rows aggregate does not take extra fields')
            return {'name': name, 'function': {'kind': 'count_rows'}}
        if set(fn) != {'kind', 'field'} or not isinstance(fn.get('field'), str) or not fn['field'].strip():
            raise ValueError(f'AggregateFunction {kind!r} requires a non-empty field name')
        return {'name': name, 'function': {'kind': kind, 'field': fn['field']}}


class ConnectedComponentsTransform(dict):
    """Exact serde representation of ``RefreshTransform::ConnectedComponents``."""

    def __init__(
        self,
        input_pin: Any = None,
        *,
        row_key: str = 'source_id',
        entity_key: str | None = None,
        edges: Any = (
            dict(namespace='canonical', column='canonical_key'),
            dict(namespace='body', column='connectable_body_key'),
        ),
        order_by: Any = ('priority_rank', 'source_id'),
        document_id_column: str = 'document_id',
        component_id_column: str | None = None,
        component_size_column: str | None = None,
        max_iterations: int = 20,
        aggregates: Any = (),
        outputs: Any = None,
    ) -> None:
        effective_row_key = entity_key if entity_key is not None else row_key
        effective_doc_id = component_id_column if component_id_column is not None else document_id_column
        effective_aggregates = outputs if outputs is not None else aggregates
        if not isinstance(effective_row_key, str) or not effective_row_key.strip():
            raise ValueError('ConnectedComponentsTransform row_key must be a non-empty string')
        if not isinstance(effective_doc_id, str) or not effective_doc_id.strip():
            raise ValueError('ConnectedComponentsTransform document_id_column must be a non-empty string')
        normalized_edges = [ConnectedEdgeSpec.normalize(e) for e in (edges or ())]
        if not normalized_edges:
            raise ValueError('ConnectedComponentsTransform requires at least one edge specification')
        normalized_order_by = [SortColumn.normalize(c) for c in (order_by or ())]
        normalized_aggregates = [AggregateSpec.normalize(a) for a in (effective_aggregates or ())]
        payload: dict[str, Any] = {
            'kind': 'connected_components',
            'row_key': effective_row_key,
            'edges': normalized_edges,
            'order_by': normalized_order_by,
            'document_id_column': effective_doc_id,
            'aggregates': normalized_aggregates,
            'max_iterations': int(max_iterations),
        }
        if component_size_column is not None:
            payload['component_size_column'] = str(component_size_column)
        if input_pin is not None:
            payload['input'] = VersionRef.normalize(input_pin)
        super().__init__(payload)

    def to_dict(self) -> dict[str, Any]:
        return dict(self)


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
