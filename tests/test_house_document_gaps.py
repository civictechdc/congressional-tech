"""Exact retained omissions and counterexamples for publisher document context."""
import hashlib
import json
from pathlib import Path

import pytest

from congress_api.models.content import content_bytes
from congress_api.parsers.committee_pages import parse_event_page, document_groups
from congress_api.parsers.document_links import document_links, http_url

FIXTURES = Path(__file__).parent / 'fixtures/meeting_inventory/house-sites/document-gaps'
SOURCES = json.loads((FIXTURES / 'sources.json').read_text())
PAGE = 'https://example.house.gov/hearings/one'


@pytest.mark.parametrize('source', SOURCES, ids=lambda s: s['sample_id'])
def test_retained_document_omissions_keep_source_context(source):
    body = (FIXTURES / source['file']).read_bytes()
    assert hashlib.sha256(body).hexdigest() == source['sha256']
    page = parse_event_page(body, source['url'])
    documents = {d[2]: d for d in page['documents']}
    assert {d[2] for d in source['baseline_documents']} <= set(documents)
    assert page['event'] == source['baseline_event']
    assert content_bytes(page['raw_html']) == body
    groups = {g['files'][0]['url']: g for g in document_groups(body, source['url'], '/event')}
    for expected in source['expected']:
        target = expected['url']
        assert target in documents
        assert documents[target][:2] == [expected['kind'], expected['label']]
        assert groups[target]['metadata']['attributes']['href'] == expected['literal_href']
        assert any(a.get('href') == expected['literal_href']
                   for o in page['document_metadata'][target]['occurrences'] for a in o['attributes'])


def test_html_url_boundary_spaces_preserve_literal_and_internal_bytes():
    body = b'<a href=" /files/a b.pdf ">Official Transcript</a>'
    link, = document_links(body, PAGE)
    assert link.url == 'https://example.house.gov/files/a b.pdf'
    assert link.attributes['href'] == ' /files/a b.pdf '
    assert http_url('/files/a%20.pdf%20', PAGE).endswith('a%20.pdf%20')


@pytest.mark.parametrize('value', ['https://exa\nmple.gov/a.pdf', 'https://example.gov/\ta.pdf', '\n/file.pdf'])
def test_outer_space_handling_does_not_repair_control_characters(value):
    assert http_url(value, PAGE) is None


def test_table_context_stays_in_its_column_and_preserves_empty_labels():
    body = b'''<h1>Hearing</h1><h2>Witnesses</h2><table>
      <tr><td>Bill Number</td><td>Legislative Report</td><td>Markup Transcript</td></tr>
      <tr><td><a href="/bill">H.R. 1</a></td><td><a href="/report"></a></td><td><a href="/record">Read here</a></td></tr>
      </table><p><a href="/unrelated">Read here</a></p>'''
    page = parse_event_page(body, PAGE)
    assert page['documents'] == [
        ['committee report', '', 'https://example.house.gov/report'],
        ['transcript', 'Read here', 'https://example.house.gov/record']]
    assert page['document_metadata']['https://example.house.gov/record']['occurrences'][0]['headings'] == ['Markup Transcript']


@pytest.mark.parametrize('table', [
    '<tr><td colspan="2">Markup Transcript</td></tr><tr><td><a href="/maybe">Read here</a></td><td>Other</td></tr>',
    '<tr><td>Markup Transcript</td><td>Other</td></tr><tr><td rowspan="2">Earlier</td><td>X</td></tr><tr><td><a href="/maybe">Read here</a></td></tr>',
    '<tr><td><a href="/earlier">Markup Transcript</a></td></tr><tr><td><a href="/maybe">Read here</a></td></tr>',
])
def test_ambiguous_table_layout_does_not_inherit_a_document_type(table):
    page = parse_event_page(('<table>' + table + '</table>').encode(), PAGE)
    assert not any(d[2].endswith('/maybe') for d in page['documents'])


def test_transcript_and_statement_labels_do_not_admit_navigation_or_topic_words():
    body = b'''<nav><a href="/nav">Transcript</a></nav>
      <h1>Transcript policy</h1><p><a href="/article">News about transcript policy</a></p>
      <p><a href="/about">Statement of values</a></p><p><a href="/record">Transcript</a></p>
      <footer><a href="/footer">Opening Statment</a></footer>'''
    assert parse_event_page(body, PAGE)['documents'] == [['transcript', 'Transcript', 'https://example.house.gov/record']]


def test_table_context_does_not_promote_fragment_only_links():
    page = parse_event_page(b'''<table><tr><th>Markup Transcript</th></tr>
      <tr><td><a href="#note">1</a></td></tr></table>''', PAGE)
    assert page['documents'] == []
    assert page['document_metadata'] == {}


@pytest.mark.parametrize('inner', [
    '<section><h2>Witness Biographies</h2><a href="/bio.pdf">Biography</a></section>',
    '<div class="vcard"><a href="/bio.pdf">Biography</a></div>',
    '<h2>Witness Biographies</h2><a href="/bio.pdf">Biography</a>',
])
def test_table_context_respects_closer_section_and_card_boundaries(inner):
    page = parse_event_page(('<table><tr><th>Testimony</th></tr><tr><td>' + inner + '</td></tr></table>').encode(), PAGE)
    assert page['documents'][0][0] == 'witness biography'
    assert page['document_metadata']['https://example.house.gov/bio.pdf']['occurrences'][0]['headings'] != ['Testimony']


def test_metadata_does_not_merge_control_character_href_with_valid_document():
    page = parse_event_page(b'<a href="/a\nb.pdf">Malformed</a><a href="/ab.pdf">Valid</a>', PAGE)
    assert page['documents'] == [['other', 'Valid', 'https://example.house.gov/ab.pdf']]
    detail = page['document_metadata']['https://example.house.gov/ab.pdf']
    assert detail['labels'] == ['Valid']
    assert len(detail['occurrences']) == 1
    assert {'text': 'Malformed', 'attributes': {'href': '/a\nb.pdf'}} in page['page_metadata']['links']


def test_new_audit_printed_hearing_text_keeps_literal_legacy_route():
    source = json.loads((FIXTURES / 'holdout-source.json').read_text())
    body = (FIXTURES / 'veterans-printed-hearing.html').read_bytes()
    assert hashlib.sha256(body).hexdigest() == source['sha256']
    page = parse_event_page(body, source['url'])
    assert ['transcript', 'Printed Hearing Text', source['new_omission']] in page['documents']
    assert content_bytes(page['raw_html']) == body


@pytest.mark.parametrize('label', ['Printed hearing text policy', 'Read about printed hearing text'])
def test_printed_hearing_topic_words_do_not_admit_document(label):
    assert not parse_event_page(f'<a href="/topic">{label}</a>'.encode(), PAGE)['documents']


def test_metadata_preserves_non_ascii_url_whitespace_without_aliasing():
    body = b'<a href="/ab.pdf&#160;">Printed Hearing Text</a><a href="/ab.pdf">Valid</a>'
    page = parse_event_page(body, PAGE)
    assert page['document_metadata']['https://example.house.gov/ab.pdf']['labels'] == ['Valid']
    assert page['document_metadata']['https://example.house.gov/ab.pdf\u00a0']['labels'] == ['Printed Hearing Text']
