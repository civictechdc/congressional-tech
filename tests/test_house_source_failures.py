"""Publisher failure regressions with preserved literal links and receipts."""
from copy import deepcopy
from html import escape
import hashlib
import json
from pathlib import Path

import pytest

from congress_api.acquisition import house_sites
from congress_api.models.content import content_bytes
from congress_api.parsers.committee_discovery import discover, key, task
from congress_api.parsers.document_links import document_links, download_query_fallback
from test_house_sites import client, DIRECTORY, HOME, TODAY

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/meeting_inventory/house-sites/source-failures.json').read_text())


@pytest.mark.parametrize('row', FIXTURE['downloads'])
def test_probed_downloads_are_documents_not_event_requests(row):
    parent = 'https://democrats-transportation.house.gov/committee-activity/'
    body = f'<a href="{escape(row["original_url"])}">Hearing testimony</a>'.encode()
    assert not discover(body, task(parent))
    link, = document_links(body, parent)
    assert link.url == row['original_url']
    assert download_query_fallback(link.url, 410).url == row['url']


@pytest.mark.parametrize('row', FIXTURE['links'])
def test_publisher_malformed_hrefs_are_not_invented_event_pages(row):
    match, = row['literal_matches']
    body = f'<a href="{escape(match["literal_href"], quote=True)}">{escape(match["text"])}</a>'.encode()
    links = discover(body, task(row['parent']))
    assert (row['failure'] in {x['url'] for x in links}) is not row['reject_from_discovery']


@pytest.mark.parametrize('href', ['/hearings/a%20valid%20title', './bit.ly/hearings/one',
    'section.test/hearings/one', '/hearings/section.v2/one', '/hearings/value%3C3',
    '/hearings/one?return=https://example.org',
    '/hearings/one?label=%3Ciframe%3E', '/hearings/one?to=/download/file'])
def test_valid_relative_paths_and_query_values_stay_admitted(href):
    links = discover(f'<a href="{escape(href)}">Hearing</a>'.encode(), task(HOME+'hearings/'))
    assert len(links) == 1


@pytest.mark.parametrize('row', FIXTURE['sitemaps'])
def test_plain_text_sitemaps_are_retained_discovery_gaps(row):
    assert hashlib.sha256(row['body'].encode()).hexdigest() == row['sha256']
    item = task(row['url'], 'sitemap');identifier = key(item)
    failure = dict(request=item, error='Unrecognized sitemap response', checked_at='2026-10-06')
    previous = dict(url=row['url'], status_code=200, sha256=row['sha256'], completed_at='2026-10-06')
    saved = dict(pages={}, done={}, pending=[item], errors={identifier: failure},
                 sources={identifier: dict(url=row['url'], receipts=[previous])})
    host = row['url'].split('/')[2]
    directory = [{**DIRECTORY[0], 'detail': {'committeeWebsiteUrl': 'https://'+host+'/'}}]
    get, calls = client({row['url']: row['body'].encode()})
    result = house_sites.collect(directory, {host:saved}, today=TODAY, get=get, limit=1)
    assert result['failed'] == 0 and result['discovery_gaps'] == 1
    observation = saved['sources'][identifier]
    assert observation['discovery_gap'] == 'sitemap_unrecognized'
    assert content_bytes(observation['content']) == row['body'].encode()
    assert observation['receipts'][0] == previous and len(observation['receipts']) == 2
    assert saved['resolved_errors'][identifier][0]['failure'] == failure
    assert len(calls) == 1 and not saved['pages'] and not saved['pending']


@pytest.mark.parametrize('url,outcome', [
    (HOME+'download/testimony', 'document_link'),
    (HOME+'?a=Files.Serve&File_id=abc', 'document_link'),
    (HOME+'hearings/%3Ciframe%20width=', 'malformed_link'),
    (HOME+'hearings/%20https:/example.house.gov/file', 'malformed_link'),
])
def test_old_pending_requests_are_revalidated_without_losing_receipts(url, outcome):
    item = task(url, 'event');identifier = key(item)
    failure = dict(request=item, checked_at='2026-10-06', error='old error')
    saved = dict(pages={}, done={}, pending=[item], errors={identifier: failure},
                 sources={identifier: dict(url=url, receipts=[{'error':'old error'}])})
    before = deepcopy(saved)
    def no_fetch(*a, **kw):
        pytest.fail('Excluded pending request reached HTTP')
    result = house_sites.collect(DIRECTORY, {'energycommerce.house.gov':saved}, today=TODAY, get=no_fetch)
    assert result['requests'] == result['failed'] == result['pending'] == 0
    assert saved['sources'] == before['sources'] and saved['pages'] == before['pages']
    assert saved['done'][identifier]['outcome'] == 'excluded_'+outcome
    assert saved['resolved_errors'][identifier][0]['failure'] == failure


def test_files_from_sitemaps_and_api_records_never_reach_fetch():
    urls = [HOME+'download/hearing', HOME+'?a=Files.Serve&File_id=abc']
    body = ('<urlset>'+''.join('<url><loc>'+escape(u)+'</loc></url>' for u in urls)+'</urlset>').encode()
    get, calls = client({HOME:b'<h1>Home</h1>', HOME+'sitemap.xml':body,
        HOME+'api/events': b'{"events_connection":{"nodes":[]}}'})
    state = {};house_sites.collect(DIRECTORY,state,today=TODAY,get=get)
    assert not set(urls) & {url for url,_ in calls}
    assert not state['energycommerce.house.gov']['pages']


def test_malformed_calendar_is_still_a_failure():
    item = task(HOME+'api/events','calendar_api',body={'offset':0,'limit':20})
    saved = dict(pages={}, sources={}, done={}, pending=[item], errors={})
    get,_ = client({item['url']:b'{"error":"CMS failed"}'})
    result = house_sites.collect(DIRECTORY,{'energycommerce.house.gov':saved},today=TODAY,get=get)
    assert result['failed'] == 1 and result['discovery_gaps'] == 0


def test_retrying_old_document_failures_preserves_history_without_requesting_them():
    failures = {key(task(url)):dict(request=task(url), error='HTTP 410') for url in
        [HOME+'download/one', HOME+'download/two']}
    saved = dict(pages={}, sources={}, done={}, pending=[], errors=deepcopy(failures))
    house_sites.collect(DIRECTORY, {'energycommerce.house.gov':saved}, today=TODAY,
                        get=lambda *a, **kw: pytest.fail('No HTTP budget'), limit=0)
    assert not saved['errors']
    assert {k:v[0]['failure'] for k,v in saved['resolved_errors'].items()} == failures
    assert all(item['url'] not in {f['request']['url'] for f in failures.values()} for item in saved['pending'])


def test_unexpected_parser_value_error_is_not_downgraded_to_a_gap(monkeypatch):
    def broken(*a, **kw):
        raise ValueError('unexpected parser bug')
    monkeypatch.setattr(house_sites, 'discover', broken)
    item=task(HOME+'sitemap.xml','sitemap')
    saved=dict(pages={}, sources={}, done={}, pending=[item], errors={})
    get,_=client({item['url']:b'<urlset/>'})
    result=house_sites.collect(DIRECTORY,{'energycommerce.house.gov':saved},today=TODAY,get=get)
    assert result['failed'] == 1 and result['discovery_gaps'] == 0
    assert 'unexpected parser bug' in saved['errors'][key(item)]['error']
