"""I6 evolution: an added optional column round-trips without touching old pins."""
import pyarrow as pa
import pytest
from pyiceberg.types import StringType

from news_lake.storage import mapping, publish_release, read_release


def test_resolve_follows_chained_refs(monkeypatch):
    definitions = mapping.SCHEMA['$defs']
    monkeypatch.setitem(definitions, 'test_alias_a', {'$ref': '#/$defs/test_alias_b'})
    monkeypatch.setitem(definitions, 'test_alias_b', {'$ref': '#/$defs/test_alias_c'})
    monkeypatch.setitem(definitions, 'test_alias_c', {'type': 'string'})
    assert mapping._resolve({'$ref': '#/$defs/test_alias_a'}) == {'type': 'string'}

    monkeypatch.setitem(definitions, 'test_alias_c', {'$ref': '#/$defs/test_alias_a'})
    with pytest.raises(ValueError, match='circular'):
        mapping._resolve({'$ref': '#/$defs/test_alias_a'})


def test_evolved_columns_convert_by_arrow_type(batch):
    record = dict(next(r for r in batch if r['kind'] == 'item'))
    record.update({
        'pilot_note': 'verified',
        'pilot_at': '2026-10-20T05:00:00.123Z',
        'pilot_date': '2026-10-20',
        'pilot_tags': ['a', 'b'],
        'pilot_meta': {'note': 'n', 'at': '2026-10-20T05:00:00Z'},
    })
    schema = pa.schema(list(mapping.iceberg_schema('item').as_arrow()) + [
        pa.field('pilot_note', pa.string()),
        pa.field('pilot_at', pa.timestamp('us', tz='UTC')),
        pa.field('pilot_date', pa.date32()),
        pa.field('pilot_tags', pa.list_(pa.string())),
        pa.field('pilot_meta', pa.struct([
            pa.field('note', pa.string()),
            pa.field('at', pa.timestamp('us', tz='UTC')),
        ])),
    ])
    exported = mapping.from_arrow_table('item', mapping.to_arrow_table('item', [record], schema))[0]
    assert exported['pilot_note'] == 'verified'
    assert exported['pilot_at'] == '2026-10-20T05:00:00.123Z'
    assert exported['pilot_date'] == '2026-10-20'
    assert exported['pilot_tags'] == ['a', 'b']
    assert exported['pilot_meta'] == {'note': 'n', 'at': '2026-10-20T05:00:00Z'}



def test_optional_column_addition_preserves_field_ids_and_old_snapshots(
        lake, control, coordinator, batch, ids, selections_a, checkpoints_a):
    publish_release(coordinator, batch, release_id=ids['release_a'],
                    recorded_at='2026-10-20T05:00:00Z',
                    selections=selections_a, checkpoints=checkpoints_a)
    items = lake.table('news.items')
    pinned = items.current_snapshot().snapshot_id
    before = {field.name: field.field_id for field in items.schema().fields}
    old_rows = lake.read_all('news.items')

    with items.update_schema() as update:
        update.add_column('pilot_note', StringType())
    after = {field.name: field.field_id for field in items.schema().fields}
    assert set(after) == set(before) | {'pilot_note'}
    assert all(after[name] == field_id for name, field_id in before.items())  # existing ids unchanged
    assert after['pilot_note'] not in before.values()  # fresh unique id
    assert items.schema().find_field('pilot_note').optional

    # The cached arrow schema invalidates automatically when schema_id advances.
    assert 'pilot_note' in lake.arrow_schema('news.items').names

    # Coordinator accepts the evolved field only because the table schema
    # defines it, then writes it through the table's authoritative Arrow schema.
    record_with_note = dict(next(r for r in batch if r['kind'] == 'item'))
    record_with_note['id'] = ids['item2']
    record_with_note['canonical_url'] = 'https://local.example/news/evolved'
    record_with_note.pop('current_version_id', None)
    record_with_note['pilot_note'] = 'verified'
    coordinator.commit([record_with_note])

    evolved = lake.read_all('news.items')
    by_id = {row['id']: row for row in evolved}
    assert by_id[record_with_note['id']]['pilot_note'] == 'verified'
    assert by_id[record_with_note['id']]['canonical_url'] == record_with_note['canonical_url']
    # Pre-evolution rows still export without the evolved column (SQL NULL omitted).
    assert all('pilot_note' not in row for row in evolved if row['id'] != record_with_note['id'])

    # Old pinned snapshot stays readable through the release reader and is
    # unchanged: no evolved column appears on its pre-evolution rows.
    result = read_release(lake, control, ids['release_a'])
    assert result['tables']['news.items'] == old_rows
    assert all('pilot_note' not in row for row in result['tables']['news.items'])
    direct = items.scan(snapshot_id=pinned).to_arrow()
    assert len(direct.to_pylist()) == len(old_rows)
    assert mapping.from_arrow_table('item', direct) == old_rows

    # A later release validates and exports the evolved column too.
    release_b = publish_release(
        coordinator, [], release_id=ids['release_b'],
        recorded_at='2026-10-20T06:00:00Z',
        selections=selections_a, checkpoints=checkpoints_a,
    )
    evolved_release = read_release(lake, control, release_b['id'])['tables']['news.items']
    evolved_row = next(row for row in evolved_release if row['id'] == record_with_note['id'])
    assert evolved_row['pilot_note'] == 'verified'
    assert evolved_row['canonical_url'] == 'https://local.example/news/evolved'

    # Evolving news.releases itself also round-trips through append_release.
    releases_table = lake.table('news.releases')
    with releases_table.update_schema() as update:
        update.add_column('release_note', StringType())
    assert lake.allowed_extra('news.releases') == frozenset({'release_note'})
    evolved_rel = dict(release_b)
    evolved_rel['id'] = '99999999-9999-4999-8999-999999999991'
    evolved_rel['release_note'] = 'audited-pilot'
    coordinator.append_release(evolved_rel)
    control.mark_available(evolved_rel['id'], epoch=coordinator.epoch)
    assert read_release(lake, control, evolved_rel['id'])['release']['release_note'] == 'audited-pilot'
