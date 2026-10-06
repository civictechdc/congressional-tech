"""Logical checkpoint identity and verified legacy checkpoint transitions."""
from copy import deepcopy
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.retention import catalog_cache
from congress_api.retention.catalog_publication import read_catalog, MANIFEST_KEY
from congress_api.retention.raw_archive import Archive, CAPTURES_KEY, STATE_KEY, decode_table, encode_table
from congress_api.retention.raw_catalog import rebuild_catalog, FILENAMES, DOCUMENTS
from test_raw_source_sync import MemoryStore, response


def checkpoint(store, *, digest=None, cursor=None):
    state = decode_table(store.objects[STATE_KEY])
    metadata = dict(state.schema.metadata)
    if digest is not None:
        metadata[b'capture_digest'] = digest
    if cursor is not None:
        metadata[b'capture_rows'] = str(cursor).encode()
    store.objects[STATE_KEY] = encode_table(state.replace_schema_metadata(metadata))


def catalog_checkpoint(store, digest):
    snapshot = read_catalog(store)
    filenames = decode_table(snapshot.filenames)
    metadata = dict(filenames.schema.metadata)
    metadata[b'capture_digest'] = digest
    # Exercise the supported pre-manifest catalog without altering selected bytes.
    store.objects[FILENAMES] = encode_table(filenames.replace_schema_metadata(metadata))
    store.objects[DOCUMENTS] = snapshot.documents
    store.objects.pop(MANIFEST_KEY, None)


def saved_archive():
    store = MemoryStore()
    archive = Archive(store, 'first')
    archive.record(response('https://example.gov/a.pdf', b'%PDF-1.7\n%%EOF'), outcome='saved', links=[])
    archive.save()
    return store, archive


def test_logical_digest_ignores_writer_encoding_and_metadata(monkeypatch):
    root = Path(__file__).parent / 'fixtures'
    paths = [root / f'capture-checkpoint-arrow{version}.parquet' for version in ('23', '25')]
    assert paths[0].read_bytes() != paths[1].read_bytes()
    tables = [pq.read_table(path) for path in paths]
    assert tables[0].equals(tables[1], check_metadata=True)
    assert pq.read_metadata(paths[0]).created_by != pq.read_metadata(paths[1]).created_by
    def forbidden(*args, **kwargs):
        pytest.fail('Logical checkpoint must not serialize Parquet')
    monkeypatch.setattr(catalog_cache, 'encode_table', forbidden)
    digests = [catalog_cache.capture_digest(table) for table in tables]
    assert digests[0] == digests[1]
    assert digests[0] == 'rows-v1:64c2fbba175956805396015527350ed92ab5c1a9151cc4450298908811c49c45'
    assert catalog_cache.capture_digest(tables[0].replace_schema_metadata({'new': 'metadata'})) == digests[0]


def test_logical_digest_spans_batches_and_captures_schema_and_values():
    table = pa.table({'text': ['é\n', None, ''] * 1400, 'number': list(range(4200))})
    digest = catalog_cache.capture_digest(table)
    chunked = pa.concat_tables([table.slice(0, 100), table.slice(100, 3999), table.slice(4099)])
    assert catalog_cache.capture_digest(chunked) == digest
    changed = [table.slice(1), table.rename_columns(['different', 'number']),
               table.select(['number', 'text']), table.cast(pa.schema([('text', pa.string()), ('number', pa.int32())])),
               table.set_column(0, 'text', pa.array(['changed'] * len(table)))]
    assert all(catalog_cache.capture_digest(candidate) != digest for candidate in changed)
    assert catalog_cache.capture_digest(table.slice(0, 0)) != catalog_cache.capture_digest(pa.table({'x': []}))


def test_legacy_digest_is_checked_before_capture_checkpoint_upgrade():
    store, archive = saved_archive()
    checkpoint(store, digest=catalog_cache.legacy_capture_digest(archive.captures).encode())
    before = deepcopy(store.objects)
    resumed = Archive(store, 'next')
    assert store.objects == before  # Reading does not migrate persisted state.
    assert resumed.state == archive.state
    resumed.save()
    assert decode_table(store.objects[STATE_KEY]).schema.metadata[b'capture_digest'].startswith(b'rows-v1:')
    assert store.objects[CAPTURES_KEY] == before[CAPTURES_KEY]


@pytest.mark.parametrize('digest', [b'0' * 64, b'rows-v1:' + b'0' * 64, b'rows-v2:unsupported', b''])
def test_capture_mismatch_refuses_implicit_recovery_without_writes(digest):
    store, archive = saved_archive()
    checkpoint(store, digest=digest)
    before = deepcopy(store.objects)
    with pytest.raises(ValueError, match='checkpoint digest mismatch'):
        Archive(store, 'next')
    assert store.objects == before
    assert Archive(store, 'repair', repair=True).state == archive.state


@pytest.mark.parametrize('cursor', [-1, 999])
def test_capture_invalid_cursor_refuses_implicit_recovery(cursor):
    store, _ = saved_archive()
    checkpoint(store, cursor=cursor)
    with pytest.raises(ValueError, match='invalid cursor'):
        Archive(store, 'next')


def test_catalog_legacy_checkpoint_reuses_then_upgrades_on_changed_input():
    store, archive = saved_archive()
    rebuild_catalog(store, workers=1)
    legacy = catalog_cache.legacy_capture_digest(archive.captures).encode()
    catalog_checkpoint(store, legacy)
    result = rebuild_catalog(store, workers=1)
    assert result['unchanged'] is True
    archive = Archive(store, 'next')
    archive.record(response('https://example.gov/b.pdf', b'%PDF-1.7\nnew\n%%EOF'), outcome='saved', links=[])
    archive.save()
    rebuild_catalog(store, workers=1)
    assert decode_table(read_catalog(store).filenames).schema.metadata[b'capture_digest'].startswith(b'rows-v1:')


def test_catalog_mismatch_refuses_source_replay_until_explicit_rebuild():
    store, _ = saved_archive()
    rebuild_catalog(store, workers=1)
    catalog_checkpoint(store, b'0' * 64)
    before = deepcopy(store.objects)
    with pytest.raises(ValueError, match='checkpoint digest mismatch'):
        rebuild_catalog(store, workers=1)
    assert store.objects == before
    rebuilt = rebuild_catalog(store, workers=1, repair=True)
    assert rebuilt['document_rows'] == 1


@pytest.mark.parametrize('missing', [b'capture_rows', b'capture_digest'])
def test_incomplete_checkpoint_refuses_implicit_recovery(missing):
    store = MemoryStore()
    Archive(store, 'empty').save()
    state = decode_table(store.objects[STATE_KEY])
    metadata = dict(state.schema.metadata)
    del metadata[missing]
    store.objects[STATE_KEY] = encode_table(state.replace_schema_metadata(metadata))
    before = dict(store.objects)
    with pytest.raises(ValueError, match='checkpoint digest mismatch'):
        Archive(store, 'next')
    assert store.objects == before


@pytest.mark.parametrize('missing', [b'raw_capture_rows', b'capture_digest'])
def test_incomplete_catalog_checkpoint_refuses_replay(missing):
    store, _ = saved_archive()
    rebuild_catalog(store, workers=1)
    snapshot = read_catalog(store)
    filenames = decode_table(snapshot.filenames)
    metadata = dict(filenames.schema.metadata)
    del metadata[missing]
    store.objects[FILENAMES] = encode_table(filenames.replace_schema_metadata(metadata))
    store.objects[DOCUMENTS] = snapshot.documents
    store.objects.pop(MANIFEST_KEY)
    before = dict(store.objects)
    with pytest.raises(ValueError, match='checkpoint digest mismatch'):
        rebuild_catalog(store, workers=1)
    assert store.objects == before


def test_filename_refresh_preserves_catalog_checkpoint_for_next_update(tmp_path):
    from congress_api.retention.catalog_cache import LocalStore
    from congress_api.retention.document_index import refresh_filename_metadata
    store = LocalStore(tmp_path)
    from congress_api.retention.raw_archive import CAPTURE_SCHEMA
    store.put(CAPTURES_KEY, encode_table(pa.Table.from_pylist([], schema=CAPTURE_SCHEMA)))
    archive = Archive(store, 'first')
    archive.record(response('https://example.gov/a.pdf', b'%PDF-1.7\n%%EOF'), outcome='saved', links=[])
    archive.save()
    rebuild_catalog(store, workers=1)
    before = decode_table(read_catalog(store).filenames).schema.metadata
    refresh_filename_metadata(tmp_path, workers=1)
    after = decode_table(read_catalog(store).filenames).schema.metadata
    for key in (b'raw_capture_rows', b'capture_digest', b'seed_digest', b'deferred_source_bodies',
                b'source_fingerprint', b'retained_recovery_fingerprint'):
        assert after[key] == before[key]
    assert rebuild_catalog(store, workers=1)['unchanged'] is True
    archive = Archive(store, 'next')
    archive.record(response('https://example.gov/b.pdf', b'%PDF-1.7\nnew\n%%EOF'), outcome='saved', links=[])
    archive.save()
    result = rebuild_catalog(store, workers=1)
    assert result['document_rows'] == 2
