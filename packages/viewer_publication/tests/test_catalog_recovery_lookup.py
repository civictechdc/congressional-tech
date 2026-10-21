"""Selected catalog lookups retain historical recovery ordering and scope."""
from copy import deepcopy
from pathlib import Path
import sys

import pyarrow as pa
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tests'))

from congress_api.retention import document_index as index
from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.catalog_dependency_storage import CatalogDependencyStorage
from congress_api.retention.catalog_publication import read_catalog
from congress_api.retention.catalog_selection import publish_native_catalog
from congress_api.retention.catalog_updates import update_native_catalog
from test_catalog_coalesced_batches import Native
from test_catalog_dependencies import source, identity
from test_docspec_boundary import native
from test_native_catalog_selection import scope_for
from test_filename_native_recoveries import BODY, OTHER, URL, reference


def seed(tmp_path, store, native):
    rows = [source('alias', None, source_url='../saved.pdf', source_resolved_url=[URL]),
            source('z.pdf', BODY, source_url=URL),
            source('a.xml', BODY, source_url=URL, media_type=['application/xml']),
            source('unrelated.pdf', OTHER)]
    rows, schema, _, _ = index.prepare_document_indexes(deepcopy(rows),
        pa.schema([*index.SOURCE_SCHEMA, ('capture_outcome', index.STRINGS),
                   ('source_resolved_url', index.STRINGS)]))
    owner = CatalogDependencyStorage(store=store, native=native, namespace='recovery-lookup',
                                     source_schema=schema, max_rows=64, max_bytes=1 << 20)
    empty = read_catalog(store)
    proof = scope_for(tmp_path, store, owner, empty, rows, name='initial')
    publish_native_catalog(store, proof, previous=empty)
    return owner


def rows(snapshot):
    return [row for batch in snapshot.table('filenames', max_ordered_bytes=1 << 20).iter_batches()
            for row in batch.to_pylist()]


def check_reference(tmp_path, snapshot, result):
    expected = reference(tmp_path, rows(snapshot), [])
    for name in ('recoveries', 'sources', 'groups'):
        assert result[name] == expected[name]


def exercise(tmp_path, native):
    from viewer_publication.filename_native_recoveries import index_catalog_recoveries
    store = LocalStore(tmp_path / 'store')
    owner = seed(tmp_path, store, native)
    old = read_catalog(store, native=native)
    first = index_catalog_recoveries(old, [], max_ordered_bytes=1 << 20)
    check_reference(tmp_path, old, first)
    # Same body, two media observations: the last source ordinal wins.
    assert first['recoveries'][0]['kind'] == 'xml'
    replacement = next(row for row in rows(old) if row['filename'] == 'a.xml')
    changed = dict(replacement, media_type=['application/pdf'])
    update_native_catalog(store, native=native, previous=old, dependencies=owner,
        replacements=[changed], candidate='media-correction', directory=tmp_path / 'correction',
        max_chunk_rows=64, max_chunk_bytes=1 << 20, rules=dict(grouping='maintained-v1'))
    current = read_catalog(store, native=native)
    corrected = index_catalog_recoveries(current, [], previous=first, max_ordered_bytes=1 << 20)
    check_reference(tmp_path, current, corrected)
    assert corrected['recoveries'][0]['kind'] == 'pdf'
    return current, corrected


def test_shared_catalog_lookup_and_scope_chain_match_reference(tmp_path):
    native = Native()
    current, corrected = exercise(tmp_path, native)
    from viewer_publication.filename_native_recoveries import index_catalog_recoveries
    native.reads.clear()
    assert index_catalog_recoveries(current, [], previous=corrected, max_ordered_bytes=1 << 20) == corrected
    assert not native.reads


def test_actual_native_recovery_lookup_and_correction(native, tmp_path):
    exercise(tmp_path, native)


def test_unknown_prior_recovery_catalog_refuses_before_source_reads(tmp_path):
    from viewer_publication.filename_native_recoveries import index_catalog_recoveries
    store, native = LocalStore(tmp_path / 'store'), Native()
    seed(tmp_path, store, native)
    snapshot = read_catalog(store, native=native)
    previous = index_catalog_recoveries(snapshot, [], max_ordered_bytes=1 << 20)
    previous['source_identity'] = dict(selector_sha256='foreign', selected_ref=None)
    native.reads.clear()
    with pytest.raises(ValueError, match='not an ancestor'):
        index_catalog_recoveries(snapshot, [], previous=previous, max_ordered_bytes=1 << 20)
    assert not native.reads
