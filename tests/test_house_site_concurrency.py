"""Cross-site latency must not compromise receipts, ordering, or resume state."""
from copy import deepcopy
from datetime import date
import threading
from urllib.parse import urlsplit

import pytest

from congress_api.acquisition import house_sites
from congress_api.parsers.committee_discovery import key, task
from congress_api.retention.tables import read_state, write_state
from test_house_sites import client, DIRECTORY

TODAY = date(2026, 10, 7)
BODY = b'<h1>Hearing</h1><p>Date: January 1, 2001</p><a href="/one.pdf">Testimony</a>'


def inputs(sites=3, pages=4):
    rows, state, bodies = [], {}, {}
    for i in range(sites):
        home = f'https://site{i}.house.gov/'
        rows.append({**DIRECTORY[0], 'detail': {'committeeWebsiteUrl': home}})
        tasks = [task(home + f'events/{n}', 'event') for n in range(pages)]
        state[urlsplit(home).hostname] = dict(pages={}, sources={}, done={}, errors={}, pending=tasks)
        bodies.update({item['url']: BODY for item in tasks})
    return rows, state, bodies


def test_default_fetching_overlaps_sites_without_overlapping_one_committee():
    rows, state, bodies = inputs()
    fetch, calls = client(bodies)
    barrier = threading.Barrier(3)
    lock = threading.Lock()
    active, peak, seen = set(), [], set()

    def get(url, receipts, **kw):
        host = urlsplit(url).hostname
        with lock:
            assert host not in active
            active.add(host)
            peak.append(len(active))
            first = host not in seen
            seen.add(host)
        if first:
            barrier.wait(timeout=3)
        try:
            return fetch(url, receipts, **kw)
        finally:
            with lock:
                active.remove(host)

    result = house_sites.collect(rows, state, today=TODAY, get=get)
    assert max(peak) == 3 and result['requests'] == 12 and not result['pending']
    for host in state:
        assert [u.rsplit('/', 1)[-1] for u, _ in calls if urlsplit(u).hostname == host] == ['0', '1', '2', '3']


def test_checkpoint_keeps_slow_inflight_request_pending_while_other_site_advances(tmp_path):
    rows, state, bodies = inputs(sites=2, pages=30)
    release = threading.Event()
    fetch, calls = client(bodies)
    slow = state['site0.house.gov']['pending'][0]
    coordinator = threading.get_ident()
    snapshots = []

    def get(url, receipts, **kw):
        if url == slow['url']:
            assert release.wait(5), 'A slow committee blocked checkpointing the other committee'
        return fetch(url, receipts, **kw)

    def checkpoint(value):
        assert threading.get_ident() == coordinator
        path = tmp_path / 'state.json.gz'
        write_state(path, value)
        snapshots.append(read_state(path))
        release.set()

    result = house_sites.collect(rows, state, today=TODAY, get=get, workers=2,
                                 limit=30, checkpoint=checkpoint)
    first = snapshots[0]['site0.house.gov']
    assert slow in first['pending'] and key(slow) not in first['done']
    assert key(slow) not in first['sources']  # Workers cannot publish partial receipts.
    assert result['requests'] == len(calls) == 30
    assert result['pending'] == 30


def test_serial_and_parallel_runs_keep_identical_bodies_receipts_and_exports(tmp_path, monkeypatch):
    rows, original, bodies = inputs()
    monkeypatch.setattr(house_sites, 'timestamp', lambda: '2026-10-07T00:00:00Z')
    bodies['https://site1.house.gov/events/1'] = RuntimeError('retained failure')
    results, states = [], []
    for workers in (1, 4):
        state = deepcopy(original)
        get, _ = client(bodies)
        results.append(house_sites.collect(rows, state, today=TODAY, get=get, workers=workers))
        states.append(state)
        house_sites.outputs(state, tmp_path / str(workers))
    assert results[0] == results[1] and states[0] == states[1]
    for name in ('house_site_events.csv', 'house_site_documents.csv', 'house_site_coverage.csv'):
        assert (tmp_path / '1' / name).read_bytes() == (tmp_path / '4' / name).read_bytes()


@pytest.mark.parametrize('limit', [0, 1, 3, 7])
def test_request_limit_includes_all_admitted_work_and_resume_does_not_repeat_it(limit):
    rows, state, bodies = inputs()
    get, calls = client(bodies)
    result = house_sites.collect(rows, state, today=TODAY, get=get, workers=4, limit=limit)
    assert result['requests'] == len(calls) == limit
    assert result['pending'] == 12 - limit
    house_sites.collect(rows, state, today=TODAY, get=get, workers=4)
    assert len(calls) == len({u for u, _ in calls}) == 12


def test_stop_drains_admitted_responses_then_checkpoints_without_starting_more():
    rows, state, bodies = inputs()
    stop = threading.Event()
    get, calls = client(bodies)
    snapshots = []

    def stopping_get(*args, **kwargs):
        response = get(*args, **kwargs)
        stop.set()
        return response

    result = house_sites.collect(rows, state, today=TODAY, get=stopping_get, workers=3,
                                 stop=stop, checkpoint=lambda s: snapshots.append(deepcopy(s)))
    assert 1 <= len(calls) <= 3
    assert result['requests'] == len(calls) and result['pending'] == 12 - len(calls)
    assert snapshots[-1] == state
    for url, _ in calls:
        saved = state[urlsplit(url).hostname]
        assert key(task(url, 'event')) in saved['done']
        assert saved['sources'][key(task(url, 'event'))]['receipts']
    house_sites.collect(rows, state, today=TODAY, get=get, workers=3)
    assert len(calls) == len({u for u, _ in calls}) == 12


def test_unexpected_worker_exception_remains_pending_and_other_receipts_are_saved():
    rows, state, bodies = inputs()
    fetch, _ = client(bodies)
    barrier = threading.Barrier(3)
    snapshots = []
    bad = state['site0.house.gov']['pending'][0]

    def get(url, receipts, **kw):
        if url.endswith('/0'):
            barrier.wait(timeout=3)
        if url == bad['url']:
            raise TypeError('unexpected transport bug')
        return fetch(url, receipts, **kw)

    with pytest.raises(TypeError, match='unexpected transport bug'):
        house_sites.collect(rows, state, today=TODAY, get=get, workers=3,
                            checkpoint=lambda s: snapshots.append(deepcopy(s)))
    assert bad in snapshots[-1]['site0.house.gov']['pending']
    assert key(bad) not in snapshots[-1]['site0.house.gov']['done']
    for host in ('site1.house.gov', 'site2.house.gov'):
        assert snapshots[-1][host]['sources'][key(task(f'https://{host}/events/0', 'event'))]['receipts']


@pytest.mark.parametrize('workers', [0, -1, 33])
def test_worker_bounds_reject_invalid_configuration_before_fetch(workers):
    rows, state, bodies = inputs()
    get, calls = client(bodies)
    with pytest.raises(ValueError, match='workers'):
        house_sites.collect(rows, state, today=TODAY, get=get, workers=workers)
    assert not calls


def test_cli_signal_requests_drain_and_restores_handlers(monkeypatch, tmp_path):
    import signal
    from congress_api.cli import house_sites as cli
    before = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}

    def run(**kwargs):
        assert kwargs['workers'] == 3 and not kwargs['stop'].is_set()
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        assert kwargs['stop'].is_set()

    monkeypatch.setattr(cli, 'main', run)
    with pytest.raises(SystemExit, match='2'):
        cli.parse_args_and_run(['--committees', str(tmp_path / 'committees'), '--state-dir', str(tmp_path),
                               '--output-dir', str(tmp_path), '--workers', '3'])
    assert {sig: signal.getsignal(sig) for sig in before} == before


def test_fast_checkpoint_compression_preserves_decoded_state_and_legacy_default(tmp_path):
    import gzip
    import json
    state = {'body': 'retained page bytes ' * 10000, 'pending': [task('https://site.house.gov/events/1')]}
    default, faster = tmp_path / 'default.gz', tmp_path / 'faster.gz'
    write_state(default, state)
    write_state(faster, state, compresslevel=3)
    expected = json.dumps(state, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    assert default.read_bytes() == gzip.compress(expected, mtime=0)
    assert gzip.decompress(faster.read_bytes()) == expected
    assert read_state(default) == read_state(faster) == state


def test_main_passes_worker_bound_and_exports_a_requested_stop_with_retained_errors(tmp_path, monkeypatch):
    import gzip
    import json
    stop = threading.Event()
    directory = tmp_path / 'committees.jsonl.gz'
    directory.write_bytes(gzip.compress((json.dumps(DIRECTORY[0]) + '\n').encode()))
    levels = []
    writer = house_sites.write_state

    def write(path, value, **kwargs):
        levels.append(kwargs['compresslevel'])
        writer(path, value, **kwargs)

    def collect(rows, state, *, workers, stop, checkpoint, **kwargs):
        assert workers == 3
        stop.set()
        checkpoint(state)
        return {'requests': 0, 'pending': 1, 'failed': 1, 'stopped': True}

    monkeypatch.setattr(house_sites, 'collect', collect)
    monkeypatch.setattr(house_sites, 'write_state', write)
    result = house_sites.main(directory, tmp_path, tmp_path, workers=3, stop=stop)
    assert result['stopped'] and levels == [3]
    assert (tmp_path / 'house_site_documents.csv').exists()
