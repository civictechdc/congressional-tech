"""Blank publisher anchors still have their explicit local section context."""
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from congress_api.parsers.committee_pages import parse_event_page

FIXTURES = Path(__file__).parent / 'fixtures/meeting_inventory/house-sites/empty-opening-labels'
SOURCES = json.loads((FIXTURES / 'sources.json').read_text())


@pytest.mark.parametrize('source', SOURCES, ids=[s['file'] for s in SOURCES])
def test_retained_empty_opening_links_preserve_occurrence_context(source):
    body = gzip.decompress((FIXTURES / source['file']).read_bytes())
    assert hashlib.sha256(body).hexdigest() == source['sha256']
    page = parse_event_page(body, source['url'])
    documents = {d[2] for d in page['documents']}
    for expected in source['expected']:
        assert expected['url'] in documents
        current = page['document_metadata'][expected['url']]['occurrences']
        for original in expected['occurrences']:
            assert any(all(o.get(k) == v for k, v in original.items() if k != 'related_page')
                       for o in current)


def test_blank_anchor_needs_an_explicit_document_section():
    page = parse_event_page(b'<h2>Information</h2><a href="/news/item"> </a>',
                            'https://example.house.gov/hearings/item')
    assert not page['documents']
    assert page['page_metadata']['links'][0]['attributes']['href'] == '/news/item'


@pytest.mark.parametrize('source', json.loads((FIXTURES / 'priority-sources.json').read_text()))
def test_specific_document_evidence_precedes_generic_testimony_or_opening_section(source):
    body = gzip.decompress((FIXTURES / source['file']).read_bytes())
    assert hashlib.sha256(body).hexdigest() == source['sha256']
    page = parse_event_page(body, source['url'])
    assert all(document in page['documents'] for document in source['expected'])


@pytest.mark.parametrize('label', ['Printed Hearing Text', 'Hearing Transcript', 'Transcript'])
def test_explicit_transcript_label_precedes_inherited_opening_heading(label):
    page = parse_event_page(f'<h2>Opening Statements</h2><a href="/legacy/item">{label}</a>'.encode(),
                            'https://example.house.gov/hearings/item')
    assert page['documents'] == [['transcript', label, 'https://example.house.gov/legacy/item']]
