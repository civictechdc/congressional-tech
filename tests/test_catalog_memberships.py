"""One catalog member layout supports grouped sources and receipt dependencies."""
import pyarrow as pa
import pytest

from test_catalog_dependency_storage import MemoryNative
from test_raw_source_sync import MemoryStore
from congress_api.retention.catalog_memberships import CatalogMemberships
from congress_api.retention.catalog_dependencies import DependencyGap


SCHEMA = pa.schema([pa.field('alias', pa.string(), nullable=False),
                   pa.field('observation_id', pa.string(), nullable=False)])


def owner():
    native, store = MemoryNative(), MemoryStore()
    def read(pin, schema):
        return native.tables[pin['dataset_key']].cast(schema)
    def write(table, kind):
        import hashlib
        key = hashlib.sha256(str(table.to_pylist()).encode()).hexdigest()
        return native.run_table(table, dataset=kind + key, operation='initial', definition='test')
    return native, CatalogMemberships(store=store, namespace='observations', schema=SCHEMA,
        member_column='observation_id', max_rows=4, max_bytes=1024,
        read=read, write=write, validate_alias=lambda value: value)


def test_large_receipt_dependency_streams_to_bounded_member_leaves_without_second_iteration():
    native, memberships = owner()
    class OnePass:
        used = False
        def __iter__(self):
            assert not self.used
            self.used = True
            yield from (f'receipt-{i}' for i in range(1000))
        def __len__(self):
            raise AssertionError('The complete membership must not be collected')
    root = memberships.replace(None, {'event:7': OnePass()})
    assert all(len(table) <= 4 and table.nbytes <= 1024 for table in native.tables.values())
    assert set(memberships.values(root, 'event:7')) == {f'receipt-{i}' for i in range(1000)}
    assert list(memberships.values(root, 'event:absent')) == []
    updated = memberships.replace(root, {'event:7': ['new-receipt']})
    assert list(memberships.values(updated, 'event:7')) == ['new-receipt']
    assert len(list(memberships.values(root, 'event:7'))) == 1000


def test_duplicate_large_memberships_refuse_before_any_native_build():
    native, memberships = owner()
    with pytest.raises(DependencyGap, match='Duplicate'):
        memberships.replace(None, {'event:7': iter(['a', 'b', 'c', 'd', 'a'])})
    assert not native.calls
