"""SqlCatalog-backed lake: the news namespace and the 13 schema-derived tables.

The persisted field ids are assigned by the catalog at table creation; writes
always go through the table's own schema so ids are never taken from column
order. Table UUIDs come from the catalog and are stable for the warehouse.
"""
from contextlib import contextmanager
from pathlib import Path

from pyiceberg.catalog.sql import SqlCatalog
from pyiceberg.exceptions import NamespaceAlreadyExistsError, TableAlreadyExistsError

from news_lake.contract.records import KIND_ORDER, KIND_TABLES, SCHEMA, TABLE_KINDS
from news_lake.storage import mapping
from news_lake.storage.mapping import iceberg_schema

NAMESPACE = 'news'


class Lake:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.warehouse = self.root / 'warehouse'
        self.warehouse.mkdir(parents=True, exist_ok=True)
        self.catalog = SqlCatalog(
            'news_lake',
            uri=f'sqlite:///{self.root / "catalog.db"}',
            warehouse=self.warehouse.as_uri(),
        )
        self._commit_table_raw = self.catalog.commit_table
        self._commit_guard = None
        self.catalog.commit_table = self._guarded_commit_table
        self._arrow_schemas = {}
        self._allowed_extras = {}
        self._table_uuids = {}

    @contextmanager
    def fenced_commit(self, control, epoch):
        """Hold the control-store fence lock across each Iceberg catalog commit.

        Parquet and manifest files are written first; at the instant PyIceberg
        commits the metadata pointer swap in catalog.db (SqlCatalog.commit_table),
        _guarded_commit_table enters control._write_tx(epoch), serializing the
        catalog CAS commit against any concurrent control.claim().
        """
        prior = self._commit_guard
        self._commit_guard = (control, epoch)
        try:
            yield
        finally:
            self._commit_guard = prior

    def _guarded_commit_table(self, table, requirements, updates):
        if self._commit_guard is not None:
            control, epoch = self._commit_guard
            with control._write_tx(epoch):
                return self._commit_table_raw(table, requirements, updates)
        return self._commit_table_raw(table, requirements, updates)

    def create_tables(self, *, granularity=None):
        if granularity not in (None, 'unpartitioned'):
            from news_lake.storage.partitions import create_partitioned_tables

            return create_partitioned_tables(self, granularity=granularity)
        try:
            self.catalog.create_namespace((NAMESPACE,))
        except NamespaceAlreadyExistsError:
            pass
        for kind in KIND_ORDER:
            table = KIND_TABLES[kind]
            try:
                self.catalog.create_table(
                    (NAMESPACE, table.split('.', 1)[1]),
                    schema=iceberg_schema(kind),
                    properties={'format-version': '2'},
                )
            except TableAlreadyExistsError:
                pass
        return self

    def table(self, table_name):
        return self.catalog.load_table((NAMESPACE, table_name.split('.', 1)[1]))

    def arrow_schema(self, table_name, table=None):
        """The table's authoritative Arrow schema, cached per (table, schema_id)."""
        table = table if table is not None else self.table(table_name)
        schema_id = table.metadata.current_schema_id
        cached = self._arrow_schemas.get(table_name)
        if not isinstance(cached, tuple) or cached[0] != schema_id:
            cached = (schema_id, table.schema().as_arrow())
            self._arrow_schemas[table_name] = cached
        return cached[1]

    def allowed_extra(self, table_name, table=None):
        """Evolved optional columns on a table beyond the JSON Schema, cached per schema_id."""
        table = table if table is not None else self.table(table_name)
        schema_id = table.metadata.current_schema_id
        cached = self._allowed_extras.get(table_name)
        if not isinstance(cached, tuple) or cached[0] != schema_id:
            kind = TABLE_KINDS[table_name]
            defined = set(SCHEMA['$defs'][kind].get('properties', {}))
            columns = {field.name for field in table.schema().fields}
            cached = (schema_id, frozenset(columns - defined - {'kind'}))
            self._allowed_extras[table_name] = cached
        return cached[1]

    def table_uuid(self, table_name, table=None):
        if table is not None:
            uuid_str = str(table.metadata.table_uuid)
            self._table_uuids[table_name] = uuid_str
            return uuid_str
        cached = self._table_uuids.get(table_name)
        if cached is None:
            cached = str(self.table(table_name).metadata.table_uuid)
            self._table_uuids[table_name] = cached
        return cached

    def read_all(self, table_name):
        """Export every record from the current snapshot of a table."""
        table = self.table(table_name)
        snapshot = table.current_snapshot()
        if snapshot is None:
            return []
        return mapping.from_arrow_table(TABLE_KINDS[table_name], table.scan(snapshot_id=snapshot.snapshot_id).to_arrow())
