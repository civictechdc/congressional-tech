"""Slice 5 cursor discipline: staged-only-after-commit, no regression, replay."""
import json

import pytest

from news_lake.adapters import FetchOutcome, GdeltAdapter, Page, PageDrain
from news_lake.storage.coordinator import Coordinator, CrashInjection, Faults
from news_lake.storage.releases import publish_release, read_release

T1, T2, T3 = '2026-10-20T02:00:00Z', '2026-10-20T03:00:00Z', '2026-10-20T04:00:00Z'


def gdelt_body(urls):
    return {'articles': [
        {'url': url, 'title': f'Story {index}', 'seendate': '20261019T120000Z', 'domain': url.split('/')[2]}
        for index, url in enumerate(urls)
    ]}


def gdelt_page(capture_id, urls, window_end, context):
    return GdeltAdapter(context).parse_page(
        FetchOutcome(url='https://api.gdeltproject.org/api/v2/doc/doc', status=200,
                     body=json.dumps(gdelt_body(urls)).encode('utf-8'),
                     access='restricted',
                     rights_basis='Synthetic fixture; replace with a reviewed retention policy.',
                     payload_uri=f'urn:fixture:captures:{capture_id}', media_type='application/json'),
        window_end=window_end, capture_id=capture_id)


def frozen_context():
    from datetime import datetime, timezone

    from news_lake.context import AdapterContext

    return AdapterContext(id_source=lambda: 'eeeeeeee-0000-4000-8000-00000000000f',
                          clock=lambda: datetime(2026, 10, 20, 4, 0, 0, tzinfo=timezone.utc))


def page(capture_id, urls, until):
    return gdelt_page(capture_id, urls, until, frozen_context())


# -- unit discipline ---------------------------------------------------------------


def test_checkpoint_advances_only_after_commit_succeeds():
    committed = []

    def commit(records):
        committed.append(records)

    drain = PageDrain('gdelt:doc', commit)
    drain.consume(Page([{'n': 1}], 'urn:test:page:1', T1))
    assert drain.checkpoint() == {'connector_key': 'gdelt:doc', 'checkpoint_ref': 'urn:test:page:1',
                                  'completed_until': T1}

    def failing_commit(records):
        committed.append(records)
        raise RuntimeError('fault mid-page')

    drain = PageDrain('gdelt:doc', failing_commit)
    with pytest.raises(RuntimeError):
        drain.consume(Page([{'n': 2}], 'urn:test:page:2', T2))
    assert drain.checkpoint() is None  # nothing stageable from the failed page


def test_late_arriving_older_page_commits_but_never_regresses_the_cursor():
    committed = []
    drain = PageDrain('gdelt:doc', committed.append)
    drain.consume(Page([{'n': 1}], 'urn:test:page:2', T2))
    drain.consume(Page([{'n': 2}], 'urn:test:page:old', T1))  # late, older window
    assert len(committed) == 2  # evidence still commits
    assert drain.checkpoint() == {'connector_key': 'gdelt:doc', 'checkpoint_ref': 'urn:test:page:2',
                                  'completed_until': T2}


def test_equal_window_and_untimed_pages_never_tear_the_checkpoint():
    """ct-t130: only a strictly advancing timed page may replace a timed
    checkpoint. An equal window or an untimed page still commits its records
    but must not rewrite the timed checkpoint_ref (no hybrid checkpoint)."""
    committed = []
    drain = PageDrain('gdelt:doc', committed.append)
    drain.consume(Page([{'n': 1}], 'urn:test:page:timed', T2))
    drain.consume(Page([{'n': 2}], 'urn:test:page:equal', T2))
    assert drain.checkpoint() == {'connector_key': 'gdelt:doc', 'checkpoint_ref': 'urn:test:page:timed',
                                  'completed_until': T2}
    drain.consume(Page([{'n': 3}], 'urn:test:page:untimed', None))
    assert drain.checkpoint() == {'connector_key': 'gdelt:doc', 'checkpoint_ref': 'urn:test:page:timed',
                                  'completed_until': T2}
    assert len(committed) == 3


def test_drain_seeded_from_the_active_checkpoint_cannot_regress_it():
    """Cross-cycle seeding is optional but must honor the same rule."""
    drain = PageDrain('gdelt:doc', [].append,
                      active_checkpoint={'checkpoint_ref': 'urn:active:newer', 'completed_until': T2})
    drain.consume(Page([{'n': 1}], 'urn:test:page:old', T1))
    assert drain.checkpoint() == {'connector_key': 'gdelt:doc', 'checkpoint_ref': 'urn:active:newer',
                                  'completed_until': T2}
    drain.consume(Page([{'n': 2}], 'urn:test:page:newer', T3))
    assert drain.checkpoint() == {'connector_key': 'gdelt:doc', 'checkpoint_ref': 'urn:test:page:newer',
                                  'completed_until': T3}


def _publish_checkpoint(coordinator, release_id, checkpoint, recorded_at=T3):
    return publish_release(coordinator, [], release_id=release_id, recorded_at=recorded_at,
                           checkpoints=[checkpoint])


def test_backfill_release_does_not_regress_the_published_active_cursor(lake, control, coordinator):
    """ct-t130: an older backfill release still records its own checkpoint but
    leaves the connector's newer active cursor untouched."""
    newer = _publish_checkpoint(coordinator, 'eeeeeeee-0000-4000-8000-0000000000d1',
                                {'connector_key': 'gdelt:doc', 'checkpoint_ref': 'urn:cp:newer',
                                 'completed_until': T3})
    backfill = _publish_checkpoint(coordinator, 'eeeeeeee-0000-4000-8000-0000000000d2',
                                   {'connector_key': 'gdelt:doc', 'checkpoint_ref': 'urn:cp:older',
                                    'completed_until': T1})
    assert control.active_cursor()['gdelt:doc'] == {
        'checkpoint_ref': 'urn:cp:newer', 'completed_until': T3, 'release_id': newer['id'],
    }
    # The release record keeps the backfill's own checkpoint, only the active
    # cursor is monotonic.
    assert read_release(lake, control, backfill['id'])['release']['checkpoints'][0]['completed_until'] == T1
    assert control.latest_available_release() == backfill['id']


def test_untimed_checkpoint_never_replaces_a_timed_active_cursor(lake, control, coordinator):
    _publish_checkpoint(coordinator, 'eeeeeeee-0000-4000-8000-0000000000d3',
                        {'connector_key': 'gdelt:doc', 'checkpoint_ref': 'urn:cp:timed',
                         'completed_until': T3})
    _publish_checkpoint(coordinator, 'eeeeeeee-0000-4000-8000-0000000000d4',
                        {'connector_key': 'gdelt:doc', 'checkpoint_ref': 'urn:cp:untimed'},
                        recorded_at=T3)
    assert control.active_cursor()['gdelt:doc'] == {
        'checkpoint_ref': 'urn:cp:timed', 'completed_until': T3,
        'release_id': 'eeeeeeee-0000-4000-8000-0000000000d3',
    }


def test_overlapping_windows_share_items_not_discoveries(lake, control, coordinator):
    page1 = page('eeeeeeee-0000-4000-8000-0000000000a1',
                 ['https://daily.example/a', 'https://daily.example/b'], T2)
    page2 = page('eeeeeeee-0000-4000-8000-0000000000b2',
                 ['https://daily.example/b', 'https://daily.example/c'], T3)
    coordinator.commit(page1.records)
    coordinator.commit(page2.records)
    items = lake.read_all('news.items')
    discoveries = lake.read_all('news.discoveries')
    assert len(items) == 3  # the overlapping story is one logical item
    assert len(discoveries) == 4  # but two observations of it (C2)
    # Replaying the same captured page commits nothing new.
    coordinator.commit(page1.records)
    assert len(lake.read_all('news.discoveries')) == 4


# -- crash / replay integration ------------------------------------------------------


class SecondDiscoveriesCommitCrash(Faults):
    """Crash after the *second* discoveries commit (page 2's mid-page fault)."""

    def __init__(self):
        super().__init__()
        self.count = 0

    def after(self, point):
        self.fired.append(('after', point))
        if point == 'table_commit:news.discoveries':
            self.count += 1
            if self.count == 2:
                raise CrashInjection(point)


def test_fault_mid_page_leaves_cursor_unmoved_and_replay_converges(lake, control):
    crashing = Coordinator(lake, control, faults=SecondDiscoveriesCommitCrash())
    page1 = page('eeeeeeee-0000-4000-8000-0000000000a1', ['https://daily.example/a'], T2)
    page2 = page('eeeeeeee-0000-4000-8000-0000000000b2', ['https://daily.example/b'], T3)
    drain = PageDrain('gdelt:doc', crashing.commit)
    drain.consume(page1)
    with pytest.raises(CrashInjection):
        drain.consume(page2)
    assert control.active_cursor() == {}  # cursor only moves at publication
    staged = drain.checkpoint()
    assert staged['completed_until'] == T2  # the failed page's checkpoint never staged

    # Replay the whole drain with a healthy coordinator (same capture ids), then publish.
    healthy = Coordinator(lake, control)
    drain2 = PageDrain('gdelt:doc', healthy.commit)
    drain2.consume(page1)
    drain2.consume(page2)
    publish_release(healthy, [], release_id='eeeeeeee-0000-4000-8000-000000000e11',
                    recorded_at=T3, checkpoints=[drain2.checkpoint()])
    cursor = control.active_cursor()
    assert cursor['gdelt:doc']['completed_until'] == T3
    assert len(lake.read_all('news.discoveries')) == 2  # no duplicates from the partial commit
    assert len(lake.read_all('news.items')) == 2
    read_release(lake, control, 'eeeeeeee-0000-4000-8000-000000000e11')  # pinned read works


def test_crash_during_publication_recovers_and_advances_the_cursor(lake, control):
    faults = Faults(crash_before={'cursor_advance'})
    crashing = Coordinator(lake, control, faults=faults)
    drain = PageDrain('gdelt:doc', crashing.commit)
    drain.consume(page('eeeeeeee-0000-4000-8000-0000000000a1', ['https://daily.example/a'], T2))
    drain.consume(page('eeeeeeee-0000-4000-8000-0000000000b2', ['https://daily.example/b'], T3))
    with pytest.raises(CrashInjection):
        publish_release(crashing, [], release_id='eeeeeeee-0000-4000-8000-000000000e12',
                        recorded_at=T3, checkpoints=[drain.checkpoint()])
    assert control.active_cursor() == {}  # unreleased: cursor unmoved
    recovered = Coordinator(lake, control).recover()
    assert recovered == ['eeeeeeee-0000-4000-8000-000000000e12']
    assert control.active_cursor()['gdelt:doc']['completed_until'] == T3


def test_quota_error_page_commits_evidence_without_advancing(lake, control, coordinator):
    from datetime import datetime, timezone

    from news_lake.context import AdapterContext

    context = AdapterContext(id_source=lambda: 'eeeeeeee-0000-4000-8000-00000000000f',
                             clock=lambda: datetime(2026, 10, 20, 4, 0, 0, tzinfo=timezone.utc))
    quota = GdeltAdapter(context).parse_page(
        FetchOutcome(url='https://api.gdeltproject.org/api/v2/doc/doc', status=429,
                     outcome='failed', error_code='provider_quota_exceeded'),
        window_end=T3, capture_id='eeeeeeee-0000-4000-8000-0000000000a4')
    drain = PageDrain('gdelt:doc', coordinator.commit)
    drain.consume(quota)
    assert drain.checkpoint() is None  # nothing stageable
    publish_release(coordinator, [], release_id='eeeeeeee-0000-4000-8000-000000000e13',
                    recorded_at=T3, checkpoints=[])
    assert control.active_cursor() == {}
    captures = lake.read_all('news.captures')
    assert [c['error_code'] for c in captures] == ['provider_quota_exceeded']
