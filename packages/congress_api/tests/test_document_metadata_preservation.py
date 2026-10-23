"""Saved response validity and paired link origins must survive catalog paths."""
from catalog_test_helpers import selected_path
from copy import deepcopy
import gzip
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

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


NAME = 'andersontestimony9-10-14.pdf'
URL = 'https://naturalresources.house.gov/uploadedfiles/' + NAME
BODY = 'bodies/sha256/aa/' + 'a' * 64 + '.gz'


def specificity_source(name=NAME, url=URL):
    return dict(body_key=BODY, filename=name, source_url=url,
                media_type=['application/pdf'], http_status=['200'], body_format=['pdf'],
                content_document_kind=['witness-statement'], content_title=['Retained witness statement'],
                **index.extract((name, url)))


def specificity_schema(rows):
    names = set().union(*(r.keys() for r in rows)) - set(index.SOURCE_SCHEMA.names)
    return pa.schema([*index.SOURCE_SCHEMA, *[(k, index.metadata_type(k)) for k in sorted(names)]])


def test_filename_only_api_stays_generic_while_index_retains_both_claims():
    assert index.extract((NAME, URL))['document_kind'] == ['testimony']
    row = specificity_source()
    index.fill_document_kind(row)
    assert row['document_kind'] == ['witness-statement']
    assert row['document_kind_source'] == ['content']
    assert row['filename_document_kind'] == ['testimony']
    assert row['content_document_kind'] == ['witness-statement']
    index.fill_document_kind(row)
    assert row['document_kind_source'] == ['content']
    row['content_document_kind'] = None
    index.fill_document_kind(row)
    assert row['document_kind'] == ['testimony']
    assert row['document_kind_source'] == ['filename']


@pytest.mark.parametrize('kinds,content,expected,basis', [
    (['report', 'testimony'], ['witness-statement'], ['report', 'witness-statement'], ['content', 'filename']),
    (['testimony', 'witness-statement'], ['witness-statement'], ['witness-statement'], ['filename']),
    (['testimony'], ['report'], ['testimony'], ['filename']),
    (['testimony'], ['report', 'witness-statement'], ['testimony'], ['filename']),
    (['transcript'], ['witness-statement'], ['transcript'], ['filename']),
    (['testimony'], None, ['testimony'], ['filename']),
])
def test_refinement_preserves_independent_and_conflicting_evidence(kinds, content, expected, basis):
    row = dict(document_kind=kinds, content_document_kind=content)
    index.fill_document_kind(row)
    assert row['document_kind'] == expected
    assert row['document_kind_source'] == basis
    assert row['filename_document_kind'] == kinds
    assert row['content_document_kind'] == content


@pytest.mark.parametrize('reverse', [False, True])
def test_both_groupers_restore_filename_after_content_correction(tmp_path, reverse):
    rows = [specificity_source(), specificity_source('opaque.pdf', 'https://example.gov/copy.pdf')]
    if reverse:
        rows.reverse()
    original_schema = specificity_schema(rows)
    expected_sources, _, expected_documents, _ = index.prepare_document_indexes(deepcopy(rows), original_schema)
    path = tmp_path / 'document-filenames.parquet'
    index.write_document_indexes(path, deepcopy(rows), original_schema)
    sources = pq.read_table(path)
    document, = pq.read_table(path.with_name('documents.parquet')).to_pylist()
    assert document['document_kind'] == ['witness-statement']
    assert document['document_kind_source'] == ['content']
    assert document['filename_document_kind'] == ['testimony']
    for field in ('document_kind', 'document_kind_source', 'filename_document_kind', 'source_ids'):
        assert document.get(field) == expected_documents[0].get(field)
    for actual, expected in zip(sources.to_pylist(), expected_sources):
        for field in ('source_id', 'document_kind', 'document_kind_source', 'filename_document_kind'):
            assert actual.get(field) == expected.get(field)
    # A corrected body classification must expose the saved filename claim,
    # including during regrouping without filename parsing or a body reader.
    corrected = sources.to_pylist()
    for row in corrected:
        row['content_document_kind'] = ['report']
    target = tmp_path / 'corrected'; target.mkdir()
    index.write_document_indexes(target / path.name, corrected, sources.schema)
    after, = pq.read_table(target / 'documents.parquet').to_pylist()
    assert after['document_kind'] == ['testimony']
    assert after['document_kind_source'] == ['filename']
    assert after['content_document_kind'] == ['report']
    assert after['document_id'] == document['document_id']
    _, _, reference, _ = index.prepare_document_indexes(deepcopy(corrected), sources.schema)
    assert reference[0]['document_kind'] == after['document_kind']
    assert reference[0]['document_kind_source'] == after['document_kind_source']


def test_cached_refresh_clear_and_source_regroup_preserve_raw_filename(tmp_path, monkeypatch):
    (tmp_path / 'indexes').mkdir()
    index.write_filename_metadata(tmp_path, [specificity_source()], workers=1)
    path = tmp_path / 'indexes/document-filenames.parquet'
    def rows():
        return [pq.read_table(selected_path(p)).to_pylist()[0]
                for p in (path, path.with_name('documents.parquet'))]
    initial = rows()
    assert all(r['document_kind'] == ['witness-statement'] for r in initial)
    fingerprint = index.parser_fingerprint()
    monkeypatch.setattr(index, 'parser_fingerprint', lambda: fingerprint)
    monkeypatch.setattr(index, 'extract', lambda _: pytest.fail('Cached filename must not be reparsed'))
    monkeypatch.setattr(index, 'read_retained_body', lambda *a: pytest.fail('Retained body must not be read'))
    refreshed = index.refresh_filename_metadata(tmp_path, workers=1)
    assert refreshed['parsed_inputs'] == 0
    index.refresh_source_metadata(tmp_path, index.DocumentSources())
    index.reindex_documents(tmp_path)
    assert all(r['document_kind'] == ['witness-statement'] and r['document_kind_source'] == ['content'] for r in rows())
    # Clear the accepted cover through the real explicit-reading API. A later
    # refresh must not resurrect the prior witness reading or lose testimony.
    previous = pq.read_table(selected_path(path))
    raw = dict(body_key=BODY, filename=NAME, source_url=URL,
               media_type=['application/pdf'], http_status=['200'])
    reading = dict(body_key=BODY, status='completed', parser_fingerprint='b' * 64, body_format=['pdf'])
    index.write_filename_metadata(tmp_path, [raw], workers=1, previous=previous, body_readings=[reading])
    index.refresh_filename_metadata(tmp_path, workers=1)
    index.reindex_documents(tmp_path)
    for before, after in zip(initial, rows()):
        assert after['document_kind'] == ['testimony']
        assert after['document_kind_source'] == ['filename']
        assert after['filename_document_kind'] == ['testimony']
        assert not after.get('content_document_kind')
        assert after['source_id'] == before['source_id']
        assert after['document_id'] == before['document_id']


@pytest.mark.parametrize('original_alias', [False, True])
def test_grouped_refinement_preserves_mixed_recovered_provenance(tmp_path, original_alias):
    row = specificity_source()
    row.update(filename='cache-key.pdf', recovered_filename=[NAME],
               document_kind=['report', 'testimony'])
    rows = [row]
    if original_alias:
        alias = specificity_source('Report.pdf', 'https://example.gov/Report.pdf')
        alias['document_kind'] = ['report']
        rows.append(alias)
    current_schema = specificity_schema(rows)
    _, _, reference, _ = index.prepare_document_indexes(deepcopy(rows), current_schema)
    path = tmp_path / 'document-filenames.parquet'
    index.write_document_indexes(path, rows, current_schema)
    doc, = pq.read_table(path.with_name('documents.parquet')).to_pylist()
    assert doc['document_kind'] == ['report', 'witness-statement']
    assert doc['filename_document_kind'] == ['report', 'testimony']
    assert doc['document_kind_source'] == ['content', 'filename' if original_alias else 'recovered_filename']
    assert doc['document_kind_source'] == reference[0]['document_kind_source']
