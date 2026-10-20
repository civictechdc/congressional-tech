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


def counted_reads(memberships):
    original, calls = memberships._read, []
    def read(pin, schema):
        calls.append((pin.copy(), schema))
        return original(pin, schema)
    memberships._read = read
    return calls


def test_shared_leaf_aliases_read_once_and_old_selection_remains_exact():
    _, memberships = owner()
    root = memberships.replace(None, {'event:7': ['first'], 'event:8': ['other']})
    reads = counted_reads(memberships)
    for _ in range(4):
        assert list(memberships.values(root, 'event:7')) == ['first']
        assert list(memberships.values(root, 'event:8')) == ['other']
    assert len(reads) == 1
    changed = memberships.replace(root, {'event:7': ['corrected']})
    assert list(memberships.values(changed, 'event:7')) == ['corrected']
    assert list(memberships.values(changed, 'event:8')) == ['other']
    assert list(memberships.values(root, 'event:7')) == ['first']
    assert len(reads) == 3


def test_leaf_reuse_revalidates_full_descriptor_and_exact_owner_schema():
    from copy import deepcopy
    _, memberships = owner()
    root = memberships.replace(None, {'event:7': ['first']})
    _, descriptor = memberships.routes.lookup(root, 'event:7')
    reads = counted_reads(memberships)
    memberships._groups(descriptor)
    memberships._groups(dict(reversed(list(descriptor.items()))))
    assert len(reads) == 1
    # Mutating the caller's descriptor cannot silently change the retained key.
    original = deepcopy(descriptor)
    descriptor['rows'] += 1
    with pytest.raises(DependencyGap, match='row count'):
        memberships._groups(descriptor)
    assert len(reads) == 2
    # A changed pin or any other selected metadata requires fresh validation.
    for key, value in [('release', dict(original['release'], id='different-pin')),
                       ('arrow_bytes', original['arrow_bytes'] + 1)]:
        changed = dict(original, **{key: value})
        before = len(reads)
        memberships._groups(changed)
        assert len(reads) == before + 1
    before = len(reads)
    memberships.schema = SCHEMA.with_metadata({b'candidate': b'new-schema-owner'})
    groups = memberships._groups(changed)
    assert len(reads) == before + 1
    assert groups['event:7'].schema.equals(memberships.schema, check_metadata=True)


def test_leaf_cache_retains_one_leaf_and_returns_immutable_groups():
    _, memberships = owner()
    a = memberships.replace(None, {'event:7': ['first']})
    b = memberships.replace(None, {'event:8': ['other']})
    reads = counted_reads(memberships)
    assert list(memberships.values(a, 'event:7')) == ['first']
    _, descriptor = memberships.routes.lookup(a, 'event:7')
    groups = memberships._groups(descriptor)
    with pytest.raises(TypeError):
        groups['event:7'] = pa.Table.from_pylist([], schema=SCHEMA)
    rows = groups['event:7'].to_pylist()
    rows[0]['observation_id'] = 'caller mutation'
    assert list(memberships.values(a, 'event:7')) == ['first']
    assert list(memberships.values(b, 'event:8')) == ['other']
    assert list(memberships.values(a, 'event:7')) == ['first']
    assert len(reads) == 3


@pytest.mark.parametrize('failure', ['row count', 'Duplicate', 'read failure'])
def test_failed_leaf_validation_is_not_cached_and_retry_can_succeed(failure):
    _, memberships = owner()
    root = memberships.replace(None, {'event:7': ['first'], 'event:8': ['other']})
    read, calls = memberships._read, []
    def transient_duplicate(pin, schema):
        calls.append(pin)
        table = read(pin, schema)
        if len(calls) == 1:
            if failure == 'read failure':
                raise DependencyGap('read failure')
            if failure == 'Duplicate':
                return pa.concat_tables([table.slice(0, 1), table.slice(0, 1)])
            return pa.concat_tables([table, table])
        return table
    memberships._read = transient_duplicate
    with pytest.raises(DependencyGap, match=failure):
        list(memberships.values(root, 'event:7'))
    assert list(memberships.values(root, 'event:7')) == ['first']
    assert list(memberships.values(root, 'event:7')) == ['first']
    assert len(calls) == 2
