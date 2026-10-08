"""Retained diagnostic responses and explicitly selected failure recovery."""
from copy import deepcopy
from datetime import date
import hashlib
import importlib.util
import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from congress_api.acquisition import house_sites
from congress_api.models.content import content_bytes
from congress_api.parsers.committee_discovery import discover, key, listing_records, task
from congress_api.parsers.committee_pages import event_identity, listing_url, parse_event_page
from test_house_sites import client
from test_house_committee_fallback import DIRECTORY, HOME

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / 'tests/fixtures/meeting_inventory/house-sites'
TODAY = date(2026, 10, 8)
HOST = 'energycommerce.house.gov'


def fixture(name):
    row = next(row for row in json.loads((FIXTURES / 'diagnostic-recovery-sources.json').read_text()) if row['file'] == name)
    body = (FIXTURES / name).read_bytes()
    assert hashlib.sha256(body).hexdigest() == row['sha256']
    return row, body


@pytest.mark.parametrize('number', [91, 103])
def test_retained_committee_activity_cards_are_not_an_event(number):
    row, body = fixture(f'foreignaffairs-committee-activity-{number}.html')
    page = parse_event_page(body, row['url'])
    assert listing_url(row['url'])
    assert page['page_kind'] == 'listing' and page['event'] is None
    assert page['documents'] == []
    assert len(listing_records(body, row['url'])) == 15
    # These particular listing pages contain bill cards; preserve their literal targets.
    assert any('/committee-activity/bills/h-r-' in item['url'] for item in discover(body, task(row['url'])))
    assert content_bytes(page['raw_html']) == body


@pytest.mark.parametrize('url', [
    'https://example.house.gov/committee-activity',
    'https://example.house.gov/committee-activity/?page=2',
    'https://example.house.gov/Committee-Activity?page=2',
])
def test_activity_route_guard_preserves_explicit_details(url):
    body = b'<h1>Child hearing</h1><p>Date: January 1, 2001</p>'
    assert event_identity(body, url) is None
    for explicit in [url + ('&' if '?' in url else '?') + 'EventID=42',
                     'https://example.house.gov/committee-activity/hearings/real-event']:
        assert event_identity(body, explicit)['title'] == 'Child hearing'


def probe_module():
    path = ROOT / 'docs/youtube-coverage/research/scripts/probe_house_sites.py'
    spec = importlib.util.spec_from_file_location('house_site_probe_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Response:
    status_code = 200
    headers = {'Content-Type': 'application/json'}

    def __init__(self, url, body):
        self.url = url
        self.request = SimpleNamespace(url=url)
        self.body = body
        self.closed = False

    def iter_content(self, chunk_size):
        yield self.body

    def close(self):
        self.closed = True


def test_probe_keeps_retained_calendar_post_body_through_discovery(monkeypatch, tmp_path):
    row, body = fixture('energycommerce-calendar-offset1120.json')
    item = row['request']
    before = deepcopy(item)
    response = Response(item['url'], body)
    module = probe_module()
    def get(session, url, **kwargs):
        assert kwargs['attempts'] == 1 and kwargs['method'] == 'POST'
        assert kwargs['json_body'] == item['body']
        return response
    monkeypatch.setattr(module.http, 'get_with_retry', get)
    result = module.probe(None, item, tmp_path)
    assert result.get('discovery_error') is None
    assert result['discovered_count'] == 21  # 20 event links plus offset1140.
    assert result['request'] == item == before
    assert Path(result['body_path']).read_bytes() == body
    assert result['body_sha256'] == row['sha256'] and response.closed


def test_probe_body_files_distinguish_post_requests_at_the_same_url(monkeypatch, tmp_path):
    module = probe_module()
    def get(session, url, **kwargs):
        offset = kwargs['json_body']['offset']
        return Response(url, json.dumps({'events_connection': {'nodes': []}, 'offset': offset}).encode())
    monkeypatch.setattr(module.http, 'get_with_retry', get)
    reports = [module.probe(None, task(HOME+'api/events', 'calendar_api', body={'offset': n, 'limit': 20}), tmp_path) for n in [0, 20]]
    assert all(not r.get('error_type') and not r.get('discovery_error') for r in reports)
    assert reports[0]['body_path'] != reports[1]['body_path']
    assert len(list((tmp_path/'responses').iterdir())) == 2


def saved_failures():
    chosen = task(HOME+'events/chosen', 'event', parent=HOME+'events')
    other = task(HOME+'events/unrelated', 'event')
    state = {HOST: dict(home=HOME, pages={}, sources={}, pending=[], done={}, errors={},
                        pagination={'old': {'digest': 'request'}}, discovery_checked='2026-10-07', parser_version=5)}
    for item in [chosen, other]:
        identifier = key(item)
        state[HOST]['errors'][identifier] = dict(request=deepcopy(item), error='Old DNS failure', checked_at='2026-10-07T01:00:00Z')
        state[HOST]['sources'][identifier] = dict(url=item['url'], receipts=[{'outcome':'error','completed_at':'2026-10-07T01:00:00Z'}])
        state[HOST]['done'][identifier] = dict(url=item['url'], kind=item['kind'])
    return state, [{'site': HOST, 'request': chosen}], other


def test_selected_retry_reuses_receipts_without_seeds_other_errors_or_discovery():
    state, targets, other = saved_failures()
    before = deepcopy(state)
    item = targets[0]['request']
    body = b'<h1>Chosen hearing</h1><p>Date: January 1, 2001</p><a href="/events/new">New hearing</a>'
    get, calls = client({item['url']: body})
    result = house_sites.collect(DIRECTORY, state, today=TODAY, get=get, retry_requests=targets)
    assert calls == [(item['url'], {})]
    assert result['mode'] == 'retry_requests' and result['failed'] == result['pending'] == 0
    assert result['retained_failed'] == 1
    saved = state[HOST]
    assert saved['errors'] == {key(other): before[HOST]['errors'][key(other)]}
    for field in ['pagination', 'discovery_checked', 'parser_version']:
        assert saved[field] == before[HOST][field]
    assert saved['done'][key(other)] == before[HOST]['done'][key(other)]
    assert saved['sources'][key(other)] == before[HOST]['sources'][key(other)]
    assert saved['sources'][key(item)]['receipts'][:1] == before[HOST]['sources'][key(item)]['receipts']
    assert saved['resolved_errors'][key(item)][0]['failure'] == before[HOST]['errors'][key(item)]
    assert content_bytes(saved['pages'][item['url']]['raw_html']) == body
    # Reusing the exact manifest is a no-op once those failures are resolved.
    house_sites.collect(DIRECTORY, state, today=TODAY, get=get, retry_requests=targets)
    assert len(calls) == 1


def test_selected_retry_preserves_post_body_and_does_not_expand_calendar():
    row, body = fixture('energycommerce-calendar-offset1120.json')
    item = row['request']; identifier = key(item)
    state = {HOST: dict(home=HOME, pages={}, sources={}, pending=[], done={identifier:item},
                       errors={identifier:dict(request=item, error='DNS')})}
    get, calls = client({item['url']:body})
    result = house_sites.collect(DIRECTORY, state, today=TODAY, get=get,
        retry_requests=[{'site':HOST, 'request':item}])
    assert calls == [(item['url'], {'json_body': item['body']})]
    assert result['pending'] == result['failed'] == 0
    assert state[HOST]['pages'] == {}
    assert content_bytes(state[HOST]['sources'][identifier]['content']) == body


@pytest.mark.parametrize('problem', ['unknown', 'altered_body', 'other_pending', 'duplicate', 'empty', 'wrong_site'])
def test_selected_retry_rejects_invalid_selection_before_mutating_state(problem):
    state, targets, other = saved_failures()
    if problem == 'unknown': targets[0]['request'] = task(HOME+'events/new', 'event')
    elif problem == 'altered_body': targets[0]['request']['body'] = {'offset':100}
    elif problem == 'other_pending': state[HOST]['pending'] = [other]
    elif problem == 'duplicate': targets *= 2
    elif problem == 'empty': targets = []
    else: targets[0]['site'] = 'absent.house.gov'
    before = deepcopy(state)
    with pytest.raises(ValueError):
        house_sites.collect(DIRECTORY, state, today=TODAY, get=lambda *a,**k: pytest.fail('No request allowed'), retry_requests=targets)
    assert state == before


def test_selected_retry_budget_and_graceful_stop_resume_with_same_manifest():
    state, targets, other = saved_failures();targets.append({'site':HOST, 'request':other})
    get, calls = client({t['request']['url']:b'<h1>Hearing</h1><p>Date: January 1, 2001</p>' for t in targets})
    stop = Event(); stop.set()
    result = house_sites.collect(DIRECTORY, state, today=TODAY, get=get, retry_requests=targets, stop=stop)
    assert result['stopped'] and result['pending'] == 2 and not calls
    result = house_sites.collect(DIRECTORY, state, today=TODAY, get=get, retry_requests=targets, limit=1)
    assert result['pending'] == 1 and len(calls) == 1
    result = house_sites.collect(DIRECTORY, state, today=TODAY, get=get, retry_requests=targets)
    assert result['pending'] == result['failed'] == 0
    assert [u for u, _ in calls] == [t['request']['url'] for t in targets]


def test_selected_retry_leaves_another_site_state_untouched():
    state, targets, _ = saved_failures()
    state['other.house.gov'] = {'pending':[task('https://other.house.gov/events/queued')], 'errors':{}, 'done':{}}
    other = deepcopy(state['other.house.gov'])
    get, _ = client({targets[0]['request']['url']:b'<h1>Event</h1><p>Date: January 1, 2001</p>'})
    house_sites.collect(DIRECTORY, state, today=TODAY, get=get, retry_requests=targets)
    assert state['other.house.gov'] == other


def test_bounded_resume_rejects_ordinary_crawl_and_changed_manifest():
    state, targets, other = saved_failures()
    targets.append({'site': HOST, 'request': other})
    stop = Event(); stop.set()
    checkpoints = []
    house_sites.collect(DIRECTORY, state, today=TODAY, get=lambda *a, **k: pytest.fail('Stopped'),
                        retry_requests=targets, stop=stop, checkpoint=lambda s: checkpoints.append(deepcopy(s)))
    assert len(checkpoints[0][HOST]['retry_selection']) == 64
    before = deepcopy(state)
    for options in [{}, {'retry_requests': targets[:1]}, {'retry_requests': targets, 'sites': [HOST]}]:
        with pytest.raises(ValueError):
            house_sites.collect(DIRECTORY, state, today=TODAY, get=lambda *a, **k: pytest.fail('No fetch'), **options)
        assert state == before


def test_budget_resume_does_not_retry_a_failed_target_again():
    state, targets, other = saved_failures()
    targets.append({'site': HOST, 'request': other})
    get, calls = client({targets[0]['request']['url']: RuntimeError('Still unavailable'), other['url']: b'<html>No event</html>'})
    result = house_sites.collect(DIRECTORY, state, today=TODAY, get=get, retry_requests=targets, limit=1)
    assert result['failed'] == 1 and result['pending'] == 1
    result = house_sites.collect(DIRECTORY, state, today=TODAY, get=get, retry_requests=targets)
    assert result['failed'] == 1 and result['pending'] == 0
    assert [u for u, _ in calls] == [t['request']['url'] for t in targets]
    assert len(state[HOST]['sources'][key(targets[0]['request'])]['receipts']) == 2


def test_multisite_resume_does_not_repeat_a_drained_sites_failed_target():
    from test_house_site_concurrency import inputs
    rows, _, _ = inputs(sites=2)
    owners = house_sites.directory(rows)
    state, targets = {}, []
    for index, (host, owner) in enumerate(owners.items()):
        saved = state[host] = dict(owner, pages={}, sources={}, pending=[], done={}, errors={})
        for n in range(index + 1):
            item = task(owner['home']+f'events/hearing-{n}', 'event')
            targets.append({'site':host, 'request':item})
            saved['errors'][key(item)] = {'request':item, 'error':'Old failure'}
    get, calls = client({t['request']['url']:RuntimeError('Still unavailable') for t in targets})
    first = house_sites.collect(rows, state, today=TODAY, get=get, retry_requests=targets, limit=2, workers=1)
    assert first['pending'] == 1 and len(calls) == 2
    before = deepcopy(state)
    with pytest.raises(ValueError):
        house_sites.collect(rows, state, today=TODAY, get=get, retry_requests=targets[1:])
    assert state == before and len(calls) == 2
    final = house_sites.collect(rows, state, today=TODAY, get=get, retry_requests=targets)
    assert final['pending'] == 0 and final['failed'] == 3
    assert len(calls) == 3 and len({u for u, _ in calls}) == 3


@pytest.mark.parametrize('status', [404, 410])
def test_bounded_retry_keeps_old_page_and_exact_terminal_receipts(status):
    from congress_api.transport.http import HttpRequestError
    state, targets, _ = saved_failures()
    item = targets[0]['request']
    old = parse_event_page(b'<h1>Old hearing</h1><p>Date: January 1, 2001</p>', item['url'])
    state[HOST]['pages'][item['url']] = deepcopy(old)
    get, calls = client({item['url']: HttpRequestError('Gone', status)})
    result = house_sites.collect(DIRECTORY, state, today=TODAY, get=get, retry_requests=targets)
    assert result['failed'] == result['pending'] == 0 and result['retained_failed'] == 1
    assert state[HOST]['pages'][item['url']] == old
    source = state[HOST]['sources'][key(item)]
    assert source['status'] == status and len(source['receipts']) == 2
    assert state[HOST]['resolved_errors'][key(item)][0]['resolution'] == 'unavailable'


@pytest.mark.parametrize('manifest', [None, {}, [], [None], [{'site': HOST}], [{'site': [], 'request': {}}]])
def test_retry_cli_rejects_invalid_manifest_without_loading_or_writing_state(monkeypatch, tmp_path, manifest):
    path = tmp_path / 'manifest.json'; path.write_text(json.dumps(manifest))
    # Shape errors must never turn --retry-requests null into a normal crawl.
    monkeypatch.setattr(house_sites, 'read_state', lambda *_: pytest.fail('Invalid manifest loaded state'))
    with pytest.raises(ValueError):
        house_sites.main(tmp_path/'missing-committees', tmp_path, tmp_path, retry_requests=path)


@pytest.mark.parametrize('options', [{'offline': True}, {'reparse': True}, {'site': [HOST]}])
def test_retry_cli_rejects_conflicting_modes_before_io(tmp_path, options):
    with pytest.raises(ValueError):
        house_sites.main(tmp_path/'missing', tmp_path, tmp_path, retry_requests=tmp_path/'missing-manifest', **options)


def test_cli_threads_retry_manifest_into_existing_main(monkeypatch, tmp_path):
    from congress_api.cli import house_sites as cli
    captured = []
    monkeypatch.setattr(cli, 'main', lambda **kw: captured.append(kw))
    cli.parse_args_and_run(['--committees', str(tmp_path/'committees'), '--state-dir', str(tmp_path),
                           '--output-dir', str(tmp_path), '--retry-requests', str(tmp_path/'manifest.json')])
    assert captured[0]['retry_requests'] == tmp_path/'manifest.json'


def test_retry_main_checkpoints_and_exports_only_selected_failure(tmp_path, monkeypatch):
    import gzip
    state, targets, _ = saved_failures()
    directory = tmp_path/'committees.jsonl.gz'
    directory.write_bytes(gzip.compress((json.dumps(DIRECTORY[0])+'\n').encode()))
    path = tmp_path/'manifest.json'; path.write_text(json.dumps(targets))
    house_sites.write_state(tmp_path/'house-sites.json.gz', state)
    item = targets[0]['request']
    get, calls = client({item['url']: b'<h1>Chosen hearing</h1><p>Date: January 1, 2001</p>'})
    monkeypatch.setattr(house_sites, 'request', lambda url, zyte, checks, **kw: get(url, checks, **kw))
    result = house_sites.main(directory, tmp_path, tmp_path, retry_requests=path, as_of=TODAY)
    assert result['mode'] == 'retry_requests' and result['failed'] == 0 and result['retained_failed'] == 1
    assert len(calls) == 1
    saved = house_sites.read_state(tmp_path/'house-sites.json.gz')[HOST]
    assert saved['pending'] == [] and 'retry_selection' not in saved
    assert item['url'] in (tmp_path/'house_site_events.csv').read_text()
