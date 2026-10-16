"""Explicit opening forms classify; references and incomplete forms abstain."""
import json
from pathlib import Path

import pytest

from congress_api.parsers.document_cover import document_page_fields

RECORDS = json.loads((Path(__file__).parent / 'fixtures/document-covers/development-forms.json').read_text())['records']
BY_ID = {r['review_id']: r for r in RECORDS}


@pytest.mark.parametrize('row', RECORDS, ids=lambda row: row['review_id'])
def test_reviewed_development_opening_forms(row):
    fields = document_page_fields(row['assisted_text'])
    assert fields.get('content_document_kind', []) == ([row['expected_assisted']] if row['expected_assisted'] else [])
    native = document_page_fields(row['native_text'])
    assert native.get('content_document_kind', []) in ([], [row['reference_kind']])


@pytest.mark.parametrize('identity', ['D099', 'D111', 'D141'])
@pytest.mark.parametrize('prefix', ['Report about document forms\n', 'MEMORANDUM\n', 'SUMMARY\n',
                                  'Dear Chairman,\n', 'DEAR CHAIRMAN,\n', 'For your reference, please see this document:\n'])
def test_form_quoted_after_another_opening_does_not_classify(identity, prefix):
    assert document_page_fields(prefix + BY_ID[identity]['native_text']) == {}


@pytest.mark.parametrize(('identity', 'old', 'new'), [
    ('D099', 'OFFERED BY', 'SUMMARIZED BY'),
    ('D099', 'Page 3, line 5, strike', 'This document discusses'),
    ('D141', 'Serial No. 113–11', 'Reference to serial 113–11'),
    ('D141', 'U.S. GOVERNMENT PRINTING OFFICE', 'PRIVATE PUBLISHER'),
    ('D141', 'HEARING\nBEFORE THE', 'MEETING NOTICE\nFOR THE'),
    ('D111', 'ROLL CALL', 'MEMBERSHIP ROSTER'),
])
def test_missing_structure_abstains(identity, old, new):
    text = BY_ID[identity]['native_text']
    assert old in text
    assert document_page_fields(text.replace(old, new)) == {}


def test_blank_vote_template_abstains():
    text = 'COMMITTEE ON SMALL BUSINESS\nROLL CALL: 6\nMEMBER\nMr. Smith\nMs. Brown\nMr. Green\nAYE\nNO\nPRESENT\n'
    assert document_page_fields(text) == {}


@pytest.mark.parametrize('identity', ['D099', 'D111', 'D141'])
def test_later_page_does_not_override_document(identity):
    assert document_page_fields('Cover of an unrelated report', BY_ID[identity]['native_text']) == {}


def test_house_serial_is_not_invented_as_a_gpo_citation():
    assert document_page_fields(BY_ID['D141']['native_text']) == {'content_document_kind': ['published-hearing']}


def test_amending_a_substitute_does_not_claim_to_be_a_substitute():
    fields = document_page_fields(BY_ID['D174']['assisted_text'])
    assert fields == {'content_document_kind': ['amendment']}


@pytest.mark.parametrize(('name', 'kind'), [
    ('house-amendment', 'amendment'), ('house-vote', 'committee-vote'),
    ('house-hearing', 'published-hearing'),
])
def test_real_pdf_readers_and_paired_tables(tmp_path, name, kind):
    import gzip
    from hashlib import sha256
    import pyarrow.parquet as pq
    from catalog_test_helpers import selected_path
    from congress_api.retention.capture_metadata import inspect_document, inspect_pdf_file
    from congress_api.retention import document_index as index

    path = Path(__file__).parent / 'fixtures/document-covers' / (name + '.pdf')
    data = path.read_bytes()
    assert inspect_document(data)['content_document_kind'] == [kind]
    assert inspect_pdf_file(path)['content_document_kind'] == [kind]
    digest = sha256(data).hexdigest()
    key = f'bodies/sha256/{digest[:2]}/{digest}.gz'
    saved = tmp_path / key
    saved.parent.mkdir(parents=True)
    saved.write_bytes(gzip.compress(data))
    (tmp_path / 'indexes').mkdir()
    index.write_filename_metadata(tmp_path, [dict(
        filename='opaque.pdf', source_url='https://example.org/opaque.pdf',
        body_key=key, media_type=['application/pdf'], **inspect_document(data))], workers=1)
    rows = []
    for filename in ['document-filenames.parquet', 'documents.parquet']:
        row, = pq.read_table(selected_path(tmp_path / 'indexes' / filename)).to_pylist()
        assert row['document_kind'] == [kind]
        assert row['document_kind_source'] == ['content']
        assert row['content_document_kind'] == [kind]
        rows.append(row)
    assert rows[0]['document_id'] == rows[1]['document_id']
