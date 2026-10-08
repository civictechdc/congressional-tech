"""Self-references remain source context, not additional documents to fetch."""
import hashlib
import json
from pathlib import Path

import pytest

from congress_api.models.content import content_bytes
from congress_api.parsers.committee_pages import parse_event_page
from congress_api.parsers.document_links import document_links
from congress_api.parsers.senate_page import document_labels, source_details

PAGE = 'https://example.house.gov/download/testimony?id=7'
FIXTURES = Path(__file__).parent / 'fixtures/meeting_inventory/house-sites/circular-links'


@pytest.mark.parametrize('href', [PAGE, '#testimony', '?id=7', '/download/testimony?id=7', './testimony?id=7'])
def test_self_document_links_preserve_literal_occurrence(href):
    body = f'<html><body><a href="{href}" download>Download Testimony</a></body></html>'.encode()
    assert document_links(body, PAGE) == []
    page = parse_event_page(body, PAGE)
    assert page['documents'] == []
    assert page['document_metadata'] == {}
    assert page['page_metadata']['links'][0]['attributes']['href'] == href
    assert content_bytes(page['raw_html']) == body
    files, _, metadata = source_details(body, PAGE, [], plain=True)
    assert files == {}
    assert metadata['links'][0]['attributes']['href'] == href
    assert document_labels(body.decode(), PAGE) == {}


def test_other_documents_query_variants_and_fragments_are_kept():
    body = b'''<a href="?download=1">Download</a>
      <a href="/files/testimony.pdf#page=2">Testimony</a>
      <a href="https://other.house.gov/download/testimony?id=7">Download</a>'''
    assert {link.url for link in document_links(body, PAGE)} == {
        'https://example.house.gov/download/testimony?download=1',
        'https://example.house.gov/files/testimony.pdf',
        'https://other.house.gov/download/testimony?id=7'}


def test_base_url_does_not_replace_the_containing_page_identity():
    body = f'<base href="https://other.house.gov/"><a href="{PAGE}">Download</a><a href="other.pdf">PDF</a>'.encode()
    assert [link.url for link in document_links(body, PAGE)] == ['https://other.house.gov/other.pdf']


def test_self_embeds_and_refresh_do_not_schedule_the_containing_page():
    body = f'<iframe src="{PAGE}" type="application/pdf"></iframe><meta http-equiv="refresh" content="0; url={PAGE}">'.encode()
    assert document_links(body, PAGE) == []


def test_retained_download_testimony_self_reference_is_context_only():
    source = json.loads((FIXTURES/'source.json').read_text())
    body = (FIXTURES/'edworkforce-wrapper.html').read_bytes()
    assert hashlib.sha256(body).hexdigest() == source['sha256']
    page = parse_event_page(body, source['url'])
    assert page['event'] == source['event']
    assert page['documents'] == [d for d in source['documents'] if d[2] != source['url']]
    assert source['url'] not in page['document_metadata']
    assert any(link['text'] == 'Download Testimony' and link['attributes']['href'] == source['url']
               for link in page['page_metadata']['links'])
    assert content_bytes(page['raw_html']) == body
