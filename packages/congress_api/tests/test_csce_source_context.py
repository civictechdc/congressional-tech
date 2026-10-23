"""Retained CSCE pages supply file roles, witness ownership, and event dates."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from congress_api.parsers.senate import parsed
from congress_api.parsers.senate_page import document_context, event_details
from congress_api.retention.document_index import DocumentSources, fill_document_kind

FIXTURES = Path(__file__).parent / 'fixtures/meeting_inventory/csce'
CASES = json.loads((FIXTURES / 'cases.json').read_text())


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['file'])
def test_retained_csce_event_date_reaches_document_index(case):
    raw = (FIXTURES / case['file']).read_bytes()
    assert sha256(raw).hexdigest() == case['sha256']
    page = parsed(raw.decode(), case['url'])
    assert page['event']['date'] == case['date']
    assert page['event']['type'] == 'Meeting'  # The template also contains briefings.
    context = DocumentSources()
    context.add_senate({'www.csce.gov': {'pages': {case['url']: page}}})
    for document in case['documents']:
        row = context.for_url(document['url'])
        assert row['source_page_date'] == [case['date']]
        assert row['source_publisher_committee_code'] == ['jcse00']


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['file'])
def test_retained_csce_document_roles_and_owners_reach_document_index(case):
    page = parsed((FIXTURES / case['file']).read_text(), case['url'])
    context = DocumentSources()
    context.add_senate({'csce.gov': {'pages': {case['url']: page}}})
    documents = {url: kind for kind, _, url in page['documents']}
    kinds = {'witness statement': ['witness-statement'], 'witness biography': ['witness-biography'], 'other': None}
    for document in case['documents']:
        assert documents[document['url']] == document['kind']
        row = context.for_url(document['url'])
        fill_document_kind(row)
        assert row.get('document_kind') == kinds[document['kind']]
        assert row.get('source_witness_name', []) == document['witnesses']
        if document['kind'] == 'witness statement':
            assert row['source_document_type_basis'] == ['publisher_witness_field']
        elif document['kind'] == 'witness biography':
            assert row['source_document_type_basis'] == ['publisher_link_label']
        else:
            assert row['source_link_heading'] == ['Related Information']


def test_exact_retained_body_repairs_legacy_context_without_mutating_saved_page():
    case = CASES[0]
    raw = (FIXTURES / case['file']).read_bytes()
    page = parsed(raw.decode(), case['url'])
    page.pop('event', None)
    page['document_metadata'] = {}
    page['documents'] = [['other', label, url] for _, label, url in page['documents']]
    original = deepcopy(page)
    context = DocumentSources()
    def read_body(key):
        assert key == f"bodies/sha256/{case['sha256'][:2]}/{case['sha256']}.gz"
        return raw
    context.add_senate({'csce.gov': {'pages': {case['url']: page}}}, read_body=read_body)
    assert page == original
    row = context.for_url(case['documents'][0]['url'])
    fill_document_kind(row)
    assert row['document_kind'] == ['witness-statement']
    assert row['source_page_date'] == [case['date']]
    assert row['source_page_sha256'] == [case['sha256']]


def test_external_report_retains_the_publishers_surrounding_paragraph():
    case = next(c for c in CASES if c['file'] == 'responding-to-hate-crimes.html')
    page = parsed((FIXTURES / case['file']).read_text(), case['url'])
    url = 'https://fra.europa.eu/sites/default/files/fra_uploads/fra-2019-young-jewish-europeans_en.pdf'
    context = DocumentSources()
    context.add_senate({'csce.gov': {'pages': {case['url']: page}}})
    row = context.for_url(url)
    assert row['source_link_context'] == [
        "Alina Bricman's video testimony concluded the hearing. She presented an overview of the first-ever report of "
        'Young Jewish Europeans: perceptions and experiences of antisemitism, released July 4, 2019.']
    assert row['source_link_label'] == ['Young Jewish Europeans: perceptions and experiences of antisemitism']
    assert not row.get('source_witness_name')  # Prose mention is not a witness-file card.
    fill_document_kind(row)
    assert row['document_kind'] is None


@pytest.mark.parametrize('url,dates', [
    ('https://example.org/hearings/example', ['October 3, 2017']),
    ('https://www.csce.gov/news/example', ['October 3, 2017']),
    ('https://www.csce.gov/hearings/example', []),
    ('https://www.csce.gov/hearings/example', ['October 3, 2017', 'October 4, 2017']),
])
def test_csce_event_requires_one_explicit_date_on_its_own_hearing_page(url, dates):
    raw = '<h1>Event</h1><p>Published October 1, 2017</p>' + ''.join(
        f'<div class="csce-hearing__field-hearing-date">{date}</div>' for date in dates)
    assert event_details(raw, url) is None


@pytest.mark.parametrize('markup,kind', [
    ('<div class="witness__field-testimony"><a href="/opaque.pdf" title="transcript of opaque.pdf"></a></div>', 'witness statement'),
    ('<div class="witness__field-testimony"></div><a href="/opaque.pdf"></a>', 'other'),
    ('<a href="/opaque.pdf" class="transcript-link" title="transcript of opaque.pdf"></a>', 'other'),
    ('<a href="/opaque.pdf">Witness Biographies</a>', 'witness biography'),
    ('<a href="/opaque.pdf">Biographies of authoritarian regimes</a>', 'other'),
])
def test_publisher_fields_do_not_leak_to_adjacent_links_or_generic_icon_attributes(markup, kind):
    raw = '<div class="paragraph--witness"><div class="witness__field-name">Alex Smith</div>' + markup + '</div>'
    page = parsed(raw, 'https://www.csce.gov/hearings/example')
    assert page['documents'][0][0] == kind


def test_repeated_file_keeps_conflicting_roles_on_their_original_links():
    url = 'https://www.csce.gov/hearings/example'
    page = parsed('<div class="paragraph--witness"><div class="witness__field-name">Alex Smith</div>'
                  '<div class="witness__field-testimony"><a href="/shared.pdf"></a></div></div>'
                  '<p><a href="/shared.pdf">Panelist Biographies</a></p>', url)
    metadata = page['document_metadata']['https://www.csce.gov/shared.pdf']
    original = deepcopy(metadata)
    assert document_context(metadata) == (None, None)
    assert document_context({**metadata, 'occurrences': list(reversed(metadata['occurrences']))}) == (None, None)
    assert metadata == original
    assert page['documents'][0][0] == 'other'
    context = DocumentSources()
    context.add_senate({'csce.gov': {'pages': {url: page}}})
    row = context.for_url('https://www.csce.gov/shared.pdf')
    claims = {tuple(o['source_document_type']): o for o in row['source_occurrences']}
    assert claims[('witness statement',)]['source_witness_name'] == ['Alex Smith']
    assert not claims[('witness biography',)].get('source_witness_name')
    assert claims[('witness biography',)]['source_link_label'] == ['Panelist Biographies']
