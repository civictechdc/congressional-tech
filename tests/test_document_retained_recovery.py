"""Replay retained evidence without inventing downloads, aliases, or successes."""
import gzip
import json
from io import BytesIO
from zipfile import ZipFile

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.parsers.source_family import family
from congress_api.retention import document_index as index


def archive(root, records):
    (root / 'indexes').mkdir(exist_ok=True)
    captures = []
    with gzip.open(root / 'receipts.jsonl.gz', 'wt') as stream:
        for number, (capture, record) in enumerate(records, 1):
            stream.write(json.dumps({'record': record}) + '\n')
            captures.append({**dict(family='documents', context_url=None, original_path=None,
                body_key=None, pointer_json=None, source_file='capture.jsonl',
                receipt_key='receipts.jsonl.gz', receipt_line=number), **capture})
    pq.write_table(pa.Table.from_pylist(captures), root / 'indexes/captures.parquet')


def build(root, rows, bodies=None, **kwargs):
    (root / 'indexes').mkdir(exist_ok=True)
    index.write_filename_metadata(root, rows, workers=1,
                                  read_body=lambda key: (bodies or {}).get(key), **kwargs)
    return (pq.read_table(root / 'indexes/document-filenames.parquet').to_pylist(),
            pq.read_table(root / 'indexes/documents.parquet').to_pylist())


def source(name=None, url=None, body=None, **fields):
    return dict(filename=name, source_url=url, body_key=body, **fields)


def test_services_files_route_is_a_document_only_on_senate_sites():
    assert family(url='https://www.commerce.senate.gov/services/files/ABC') == 'documents'
    assert family(url='https://example.org/services/files/ABC') != 'documents'


def test_replay_joins_exact_final_url_and_keeps_all_body_versions(tmp_path):
    start = 'https://www.commerce.senate.gov/services/files/ABC'
    final = 'https://www.commerce.senate.gov/uploads/AEG21418.pdf'
    archive(tmp_path, [({'context_url': start, 'body_key': body, 'pointer_json': '["raw_path"]'},
                       {'raw_path': 'cache.pdf', 'final_url': final, 'http_status': 200,
                        'content_type': 'application/pdf', 'usable': True}) for body in ['v1', 'v2']])
    original = source('AEG21418.pdf', final, filename_origins=['filename_inventory'],
        source_occurrences=[{'source_association_basis': ['publisher_redirect'],
                             'source_associated_url': [start]}])
    rows, _ = build(tmp_path, [original, source('AEG21418.pdf', 'https://other.test/AEG21418.pdf')])
    recovered = [r for r in rows if r['source_url'] == final]
    assert {r['body_key'] for r in recovered} == {'v1', 'v2'}
    assert all('filename_inventory' in r['filename_origins'] for r in recovered)
    assert all(r['response_usable'] == ['true'] and r['http_status'] == ['200'] for r in recovered)
    assert all(r['source_receipt_key'] == ['receipts.jsonl.gz'] for r in recovered)
    assert next(r for r in rows if r['source_url'].startswith('https://other'))['body_key'] is None


@pytest.mark.parametrize('status,http', [('not_found', 404), ('blocked', 403), ('not_attempted_host_blocked', None)])
def test_failed_or_unattempted_generated_xml_is_a_probe_not_an_ordinary_document(tmp_path, status, http):
    url = 'https://example.test/Vita.xml'
    archive(tmp_path, [({'source_file': 'external-sources/hearing-text/xml_path_families/attempts.jsonl'},
        {'xml_url': url, 'pdf_url': url.replace('.xml', '.pdf'), 'status': status,
         'http_status': http, 'arm': 'extension replacement', 'checked_at': '2026-09-27'})])
    rows, docs = build(tmp_path, [source('Vita.xml', url)])
    assert docs[0]['record_role'] == ['capture-state']
    assert rows[0]['source_probe_status'] == [status]
    assert rows[0]['http_status'] == ([str(http)] if http else None)
    assert rows[0]['source_association_basis'] == ['generated_xml_probe']
    assert rows[0]['source_associated_url'] == ['https://example.test/Vita.pdf']


def test_old_failed_probe_does_not_poison_a_later_retained_xml(tmp_path):
    url = 'https://example.test/Vita.xml'
    archive(tmp_path, [({'source_file': 'external-sources/hearing-text/pdf_xml_probe/attempts.jsonl'},
        {'xml_url': url, 'pdf_url': url.replace('.xml', '.pdf'), 'status': 'not_found', 'http_status': 404})])
    rows, docs = build(tmp_path, [source('Vita.xml', url, 'xml', http_status=['200'])],
                       {'xml': b'<witness-list meeting-id="HMKP123"/>'})
    assert rows[0]['http_status'] == ['200']
    assert docs[0]['record_role'] == ['document']


def test_anonymous_verified_pdf_joins_named_copy_without_copying_response_failure(tmp_path):
    name = 'HHRG-117-II13-20211104-SD011.pdf'
    rows, docs = build(tmp_path, [source(None, None, 'pdf'),
        source(name, 'https://docs.house.gov/' + name, 'pdf', media_type=['application/pdf'], http_status=['200'])],
        {'pdf': b'%PDF-1.4\nfixture'})
    assert len(docs) == 1
    assert docs[0]['document_kind'] == ['meeting-support']
    assert next(r for r in rows if r['filename'] is None)['http_status'] is None


def test_anonymous_house_xml_is_interpreted_from_its_root(tmp_path):
    rows, docs = build(tmp_path, [source(body='xml')], {'xml': b'<committee-meeting meeting-id="HMKP123"/>'})
    assert rows[0]['body_format'] == ['xml']
    assert docs[0]['record_role'] == ['source-record']


def test_local_path_receipt_corrects_only_the_matching_saved_copy(tmp_path):
    path = 'external-sources/hearing-text/senate_pages/broken.html'
    archive(tmp_path, [({'body_key': 'damaged', 'original_path': path, 'pointer_json': '["raw_reference","path"]'},
        {'raw_reference': {'path': path, 'usable': False, 'reason': 'pdf_not_html', 'format': 'pdf'}})])
    rows, _ = build(tmp_path, [source('broken.html', body='damaged', source_paths=[path]),
                              source('unrelated.html', body='damaged', source_paths=['different.html'])])
    assert rows[0]['record_role'] == ['error-response']
    assert rows[0]['response_format'] == ['pdf']
    assert rows[1]['record_role'] == ['document']


def test_relocated_local_cache_requires_same_relative_path_and_body(tmp_path):
    path = '/Users/collector/hearing-text/senate_pages/broken.html'
    archive(tmp_path, [({'body_key': 'damaged', 'original_path': path, 'pointer_json': '["raw_reference","path"]'},
        {'raw_reference': {'path': path, 'usable': False, 'format': 'pdf'}})])
    rows, _ = build(tmp_path, [
        source('broken.html', body='damaged', source_paths=['external-sources/hearing-text/senate_pages/broken.html']),
        source('broken.html', body='damaged', source_paths=['external-sources/hearing-text/other/broken.html'], url='https://other.test/broken.html'),
        source('broken.html', body='different', source_paths=['external-sources/hearing-text/senate_pages/broken.html']),
    ])
    assert [r['record_role'] for r in rows] == [['error-response'], ['document'], ['document']]


@pytest.mark.parametrize('title', ['Page Not Found | GovInfo', 'U.S. Senate: 404 Error Page', '403 Forbidden'])
def test_saved_html_error_is_not_a_document_even_with_http_200(tmp_path, title):
    _, docs = build(tmp_path, [source('cached.html', body='html', http_status=['200'])],
                    {'html': f'<html><title>{title}</title></html>'.encode()})
    assert docs[0]['record_role'] == ['error-response']


def test_failed_xml_interpretation_does_not_hide_html_error_evidence(tmp_path):
    rows, _ = build(tmp_path, [source('unknown.xml', body='html'), source('page.htm', body='html')],
                    {'html': b'<html><title>Page Not Found | GovInfo</title></html>'})
    assert all(r['record_role'] == ['error-response'] and r['body_format'] == ['html'] for r in rows)


def test_unattempted_inventory_candidate_remains_distinct_from_failed_probe(tmp_path):
    url = 'https://example.test/Vita.xml'
    archive(tmp_path, [({'source_file': 'external-sources/hearing-text/pdf_xml_probe/inventory.jsonl'},
        {'xml_url': url, 'pdf_url': url.replace('.xml', '.pdf')})])
    rows, docs = build(tmp_path, [source('Vita.xml', url)])
    assert rows[0]['source_probe_status'] == ['candidate']
    assert rows[0]['http_status'] is None
    assert docs[0]['record_role'] == ['capture-state']


def test_anonymous_zip_gets_format_without_inventing_document_kind(tmp_path):
    stream = BytesIO()
    with ZipFile(stream, 'w') as package:
        package.writestr('meeting.xml', '<committee-meeting/>')
    rows, _ = build(tmp_path, [source(body='zip')], {'zip': stream.getvalue()})
    assert rows[0]['body_format'] == ['zip']
    assert rows[0]['document_kind'] is None


def test_failed_bodyless_receipt_keeps_native_status_without_inventing_body(tmp_path):
    url = 'https://example.test/missing.pdf'
    archive(tmp_path, [({'context_url': url}, {'url': url, 'http_status': 404, 'usable': False})])
    rows, _ = build(tmp_path, [source('missing.pdf', url)])
    assert rows[0]['body_key'] is None
    assert rows[0]['http_status'] == ['404']
    assert rows[0]['record_role'] == ['error-response']


def test_genuine_html_document_is_preserved(tmp_path):
    _, docs = build(tmp_path, [source('article.html', 'https://example.org/article.html', 'html')],
                    {'html': b'<html><title>A real document</title></html>'})
    assert docs[0]['record_role'] == ['document']


def test_extensionless_hearing_page_keeps_source_role(tmp_path):
    _, docs = build(tmp_path, [source('a-hearing', 'https://democrats-homeland.house.gov/activities/hearings/a-hearing', 'html')],
                    {'html': b'<html><title>A hearing</title></html>'})
    assert docs[0]['record_role'] == ['source-record']


def test_provider_response_cannot_be_used_as_the_publishers_file(tmp_path):
    url = 'https://example.test/a.pdf'
    archive(tmp_path, [({'family': 'external/provider-responses', 'context_url': url, 'body_key': 'transport'},
                       {'url': url, 'content_type': 'application/json', 'http_status': 200})])
    rows, _ = build(tmp_path, [source('a.pdf', url)])
    assert rows[0]['body_key'] is None


def test_probe_facts_survive_a_source_context_only_refresh(tmp_path):
    url = 'https://example.test/Vita.xml'
    archive(tmp_path, [({'source_file': 'external-sources/hearing-text/pdf_xml_probe/attempts.jsonl'},
        {'xml_url': url, 'pdf_url': url.replace('.xml', '.pdf'), 'status': 'not_found', 'http_status': 404})])
    build(tmp_path, [source('Vita.xml', url)])
    index.refresh_source_metadata(tmp_path, index.DocumentSources())
    row, = pq.read_table(tmp_path / 'indexes/document-filenames.parquet').to_pylist()
    assert row['source_probe_status'] == ['not_found']
    assert row['record_role'] == ['capture-state']


def test_anonymous_xml_body_cache_replays_without_rereading(tmp_path):
    row = source(body='xml')
    build(tmp_path, [row], {'xml': b'<witness-list meeting-id="HMKP123"/>'})
    previous = pq.read_table(tmp_path / 'indexes/document-filenames.parquet')
    index.write_filename_metadata(tmp_path, [row], workers=1, previous=previous,
        read_body=lambda _: pytest.fail('Immutable XML meaning should be cached'))
    assert pq.read_table(tmp_path / 'indexes/document-filenames.parquet').to_pylist() == previous.to_pylist()


def test_recurring_catalog_replays_old_consumed_receipts_once_then_new_attempts(tmp_path):
    from congress_api.retention.raw_catalog import rebuild_catalog, FILENAMES, DOCUMENTS
    from test_raw_source_sync import MemoryStore

    url = 'https://example.test/Vita.xml'
    build(tmp_path, [source('Vita.xml', url)], metadata={'raw_capture_rows': '1'})
    archive(tmp_path, [({'source_file': 'external-sources/hearing-text/pdf_xml_probe/attempts.jsonl'},
        {'xml_url': url, 'pdf_url': url.replace('.xml', '.pdf'), 'status': 'not_found', 'http_status': 404})])
    store = MemoryStore()
    for path in (FILENAMES, DOCUMENTS, 'receipts.jsonl.gz'):
        store.objects[path] = (tmp_path / path).read_bytes()
    captures = pq.read_table(tmp_path / 'indexes/captures.parquet')
    rebuild_catalog(store, captures, workers=1)
    first = pq.read_table(pa.BufferReader(store.read(FILENAMES)))
    assert first.to_pylist()[0]['source_probe_status'] == ['not_found']
    rebuild_catalog(store, captures, workers=1)
    assert pq.read_table(pa.BufferReader(store.read(FILENAMES))).to_pylist() == first.to_pylist()
    # A later metadata-only attempt must be consumed even though it is not a download receipt.
    capture = {**captures.to_pylist()[0], 'receipt_key': 'next.jsonl.gz'}
    store.objects['next.jsonl.gz'] = gzip.compress(json.dumps({'record': {
        'xml_url': url, 'pdf_url': url.replace('.xml', '.pdf'), 'status': 'blocked', 'http_status': 403}}).encode())
    rebuild_catalog(store, pa.Table.from_pylist([*captures.to_pylist(), capture], schema=captures.schema), workers=1)
    row, = pq.read_table(pa.BufferReader(store.read(FILENAMES))).to_pylist()
    assert row['source_probe_status'] == ['blocked', 'not_found']
    assert row['http_status'] == ['403', '404']
