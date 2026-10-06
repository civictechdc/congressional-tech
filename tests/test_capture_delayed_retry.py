"""Server-directed waits free acquisition slots and survive checkpoints."""
import asyncio
from datetime import datetime, timezone
import time

import pytest

from congress_api.acquisition.raw_sync import run_async
from congress_api.retention.raw_archive import Archive
from test_async_capture import receipts
from test_raw_source_sync import MemoryStore, response


def deferred(url, delay=1):
    return response(url, b'Generating ZIP, retry later', media='text/html', status=503,
                    retry_later={'delay_seconds': delay, 'reason': 'retry_after'})


def test_retry_wait_does_not_hold_the_only_worker():
    calls = []
    def fetch(url):
        calls.append((url, time.monotonic()))
        if url.endswith('/a.zip') and sum(u == url for u, _ in calls) == 1:
            return deferred(url)
        return response(url, b'<bill/>', media='application/xml')
    store = MemoryStore()
    result = asyncio.run(run_async(Archive(store, 'retry'),
        [{'url': 'https://example.gov/a.zip'}, {'url': 'https://example.gov/b.xml'}],
        fetch=fetch, workers=1, limit=3, initial_only=True))
    assert [u.rsplit('/', 1)[-1] for u, _ in calls] == ['a.zip', 'b.xml', 'a.zip']
    assert calls[-1][1] - calls[0][1] >= 1
    assert result['retry_later'] == 1
    assert result['saved'] == 2
    assert [r['record']['outcome'] for r in receipts(store)] == ['retry_later', 'saved', 'saved']


def test_long_retry_is_checkpointed_without_waiting_past_run_deadline():
    store = MemoryStore()
    started = time.monotonic()
    result = asyncio.run(run_async(Archive(store, 'defer'),
        [{'url': 'https://example.gov/a.zip'}], fetch=lambda u: deferred(u, 7200),
        max_seconds=0.1))
    assert time.monotonic() - started < 5
    assert result['attempted'] == 1
    state = Archive(store, 'resume').state['https://example.gov/a.zip']
    delay = (datetime.fromisoformat(state['next_attempt_at']) - datetime.fromisoformat(state['checked_at'])).total_seconds()
    assert delay == 7200
    assert state['outcome'] == 'retry_later'


def test_repeated_retry_hints_are_bounded_per_run():
    store = MemoryStore()
    result = asyncio.run(run_async(Archive(store, 'bounded'),
        [{'url': 'https://example.gov/a.zip'}], fetch=deferred, limit=100))
    assert result['attempted'] == 4
    assert len(receipts(store)) == 4
    state = Archive(store, 'resume').state['https://example.gov/a.zip']
    assert state['outcome'] == 'retry_later'
    assert datetime.fromisoformat(state['next_attempt_at']) >= datetime.now(timezone.utc)


def test_attempt_limit_also_bounds_delayed_retries():
    result = asyncio.run(run_async(Archive(MemoryStore(), 'limit'),
        [{'url': 'https://example.gov/a.zip'}], fetch=deferred, limit=1))
    assert result['attempted'] == 1
    assert result['retry_later'] == 1


def test_initial_population_leaves_old_failures_and_retained_replays_untouched():
    store = MemoryStore()
    archive = Archive(store, 'initial')
    old = {}
    for outcome in ['retry_later', 'request_failed', 'http_error', 'retained', 'size_limit']:
        url = f'https://example.gov/{outcome}.xml'
        archive.seed({'url': url}, publisher_link=True)
        archive.state[url].update(outcome=outcome, next_attempt_at=None)
        old[url] = dict(archive.state[url])
    calls = []
    def fetch(url):
        calls.append(url)
        if url.endswith('/page.html'):
            return response(url, b'<a href="https://example.gov/new.xml">new</a>', media='text/html')
        return response(url, b'<bill/>', media='application/xml')
    result = asyncio.run(run_async(archive, [{'url': 'https://example.gov/page.html'}],
        fetch=fetch, initial_only=True, workers=1))
    assert calls == ['https://example.gov/page.html', 'https://example.gov/new.xml']
    assert result['initial_only'] is True
    assert result['attempted'] == 2
    assert result['accounting']['url_outcomes'].get('pending', 0) == 0
    assert all(archive.state[url] == row for url, row in old.items())


def test_targeted_retry_preserves_other_states_and_future_retries():
    store = MemoryStore()
    archive = Archive(store, 'targeted')
    old = {}
    for outcome in ['pending', 'retained', 'saved', 'http_error', 'html', 'size_limit',
                    'empty', 'invalid_document', 'unverified', 'excluded_probe']:
        url = f'https://example.gov/{outcome}.xml'
        archive.seed({'url': url}, publisher_link=True)
        archive.state[url].update(outcome=outcome, next_attempt_at=None)
        old[url] = dict(archive.state[url])
    for outcome in ['retry_later', 'request_failed']:
        for due in [True, False]:
            url = f'https://example.gov/{outcome}-{due}.xml'
            archive.seed({'url': url}, publisher_link=True)
            archive.state[url].update(outcome=outcome,
                next_attempt_at='2020-01-01T00:00:00+00:00' if due else '2099-01-01T00:00:00+00:00')
            if not due:
                old[url] = dict(archive.state[url])
            else:
                # A stale retained response must not turn this recovery into a replay.
                archive.state[url].update(body_key='must-not-replay', links_scanned=False)
    calls = []
    def fetch(url):
        calls.append(url)
        return response(url, b'<a href="https://example.gov/discovered.xml">new</a>', media='text/html')
    result = asyncio.run(run_async(archive, [], fetch=fetch, workers=1,
        retry_outcomes=['retry_later', 'request_failed']))
    assert set(calls) == {'https://example.gov/retry_later-True.xml',
                          'https://example.gov/request_failed-True.xml'}
    assert result['attempted'] == result['fetch'] == 2
    assert result['accounting']['retained_replays_completed'] == 0
    assert result['retry_outcomes'] == ['request_failed', 'retry_later']
    restored = Archive(store, 'check')
    assert all(restored.state[url] == row for url, row in old.items())
    assert restored.state['https://example.gov/discovered.xml']['outcome'] == 'pending'
    assert {r['record']['requested_url'] for r in receipts(store)} == set(calls)


def test_targeted_retry_keeps_delayed_retry_and_attempt_bounds():
    archive = Archive(MemoryStore(), 'retry-selected')
    url = 'https://example.gov/a.zip'
    archive.seed({'url': url}, publisher_link=True)
    archive.state[url].update(outcome='retry_later', next_attempt_at=None)
    result = asyncio.run(run_async(archive, [], fetch=deferred, workers=1,
        retry_outcomes=['retry_later'], limit=2))
    assert result['attempted'] == result['retry_later'] == 2


@pytest.mark.parametrize('options,seeds', [
    ({'retry_outcomes': ['retained']}, []),
    ({'retry_outcomes': ['retry_later'], 'initial_only': True}, []),
    ({'retry_outcomes': ['request_failed']}, [{'url': 'https://example.gov/new.xml'}]),
])
def test_retry_selection_rejects_broader_work_without_writes(options, seeds):
    store = MemoryStore()
    archive = Archive(store, 'bad-retry')
    with pytest.raises(ValueError, match='Retry selection'):
        asyncio.run(run_async(archive, seeds, fetch=lambda _: pytest.fail('must not fetch'), **options))
    assert not store.writes
