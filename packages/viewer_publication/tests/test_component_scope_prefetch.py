"""Fresh component scope overlaps verified metadata reads, not SQLite mutations."""
from collections import Counter
import json
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest

from congress_api.retention.catalog_selection import CatalogComponents
from congress_api.retention.partition_routing import RoutingPages, key_hash
from viewer_publication import filename_native as native


class Store:
    def __init__(self):
        self.objects = {}
        self.reads = []
        self.active = self.peak = 0
        self.lock = threading.Lock()
        self.bad = None
        self.fail = None

    def put(self, key, raw, **kwargs):
        self.objects[key] = raw

    def read(self, key):
        with self.lock:
            self.reads.append(key)
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(.001)
            if key == self.fail:
                raise OSError('metadata unavailable')
            return b'corrupt' if key == self.bad else self.objects[key]
        finally:
            with self.lock:
                self.active -= 1


def tree():
    store = Store()
    routes = RoutingPages(store, 'catalog-component-selection-v2')
    leaves = {}
    for index in range(256):
        name = f'component-{index}'
        members = leaves.setdefault(key_hash(name)[:2], dict(members={}))['members']
        members[name] = dict(component=name, page=dict(key='proof/' + name, sha256='a' * 64, bytes=1))
    root = routes.replace(None, '', leaves)
    return store, root


def owner(store):
    db = sqlite3.connect(':memory:')
    snapshot = SimpleNamespace(store=store, components=CatalogComponents(store))
    assets = SimpleNamespace(read_node=lambda ref: dict(kind='component-branch', prefix='', children={}))
    value = native.NativeComponents(snapshot, assets, None, db, viewer=SimpleNamespace(),
                                    policy=SimpleNamespace(), metrics={})
    return value


def staged(value):
    return {table: value.db.execute('SELECT * FROM ' + table + ' ORDER BY rowid').fetchall()
            for table in ['components', 'plans', 'retired']}


def test_fresh_scope_keeps_exact_order_and_one_read_per_node(monkeypatch):
    store, root = tree()
    serial = owner(store)
    expected = serial._plan(root)
    expected_rows = staged(serial)
    expected_reads = Counter(store.reads)
    assert len(expected_rows['components']) == 256
    store.reads.clear()
    store.peak = 0
    fresh = owner(store)
    widths = []
    original = fresh._scope_batch
    def batch(children, characters, prefix, pool):
        widths.append(len(characters))
        return original(children, characters, prefix, pool)
    monkeypatch.setattr(fresh, '_scope_batch', batch)
    assert fresh.plan(root) == expected
    assert staged(fresh) == expected_rows
    assert Counter(store.reads) == expected_reads
    assert all(count == 1 for count in expected_reads.values())
    assert 1 < store.peak <= native.COMPONENT_SCOPE_WORKERS
    assert max(widths) <= native.COMPONENT_SCOPE_WORKERS
    assert store.active == 0


@pytest.mark.parametrize('unchanged', [False, True])
def test_incremental_scope_never_starts_a_pool(monkeypatch, unchanged):
    store, root = tree()
    current = owner(store)
    def forbidden(**kwargs):
        pytest.fail('Incremental scope must retain serial ownership')
    monkeypatch.setattr(native, 'ThreadPoolExecutor', forbidden)
    previous = dict(native_sha256=root['sha256'] if unchanged else 'f' * 64)
    result = current.plan(root, previous)
    if unchanged:
        assert result is previous
        assert store.reads == []
    else:
        assert len(staged(current)['components']) == 256
        assert store.peak == 1


@pytest.mark.parametrize('damage', ['digest', 'fetch'])
def test_failed_prefetch_joins_workers_and_refuses_stage_acceptance(damage):
    store, root = tree()
    first = json.loads(store.objects[root['key']])['children']['5']['key']
    if damage == 'digest':
        store.bad = first
        error, message = ValueError, 'identity'
    else:
        store.fail = first
        error, message = OSError, 'unavailable'
    current = owner(store)
    with pytest.raises(error, match=message):
        with current.db:
            current.plan(root)
    assert staged(current) == dict(components=[], plans=[], retired=[])
    assert store.active == 0
    assert store.peak <= native.COMPONENT_SCOPE_WORKERS
    assert len(store.reads) <= 1 + native.COMPONENT_SCOPE_WORKERS


def test_empty_child_remains_an_empty_route():
    store = Store()
    routes = RoutingPages(store, 'catalog-component-selection-v2')
    root = routes.objects.put(dict(version=1, prefix='', children={'0': None}))
    current = owner(store)
    current.plan(root)
    assert staged(current)['components'] == []
    assert len(store.reads) == 1
