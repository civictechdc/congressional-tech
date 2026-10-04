"""Saved response validity and paired link origins must survive catalog paths."""
from catalog_test_helpers import selected_path
import gzip
import json

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.retention import document_index as index


def test_response_validation_follows_body_owner_and_preserves_false():
    record = {'first': {'usable': True, 'body_complete': True}, 'second': {
        'url': 'https://www.foreign.senate.gov/download/s-3492-as-reported04',
        'raw_path': 'failed.pdf.gz', 'http_status': 200, 'usable': False,
        'body_complete': True, 'format': 'pdf_missing_eof', 'result': 'unresolved_response',
    }}
    result = index.response_metadata({'pointer_json': '["second","raw_path"]'}, record)
    assert result['response_usable'] == {'false'}
    assert result['response_body_complete'] == {'true'}
    assert result['response_format'] == {'pdf_missing_eof'}
    assert result['response_result'] == {'unresolved_response'}
    assert index.response_metadata({'pointer_json': '[]'}, {}) == {
        'media_type': set(), 'http_status': set()}
    assert index.response_metadata({'pointer_json': '[]'}, {'complete': False})['response_body_complete'] == {'false'}


def test_source_refresh_recovers_historical_validation_without_fetching(tmp_path):
    (tmp_path / 'indexes').mkdir()
    (tmp_path / 'receipts').mkdir()
    source = dict(body_key='failed-body', filename='S.3492 as reported.pdf',
                  source_url='https://x.test/final.pdf', media_type=['application/pdf'], http_status=['200'])
    index.write_filename_metadata(tmp_path, [source], workers=1)
    key = 'receipts/original.jsonl.gz'
    with gzip.open(tmp_path / key, 'wt') as stream:
        stream.write(json.dumps({'record': {'attempt': {'url': 'https://x.test/download',
            'final_url': source['source_url'], 'raw_path': 'old.gz', 'usable': False,
            'body_complete': True, 'format': 'pdf_missing_eof', 'http_status': 200}}}) + '\n')
    pq.write_table(pa.Table.from_pylist([dict(body_key='failed-body', receipt_key=key, receipt_line=1,
        pointer_json='["attempt","raw_path"]', context_url='https://x.test/download')]),
        tmp_path / 'indexes/captures.parquet')
    anonymous = dict(body_key='failed-body', source_url=None)
    unrelated = dict(body_key='failed-body', source_url='https://other.test/success.pdf')
    index.refresh_response_metadata(tmp_path, [anonymous, unrelated])
    assert not any(anonymous.get(field) or unrelated.get(field) for field in index.RESPONSE_FIELDS)
    assert anonymous['source_capture_url'] == ['https://x.test/download', 'https://x.test/final.pdf']
    assert anonymous['source_occurrences'][0]['source_capture_url'] == anonymous['source_capture_url']
    assert not unrelated.get('source_occurrences')
    index.refresh_source_metadata(tmp_path, index.DocumentSources())
    for name in ('documents.parquet', 'document-filenames.parquet'):
        row, = pq.read_table(selected_path(tmp_path / 'indexes' / name)).to_pylist()
        assert row['response_usable'] == ['false']
        assert row['response_body_complete'] == ['true']
        assert row['response_format'] == ['pdf_missing_eof']
        assert row['record_role'] == ['error-response']
        assert row['body_key'] == 'failed-body'
    # New positive evidence on the same body/URL must clear capture-derived
    # failure, while retaining both historical validation observations.
    with gzip.open(tmp_path / key, 'wt') as stream:
        stream.write(json.dumps({'record': {'attempt': {'url': source['source_url'],
            'raw_path': 'old.gz', 'usable': True, 'body_complete': True, 'http_status': 200}}}) + '\n')
    index.refresh_source_metadata(tmp_path, index.DocumentSources())
    row, = pq.read_table(selected_path(tmp_path / 'indexes/document-filenames.parquet')).to_pylist()
    assert row['response_usable'] == ['false', 'true']
    assert row['record_role'] == ['document']


def test_unusable_pdf_bytes_do_not_join_unrelated_documents(tmp_path):
    (tmp_path / 'indexes').mkdir()
    rows = [dict(body_key='same-bad-pdf', filename='Report.pdf', source_url=f'https://x.test/{i}',
                 media_type=['application/pdf'], http_status=['200'], response_usable=['false'],
                 response_body_complete=['true'], response_format=['pdf_missing_eof']) for i in range(2)]
    index.write_filename_metadata(tmp_path, rows, workers=1)
    docs = pq.read_table(selected_path(tmp_path / 'indexes/documents.parquet')).to_pylist()
    assert len(docs) == 2
    assert all(r['response_usable'] == ['false'] for r in docs)
    assert all(r['record_role'] == ['error-response'] for r in docs)
    # A filename reading is still useful even when the saved body is unusable.
    assert all(r['document_kind'] == ['report'] for r in docs)


def test_occurrences_keep_labels_with_their_own_parents_across_aliases_and_refresh(tmp_path):
    (tmp_path / 'indexes').mkdir()
    rows = [dict(body_key='same-good-pdf', filename='Doe.pdf', source_url=f'https://x.test/{i}',
                 media_type=['application/pdf'], http_status=['200'], response_usable=['true'],
                 source_occurrences=[{'source_page_url': [f'https://committee.test/{i}'],
                                      'source_link_label': [label]}])
            for i, label in enumerate(('Article', 'Supporting attachment'))]
    index.write_filename_metadata(tmp_path, rows, workers=1)
    path = tmp_path / 'indexes/document-filenames.parquet'
    original = pq.read_table(selected_path(path))
    docs, = pq.read_table(selected_path(path.with_name('documents.parquet'))).to_pylist()
    assert pa.types.is_struct(original.schema.field('source_occurrences').type.value_type)
    pairs = {(tuple(r['source_page_url']), tuple(r['source_link_label'])) for r in docs['source_occurrences']}
    assert pairs == {(('https://committee.test/0',), ('Article',)),
                     (('https://committee.test/1',), ('Supporting attachment',))}
    index.refresh_filename_metadata(tmp_path, workers=1)
    refreshed = pq.read_table(selected_path(path))
    assert original['source_occurrences'] == refreshed['source_occurrences']
    assert original['response_usable'] == refreshed['response_usable']
    assert json.dumps(docs['source_occurrences'])  # Plain values remain API serializable.


def test_explicit_label_kind_is_recomputed_and_does_not_override_filename(tmp_path):
    (tmp_path / 'indexes').mkdir()
    source = dict(body_key=None, filename='SCA_Berman_Health_affairs.pdf', source_url='https://x.test/a',
                  source_document_type=['other'], source_label_document_kind=['article'])
    index.write_filename_metadata(tmp_path, [source], workers=1)
    path = tmp_path / 'indexes/document-filenames.parquet'
    row, = pq.read_table(selected_path(path)).to_pylist()
    assert row['document_kind'] == ['article']
    assert row['document_kind_source'] == ['source_link_label']
    index.write_filename_metadata(tmp_path, [{**source, 'source_label_document_kind': None}],
                                  workers=1, previous=pq.read_table(selected_path(path)))
    row, = pq.read_table(selected_path(path)).to_pylist()
    assert row['document_kind'] is None
    row = dict(document_kind=['transcript'], source_label_document_kind=['article'])
    index.fill_document_kind(row)
    assert row['document_kind'] == ['transcript']


def test_recovery_association_supplies_context_without_authorizing_type_fallback():
    occurrence = dict(source_document_type=['Witness Statement'], source_label_document_kind=['article'],
                      source_association_basis=['candidate_without_legacy_directory'])
    row = {**occurrence, 'source_occurrences': [occurrence]}
    index.fill_document_kind(row)
    assert row['document_kind'] is None
    assert row['source_document_type'] == ['Witness Statement']
    row['source_occurrences'].append({**occurrence, 'source_association_basis': ['publisher_redirect']})
    index.fill_document_kind(row)
    assert row['document_kind'] == ['witness-statement']


def test_candidate_stays_unconfirmed_after_a_later_publisher_redirect():
    context = index.DocumentSources()
    original, candidate, final = ('https://x.test/original', 'https://x.test/candidate', 'https://x.test/final')
    context.add_url(original, {'source_document_type': ['Witness Statement'],
                              'source_page_url': ['https://x.test/hearing'],
                              'source_receipt_key': ['origin.jsonl.gz'], 'source_receipt_line': ['3']})
    context.add_associations({'url': candidate, 'source_associations': [
        {'original_url': original, 'basis': 'candidate_without_legacy_directory'}]})
    context.add_redirect({'requested_url': candidate, 'url': final, 'http_status': 200},
                         {'source_receipt_key': ['later.jsonl.gz'], 'source_receipt_line': ['99']})
    row = context.for_url(final)
    assert row['source_association_basis'] == ['candidate_without_legacy_directory', 'publisher_redirect']
    assert row['source_occurrences'][0]['source_receipt_key'] == ['origin.jsonl.gz']
    assert row['source_occurrences'][0]['source_receipt_line'] == ['3']
    index.fill_document_kind(row)
    assert row['document_kind'] is None


def test_recurring_senate_tuple_is_not_a_publisher_document_type():
    context = index.DocumentSources()
    context.add_link({'url': 'https://www.epw.senate.gov/download/spw',
                      'native': ['other', 'SPW 03152023.pdf', 'https://www.epw.senate.gov/download/spw']})
    row = context.for_url('https://www.epw.senate.gov/download/spw')
    assert row['source_document_type'] == ['other']
    assert row['source_document_type_basis'] == ['senate_parser_fallback']
