"""Read exact selected native source partitions with application Arrow metadata.

This module does not choose publication state or issue semantic validation.
The application selector owns the complete table selection and the original
schema. Native completion alone does not prove catalog reference consistency.
"""
from copy import deepcopy

import pyarrow as pa


class CatalogTable:
    """A logical catalog table backed by explicitly selected bounded partitions.

    Partition iteration follows selector order. Rows within a partition follow
    the native source stream; callers needing stable top-level row positions
    must supply and validate application ordering before deriving mappings.
    """

    def __init__(self, schema, partitions, *, native):
        if not isinstance(schema, pa.Schema):
            raise TypeError('A selected catalog table requires its application Arrow schema')
        self.schema_arrow = schema
        self.native = native
        self._partitions = []
        names = set()
        for name, release in partitions:
            if not isinstance(name, str) or not name or name in names:
                raise ValueError('Catalog partition names must be nonempty and unique')
            pin = deepcopy(release)
            dataset = pin.get('dataset', {})
            groups = dataset.get('groups', {})
            if (pin.get('verified') is not True or set(groups) != {'source'}
                    or dataset.get('computed') or dataset.get('related') is not None
                    or dataset.get('evidence') is not None):
                raise ValueError('Catalog partitions require completed source-only native releases')
            rows = groups['source'].get('rows')
            if type(rows) is not int or rows < 0:
                raise ValueError('Catalog partition has an invalid selected row count')
            names.add(name)
            self._partitions.append((name, pin, rows))
        self.partition_names = tuple(name for name, _, _ in self._partitions)
        self.rows = sum(rows for _, _, rows in self._partitions)

    def iter_batches(self, *, partitions=None, columns=None):
        """Read requested partitions only, checking types before restoring metadata.

        The maintained CLI currently reads every column of a selected partition;
        column selection happens after that bounded native read. No complete
        logical-table file is exported or materialized by this reader.
        """
        requested = self.partition_names if partitions is None else tuple(partitions)
        requested_set = set(requested)
        if len(requested_set) != len(requested) or requested_set - set(self.partition_names):
            raise ValueError('Requested catalog partitions must be distinct selected names')
        columns = self.schema_arrow.names if columns is None else list(columns)
        if not columns or len(set(columns)) != len(columns) or set(columns) - set(self.schema_arrow.names):
            raise ValueError('Requested catalog columns must be nonempty distinct selected fields')
        output_schema = pa.schema([self.schema_arrow.field(name) for name in columns],
                                  metadata=self.schema_arrow.metadata)
        for name, pin, rows in self._partitions:
            if name not in requested_set:
                continue
            count = 0
            with self.native.source_batches(deepcopy(pin)) as reader:
                if not reader.schema.equals(self.schema_arrow, check_metadata=False):
                    raise ValueError(f'Native catalog partition schema differs: {name}')
                for batch in reader:
                    if not batch.schema.equals(self.schema_arrow, check_metadata=False):
                        raise ValueError(f'Native catalog partition batch schema differs: {name}')
                    count += batch.num_rows
                    if count > rows:
                        raise ValueError(f'Native catalog partition row count differs: {name}')
                    selected = batch.select(columns)
                    yield pa.RecordBatch.from_arrays(selected.columns, schema=output_schema)
            if count != rows:
                raise ValueError(f'Native catalog partition row count differs: {name}')
