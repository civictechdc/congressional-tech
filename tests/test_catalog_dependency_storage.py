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
    def source_batches(self, pin, *, schema=None):
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
    assert len(native.calls) == 4  # Source, grouping, URL and non-grouping body leaves.
    assert sum(len(table) for table in native.tables.values()) == 500
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


def test_actual_native_dependency_values_retain_unsigned_binary_and_field_metadata(native):
    evidence = pa.field('saved_native_evidence', pa.struct([
        pa.field('maximum', pa.uint64(), metadata={b'publisher': b'exact'}),
        pa.field('bytes', pa.binary()),
    ]), metadata={b'meaning': b'untouched evidence'})
    schema = SCHEMA.append(evidence)
    store = MemoryStore()
    owner = CatalogDependencyStorage(native=native, store=store, namespace='exact-typed-evidence',
                                     source_schema=schema, max_rows=8, max_bytes=1 << 20)
    row = source('unsigned.pdf', 'A', saved_native_evidence=dict(maximum=2**64 - 1, bytes=b'\x00\xff'))
    selection = owner.prepare(None, replacements=[row])
    assert owner.selected(selection).source(identity(row)) == pa.Table.from_pylist([row], schema=schema).to_pylist()[0]


def test_bulk_adoption_streams_large_shared_component_without_closure_replays():
    native, store = MemoryNative(), MemoryStore()
    rows = [source(f'bulk-{i}.pdf', 'shared-body') for i in range(1000)]
    old_rows, schema, _, _ = index.prepare_document_indexes(rows, SCHEMA)
    owner = CatalogDependencyStorage(native=native, store=store, namespace='bulk-adopt',
                                     source_schema=schema, max_rows=64, max_bytes=1 << 20)
    table = pa.Table.from_pylist(old_rows, schema=schema)
    selection = owner.adopt(pa.Table.from_batches([batch]) for batch in table.to_batches(max_chunksize=32))
    assert all(len(part) <= 64 and part.nbytes <= 1 << 20 for part in native.tables.values())
    assert not native.reads  # Initial import has no previous component to close.
    selected = owner.selected(selection)
    for position in (0, 499, 999):
        row = old_rows[position]
        assert selected.source(identity(row)) == table.slice(position, 1).to_pylist()[0]
        assert selected.order(identity(row)) == position
    assert selection['next_source_order'] == 1000
    assert len(set(owner.memberships.values(selection['alias_root'], '["body","shared-body"]'))) == 1000


def test_full_dependency_refresh_preserves_sparse_ordinals_and_rejects_reassignment():
    import pytest
    native, store = MemoryNative(), MemoryStore()
    originals, schema, _, _ = index.prepare_document_indexes(
        [source(f'{i}.pdf', str(i)) for i in range(3)], SCHEMA)
    owner = CatalogDependencyStorage(native=native, store=store, namespace='full-refresh',
                                     source_schema=schema, max_rows=2, max_bytes=1 << 20)
    selected = owner.adopt([pa.Table.from_pylist(originals, schema=schema)])
    added, _, _, _ = index.prepare_document_indexes([source('new.pdf', 'new')], SCHEMA)
    rows = [originals[1], added[0]]
    orders = {identity(rows[0]): 1, identity(rows[1]): 3}
    refreshed = owner.prepare_full(selected, replacements=rows, source_orders=orders)
    assert refreshed['next_source_order'] == 4
    assert owner.selected(refreshed).order(identity(rows[0])) == 1
    assert owner.selected(refreshed).order(identity(rows[1])) == 3
    assert owner.selected(refreshed).source(identity(originals[0])) is None
    assert owner.selected(selected).source(identity(originals[0])) is not None
    with pytest.raises(ValueError, match='existing source order'):
        owner.prepare_full(selected, replacements=rows, source_orders={**orders, identity(rows[0]): 0})


def test_saved_document_ownership_closes_old_component_after_group_policy_changes():
    schema = SCHEMA.append(pa.field('document_id', pa.string()))
    native, store = MemoryNative(), MemoryStore()
    owner = CatalogDependencyStorage(native=native, store=store, namespace='old-component',
                                     source_schema=schema, max_rows=8, max_bytes=1 << 20)
    # Historical grouping may have different eligibility/alias rules. Exact
    # selected document ownership is an old edge independent of current policy.
    a = source('a.pdf', 'A', document_id='historical-component')
    b = source('b.pdf', 'B', document_id='historical-component')
    initial = owner.prepare(None, replacements=[a, b])
    scope = affected_sources(owner.selected(initial), replacements=[{**a, 'http_status': ['404']}])
    assert set(scope.before) == {identity(a), identity(b)}


def test_non_grouping_url_and_resolution_lookup_preserves_all_row_owners():
    schema = SCHEMA.append(pa.field('source_resolved_url', pa.list_(pa.string())))
    native, store = MemoryNative(), MemoryStore()
    owner = CatalogDependencyStorage(native=native, store=store, namespace='url-lookups',
                                     source_schema=schema, max_rows=4, max_bytes=1 << 20)
    target = 'https://example.gov/target.pdf'
    original = 'https://example.gov/original'
    a = source('a.pdf', 'A', source_url=original, source_resolved_url=[target, None])
    b = source('b.pdf', 'B', source_url=original, source_resolved_url=[target])
    wrapped = source('c.pdf', 'C', source_url='mailto:' + target, source_resolved_url=[])
    initial = owner.prepare(None, replacements=[a, b, wrapped])
    assert {row['source_id'] for row in owner.sources_at_url(initial, original)} == {identity(a), identity(b)}
    assert {row['source_id'] for row in owner.originals_targeting(initial, target)} == {identity(a), identity(b), identity(wrapped)}
    # Invalid/null values stay in the candidate index and source payloads until
    # the maintained alias owner combines all observations and checks validity.
    null_owner, = owner.originals_targeting(initial, None)
    assert null_owner['source_id'] == identity(a)
    corrected = {**a, 'source_resolved_url': ['https://example.gov/other.pdf']}
    changed = owner.prepare(initial, replacements=[corrected], deletions=[identity(wrapped)])
    assert {row['source_id'] for row in owner.originals_targeting(changed, target)} == {identity(b)}
    assert {row['source_id'] for row in owner.originals_targeting(initial, target)} == {identity(a), identity(b), identity(wrapped)}
    row, = owner.originals_targeting(changed, 'https://example.gov/other.pdf')
    assert row['source_values']['source_resolved_url'] == ['https://example.gov/other.pdf']
    assert row['source_order'] == 0
    assert len(affected_sources(owner.selected(initial), replacements=[a]).before) == 1


def test_url_lookups_refuse_stale_resolution_policy_without_payload_reads():
    import pytest
    from congress_api.retention.catalog_dependencies import DependencyGap
    native, store = MemoryNative(), MemoryStore()
    owner = CatalogDependencyStorage(native=native, store=store, namespace='stale-lookups',
                                     source_schema=SCHEMA, max_rows=4, max_bytes=1 << 20)
    initial = owner.prepare(None, replacements=[source('a.pdf', 'A')])
    initial['lookup_requirements'] = 'old-resolution-policy'
    native.reads.clear()
    for lookup in (owner.sources_at_url, owner.originals_targeting):
        with pytest.raises(DependencyGap, match='lookup policy changed'):
            list(lookup(initial, 'https://example.gov/a.pdf'))
    assert not native.reads


def test_non_grouping_body_lookup_retains_failed_and_source_record_owners():
    native, store = MemoryNative(), MemoryStore()
    owner = CatalogDependencyStorage(native=native, store=store, namespace='body-lookups',
                                     source_schema=SCHEMA, max_rows=4, max_bytes=1 << 20)
    failed = source('failed.pdf', 'saved-response', http_status=['500'])
    source_record = source('metadata.xml', 'saved-response', media_type=['text/html'])
    initial = owner.prepare(None, replacements=[failed, source_record])
    assert {row['source_id'] for row in owner.sources_at_body(initial, 'saved-response')} == {
        identity(failed), identity(source_record)}
    changed = owner.prepare(initial, deletions=[identity(failed)])
    assert {row['source_id'] for row in owner.sources_at_body(changed, 'saved-response')} == {identity(source_record)}


def test_nullable_source_addition_reuses_exact_old_leaves_and_pads_only_missing_values():
    native, store = MemoryNative(), MemoryStore()
    owner = CatalogDependencyStorage(native=native, store=store, namespace='schema-growth',
                                     source_schema=SCHEMA, max_rows=4, max_bytes=1 << 20)
    rows = [source(f'{i}.pdf', f'body-{i}') for i in range(100)]
    initial = owner.prepare(None, replacements=rows)
    retained = dict(native.tables)
    expanded = SCHEMA.append(pa.field('source_new_literal', pa.list_(pa.string())))
    changed_owner = CatalogDependencyStorage(native=native, store=store, namespace='schema-growth',
                                     source_schema=expanded, max_rows=4, max_bytes=1 << 20)
    native.reads.clear()
    changed = changed_owner.prepare(initial, replacements=[{**rows[0], 'source_new_literal': ['exact publisher value']}])
    assert changed_owner.selected(changed).source(identity(rows[0]))['source_new_literal'] == ['exact publisher value']
    untouched = changed_owner.selected(changed).source(identity(rows[-1]))
    assert untouched == {**owner.selected(initial).source(identity(rows[-1])), 'source_new_literal': None}
    assert changed_owner.selected(changed).order(identity(rows[-1])) == 99
    assert all(native.tables[key].equals(table, check_metadata=True) for key, table in retained.items())
    assert sum(len(native.tables[key]) for key in native.reads) < 100


def test_nullable_addition_reads_plain_legacy_pins_without_rewriting_unrelated_leaves():
    native, store = MemoryNative(), MemoryStore()
    owner = CatalogDependencyStorage(native=native, store=store, namespace='legacy-source-schema',
                                     source_schema=SCHEMA, max_rows=1, max_bytes=1 << 20)
    rows = [source(f'{i}.pdf', f'body-{i}') for i in range(10)]
    initial = owner.prepare(None, replacements=rows)
    # Historical source leaves retained only a native pin; their exact source
    # schema was selected once at the dependency root.
    for prefix, value in list(owner.sources.leaf_items(initial['source_root'])):
        initial['source_root'] = owner.sources.replace(initial['source_root'], prefix, {prefix: value['release']})
    expanded = SCHEMA.append(pa.field('new_value', pa.string()))
    current = CatalogDependencyStorage(native=native, store=store, namespace='legacy-source-schema',
                                     source_schema=expanded, max_rows=1, max_bytes=1 << 20)
    changed = current.prepare(initial, replacements=[{**rows[0], 'new_value': 'literal'}])
    assert changed['legacy_source_schema'] == initial['source_schema']
    old_values = dict(owner.sources.leaf_items(initial['source_root']))
    new_values = dict(current.sources.leaf_items(changed['source_root']))
    assert sum(new_values[key] == value for key, value in old_values.items()) == 9
    assert current.selected(changed).source(identity(rows[-1]))['new_value'] is None
    # A full exported leaf also restores the logical schema only after verifying
    # its old exact physical schema; public bundle writers can reuse this owner.
    prefix, value = current.sources.lookup(changed['source_root'], identity(rows[-1]))
    table = current.read_source_leaf(changed, value)
    assert table['source_values'][0].as_py()['new_value'] is None


def test_actual_native_nullable_dependency_schema_keeps_unsigned_binary_and_field_metadata(native):
    schema = SCHEMA.append(pa.field('exact_uint', pa.uint64(), metadata={b'origin': b'kept'})).append(
        pa.field('exact_bytes', pa.list_(pa.binary())))
    store = MemoryStore()
    old = CatalogDependencyStorage(native=native, store=store, namespace='native-schema-growth',
        source_schema=schema, max_rows=1, max_bytes=1 << 20)
    a = source('a.pdf', 'A', exact_uint=2**64 - 1, exact_bytes=[None, b'\x00\xff'])
    b = source('b.pdf', 'B', exact_uint=None, exact_bytes=[])
    before = old.prepare(None, replacements=[a, b])
    expanded = schema.append(pa.field('new_literal', pa.string()))
    current = CatalogDependencyStorage(native=native, store=store, namespace='native-schema-growth',
        source_schema=expanded, max_rows=1, max_bytes=1 << 20)
    after = current.prepare(before, replacements=[{**a, 'new_literal': 'exact'}])
    selected = current.selected(after)
    assert selected.source(identity(a)) == {**old.selected(before).source(identity(a)), 'new_literal': 'exact'}
    assert selected.source(identity(b)) == {**old.selected(before).source(identity(b)), 'new_literal': None}
    assert current.source_schema.field('exact_uint').metadata == {b'origin': b'kept'}


def test_nonnullable_or_changed_dependency_field_refuses_before_payload_read():
    import pytest
    from congress_api.retention.catalog_dependencies import DependencyGap
    native, store = MemoryNative(), MemoryStore()
    owner = CatalogDependencyStorage(native=native, store=store, namespace='schema-refusal',
        source_schema=SCHEMA, max_rows=4, max_bytes=1 << 20)
    before = owner.prepare(None, replacements=[source('a.pdf', 'A')])
    for schema in (SCHEMA.append(pa.field('required', pa.string(), nullable=False)),
                   SCHEMA.set(0, pa.field('body_key', pa.binary()))):
        current = CatalogDependencyStorage(native=native, store=store, namespace='schema-refusal',
            source_schema=schema, max_rows=4, max_bytes=1 << 20)
        native.reads.clear()
        with pytest.raises(DependencyGap, match='schema or order basis differs'):
            current.prepare(before, replacements=[])
        assert native.reads == []


def test_package_lookup_preserves_complete_members_without_creating_group_edges():
    package = 'CHRG-116shrg40895'
    schema = pa.schema([*SCHEMA, ('hearing_package_id', index.STRINGS)])
    native, store = MemoryNative(), MemoryStore()
    owner = CatalogDependencyStorage(native=native, store=store, namespace='packages',
                                     source_schema=schema, max_rows=4, max_bytes=1 << 20)
    api = dict(source('api', 'api-body'), source_url='https://api.congress.gov/v3/hearing/116/joint/40895',
               hearing_package_id=[package])
    pdf = dict(source('paper.pdf', 'paper-body'),
               source_url=f'https://www.govinfo.gov/content/pkg/{package}/pdf/{package}.pdf')
    initial = owner.prepare(None, replacements=[api, pdf, *[source(f'{i}.pdf', str(i)) for i in range(100)]])
    selected = owner.selected(initial)
    assert set(affected_sources(selected, replacements=[api]).before) == {identity(api)}
    assert {row['source_id'] for row in owner.sources_at_package(initial, package)} == {identity(api), identity(pdf)}
    assert {row['source_id'] for row in owner.sources_at_package(initial, 'CHRG-116jhrg40895')} == {identity(api)}
    changed = owner.prepare(initial, deletions=[identity(pdf)])
    assert {row['source_id'] for row in owner.sources_at_package(changed, package)} == {identity(api)}
    # Historical roots retain exact membership after correction.
    assert {row['source_id'] for row in owner.sources_at_package(initial, package)} == {identity(api), identity(pdf)}
