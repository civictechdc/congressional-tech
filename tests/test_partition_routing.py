"""A full affected partition splits locally; unrelated routing stays usable."""
import pyarrow as pa
import pytest

from congress_api.retention.partition_routing import key_hash, route_prefix, split_partition


def test_split_only_affected_leaf_preserves_every_row_and_routes():
    rows = [dict(key=f'url-{i}', value=['', str(i)]) for i in range(12)]
    table = pa.Table.from_pylist(rows)
    leaves = split_partition(table, key='key', prefix='', max_rows=2, max_bytes=4096)
    assert sum(len(value) for _, value in leaves) == len(table)
    assert all(len(value) <= 2 for _, value in leaves)
    assert sorted(r['key'] for _, value in leaves for r in value.to_pylist()) == sorted(r['key'] for r in rows)
    prefixes = [prefix for prefix, _ in leaves]
    for index in range(64):
        assert route_prefix(f'future-key-{index}', prefixes) in prefixes
    for prefix, value in leaves:
        for row in value.to_pylist():
            assert route_prefix(row['key'], prefixes) == prefix
    untouched = next(prefix for prefix, value in leaves if len(value) == 1)
    target = next((prefix, value) for prefix, value in leaves if len(value) == 2)
    revised = split_partition(target[1], key='key', prefix=target[0], max_rows=1, max_bytes=4096)
    assert all(prefix.startswith(target[0]) for prefix, _ in revised)
    assert untouched not in [prefix for prefix, _ in revised]
    assert len(key_hash('url-0')) == 64


def test_invalid_routing_and_unsplittable_values_fail_explicitly():
    with pytest.raises(ValueError, match='ambiguous'):
        route_prefix('one', ['', key_hash('one')[:1]])
    with pytest.raises(ValueError, match='Missing'):
        route_prefix('one', ['unrelated'])
    table = pa.table({'key': ['one'], 'large': ['x' * 100]})
    with pytest.raises(ValueError, match='single row'):
        split_partition(table, key='key', prefix='', max_rows=1, max_bytes=16)
    with pytest.raises(ValueError, match='Duplicate'):
        split_partition(pa.table({'key': ['one', 'one']}), key='key', prefix='', max_rows=1, max_bytes=4096)


def test_immutable_routing_pages_rewrite_only_changed_path_and_keep_old_root():
    from congress_api.retention.partition_routing import RoutingPages
    from test_raw_capture_pages import Store

    store = Store()
    routes = RoutingPages(store, 'raw-state-v1')
    root = routes.replace(None, '', {'': {'dataset': 'old', 'version': 'initial'}})
    prefix, old = routes.lookup(root, 'one')
    assert prefix == '' and old['dataset'] == 'old'
    children = {char: {'dataset': f'child-{char}', 'version': 'initial'}
                for char in '0123456789abcdef'}
    split = routes.replace(root, '', children)
    before = dict(store.objects)
    leaf, value = routes.lookup(split, 'one')
    store.writes.clear()
    changed = routes.replace(split, leaf, {leaf: {'dataset': 'changed', 'version': 'initial'}})
    assert len(store.writes) == 2  # new leaf + its root, all siblings reused
    assert all(store.objects[key] == raw for key, raw in before.items())
    assert routes.lookup(changed, 'one')[1]['dataset'] == 'changed'
    assert routes.lookup(split, 'one')[1] == value
    assert routes.lookup(root, 'one')[1]['dataset'] == 'old'
    assert len(list(routes.leaf_items(changed))) == 16


def test_empty_child_insertion_and_fresh_reader_verify_exact_metadata():
    from congress_api.retention.partition_routing import RoutingPages
    from test_raw_capture_pages import Store

    store = Store()
    routes = RoutingPages(store, 'catalog-sources-v1')
    key = 'one'
    prefix = key_hash(key)[:1]
    root = routes.replace(None, '', {prefix: {'dataset': 'one', 'version': 'initial'}})
    fresh = RoutingPages(store, 'catalog-sources-v1')
    assert fresh.lookup(root, key)[1]['dataset'] == 'one'
    other = next(f'other-{i}' for i in range(100) if key_hash(f'other-{i}')[:1] != prefix)
    missing, value = fresh.lookup(root, other)
    assert value is None
    root2 = fresh.replace(root, missing, {missing: {'dataset': 'two', 'version': 'initial'}})
    assert fresh.lookup(root2, other)[1]['dataset'] == 'two'
    with pytest.raises(ValueError, match='leaf'):
        fresh.replace(root2, '', {'': {'dataset': 'replace-whole-tree'}})
    store.objects[root['key']] = b'corrupt'
    with pytest.raises(ValueError, match='identity'):
        RoutingPages(store, 'catalog-sources-v1').lookup(root, key)


def test_metadata_reference_is_rejected_before_any_object_read():
    from congress_api.retention.immutable_metadata import MetadataObjects
    from test_raw_capture_pages import Store

    store = Store()
    objects = MetadataObjects(store, 'raw-state-v1', max_bytes=1024)
    good = objects.put({'value': 'one'})
    store.reads.clear()
    with pytest.raises(ValueError, match='identity'):
        objects.read({**good, 'key': 'bodies/large.gz'})
    with pytest.raises(ValueError, match='identity'):
        objects.read({**good, 'bytes': 1025})
    with pytest.raises(ValueError, match='identity'):
        objects.read({**good, 'sha256': '../not-a-digest'})
    assert store.reads == []
