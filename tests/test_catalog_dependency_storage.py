"""Immutable routed dependency state changes only affected native leaves."""
from contextlib import contextmanager
from copy import deepcopy

import pyarrow as pa

from test_catalog_dependencies import source, identity
from test_docspec_boundary import native
from test_raw_source_sync import MemoryStore
from congress_api.retention import document_index as index
from congress_api.retention.catalog_dependencies import affected_sources, dependency_schema
from congress_api.retention.catalog_dependency_storage import CatalogDependencyStorage

SCHEMA = pa.schema([*index.SOURCE_SCHEMA, ('capture_outcome', index.STRINGS)])


class MemoryNative:
    def __init__(self):
        self.tables, self.reads, self.writes, self.calls = {}, [], [], []
    def run_table(self, table, *, dataset, operation, definition):
        self.calls.append(dataset)
        if dataset not in self.tables:
            self.tables[dataset] = table
            self.writes.append(dataset)
        else:
            assert self.tables[dataset].equals(table)
        return {'dataset_key': dataset}
    @contextmanager
    def source_batches(self, pin):
        self.reads.append(pin['dataset_key'])
        yield self.tables[pin['dataset_key']].to_reader()


def test_routed_bridge_deletion_retains_old_pins_and_replays_without_writes():
    native, store = MemoryNative(), MemoryStore()
    owner = CatalogDependencyStorage(native=native, store=store, namespace='catalog-test',
                                     source_schema=SCHEMA, max_rows=4, max_bytes=1 << 20)
    a, b, bridge = source('a.pdf', 'A'), source('b.pdf', 'B'), source('a.pdf', 'B')
    rows = [a, b, bridge, *[source(f'{i}.pdf', f'unrelated-{i}') for i in range(30)]]
    initial = owner.prepare(None, replacements=rows)
    old = owner.selected(initial)
    scope = affected_sources(old, deletions=[identity(bridge)])
    before_writes = len(native.writes)
    changed = owner.prepare(initial, deletions=[identity(bridge)])
    assert len(native.writes) > before_writes
    fresh = CatalogDependencyStorage(native=native, store=store, namespace='catalog-test',
                                     source_schema=SCHEMA, max_rows=4, max_bytes=1 << 20)
    assert fresh.selected(changed).source(identity(bridge)) is None
    assert fresh.selected(initial).source(identity(bridge)) == old.source(identity(bridge))
    assert fresh.selected(changed).order(identity(a)) == 0
    writes = len(native.writes), len(store.objects)
    assert fresh.prepare(initial, deletions=[identity(bridge)]) == changed
    assert (len(native.writes), len(store.objects)) == writes
    # Existing immutable IDs and typed values in the closed source set survive.
    assert set(scope.after) == {identity(a), identity(b)}


def test_identical_replacement_and_no_change_write_nothing():
    native, store = MemoryNative(), MemoryStore()
    owner = CatalogDependencyStorage(native=native, store=store, namespace='catalog-test',
                                     source_schema=SCHEMA, max_rows=4, max_bytes=1 << 20)
    a = source('a.pdf', 'A')
    initial = owner.prepare(None, replacements=[a])
    baseline = deepcopy(store.objects), len(native.writes)
    assert owner.prepare(initial) == initial
    assert owner.prepare(initial, replacements=[a]) == initial
    assert (store.objects, len(native.writes)) == baseline


def test_actual_native_dependency_roots_survive_fresh_owner(native, tmp_path):
    store = MemoryStore()
    owner = CatalogDependencyStorage(native=native, store=store, namespace='native-catalog',
                                     source_schema=SCHEMA, max_rows=8, max_bytes=1 << 20)
    a, b, bridge = source('a.pdf', 'A'), source('b.pdf', 'B'), source('a.pdf', 'B')
    initial = owner.prepare(None, replacements=[a, b, bridge])
    changed = owner.prepare(initial, deletions=[identity(bridge)])
    fresh = CatalogDependencyStorage(native=native, store=store, namespace='native-catalog',
                                     source_schema=SCHEMA, max_rows=8, max_bytes=1 << 20)
    remaining = affected_sources(fresh.selected(initial), deletions=[identity(bridge)])
    assert set(remaining.after) == {identity(a), identity(b)}
    assert fresh.selected(changed).source(identity(bridge)) is None


def test_fixed_delta_native_payload_reads_are_bounded_in_larger_unrelated_corpus():
    measured = []
    for unrelated in (10, 1000):
        native, store = MemoryNative(), MemoryStore()
        owner = CatalogDependencyStorage(native=native, store=store, namespace='growth',
                                         source_schema=SCHEMA, max_rows=4, max_bytes=1 << 20)
        a, b, bridge = source('a.pdf', 'A'), source('b.pdf', 'B'), source('a.pdf', 'B')
        initial = owner.prepare(None, replacements=[a, b, bridge, *[
            source(f'{i}.pdf', f'unrelated-{i}') for i in range(unrelated)]])
        # Cold domain owner and routing caches; seed/adoption is outside the
        # measured correction path. Native reads are counted at actual calls.
        owner = CatalogDependencyStorage(native=native, store=store, namespace='growth',
                                         source_schema=SCHEMA, max_rows=4, max_bytes=1 << 20)
        native.reads.clear()
        native.writes.clear()
        changed = owner.prepare(initial, deletions=[identity(bridge)])
        measured.append(dict(rows_read=sum(len(native.tables[key]) for key in native.reads),
                             rows_written=sum(len(native.tables[key]) for key in native.writes)))
        assert owner.selected(changed).source(identity(bridge)) is None
    assert all(value['rows_read'] < 100 for value in measured)
    assert all(value['rows_written'] < 40 for value in measured)


def test_incomplete_reverse_directory_count_refuses():
    import pytest
    from congress_api.retention.catalog_dependencies import DependencyGap, _encoded_alias
    native, store = MemoryNative(), MemoryStore()
    owner = CatalogDependencyStorage(native=native, store=store, namespace='count',
                                     source_schema=SCHEMA, max_rows=4, max_bytes=1 << 20)
    a = source('a.pdf', 'A')
    initial = owner.prepare(None, replacements=[a])
    alias = index.group_aliases(a, identity(a))[0]
    prefix, leaf = owner.aliases.lookup(initial['alias_root'], _encoded_alias(alias))
    leaf = {**leaf, 'rows': leaf['rows'] + 1}
    broken = {**initial, 'alias_root': owner.aliases.replace(initial['alias_root'], prefix, {prefix: leaf})}
    with pytest.raises(DependencyGap, match='leaf row count differs'):
        affected_sources(owner.selected(broken), replacements=[a])


def test_source_evidence_and_state_edits_preserve_all_fields_and_other_rows(monkeypatch):
    schema = pa.schema([*SCHEMA, ('source_document_label', index.STRINGS),
                        ('source_occurrences', index.metadata_type('source_occurrences'))])
    native, store = MemoryNative(), MemoryStore()
    owner = CatalogDependencyStorage(native=native, store=store, namespace='edits',
                                     source_schema=schema, max_rows=4, max_bytes=1 << 20)
    occurrence = {'source_link_label': [], 'source_page_title': None}
    a = source('a.pdf', 'A', source_document_label=None,
               source_occurrences=[occurrence, deepcopy(occurrence)])
    b = source('b.pdf', 'A', source_document_label=[], source_occurrences=[])
    unrelated = source('unrelated.pdf', 'U', source_document_label=[''], source_occurrences=None)
    rows = [a, b, unrelated]
    initial = owner.prepare(None, replacements=rows)
    correction = {**a, 'http_status': ['404'], 'source_document_label': ['corrected']}
    def forbidden(*args, **kwargs):
        raise AssertionError('Stored interpretations must not be classified again')
    monkeypatch.setattr(index, 'extract', forbidden)
    changed = owner.prepare(initial, replacements=[correction])
    selected = owner.selected(changed)
    expected = pa.Table.from_pylist([correction, b, unrelated], schema=schema).to_pylist()
    actual = [selected.source(identity(row)) for row in rows]
    assert actual == expected
    assert [selected.order(identity(row)) for row in rows] == [0, 1, 2]
    # Offline exhaustive reference only: the changed path never enumerates this.
    stored_ids = [row['source_id'] for _, pin in owner.sources.leaf_items(changed['source_root'])
                  for row in owner._read(pin, dependency_schema(schema)).to_pylist()]
    assert sorted(stored_ids) == sorted(identity(row) for row in rows)


def test_schema_change_refuses_instead_of_dropping_new_source_fields():
    import pytest
    native, store = MemoryNative(), MemoryStore()
    owner = CatalogDependencyStorage(native=native, store=store, namespace='schema',
                                     source_schema=SCHEMA, max_rows=4, max_bytes=1 << 20)
    before = deepcopy(store.objects)
    with pytest.raises(ValueError, match='not declared'):
        owner.prepare(None, replacements=[source('a.pdf', 'A', unknown_field=['preserve-me'])])
    assert not native.writes
    assert store.objects == before


def test_small_aliases_share_bounded_physical_native_tables():
    native, store = MemoryNative(), MemoryStore()
    owner = CatalogDependencyStorage(native=native, store=store, namespace='coalesced',
                                     source_schema=SCHEMA, max_rows=1024, max_bytes=4 << 20)
    rows = [source(f'{i}.pdf', f'body-{i}') for i in range(100)]
    selected = owner.prepare(None, replacements=rows)
    assert len(native.calls) == 2  # One source leaf and one shared reverse leaf.
    assert sum(len(table) for table in native.tables.values()) == 300
    assert owner.selected(selected).source(identity(rows[50])) is not None


def test_large_alias_uses_only_bounded_secondary_member_leaves():
    from congress_api.retention.catalog_dependencies import _encoded_alias
    native, store = MemoryNative(), MemoryStore()
    owner = CatalogDependencyStorage(native=native, store=store, namespace='large-alias',
                                     source_schema=SCHEMA, max_rows=4, max_bytes=1 << 20)
    rows = [source(f'{i}.pdf', 'shared-body') for i in range(40)]
    selected = owner.prepare(None, replacements=rows)
    _, leaf = owner.aliases.lookup(selected['alias_root'], _encoded_alias(('body', 'shared-body')))
    assert leaf['kind'] == 'members' and leaf['count'] == 40
    assert all(len(table) <= 4 for table in native.tables.values())
    assert len(owner.selected(selected).members(('body', 'shared-body'))) == 40
    changed = owner.prepare(selected, replacements=[{**rows[0], 'http_status': ['404']}])
    assert len(owner.selected(changed).members(('body', 'shared-body'))) == 39
    assert len(owner.selected(selected).members(('body', 'shared-body'))) == 40
