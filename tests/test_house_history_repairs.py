"""Actual older House listings plus transport/receipt preservation regressions."""
from copy import deepcopy
from collections import deque
from datetime import date
import hashlib
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import pytest
import requests
from urllib3.exceptions import MaxRetryError, NameResolutionError

from congress_api.acquisition import house, house_sites
from congress_api.parsers.committee_discovery import comparison_key, discover, key, listing_records, task
from congress_api.parsers.committee_pages import parse_event_page
from congress_api.transport import http
from test_house_sites import client, DIRECTORY, HOME

FIXTURES = Path(__file__).parent / 'fixtures/meeting_inventory/house-sites'


def fixture(name):
    row = next(r for r in json.loads((FIXTURES / 'history-repair-sources.json').read_text()) if r['file'] == name)
    body = (FIXTURES / name).read_bytes()
    assert hashlib.sha256(body).hexdigest() == row['sha256']
    return body, row['url']


def test_explicit_old_event_subject_wins_over_newsletter_heading():
    body, url = fixture('smallbusiness-zte.html')
    page = parse_event_page(body, url)
    assert page['title'] == 'ZTE: A Threat to America’s Small Businesses'
    assert page['event']['title'] == page['title']
    assert page['event']['date'] == '2018-06-27'
    assert len(page['documents']) == 10


def test_query_comparison_preserves_originals_and_repeated_value_order():
    first = task(HOME + 'events?Page=2&Congress=111')
    other = task(HOME + 'events?Congress=111&Page=2')
    original = deepcopy(first)
    assert comparison_key(first) == comparison_key(other)
    assert key(first) != key(other) and first == original
    assert comparison_key(task(HOME + '?a=1&a=2')) != comparison_key(task(HOME + '?a=2&a=1'))
    assert comparison_key(task(HOME + '?a=')) != comparison_key(task(HOME))


def test_repeated_archive_navigation_preserves_first_source_relationship():
    archive = 'https://archive-example.house.gov/'
    saved = dict(home=HOME, linked_sites={archive: HOME}, done={}, pages={})
    house_sites._enqueue(saved, deque(), set(), task(archive, 'site_home', parent=HOME + 'events/old'),
                         today=date(2026,10,7), refresh=[0])
    assert saved['linked_sites'][archive] == HOME


def test_same_listing_page_under_reordered_parameters_is_not_a_loop():
    body, url = fixture('smallbusiness-page2.html')
    alias = url.replace('Congress=111&Page=2', 'Page=2&Congress=111')
    saved = {}
    for u in [alias, url]:
        request = task(u)
        house_sites._check_pagination(saved, request, discover(body, request), source_body=body)
    assert sum(len(v) for v in saved['pagination'].values()) == 1


def test_different_bill_rows_can_share_the_same_hearing_link():
    saved = {};event_sets = []
    for name in ['foreignaffairs-bills-page1.html', 'foreignaffairs-bills-page2.html']:
        body, url = fixture(name);request = task(url);links = discover(body, request)
        event_sets.append({r['url'] for r in links if r['kind'] == 'event'})
        house_sites._check_pagination(saved, request, links, source_body=body)
    assert event_sets[0] == event_sets[1]
    assert sum(len(v) for v in saved['pagination'].values()) == 2


def test_actual_repeated_listing_rows_still_stop_pagination():
    body, url = fixture('smallbusiness-page2.html');saved = {}
    house_sites._check_pagination(saved, task(url), discover(body, task(url)), source_body=body)
    other = url.replace('Page=2', 'Page=3')
    # Changing the pager alone does not change the actual listed records.
    changed_pager = body.replace(b'Page=3', b'Page=4').replace(b'Page=1', b'Page=2')
    with pytest.raises(ValueError, match='same records'):
        house_sites._check_pagination(saved, task(other), discover(changed_pager, task(other)), source_body=changed_pager)


def test_drupal_event_grids_do_not_fingerprint_shared_footer_addresses():
    saved = {}
    for name in ['cha-hearings-page1.html', 'cha-hearings-page2.html']:
        body, url = fixture(name)
        records = listing_records(body, url)
        assert len(records) == 10
        assert not any('Main Office' in record for record in records)
        house_sites._check_pagination(saved, task(url), discover(body, task(url)), source_body=body)
    assert sum(len(v) for v in saved['pagination'].values()) == 2
    # A genuinely repeated event grid must still be rejected.
    other = url.replace('page=2', 'page=3')
    with pytest.raises(ValueError, match='same records'):
        house_sites._check_pagination(saved, task(other), discover(body, task(other)), source_body=body)


def test_empty_listing_navigation_is_not_a_repeated_record():
    body, url = fixture('smallbusiness-empty-listing.html');saved = {}
    for u in [url, url.replace('Page=1', 'Page=3')]:
        links = discover(body, task(u))
        assert links and not any(link['kind'] == 'event' for link in links)
        house_sites._check_pagination(saved, task(u), links, source_body=body)
    assert not saved.get('pagination')


def test_old_derived_pagination_cache_is_replaced_without_touching_sources():
    body, url = fixture('smallbusiness-page2.html')
    saved = {'pagination': {'old-signature': {'old-digest': 'old-key'}}, 'sources': {'receipt': {'status': 200}}}
    source = deepcopy(saved['sources'])
    house_sites._check_pagination(saved, task(url), discover(body, task(url)), source_body=body)
    assert 'old-signature' not in saved['pagination']
    assert saved['pagination_version'] == house_sites.PAGINATION_VERSION
    assert saved['sources'] == source


def test_event_query_ids_on_same_path_remain_guarded():
    saved = {}
    links = [task(HOME + 'hearings?ID=abc', 'event')]
    house_sites._check_pagination(saved, task(HOME + 'hearings?page=1'), links)
    with pytest.raises(ValueError, match='same records'):
        house_sites._check_pagination(saved, task(HOME + 'hearings?page=2'), links)


def test_successful_retry_keeps_failed_receipt_and_error_history():
    url = HOME + 'events/old';request = task(url, 'event');identifier = key(request)
    failure = dict(request=request, error='old request error', checked_at='2026-10-06T01:00:00Z')
    receipt = dict(url=url, outcome='error', error='old request error', completed_at='2026-10-06T01:00:00Z')
    saved = dict(pages={}, done={}, pending=[request], errors={identifier: failure},
                 sources={identifier: dict(url=url, kind='event', receipts=[receipt])})
    state = {'energycommerce.house.gov': saved};before = deepcopy(receipt)
    get, _ = client({url: b'<h1>Old hearing</h1><p>Date: January 1, 2001</p>'})
    house_sites.collect(DIRECTORY, state, today=date(2026,10,7), get=get, limit=1)
    assert saved['sources'][identifier]['receipts'][0] == before
    assert len(saved['sources'][identifier]['receipts']) == 2
    assert identifier not in saved['errors']
    assert saved['resolved_errors'][identifier][0]['failure'] == failure
    assert saved['pages'][url]['event']['date'] == '2001-01-01'


def test_transport_details_keep_timeout_type_and_attempts_without_secret_messages(monkeypatch):
    monkeypatch.setattr(http, 'pace_request', lambda *a, **kw: None)
    calls = []
    def request(*a, **kw):
        calls.append(kw)
        raise requests.ReadTimeout('request https://test.gov/?api_key=secret-value')
    with pytest.raises(http.HttpRequestError) as error:
        http.get_with_retry(SimpleNamespace(request=request), 'https://test.gov/path?api_key=secret-value')
    assert len(calls) == 3 and all(c['timeout'] == 60 for c in calls)
    assert error.value.details == dict(status='request error', attempts=3, exception_types=['ReadTimeout'])
    assert 'ReadTimeout' in str(error.value) and 'secret-value' not in str(error.value)
    assert 'secret-value' not in json.dumps(error.value.details)


def test_nested_dns_failure_keeps_classes_without_sensitive_exception_text():
    cause = socket.gaierror('secret-value')
    dns = NameResolutionError('private-host', None, cause)
    dns.__cause__ = cause
    wrapped = requests.ConnectionError(MaxRetryError(None, '/?api_key=secret-value', dns))
    classes = http.exception_types(wrapped)
    assert classes[:3] == ['ConnectionError', 'MaxRetryError', 'NameResolutionError']
    assert 'gaierror' in classes and 'secret-value' not in json.dumps(classes)


def test_final_http_status_does_not_keep_an_earlier_timeout(monkeypatch):
    monkeypatch.setattr(http, 'pace_request', lambda *a, **kw: None)
    calls = []
    def request(*a, **kw):
        calls.append(None)
        if len(calls) == 1: raise requests.ReadTimeout('timed out')
        return SimpleNamespace(status_code=404)
    with pytest.raises(http.HttpRequestError) as error:
        http.get_with_retry(SimpleNamespace(request=request), HOME)
    assert error.value.details == dict(status=404, attempts=2, exception_types=[])


def test_house_receipt_retains_structured_transport_failure(monkeypatch):
    def fail(*a, **kw):
        raise http.HttpRequestError('safe failure', 'request error', attempts=3, exception_types=['ReadTimeout'])
    monkeypatch.setattr(http, 'get_with_retry', fail)
    receipts = []
    with pytest.raises(http.HttpRequestError):
        house.request(HOME + 'events/old', False, receipts)
    assert receipts[0]['transport_failure']['exception_types'] == ['ReadTimeout']
    assert receipts[0]['transport_failure']['attempts'] == 3
