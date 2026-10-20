"""I3 publish-last ordering and I4 reader behavior."""
import copy
import json
from uuid import NAMESPACE_URL, uuid5

import pytest

from news_lake.contract import ContractError
from news_lake.storage import (
    CommitError,
    Coordinator,
    CrashInjection,
    Faults,
    ReleaseError,
    publish_release,
    read_release,
    retire_release,
)
from news_lake.storage.releases import find_release


def publish(lake, control, coordinator, batch, release_id, selections, checkpoints,
            recorded_at='2026-10-20T05:00:00Z'):
    return publish_release(coordinator, batch, release_id=release_id, recorded_at=recorded_at,
                           selections=selections, checkpoints=checkpoints)


def test_invalid_batch_publishes_no_release(lake, control, coordinator, batch, second_batch, ids,
                                            selections_a, selections_b, checkpoints_a, checkpoints_b):
    release_a = publish(lake, control, coordinator, batch, ids['release_a'],
                        selections_a, checkpoints_a)
    # Shape-valid, corpus-invalid: a mention naming an entity that does not exist.
    invalid = copy.deepcopy(second_batch)
    invalid_mention = next(r for r in invalid if r['kind'] == 'mention')
    invalid_mention['entity_id'] = '00000000-0000-0000-0000-00000000000f'
    with pytest.raises(ContractError) as raised:
        publish(lake, control, coordinator, invalid, ids['release_b'], selections_b, checkpoints_b)
    assert raised.value.rule == 'missing_reference'

    # The release was never appended; the prior release stays usable; the
    # cursor still names release A.
    assert [r['id'] for r in lake.read_all('news.releases')] == [release_a['id']]
    assert read_release(lake, control, ids['release_a'])['release']['id'] == release_a['id']
    assert control.availability(ids['release_b']) is None
    cursor = control.active_cursor()
    assert all(entry['release_id'] == ids['release_a'] for entry in cursor.values())


def test_abandoned_cycle_unblocks_the_next_release(lake, control, coordinator, batch, second_batch,
                                                    ids, selections_a, selections_b,
                                                    checkpoints_a, checkpoints_b):
    """Remediation for I3's commit-first order: a corpus-invalid candidate
    cycle's rows would block every future release; abandoning the cycle
    restores the baseline pinned by the latest available release (including
    when the failed cycle updated an existing outlet/item from release A or
    replayed an existing capture) and unblocks the next publication."""
    publish(lake, control, coordinator, batch, ids['release_a'], selections_a, checkpoints_a)
    prior_outlet = copy.deepcopy(next(r for r in batch if r['kind'] == 'outlet'))
    mutated_outlet = copy.deepcopy(prior_outlet)
    mutated_outlet['name'] = 'Mutated By Failed Cycle B'
    replayed_capture = copy.deepcopy(next(r for r in batch if r['kind'] == 'capture'))
    invalid = [mutated_outlet, replayed_capture, *copy.deepcopy(second_batch)]
    invalid_mention = next(r for r in invalid if r['kind'] == 'mention')
    invalid_mention['entity_id'] = '00000000-0000-0000-0000-00000000000f'
    with pytest.raises(ContractError):
        publish(lake, control, coordinator, invalid, ids['release_b'], selections_b, checkpoints_b)

    coordinator.abandon_cycle(ids['release_b'])
    # Abandoning is idempotent and terminal: no open cycles, prior release and
    # its upserted/replayed rows are restored intact.
    coordinator.abandon_cycle(ids['release_b'])
    assert control.cycle_state(ids['release_b']) == 'abandoned'
    assert coordinator.recover() == []
    assert read_release(lake, control, ids['release_a'])['release']['id'] == ids['release_a']
    assert lake.read_all('news.outlets') == [prior_outlet]
    assert [r['id'] for r in lake.read_all('news.captures')] == [replayed_capture['id']]

    # Retrying an abandoned release_id is rejected; unknown cycle ids fail cleanly.
    with pytest.raises(ReleaseError) as retry_abandoned:
        publish(lake, control, coordinator, second_batch, ids['release_b'], selections_b, checkpoints_b)
    assert retry_abandoned.value.rule == 'cycle_abandoned'
    with pytest.raises(CommitError) as unknown_cycle:
        coordinator.abandon_cycle('00000000-0000-0000-0000-000000000000')
    assert unknown_cycle.value.rule == 'unknown_cycle'

    # The next valid cycle publishes; the poisoned rows no longer block it.
    release_c = publish(lake, control, coordinator, second_batch,
                        str(uuid5(NAMESPACE_URL, 'news-lake-test:release-c')),
                        selections_b, checkpoints_b)
    assert read_release(lake, control, release_c['id'])['release']['id'] == release_c['id']
    with pytest.raises(CommitError) as released_cycle:
        coordinator.abandon_cycle(ids['release_a'])
    assert released_cycle.value.rule == 'cycle_released'
    with pytest.raises(ReleaseError) as unknown:
        read_release(lake, control, ids['release_b'])
    assert unknown.value.rule == 'unknown_release'


def test_reader_rejects_contract_version_mismatch(lake, control, coordinator, batch, ids,
                                                  selections_a, checkpoints_a, monkeypatch):
    from news_lake.storage import releases as releases_mod

    publish(lake, control, coordinator, batch, ids['release_a'], selections_a, checkpoints_a)
    monkeypatch.setattr(releases_mod, 'CONTRACT_VERSION', '0.2.0')
    with pytest.raises(ReleaseError) as raised:
        read_release(lake, control, ids['release_a'])
    assert raised.value.rule == 'contract_version_mismatch'


def test_candidate_records_are_committed_but_not_released_before_validation(
        lake, control, coordinator, batch, second_batch, ids, selections_a, selections_b,
        checkpoints_a, checkpoints_b):
    """I3 order: candidate commits precede validation; only the release is gated."""
    publish(lake, control, coordinator, batch, ids['release_a'], selections_a, checkpoints_a)
    invalid = copy.deepcopy(second_batch)
    member = next(r for r in invalid if r['kind'] == 'story_member')
    member['run_id'] = next(r['id'] for r in invalid if r['kind'] == 'run' and r['processor'] == 'extract')
    with pytest.raises(ContractError):
        publish(lake, control, coordinator, invalid, ids['release_b'], selections_b, checkpoints_b)
    assert len(lake.read_all('news.items')) == 2  # candidate commits landed
    assert [r['id'] for r in lake.read_all('news.releases')] == [ids['release_a']]


def test_minimal_release_names_empty_tables_explicitly(lake, control, coordinator, batch, ids):
    single_outlet = [copy.deepcopy(batch[0])]
    release = publish(lake, control, coordinator, single_outlet, ids['release_a'], [], [])
    pinned = [entry for entry in release['snapshots'] if 'snapshot_id' in entry]
    assert {entry['table'] for entry in pinned} == {'news.outlets'}
    result = read_release(lake, control, ids['release_a'])
    assert result['tables']['news.outlets'] == single_outlet
    for table, rows in result['tables'].items():
        if table != 'news.outlets':
            assert rows == []  # explicitly empty, never "latest"


def test_reader_rejects_retired_release(lake, control, coordinator, batch, ids, selections_a, checkpoints_a):
    publish(lake, control, coordinator, batch, ids['release_a'], selections_a, checkpoints_a)
    retire_release(control, ids['release_a'])
    with pytest.raises(ReleaseError) as raised:
        read_release(lake, control, ids['release_a'])
    assert raised.value.rule == 'retired_release'


def test_reader_rejects_table_uuid_mismatch(lake, control, coordinator, batch, ids, selections_a, checkpoints_a):
    publish(lake, control, coordinator, batch, ids['release_a'], selections_a, checkpoints_a)
    tampered = copy.deepcopy(lake.read_all('news.releases')[0])
    tampered['id'] = tampered_id = '21212121-2121-5212-8212-212121212121'
    entry = next(e for e in tampered['snapshots'] if e['table'] == 'news.outlets')
    entry['table_uuid'] = '32323232-3232-5323-8323-323232323232'
    coordinator.append_release(tampered)
    control.mark_available(tampered_id)
    with pytest.raises(ReleaseError) as raised:
        read_release(lake, control, tampered_id)
    assert raised.value.rule == 'table_uuid_mismatch'


def test_reader_rejects_missing_snapshot(lake, control, coordinator, batch, ids, selections_a, checkpoints_a):
    publish(lake, control, coordinator, batch, ids['release_a'], selections_a, checkpoints_a)
    ghost = copy.deepcopy(lake.read_all('news.releases')[0])
    ghost['id'] = ghost_id = '42424242-4242-5424-8424-424242424242'
    entry = next(e for e in ghost['snapshots'] if 'snapshot_id' in e)
    entry['snapshot_id'] = str(2 ** 62)  # in int64 range, never created
    coordinator.append_release(ghost)
    control.mark_available(ghost_id)
    with pytest.raises(ReleaseError) as raised:
        read_release(lake, control, ghost_id)
    assert raised.value.rule == 'missing_snapshot'


def test_old_release_stays_readable_after_later_commits(lake, control, coordinator, batch,
                                                        second_batch, ids, selections_a, selections_b,
                                                        checkpoints_a, checkpoints_b):
    publish(lake, control, coordinator, batch, ids['release_a'], selections_a, checkpoints_a)
    publish(lake, control, coordinator, second_batch, ids['release_b'], selections_b, checkpoints_b)
    old = read_release(lake, control, ids['release_a'])
    assert len(old['tables']['news.items']) == 1
    assert len(old['tables']['news.outlets']) == 1
    new = read_release(lake, control, ids['release_b'])
    assert len(new['tables']['news.items']) == 2
    assert len(new['tables']['news.outlets']) == 2


def test_release_pins_exact_validated_snapshots(lake, control, coordinator, batch, ids, selections_a, checkpoints_a):
    release = publish(lake, control, coordinator, batch, ids['release_a'], selections_a, checkpoints_a)
    for entry in release['snapshots']:
        table = lake.table(entry['table'])
        if 'snapshot_id' in entry:
            assert table.current_snapshot().snapshot_id == int(entry['snapshot_id'])
        else:
            assert table.current_snapshot() is None
        assert entry['table_uuid'] == lake.table_uuid(entry['table'])
    assert release['contract_version'] == '0.1.0'


# -- ct-1h4g: availability gating, abandon_cycle, fencing --------------------------


def test_release_appended_but_not_available_is_unreadable_until_recovery(
        lake, control, coordinator, batch, second_batch, ids, selections_a, selections_b,
        checkpoints_a, checkpoints_b):
    publish(lake, control, coordinator, batch, ids['release_a'], selections_a, checkpoints_a)
    crashing = Coordinator(lake, control, writer_id='crashing', faults=Faults(crash_after={'release_append'}))
    with pytest.raises(CrashInjection):
        publish(lake, control, crashing, second_batch, ids['release_b'], selections_b, checkpoints_b)
    assert find_release(lake, ids['release_b']) is not None
    assert control.availability(ids['release_b']) is None
    with pytest.raises(ReleaseError) as raised:
        read_release(lake, control, ids['release_b'])
    assert raised.value.rule == 'unreleased_release'
    # The prior release stays readable and recovery makes the new one available.
    assert read_release(lake, control, ids['release_a'])['release']['id'] == ids['release_a']
    assert Coordinator(lake, control, writer_id='recovery').recover() == [ids['release_b']]
    assert read_release(lake, control, ids['release_b'])['release']['id'] == ids['release_b']


def test_abandon_cycle_refuses_after_the_release_record_is_appended(
        lake, control, coordinator, batch, second_batch, ids, selections_a, selections_b,
        checkpoints_a, checkpoints_b):
    publish(lake, control, coordinator, batch, ids['release_a'], selections_a, checkpoints_a)
    crashing = Coordinator(lake, control, writer_id='crashing', faults=Faults(crash_after={'release_append'}))
    with pytest.raises(CrashInjection):
        publish(lake, control, crashing, second_batch, ids['release_b'], selections_b, checkpoints_b)
    with pytest.raises(CommitError) as raised:
        crashing.abandon_cycle(ids['release_b'])
    assert raised.value.rule == 'cycle_release_appended'
    # The release record was not silently orphaned or deleted.
    assert find_release(lake, ids['release_b']) is not None


def test_abandon_cycle_restores_the_available_baseline_and_discards_staged_checkpoints(
        lake, control, coordinator, batch, second_batch, ids, selections_a, selections_b,
        checkpoints_a, checkpoints_b):
    publish(lake, control, coordinator, batch, ids['release_a'], selections_a, checkpoints_a)
    prior_outlet = copy.deepcopy(next(r for r in batch if r['kind'] == 'outlet'))
    mutated = copy.deepcopy(prior_outlet)
    mutated['name'] = 'Mutated By Failed Cycle B'
    invalid = [mutated, *copy.deepcopy(second_batch)]
    next(r for r in invalid if r['kind'] == 'mention')['entity_id'] = '00000000-0000-0000-0000-00000000000f'
    with pytest.raises(ContractError):
        publish(lake, control, coordinator, invalid, ids['release_b'], selections_b, checkpoints_b)
    assert len(lake.read_all('news.outlets')) == 2  # candidate rows landed

    control.stage_checkpoint(ids['release_b'], {
        'connector_key': 'rss:failed', 'checkpoint_ref': 'urn:cp:failed',
        'completed_until': '2026-10-20T06:00:00Z',
    })
    coordinator.abandon_cycle(ids['release_b'])
    assert control.cycle_state(ids['release_b']) == 'abandoned'
    assert lake.read_all('news.outlets') == [prior_outlet]
    assert control.connection.execute(
        'SELECT * FROM staged_checkpoints WHERE cycle_id = ?', (ids['release_b'],)
    ).fetchall() == []
    assert read_release(lake, control, ids['release_a'])['release']['id'] == ids['release_a']


def test_abandon_cycle_refuses_to_wipe_when_all_releases_are_retired(
        lake, control, coordinator, batch, second_batch, ids, selections_a, selections_b,
        checkpoints_a, checkpoints_b):
    """Retiring the only baseline must not turn abandon_cycle into a full wipe."""
    publish(lake, control, coordinator, batch, ids['release_a'], selections_a, checkpoints_a)
    prior_outlet = copy.deepcopy(next(r for r in batch if r['kind'] == 'outlet'))
    mutated = copy.deepcopy(prior_outlet)
    mutated['name'] = 'Mutated By Failed Cycle B'
    invalid = [mutated, *copy.deepcopy(second_batch)]
    next(r for r in invalid if r['kind'] == 'mention')['entity_id'] = '00000000-0000-0000-0000-00000000000f'
    with pytest.raises(ContractError):
        publish(lake, control, coordinator, invalid, ids['release_b'], selections_b, checkpoints_b)
    retire_release(control, ids['release_a'])

    with pytest.raises(CommitError) as raised:
        coordinator.abandon_cycle(ids['release_b'])
    assert raised.value.rule == 'no_available_baseline'
    # Nothing was wiped: the failed cycle's candidate rows are still evidence.
    assert len(lake.read_all('news.outlets')) == 2

    # Restoring availability lets the same abandon complete against A's pins.
    control.mark_available(ids['release_a'])
    coordinator.abandon_cycle(ids['release_b'])
    assert lake.read_all('news.outlets') == [prior_outlet]


def test_latest_available_release_uses_publication_sequence(
        lake, control, coordinator, batch, second_batch, ids, selections_a, selections_b,
        checkpoints_a, checkpoints_b):
    publish(lake, control, coordinator, batch, ids['release_a'], selections_a, checkpoints_a)
    assert control.latest_available_release() == ids['release_a']
    publish(lake, control, coordinator, second_batch, ids['release_b'], selections_b, checkpoints_b)
    assert control.latest_available_release() == ids['release_b']
    control.mark_available(ids['release_a'])  # re-mark keeps A's original sequence
    assert control.latest_available_release() == ids['release_b']
    retire_release(control, ids['release_b'])
    assert control.latest_available_release() == ids['release_a']


# -- ct-07eg: filtered reads, table subsets, validation cache -----------------------


def test_find_release_uses_a_row_filter_instead_of_a_full_scan(
        lake, control, coordinator, batch, ids, selections_a, checkpoints_a, monkeypatch):
    publish(lake, control, coordinator, batch, ids['release_a'], selections_a, checkpoints_a)

    def full_scan(*args, **kwargs):
        raise AssertionError('find_release must not scan the whole releases table')

    monkeypatch.setattr(lake, 'read_all', full_scan)
    assert find_release(lake, ids['release_a'])['id'] == ids['release_a']
    assert find_release(lake, '00000000-0000-0000-0000-000000000000') is None
    assert read_release(lake, control, ids['release_a'])['release']['id'] == ids['release_a']


def test_read_release_can_restrict_the_pinned_tables(
        lake, control, coordinator, batch, ids, selections_a, checkpoints_a):
    publish(lake, control, coordinator, batch, ids['release_a'], selections_a, checkpoints_a)
    result = read_release(lake, control, ids['release_a'], tables={'news.items'})
    assert set(result['tables']) == {'news.items'}
    assert len(result['tables']['news.items']) == 1
    assert read_release(lake, control, ids['release_a'], tables=set())['tables'] == {}
    with pytest.raises(ReleaseError) as raised:
        read_release(lake, control, ids['release_a'], tables={'news.releases'})
    assert raised.value.rule == 'unknown_table'


def test_second_publish_skips_per_record_validation_for_validated_snapshots(
        lake, control, coordinator, batch, ids, selections_a, checkpoints_a, monkeypatch):
    from news_lake.contract import semantics

    real = semantics.validate_shape
    calls = []

    def counting(record, *args, **kwargs):
        calls.append(record['id'])
        return real(record, *args, **kwargs)

    monkeypatch.setattr(semantics, 'validate_shape', counting)
    publish(lake, control, coordinator, batch, ids['release_a'], selections_a, checkpoints_a)
    first = len(calls)
    assert first == len(batch) + 1  # every candidate record plus the release

    calls.clear()
    release_c = str(uuid5(NAMESPACE_URL, 'news-lake-test:release-c'))
    publish(lake, control, coordinator, batch, release_c, selections_a, checkpoints_a)
    # All pinned snapshots are unchanged and already validated; only the new
    # release record needs per-record shape validation.
    assert calls == [release_c]
    assert len(calls) < first


def test_incremental_publish_skips_prior_append_rows_and_projects_validated_versions(
        lake, control, coordinator, batch, second_batch, ids, selections_a, selections_b,
        checkpoints_a, checkpoints_b, monkeypatch):
    from news_lake.contract import semantics
    from news_lake.storage.releases import _pinned_records

    publish(lake, control, coordinator, batch, ids['release_a'], selections_a, checkpoints_a)

    # 1. Validated version snapshots project only id/FK columns unless a new
    # mention references them.
    release_a = find_release(lake, ids['release_a'])
    pinned, validated_ids, _ = _pinned_records(lake, release_a, control.validated_snapshots())
    v1 = next(r for r in pinned if r['kind'] == 'version')
    assert v1['id'] in validated_ids
    assert 'text' not in v1  # projected out on validated snapshot scan

    # 2. When a new mention in a later cycle references that validated version,
    # its title/text are fetched on demand so span checks still catch errors.
    bad_mention = copy.deepcopy(next(r for r in batch if r['kind'] == 'mention'))
    bad_mention['id'] = '99999999-9999-4999-8999-999999999981'
    bad_mention['surface'] = 'Wrong Surface'
    with pytest.raises(ContractError) as span_err:
        publish(lake, control, coordinator, [bad_mention],
                '99999999-9999-4999-8999-999999999982', selections_a, checkpoints_a)
    assert span_err.value.rule == 'surface_mismatch'
    coordinator.abandon_cycle('99999999-9999-4999-8999-999999999982')

    # 3. Publishing second_batch advances append-only tables, but prior rows
    # from release A's validated snapshots are not re-validated for shape.
    real = semantics.validate_shape
    calls = []

    def counting(record, *args, **kwargs):
        calls.append(record['id'])
        return real(record, *args, **kwargs)

    monkeypatch.setattr(semantics, 'validate_shape', counting)
    publish(lake, control, coordinator, second_batch, ids['release_b'], selections_b, checkpoints_b)
    first_cycle_append_ids = {
        r['id'] for r in batch if r['kind'] not in ('outlet', 'item', 'entity')
    }
    assert first_cycle_append_ids.isdisjoint(calls)


def test_retry_reuses_the_journaled_release_snapshots(
        lake, control, coordinator, batch, second_batch, ids, selections_a, selections_b,
        checkpoints_a, checkpoints_b):
    """ct-1h4g: a retry must not rebuild the release against drifted current snapshots."""
    publish(lake, control, coordinator, batch, ids['release_a'], selections_a, checkpoints_a)
    crashing = Coordinator(lake, control, writer_id='crashing',
                           faults=Faults(crash_before={'checkpoint_stage'}))
    with pytest.raises(CrashInjection):
        publish(lake, control, crashing, second_batch, ids['release_b'], selections_b, checkpoints_b)
    journaled = json.loads(control.cycle(ids['release_b'])['payload'])['release']
    pinned_outlets = next(e['snapshot_id'] for e in journaled['snapshots'] if e['table'] == 'news.outlets')

    later = copy.deepcopy(next(r for r in batch if r['kind'] == 'outlet'))
    later['id'] = '99999999-9999-4999-8999-999999999992'
    later['recorded_at'] = '2026-10-20T09:00:00Z'
    later['name'] = 'Later Current Snapshot'
    crashing.commit([later])
    assert lake.table('news.outlets').current_snapshot().snapshot_id != int(pinned_outlets)

    assert Coordinator(lake, control, writer_id='recovery').recover() == [ids['release_b']]
    recovered = find_release(lake, ids['release_b'])
    assert recovered['snapshots'] == journaled['snapshots']
    assert later['id'] not in {r['id'] for r in read_release(lake, control, ids['release_b'])['tables']['news.outlets']}
