"""Crash recovery (I2): every fault point -> prior release usable -> converge.

The interrupted warehouse must end content-identical to an uninterrupted run
of the same two cycles. Snapshot ids are allowed to differ; records, release
sets, table UUIDs, cursor and availability must not.
"""
import copy

import pytest

from news_lake.storage import Coordinator, CrashInjection, Faults, publish_release, read_release
from news_lake_test_support import logical_state
from news_lake.contract.records import CONTENT_TABLES

# second_batch touches every non-release table, so every table point fires.
POINTS = [('before', 'journal_write'), ('after', 'journal_write')]
POINTS += [(phase, f'table_commit:{table}') for table in CONTENT_TABLES for phase in ('before', 'after')]
POINTS += [(phase, point) for point in ('checkpoint_stage', 'release_append', 'cursor_advance')
           for phase in ('before', 'after')]

UPSERT_TABLES = ('news.outlets', 'news.items', 'news.entities')
UPSERT_POINTS = [(phase, f'upsert_replace:{table}') for table in UPSERT_TABLES
                 for phase in ('before', 'after')]


def publish_a(coordinator, batch, ids, selections_a, checkpoints_a):
    return publish_release(coordinator, batch, release_id=ids['release_a'],
                           recorded_at='2026-10-20T05:00:00Z',
                           selections=selections_a, checkpoints=checkpoints_a)


def publish_b(coordinator, second_batch, ids, selections_b, checkpoints_b):
    return publish_release(coordinator, second_batch, release_id=ids['release_b'],
                           recorded_at='2026-10-20T07:00:00Z',
                           selections=selections_b, checkpoints=checkpoints_b)


@pytest.fixture(scope='module')
def reference_state(tmp_path_factory, batch, second_batch, ids, selections_a, selections_b,
                    checkpoints_a, checkpoints_b):
    from news_lake.storage.catalog import Lake
    from news_lake.storage.control import ControlStore

    root = tmp_path_factory.mktemp('reference')
    lake = Lake(root / 'lake').create_tables()
    control = ControlStore(root / 'lake' / 'control.db')
    coordinator = Coordinator(lake, control)
    publish_a(coordinator, batch, ids, selections_a, checkpoints_a)
    publish_b(coordinator, second_batch, ids, selections_b, checkpoints_b)
    release_ids = (ids['release_a'], ids['release_b'])
    pinned_b = {table: rows for table, rows in read_release(lake, control, ids['release_b'])['tables'].items()}
    return logical_state(lake, control, release_ids), pinned_b, release_ids


@pytest.mark.parametrize('phase,point', POINTS)
def test_crash_at_every_point_converges(tmp_path, batch, second_batch, ids, selections_a, selections_b,
                                        checkpoints_a, checkpoints_b, reference_state, phase, point):
    expected, pinned_b_expected, release_ids = reference_state
    from news_lake.storage.catalog import Lake
    from news_lake.storage.control import ControlStore

    root = tmp_path
    lake = Lake(root / 'lake').create_tables()
    control = ControlStore(root / 'lake' / 'control.db')
    coordinator = Coordinator(lake, control)
    publish_a(coordinator, batch, ids, selections_a, checkpoints_a)

    faults = Faults(crash_after={point} if phase == 'after' else set(),
                    crash_before={point} if phase == 'before' else set())
    interrupted = Coordinator(lake, control, writer_id='crashed-writer', faults=faults)
    with pytest.raises(CrashInjection) as raised:
        publish_b(interrupted, second_batch, ids, selections_b, checkpoints_b)
    assert raised.value.point == point or raised.value.point.startswith(point + ':')

    # The prior release stays readable at every interruption point.
    still = read_release(lake, control, ids['release_a'])
    assert any(still['tables'].values())

    # Recovery converges; unjournaled intent (crash before the journal write)
    # is re-submitted by the caller, exactly as an acquisition loop would.
    recovered = Coordinator(lake, control, writer_id='recovery-writer').recover()
    if (phase, point) == ('before', 'journal_write'):
        assert recovered == []
        publish_b(Coordinator(lake, control, writer_id='resubmitted'), second_batch, ids,
                  selections_b, checkpoints_b)
    else:
        assert recovered == [ids['release_b']]
        assert control.cycle_state(ids['release_b']) == 'done'

    assert logical_state(lake, control, release_ids) == expected
    pinned_b = read_release(lake, control, ids['release_b'])['tables']
    assert pinned_b == pinned_b_expected


def test_recover_on_a_clean_warehouse_is_a_noop(lake, control, coordinator):
    assert coordinator.recover() == []


def test_replay_of_a_done_cycle_is_idempotent(lake, control, coordinator, batch, second_batch, ids,
                                              selections_a, checkpoints_a):
    publish_a(coordinator, batch, ids, selections_a, checkpoints_a)
    again = publish_a(coordinator, batch, ids, selections_a, checkpoints_a)
    assert again['id'] == ids['release_a']
    assert len(lake.read_all('news.releases')) == 1


def upsert_updates(batch):
    """A second poll that updates the existing outlet/item/entity ids."""
    at = '2026-10-20T06:00:00Z'
    outlet = copy.deepcopy(next(r for r in batch if r['kind'] == 'outlet'))
    outlet['recorded_at'] = at
    outlet['name'] = 'Renamed Example Local News'
    outlet['domains'] = outlet['domains'] + ['late.example']
    outlet['feed_urls'] = outlet['feed_urls'] + ['https://late.example/feed.xml']
    item = copy.deepcopy(next(r for r in batch if r['kind'] == 'item'))
    item['recorded_at'] = at
    item['url_aliases'] = item['url_aliases'] + ['https://local.example/late']
    item['content_type'] = 'press_release'
    item['first_seen_at'] = at  # later poll must not regress the earlier first_seen_at
    entity = copy.deepcopy(next(r for r in batch if r['kind'] == 'entity' and 'tenures' in r))
    entity['recorded_at'] = at
    entity['name'] = 'Alex D. Doe'
    entity['aliases'] = entity['aliases'] + [{'value': 'A. D. Doe', 'language': 'en'}]
    entity['identifiers'] = entity['identifiers'] + [{'scheme': 'fixture', 'value': 'person-late'}]
    entity['tenures'] = entity['tenures'] + [{
        'office': 'Mayor', 'jurisdiction': 'Example City', 'from': '2026-01-01',
    }]
    return [outlet, item, entity]


@pytest.fixture(scope='module')
def upsert_reference_state(tmp_path_factory, batch, ids, selections_a, selections_b,
                           checkpoints_a, checkpoints_b):
    from news_lake.storage.catalog import Lake
    from news_lake.storage.control import ControlStore

    root = tmp_path_factory.mktemp('upsert-reference')
    lake = Lake(root / 'lake').create_tables()
    control = ControlStore(root / 'lake' / 'control.db')
    coordinator = Coordinator(lake, control)
    publish_a(coordinator, batch, ids, selections_a, checkpoints_a)
    publish_b(coordinator, upsert_updates(batch), ids, selections_b, checkpoints_b)
    return logical_state(lake, control, (ids['release_a'], ids['release_b']))


@pytest.mark.parametrize('phase,point', UPSERT_POINTS)
def test_crash_during_atomic_upsert_preserves_prior_evidence(
        tmp_path, batch, ids, selections_a, selections_b, checkpoints_a, checkpoints_b,
        upsert_reference_state, phase, point):
    """A crash around the delete+append transaction must never expose a
    row-absent state: recovery replays the merged replacement, so all earlier
    list evidence, the earliest first_seen_at, and the newer scalars survive."""
    from news_lake.storage.catalog import Lake
    from news_lake.storage.control import ControlStore

    root = tmp_path
    lake = Lake(root / 'lake').create_tables()
    control = ControlStore(root / 'lake' / 'control.db')
    coordinator = Coordinator(lake, control)
    publish_a(coordinator, batch, ids, selections_a, checkpoints_a)

    faults = Faults(crash_after={point} if phase == 'after' else set(),
                    crash_before={point} if phase == 'before' else set())
    interrupted = Coordinator(lake, control, writer_id='crashed-writer', faults=faults)
    with pytest.raises(CrashInjection) as raised:
        publish_b(interrupted, upsert_updates(batch), ids, selections_b, checkpoints_b)
    assert raised.value.point == point

    # The prior release is still readable, whether or not the upsert landed.
    assert read_release(lake, control, ids['release_a'])['release']['id'] == ids['release_a']

    recovered = Coordinator(lake, control, writer_id='recovery-writer').recover()
    assert recovered == [ids['release_b']]

    original = {r['kind']: r for r in batch}
    original_entity = next(r for r in batch if r['kind'] == 'entity' and 'tenures' in r)
    outlet = next(r for r in lake.read_all('news.outlets') if r['id'] == original['outlet']['id'])
    assert outlet['name'] == 'Renamed Example Local News'
    assert outlet['domains'] == original['outlet']['domains'] + ['late.example']
    assert outlet['feed_urls'] == original['outlet']['feed_urls'] + ['https://late.example/feed.xml']

    item = next(r for r in lake.read_all('news.items') if r['id'] == original['item']['id'])
    assert item['content_type'] == 'press_release'
    assert item['url_aliases'] == original['item']['url_aliases'] + ['https://local.example/late']
    assert item['first_seen_at'] == original['item']['first_seen_at']

    entity = next(r for r in lake.read_all('news.entities') if r['id'] == original_entity['id'])
    assert entity['name'] == 'Alex D. Doe'
    assert entity['aliases'] == original_entity['aliases'] + [{'value': 'A. D. Doe', 'language': 'en'}]
    assert entity['identifiers'] == original_entity['identifiers'] + [
        {'scheme': 'fixture', 'value': 'person-late'}
    ]
    assert entity['tenures'] == original_entity['tenures'] + [{
        'office': 'Mayor', 'jurisdiction': 'Example City', 'from': '2026-01-01',
    }]

    # Full logical convergence with an uninterrupted run, not just spot checks.
    assert logical_state(lake, control, (ids['release_a'], ids['release_b'])) == upsert_reference_state


def test_late_older_poll_keeps_newer_scalars_and_unions_older_evidence(
        lake, control, coordinator, batch, ids, selections_a, checkpoints_a):
    """ct-upl1: an out-of-order older poll is evidence, not a regression."""
    coordinator.commit(batch)
    original = {r['kind']: r for r in batch}
    at_new, at_old = '2026-10-20T08:00:00Z', '2026-10-20T06:00:00Z'

    newer_outlet = copy.deepcopy(original['outlet'])
    newer_outlet.update(recorded_at=at_new, name='Newest Name', domains=['newest.example'])
    older_outlet = copy.deepcopy(original['outlet'])
    older_outlet.update(recorded_at=at_old, name='Older Name', domains=['older.example'])

    newer_entity = copy.deepcopy(original['entity'])
    newer_entity.update(recorded_at=at_new, name='Alex New',
                        aliases=[{'value': 'A. New', 'language': 'en'}])
    older_entity = copy.deepcopy(original['entity'])
    older_entity.update(recorded_at=at_old, name='Alex Old',
                        aliases=[{'value': 'A. Old', 'language': 'en'}])

    new_version = copy.deepcopy(next(r for r in batch if r['kind'] == 'version'))
    new_version['id'] = '99999999-9999-4999-8999-999999999993'
    new_version['recorded_at'] = at_new
    newer_item = copy.deepcopy(original['item'])
    newer_item.update(recorded_at=at_new, content_type='press_release',
                      current_version_id=new_version['id'],
                      url_aliases=['https://local.example/newest'])
    older_item = copy.deepcopy(original['item'])
    older_item.update(recorded_at=at_old, content_type='unknown',
                      current_version_id=original['item']['current_version_id'],
                      url_aliases=['https://local.example/older'],
                      first_seen_at=at_old)

    coordinator.commit([newer_outlet, newer_item, newer_entity, new_version])
    coordinator.commit([older_outlet, older_item, older_entity])

    outlet = next(r for r in lake.read_all('news.outlets') if r['id'] == original['outlet']['id'])
    assert outlet['name'] == 'Newest Name'
    assert outlet['recorded_at'] == at_new
    assert outlet['domains'] == original['outlet']['domains'] + ['newest.example', 'older.example']

    item = next(r for r in lake.read_all('news.items') if r['id'] == original['item']['id'])
    assert item['content_type'] == 'press_release'
    assert item['current_version_id'] == new_version['id']
    assert item['recorded_at'] == at_new
    assert item['first_seen_at'] == original['item']['first_seen_at']
    assert item['url_aliases'] == original['item']['url_aliases'] + [
        'https://local.example/newest', 'https://local.example/older',
    ]

    entity = next(r for r in lake.read_all('news.entities') if r['id'] == original['entity']['id'])
    assert entity['name'] == 'Alex New'
    assert entity['recorded_at'] == at_new
    assert entity['aliases'] == original['entity']['aliases'] + [
        {'value': 'A. New', 'language': 'en'}, {'value': 'A. Old', 'language': 'en'},
    ]
