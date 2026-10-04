"""Resolve catalog aliases only from observed anchors; retain anonymous evidence."""
from catalog_test_helpers import selected_path
from copy import deepcopy
import gzip
import json

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.parsers.senate_page import source_details
from congress_api.retention import document_index as index


NAME = '1019-Supporting-Israel-and-Ukraine-Against-Terror.pdf'
HREF = '/sites/evo-subsites/csce.house.gov/files/migrated/uploads/2023/10/' + NAME
PAGE = 'https://www.csce.gov/hearings/israel-and-ukraine-against-terror'
URL = 'https://www.csce.gov' + HREF


def add_page(context, page=PAGE):
    files, _, _ = source_details(f'<main><a href="{HREF}" class="transcript-link">Transcript</a></main>', page, [])
    target, = files
    context.add_senate({'www.csce.gov': {'pages': {page: {
        'title': 'Israel and Ukraine Against Terror', 'documents': [['transcript', 'Transcript', target]],
        'document_metadata': files,
    }}}}, {'source_receipt_key': {'pages.jsonl.gz'}, 'source_receipt_line': {'3'}})


def source(url, body=None):
    return dict(filename=NAME, source_url=url, body_key=body,
                media_type=['application/pdf'], http_status=['200'] if body else None)


def documents(rows):
    fields = set().union(*(r.keys() for r in rows)) - set(index.SOURCE_SCHEMA.names)
    schema = pa.schema([*index.SOURCE_SCHEMA, *[(f, index.metadata_type(f)) for f in sorted(fields)]])
    return index.prepare_document_indexes(deepcopy(rows), schema)[2]


def test_retained_relative_anchor_joins_existing_download_and_keeps_literal_source():
    context = index.DocumentSources()
    add_page(context)
    relative = {**source(HREF), **context.for_url(HREF)}
    complete = {**source(URL, 'retained-pdf'), **context.for_url(URL)}
    expected_id = documents([complete])[0]['document_id']
    result, = documents([relative, complete])
    assert result['document_id'] == expected_id
    assert result['source_urls'] == sorted([HREF, URL])
    assert result['source_url'] == URL
    assert result['document_kind'] == ['transcript']
    assert relative['source_resolved_url'] == [URL]
    occurrence, = relative['source_occurrences']
    assert occurrence['source_link_href'] == [HREF]
    assert occurrence['source_original_page_url'] == [PAGE]
    assert occurrence['source_receipt_line'] == ['3']


def test_same_relative_href_on_two_hosts_does_not_merge_either_document():
    context = index.DocumentSources()
    add_page(context)
    add_page(context, 'https://different.test/hearing')
    relative = {**source(HREF), **context.for_url(HREF)}
    rows = [relative, source(URL, 'one'), source('https://different.test' + HREF, 'two')]
    assert len(documents(rows)) == 3
    assert relative['source_resolved_url'] == sorted([URL, 'https://different.test' + HREF])
    assert {(o['source_original_page_url'][0], o['source_resolved_url'][0])
            for o in relative['source_occurrences']} == {(PAGE, URL),
                ('https://different.test/hearing', 'https://different.test' + HREF)}


def test_equal_basename_without_observed_anchor_is_not_an_alias():
    assert len(documents([source(HREF), source(URL, 'one'),
                          source('https://different.test/' + NAME, 'two')])) == 3


def test_url_without_basename_survives_source_discovery():
    url = 'https://www.appropriations.senate.gov/download/?id=0519C347'
    row = dict(context_url=url, pointer_json='["raw_path"]', original_path=None)
    names = index.source_names(row, {'raw_path': None, 'url': url})
    assert names == [(None, None, url, url)]


def test_nameless_endpoint_does_not_discard_a_retained_local_filename():
    url = 'https://x.test/download/?id=1'
    row = dict(context_url=url, pointer_json='[]', original_path='cache/actual.pdf')
    assert index.source_names(row, {}) == [('actual.pdf', 'retained_path', url, 'cache/actual.pdf')]


def anonymous_archive(root):
    (root / 'indexes').mkdir()
    captures = []
    records = [
        ('house/meeting-xml', 'source-fidelity/house/house.json.gz',
         {'334482': {'evidence': {'html': None}}}, '["334482","evidence","html"]', 'house-page'),
        ('documents', 'recovery.jsonl', {'raw_path': None}, '["raw_path"]', 'unknown-body'),
    ]
    with gzip.open(root / 'receipts.jsonl.gz', 'wt') as stream:
        for n, (family, file, record, pointer, body) in enumerate(records, 1):
            stream.write(json.dumps({'record': record}) + '\n')
            captures.append(dict(family=family, source_file=file, body_key=body,
                context_url=None, pointer_json=pointer, receipt_key='receipts.jsonl.gz', receipt_line=n))
    pq.write_table(pa.Table.from_pylist(captures), root / 'indexes/captures.parquet')


def test_anonymous_source_page_keeps_capture_locator_without_inventing_url(tmp_path):
    anonymous_archive(tmp_path)
    rows = [dict(body_key=body, filename=None, source_url=None, media_type=['text/html'])
            for body in ['house-page', 'unknown-body']]
    index.write_filename_metadata(tmp_path, rows, workers=1)
    path = tmp_path / 'indexes/document-filenames.parquet'
    before = pq.read_table(selected_path(path))
    page, unknown = before.to_pylist()
    assert page['record_role'] == ['source-record']
    assert page['source_record_type'] == ['committee-meeting-page']
    assert page['filename'] is None and page['source_url'] is None
    occurrence, = page['source_occurrences']
    assert occurrence['source_capture_file'] == ['source-fidelity/house/house.json.gz']
    assert occurrence['source_capture_pointer'] == ['["334482","evidence","html"]']
    assert occurrence['source_receipt_key'] == ['receipts.jsonl.gz']
    assert occurrence['source_receipt_line'] == ['1']
    assert unknown['record_role'] == ['document']
    assert not unknown.get('source_record_type')
    index.refresh_source_metadata(tmp_path, index.DocumentSources())
    after = pq.read_table(selected_path(path))
    assert before.to_pylist() == after.to_pylist()
    index.refresh_filename_metadata(tmp_path, workers=1)
    assert before.to_pylist() == pq.read_table(selected_path(path)).to_pylist()


def test_cached_filename_metadata_cannot_type_another_anonymous_body(tmp_path):
    anonymous_archive(tmp_path)
    # Put the source page last so its body-derived meaning is the tempting
    # cache value for the shared (None, None) filename/URL pair.
    rows = [dict(body_key=body, filename=None, source_url=None, media_type=['text/html'])
            for body in ['unknown-body', 'house-page']]
    index.write_filename_metadata(tmp_path, rows, workers=1)
    previous = pq.read_table(selected_path(tmp_path / 'indexes/document-filenames.parquet'))
    index.write_filename_metadata(tmp_path, rows, workers=1, previous=previous)
    after = pq.read_table(selected_path(tmp_path / 'indexes/document-filenames.parquet'))
    assert previous.to_pylist() == after.to_pylist()


def test_equal_body_does_not_assign_capture_origins_to_unlocated_named_files(tmp_path):
    anonymous_archive(tmp_path)
    rows = [dict(body_key='unknown-body', filename=name, source_url=None)
            for name in ['123.none', '456.none']]
    index.refresh_response_metadata(tmp_path, rows)
    assert all(not row.get('source_occurrences') for row in rows)
