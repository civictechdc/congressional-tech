"""Response validation affects its capture, while content evidence follows bytes."""
from copy import deepcopy

import pytest

from congress_api.retention import document_evidence as evidence
from house_naming import Engine


PDF = b'%PDF-1.4\nretained fixture bytes'
ENCODED = 'house_123_documents_HHRG_119_IF00_WList_20250101_pdf'
URL = 'https://www.congress.gov/119/meeting/house/123/documents/HHRG-119-IF00-WList-20250101.pdf'


def enrich(rows, data=PDF, *, cached=None):
    engine = Engine()
    return evidence.enrich_sources(
        deepcopy(rows), read_body=lambda _: data,
        extract=lambda pair: engine.extract(pair[0], source_url=pair[1])['metadata'], cached=cached)


def source(name='HHRG-119-IF00-WList-20250101.pdf', **fields):
    return dict(filename=name, source_url=URL, body_key='same-body',
                document_kind=['witness-list'], document_kind_source=['filename'], **fields)


@pytest.mark.parametrize('fields', [
    {'response_usable': ['false'], 'http_status': ['200']},
    {'response_body_complete': ['false'], 'http_status': ['200']},
    {'http_status': ['404']},
    {'http_status': ['302', '503']},
    {'capture_outcome': ['challenge']},
    {'capture_outcome': ['incomplete', 'error']},
    {'capture_outcome': ['challenge'], 'response_usable': ['true']},
])
def test_definitive_failed_responses_keep_expected_filename_meaning_and_evidence(fields):
    original = source(**fields)
    row, = enrich([original])
    assert row['record_role'] == ['error-response']
    assert {key: row[key] for key in original} == original
    assert row['document_kind'] == ['witness-list']
    assert 'source_record_type' not in row  # A response failure does not invent an error page.


@pytest.mark.parametrize('fields', [
    {},
    {'response_usable': None, 'response_body_complete': None, 'http_status': None},
    {'http_status': ['unknown']},
    {'http_status': ['200', '404']},
    {'response_usable': ['false', 'true'], 'http_status': ['404']},
    {'response_usable': ['true'], 'http_status': ['404']},
    {'response_body_complete': ['false', 'true'], 'http_status': ['200']},
    {'capture_outcome': ['saved', 'challenge']},
    {'capture_outcome': ['html']},
    {'capture_outcome': ['inspection_deferred']},
    {'capture_outcome': ['unverified']},
    {'capture_outcome': ['retained']},
])
def test_missing_or_mixed_response_evidence_does_not_assert_definitive_failure(fields):
    row, = enrich([source(**fields)])
    assert row['record_role'] == ['document']


def test_success_status_does_not_override_explicit_incomplete_content():
    row, = enrich([source(response_usable=['true'], response_body_complete=['false'], http_status=['200'])])
    assert row['record_role'] == ['error-response']


def test_genuine_html_is_not_an_error_response():
    row, = enrich([source(ENCODED, http_status=['200'], response_usable=['true'])],
                  b'<html><title>Committee hearing</title><main>Witness statement</main></html>')
    assert row['record_role'] == ['document']
    assert row['body_format'] == ['html']


def test_capture_failure_does_not_spread_to_other_capture_of_same_bytes():
    rows = [source(ENCODED, response_usable=['false'], http_status=['503']),
            source(response_usable=['true'], http_status=['200'])]
    failed, good = enrich(rows)
    assert failed['record_role'] == ['error-response']
    assert good['record_role'] == ['document']
    assert failed['body_format'] == good['body_format'] == ['pdf']
    assert failed['response_usable'] == ['false'] and good['response_usable'] == ['true']


@pytest.mark.parametrize(('name', 'data'), [
    (ENCODED, PDF),
    ('123.xml', b'<witness-list meeting-id="HMKP123"/>'),
    ('amendment.xml', b'<amendment-doc amend-type="house-amendment"><amendment-form/><amendment-body/></amendment-doc>'),
])
def test_replay_cache_does_not_copy_capture_failure_into_successful_capture(name, data):
    fields = {'document_kind': None} if name.endswith('.xml') else {}
    failed = source(name, response_usable=['false'], http_status=['503'])
    failed.update(fields)
    first, = enrich([failed], data)
    assert first['record_role'] == ['error-response']
    key = evidence.body_evidence_key(first)
    assert key is not None
    cached = {key: evidence.cached_body_fields(first, key)}
    good = source(name, response_usable=['true'], http_status=['200'])
    good.update(fields)
    row, = evidence.enrich_sources(
        [good], read_body=lambda _: pytest.fail('Replay must reuse immutable body evidence'),
        extract=lambda _: {}, cached=cached)
    assert row['record_role'] == ['document']
    assert row['body_format'] == first['body_format']


def test_content_proven_error_page_still_follows_identical_bytes_across_captures():
    error = b'<html><title>Not Found | Committee Repository | U.S. House of Representatives</title></html>'
    failed, good_status = enrich([source(ENCODED, http_status=['404']), source(http_status=['200'])], error)
    assert failed['record_role'] == good_status['record_role'] == ['error-response']
    assert good_status['source_record_type'] == ['error-page']


@pytest.mark.parametrize(('row', 'data', 'role'), [
    (dict(filename='123.xml', body_key='same-body'), b'<committee-meeting meeting-id="HMKP123"/>', 'source-record'),
    (dict(filename='123.none', body_key='same-body', source_paths=['docs_house_xml/wlist/123.none']), b'', 'capture-state'),
])
def test_source_record_and_cache_marker_roles_take_precedence(row, data, role):
    row.update(response_usable=['false'], http_status=['404'])
    result, = enrich([row], data)
    assert result['record_role'] == [role]
    assert result['response_usable'] == ['false']
