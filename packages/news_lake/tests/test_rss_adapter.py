"""Slice 3 exit gate: the RSS adapter over fixture feed bytes (C1-C5)."""
import copy
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest

from news_lake.adapters import FetchOutcome, RssAdapter, publication_from_feed
from news_lake.contract import check_corpus, validate_shape
from news_lake.context import AdapterContext
from news_lake.storage.releases import publish_release, read_release

FIXTURES = Path(__file__).parent / 'fixtures'
FEED = (FIXTURES / 'example_feed.xml').read_bytes()
FROZEN = datetime(2026, 10, 20, 4, 0, 0, tzinfo=timezone.utc)


def frozen_context(ids):
    counter = iter(ids)
    return AdapterContext(id_source=lambda: next(counter), clock=lambda: FROZEN)


def feed_fetch(body=FEED, **kwargs):
    defaults = dict(
        url='https://example.com/feed.xml',
        status=200,
        body=body,
        access='restricted',
        rights_basis='Synthetic fixture; replace with a reviewed retention policy.',
        payload_uri='urn:fixture:captures:example-feed-1',
        media_type='application/rss+xml',
    )
    defaults.update(kwargs)
    return FetchOutcome(**defaults)


def ingest(fetch, context=None, **kwargs):
    adapter = RssAdapter(context if context is not None else frozen_context(
        ['eeeeeeee-0000-4000-8000-000000000001']))
    return adapter.ingest(fetch, **kwargs)


def by_kind(records, kind):
    return [record for record in records if record['kind'] == kind]


def item_where(records, fragment):
    return next(i for i in by_kind(records, 'item') if fragment in i['canonical_url'])


def version_where(records, fragment):
    item = item_where(records, fragment)
    return next(v for v in by_kind(records, 'version') if v['item_id'] == item['id'])


# -- basic pipeline -----------------------------------------------------------


def test_fixture_feed_produces_contract_valid_records():
    records = ingest(feed_fetch())
    kinds = {record['kind'] for record in records}
    assert {'outlet', 'capture', 'discovery', 'item', 'version', 'run'} <= kinds
    for record in records:
        validate_shape(record)
    check_corpus(records)


def test_outlet_derived_from_feed_domain():
    records = ingest(feed_fetch())
    outlet = by_kind(records, 'outlet')[0]
    assert outlet['domains'] == ['example.com']
    assert outlet['name'] == 'Example News'
    assert outlet['feed_urls'] == ['https://example.com/feed.xml']


def test_outlet_falls_back_to_fetch_host_for_relative_feed_link():
    feed = b"""<?xml version="1.0"?><rss version="2.0"><channel>
      <title>Relative Link News</title><link>/</link>
      <item><title>Story</title><link>https://news.example.com/politics/story</link></item>
    </channel></rss>"""
    records = ingest(feed_fetch(feed, url='https://www.example.com/feed.xml'))
    outlet = by_kind(records, 'outlet')[0]
    assert outlet['domains'] == ['example.com']


def test_capture_records_the_fetch_and_payload():
    records = ingest(feed_fetch())
    capture = by_kind(records, 'capture')[0]
    assert capture['status'] == 'succeeded'
    assert capture['provider'] == 'rss'
    assert capture['http_status'] == 200
    assert capture['payload_hash'] == sha256(FEED).hexdigest()
    assert capture['access'] == 'restricted'
    assert capture['rights_basis']


def test_duplicate_urls_within_a_feed_yield_one_item():
    records = ingest(feed_fetch())
    items = by_kind(records, 'item')
    assert len(items) == 4  # doe-votes, roe-speaks, untitled, committee
    assert len(items) == len({item['id'] for item in items})
    assert {item['canonical_url'] for item in items} == {
        'https://example.com/politics/doe-votes',
        'https://example.com/politics/roe-speaks',
        'https://example.com/politics/untitled',
        'https://example.com/politics/committee',
    }
    # Five feed entries, but the duplicate-URL entry reuses the first
    # observation's discovery identity (same capture + same url).
    assert len(by_kind(records, 'discovery')) == 4


def test_redirect_evidence_merges_publisher_urls_into_aliases():
    records = ingest(feed_fetch())
    doe = item_where(records, 'doe-votes')
    assert 'https://www.example.com/politics/doe-votes' in doe['url_aliases']


def test_later_entry_matching_an_earlier_redirect_url_folds_and_backfills():
    feed = b"""<?xml version="1.0"?><rss version="2.0"><channel>
      <title>Example News</title><link>https://www.example.com/</link>
      <item>
        <link>https://example.com/politics/redirect-story</link>
        <guid isPermaLink="true">https://www.example.com/politics/redirect-story</guid>
      </item>
      <item>
        <title>Redirect story</title>
        <link>https://www.example.com/politics/redirect-story</link>
        <pubDate>Mon, 19 Oct 2026 12:00:00 GMT</pubDate>
        <description>&lt;p&gt;Story body.&lt;/p&gt;</description>
      </item>
    </channel></rss>"""
    records = ingest(feed_fetch(feed))
    items = by_kind(records, 'item')
    assert len(items) == 1
    item = items[0]
    assert item['canonical_url'] == 'https://example.com/politics/redirect-story'
    assert 'https://www.example.com/politics/redirect-story' in item['url_aliases']
    versions = by_kind(records, 'version')
    assert len(versions) == 1
    assert versions[0]['item_id'] == item['id']
    assert versions[0]['title'] == 'Redirect story'  # backfilled from the later entry
    assert versions[0]['publication'] == {
        'precision': 'instant', 'at': '2026-10-19T12:00:00Z', 'basis': 'publisher'}
    assert versions[0]['text'] == 'Story body.'


def test_fragment_stripped_from_canonical_original_preserved_in_aliases():
    records = ingest(feed_fetch())
    committee = item_where(records, 'committee')
    assert committee['canonical_url'] == 'https://example.com/politics/committee'
    assert 'https://example.com/politics/committee#notes' in committee['url_aliases']
    discovery = next(d for d in by_kind(records, 'discovery')
                     if d.get('external_id') == 'urn:example:committee-notes')
    assert discovery['url'] == 'https://example.com/politics/committee#notes'  # original preserved


def test_publication_precisions_follow_c3():
    records = ingest(feed_fetch())
    assert version_where(records, 'doe-votes')['publication'] == {
        'precision': 'instant', 'at': '2026-10-19T18:30:00Z', 'basis': 'publisher'}
    assert version_where(records, 'roe-speaks')['publication'] == {
        'precision': 'day', 'date': '2026-10-19', 'basis': 'publisher'}
    assert version_where(records, 'committee')['publication'] == {
        'precision': 'day', 'date': '2026-10-20', 'basis': 'publisher'}


def test_time_without_timezone_never_becomes_an_invented_instant():
    assert publication_from_feed('Mon, 19 Oct 2026 18:30:00') == {
        'precision': 'day', 'date': '2026-10-19', 'basis': 'publisher'}
    assert publication_from_feed('not a date') == {'precision': 'unknown'}
    assert publication_from_feed('') == {'precision': 'unknown'}


def test_iso_and_rfc3339_feed_timestamps_parse():
    assert publication_from_feed('2026-10-19T18:30:00Z') == {
        'precision': 'instant', 'at': '2026-10-19T18:30:00Z', 'basis': 'publisher'}
    assert publication_from_feed('2026-10-19T18:30:00+00:00') == {
        'precision': 'instant', 'at': '2026-10-19T18:30:00Z', 'basis': 'publisher'}
    assert publication_from_feed('2026-10-19T18:30:00') == {
        'precision': 'day', 'date': '2026-10-19', 'basis': 'publisher'}
    assert publication_from_feed('2026-10-19') == {
        'precision': 'day', 'date': '2026-10-19', 'basis': 'publisher'}
    assert publication_from_feed('Mon, 19 Oct 2026 18:30:00 GMT') == {
        'precision': 'instant', 'at': '2026-10-19T18:30:00Z', 'basis': 'publisher'}


def test_extraction_and_text_hash():
    records = ingest(feed_fetch())
    doe = version_where(records, 'doe-votes')
    # script content dropped, entity unescaped, whitespace collapsed
    assert doe['text'] == 'Alex Doe voted & approved the plan.'
    assert doe['text_hash'] == sha256(doe['text'].encode('utf-8')).hexdigest()
    run = by_kind(records, 'run')[0]
    capture = by_kind(records, 'capture')[0]
    assert run['processor'] == 'extract'
    assert run['inputs'] == [{'kind': 'capture', 'id': capture['id']}]
    assert doe['run_id'] == run['id']
    assert doe['capture_id'] == capture['id']


def test_inline_tags_do_not_insert_artificial_spaces():
    from news_lake.adapters import extract_text

    html = ('<p><a href="https://example.com/doe">Alex Doe</a>, Jr. said '
            '<em>Pol</em>itics &amp; policy.</p><div>Next<br/>block</div>')
    assert extract_text(html) == 'Alex Doe, Jr. said Politics & policy. Next block'


def test_atom_updated_timestamp_is_used_when_published_is_absent():
    feed = b"""<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <title>Atom News</title><link href="https://www.example.com/"/>
      <entry>
        <title>Atom story</title>
        <link href="https://example.com/politics/atom-story"/>
        <id>urn:example:atom-story</id>
        <updated>2026-10-19T18:30:00Z</updated>
      </entry>
    </feed>"""
    records = ingest(feed_fetch(feed, url='https://www.example.com/atom.xml'))
    version = version_where(records, 'atom-story')
    assert version['publication'] == {
        'precision': 'instant', 'at': '2026-10-19T18:30:00Z', 'basis': 'publisher'}


def test_no_title_entry_is_an_item_without_a_version():
    records = ingest(feed_fetch())
    untitled = item_where(records, 'untitled')
    assert 'current_version_id' not in untitled
    versions = by_kind(records, 'version')
    assert all(v['item_id'] != untitled['id'] for v in versions)
    assert all(v['title'] for v in versions)  # nothing fabricated
    # The duplicate entry carried a different title; the first observation wins.
    assert version_where(records, 'doe-votes')['title'] == 'Alex Doe votes yes'


# -- fetch outcomes (C2/C5) ----------------------------------------------------


def test_http_failed_feed_is_a_failed_capture_with_error_code():
    records = ingest(feed_fetch(outcome='failed', status=500, error_code='http_500', body=None,
                                payload_uri=None, rights_basis=None, media_type=None))
    assert len(records) == 1
    capture = records[0]
    assert capture['status'] == 'failed'
    assert capture['error_code'] == 'http_500'
    assert 'payload_uri' not in capture and 'payload_hash' not in capture and 'media_type' not in capture


def test_not_modified_feed_records_no_payload():
    records = ingest(feed_fetch(outcome='not_modified', status=304, body=None,
                                payload_uri=None, rights_basis=None, media_type=None))
    assert len(records) == 1
    capture = records[0]
    assert capture['status'] == 'not_modified'
    assert capture['http_status'] == 304


def test_blocked_source_is_metadata_only_everywhere():
    records = ingest(feed_fetch(metadata_only=True, payload_uri=None, rights_basis=None, media_type=None))
    capture = by_kind(records, 'capture')[0]
    assert capture['status'] == 'succeeded'
    assert capture['access'] == 'metadata_only'
    assert 'payload_uri' not in capture and 'payload_hash' not in capture and 'media_type' not in capture
    for version in by_kind(records, 'version'):
        assert version['access'] == 'metadata_only'
        assert 'text' not in version and 'text_hash' not in version
        assert version['title']  # the feed supplied titles; nothing fabricated
    check_corpus(records)


def test_redistributable_access_carries_rights_basis():
    records = ingest(feed_fetch(access='redistributable',
                                rights_basis='Fixture dedication to the public domain.'))
    capture = by_kind(records, 'capture')[0]
    assert capture['access'] == 'redistributable'
    version = version_where(records, 'doe-votes')
    assert version['access'] == 'redistributable'
    assert version['rights_basis'] == 'Fixture dedication to the public domain.'
    check_corpus(records)


# -- C1: cross-domain canonical must not merge outlets -------------------------


def test_cross_domain_link_does_not_merge_two_outlets():
    # Outlet X's feed points at an article URL owned by outlet Y.
    feed_x = b"""<?xml version="1.0"?><rss version="2.0"><channel>
      <title>X News</title><link>https://x.example/</link>
      <item><title>Story via Y</title><link>https://y.example/shared-story</link>
      <pubDate>Mon, 19 Oct 2026 12:00:00 GMT</pubDate></item>
    </channel></rss>"""
    feed_y = b"""<?xml version="1.0"?><rss version="2.0"><channel>
      <title>Y News</title><link>https://y.example/</link>
      <item><title>Original story</title><link>https://y.example/shared-story</link>
      <pubDate>Mon, 19 Oct 2026 11:00:00 GMT</pubDate></item>
    </channel></rss>"""
    adapter = RssAdapter(frozen_context([
        'eeeeeeee-0000-4000-8000-000000000001', 'eeeeeeee-0000-4000-8000-000000000002']))
    records_x = adapter.ingest(feed_fetch(feed_x, url='https://x.example/feed.xml'))
    records_y = adapter.ingest(feed_fetch(feed_y, url='https://y.example/feed.xml'))
    item_x = by_kind(records_x, 'item')[0]
    item_y = by_kind(records_y, 'item')[0]
    assert item_x['id'] != item_y['id']  # two appearances, never merged (C1)
    check_corpus(records_x + records_y)


# -- determinism and replay (C2) ------------------------------------------------


CAPTURE_A = 'eeeeeeee-0000-4000-8000-0000000000aa'
CAPTURE_B = 'eeeeeeee-0000-4000-8000-0000000000bb'


def test_replaying_the_same_captured_result_reuses_ids():
    first = ingest(feed_fetch(), capture_id=CAPTURE_A)
    second = ingest(feed_fetch(), capture_id=CAPTURE_A)
    assert first == second


def test_a_new_successful_poll_is_a_new_observation_of_the_same_items():
    first = ingest(feed_fetch(), capture_id=CAPTURE_A)
    second = ingest(feed_fetch(), capture_id=CAPTURE_B)
    assert {i['id'] for i in by_kind(first, 'item')} == {i['id'] for i in by_kind(second, 'item')}
    assert {d['id'] for d in by_kind(first, 'discovery')} != {d['id'] for d in by_kind(second, 'discovery')}
    assert by_kind(first, 'capture')[0]['id'] != by_kind(second, 'capture')[0]['id']
    # The newer extraction supersedes the item's selected version pointer.
    versions_first = {i['id']: i.get('current_version_id') for i in by_kind(first, 'item')}
    for item in by_kind(second, 'item'):
        if 'current_version_id' in item:
            assert item['current_version_id'] != versions_first[item['id']]


# -- end to end through storage --------------------------------------------------


def test_feed_to_release_round_trip(lake, control, coordinator):
    records = ingest(feed_fetch())
    coordinator.commit(records)
    run = by_kind(records, 'run')[0]
    release = publish_release(
        coordinator, [], release_id='dddddddd-0000-4000-8000-000000000001',
        recorded_at='2026-10-20T04:00:00Z',
        selections=[{'processor': 'extract', 'processor_version': run['processor_version'],
                     'config_hash': run['config_hash']}],
        checkpoints=[{'connector_key': 'rss:example', 'checkpoint_ref': 'urn:fixture:checkpoints:rss-1',
                      'completed_until': '2026-10-20T04:00:00Z'}],
    )
    read = read_release(lake, control, release['id'])
    stored = [record for rows in read['tables'].values() for record in rows]
    assert {record['id'] for record in stored} == {record['id'] for record in records}
    assert len(stored) == len(records)
    # Replay commits nothing new.
    coordinator.commit(copy.deepcopy(records))
    assert len(lake.read_all('news.items')) == 4
    assert len(lake.read_all('news.versions')) == 3


# -- review regressions -----------------------------------------------------------


def test_backfill_ingest_labels_discoveries_and_the_run_backfill():
    """Review finding: the extraction run was hardcoded mode='live' while the
    caller's mode reached only discoveries."""
    records = ingest(feed_fetch(), mode='backfill')
    assert all(d['mode'] == 'backfill' for d in by_kind(records, 'discovery'))
    assert all(r['mode'] == 'backfill' for r in by_kind(records, 'run'))


def test_credentialed_request_urls_are_redacted(lake, control, coordinator):
    """C2 regression: credentials must not reach any stored record or checkpoint."""
    import json

    from news_lake.adapters import Page, PageDrain

    body = FEED.replace(
        b'https://example.com/news/budget',
        b'https://alice:topsecret@example.com/news/budget',
    )
    records = ingest(feed_fetch(url='https://user:secret@example.com/feed.xml', body=body))
    serialized = json.dumps(records)
    assert 'secret' not in serialized
    assert 'topsecret' not in serialized
    capture = by_kind(records, 'capture')[0]
    assert capture['request_url'] == 'https://example.com/feed.xml'
    assert by_kind(records, 'outlet')[0]['feed_urls'] == ['https://example.com/feed.xml']
    assert all(d['feed_url'] == 'https://example.com/feed.xml' for d in by_kind(records, 'discovery'))

    drain = PageDrain('rss:example', coordinator.commit)
    drain.consume(Page(records, checkpoint_ref='https://user:secret@example.com/cp/1',
                       completed_until='2026-10-20T04:00:00Z'))
    cp = drain.checkpoint()
    assert cp['checkpoint_ref'] == 'https://example.com/cp/1'
    release = publish_release(
        coordinator, [], release_id='dddddddd-0000-4000-8000-000000000009',
        recorded_at='2026-10-20T04:00:00Z', selections=[],
        checkpoints=[{'connector_key': 'rss:direct',
                      'checkpoint_ref': 'https://user:secret@example.com/cp/2'}],
    )
    assert 'secret' not in json.dumps(release)
    assert 'secret' not in json.dumps(control.active_cursor())
