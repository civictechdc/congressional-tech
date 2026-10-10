"""Exposed retained-source and synthetic controls for the shared corrections."""
import gzip
import hashlib
import json
from functools import lru_cache
from pathlib import Path

import pytest

from congress_api.models.content import content_bytes
from congress_api.parsers.committee_pages import parse_event_page

FIXTURES = Path(__file__).parent / 'fixtures/meeting_inventory/house-sites/acceptance-boundaries'
SOURCES = json.loads((FIXTURES / 'manifest.json').read_text())['pages']
PAGE = 'https://example.house.gov/hearings/example'


@lru_cache
def parsed(sample_id):
    source = next(s for s in SOURCES if s['sample_id'] == sample_id)
    packed = (FIXTURES / source['file']).read_bytes()
    assert hashlib.sha256(packed).hexdigest() == source['gzip_sha256']
    body = gzip.decompress(packed)
    assert hashlib.sha256(body).hexdigest() == source['body_sha256']
    page = parse_event_page(body, source['url'])
    assert content_bytes(page['raw_html']) == body
    return page


@pytest.mark.parametrize('source', SOURCES, ids=lambda s: s['sample_id'])
def test_retained_roles_and_navigation_boundaries(source):
    page = parsed(source['sample_id'])
    documents = {d[2]: d for d in page['documents']}
    for expected in source['expected_documents']:
        assert documents.get(expected[2]) == expected
    assert set(source['excluded_targets']).isdisjoint(documents)


@pytest.mark.parametrize('body,href', [
    ('<h2>Witnesses</h2><a href="https://edit-/statement">Opening Statement</a>',
     'https://edit-/statement'),
    ('<a href="https://example.house.gov#record">Transcript</a>',
     'https://example.house.gov#record'),
    ('<p class="hearing-transcript"><a href="https://example.house.gov#record">Record</a></p>',
     'https://example.house.gov#record'),
])
def test_unsafe_designation_cannot_crash_or_create_a_homepage_document(body, href):
    page = parse_event_page(body.encode(), PAGE)
    assert page['documents'] == []
    link, = page['page_metadata']['links']
    assert link['attributes']['href'] == href
    assert link['related_page']['role'] == 'source_document_reference'
    assert 'url' not in link['related_page']


def test_vote_and_registration_clauses_do_not_retype_neighboring_links():
    body = b'''<h2>Legislation</h2><ul><li><a href="/bill.pdf">Bill text</a>
      approved by a recorded vote of 10 ayes and 2 nays (<a href="/vote.pdf">FC-1</a>).
      <ul><li><a href="/amendment.pdf">Committee amendment</a></li></ul></li></ul>
      <p>To <a href="/register">register</a>, <a href="/intake">click here</a>.
      <a href="/testimony.pdf">Witness Statement</a></p>'''
    documents = {d[2].rsplit('/', 1)[-1]: d[0] for d in parse_event_page(body, PAGE)['documents']}
    assert documents['bill.pdf'] == 'legislative text'
    assert documents['vote.pdf'] == 'recorded vote'
    assert documents['amendment.pdf'] != 'recorded vote'
    assert documents['testimony.pdf'] == 'witness statement'
    assert 'intake' not in documents and 'register' not in documents


def test_ordinary_report_topic_does_not_designate_a_document():
    page = parse_event_page(b'<p>Discussion of report <a href="/policy">policy</a>.</p>', PAGE)
    assert page['documents'] == []


def test_corporate_chair_opening_remarks_remain_witness_material():
    body = b'<h2>Witnesses</h2><p><a href="/remarks">Chairman Mary Jones Opening Remarks</a></p>'
    assert parse_event_page(body, PAGE)['documents'] == [
        ['witness statement', 'Chairman Mary Jones Opening Remarks', 'https://example.house.gov/remarks']]


@pytest.mark.parametrize('prompt', ['Read', 'View'])
@pytest.mark.parametrize('href', ['/testimony.pdf', '/testimony'])
def test_generic_opening_statement_prompt_keeps_witness_role(prompt, href):
    body = f'''<h2>Witnesses</h2><p>{prompt} Dr. Jane Smith's opening statement
        <a href="{href}">here</a>.</p>'''
    documents = parse_event_page(body.encode(), PAGE)['documents']
    assert documents == [['witness statement', 'here', 'https://example.house.gov' + href]]


@pytest.mark.parametrize('prompt', ['Read', 'View'])
@pytest.mark.parametrize('href', ['/statement.pdf', '/statement'])
def test_chair_prompt_keeps_bounded_witness_field_priority(prompt, href):
    body = f'''<div class="witness-document"><h2>Witnesses</h2>
        <p>{prompt} Chairman Mary Jones's opening statement <a href="{href}">here</a>.</p></div>'''
    documents = parse_event_page(body.encode(), PAGE)['documents']
    assert documents == [['witness statement', 'here', 'https://example.house.gov' + href]]


@pytest.mark.parametrize('prompt', ['Read', 'View'])
def test_local_chair_prompt_outweighs_inherited_witness_list_heading(prompt):
    body = f'''<p><b>WITNESS LIST:</b><br>
        <a href="/testimony.pdf">Dr. Jane Smith</a>, Research Director<br>
        {prompt} Chairman Thompson's opening statement <a href="/statement">here</a>.</p>'''
    documents = parse_event_page(body.encode(), PAGE)['documents']
    assert ['member statement', 'here', 'https://example.house.gov/statement'] in documents


def participant_card(contents, family='paragraph--witness', name='Mary Jones'):
    if family == 'vcard':
        return f'<li class="vcard"><span class="fn">{name}</span><div class="title">Chairman, Example Corporation</div>{contents}</li>'
    return f'''<div class="paragraph--witness"><div class="witness__field-name">{name}</div>
        <div class="witness__field-position">Chairman, Example Corporation</div>
        <div class="witness__field-testimony">{contents}</div></div>'''


@pytest.mark.parametrize('family', ['paragraph--witness', 'vcard'])
@pytest.mark.parametrize('href', ['/statement.pdf', '/statement'])
@pytest.mark.parametrize('prompt', ['Read', 'View'])
def test_recognized_participant_card_owns_generic_statement_prompt(family, href, prompt):
    body = participant_card(f'<p>{prompt} Chairman Mary Jones\'s opening statement <a href="{href}">here</a>.</p>', family)
    page = parse_event_page(body.encode(), PAGE)
    assert page['documents'] == [['witness statement', 'here', 'https://example.house.gov' + href]]


def test_member_card_and_local_prompt_outside_witness_card_keep_member_role():
    prompt = '<p>View Chairman Mary Jones\'s opening statement <a href="/member">here</a>.</p>'
    body = '<div class="Hearing__additionalContentSection--members">' + participant_card(prompt, 'vcard') + '</div>'
    body += participant_card('<a href="/witness.pdf">Witness statement</a>')
    body += '<p>View Chairman Thompson\'s opening statement <a href="/outside">here</a>.</p>'
    docs = {d[2]: d[0] for d in parse_event_page(body.encode(), PAGE)['documents']}
    assert docs['https://example.house.gov/member'] == docs['https://example.house.gov/outside'] == 'member statement'
    assert docs['https://example.house.gov/witness.pdf'] == 'witness statement'


@pytest.mark.parametrize('label,kind', [('Truth in Testimony', 'truth in testimony'),
                                        ('Witness Biography', 'witness biography'),
                                        ('Representative Jane Smith Opening Statement', 'member statement')])
def test_explicit_source_form_survives_participant_card_context(label, kind):
    body = participant_card(f'<a href="/document.pdf">{label}</a>')
    assert parse_event_page(body.encode(), PAGE)['documents'][0][0] == kind


def test_nested_document_section_blocks_outer_participant_prompt_inference():
    body = participant_card('''<section><h2>Key Documents</h2><p>View Chairman Thompson's opening statement
        <a href="/member">here</a>.</p></section>''')
    assert parse_event_page(body.encode(), PAGE)['documents'][0][0] == 'member statement'


def test_repeated_participant_names_keep_occurrences_without_inventing_association():
    prompt = '<p>View Chairman Mary Jones\'s opening statement <a href="/shared.pdf">here</a>.</p>'
    page = parse_event_page((participant_card(prompt) + participant_card(prompt)).encode(), PAGE)
    assert page['documents'][0][0] == 'witness statement'
    metadata = page['document_metadata']['https://example.house.gov/shared.pdf']
    assert len(metadata['occurrences']) == 2
    assert all(o['witness_indexes'] == [] for o in metadata['occurrences'])
    assert page['witness_metadata'] == {}


def test_one_target_in_member_and_witness_cards_retains_each_role():
    prompt = '<p>View Chairman Mary Jones\'s opening statement <a href="/shared.pdf">here</a>.</p>'
    body = participant_card(prompt) + '<div class="Hearing__additionalContentSection--members">' + participant_card(prompt) + '</div>'
    page = parse_event_page(body.encode(), PAGE)
    occurrences = page['document_metadata']['https://example.house.gov/shared.pdf']['occurrences']
    assert [o['related_page']['document_kind'] for o in occurrences] == ['witness statement', 'member statement']
    assert page['documents'][0][0] == 'other'


OBSERVATIONS = json.loads((FIXTURES / 'observations.json').read_text())['pages']


@pytest.mark.parametrize('sample_id', OBSERVATIONS)
def test_classification_preserves_retained_source_observations(sample_id):
    page = parsed(sample_id)
    expected = OBSERVATIONS[sample_id]
    assert page['witnesses'] == expected['witnesses']
    for target, occurrences in expected['occurrences'].items():
        actual = page['document_metadata'][target]['occurrences']
        assert [{k: v for k, v in o.items() if k != 'related_page'} for o in actual] == occurrences
