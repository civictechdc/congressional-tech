"""Retained imports separate admission modes without broadening selected URLs."""
import copy
import socket

import pytest

from congress_api.acquisition.retained_import import (
    capture_retained_batch, partition_retained_urls,
)
from congress_api.acquisition.raw_sync import run_sync
from historical_raw_archive import LegacyArchiveSeed as Archive
from test_raw_source_sync import MemoryStore, response
from test_async_capture import receipts


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Retained import tests cannot use the network')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)


def test_separate_mixed_import_preserves_unselected_failures_and_pending():
    store = MemoryStore()
    archive = Archive(store, 'prior')
    urls = {key: f'https://example.gov/{key}.xml'
            for key in ('new', 'pending', 'retry', 'other_failure', 'other_pending')}
    for name in ('pending', 'retry', 'other_failure', 'other_pending'):
        archive.seed({'url': urls[name], 'family': 'documents'})
    for name in ('retry', 'other_failure'):
        archive.state[urls[name]].update(outcome='http_error', next_attempt_at='2099-01-01T00:00:00+00:00')
    archive.save()
    before = copy.deepcopy(archive.state)
    selected = [urls[name] for name in ('new', 'retry', 'pending')]
    initial, retry = partition_retained_urls(archive.state, selected)
    assert initial == [urls['new'], urls['pending']] and retry == [urls['retry']]
    calls = []

    def fetch(url):
        calls.append(url)
        return response(url, b'<document>retained bytes</document>', media='application/xml')

    # The failing production combination still fails before any mutation.
    writes = len(store.writes)
    with pytest.raises(ValueError, match='Retry selection cannot add seeds'):
        run_sync(archive, [{'url': urls['new']}], urls=selected,
                 retry_outcomes={'http_error'}, retry_now=True, fetch=fetch)
    assert len(store.writes) == writes and archive.state == before and not calls
    for number, batch in enumerate((initial, retry)):
        current = Archive(store, f'import-{number}')
        result = capture_retained_batch(current, batch, fetch=fetch,
                                        seed_context={'family': 'documents'})
        assert result['attempted'] == len(batch)
    assert set(calls) == set(selected) and len(calls) == len(selected)
    final = Archive(store, 'read').state
    for name in ('other_failure', 'other_pending'):
        assert final[urls[name]] == before[urls[name]]
    assert all(final[url]['outcome'] == 'saved' for url in selected)
    assert len(receipts(store)) == len(selected)
    assert all(r['download_state']['body_key'] in store.objects for r in receipts(store))


def test_mixed_batch_rejected_before_seeding_or_fetching():
    store = MemoryStore(); archive = Archive(store, 'mixed')
    failed = 'https://example.gov/failed.xml'; new = 'https://example.gov/new.xml'
    archive.seed({'url': failed}); archive.state[failed]['outcome'] = 'request_failed'
    before = copy.deepcopy(archive.state); writes = list(store.writes)
    with pytest.raises(ValueError, match='Separate initial and retry'):
        capture_retained_batch(archive, [new, failed], fetch=lambda _: pytest.fail('No fetch'))
    assert archive.state == before and store.writes == writes


@pytest.mark.parametrize('outcome', ['saved', 'retained', 'excluded_scope', 'excluded_probe'])
def test_successful_or_non_retryable_states_require_explicit_caller_resolution(outcome):
    url = 'https://example.gov/a.xml'
    with pytest.raises(ValueError, match='not new, pending or retryable'):
        partition_retained_urls({url: {'outcome': outcome}}, [url])


@pytest.mark.parametrize('urls', [['x', 'x'], [''], [None]])
def test_invalid_selection_rejected(urls):
    with pytest.raises(ValueError, match='distinct nonempty'):
        partition_retained_urls({}, urls)


def test_selection_options_cannot_override_partition():
    archive = Archive(MemoryStore(), 'options')
    with pytest.raises(ValueError, match='owns selection'):
        capture_retained_batch(archive, ['https://example.gov/a.xml'],
                               retry_now=True, fetch=lambda _: pytest.fail('No fetch'))


def test_empty_batch_requires_explicit_empty_phase():
    with pytest.raises(ValueError, match='empty'):
        capture_retained_batch(Archive(MemoryStore(), 'empty'), [], fetch=lambda _: None)


def test_retained_html_retry_requires_exact_urls_and_preserves_other_html():
    store = MemoryStore()
    archive = Archive(store, 'html-before')
    urls = ['https://example.gov/selected.xml', 'https://example.gov/other.xml']
    run_sync(archive, [{'url': u} for u in urls],
             fetch=lambda u: response(u, b'<html>Previously served HTML</html>',
                                       media='text/html'), limit=2)
    for u in urls:
        archive.state[u]['next_attempt_at'] = '2099-01-01T00:00:00+00:00'
    archive.save()
    prior = copy.deepcopy(archive.state)
    with pytest.raises(ValueError, match='require explicit URLs'):
        run_sync(archive, [], retry_outcomes={'html'}, fetch=lambda _: None)
    assert archive.state == prior
    current = Archive(store, 'html-recovery')
    result = capture_retained_batch(current, [urls[0]],
        fetch=lambda u: response(u, b'<document>Retained XML</document>',
                                 media='application/xml'))
    assert result['attempted'] == 1 and current.state[urls[0]]['outcome'] == 'saved'
    assert current.state[urls[1]] == prior[urls[1]]
    assert prior[urls[0]]['body_key'] in store.objects
