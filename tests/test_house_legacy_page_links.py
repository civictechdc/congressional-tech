"""Legacy supporting-page links retain their role without claiming fetched files."""
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from congress_api.models.content import content_bytes
from congress_api.parsers.committee_pages import parse_event_page, document_groups

FIXTURES = Path(__file__).parent / 'fixtures/meeting_inventory/house-sites/legacy-page-links'
SOURCES = json.loads((FIXTURES / 'sources.json').read_text())
PAGE = 'https://example.house.gov/hearings/one'


def expected_kind(url):
    path = urlsplit(url).path
    if path.startswith('/witness-testimony/'):
        return 'witness statement'
    if path.startswith('/submission-for-the-record/') or path in {'/node/52602', '/node/52603', '/node/49264'}:
        return 'support document'
    if path.startswith('/hearing-transcript/') or path == '/node/50092':
        return 'transcript'


@pytest.mark.parametrize('source', SOURCES, ids=lambda s: s['id'])
def test_retained_legacy_links_are_qualified_without_inventing_files(source):
    body = (FIXTURES / source['file']).read_bytes()
    assert hashlib.sha256(body).hexdigest() == source['sha256']
    page = parse_event_page(body, source['url'])
    assert content_bytes(page['raw_html']) == body
    docs = {d[2]: d for d in page['documents']}
    generic = {r['attributes']['href']: r for r in page['page_metadata']['links']}
    for link in source['links']:
        if kind := expected_kind(link['url']):
            assert docs[link['url']][:2] == [kind, link['label']]
            occurrences = page['document_metadata'][link['url']]['occurrences']
            assert any(o['related_page']['document_kind'] == kind and
                       o['related_page']['url'] == link['url'] and
                       any(a.get('href') == link['literal_href'] for a in o['attributes']) for o in occurrences)
            assert any(g['files'][0]['url'] == link['url'] for g in document_groups(body, source['url'], '/event'))
        else:
            assert link['url'] not in docs
            related = generic[link['literal_href']]['related_page']
            assert related['url'] == link['url']
            assert 'document_kind' not in related
            assert related['role'] == ('repository' if link['old_classification'] == 'event_repository' else 'witness_reference')
            assert related['basis']


@pytest.mark.parametrize('href', ['/witness-testimony/someone','/submission-for-the-record/someone','/hearing-transcript/a-hearing','/opening-statement/chair'])
def test_explicit_publisher_routes_are_document_pages(href):
    page = parse_event_page(f'<p><a href="{href}">Literal label</a></p>'.encode(), PAGE)
    assert len(page['documents']) == 1
    assert page['documents'][0][2] == 'https://example.house.gov'+href


@pytest.mark.parametrize('href', ['/witness-testimony','/witness-testimony/','/news/witness-testimony-policy','/node/1','https://example.net/witness-testimony/person','#witness-testimony/person'])
def test_routes_alone_do_not_promote_indexes_generic_nodes_or_unrelated_hosts(href):
    page = parse_event_page(f'<a href="{href}">Literal label</a>'.encode(), PAGE)
    assert not page['documents']


def test_navigation_and_organizations_do_not_become_witness_documents():
    body = b'''<nav><a href="/witness-testimony/nav">Witnesses</a></nav>
      <section><h2>Witnesses</h2><h3>Panel 1</h3><p><a href="/node/7">Ms. Jane Doe</a></p></section>
      <section><h2>Organizations</h2><p><a href="/node/8">Jane Doe Institute</a></p></section>'''
    page = parse_event_page(body, PAGE)
    assert not page['documents']
    links={r['attributes']['href']:r for r in page['page_metadata']['links']}
    assert links['/node/7']['related_page']['role']=='witness_reference'
    assert 'related_page' not in links['/node/8']


def test_repository_scope_stays_literal_and_does_not_create_event_matches():
    body = b'''<a href="https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=123">here</a>
      <a href="https://docs.house.gov/Committee/Calendar/ByDay.aspx?DayID=01022020">here</a>
      <a href="https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=1&EventID=2">here</a>'''
    page=parse_event_page(body,PAGE)
    assert not page['documents'] and page['event'] is None
    refs=[r['related_page'] for r in page['page_metadata']['links']]
    assert refs[0]['event_ids']==['123']
    assert refs[1]['day_ids']==['01022020'] and 'event_ids' not in refs[1]
    assert refs[2]['event_ids']==['1','2']


def test_document_field_takes_precedence_over_distant_section_heading():
    body=b'<h2>Submissions for the Record</h2><p class="hearing-transcript"><a href="/node/5">Hearing title</a></p>'
    assert parse_event_page(body,PAGE)['documents']==[['transcript','Hearing title','https://example.house.gov/node/5']]


@pytest.mark.parametrize('source_id', ['t118', 't141', 't164', 't187'])
def test_retained_webcasts_keep_media_role(source_id):
    source = next(s for s in SOURCES if s['id'] == source_id)
    page = parse_event_page((FIXTURES / source['file']).read_bytes(), source['url'])
    links = [r for r in page['page_metadata']['links'] if r['text'].strip().lower() == 'watch webcast']
    assert links
    for link in links:
        assert link['related_page']['role'] == 'media'
        assert link['related_page']['url'] not in {d[2] for d in page['documents']}


def test_file_biography_below_legacy_route_keeps_its_existing_kind():
    body = b'<a href="/witness-testimony/jane-bio.pdf">Biography</a>'
    assert parse_event_page(body, PAGE)['documents'][0][0] == 'witness biography'


@pytest.mark.parametrize('body', [
    '<aside><a href="/witness-testimony/example">Jane Doe</a></aside>',
    '<div class="evo-hearing__field-evo-witnesses"><section><h3>Organizations</h3><a href="/node/8">An organization</a></section></div>',
    '<div class="evo-hearing__field-evo-witnesses"><section><a href="/node/8">An organization</a></section></div>',
    '<div class="hearing-transcript"><section><h3>Organizations</h3><a href="/node/8">An organization</a></section></div>',
    '<div class="hearing-transcript"><h2>Transcript</h2><div><h3>Related news</h3><a href="/node/news">News</a></div></div>',
    '<h2>Submissions for the Record</h2><a href="/submit">Submit your testimony</a>',
    '<h2>Submissions for the Record</h2><div><a href="/node/8">An organization</a></div>',
    '<div id="statement-for-the-record"><h2>Submissions for the Record</h2><a href="/submit">Submit testimony</a></div>',
    '<div id="statement-for-the-record"><h2>Submissions for the Record</h2><section><h3>Organizations</h3><a href="/node/8">An organization</a></section></div>',
])
def test_unqualified_links_stay_literal_without_inherited_document_or_witness_role(body):
    page = parse_event_page(body.encode(), PAGE)
    assert not page['documents']
    assert all('related_page' not in r for r in page['page_metadata']['links'])


@pytest.mark.parametrize('between', ['', '<p>Unrelated block</p>'])
def test_marked_submission_list_requires_immediate_heading(between):
    body=('<h2 class="migrated-submissions-record">Submissions for the Record</h2>'+between+
          '<div class="item-list"><ul><li><a href="/node/42">An organization</a></li></ul></div>')
    docs=parse_event_page(body.encode(), PAGE)['documents']
    assert docs == ([] if between else [['support document','An organization','https://example.house.gov/node/42']])
