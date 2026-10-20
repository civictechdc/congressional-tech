"""Read exact selected native source partitions with application Arrow metadata.

This module does not choose publication state or issue semantic validation.
The application selector owns the complete table selection and the original
schema. Native completion alone does not prove catalog reference consistency.
"""
from copy import deepcopy

import pyarrow as pa
import pyarrow.compute as pc


class CatalogTable:
    """A logical catalog table backed by explicitly selected bounded partitions.

    Partition iteration follows selector order. Rows within a partition follow
    the native source stream; callers needing stable top-level row positions
    must supply and validate application ordering before deriving mappings.
    """

    def __init__(self, schema, partitions, *, native, order_column=None, max_ordered_bytes=None, views=None):
        if not isinstance(schema, pa.Schema):
            raise TypeError('A selected catalog table requires its application Arrow schema')
        self.schema_arrow = schema
        self.native = native
        if order_column is not None:
            if (not isinstance(order_column, str) or not order_column or order_column in schema.names
                    or type(max_ordered_bytes) is not int or max_ordered_bytes < 1):
                raise ValueError('Ordered catalog reads require a separate order field and explicit byte bound')
        elif max_ordered_bytes is not None:
            raise ValueError('An ordered read byte bound requires an order field')
        self.order_column, self.max_ordered_bytes = order_column, max_ordered_bytes
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
        self._views = deepcopy(views) if views is not None else None
        if self._views is not None:
            if set(self._views) != names or 'document_id' not in schema.names:
                raise ValueError('Catalog views must describe every selected pin and its document membership')
            for name, _, rows in self._partitions:
                view = self._views[name]
                components = view.get('components', [])
                if (not isinstance(components, list) or not components
                        or any(not isinstance(value, str) or not value for value in components)
                        or len(set(components)) != len(components)
                        or type(view.get('rows')) is not int or not 0 < view['rows'] <= rows):
                    raise ValueError('Invalid selected catalog membership view')
        self.rows = sum(self._views[name]['rows'] if self._views is not None else rows
                        for name, _, rows in self._partitions)

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
            batches = self._partition_batches(name, pin, rows)
            if self.order_column is not None:
                # Only one caller-bounded native chunk is buffered. This caps
                # admitted Arrow input bytes; sorting also allocates its output
                # and indices, so it is not a whole-process memory guarantee.
                retained, size = [], 0
                for batch in batches:
                    size += batch.nbytes
                    if size > self.max_ordered_bytes:
                        raise ValueError(f'Ordered catalog partition exceeds Arrow byte bound: {name}')
                    retained.append(batch)
                if not retained:
                    continue
                table = pa.Table.from_batches(retained)
                order = table[self.order_column]
                if order.null_count or len(pc.unique(order)) != table.num_rows:
                    raise ValueError(f'Catalog order values must be nonnull and unique: {name}')
                batches = table.sort_by([(self.order_column, 'ascending')]).to_batches()
            view = self._views[name] if self._views is not None else None
            selected_rows = 0
            for batch in batches:
                if view is not None:
                    batch = batch.filter(pc.is_in(batch.column('document_id'),
                        value_set=pa.array(view['components'], type=pa.string())))
                    selected_rows += batch.num_rows
                    if selected_rows > view['rows']:
                        raise ValueError(f'Catalog view row count differs: {name}')
                if not batch.num_rows:
                    continue
                selected = batch.select(columns)
                yield pa.RecordBatch.from_arrays(selected.columns, schema=output_schema)
            if view is not None and selected_rows != view['rows']:
                raise ValueError(f'Catalog view row count differs: {name}')

    def _partition_batches(self, name, pin, rows):
        def require_schema(schema):
            if self.order_column is not None:
                if (schema.names.count(self.order_column) != 1
                        or not pa.types.is_int64(schema.field(self.order_column).type)):
                    raise ValueError(f'Native catalog order field must be int64: {name}')
                schema = pa.schema([field for field in schema if field.name != self.order_column])
            if not schema.equals(self.schema_arrow, check_metadata=False):
                raise ValueError(f'Native catalog partition schema differs: {name}')

        count = 0
        with self.native.source_batches(deepcopy(pin)) as reader:
            require_schema(reader.schema)
            for batch in reader:
                require_schema(batch.schema)
                count += batch.num_rows
                if count > rows:
                    raise ValueError(f'Native catalog partition row count differs: {name}')
                yield batch
        if count != rows:
            raise ValueError(f'Native catalog partition row count differs: {name}')
