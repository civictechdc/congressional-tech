"""Relational bridge tables (Arrow & row dicts) for out-of-core / DocSpec views.

Pre-resolves graph-recursive and selection-scoped state into flat relational
tables so ``politician_articles`` and ``coverage_daily`` can be executed via
Arrow/DuckDB/docspec-rs relational joins and aggregations without scanning
Python dicts:

- ``entity_roots_rows`` / ``entity_roots_arrow``:
  ``(entity_id, person_root_id, entity_type, name)``
- ``survivor_items_rows`` / ``survivor_items_arrow``:
  ``(item_id, outlet_id, current_version_id, effective_pub_date, story_id, text_group_id)``
- ``selected_mentions_rows`` / ``selected_mentions_arrow``:
  ``(mention_id, version_id, run_id, entity_id, surface, aboutness, occurrences)``
"""
from datetime import date

import pyarrow as pa

from news_lake.analysis.cluster import text_group_key
from news_lake.analysis.selection import select_runs
from news_lake.analysis.views import _by_kind, _publication_date, _survivor
from news_lake.identity.decisions import apply_decisions

ENTITY_ROOTS_SCHEMA = pa.schema([
    pa.field('entity_id', pa.string(), nullable=False),
    pa.field('person_root_id', pa.string(), nullable=False),
    pa.field('entity_type', pa.string(), nullable=False),
    pa.field('name', pa.string(), nullable=False),
])

SURVIVOR_ITEMS_SCHEMA = pa.schema([
    pa.field('item_id', pa.string(), nullable=False),
    pa.field('outlet_id', pa.string(), nullable=True),
    pa.field('current_version_id', pa.string(), nullable=True),
    pa.field('effective_pub_date', pa.date32(), nullable=True),
    pa.field('story_id', pa.string(), nullable=True),
    pa.field('text_group_id', pa.string(), nullable=True),
    pa.field('identical_text_group_id', pa.string(), nullable=True),
])

SPAN_STRUCT_TYPE = pa.struct([
    pa.field('field', pa.string(), nullable=False),
    pa.field('start', pa.int64(), nullable=False),
    pa.field('end', pa.int64(), nullable=False),
])

SELECTED_MENTIONS_SCHEMA = pa.schema([
    pa.field('mention_id', pa.string(), nullable=False),
    pa.field('version_id', pa.string(), nullable=False),
    pa.field('run_id', pa.string(), nullable=False),
    pa.field('entity_id', pa.string(), nullable=False),
    pa.field('surface', pa.string(), nullable=False),
    pa.field('aboutness', pa.string(), nullable=False),
    pa.field('occurrences', pa.list_(pa.field('element', SPAN_STRUCT_TYPE, nullable=False)), nullable=False),
])

BRIDGE_KEYS = {
    'entity_roots': 'entity_id',
    'selected_mentions': 'mention_id',
    'survivor_items': 'item_id',
}

BRIDGE_SCHEMAS = {
    'entity_roots': ENTITY_ROOTS_SCHEMA,
    'selected_mentions': SELECTED_MENTIONS_SCHEMA,
    'survivor_items': SURVIVOR_ITEMS_SCHEMA,
}


def _unwrap_records_and_selections(records, selections=None):
    if isinstance(records, dict) and 'tables' in records:
        flat = [record for rows in records['tables'].values() for record in rows]
        if selections is None:
            selections = records.get('release', {}).get('selections', ())
        return flat, selections
    return list(records), (() if selections is None else selections)


def entity_roots_rows(records, decision_result=None):
    """Emit one relational bridge row per entity with its resolved root ID."""
    flat_records, _ = _unwrap_records_and_selections(records)
    entities = _by_kind(flat_records, 'entity')
    if decision_result is None:
        decision_result = apply_decisions(flat_records)
    roots = decision_result.get('roots', {})
    rows = []
    for entity_id in sorted(entities):
        entity = entities[entity_id]
        root_id = roots.get(entity_id, entity_id)
        root_entity = entities.get(root_id, entity)
        rows.append({
            'entity_id': entity_id,
            'person_root_id': root_id,
            'entity_type': root_entity.get('entity_type', entity['entity_type']),
            'name': root_entity.get('name', entity['name']),
        })
    return rows


def entity_roots_arrow(records, decision_result=None):
    """Return the ``entity_roots`` bridge table as a ``pyarrow.Table``."""
    return pa.Table.from_pylist(
        entity_roots_rows(records, decision_result=decision_result),
        schema=ENTITY_ROOTS_SCHEMA,
    )


def survivor_items_rows(records, selections=None):
    """Emit one relational bridge row per terminal survivor item."""
    flat_records, selections = _unwrap_records_and_selections(records, selections)
    items = _by_kind(flat_records, 'item')
    versions = _by_kind(flat_records, 'version')
    runs = _by_kind(flat_records, 'run')

    discoveries_by_item = {}
    for record in flat_records:
        if record.get('kind') == 'discovery':
            discoveries_by_item.setdefault(record['item_id'], []).append(record)

    selection = select_runs(flat_records, selections)
    pinned_processors = {entry['processor'] for entry in selections}

    story_by_version = {}
    for record in flat_records:
        if record.get('kind') != 'story_member':
            continue
        run = runs.get(record['run_id'])
        if run is None or run['processor'] not in pinned_processors:
            continue
        if selection['assignments'].get((run['processor'], 'version', record['version_id'])) == record['run_id']:
            story_by_version.setdefault(record['version_id'], record['story_id'])

    seen = set()
    survivors = []
    for item in items.values():
        survivor = _survivor(item, items)
        if survivor['id'] not in seen:
            seen.add(survivor['id'])
            survivors.append(survivor)
    survivors.sort(key=lambda item: item['id'])

    text_group_counts = {}
    text_group_by_item = {}
    for item in survivors:
        version_id = item.get('current_version_id')
        version = versions.get(version_id) if version_id is not None else None
        if version is not None and isinstance(version.get('text'), str):
            group_id = text_group_key(version['text'])
            text_group_by_item[item['id']] = group_id
            text_group_counts[group_id] = text_group_counts.get(group_id, 0) + 1

    rows = []
    for item in survivors:
        version_id = item.get('current_version_id')
        version = versions.get(version_id) if version_id is not None else None
        pub_date_str = _publication_date(version.get('publication')) if version is not None else None
        if pub_date_str is None:
            discovery_dates = {
                d
                for discovery in discoveries_by_item.get(item['id'], ())
                if (d := _publication_date(discovery.get('reported_publication'))) is not None
            }
            if len(discovery_dates) == 1:
                pub_date_str = discovery_dates.pop()
        effective_pub_date = date.fromisoformat(pub_date_str) if pub_date_str is not None else None
        story_id = story_by_version.get(version['id']) if version is not None else None
        text_group_id = text_group_by_item.get(item['id'])
        identical_text_group_id = (
            text_group_id
            if text_group_id is not None and text_group_counts.get(text_group_id, 0) > 1
            else None
        )
        rows.append({
            'item_id': item['id'],
            'outlet_id': item.get('outlet_id'),
            'current_version_id': version['id'] if version is not None else None,
            'effective_pub_date': effective_pub_date,
            'story_id': story_id,
            'text_group_id': text_group_id,
            'identical_text_group_id': identical_text_group_id,
        })
    return rows


def survivor_items_arrow(records, selections=None):
    """Return the ``survivor_items`` bridge table as a ``pyarrow.Table``."""
    return pa.Table.from_pylist(
        survivor_items_rows(records, selections=selections),
        schema=SURVIVOR_ITEMS_SCHEMA,
    )


def selected_mentions_rows(records, selections=None):
    """Emit one relational bridge row per resolved mention from a selected run."""
    flat_records, selections = _unwrap_records_and_selections(records, selections)
    runs = _by_kind(flat_records, 'run')
    selection = select_runs(flat_records, selections)
    pinned_processors = {entry['processor'] for entry in selections}

    rows = []
    for record in flat_records:
        if record.get('kind') != 'mention':
            continue
        if record.get('resolution') != 'resolved' or record.get('entity_id') is None:
            continue
        run = runs.get(record['run_id'])
        if run is None or run['processor'] not in pinned_processors:
            continue
        if selection['assignments'].get((run['processor'], 'version', record['version_id'])) != record['run_id']:
            continue
        rows.append({
            'mention_id': record['id'],
            'version_id': record['version_id'],
            'run_id': record['run_id'],
            'entity_id': record['entity_id'],
            'surface': record['surface'],
            'aboutness': record['aboutness'],
            'occurrences': [
                {'field': span['field'], 'start': span['start'], 'end': span['end']}
                for span in record['occurrences']
            ],
        })
    rows.sort(key=lambda row: row['mention_id'])
    return rows


def selected_mentions_arrow(records, selections=None):
    """Return the ``selected_mentions`` bridge table as a ``pyarrow.Table``."""
    return pa.Table.from_pylist(
        selected_mentions_rows(records, selections=selections),
        schema=SELECTED_MENTIONS_SCHEMA,
    )
