"""Slice 5: GDELT / Media Cloud fixture parsing (C1-C3) and provider overlap."""
import json
from datetime import datetime, timezone

import pytest

from news_lake.adapters import FetchOutcome, GdeltAdapter, MediaCloudAdapter, RssAdapter
from news_lake.contract import check_corpus, validate_shape

FROZEN = datetime(2026, 10, 20, 4, 0, 0, tzinfo=timezone.utc)
WIRE_STORY_URL = 'https://wire.example/stories/shared-story'

GDELT_PAGE = {
    'articles': [
        {'url': WIRE_STORY_URL, 'url_mobile': 'https://m.wire.example/stories/shared-story',
         'title': 'Shared wire story', 'seendate': '20261019T120000Z',
         'domain': 'wire.example', 'language': 'English', 'sourcecountry': 'US'},
        {'url': 'https://daily.example/politics/budget', 'title': 'Budget passes',
         'seendate': '20261019T090000Z', 'domain': 'daily.example'},
        {'url': 'https://daily.example/politics/budget#details', 'seendate': '20261019T100000Z',
         'domain': 'daily.example'},  # fragment duplicate of the budget story
        {'url': 'https://daily.example/politics/notes', 'seendate': '20261019T110000Z',
         'domain': 'daily.example'},  # no title: an item without a fabricated one
    ]
}

MC_PAGE = {
    'stories': [
        {'stories_id': 551, 'url': WIRE_STORY_URL, 'title': 'Shared wire story',
         'publish_date': '2026-10-19 06:30:04', 'media_id': 91, 'language': 'en'},
        {'stories_id': 552, 'url': 'https://daily.example/politics/budget-vote',
         'title': 'Council budget vote', 'publish_date': '2026-10-19', 'media_id': 92},
        {'stories_id': 553, 'url': 'https://daily.example/politics/no-date', 'media_id': 92},
    ],
    'next': 'b2xlc3NfdG9rZW4='
}


def context():
    from news_lake.context import AdapterContext

    counter = iter(f'eeeeeeee-0000-4000-8000-{i:012d}' for i in range(1, 20))
    return AdapterContext(id_source=lambda: next(counter), clock=lambda: FROZEN)


def page_fetch(body, url, **kwargs):
    defaults = dict(status=200, body=json.dumps(body).encode('utf-8'), access='restricted',
                    rights_basis='Synthetic fixture; replace with a reviewed retention policy.',
                    payload_uri='urn:fixture:captures:provider-page', media_type='application/json')
    defaults.update(kwargs)
    return FetchOutcome(url=url, **defaults)


def by_kind(records, kind):
    return [record for record in records if record['kind'] == kind]


def dedupe(records):
    """What the upsert tables do at commit time: first occurrence wins by id."""
    seen, result = set(), []
    for record in records:
        if record['id'] not in seen:
            seen.add(record['id'])
            result.append(record)
    return result


# -- GDELT -----------------------------------------------------------------------


def test_gdelt_page_parses_into_contract_valid_records():
    page = GdeltAdapter(context()).parse_page(
        page_fetch(GDELT_PAGE, 'https://api.gdeltproject.org/api/v2/doc/doc?query=example'),
        window_end='2026-10-20T04:00:00Z')
    for record in page.records:
        validate_shape(record)
    check_corpus(page.records)
    items = by_kind(page.records, 'item')
    assert len(items) == 3  # the fragment variant folds into the budget item
    assert len(by_kind(page.records, 'discovery')) == 3  # ...so it is not a new observation
    assert page.checkpoint_ref.startswith('urn:news-lake:gdelt:')
    assert page.completed_until == '2026-10-20T04:00:00Z'


def test_gdelt_mobile_url_is_an_alias_and_publication_stays_unknown():
    page = GdeltAdapter(context()).parse_page(
        page_fetch(GDELT_PAGE, 'https://api.gdeltproject.org/api/v2/doc/doc'),
        window_end='2026-10-20T04:00:00Z')
    wire = next(i for i in by_kind(page.records, 'item') if 'shared-story' in i['canonical_url'])
    assert 'https://m.wire.example/stories/shared-story' in wire['url_aliases']
    # seendate is GDELT acquisition, never a publication time (C3).
    for discovery in by_kind(page.records, 'discovery'):
        assert 'reported_publication' not in discovery


def test_gdelt_never_fabricates_titles():
    page = GdeltAdapter(context()).parse_page(
        page_fetch(GDELT_PAGE, 'https://api.gdeltproject.org/api/v2/doc/doc'),
        window_end='2026-10-20T04:00:00Z')
    untitled = next(d for d in by_kind(page.records, 'discovery') if '/notes' in d['url'])
    assert 'reported_title' not in untitled


def test_gdelt_malformed_page_raises_and_consumes_nothing():
    broken = {'articles': [{'title': 'no url here'}]}
    with pytest.raises(ValueError):
        GdeltAdapter(context()).parse_page(
            page_fetch(broken, 'https://api.gdeltproject.org/api/v2/doc/doc'),
            window_end='2026-10-20T04:00:00Z')


def test_gdelt_quota_error_is_a_failed_capture_and_advances_nothing():
    page = GdeltAdapter(context()).parse_page(
        FetchOutcome(url='https://api.gdeltproject.org/api/v2/doc/doc', status=429,
                     outcome='failed', error_code='provider_quota_exceeded'),
        window_end='2026-10-20T04:00:00Z')
    assert [record['kind'] for record in page.records] == ['capture']
    capture = page.records[0]
    assert capture['status'] == 'failed'
    assert capture['error_code'] == 'provider_quota_exceeded'
    assert page.checkpoint_ref is None


# -- Media Cloud -------------------------------------------------------------------


def test_mediacloud_page_parses_with_c3_publication_precisions():
    page = MediaCloudAdapter(context()).parse_page(
        page_fetch(MC_PAGE, 'https://api.mediacloud.org/api/v2/stories_public/search'),
        window_end='2026-10-20T04:00:00Z')
    for record in page.records:
        validate_shape(record)
    check_corpus(page.records)
    discoveries = {d.get('external_id'): d for d in by_kind(page.records, 'discovery')}
    assert discoveries['551']['reported_publication'] == {
        'precision': 'instant', 'at': '2026-10-19T06:30:04Z', 'basis': 'provider'}
    assert discoveries['552']['reported_publication'] == {
        'precision': 'day', 'date': '2026-10-19', 'basis': 'provider'}
    assert 'reported_publication' not in discoveries['553']
    assert 'reported_title' not in discoveries['553']  # no fabricated title
    assert page.checkpoint_ref.endswith('b2xlc3NfdG9rZW4=')


def test_mediacloud_unparseable_date_stays_unknown():
    from news_lake.adapters.mediacloud import parse_publish_date

    assert parse_publish_date('yesterday') is None
    assert parse_publish_date('') is None
    assert parse_publish_date('0000-00-00') is None
    assert parse_publish_date('2026-02-30') is None


def test_mediacloud_midnight_naive_datetime_degrades_to_day():
    from news_lake.adapters.mediacloud import parse_publish_date

    assert parse_publish_date('2026-10-19 00:00:00') == {
        'precision': 'day', 'date': '2026-10-19', 'basis': 'provider'}
    assert parse_publish_date('2026-10-19T00:00:00') == {
        'precision': 'day', 'date': '2026-10-19', 'basis': 'provider'}


def test_mediacloud_malformed_story_raises():
    broken = {'stories': [{'stories_id': 1, 'title': 'no url'}]}
    with pytest.raises(ValueError):
        MediaCloudAdapter(context()).parse_page(
            page_fetch(broken, 'https://api.mediacloud.org/api/v2/stories_public/search'),
            window_end='2026-10-20T04:00:00Z')


def test_mediacloud_metadata_only_page_is_capture_evidence_only():
    """C5 regression: a metadata-only fetch has no retained body; parsing it
    must not crash (review finding: AttributeError on body.decode)."""
    page = MediaCloudAdapter(context()).parse_page(
        FetchOutcome(url='https://api.mediacloud.org/api/v2/stories_public/search',
                     status=200, metadata_only=True),
        window_end='2026-10-20T04:00:00Z')
    assert [record['kind'] for record in page.records] == ['capture']
    assert page.records[0]['access'] == 'metadata_only'
    assert page.checkpoint_ref is None


# -- shared outlet-domain normalization ---------------------------------------------


def test_host_and_outlet_domain_normalization():
    from news_lake.adapters.common import outlet_for_domain
    from news_lake.adapters.urls import host_of, outlet_domain
    from news_lake.contract import ContractError

    assert host_of('https://[2001:db8::1]:8443/path') == '2001:db8::1'
    assert host_of('https://Example.COM.:443/path') == 'example.com'
    assert host_of('https://alice:secret@Example.COM/path') == 'example.com'
    for host in ('www.example.com', 'm.example.com', 'mobile.example.com',
                 'amp.example.com', 'news.example.com', 'politics.example.com'):
        assert outlet_domain(host) == 'example.com'
    assert outlet_domain('example.com') == 'example.com'
    for protected in ('news.com.au', 'news.example.co.uk', 'news.gob.mx',
                      'news.go.jp', 'news.gouv.fr', 'news.or.kr',
                      'news.pvt.k12.ma.us', 'www.news.ck'):
        assert outlet_domain(protected) == protected
    for bad_domain in ('2001:db8::1', '::1', '', '.example.com'):
        with pytest.raises(ContractError) as raised:
            outlet_for_domain(bad_domain, '2026-10-20T04:00:00Z')
        assert raised.value.rule == 'invalid_outlet_domain'


def test_subdomain_articles_reconcile_outlets_across_providers():
    url = 'https://news.example.com/politics/subdomain-story'
    feed = b"""<?xml version="1.0"?><rss version="2.0"><channel>
      <title>Example News</title><link>https://www.example.com/</link>
      <item><title>Subdomain story</title><link>https://news.example.com/politics/subdomain-story</link>
      <pubDate>Mon, 19 Oct 2026 12:00:00 GMT</pubDate></item>
    </channel></rss>"""
    rss = RssAdapter(context()).ingest(FetchOutcome(
        url='https://www.example.com/feed.xml', status=200, body=feed, access='restricted',
        rights_basis='Synthetic fixture; replace with a reviewed retention policy.',
        payload_uri='urn:fixture:captures:subdomain-feed', media_type='application/rss+xml'))
    gdelt_page = GdeltAdapter(context()).parse_page(
        page_fetch({'articles': [{'url': url, 'title': 'Subdomain story',
                                  'seendate': '20261019T120000Z'}]},
                   'https://api.gdeltproject.org/api/v2/doc/doc'),
        window_end='2026-10-20T04:00:00Z')
    mc_page = MediaCloudAdapter(context()).parse_page(
        page_fetch({'stories': [{'stories_id': 701, 'url': url, 'title': 'Subdomain story',
                                 'publish_date': '2026-10-19'}]},
                   'https://api.mediacloud.org/api/v2/stories_public/search'),
        window_end='2026-10-20T04:00:00Z')
    items = [
        next(i for i in by_kind(records, 'item') if 'subdomain-story' in i['canonical_url'])
        for records in (rss, gdelt_page.records, mc_page.records)
    ]
    outlets = [by_kind(records, 'outlet')[0] for records in (rss, gdelt_page.records, mc_page.records)]
    assert [outlet['domains'] for outlet in outlets] == [['example.com']] * 3
    assert len({item['id'] for item in items}) == 1


# -- provider overlap dedups at the item level (P1) ---------------------------------


def test_overlap_across_providers_shares_items_not_discoveries():
    gdelt_page = GdeltAdapter(context()).parse_page(
        page_fetch(GDELT_PAGE, 'https://api.gdeltproject.org/api/v2/doc/doc'),
        window_end='2026-10-20T04:00:00Z', capture_id='eeeeeeee-0000-4000-8000-000000009d01')
    mc_page = MediaCloudAdapter(context()).parse_page(
        page_fetch(MC_PAGE, 'https://api.mediacloud.org/api/v2/stories_public/search'),
        window_end='2026-10-20T04:00:00Z', capture_id='eeeeeeee-0000-4000-8000-000000009c01')
    wire_gdelt = next(i for i in by_kind(gdelt_page.records, 'item') if 'shared-story' in i['canonical_url'])
    wire_mc = next(i for i in by_kind(mc_page.records, 'item') if 'shared-story' in i['canonical_url'])
    assert wire_gdelt['id'] == wire_mc['id']  # one logical item
    gdelt_discovery = next(d for d in by_kind(gdelt_page.records, 'discovery') if 'shared-story' in d['url'])
    mc_discovery = next(d for d in by_kind(mc_page.records, 'discovery') if 'shared-story' in d['url'])
    assert gdelt_discovery['id'] != mc_discovery['id']  # two observations (C2)
    check_corpus(dedupe(gdelt_page.records + mc_page.records))


def test_rss_and_gdelt_overlap_shares_the_item():
    from pathlib import Path

    wire_feed = (Path(__file__).parent / 'fixtures' / 'wire_feed.xml').read_bytes()
    rss = RssAdapter(context()).ingest(FetchOutcome(
        url='https://wire.example/feed.xml', status=200, body=wire_feed, access='restricted',
        rights_basis='Synthetic fixture; replace with a reviewed retention policy.',
        payload_uri='urn:fixture:captures:wire-feed', media_type='application/rss+xml'))
    gdelt_page = GdeltAdapter(context()).parse_page(
        page_fetch(GDELT_PAGE, 'https://api.gdeltproject.org/api/v2/doc/doc'),
        window_end='2026-10-20T04:00:00Z')
    rss_item = next(i for i in by_kind(rss, 'item') if 'shared-story' in i['canonical_url'])
    gdelt_item = next(i for i in by_kind(gdelt_page.records, 'item') if 'shared-story' in i['canonical_url'])
    assert rss_item['id'] == gdelt_item['id']
    check_corpus(dedupe(rss + gdelt_page.records))
