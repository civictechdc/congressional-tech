"""Regression controls for retained House records, cache markers and filenames."""
import gzip
from hashlib import sha256
import tracemalloc

import pyarrow.parquet as pq
import pytest

from congress_api.retention import document_index as index


def test_body_interpretation_does_not_retain_every_raw_payload(monkeypatch):
    from congress_api.retention import document_evidence as evidence

    rows = [dict(body_key=f'body-{n}', filename=f'opaque-{n}', source_url=None)
            for n in range(20)]
    # Isolate retention from parser allocations: keep only the resulting fields.
    monkeypatch.setattr(evidence, 'document_body_fields', lambda _: {'body_format': ['zip']})
    tracemalloc.start()
    try:
        evidence.enrich_sources(rows, read_body=lambda _: b'x' * (2 * 1024**2), extract=lambda _: {})
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert all(row['body_format'] == ['zip'] for row in rows)
    assert peak < 8 * 1024**2, 'Raw body memory must not grow with corpus size'


def retained(root, name, data, *, url=None, path=None, **fields):
    digest = sha256(data).hexdigest()
    key = f'bodies/sha256/{digest[:2]}/{digest}.gz'
    target = root / key
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(gzip.compress(data))
    return dict(body_key=key, filename=name, source_url=url,
                source_paths=[path] if path else None, **fields)


def build(root, rows, **kwargs):
    (root / 'indexes').mkdir(exist_ok=True)
    index.write_filename_metadata(root, rows, workers=1, **kwargs)
    return (pq.read_table(root / 'indexes' / name).to_pylist()
            for name in ('document-filenames.parquet', 'documents.parquet'))


def test_typed_xml_identifies_source_records_and_witness_documents(tmp_path):
    rows = [
        retained(tmp_path, '123.xml', b'<committee-meeting meeting-id="HMKP123"><unknown x="keep"/></committee-meeting>'),
        retained(tmp_path, '124.xml', b'<witness-list meeting-id="HMKP124"><panel><witness/></panel></witness-list>'),
        retained(tmp_path, '125.xml', b'<witness-list/>'),
        retained(tmp_path, '126.xml', b'<witness-list meeting-id="HMKP999"/>'),
    ]
    sources, docs = build(tmp_path, rows)
    a, b, c, d = sources
    assert a['record_role'] == ['source-record']
    assert a['source_record_type'] == ['committee-meeting']
    assert a['document_kind'] is None
    assert b['document_kind'] == ['witness-list']
    assert b['document_kind_source'] == ['content']
    assert b['source_record_identifier'] == ['HMKP124']
    assert c['document_kind'] == ['witness-list']
    assert c['source_record_identifier'] is None  # Do not manufacture an ID.
    assert d['source_record_identifier'] == ['HMKP999']  # Embedded value wins.
    assert d.get('source_meeting_id') is None
    assert {r['body_key'] for r in sources} == {r['body_key'] for r in rows}
    assert all(r['format'] == ['xml'] for r in sources)


@pytest.mark.parametrize('data', [b'<floorschedule/>', b'<bill/>', b'<witness-list', b'<html>&nbsp;</html>'])
def test_foreign_and_malformed_xml_stay_unclassified(tmp_path, data):
    sources, _ = build(tmp_path, [retained(tmp_path, '123.xml', data)])
    row, = sources
    assert row['record_role'] == ['document']
    assert row['document_kind'] is None
    assert not row.get('source_record_identifier')


def test_amendment_xml_retains_native_meaning_and_replays_without_body_reads(tmp_path):
    data = b'''<?xml version="1.0"?><amendment-doc amend-stage="proposed"
        amend-type="house-amendment" amend-degree="first">
        <amendment-form><legis-num>Rules Committee Print 116-69</legis-num></amendment-form>
        <amendment-body><text>Strike the text.</text></amendment-body></amendment-doc>'''
    source = retained(tmp_path, 'BILLS-116HR1520SA-RCP116-69.xml', data)
    sources, docs = build(tmp_path, [source])
    for row in (sources[0], docs[0]):
        assert row['document_kind'] == ['amendment']
        assert row['document_kind_source'] == ['content']
        assert row['content_xml_root'] == ['amendment-doc']
        assert row['content_amendment_type'] == ['house-amendment']
        assert row['content_amendment_stage'] == ['proposed']
        assert row['content_amendment_degree'] == ['first']
        assert row['content_legis_num'] == ['Rules Committee Print 116-69']
        assert row['record_role'] == ['document']
        assert row['version_token'] == ['SA']  # Literal filename token stays intact.
        assert not row.get('version_token_code')  # No official GovInfo code inferred.
    before = pq.read_table(tmp_path/'indexes/document-filenames.parquet')
    def no_reads(key):
        raise AssertionError('Known XML contents should be cached')
    replay, _ = build(tmp_path, [source], previous=before, read_body=no_reads)
    assert replay == sources


@pytest.mark.parametrize('data', [
    b'<amendment-doc/>', b'<amendment-doc amend-type="unknown"><amendment-form/></amendment-doc>',
    b'<html><amendment-doc amend-type="house-amendment"/></html>',
])
def test_incomplete_or_embedded_amendment_roots_do_not_establish_kind(tmp_path, data):
    sources, _ = build(tmp_path, [retained(tmp_path, 'local.xml', data)])
    assert sources[0]['document_kind'] is None


@pytest.mark.parametrize(('data', 'state', 'attempted'), [
    (b'', 'empty', None),
    (b'https://docs.house.gov/meetings/A/123/WList.xml', 'url-pointer', 'https://docs.house.gov/meetings/A/123/WList.xml'),
    (b'https://docs.house.gov/meetings/A/123/HMTG-119-IF00', 'incomplete-url-pointer', 'https://docs.house.gov/meetings/A/123/HMTG-119-IF00'),
    (b'Please visit https://docs.house.gov/test.xml', 'unrecognized', None),
    (b'https://example.test/test.xml', 'unrecognized', None),
])
def test_house_cache_markers_preserve_history_without_claiming_absence(tmp_path, data, state, attempted):
    source = retained(tmp_path, '123.none', data, path='external/docs_house_xml/wlist/123.none')
    sources, docs = build(tmp_path, [source])
    for row in (sources[0], docs[0]):
        assert row['record_role'] == ['capture-state']
        assert row['cache_marker_state'] == [state]
        assert row.get('attempted_url') == ([attempted] if attempted else None)
        assert row['document_kind'] is None
        assert row['http_status'] is None
        assert row['format'] is None
    assert sources[0]['filename'] == '123.none'


def test_empty_files_outside_known_cache_are_not_markers(tmp_path):
    sources, _ = build(tmp_path, [
        retained(tmp_path, '123.none', b'', path='documents/123.none'),
        retained(tmp_path, '123.pdf', b'', path='external/docs_house_xml/wlist/123.pdf'),
    ])
    assert all(r['record_role'] == ['document'] for r in sources)
    assert all(not r.get('cache_marker_state') for r in sources)


def test_recovered_cache_name_reuses_known_url_and_merges_exact_pdf_without_losing_source(tmp_path):
    name = 'HHRG-119-IF00-WList-20250101.pdf'
    url = f'https://www.congress.gov/119/meeting/house/123/documents/{name}'
    encoded = 'house_123_documents_HHRG_119_IF00_WList_20250101_pdf'
    pdf = b'%PDF-1.4\nreal retained bytes'
    original = retained(tmp_path, name, pdf, url=url, media_type=['application/pdf'], http_status=['200'])
    cache = retained(tmp_path, encoded, pdf, path='witness_lists/' + encoded)
    sources, docs = build(tmp_path, [cache, original])
    assert len(docs) == 1
    row, = docs
    assert row['filename'] == name
    assert row['document_kind'] == ['witness-list']
    assert row['filenames'] == sorted([encoded, name])
    assert sources[0]['filename'] == encoded and sources[0]['source_url'] is None
    assert sources[0]['http_status'] is None  # No invented response status.
    assert sources[0]['recovered_filename'] == [name]
    assert sources[0]['recovered_source_url'] == [url]
    assert sources[0]['document_kind_source'] == ['recovered_filename']
    assert sources[0]['body_format'] == ['pdf']
    assert sources[0]['source_paths'] == ['witness_lists/' + encoded]
    assert not sources[0].get('name_token')  # The cache key is not a document subject.
    source_id, document_id = sources[0]['source_id'], row['document_id']
    # Cache reuse and grouping refresh must preserve provenance and identities.
    previous = pq.read_table(tmp_path / 'indexes/document-filenames.parquet')
    again, docs_again = build(tmp_path, [cache, original], previous=previous)
    assert again[0]['source_id'] == source_id
    assert docs_again[0]['document_id'] == document_id
    assert again[0]['document_kind_source'] == ['recovered_filename']
    index.reindex_documents(tmp_path)
    assert pq.read_table(tmp_path / 'indexes/documents.parquet').to_pylist() == docs_again


def test_xml_links_can_restore_names_without_inventory_url_rows(tmp_path):
    name = 'HHRG-119-IF00-20250101-SD001.pdf'
    url = f'https://www.congress.gov/119/meeting/house/123/documents/{name}'
    encoded = 'house_123_documents_HHRG_119_IF00_20250101_SD001_pdf'
    sources, docs = build(tmp_path, [
        retained(tmp_path, '123.xml', f'<committee-meeting><file doc-url="{url}"/></committee-meeting>'.encode()),
        retained(tmp_path, encoded, b'%PDF-1.4\n'),
    ])
    assert sources[1]['recovered_filename'] == [name]
    assert sources[1]['document_kind'] == ['meeting-support']
    assert next(r for r in docs if r['record_role'] == ['document'])['filename'] == name


def test_lossy_cache_name_collisions_do_not_choose_a_publisher_name(tmp_path):
    rows = [retained(tmp_path, 'house_123_documents_a_b_pdf', b'%PDF-1.4\n')]
    rows += [dict(body_key=None, filename=name, source_url=f'https://www.congress.gov/119/meeting/house/123/documents/{name}')
             for name in ('a-b.pdf', 'a_b.pdf')]
    sources, _ = build(tmp_path, rows)
    assert not sources[0].get('recovered_filename')
    assert sources[0]['document_kind'] is None


def test_not_found_response_keeps_requested_name_kind_but_never_counts_as_pdf(tmp_path):
    name = 'HHRG-119-IF00-WList-20250101.pdf'
    url = f'https://www.congress.gov/119/meeting/house/123/documents/{name}'
    encoded = 'house_123_documents_HHRG_119_IF00_WList_20250101_pdf'
    error = b'<html><head><title>Not Found | Committee Repository | U.S. House of Representatives</title></head><body>Not found</body></html>'
    sources, docs = build(tmp_path, [retained(tmp_path, encoded, error), dict(body_key=None, filename=name, source_url=url)])
    row = sources[0]
    assert row['record_role'] == ['error-response']
    assert row['format'] == ['html']
    assert row['document_kind'] == ['witness-list']  # Requested filename, not body validity.
    assert row['document_kind_source'] == ['recovered_filename']
    assert row['http_status'] is None
    assert len(docs) == 2  # Do not join an error body to an unfetched document.


def test_body_reader_is_injected_and_missing_evidence_does_not_infer_type(tmp_path):
    key = 'bodies/sha256/00/' + '0' * 64 + '.gz'
    row = dict(body_key=key, filename='123.xml', source_url=None)
    calls = []
    sources, _ = build(tmp_path, [row], read_body=lambda k: calls.append(k) or None)
    assert calls == [key]
    assert sources[0]['document_kind'] is None
    assert sources[0]['record_role'] == ['document']


def test_error_body_classification_follows_exact_bytes_but_does_not_merge_errors(tmp_path):
    name = 'HHRG-119-IF00-WList-20250101.pdf'
    encoded = 'house_123_documents_HHRG_119_IF00_WList_20250101_pdf'
    url = f'https://www.congress.gov/119/meeting/house/123/documents/{name}'
    error = b'<html><title>Not Found | Committee Repository | U.S. House of Representatives</title></html>'
    sources, docs = build(tmp_path, [
        retained(tmp_path, encoded, error),
        retained(tmp_path, name, error, url=url, media_type=['application/pdf'], http_status=['200']),
    ])
    assert len(docs) == 2
    assert all(r['record_role'] == ['error-response'] and r['format'] == ['html'] for r in sources)
    assert sources[1]['media_type'] == ['application/pdf']  # Preserve a wrong header too.


def test_recovered_metadata_is_not_reused_when_its_url_evidence_disappears(tmp_path):
    encoded = 'house_123_documents_HHRG_119_IF00_WList_20250101_pdf'
    name = 'HHRG-119-IF00-WList-20250101.pdf'
    cache = retained(tmp_path, encoded, b'%PDF-1.4\n')
    build(tmp_path, [cache, dict(body_key=None, filename=name,
          source_url=f'https://www.congress.gov/119/meeting/house/123/documents/{name}')])
    previous = pq.read_table(tmp_path / 'indexes/document-filenames.parquet')
    sources, _ = build(tmp_path, [cache], previous=previous)
    assert not sources[0].get('recovered_filename')
    assert sources[0]['document_kind'] is None


def test_retained_reader_checks_digest_and_does_not_read_outside_archive(tmp_path):
    from congress_api.retention.document_evidence import read_retained_body
    row = retained(tmp_path, '123.xml', b'<witness-list/>')
    assert read_retained_body(tmp_path, row['body_key'], limit=4) is None
    assert read_retained_body(tmp_path, '../elsewhere') is None
    (tmp_path / row['body_key']).write_bytes(gzip.compress(b'<bill/>'))
    with pytest.raises(ValueError, match='digest mismatch'):
        read_retained_body(tmp_path, row['body_key'])


def test_body_classification_cache_outlives_the_local_filename_alias(tmp_path):
    name = 'HHRG-119-IF00-WList-20250101.pdf'
    encoded = 'house_123_documents_HHRG_119_IF00_WList_20250101_pdf'
    url = f'https://www.congress.gov/119/meeting/house/123/documents/{name}'
    data = b'<html><title>Not Found | Committee Repository | U.S. House of Representatives</title></html>'
    cache = retained(tmp_path, encoded, data)
    original = retained(tmp_path, name, data, url=url, media_type=['application/pdf'], http_status=['200'])
    build(tmp_path, [cache, original])
    previous = pq.read_table(tmp_path / 'indexes/document-filenames.parquet')
    sources, _ = build(tmp_path, [original], previous=previous,
                       read_body=lambda _: pytest.fail('Unchanged bytes should use prior classification'))
    assert sources[0]['record_role'] == ['error-response']
    assert sources[0]['format'] == ['html']


def test_body_cache_is_invalidated_when_the_body_reader_changes(tmp_path, monkeypatch):
    row = retained(tmp_path, '123.xml', b'<witness-list/>')
    build(tmp_path, [row])
    previous = pq.read_table(tmp_path / 'indexes/document-filenames.parquet')
    monkeypatch.setattr(index, 'evidence_fingerprint', lambda: 'new-body-reader')
    reads = []
    sources, _ = build(tmp_path, [row], previous=previous,
                       read_body=lambda key: reads.append(key) or b'<committee-meeting/>')
    assert reads == [row['body_key']]
    assert sources[0]['record_role'] == ['source-record']
    assert sources[0]['document_kind'] is None
