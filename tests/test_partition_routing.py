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
