"""I2 replay semantics: dedup, append collisions, upsert replacement, fencing."""
import copy

import pytest

from news_lake.contract.records import CONTENT_TABLES, TABLE_KINDS
from news_lake.storage import CommitError, Coordinator, Faults, FencedError


def test_replay_twice_creates_no_duplicate_rows(lake, coordinator, batch):
    coordinator.commit(batch)
    coordinator.commit(batch)
    per_table = {}
    for record in batch:
        per_table[record['kind']] = per_table.get(record['kind'], 0) + 1
    for table in CONTENT_TABLES:
        stored = lake.read_all(table)
        expected = per_table.get(TABLE_KINDS[table], 0)
        assert len(stored) == expected, table


def test_replayed_release_record_is_a_noop(lake, coordinator, fixture_records):
    release = fixture_records[-1]
    coordinator.append_release(release)
    coordinator.append_release(release)
    assert len(lake.read_all('news.releases')) == 1


def test_mutated_value_on_append_table_fails(lake, coordinator, batch):
    coordinator.commit(batch)
    capture = copy.deepcopy(next(r for r in batch if r['kind'] == 'capture'))
    capture['http_status'] = 500
    with pytest.raises(CommitError) as raised:
        coordinator.commit([capture])
    assert raised.value.rule == 'append_collision'
    assert raised.value.record_id == capture['id']
    assert lake.read_all('news.captures')[0]['http_status'] == 200


def test_mutated_release_reappend_fails(lake, coordinator, fixture_records):
    coordinator.append_release(fixture_records[-1])
    mutated = copy.deepcopy(fixture_records[-1])
    mutated['selections'] = []
    with pytest.raises(CommitError) as raised:
        coordinator.append_release(mutated)
    assert raised.value.rule == 'append_collision'


def test_same_id_different_values_within_one_batch_fails(lake, coordinator, batch):
    outlet = copy.deepcopy(batch[0])
    clone = dict(outlet)
    clone['name'] = 'Different Name'
    with pytest.raises(CommitError) as raised:
        coordinator.commit([outlet, clone])
    assert raised.value.rule == 'batch_id_collision'
    assert lake.read_all('news.outlets') == []


def test_identical_duplicate_within_one_batch_collapses(lake, coordinator, batch):
    coordinator.commit([batch[0], copy.deepcopy(batch[0])])
    assert len(lake.read_all('news.outlets')) == 1


@pytest.mark.parametrize('kind', ['outlet', 'item', 'entity'])
def test_upsert_tables_merge_by_id(lake, coordinator, batch, kind):
    """Upsert replaces scalar values but unions list evidence (C1)."""
    coordinator.commit(batch)
    record = copy.deepcopy(next(r for r in batch if r['kind'] == kind))
    table = {'outlet': 'news.outlets', 'item': 'news.items', 'entity': 'news.entities'}[kind]
    before = len(lake.read_all(table))
    if kind == 'outlet':
        record['name'] = 'Renamed Outlet'
        record['domains'].append('renamed.example')
    elif kind == 'item':
        record['url_aliases'] = ['https://renamed.example/alt']
    else:
        record['name'] = 'Renamed Person'
        record['aliases'].append({'value': 'The Renamed', 'language': 'en'})
    coordinator.commit([record])
    stored = lake.read_all(table)
    assert len(stored) == before
    merged = next(r for r in stored if r['id'] == record['id'])
    if kind == 'outlet':
        assert merged['name'] == 'Renamed Outlet'
        assert set(merged['domains']) == set(batch[0]['domains']) | {'renamed.example'}
    elif kind == 'item':
        prior_aliases = next(r for r in batch if r['kind'] == 'item')['url_aliases']
        assert merged['url_aliases'] == prior_aliases + ['https://renamed.example/alt']
    else:
        assert merged['name'] == 'Renamed Person'
        prior_names = {a['value'] for a in next(r for r in batch if r['kind'] == 'entity')['aliases']}
        assert {a['value'] for a in merged['aliases']} == prior_names | {'The Renamed'}


def test_upsert_merge_preserves_alias_evidence_across_polls(lake, coordinator, batch):
    """C1 regression: a later poll lacking earlier redirect evidence must not
    erase the aliases the earlier poll recorded (review finding: replace lost)."""
    coordinator.commit(batch)
    item = copy.deepcopy(next(r for r in batch if r['kind'] == 'item'))
    poll1 = copy.deepcopy(item)
    poll1['url_aliases'] = ['https://first.example/alt']
    coordinator.commit([poll1])
    snap_after_poll1 = lake.table('news.items').current_snapshot().snapshot_id
    poll2 = copy.deepcopy(item)
    poll2['url_aliases'] = []  # this poll's response carries no alias evidence
    coordinator.commit([poll2])
    stored = next(r for r in lake.read_all('news.items') if r['id'] == item['id'])
    assert stored['url_aliases'] == ['https://first.example/alt']
    # When the merged record equals the stored prior, no redundant snapshot is written.
    assert lake.table('news.items').current_snapshot().snapshot_id == snap_after_poll1


def test_upsert_merge_validates_merged_shape(lake, coordinator, batch):
    """An upsert whose merged state violates the schema (e.g. changing a person
    with tenures into an organization) is rejected before touching Iceberg."""
    from news_lake.contract import ContractError

    coordinator.commit(batch)
    person = copy.deepcopy(next(r for r in batch if r['kind'] == 'entity' and 'tenures' in r))
    as_org = copy.deepcopy(person)
    as_org['entity_type'] = 'organization'
    as_org.pop('tenures', None)
    as_org.pop('affiliations', None)
    with pytest.raises(ContractError):
        coordinator.commit([as_org])


def test_upsert_keeps_the_earlier_first_seen_at(lake, coordinator, batch):
    coordinator.commit(batch)
    item = copy.deepcopy(next(r for r in batch if r['kind'] == 'item'))
    item['first_seen_at'] = '2026-10-21T04:00:00Z'  # a later poll's timestamp
    coordinator.commit([item])
    stored = next(r for r in lake.read_all('news.items') if r['id'] == item['id'])
    assert stored['first_seen_at'] == next(r for r in batch if r['kind'] == 'item')['first_seen_at']


def test_replay_of_trailing_zero_instants_dedups(lake, coordinator, batch, fixture_records):
    """I2 regression: schema-valid instants with trailing-zero fractions
    (both top-level and nested in publication.at / checkpoints[].completed_until)
    normalize on export; a replay must still be recognized as the same record
    (review finding: append_collision on legitimate replays)."""
    capture = copy.deepcopy(next(r for r in batch if r['kind'] == 'capture'))
    capture['id'] = '99999999-9999-4999-8999-999999999999'
    capture['recorded_at'] = '2026-10-20T04:00:00.123000Z'
    capture['observed_at'] = '2026-10-20T04:00:00.500000Z'
    discovery = copy.deepcopy(next(r for r in batch if r['kind'] == 'discovery'))
    discovery['id'] = '99999999-9999-4999-8999-999999999998'
    discovery['capture_id'] = capture['id']
    discovery['reported_publication'] = {
        'precision': 'instant', 'at': '2026-10-19T18:00:00.250000Z', 'basis': 'provider'
    }
    version = copy.deepcopy(next(r for r in batch if r['kind'] == 'version'))
    version['id'] = '99999999-9999-4999-8999-999999999997'
    version['publication'] = {
        'precision': 'instant', 'at': '2026-10-19T18:00:00.750000Z', 'basis': 'publisher'
    }
    coordinator.commit([capture, discovery, version])
    coordinator.commit([capture, discovery, version])  # must be a no-op, not append_collision
    stored = [r for r in lake.read_all('news.captures') if r['id'] == capture['id']]
    assert len(stored) == 1
    assert stored[0]['recorded_at'] == '2026-10-20T04:00:00.123Z'  # canonical on read
    stored_version = next(r for r in lake.read_all('news.versions') if r['id'] == version['id'])
    assert stored_version['publication']['at'] == '2026-10-19T18:00:00.75Z'

    release = copy.deepcopy(fixture_records[-1])
    release['id'] = '99999999-9999-4999-8999-999999999996'
    release['checkpoints'] = [
        {'connector_key': 'rss:example', 'checkpoint_ref': 'urn:fixture:cp',
         'completed_until': '2026-10-20T04:00:00.500000Z'}
    ]
    coordinator.append_release(release)
    coordinator.append_release(release)  # nested checkpoint instant dedups too
    assert len(lake.read_all('news.releases')) == 1


def test_release_kind_is_rejected_in_commit_batches(lake, coordinator, fixture_records):
    with pytest.raises(CommitError) as raised:
        coordinator.commit([fixture_records[-1]])
    assert raised.value.rule == 'release_in_batch'


def test_non_dict_inputs_raise_shape_errors(lake, coordinator):
    """Review finding: non-dict input must surface as ContractError('shape'),
    never an AttributeError from the canonicalizer."""
    from news_lake.contract import ContractError

    for bad in ('x', None, 42, ['nested']):
        with pytest.raises(ContractError) as raised:
            coordinator.commit([bad])
        assert raised.value.rule == 'shape'
        with pytest.raises(ContractError) as release_case:
            coordinator.append_release(bad)
        assert release_case.value.rule == 'shape'


def test_free_text_matching_an_instant_is_never_canonicalized(lake, coordinator, batch):
    """Review finding: only INSTANT_KEYS fields are canonicalized; a free-text
    field (here: a version title) whose entire value looks like a trailing-zero
    instant must round-trip verbatim."""
    version = copy.deepcopy(next(r for r in batch if r['kind'] == 'version'))
    version['id'] = '99999999-9999-4999-8999-999999999995'
    version['title'] = '2026-10-20T04:00:00.123000Z'
    coordinator.commit([version])
    stored = next(r for r in lake.read_all('news.versions') if r['id'] == version['id'])
    assert stored['title'] == '2026-10-20T04:00:00.123000Z'  # verbatim, trailing zeros intact
    coordinator.commit([version])  # replay still a no-op
    assert len([r for r in lake.read_all('news.versions') if r['id'] == version['id']]) == 1


def test_stale_writer_is_fenced_out(lake, control, batch):
    first = Coordinator(lake, control, writer_id='writer-1')
    second = Coordinator(lake, control, writer_id='writer-2')
    assert second.epoch > first.epoch
    with pytest.raises(FencedError):
        first.commit([batch[0]])
    second.commit([batch[0]])  # the current lease holder still commits
    assert len(lake.read_all('news.outlets')) == 1


class StealFenceAfterFirstTable(Faults):
    """A second writer claims the lease after the first table commit."""

    def __init__(self, lake, control):
        super().__init__()
        self.lake = lake
        self.control = control
        self.intruder = None

    def after(self, point):
        super().after(point)
        if self.intruder is None and point.startswith('table_commit:'):
            self.intruder = Coordinator(self.lake, self.control, writer_id='intruder')


def test_fence_stolen_mid_batch_stops_before_the_next_table(lake, control, batch):
    """ct-1h4g: the epoch is re-checked before every table commit, so a writer
    fenced mid-batch cannot commit the remaining tables."""
    faults = StealFenceAfterFirstTable(lake, control)
    first = Coordinator(lake, control, writer_id='first', faults=faults)
    with pytest.raises(FencedError):
        first.commit(batch)
    assert faults.intruder is not None
    # The first table (news.outlets) committed; the next one never did.
    assert len(lake.read_all('news.outlets')) == 1
    for table in CONTENT_TABLES:
        if table != 'news.outlets':
            assert lake.read_all(table) == [], table


@pytest.mark.parametrize('call', [
    lambda c, e: c.begin_cycle('cycle-2', {'records': []}, epoch=e),
    lambda c, e: c.update_cycle_payload('cycle-under-test', {'records': [], 'release': {}}, epoch=e),
    lambda c, e: c.set_cycle_state('cycle-under-test', 'committed', epoch=e),
    lambda c, e: c.stage_checkpoint(
        'cycle-under-test',
        {'connector_key': 'rss:test', 'checkpoint_ref': 'urn:test', 'completed_until': None},
        epoch=e,
    ),
    lambda c, e: c.activate_checkpoints('cycle-under-test', epoch=e),
    lambda c, e: c.discard_staged_checkpoints('cycle-under-test', epoch=e),
    lambda c, e: c.mark_available('cycle-under-test', epoch=e),
    lambda c, e: c.retire('cycle-under-test', epoch=e),
    lambda c, e: c.mark_snapshots_validated([('news.items', '1')], epoch=e),
])
def test_fenced_writer_cannot_mutate_the_control_store(lake, control, batch, call):
    """The epoch is enforced inside the SQLite transaction across every mutator."""
    first = Coordinator(lake, control, writer_id='first')
    first.control.begin_cycle('cycle-under-test', {'records': []}, epoch=first.epoch)
    Coordinator(lake, control, writer_id='second')  # steals the lease
    with pytest.raises(FencedError):
        call(control, first.epoch)
    assert control.cycle_state('cycle-under-test') == 'intent'
    assert control.cycle('cycle-2') is None
    assert control.availability('cycle-under-test') is None
    assert control.validated_snapshots() == set()


def test_fence_stolen_right_before_catalog_commit_aborts_the_iceberg_commit(
        lake, control, batch, monkeypatch):
    """Lake.fenced_commit acquires BEGIN IMMEDIATE on control.db around
    SqlCatalog.commit_table, eliminating the cross-system TOCTOU window even
    after Parquet files have been written."""
    first = Coordinator(lake, control, writer_id='first')
    guarded = lake._guarded_commit_table

    def steal_then_commit(table, requirements, updates):
        # Intruder steals the lease after _commit_table's pre-check and after
        # Parquet files were written, right as catalog.commit_table is called.
        Coordinator(lake, control, writer_id='intruder')
        return guarded(table, requirements, updates)

    monkeypatch.setattr(lake.catalog, 'commit_table', steal_then_commit)
    with pytest.raises(FencedError):
        first.commit([batch[0]])
    assert lake.read_all('news.outlets') == []
