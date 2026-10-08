"""Shared alerts are not hearing links; gone pages retain their failure evidence."""
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urljoin

import pytest

from congress_api.acquisition import house_sites
from congress_api.acquisition.house import request
from congress_api.models.content import content_bytes
from congress_api.parsers.committee_discovery import discover, key, task
from congress_api.parsers.committee_pages import parse_event_page
from congress_api.transport import http
from test_house_committee_fallback import DIRECTORY

FIXTURES = Path(__file__).parent / 'fixtures/meeting_inventory/house-sites'


def test_retained_science_alert_is_not_an_event_request_and_page_content_is_preserved():
    source = json.loads((FIXTURES / 'science-relative-alert-source.json').read_text())
    body = (FIXTURES / source['file']).read_bytes()
    assert hashlib.sha256(body).hexdigest() == source['sha256']
    links = discover(body, task(source['url'], 'event'))
    assert not any(link['url'].endswith('/sciencefirings') for link in links)
    assert any('/hearings' in link['url'] for link in links)
    page = parse_event_page(body, source['url'])
    assert page['event'] == source['event']
    assert len(page['documents']) == source['documents'] == 13
    assert content_bytes(page['raw_html']) == body


@pytest.mark.parametrize('alert', ['class="alert"', 'class="notice alert active"', 'role="alert"'])
@pytest.mark.parametrize('parent', ['/hearings/2022/6/subject', '/markups/subject', '/hearings'])
def test_alert_link_needs_its_own_event_evidence(alert, parent):
    base = 'https://example.house.gov' + parent
    body = f'''<div {alert}><a href="sciencefirings">Contact us</a>
        <a href="/hearings/other">Read more</a><a href="relative-subject">Upcoming hearing</a>
        <a href="?EventID=123">Join us</a><a href="/calendar/default.aspx">Calendar</a>
        <a href="https://archive-example.house.gov/">Archived site</a></div>
        <nav><a href="/events">Events</a></nav>'''.encode()
    links = discover(body, task(base))
    urls = {link['url'] for link in links}
    assert urljoin(base, 'sciencefirings') not in urls
    assert urls == {urljoin(base, target) for target in [
        '/hearings/other', 'relative-subject', '?EventID=123', '/calendar/default.aspx',
        'https://archive-example.house.gov/', '/events']}
    assert all(link['discovered_from'] == base for link in links)


def test_unqualified_links_outside_site_alerts_keep_existing_discovery():
    base = 'https://example.house.gov/hearings/original'
    body = b'<main><a href="detail">Read more</a></main><div class="alerted"><a href="other">Other</a></div>'
    assert {link['url'] for link in discover(body, task(base, 'event'))} == {
        'https://example.house.gov/hearings/detail', 'https://example.house.gov/hearings/other'}


@pytest.mark.parametrize('status', [404, 410, 403, 429, 503])
def test_unavailable_observation_preserves_page_and_receipts_and_keeps_transient_failures(status, monkeypatch, tmp_path):
    home = 'https://example.house.gov/'
    url = home + 'events/retained'; item = task(url, 'event'); identifier = key(item)
    page = parse_event_page(b'<h1>Retained hearing</h1><p>Date: January 1, 2001</p>', url)
    old_receipt = dict(url=url, status_code=200, outcome='retrieved', completed_at='2026-10-06T00:00:00Z')
    old_error = dict(request=item, error='Previous interruption', checked_at='2026-10-06T01:00:00Z')
    state = {'example.house.gov': dict(pages={url: deepcopy(page)}, pending=[item], done={},
        errors={identifier: deepcopy(old_error)}, sources={identifier:dict(url=url, page_url=url, receipts=[deepcopy(old_receipt)])})}
    calls = []
    def fetch(session, target, **kwargs):
        calls.append(target)
        assert kwargs['allowed'] == (200, 404)  # Shared transport policy stays unchanged.
        if status == 404:
            return SimpleNamespace(url=target, status_code=404, content=b'')
        raise http.HttpRequestError('Recorded response', status, attempts=1)
    monkeypatch.setattr(http, 'get_with_retry', fetch)
    rows = [{**DIRECTORY[0], 'detail': {'committeeWebsiteUrl': home}}]
    result = house_sites.collect(rows, state, today=date(2026, 10, 7),
        get=lambda url, receipts: request(url, False, receipts))
    saved = state['example.house.gov']; observation = saved['sources'][identifier]
    unavailable = status in {404, 410}
    assert calls == [url] and result['pending'] == 0
    assert result['failed'] == (0 if unavailable else 1)
    assert saved['coverage']['unavailable'] == int(unavailable)
    assert saved['pages'][url] == page
    assert observation['receipts'][0] == old_receipt and len(observation['receipts']) == 2
    last = observation['receipts'][-1]
    if status != 404:
        assert last['outcome'] == 'error' and last['transport_failure']['status'] == status
    if unavailable:
        assert observation['status'] == status
        resolution, = saved['resolved_errors'][identifier]
        assert resolution['failure'] == old_error and resolution['resolution'] == 'unavailable'
    house_sites.outputs(state, tmp_path)
    assert 'Retained hearing' in (tmp_path / 'house_site_events.csv').read_text()


def test_optional_410_remains_a_discovery_gap():
    item = task('https://example.house.gov/sitemap.xml', 'sitemap')
    saved = dict(home='https://example.house.gov/', sources={}, pages={})
    receipt = dict(outcome='error', transport_failure=dict(status=410, attempts=1))
    assert house_sites._read(saved, item, (None, [receipt], http.HttpRequestError('Gone index', 410)), today=date(2026, 10, 7)) == []
    assert saved['sources'][key(item)]['discovery_gap'] == 'index_not_available'
    assert saved['sources'][key(item)]['receipts'] == [receipt]
