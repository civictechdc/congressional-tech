"""Regressions established by rendered publisher pages, not parser snapshots."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from congress_api.acquisition import house_sites
from congress_api.models.content import content_bytes
from congress_api.parsers.committee_pages import parse_event_page, document_groups, event_identity
from congress_api.parsers.committee_discovery import key, task
from congress_api.parsers.document_links import document_links
from test_house_committee_fallback import BODY, PAGE, ROYSE

FIXTURES = Path(__file__).parent / 'fixtures/meeting_inventory/house-sites'


def fixture(name):
    source = next(row for row in json.loads((FIXTURES / 'visual-sources.json').read_text()) if row['file'] == name + '.html')
    body = (FIXTURES / source['file']).read_bytes()
    assert hashlib.sha256(body).hexdigest() == source['sha256']
    return body, source['url']


def test_next_event_keeps_memo_and_each_named_witness():
    page = parse_event_page(BODY, PAGE)
    assert len(page['documents']) == 10
    memo, = [link for link in document_links(BODY, PAGE) if 'Memorandum_c5b0' in link.url]
    assert memo.source_selector == '__NEXT_DATA__/props/pageProps/event/links/1'
    assert memo.text == 'Hearing Memo'
    assert [w['name'] for w in page['witnesses']] == ['Todd Brinton', 'Stephen Ezell', 'Roger Royse', 'Diana Zuckerman', 'David Lipschutz']
    occurrence, = page['document_metadata'][ROYSE]['occurrences']
    assert occurrence['witness_indexes'] == [2]
    assert occurrence['witness_card']['text'] == 'Roger Royse, Patient Advocate and partner, Haynes and Boone, LLP'
    assert content_bytes(page['raw_html']) == BODY


def test_agriculture_keeps_html_opening_statement_and_five_witness_links():
    body, url = fixture('agriculture-cftc')
    page = parse_event_page(body, url)
    assert page['event']['date'] == '2025-12-11'
    assert len(page['documents']) == 7  # 5 testimonies, opening statement, transcript.
    opening, = [d for d in page['documents'] if 'DocumentID=8045' in d[2]]
    assert opening[0] == 'member statement'
    assert len(page['witnesses']) == 5
    for index, name in enumerate(['Stump', 'Prosser', 'Crighton', 'Schwartz', 'Schiffrin']):
        doc, = [d for d in page['documents'] if name in d[2]]
        assert page['document_metadata'][doc[2]]['witness_indexes'] == [index]
    assert any(g['files'][0]['url'] == opening[2] for g in document_groups(body, url, '/event'))


def test_science_uses_displayed_date_and_subject_and_html_statements():
    body, url = fixture('science-biotech')
    page = parse_event_page(body, url)
    assert page['event']['date'] == '2026-09-16'
    assert page['title'].endswith('Securing U.S. Leadership in a Global Race')
    assert 'Republicans' not in page['title']
    assert len(page['documents']) == 5
    assert [d[0] for d in page['documents']].count('member statement') == 2
    assert len(page['witnesses']) == 3
    # The same generic post template on a news route is not an event date.
    assert event_identity(body, 'https://science.house.gov/news/example') is None


def test_judiciary_excludes_feed_and_preserves_three_witness_associations():
    body, url = fixture('judiciary-sanctuary')
    page = parse_event_page(body, url)
    assert page['event']['date'] == '2026-09-15'
    assert len(page['documents']) == 3
    assert [p['name'] for p in page['witnesses']] == ['Elizabeth Carter', 'Anatoly Varfolomeev', 'Frederick Akshar II']
    assert all('rss.xml' not in d[2] for d in page['documents'])


def test_listing_child_date_does_not_create_an_event_or_document_group():
    body, url = fixture('judiciary-listing')
    page = parse_event_page(body, url)
    assert page['event'] is None and page['page_kind'] == 'listing'
    assert page['documents'] == [] and list(document_groups(body, url, '/listing')) == []


def test_html_statement_context_does_not_cross_navigation_or_witness_boundaries():
    body = b'''<nav><a href="/opening-statement">Opening Statement</a></nav>
    <main><h1>Sample hearing</h1><p>Date: January 1, 2000</p>
      <h2>Opening Statements</h2><p><a href="/statement">Chair</a></p>
      <h2>Witnesses</h2><p>Jane Smith, Scientist, Lab</p><p><a href="/jane.pdf">Testimony</a></p>
      <p>Unrelated explanatory text</p><p><a href="/unowned.pdf">Testimony</a></p>
      <h2>Resources</h2><p><a href="/unrelated">External organization</a></p></main>
    <footer><a href="/foot.pdf">Opening Statement</a><a href="/rss.xml">RSS</a></footer>'''
    page = parse_event_page(body, 'https://test.house.gov/events/one')
    assert {d[2] for d in page['documents']} == {'https://test.house.gov/statement', 'https://test.house.gov/jane.pdf', 'https://test.house.gov/unowned.pdf'}
    assert page['document_metadata']['https://test.house.gov/jane.pdf']['witness_indexes'] == [0]
    assert page['document_metadata']['https://test.house.gov/unowned.pdf']['witness_indexes'] == []


def test_shared_url_occurrences_keep_their_own_witnesses():
    body = b'''<h1>Hearing</h1><h2>Witnesses</h2>
      <p>Jane Smith, Scientist, Lab</p><p><a href="/joint.pdf">Testimony</a></p>
      <p>John Jones, Engineer, Institute</p><p><a href="/joint.pdf">Testimony</a></p>'''
    page = parse_event_page(body, 'https://test.house.gov/events/one')
    detail = page['document_metadata']['https://test.house.gov/joint.pdf']
    assert [o['witness_indexes'] for o in detail['occurrences']] == [[0], [1]]
    assert len(page['documents']) == 1


def test_reparse_preserves_original_bodies_receipts_timestamps_and_queue():
    body, url = fixture('judiciary-listing')
    source = parse_event_page(body, url)
    source.update(checked='2026-10-06', retrieved_at='2026-10-06T12:00:00Z', parser_version=1)
    event = parse_event_page(BODY, PAGE)
    event.update(checked='2026-10-06', retrieved_at='2026-10-06T12:00:00Z', parser_version=1, documents=[])
    state = {'test.house.gov': {'pages': {url: source, PAGE: event}, 'sources': {
        key(task(url)): {'url': url, 'kind': 'html', 'page_url': url, 'receipts': [{'sha256': source['raw_html']['sha256'], 'status_code': 200}]}},
        'pending': [task('https://test.house.gov/events/next')], 'done': {}, 'errors': {}}}
    before = deepcopy(state)
    assert house_sites.reparse_pages(state) == {'reparsed_pages': 1, 'restored_listings': 1}
    saved = state['test.house.gov']
    assert url not in saved['pages']
    assert saved['sources'][key(task(url))]['content'] == source['raw_html']
    assert saved['sources'][key(task(url))]['receipts'] == before['test.house.gov']['sources'][key(task(url))]['receipts']
    assert saved['pages'][PAGE]['raw_html'] == event['raw_html']
    assert saved['pages'][PAGE]['retrieved_at'] == event['retrieved_at']
    assert saved['pages'][PAGE]['checked'] == event['checked']
    assert len(saved['pages'][PAGE]['documents']) == 10
    for key_ in ['pending', 'done', 'errors']:
        assert saved[key_] == before['test.house.gov'][key_]
