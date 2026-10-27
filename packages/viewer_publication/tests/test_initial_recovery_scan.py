"""Initial recovery reuses one exact ordered source scan; updates stay routed."""
from collections import Counter

import pytest

from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.catalog_publication import read_catalog
from congress_api.retention.catalog_updates import update_native_catalog
from congress_api.retention.saved_responses import FIELDS
from viewer_publication.filename_native_recoveries import (
    CatalogRecoverySources, index_catalog_recoveries, index_selected_recoveries,
)
from test_catalog_coalesced_batches import Native
from test_catalog_recovery_lookup import seed, rows
from test_filename_native_recoveries import URL


def baseline(snapshot):
    sources = CatalogRecoverySources(snapshot, max_ordered_bytes=1 << 20)
    try:
        counts = snapshot.selection['counts']
        info = dict(catalog_id=snapshot.schemas['filenames'].metadata[b'catalog_id'].decode(),
                    rows=counts['source_rows'], entries=counts['document_rows'])
        return index_selected_recoveries(info, snapshot.identity, sources, [])
    finally:
        sources.close()


def test_initial_scan_matches_routed_recovery_and_reuses_every_pin(tmp_path, monkeypatch):
    store, native = LocalStore(tmp_path / 'store'), Native()
    seed(tmp_path, store, native)
    snapshot = read_catalog(store, native=native)
    expected = baseline(snapshot)
    native.reads.clear()
    initial_tables = set(native.tables)
    metrics = {}
    original_table, calls = snapshot.table, []
    def table(*args, **kwargs):
        selected = original_table(*args, **kwargs)
        iterate = selected.iter_batches
        def observed(**options):
            calls.append(options)
            yield from iterate(**options)
        selected.iter_batches = observed
        return selected
    monkeypatch.setattr(snapshot, 'table', table)
    assert index_catalog_recoveries(snapshot, [], max_ordered_bytes=1 << 20, metrics=metrics) == expected
    assert metrics['initial_recovery_scans'] == 1 and metrics['initial_recovery_rows'] == 4
    assert calls == [dict(columns=[name for name in dict.fromkeys([*FIELDS, 'source_resolved_url',
        'source_id', 'document_id']) if name in snapshot.schemas['filenames'].names],
        batch_size=128, include_order=True)]
    assert all(name.startswith('catalog-filenames-') and count == 1
               for name, count in Counter(native.reads).items())
    assert native.reads and set(native.tables) == initial_tables
    native.reads.clear();calls.clear()
    again = index_catalog_recoveries(snapshot, [], previous=expected, max_ordered_bytes=1 << 20)
    assert again == expected and not calls and not native.reads


def test_initial_after_partial_replacement_preserves_dependency_order(tmp_path):
    store, native = LocalStore(tmp_path / 'store'), Native()
    owner = seed(tmp_path, store, native)
    old = read_catalog(store, native=native)
    replacement = next(row for row in rows(old) if row['filename'] == 'z.pdf')
    update_native_catalog(store, native=native, previous=old, dependencies=owner,
        replacements=[dict(replacement, capture_outcome=['saved'])], candidate='new-physical-chunk',
        directory=tmp_path / 'update', max_chunk_rows=64, max_chunk_bytes=1 << 20,
        rules=dict(grouping='maintained-v1'))
    snapshot = read_catalog(store, native=native)
    selected = snapshot.table('filenames', max_ordered_bytes=1 << 20)
    assert all('_catalog_order' not in batch.schema.names for batch in selected.iter_batches(columns=['source_id']))
    exposed = [row for batch in selected.iter_batches(columns=['source_id'], include_order=True) for row in batch.to_pylist()]
    orders = {row['source_id']:row['_catalog_order'] for row in exposed}
    lookup = CatalogRecoverySources(snapshot, max_ordered_bytes=1 << 20, initial=True)
    try:
        urls = list(lookup.urls())
        projected = [name for name in dict.fromkeys([*FIELDS, 'source_resolved_url', 'source_id', 'document_id'])
                     if name in snapshot.schemas['filenames'].names]
        before = len(native.reads)
        for url in urls:
            direct = sorted(owner.sources_at_url(snapshot.selection['dependency'], url), key=lambda row:row['source_order'])
            assert all(orders[row['source_id']] == row['source_order'] for row in direct)
            expected = [{key:row['source_values'].get(key) for key in projected} for row in direct]
            assert list(lookup.at_url(url)) == expected
            expected_targets = [{key:row['source_values'].get(key) for key in projected}
                                for row in owner.originals_targeting(snapshot.selection['dependency'], url)]
            assert list(lookup.targeting(url)) == expected_targets
        routed_reads = len(native.reads)
        for _ in range(3):
            for url in urls:
                list(lookup.at_url(url));list(lookup.targeting(url))
        assert len(native.reads) == routed_reads
        assert routed_reads >= before
    finally:
        lookup.close()
    expected = baseline(snapshot)
    assert index_catalog_recoveries(snapshot, [], max_ordered_bytes=1 << 20) == expected
    assert expected['recoveries'][0]['kind'] == 'xml'


def test_initial_scan_retains_lookup_policy_admission_before_native_reads(tmp_path, monkeypatch):
    store, native = LocalStore(tmp_path / 'store'), Native()
    seed(tmp_path, store, native); snapshot = read_catalog(store, native=native)
    source = CatalogRecoverySources(snapshot, max_ordered_bytes=1 << 20, initial=True)
    def checked(selection, *, require_lookup_policy=False):
        assert require_lookup_policy is True
        raise ValueError('Current lookup policy required')
    monkeypatch.setattr(source.owner, '_selection', checked)
    native.reads.clear()
    try:
        with pytest.raises(ValueError, match='lookup policy'):
            list(source.urls())
        assert not native.reads and source._temp_dir is None
    finally:
        source.close()


def test_interrupted_initial_scan_discards_private_index(tmp_path, monkeypatch):
    store, native = LocalStore(tmp_path / 'store'), Native()
    seed(tmp_path, store, native); snapshot = read_catalog(store, native=native)
    original = snapshot.table
    def table(*args, **kwargs):
        selected = original(*args, **kwargs)
        iterate = selected.iter_batches
        def interrupted(**options):
            yield from iterate(**options)
            raise OSError('source scan interrupted')
        selected.iter_batches = interrupted
        return selected
    monkeypatch.setattr(snapshot, 'table', table)
    source = CatalogRecoverySources(snapshot, max_ordered_bytes=1 << 20, initial=True)
    try:
        with pytest.raises(OSError, match='interrupted'):
            list(source.urls())
        assert source._spill_db is None and source._temp_dir is None and not source._initial_ready
    finally:
        source.close()


@pytest.mark.parametrize('change', ['duplicate', 'null', 'conflict', 'second_body', 'failed_capture'])
def test_initial_projection_preserves_alias_ambiguity_and_capture_evidence(tmp_path, change):
    from test_filename_native_recoveries import OTHER
    store, native = LocalStore(tmp_path / 'store'), Native()
    owner = seed(tmp_path, store, native); old = read_catalog(store, native=native)
    values = rows(old)
    alias = next(row for row in values if row.get('source_resolved_url'))
    saved = next(row for row in values if row['filename'] == 'z.pdf')
    changes = {
        'duplicate': dict(alias, source_resolved_url=[URL, URL]),
        'null': dict(alias, source_resolved_url=[URL, None]),
        'conflict': dict(alias, source_resolved_url=[URL, 'https://example.test/other']),
        'second_body': dict(saved, body_key=OTHER),
        'failed_capture': dict(saved, response_body_complete=['false']),
    }
    update_native_catalog(store, native=native, previous=old, dependencies=owner,
        replacements=[changes[change]], candidate='capture-' + change, directory=tmp_path / 'update',
        max_chunk_rows=64, max_chunk_bytes=1 << 20, rules=dict(grouping='maintained-v1'))
    snapshot = read_catalog(store, native=native)
    expected = baseline(snapshot)
    assert index_catalog_recoveries(snapshot, [], max_ordered_bytes=1 << 20) == expected


def test_overbudget_source_refuses_and_discards_partial_private_index(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import pyarrow as pa
    from viewer_publication.filename_budget import DEFAULT_DECODED_POLICY, DecodedBudgetExceeded
    store, native = LocalStore(tmp_path / 'store'), Native()
    seed(tmp_path, store, native); snapshot = read_catalog(store, native=native)
    values = rows(snapshot)
    schema = snapshot.schemas['filenames'].append(pa.field('_catalog_order', pa.int64(), nullable=False))
    small = pa.RecordBatch.from_pylist([dict(values[0], _catalog_order=0)], schema=schema)
    huge = pa.RecordBatch.from_pylist([dict(values[1], _catalog_order=1,
        source_url='x' * (DEFAULT_DECODED_POLICY.row_arrow_bytes + 1))], schema=schema)
    monkeypatch.setattr(snapshot, 'table', lambda *a, **k: SimpleNamespace(
        iter_batches=lambda **options: iter([small, huge])))
    source = CatalogRecoverySources(snapshot, max_ordered_bytes=96 << 20, initial=True)
    try:
        with pytest.raises(DecodedBudgetExceeded, match='single-row Arrow bytes'):
            list(source.urls())
        assert source._spill_db is None and source._temp_dir is None and not source._initial_ready
    finally:
        source.close()
