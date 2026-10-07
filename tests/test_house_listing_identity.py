"""Retained calendar and event layouts that defeated generic heading/link scans."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from congress_api.acquisition import house_sites
from congress_api.models.content import content_bytes
from congress_api.parsers.committee_discovery import discover, event_url, key, listing_records, task
from congress_api.parsers.committee_pages import event_identity, listing_url, parse_event_page

FIXTURES = Path(__file__).parent / 'fixtures/meeting_inventory/house-sites'


def fixture(name):
    source = next(row for row in json.loads((FIXTURES / 'listing-identity-sources.json').read_text())
                  if row['file'] == name + '.html')
    body = (FIXTURES / source['file']).read_bytes()
    assert hashlib.sha256(body).hexdigest() == source['sha256']
    return body, source['url']


@pytest.mark.parametrize('route', ['calendar/default.aspx', 'Calendar/Schedule.aspx', 'events/default.aspx'])
def test_shared_calendar_routes_are_listings_unless_an_event_id_is_present(route):
    url = 'https://example.house.gov/' + route + '?Congress=113&Page=2'
    assert listing_url(url) and not event_url(url)
    assert event_identity(b'<h1>Child hearing</h1><p>Date: January 1, 2001</p>', url) is None
    assert not listing_url(url + '&EventID=123')
    assert event_url(url + '&EventID=123')


def test_retained_minority_calendar_is_not_an_event():
    body, url = fixture('financialservices-minority-calendar')
    page = parse_event_page(body, url)
    assert page['page_kind'] == 'listing' and page['event'] is None
    assert page['documents'] == []
    assert len(listing_records(body, url)) == 10
    assert content_bytes(page['raw_html']) == body


def test_explicit_empty_calendars_do_not_fingerprint_navigation():
    body, url = fixture('financialservices-empty-calendar')
    assert listing_records(body, url) == []
    saved = {}
    for u in [url, url.replace('Page=3', 'Page=4')]:
        links = discover(body, task(u))
        assert any('/Calendar/Schedule.aspx' in link['url'] for link in links)
        house_sites._check_pagination(saved, task(u), links, source_body=body)
    assert not saved.get('pagination')


def test_unknown_layout_and_navigation_empty_messages_do_not_claim_empty_results():
    url = 'https://example.house.gov/calendar/default.aspx'
    message = b'<span class="errormsg">No events found.</span>'
    assert listing_records(b'<main>Unrecognized layout</main>', url) is None
    assert listing_records(b'<nav>' + message + b'</nav><main>Unknown</main>', url) is None
    assert listing_records(b'<nav>' + message + b'</nav><div>Unknown</div>', url) is None
    assert listing_records(b'<main>' + message + b'</main>', url + '?EventID=123') is None


def test_actual_event_rows_take_precedence_over_empty_state_text():
    body = b'<main><span class="errormsg">No events found.</span><article class="article-item">A real event</article></main>'
    records = listing_records(body, 'https://example.house.gov/calendar/default.aspx')
    assert len(records) == 1 and 'A real event' in records[0]


def test_filter_changes_reset_page_but_keep_other_filters_and_literal_page_links():
    body, url = fixture('financialservices-empty-calendar')
    links = discover(body, task(url))
    choices = [link for link in links if urlsplit(link['url']).path == '/calendar/default.aspx'
               and parse_qs(urlsplit(link['url']).query).get('Congress') == ['119']]
    assert len(choices) == 1
    assert parse_qs(urlsplit(choices[0]['url']).query) == {'EventTypeID': ['311'], 'Congress': ['119']}
    assert choices[0]['discovered_from'] == url


@pytest.mark.parametrize('field', ['Page', 'page', 'Pagenum_RS', 'mt_page', 'MT_PAGE_events'])
def test_filter_reset_also_removes_hidden_pagination(field):
    url = f'https://example.house.gov/events?{field}=9&CategoryID=2'
    body = f'''<a href="?{field}=10&amp;CategoryID=2">Next</a>
        <form><input type="hidden" name="{field}" value="9">
        <input type="hidden" name="Congress" value="118">
        <select name="Congress"><option value="119">119</option></select></form>'''.encode()
    links = discover(body, task(url))
    assert any(link['url'] == f'https://example.house.gov/events?{field}=10&CategoryID=2' for link in links)
    choice, = [link for link in links if parse_qs(urlsplit(link['url']).query).get('Congress') == ['119']]
    assert parse_qs(urlsplit(choice['url']).query) == {'CategoryID': ['2'], 'Congress': ['119']}


def test_wordpress_pagination_still_advances():
    request = task('https://example.house.gov/wp-json/wp/v2/events?page=2&per_page=100', 'wordpress_posts')
    result = discover(b'[]', request, headers={'X-WP-TotalPages': '3'})
    assert parse_qs(urlsplit(result[0]['url']).query)['page'] == ['3']


@pytest.mark.parametrize('name,title,day,documents', [
    ('foreignaffairs-iraq', 'Iraqi Benchmarks: An Objective Assessment', '2007-09-05', 1),
    ('foreignaffairs-arctic', 'Climate Change and the Arctic: New Frontiers of National Security', '2009-03-25', 1),
    ('transportation-water', 'America’s Water Resources Infrastructure: Approaches to Enhanced Project Delivery', '2018-01-18', 0),
    ('veterans-fertility', '“Protecting the Freedom to Build a Family: Fertility Care and IVF Access for Veterans”', '2026-03-17', 0),
])
def test_publisher_subject_headings_win_over_other_headings(name, title, day, documents):
    body, url = fixture(name)
    page = parse_event_page(body, url)
    assert page['event'] is not None
    assert page['event']['title'] == page['title'] == title
    assert page['event']['date'] == day
    assert len(page['documents']) == documents
    assert content_bytes(page['raw_html']) == body


@pytest.mark.parametrize('name', ['intelligence-amendment', 'waysandmeans-default', 'waysandmeans-kidney'])
def test_publication_or_continuation_dates_remain_unqualified(name):
    body, url = fixture(name)
    assert event_identity(body, url) is None


def test_ambiguous_explicit_titles_remain_unknown_even_with_one_generic_main_heading():
    body = b'''<main><h1 class="main_page_title">First subject</h1></main>
        <h1 class="main_page_title">Second subject</h1><p>Date: January 1, 2001</p>'''
    assert event_identity(body, 'https://example.house.gov/events/one') is None


def test_subject_heading_class_tokens_and_navigation_scope():
    body = b'''<nav><h1 class="main_page_title">Navigation</h1></nav>
        <article class="post featured"><header><h1 class="title subject">Actual subject</h1></header></article>
        <h1>Newsletter</h1><p>Date: January 1, 2001</p>'''
    assert event_identity(body, 'https://example.house.gov/events/one')['title'] == 'Actual subject'


def test_reparse_corrects_retained_readings_without_changing_request_evidence():
    saved = dict(pages={}, sources={}, pending=[task('https://example.house.gov/events/next')],
                 done={'old-request': {'outcome': 'complete'}}, errors={'old-request': {'error': 'retained diagnostic'}})
    for name in ['financialservices-minority-calendar', 'foreignaffairs-iraq']:
        body, url = fixture(name)
        page = parse_event_page(body, url)
        page.update(event=None, page_kind='event_candidate', parser_version=4,
                    checked='2026-10-07', retrieved_at='2026-10-07T12:00:00Z')
        saved['pages'][url] = page
        saved['sources'][key(task(url))] = dict(url=url, page_url=url, receipts=[
            dict(status_code=200, sha256=page['raw_html']['sha256'], completed_at=page['retrieved_at'])])
    before = deepcopy(saved)
    assert house_sites.reparse_pages({'example.house.gov': saved}) == dict(reparsed_pages=1, restored_listings=1)
    for field in ['pending', 'done', 'errors']:
        assert saved[field] == before[field]
    for identifier, source in saved['sources'].items():
        assert source['receipts'] == before['sources'][identifier]['receipts']
        old = before['pages'][source['url']]
        if 'page_url' in source:
            page = saved['pages'][source['page_url']]
            for field in ['raw_html', 'documents', 'document_metadata', 'checked', 'retrieved_at']:
                assert page[field] == old[field]
            assert page['event']['date'] == '2007-09-05'
        else:
            assert source['content'] == old['raw_html']
            assert source['url'] not in saved['pages']
