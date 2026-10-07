"""Explicit PDF readings replace selected body facts across catalog aliases."""
from hashlib import sha256
import json
from pathlib import Path

import pytest
import pyarrow.parquet as pq

from congress_api.acquisition.raw_sync import run_sync
from congress_api.retention.capture_metadata import MetadataWriter
from congress_api.retention.document_index import validated_body_readings
from congress_api.retention.raw_archive import Archive
from congress_api.retention.raw_catalog import rebuild_catalog
from test_raw_catalog import table
from test_raw_source_sync import MemoryStore, response
from catalog_test_helpers import selected_path

PDF = (Path(__file__).parent / 'fixtures/meeting_inventory/senate-burma-hearing-cover.pdf').read_bytes()


def body_key(data):
    digest = sha256(data).hexdigest()
    return f'bodies/sha256/{digest[:2]}/{digest}.gz'


def reading(key, **fields):
    return dict(body_key=key, parser_fingerprint='1' * 64, status='completed',
                error_type=None, body_format=['pdf'], **fields)


@pytest.mark.parametrize('change', [
    {'body_key': None}, {'body_key': 3}, {'body_key': 'other'},
    {'parser_fingerprint': None}, {'parser_fingerprint': 3},
    {'parser_fingerprint': ''}, {'status': 'failed'}, {'error_type': 'PdfToolError'},
    {'body_format': ['xml']}, {'content_citation': 'not a list'},
    {'content_citation': [123]}, {'source_url': 'https://example.gov/invented.pdf'},
])
def test_invalid_reading_refuses_before_storage(change):
    class NoStorage:
        def __getattr__(self, name):
            pytest.fail('Invalid readings must fail before storage access')
    row = {**reading(body_key(PDF)), **change}
    with pytest.raises(ValueError):
        rebuild_catalog(NoStorage(), body_readings=[row], workers=1)


def test_duplicate_body_readings_refuse():
    row = reading(body_key(PDF))
    with pytest.raises(ValueError, match='distinct'):
        validated_body_readings([row, row])


def captured_store():
    class NoCatalogBodyReads(MemoryStore):
        def read(self, key):
            assert not key.startswith('bodies/'), 'Overrides must not download body bytes'
            return super().read(key)
    store = NoCatalogBodyReads()
    key, other = body_key(PDF), body_key(PDF + b'\n')
    # Historical immutable readings are preserved; an explicit override can clear
    # a previous incorrect citation, even when a source has multiple URL aliases.
    with MetadataWriter(store, 'earlier') as writer:
        for body in (key, other):
            writer.append(reading(body, content_document_kind=['published-hearing'],
                                  content_citation=['old citation']))
    inputs = [('a.pdf', PDF), ('alias.pdf', PDF), ('unselected.pdf', PDF + b'\n')]
    archive = Archive(store, 'capture')
    documents = {'https://example.gov/' + name: data for name, data in inputs}
    run_sync(archive, [{'url': url} for url in documents], limit=3,
             fetch=lambda url: response(url, documents[url]))
    rebuild_catalog(store, workers=1)
    return store, key, other


def test_explicit_empty_cover_refreshes_every_alias_and_stays_cleared():
    store, key, other = captured_store()
    before = table(store).to_pylist()
    assert all(row['content_citation'] == ['old citation'] for row in before)
    no_change = rebuild_catalog(store, workers=1)
    assert no_change['unchanged'] is True
    assert table(store).to_pylist() == before

    result = rebuild_catalog(store, workers=1, body_readings=[reading(key)])
    assert result['refreshed_body_readings'] == 1
    rows = table(store).to_pylist()
    selected = [row for row in rows if row['body_key'] == key]
    assert {row['source_url'] for row in selected} == {
        'https://example.gov/a.pdf', 'https://example.gov/alias.pdf'}
    assert all(row.get('content_citation') is None and row['document_kind'] is None for row in selected)
    assert all(row['body_format'] == ['pdf'] for row in selected)
    assert [row for row in rows if row['body_key'] == other] == [row for row in before if row['body_key'] == other]
    assert json.loads(table(store).schema.metadata[b'body_reading_overrides']) == {key: '1' * 64}

    # A later normal incremental update must use the cleared cover for a new
    # alias too, not resurrect the older immutable capture-part reading.
    url = 'https://example.gov/later-alias.pdf'
    run_sync(Archive(store, 'later-capture'), [{'url': url}], limit=1,
             fetch=lambda _: response(url, PDF))
    rebuild_catalog(store, workers=1)
    later = [row for row in table(store).to_pylist() if row['body_key'] == key]
    assert len(later) == 3
    assert all(row.get('content_citation') is None and row['document_kind'] is None for row in later)
    assert json.loads(table(store).schema.metadata[b'body_reading_overrides']) == {key: '1' * 64}


def test_unknown_body_refuses_without_changing_publication():
    store, _, _ = captured_store()
    before = dict(store.objects)
    with pytest.raises(ValueError, match='no retained capture'):
        rebuild_catalog(store, workers=1, body_readings=[reading(body_key(b'unknown PDF'))])
    assert store.objects == before


def test_explicit_reading_with_cover_is_consumed_without_body_inspection():
    store, key, _ = captured_store()
    rebuild_catalog(store, workers=1, body_readings=[reading(
        key, content_document_kind=['witness-statement'], content_citation=['new reading'])])
    rows = [row for row in table(store).to_pylist() if row['body_key'] == key]
    assert len(rows) == 2
    assert all(row['content_citation'] == ['new reading'] for row in rows)
    assert all(row['document_kind'] == ['witness-statement'] for row in rows)


@pytest.mark.parametrize('new_override', [False, True])
def test_full_reinspection_drops_obsolete_override_provenance(tmp_path, new_override):
    from congress_api.retention.document_index import write_filename_metadata
    store, key, other = captured_store()
    rebuild_catalog(store, workers=1, body_readings=[reading(key)])
    previous = table(store)
    sources = [{name: row[name] for name in ('body_key', 'filename', 'source_url')}
               for row in previous.to_pylist()]
    overrides = [{**reading(key), 'parser_fingerprint': '2' * 64}] if new_override else []
    write_filename_metadata(tmp_path, sources, workers=1, previous=previous,
                            cache_store=store, reuse_results=False, inspect_bodies=True,
                            read_body=lambda body: PDF if body == key else PDF + b'\n',
                            body_readings=overrides)
    current = pq.read_table(selected_path(tmp_path / 'indexes/document-filenames.parquet'))
    assert json.loads(current.schema.metadata.get(b'body_reading_overrides', b'{}')) == (
        {key: '2' * 64} if new_override else {})
    selected = [row for row in current.to_pylist() if row['body_key'] == key]
    assert all(row.get('content_citation') == (None if new_override else ['S. Hrg. 117-16'])
               for row in selected)
