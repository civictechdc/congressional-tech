"""Stored dependencies must name both sides of a removed transitive bridge."""
from copy import deepcopy

import pyarrow as pa
import pytest


from congress_api.retention import document_index as index
from congress_api.retention.catalog_dependencies import affected_sources, DependencyGap


def source(name, body=None, **values):
    return {**dict(body_key=body, filename=name, source_url='https://example.gov/' + name,
                   media_type=['application/pdf'], http_status=['200'], capture_outcome=['saved']), **values}


def identity(row):
    return index.source_identity(row)


class SelectedDependencies:
    """A complete selected fixture index; no corpus enumeration API is exposed."""
    def __init__(self, rows):
        self.rows = {identity(row): deepcopy(row) for row in rows}
        self.edges = {}
        self.reads = []
        for key, row in self.rows.items():
            for alias in index.group_aliases(row, key):
                self.edges.setdefault(alias, set()).add(key)

    def source(self, key):
        self.reads.append(('source', key))
        return deepcopy(self.rows.get(key))

    def aliases(self, key):
        return index.group_aliases(self.rows[key], key)

    def members(self, alias):
        self.reads.append(('alias', alias))
        return sorted(self.edges.get(alias, ()))


def test_bridge_deletion_closes_old_component_and_ignores_unrelated():
    a, b, bridge = source('a.pdf', 'A'), source('b.pdf', 'B'), source('a.pdf', 'B')
    unrelated = source('else.pdf', 'C')
    selected = SelectedDependencies([a, b, bridge, unrelated])
    result = affected_sources(selected, replacements=[], deletions=[identity(bridge)])
    assert set(result.before) == {identity(row) for row in (a, b, bridge)}
    assert set(result.after) == {identity(row) for row in (a, b)}
    assert result.sources_read == 3
    assert not any(key == identity(unrelated) for kind, key in selected.reads if kind == 'source')
    schema = pa.schema([*index.SOURCE_SCHEMA, ('capture_outcome', index.STRINGS)])
    _, _, documents, _ = index.prepare_document_indexes(list(result.after.values()), schema)
    assert len(documents) == 2


def test_new_bridge_and_changed_eligibility_expand_new_and_old_neighbors():
    a, b = source('a.pdf', 'A'), source('b.pdf', 'B')
    selected = SelectedDependencies([a, b])
    bridge = source('a.pdf', 'B')
    result = affected_sources(selected, replacements=[bridge])
    assert set(result.before) == {identity(a), identity(b)}
    assert set(result.after) == {identity(row) for row in (a, b, bridge)}
    failed = {**b, 'http_status': ['404']}
    result = affected_sources(SelectedDependencies([a, b, bridge]), replacements=[failed])
    assert set(result.after) == {identity(row) for row in (a, b, bridge)}
    assert result.after[identity(b)]['http_status'] == ['404']


def test_unknown_deletion_and_incomplete_reverse_dependency_refuse():
    with pytest.raises(DependencyGap, match='Missing changed source'):
        affected_sources(SelectedDependencies([]), deletions=['missing'])
    a = source('a.pdf', 'A')
    selected = SelectedDependencies([a])
    selected.edges[next(iter(selected.edges))].add('missing-member')
    with pytest.raises(DependencyGap, match='Missing dependency source'):
        affected_sources(selected, replacements=[{**a, 'source_document_label': ['corrected']}])


def test_aliases_agree_with_existing_endpoint_body_policy():
    rows = [source('a.pdf', 'A'), source('a.pdf?download=1', 'A'),
            source('failed.pdf', 'A', **{'http_status': ['404']})]
    for key, row in enumerate(rows):
        aliases = index.group_aliases(row, key)
        assert aliases[0][0] == 'endpoint'
        assert ('body', 'A') in aliases if key != 2 else ('body', 'A') not in aliases


def test_no_change_performs_no_dependency_reads():
    selected = SelectedDependencies([source('a.pdf', 'A')])
    result = affected_sources(selected)
    assert result.before == result.after == {}
    assert result.sources_read == result.aliases_read == 0
    assert selected.reads == []


def test_fixed_correction_lookup_cost_does_not_grow_with_unrelated_corpus():
    a, b, bridge = source('a.pdf', 'A'), source('b.pdf', 'B'), source('a.pdf', 'B')
    costs = []
    for unrelated in (10, 1000):
        selected = SelectedDependencies([a, b, bridge, *[
            source(f'{i}.pdf', f'unrelated-{i}') for i in range(unrelated)]])
        result = affected_sources(selected, replacements=[{**a, 'source_document_label': ['corrected']}])
        costs.append((result.sources_read, result.aliases_read))
    assert costs[0] == costs[1]


def test_explicit_upgrade_uses_stored_old_aliases(monkeypatch):
    a, b, bridge = source('a.pdf', 'A'), source('b.pdf', 'B'), source('a.pdf', 'B')
    selected = SelectedDependencies([a, b, bridge])
    stored = {key: index.group_aliases(row, key) for key, row in selected.rows.items()}
    selected.aliases = stored.__getitem__
    # Simulate an explicitly requested rule change: body aliases are no longer
    # eligible. Old stored aliases still force both original sides into scope.
    original = index.group_aliases
    monkeypatch.setattr(index, 'group_aliases', lambda row, key: original(row, key)[:1])
    result = affected_sources(selected, replacements=[a])
    assert set(result.before) == {identity(row) for row in (a, b, bridge)}



def test_native_selected_dependency_values_preserve_old_aliases_and_order(native, tmp_path):
    from congress_api.retention.catalog_dependencies import dependency_tables, NativeCatalogDependencies
    import pyarrow.parquet as pq

    a, b, bridge = source('a.pdf', 'A'), source('b.pdf', 'B'), source('a.pdf', 'B')
    a['source_occurrences'] = [{'source_link_label': [], 'source_page_title': None},
                               {'source_link_label': [], 'source_page_title': None}]
    schema = pa.schema([*index.SOURCE_SCHEMA, ('capture_outcome', index.STRINGS),
                        ('source_occurrences', index.metadata_type('source_occurrences'))],
                       metadata={b'application': b'selected-catalog'})
    source_table, alias_table = dependency_tables([a, b, bridge], schema, first_order=37)
    pins = []
    for label, table in (('sources', source_table), ('aliases', alias_table)):
        path = tmp_path / f'{label}.parquet'
        pq.write_table(table, path)
        pins.append(native.run(dict(dataset='dependency-' + label, operation='initial',
            definition='catalog-dependency-v1', input=str(path),
            expected_digest=native.hash_input(path)['digest'], sql='SELECT * FROM input')))
    selected = NativeCatalogDependencies(native=native, source_schema=schema,
        locate_source=lambda key: pins[0], locate_alias=lambda alias: [pins[1]])
    result = affected_sources(selected, deletions=[identity(bridge)])
    assert set(result.before) == {identity(row) for row in (a, b, bridge)}
    assert selected.order(identity(a)) == 37
    assert selected.order(identity(bridge)) == 39
    assert result.before[identity(a)]['source_occurrences'] == source_table.to_pylist()[0]['source_values']['source_occurrences']
    assert selected.native_rows_read == len(source_table) + len(alias_table)


def test_missing_old_reverse_edge_refuses_even_when_alias_was_seen_already():
    a, b, bridge = source('a.pdf', 'A'), source('b.pdf', 'B'), source('a.pdf', 'B')
    selected = SelectedDependencies([a, b, bridge])
    # Keep endpoint routing to the bridge, but remove its body membership. The
    # previously visited body alias must still validate this later source.
    selected.edges[('body', 'B')].remove(identity(bridge))
    with pytest.raises(DependencyGap, match='Missing reverse dependency membership'):
        affected_sources(selected, replacements=[a])


def test_native_dependency_reader_refuses_schema_and_duplicate_source_rows():
    from contextlib import contextmanager
    from congress_api.retention.catalog_dependencies import dependency_tables, NativeCatalogDependencies
    rows = [source('a.pdf', 'A')]
    schema = pa.schema([*index.SOURCE_SCHEMA, ('capture_outcome', index.STRINGS)])
    stored, _ = dependency_tables(rows, schema)

    class Native:
        def __init__(self, table):
            self.table = table
        @contextmanager
        def source_batches(self, pin, *, schema=None):
            yield self.table.to_reader()

    for table, message in [(pa.table({'wrong': ['field']}), 'schema differs'),
                           (pa.concat_tables([stored, stored]), 'repeated native dependency source')]:
        selected = NativeCatalogDependencies(native=Native(table), source_schema=schema,
            locate_source=lambda key: {'id': 'exact'}, locate_alias=lambda alias: [])
        with pytest.raises(DependencyGap, match=message):
            selected.source(identity(rows[0]))


def test_scope_after_rows_cannot_mutate_old_mapping_evidence():
    a = source('a.pdf', 'A', source_document_label=['original'])
    result = affected_sources(SelectedDependencies([a]), replacements=[a])
    result.after[identity(a)]['source_document_label'].append('new')
    assert result.before[identity(a)]['source_document_label'] == ['original']
