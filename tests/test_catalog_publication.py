import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.catalog_publication import (
    MANIFEST_KEY, read_catalog, publish_catalog, local_catalog_paths,
)


def pair(root, catalog_id='one'):
    root.mkdir(parents=True, exist_ok=True)
    paths = [root / name for name in ('document-filenames.parquet', 'documents.parquet')]
    for path in paths:
        pq.write_table(pa.table({'source_id': ['source'], 'document_id': ['document'], 'value': [catalog_id]}).replace_schema_metadata(
            {b'catalog_id': catalog_id.encode()}), path)
    return paths


def test_legacy_migration_and_selected_pair(tmp_path):
    paths = pair(tmp_path / 'indexes')
    store = LocalStore(tmp_path)
    before = read_catalog(store)
    assert before.manifest is None
    result = publish_catalog(store, *paths, previous=before)
    selected = read_catalog(store)
    assert selected.manifest['catalog_id'] == 'one'
    assert result['generation'] in local_catalog_paths(tmp_path)[0].as_posix()
    paths[0].write_bytes(b'stale root')
    assert read_catalog(store).filenames == selected.filenames


@pytest.mark.parametrize('failure', [1, 2, 3])
def test_interrupted_publication_keeps_previous_pair(tmp_path, failure):
    store = LocalStore(tmp_path)
    publish_catalog(store, *pair(tmp_path / 'build1'), previous=read_catalog(store))
    previous = read_catalog(store)
    original = store.put
    calls = 0
    def fail(key, data, **options):
        nonlocal calls
        calls += 1
        if calls == failure:
            raise RuntimeError('interrupted')
        return original(key, data, **options)
    store.put = fail
    with pytest.raises(RuntimeError, match='interrupted'):
        publish_catalog(store, *pair(tmp_path / 'build2', 'two'), previous=previous)
    assert read_catalog(store).manifest == previous.manifest


def test_concurrent_writer_does_not_replace_selected_pair(tmp_path):
    first, second = LocalStore(tmp_path), LocalStore(tmp_path)
    prior1, prior2 = read_catalog(first), read_catalog(second)
    publish_catalog(first, *pair(tmp_path / 'build1'), previous=prior1)
    with pytest.raises(RuntimeError, match='Concurrent'):
        publish_catalog(second, *pair(tmp_path / 'build2', 'two'), previous=prior2)
    assert read_catalog(first).manifest['catalog_id'] == 'one'


@pytest.mark.parametrize('damage', ['hash', 'rows', 'catalog_id', 'missing', 'manifest'])
def test_selected_corruption_refuses_legacy_fallback(tmp_path, damage):
    paths = pair(tmp_path / 'indexes')
    store = LocalStore(tmp_path)
    publish_catalog(store, *paths, previous=read_catalog(store))
    manifest = json.loads((tmp_path / MANIFEST_KEY).read_text())
    if damage == 'hash':
        (tmp_path / manifest['files']['filenames']['key']).write_bytes(b'bad')
    elif damage == 'missing':
        (tmp_path / manifest['files']['documents']['key']).unlink()
    elif damage == 'manifest':
        (tmp_path / MANIFEST_KEY).write_text('{')
    else:
        manifest['files']['filenames']['rows'] = 2 if damage == 'rows' else 1
        if damage == 'catalog_id':
            manifest['catalog_id'] = 'other'
        (tmp_path / MANIFEST_KEY).write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        read_catalog(store)
    with pytest.raises(ValueError):
        local_catalog_paths(tmp_path)


def test_invalid_pair_references_are_rejected_before_upload(tmp_path):
    paths = pair(tmp_path / 'build')
    docs = pq.read_table(paths[1]).set_column(0, 'source_id', pa.array(['missing-source']))
    pq.write_table(docs, paths[1])
    store = LocalStore(tmp_path)
    with pytest.raises(ValueError, match='references'):
        publish_catalog(store, *paths, previous=read_catalog(store))
    assert not (tmp_path / MANIFEST_KEY).exists()
    assert not (tmp_path / 'catalog-generations').exists()
