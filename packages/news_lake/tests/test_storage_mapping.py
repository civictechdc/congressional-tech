"""I1 round trip: every fixture record through its table and back unchanged."""
import pytest

from news_lake.contract.records import CONTENT_TABLES, KIND_TABLES
from news_lake.storage import mapping


def test_round_trip_every_kind_from_docs_fixture(lake, coordinator, batch, fixture_records):
    coordinator.commit(batch)
    # The release kind is data like any other record for the round trip.
    coordinator.append_release(fixture_records[-1])
    for table in CONTENT_TABLES + ['news.releases']:
        stored = lake.read_all(table)
        expected = [r for r in batch + [fixture_records[-1]] if KIND_TABLES[r['kind']] == table]
        assert {r['id']: r for r in stored} == {r['id']: r for r in expected}, table


def test_pinned_snapshot_read_matches_current_before_further_commits(lake, coordinator, batch):
    coordinator.commit(batch)
    items = lake.table('news.items')
    snapshot = items.current_snapshot()
    coordinator.commit([])  # no-op
    pinned = mapping.from_arrow_table('item', items.scan(snapshot_id=snapshot.snapshot_id).to_arrow())
    assert pinned == lake.read_all('news.items')


def test_null_and_empty_list_stay_distinct(lake, coordinator, fixture_records):
    """Absent optional arrays export as omitted; recorded empty arrays stay []."""
    records = [r for r in fixture_records if r['kind'] == 'entity']
    coordinator.commit(records)
    exported = {r['id']: r for r in lake.read_all('news.entities')}
    second = next(r for r in records if not r.get('tenures'))
    assert 'tenures' not in exported[second['id']]
    assert exported[second['id']]['aliases'] == []
    first = next(r for r in records if r.get('tenures'))
    assert exported[first['id']]['tenures'] == first['tenures']


def test_timestamptz_precision_survives(lake, coordinator, fixture_records):
    coordinator.commit([r for r in fixture_records if r['kind'] == 'version'])
    exported = lake.read_all('news.versions')[0]
    assert exported['recorded_at'] == '2026-10-20T04:00:00Z'
    row = mapping.record_to_row(fixture_records[-1])
    assert row['recorded_at'].microsecond == 0
    fractional = dict(fixture_records[-1])
    fractional['recorded_at'] = '2026-10-20T04:00:00.123456Z'
    assert mapping.format_instant(mapping.record_to_row(fractional)['recorded_at']) == '2026-10-20T04:00:00.123456Z'
    trimmed = dict(fixture_records[-1])
    trimmed['recorded_at'] = '2026-10-20T04:00:00.5Z'
    assert mapping.format_instant(mapping.record_to_row(trimmed)['recorded_at']) == '2026-10-20T04:00:00.5Z'
