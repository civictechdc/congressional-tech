"""Existing reader results retain their precedence through explicit adoption."""
from hashlib import sha256

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.retention.capture_metadata import restore_readings
from congress_api.retention.catalog_cache import save_results
from test_raw_readings import part
from test_raw_storage import SelectorStore
from native_memory_helpers import memory_raw_storage


def test_adopted_readers_keep_empty_results_exact_values_and_capture_fallback(tmp_path):
    from congress_api.retention.raw_readings_adoption import adopt_body_readings
    store = SelectorStore()
    capture = part(store, 'capture', 'body:a')
    other = part(store, 'other', 'body:other')
    old = {
        ('cover', 'body:a'): {},
        ('document', 'body:a'): {'body_format': ['pdf'], 'content_title': ['Exact', None, 'Exact']},
        ('xml', 'body:legacy-only'): {},
    }
    save_results(store, 'bodies', 'earlier-reader', ('reader', 'body_key'), old)
    cache_bytes = store.read('indexes/processing/bodies.parquet')
    source = tmp_path / 'bodies.parquet'
    source.write_bytes(cache_bytes)
    expected = dict(bytes=len(cache_bytes), sha256=sha256(cache_bytes).hexdigest())
    references = adopt_body_readings(store, [capture, other], cache_path=source,
                                    expected=expected, directory=tmp_path / 'adoption')
    owner = memory_raw_storage(store)
    selected = owner.publish(owner.prepare(owner.snapshot(), operation='adopt',
        reading_parts=references, qualify_readings=True))
    assert store.read('indexes/processing/bodies.parquet') == cache_bytes
    store.keys = lambda *args: pytest.fail('Adopted lookup scanned old history')
    readings = list(selected.body_readings(['body:a', 'body:legacy-only']))
    cache = {}
    restore_readings(readings, cache)
    assert cache[('cover', 'body:a')] == {}
    assert cache[('document', 'body:a')]['content_title'] == ['Exact', None, 'Exact']
    assert cache[('xml', 'body:legacy-only')] == {}
    assert selected.has_body_reading('body:legacy-only')
    assert len(list(selected.body_readings(['body:other']))) == 1
    assert other in references
    before = dict(store.objects)
    assert references == adopt_body_readings(store, [capture, other], cache_path=source,
        expected=expected, directory=tmp_path / 'retry')
    assert store.objects == before


def test_reader_adoption_refuses_changed_file_and_unknown_schema_before_writes(tmp_path):
    from congress_api.retention.raw_readings_adoption import adopt_body_readings
    store = SelectorStore()
    path = tmp_path / 'cache.parquet'
    pq.write_table(pa.table({'reader': ['xml'], 'body_key': ['a'], 'wrong': [42]}), path)
    payload = path.read_bytes()
    options = dict(cache_path=path, directory=tmp_path / 'work',
        expected=dict(bytes=len(payload), sha256=sha256(payload).hexdigest()))
    with pytest.raises(ValueError, match='schema'):
        adopt_body_readings(store, [], **options)
    assert not store.writes
    options['expected']['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='checksum'):
        adopt_body_readings(store, [], **options)
    assert not store.writes


def test_reader_adoption_keeps_last_duplicate_reader_result(tmp_path):
    from congress_api.retention.raw_readings_adoption import adopt_body_readings
    store = SelectorStore()
    path = tmp_path / 'cache.parquet'
    pq.write_table(pa.table({'reader': ['cover', 'cover'], 'body_key': ['a', 'a'],
                            'content_citation': [['old'], None]}), path)
    data = path.read_bytes()
    refs = adopt_body_readings(store, [], cache_path=path, directory=tmp_path / 'work',
        expected=dict(bytes=len(data), sha256=sha256(data).hexdigest()))
    owner = memory_raw_storage(store)
    selected = owner.publish(owner.prepare(owner.snapshot(), operation='adopt',
        reading_parts=refs, qualify_readings=True))
    cache = {}
    restore_readings(selected.body_readings(['a']), cache)
    assert cache == {('cover', 'a'): {}}


def test_selected_reader_cache_keeps_precedence_over_previous_catalog(tmp_path):
    from contextlib import closing
    from congress_api.retention import document_index as index
    from congress_api.retention.catalog_staging import WorkingCatalog
    from congress_api.retention.raw_readings_adoption import adopt_body_readings
    store = SelectorStore()
    save_results(store, 'bodies', 'earlier', ('reader', 'body_key'), {
        ('document', 'body:a'): {'body_format': ['pdf']},
        ('cover', 'body:a'): {},
    })
    data = store.read('indexes/processing/bodies.parquet')
    path = tmp_path / 'cache.parquet'
    path.write_bytes(data)
    parts = adopt_body_readings(store, [], cache_path=path, directory=tmp_path / 'adopt',
        expected=dict(bytes=len(data), sha256=sha256(data).hexdigest()))
    owner = memory_raw_storage(store)
    selected = owner.publish(owner.prepare(owner.snapshot(), operation='seed',
        reading_parts=parts, qualify_readings=True))
    source = dict(body_key='body:a', filename='paper.pdf', source_url='https://example.gov/paper.pdf')
    previous = pa.Table.from_pylist([dict(source, body_format=['pdf'],
        content_document_kind=['testimony'], content_citation=['stale previous reading'])])
    results = []
    for mode in ('legacy', 'selected'):
        root = tmp_path / mode
        (root / 'indexes').mkdir(parents=True)
        readings = {} if mode == 'legacy' else dict(retained_body_readings=selected.body_readings(['body:a']))
        with closing(WorkingCatalog(root / 'working.sqlite')) as work:
            index.write_filename_metadata(root, [source], previous=previous, working=work,
                                          cache_store=store, workers=1, **readings)
        results.append(pq.read_table(root / 'indexes/document-filenames.parquet').to_pylist())
    assert results[0] == results[1]


@pytest.mark.parametrize('mutate', [False, True])
def test_archive_adoption_binds_legacy_cache_version_and_preserves_source(tmp_path, mutate, monkeypatch):
    from congress_api.retention import raw_adoption
    from congress_api.retention.raw_archive import CAPTURE_SCHEMA
    store = SelectorStore()
    save_results(store, 'bodies', 'earlier', ('reader', 'body_key'), {('cover', 'a'): {}})
    key = 'indexes/processing/bodies.parquet'
    payload = store.read(key)
    # An unrelated local file must not be paired with the remote cache version.
    source = tmp_path / 'adopt' / 'retained-body-cache.parquet'
    source.parent.mkdir()
    pq.write_table(pa.table({'reader': ['cover'], 'body_key': ['wrong']}), source)
    owner = memory_raw_storage(store)
    paths = {name: tmp_path / (name + '.parquet') for name in ('captures', 'state')}
    pq.write_table(pa.Table.from_pylist([], schema=CAPTURE_SCHEMA), paths['captures'])
    pq.write_table(pa.Table.from_pylist([], schema=owner.state_schema), paths['state'])
    original_adopt = raw_adoption.adopt_tables
    def adopt(storage, **kwargs):
        before_publish = kwargs['before_publish']
        def recheck():
            if mutate:
                store.objects[key] = b'changed source'
            before_publish()
        return original_adopt(storage, **dict(kwargs, before_publish=recheck))
    monkeypatch.setattr(raw_adoption, 'adopt_tables', adopt)
    options = dict(paths=paths, sha256s={name: sha256(path.read_bytes()).hexdigest() for name, path in paths.items()},
        operation='archive-adoption', directory=tmp_path / 'adopt')
    if mutate:
        with pytest.raises(ValueError, match='Legacy reader cache changed during adoption'):
            raw_adoption.adopt_archive(owner, **options)
        assert owner.snapshot().version is None
    else:
        selected = raw_adoption.adopt_archive(owner, **options)
        assert selected.has_body_reading('a')
        assert not selected.has_body_reading('wrong')
        assert store.read(key) == payload


def test_reader_adoption_rejects_oversized_body_before_group_decode(tmp_path, monkeypatch):
    from congress_api.retention import raw_readings_adoption as adoption
    store = SelectorStore()
    path = tmp_path / 'cache.parquet'
    pq.write_table(pa.table({'reader': [f'reader-{i}' for i in range(1001)],
                            'body_key': ['a'] * 1001}), path)
    data = path.read_bytes()
    monkeypatch.setattr(adoption.json, 'loads', lambda *args: pytest.fail('Oversized group decoded'))
    with pytest.raises(ValueError, match='One body exceeds'):
        adoption.adopt_body_readings(store, [], cache_path=path, directory=tmp_path / 'adopt',
            expected=dict(bytes=len(data), sha256=sha256(data).hexdigest()))
    assert not store.writes
