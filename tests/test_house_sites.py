"""All-history discovery, resumable collection and shared source fidelity."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from congress_api.acquisition import house_sites
from congress_api.models.content import RawContent, content_bytes
from congress_api.parsers.committee_discovery import discover, event_url, key, task
from congress_api.parsers.committee_pages import parse_event_page
from congress_api.retention.document_index import DocumentSources
from congress_api.retention.tables import read_state, write_state
from test_house_committee_fallback import BODY, CALENDAR, DIRECTORY, HOME, PAGE, ROYSE

TODAY = date(2026, 10, 7)


def client(pages):
    calls = []
    def get(url, receipts, **kwargs):
        calls.append((url, kwargs))
        value = pages.get(url)
        receipt = dict(url=url, completed_at='2026-10-07T06:00:00Z')
        receipts.append(receipt)
        if isinstance(value, Exception):
            receipt.update(outcome='error', error=str(value))
            raise value
        final, body = value if isinstance(value, tuple) else (url, value)
        code = 200 if body is not None else 404
        receipt.update(status_code=code, outcome='retrieved' if code == 200 else 'not_found')
        if body is not None:
            receipt['content'] = RawContent.from_bytes(body, 'text/html').source_dict()
        return SimpleNamespace(url=final, status_code=code, content=body or b'', headers={})
    return get, calls


def fixture_site():
    nodes = json.loads(CALENDAR)['events_connection']['nodes'][:1]
    return {HOME: b'<a href="/events">Events</a>', HOME + 'events': b'<a href="'+PAGE.encode()+b'">Hearing</a>',
            HOME + 'api/events': json.dumps({'events_connection': {'nodes': nodes}}).encode(), PAGE: BODY}


def test_all_history_without_native_meetings_retains_unmatched_pages_and_exact_bodies(tmp_path):
    get, calls = client(fixture_site());state = {}
    result = house_sites.collect(DIRECTORY, state, today=TODAY, get=get)
    assert not result['pending'] and not result['failed'] and result['events'] == 1
    page = state['energycommerce.house.gov']['pages'][PAGE]
    assert content_bytes(page['raw_html']) == BODY
    assert ROYSE in {d[2] for d in page['documents']}
    assert state['energycommerce.house.gov']['coverage']['history'] == 'all discoverable'
    query, = [args['json_body'] for url, args in calls if url.endswith('/api/events')]
    assert 'start' not in query and 'end' not in query
    house_sites.outputs(state, tmp_path)
    assert PAGE in (tmp_path / 'house_site_events.csv').read_text()
    index = DocumentSources(); index.add_house_sites(state)
    context = index.for_url(ROYSE)
    assert context['source_page_url'] == [PAGE]
    assert context['source_publisher_committee_code'] == ['hsif00']
    assert context['source_page_sha256'] == [page['raw_html']['sha256']]
    assert not context.get('source_meeting_id')  # A site observation is not a native match.
    from test_raw_bundle_extraction import extract
    from congress_api.retention.bundles import restore
    record, captures, bodies = extract(state)
    assert restore(record, captures, bodies.__getitem__) == state
    assert BODY in bodies.values()


def test_request_budget_resumes_queue_and_visits_each_site_fairly(tmp_path):
    other = 'https://agriculture.house.gov/'
    directory = DIRECTORY + [{**DIRECTORY[0], 'detail': {'committeeWebsiteUrl': other}}]
    get, calls = client({**fixture_site(), other: b'<a href="/hearings/old">Old</a>',
                         other + 'hearings/old': b'<h1>Old hearing</h1><p>Date: January 1, 2001</p>'})
    state = {};path = tmp_path / 'house-sites.json.gz'
    result = house_sites.collect(directory, state, today=TODAY, get=get, limit=2, checkpoint=lambda s: write_state(path, s))
    assert {u for u, _ in calls} == {HOME, other}
    assert result['pending'] > 0
    state = read_state(path)
    house_sites.collect(directory, state, today=TODAY, get=get)
    assert state['agriculture.house.gov']['pages'][other + 'hearings/old']['event']['date'] == '2001-01-01'
    assert sum(url == HOME for url, _ in calls) == 1
    before = len(calls)
    house_sites.collect(directory, state, today=TODAY, get=get)
    assert len(calls) == before


def test_failures_preserve_usable_page_and_receipts_and_retry_on_later_run():
    get, _ = client(fixture_site());state = {}
    house_sites.collect(DIRECTORY, state, today=TODAY, get=get)
    old = deepcopy(state['energycommerce.house.gov']['pages'][PAGE])
    get, calls = client({**fixture_site(), PAGE: RuntimeError('HTTP 503')})
    result = house_sites.collect(DIRECTORY, state, today=date(2027, 10, 7), get=get)
    site = state['energycommerce.house.gov']
    assert result['failed'] == 1 and site['pages'][PAGE] == old
    assert site['sources'][key(task(PAGE))]['receipts'][0]['error'] == 'HTTP 503'
    assert sum(u == PAGE for u, _ in calls) == 1
    get, _ = client(fixture_site())
    result = house_sites.collect(DIRECTORY, state, today=date(2027, 10, 7), get=get)
    assert not result['failed']


def test_discovery_rejects_files_and_other_sites_and_follows_archive_filters():
    url = 'https://agriculture.house.gov/calendar/list.aspx'
    body = b'''<a href="/calendar/eventsingle.aspx?EventID=20">Hearing</a>
      <a href="/calendar/list.aspx?EventTypeID=20">Hearings</a>
      <a href="https://other.house.gov/events/no">Hearing</a><a href="/events/large.pdf">PDF</a>
      <a href="?Page=2">Next</a><form method="get"><select name="Year"><option value="2001">2001</option></select></form>'''
    links = discover(body, task(url))
    assert sum(t['kind'] == 'event' for t in links) == 1
    assert any('Year=2001' in t['url'] for t in links)
    assert any('Page=2' in t['url'] for t in links)
    assert all('other.house.gov' not in t['url'] and not t['url'].endswith('.pdf') for t in links)


@pytest.mark.parametrize('url', ['https://test.house.gov/calendar/?EventTypeID=1',
    'https://test.house.gov/events/hearings', 'https://test.house.gov/hearings/feed/',
    'https://test.house.gov/about/events/calendar', 'https://test.house.gov/wp-json/wp/v2/event/1'])
def test_listings_and_api_records_are_not_event_pages(url):
    assert not event_url(url)


def test_api_pagination_and_wordpress_types_have_no_date_cutoff():
    body = json.dumps({'events_connection': {'nodes': [{'slug': str(i)} for i in range(20)]}}).encode()
    links = discover(body, task(HOME + 'api/events', 'calendar_api', body={'offset': 0, 'limit': 20}))
    assert links[-1]['body'] == {'offset': 20, 'limit': 20}
    types = json.dumps({'events': {'rest_base': 'tribe_events'}, 'posts': {'rest_base': 'posts'}}).encode()
    links = discover(types, task(HOME + 'wp-json/wp/v2/types', 'wordpress_types'))
    assert len(links) == 1 and '/tribe_events?' in links[0]['url']
    posts = json.dumps([{'link': PAGE}]).encode()
    links = discover(posts, links[0], headers={'X-WP-TotalPages': '3'})
    assert links[0]['url'] == PAGE and 'page=2' in links[-1]['url']


def test_repeated_pagination_fails_explicitly_instead_of_looping():
    saved = {}
    links = [task(PAGE, 'event')]
    house_sites._check_pagination(saved, task(HOME + 'events?page=1'), links)
    with pytest.raises(ValueError, match='repeated'):
        house_sites._check_pagination(saved, task(HOME + 'events?page=2'), links)


def test_root_redirect_and_explicit_official_archive_link_preserve_owner():
    canonical = 'https://newcommittee.house.gov/'
    archive = 'https://archive-committee.house.gov/'
    get, _ = client({HOME: (canonical, b'<a href="'+archive.encode()+b'">Archived Site</a>'),
        canonical + 'api/events': b'{"events_connection":{"nodes":[]}}',
        archive: b'<a href="/hearings/old">Old hearing</a>', archive + 'hearings/old': BODY})
    state = {};result = house_sites.collect(DIRECTORY, state, today=TODAY, get=get)
    assert not result['failed']
    assert archive + 'hearings/old' in state['energycommerce.house.gov']['pages']
    assert state['energycommerce.house.gov']['linked_sites'][canonical] == HOME


def test_external_redirect_and_malformed_calendar_remain_failures():
    get, _ = client({HOME: ('https://unofficial.example/', b'<h1>Fake</h1>')})
    state = {};result = house_sites.collect(DIRECTORY, state, today=TODAY, get=get)
    assert result['failed'] == 1 and not state['energycommerce.house.gov']['pages']
    with pytest.raises(ValueError, match='Unrecognized'):
        discover(b'{"error":"upstream"}', task(HOME + 'api/events', 'calendar_api', body={}))


def test_unrecognized_event_is_retained_without_inventing_a_date():
    body = b'<h1>Event title</h1><time>2020-01-01</time><a href="/one.pdf">Testimony</a>'
    page = parse_event_page(body, HOME + 'events/test')
    assert page['event'] is None and page['documents'][0][2] == HOME + 'one.pdf'


def test_offline_reads_saved_state_without_http(tmp_path, monkeypatch):
    import gzip
    directory = tmp_path / 'committees.jsonl.gz'
    directory.write_bytes(gzip.compress((json.dumps(DIRECTORY[0]) + '\n').encode()))
    write_state(tmp_path / 'house-sites.json.gz', {'energycommerce.house.gov': {'pages': {PAGE: parse_event_page(BODY, PAGE)}}})
    monkeypatch.setattr(house_sites, 'request', lambda *a, **k: pytest.fail('Offline HTTP'))
    assert house_sites.main(directory, tmp_path, tmp_path, offline=True) == {'mode': 'offline'}


@pytest.mark.parametrize('row', json.loads((Path(__file__).parent / 'fixtures/meeting_inventory/house-sites/sources.json').read_text()))
def test_retained_house_layouts_keep_event_dates_and_document_links(row):
    import hashlib
    body = (Path(__file__).parent / 'fixtures/meeting_inventory/house-sites' / row['file']).read_bytes()
    assert hashlib.sha256(body).hexdigest() == row['sha256']
    page = parse_event_page(body, row['url'])
    assert row['date'] is not None
    assert page['event']['date'] == row['date']
    assert len(page['documents']) == row['documents']
    assert content_bytes(page['raw_html']) == body


def test_browser_style_json_body_reaches_shared_transport(monkeypatch):
    from congress_api.acquisition.house import request
    from congress_api.transport import http
    captured = {}
    def get(session, url, **options):
        captured.update(options)
        return SimpleNamespace(status_code=200, content=b'{"events_connection":{"nodes":[]}}')
    monkeypatch.setattr(http, 'get_with_retry', get)
    receipts = []
    request(HOME + 'api/events', False, receipts, json_body={'limit': 20})
    assert captured['method'] == 'POST' and captured['json_content_type'] == 'text/plain;charset=UTF-8'
    assert receipts[0]['request_json'] == {'limit': 20}


def test_event_related_css_is_not_crawled_and_robots_remains_a_seed():
    body = b'<link rel="stylesheet" href="/events/site.css"><a href="/events/site.js">Script</a><a href="/events/one">One</a>'
    assert discover(body, task(HOME)) == [task(HOME + 'events/one', 'event', parent=HOME)]
    get, calls = client({HOME: b'<h1>Home</h1>'})
    house_sites.collect(DIRECTORY, {}, today=TODAY, get=get, limit=3)
    assert HOME + 'robots.txt' in {url for url, _ in calls}


def test_optional_blocked_index_is_visible_as_a_gap_without_losing_other_events():
    from congress_api.transport.http import HttpRequestError
    home = 'https://ethics.house.gov/'
    rows = [{**DIRECTORY[0], 'detail': {'committeeWebsiteUrl': home}}]
    get, _ = client({home: b'<link href="/wp-content/foo.css"><a href="/event/old">Old</a>',
        home + 'wp-json/wp/v2/types': HttpRequestError('Unauthorized index', 401),
        home + 'sitemap.xml': b'<!doctype html><html><title>No sitemap</title></html>',
        home + 'event/old': b'<h1>Old hearing</h1><p>Date: June 1, 2000</p>'})
    state = {}; result = house_sites.collect(rows, state, today=TODAY, get=get)
    assert not result['failed'] and result['events'] == 1 and result['discovery_gaps'] == 2
    assert state['ethics.house.gov']['coverage']['status'] == 'queue_exhausted_with_gaps'


def test_live_collection_rejects_an_empty_directory():
    with pytest.raises(ValueError, match='no House websites'):
        house_sites.collect([], {}, today=TODAY, get=lambda *a: None)


def test_previously_recognized_event_on_generic_route_respects_refresh_budget():
    from collections import deque
    saved = {'home': HOME, 'done': {}, 'pages': {HOME + 'a-legislative-markup':
        {'checked': TODAY.isoformat(), 'version': '', 'parser_version': house_sites.PARSER_VERSION,
         'event': {'date': '2000-01-01'}}}}
    queue = deque()
    house_sites._enqueue(saved, queue, set(), task(HOME + 'a-legislative-markup'), today=TODAY, refresh=[450])
    assert not queue
