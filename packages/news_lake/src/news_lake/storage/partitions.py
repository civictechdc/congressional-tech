"""I5 time-partitioned Iceberg table layout for multi-decade corpora.

Per 03-iceberg-profile.md (I5):
- Append-only capture and discovery tables partition on ``observed_at``.
- Other append-only tables partition on ``recorded_at``.
- Upsert dimension tables (``outlets``, ``items``, ``entities``) remain
  unpartitioned so logical-key upserts by ``id`` never scatter across time
  partitions or partition articles by politician.
"""
import pyarrow as pa
from pyiceberg.exceptions import NamespaceAlreadyExistsError, NotInstalledError, TableAlreadyExistsError
from pyiceberg.partitioning import PartitionField, PartitionSpec
from pyiceberg.transforms import DayTransform, MonthTransform

from news_lake.contract.records import KIND_ORDER, KIND_TABLES
from news_lake.storage.catalog import NAMESPACE
from news_lake.storage.mapping import iceberg_schema


def _ensure_pyarrow_time_transforms():
    """Fall back to PyIceberg's pure-Python scalar transform when pyiceberg_core is absent."""
    for transform_cls in (MonthTransform, DayTransform):
        original = transform_cls.pyarrow_transform
        if getattr(original, '_news_lake_fallback', False):
            continue

        def _make_wrapper(orig):
            def _pyarrow_transform(self, source):
                try:
                    return orig(self, source)
                except NotInstalledError:
                    scalar_fn = self.transform(source)

                    def _apply(array):
                        if isinstance(array, pa.ChunkedArray):
                            return pa.chunked_array(
                                [
                                    pa.array([scalar_fn(v) for v in chunk.to_pylist()], type=pa.int32())
                                    for chunk in array.iterchunks()
                                ],
                                type=pa.int32(),
                            )
                        return pa.array([scalar_fn(v) for v in array.to_pylist()], type=pa.int32())

                    return _apply

            _pyarrow_transform._news_lake_fallback = True
            return _pyarrow_transform

        transform_cls.pyarrow_transform = _make_wrapper(original)


_ensure_pyarrow_time_transforms()

PARTITION_FIELD_ID_START = 1000

PARTITION_COLUMNS = {
    'outlet': None,
    'capture': 'observed_at',
    'discovery': 'observed_at',
    'item': None,
    'version': 'recorded_at',
    'entity': None,
    'identity_decision': 'recorded_at',
    'run': 'recorded_at',
    'mention': 'recorded_at',
    'classification': 'recorded_at',
    'story': 'recorded_at',
    'story_member': 'recorded_at',
    'release': 'recorded_at',
}

_TRANSFORMS = {
    'month': MonthTransform,
    'day': DayTransform,
}


def partition_spec_for(kind, schema=None, *, granularity='month'):
    """Build the I5 Iceberg PartitionSpec for ``kind`` and ``schema``."""
    if kind not in PARTITION_COLUMNS:
        raise ValueError(f'unknown record kind: {kind!r}')
    if granularity in ('unpartitioned', None):
        return PartitionSpec()
    if granularity not in _TRANSFORMS:
        raise ValueError(f'unsupported partition granularity: {granularity!r}')
    column = PARTITION_COLUMNS[kind]
    if column is None:
        return PartitionSpec()
    if schema is None:
        schema = iceberg_schema(kind)
    source_field = schema.find_field(column)
    transform = _TRANSFORMS[granularity]()
    return PartitionSpec(
        PartitionField(
            source_id=source_field.field_id,
            field_id=PARTITION_FIELD_ID_START,
            transform=transform,
            name=f'{column}_{granularity}',
        )
    )


def create_partitioned_tables(lake, *, granularity='month'):
    """Create the ``news`` namespace and all 13 tables with I5 partition specs."""
    try:
        lake.catalog.create_namespace((NAMESPACE,))
    except NamespaceAlreadyExistsError:
        pass
    for kind in KIND_ORDER:
        table = KIND_TABLES[kind]
        schema = iceberg_schema(kind)
        spec = partition_spec_for(kind, schema, granularity=granularity)
        try:
            lake.catalog.create_table(
                (NAMESPACE, table.split('.', 1)[1]),
                schema=schema,
                partition_spec=spec,
                properties={'format-version': '2'},
            )
        except TableAlreadyExistsError:
            pass
    return lake
