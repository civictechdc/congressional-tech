"""Tests for I5 26-year time-partitioned Iceberg layout and relational bridge tables."""
import copy
from datetime import date
import hashlib
from uuid import NAMESPACE_URL, uuid5

import pyarrow as pa
import pytest
from pyiceberg.transforms import DayTransform, MonthTransform

from news_lake.analysis import coverage_daily, politician_articles
from news_lake.analysis.bridges import (
    ENTITY_ROOTS_SCHEMA,
    SELECTED_MENTIONS_SCHEMA,
    SURVIVOR_ITEMS_SCHEMA,
    entity_roots_arrow,
    entity_roots_rows,
    selected_mentions_arrow,
    selected_mentions_rows,
    survivor_items_arrow,
    survivor_items_rows,
)
from news_lake.analysis.views import _merge_spans
from news_lake.contract import ContractError
from news_lake.contract.records import CONTENT_TABLES, KIND_ORDER, KIND_TABLES, UPSERT_TABLES, validate_shape
from news_lake.identity import apply_decisions
from news_lake.storage import ControlStore, Coordinator, Lake, publish_release, read_release
from news_lake.storage.mapping import iceberg_schema
from news_lake.storage.partitions import (
    PARTITION_COLUMNS,
    create_partitioned_tables,
    partition_spec_for,
)

AT = '2026-10-20T04:00:00Z'
_id = lambda key: str(uuid5(NAMESPACE_URL, 'news-lake-views-test:' + key))
_uid = lambda name: str(uuid5(NAMESPACE_URL, f'news-lake-26yr:{name}'))
_hash = lambda text: hashlib.sha256(text.encode('utf-8')).hexdigest()


def _entity(key, name, entity_type='person', aliases=(), identifiers=()):
    return {
        'kind': 'entity',
        'id': _id('entity:' + key),
        'recorded_at': AT,
        'entity_type': entity_type,
        'name': name,
        'aliases': list(aliases),
        'identifiers': list(identifiers),
    }


P1 = _entity('p1', 'Alex Doe', identifiers=[{'scheme': 'fixture', 'value': 'p1'}])
P1B = _entity(
    'p1b',
    'Alex Doe',
    aliases=[{'value': 'A. Doe', 'language': 'en'}],
    identifiers=[{'scheme': 'fixture-alias', 'value': 'p1b'}],
)
P2 = _entity('p2', 'Robin Roe', identifiers=[{'scheme': 'fixture', 'value': 'p2'}])
ORG = _entity('org', 'Example Party', entity_type='organization', identifiers=[{'scheme': 'fixture', 'value': 'org'}])
MERGE_P1B_INTO_P1 = {
    'kind': 'identity_decision',
    'id': _id('decision:merge'),
    'recorded_at': AT,
    'action': 'same_as',
    'left_id': P1B['id'],
    'right_id': P1['id'],
    'decided_by': 'fixture:reviewer',
    'reason': 'Fixture merge of the alias entity.',
}
OUTLET_A = {'kind': 'outlet', 'id': _id('outlet:a'), 'recorded_at': AT, 'name': 'Example News', 'domains': ['a.example']}
OUTLET_B = {'kind': 'outlet', 'id': _id('outlet:b'), 'recorded_at': AT, 'name': 'Other News', 'domains': ['b.example']}


def _capture(key):
    return {
        'kind': 'capture',
        'id': _id('capture:' + key),
        'recorded_at': AT,
        'provider': 'rss',
        'request_url': f'https://a.example/{key}',
        'observed_at': AT,
        'http_status': 200,
        'access': 'redistributable',
        'payload_uri': f's3://fixture/{key}',
        'payload_hash': _hash('capture:' + key),
        'media_type': 'text/html',
        'rights_basis': 'Synthetic fixture.',
        'status': 'succeeded',
    }


def _discovery(key, *, item_key=None, reported_publication=None):
    item_key = item_key or key
    record = {
        'kind': 'discovery',
        'id': _id('discovery:' + key),
        'recorded_at': AT,
        'capture_id': _id('capture:' + item_key),
        'item_id': _id('item:' + item_key),
        'provider': 'mediacloud',
        'url': f'https://a.example/{key}',
        'observed_at': AT,
        'mode': 'live',
    }
    if reported_publication is not None:
        record['reported_publication'] = reported_publication
    return record


def _extract_run(key, capture_id):
    return {
        'kind': 'run',
        'id': _id('run-extract:' + key),
        'recorded_at': AT,
        'processor': 'extract',
        'processor_version': 'fixture-1',
        'config_hash': _hash('extract:' + key),
        'input_hash': _hash('extract-inputs:' + key),
        'inputs': [{'kind': 'capture', 'id': capture_id}],
        'mode': 'live',
        'status': 'succeeded',
        'started_at': AT,
        'finished_at': AT,
    }


def _item(key, *, outlet=OUTLET_A, version_key=None, superseded_by=None):
    record = {
        'kind': 'item',
        'id': _id('item:' + key),
        'recorded_at': AT,
        'outlet_id': outlet['id'],
        'canonical_url': f"https://{outlet['domains'][0]}/{key}",
        'url_aliases': [],
        'content_type': 'news_article',
        'first_seen_at': AT,
    }
    if version_key is not None:
        record['current_version_id'] = _id('version:' + version_key)
    if superseded_by is not None:
        record['superseded_by'] = _id('item:' + superseded_by)
    return record


def _version(key, *, title, publication, text=None):
    record = {
        'kind': 'version',
        'id': _id('version:' + key),
        'recorded_at': AT,
        'item_id': _id('item:' + key),
        'capture_id': _id('capture:' + key),
        'run_id': _id('run-extract:' + key),
        'title': title,
        'publication': publication,
        'access': 'metadata_only',
    }
    if text is not None:
        record['access'] = 'restricted'
        record['rights_basis'] = 'Synthetic fixture.'
        record['text'] = text
        record['text_hash'] = _hash(text)
    return record


def _run(key, *, processor, config, inputs, finished_at):
    return {
        'kind': 'run',
        'id': _id('run:' + key),
        'recorded_at': finished_at,
        'processor': processor,
        'processor_version': 'fixture-1',
        'config_hash': _hash(processor + ':' + config),
        'input_hash': _hash(processor + '-inputs:' + key),
        'inputs': [{'kind': 'version', 'id': identifier} for identifier in inputs],
        'mode': 'reprocess',
        'status': 'succeeded',
        'started_at': AT,
        'finished_at': finished_at,
    }


def _mention(key, *, version_key, surface, resolution, occurrences, entity_key=None, aboutness='primary'):
    record = {
        'kind': 'mention',
        'id': _id('mention:' + key),
        'recorded_at': AT,
        'version_id': _id('version:' + version_key),
        'run_id': _id('run:link2'),
        'surface': surface,
        'resolution': resolution,
        'aboutness': aboutness,
        'occurrences': occurrences,
    }
    if entity_key is not None:
        record['entity_id'] = _id('entity:' + entity_key)
    return record


def _story(key, run_key):
    return {'kind': 'story', 'id': _id('story:' + key), 'recorded_at': AT, 'run_id': _id('run:' + run_key)}


def _member(story_key, version_key, run_key):
    return {
        'kind': 'story_member',
        'id': _id('member:' + story_key + ':' + version_key),
        'recorded_at': AT,
        'story_id': _id('story:' + story_key),
        'version_id': _id('version:' + version_key),
        'run_id': _id('run:' + run_key),
    }


V1 = _version(
    'v1',
    title='Alex Doe speaks at the council',
    publication={'precision': 'day', 'date': '2026-10-18', 'basis': 'publisher'},
    text='Council member Alex Doe and Alex Doe spoke.',
)
V2 = _version(
    'v2',
    title='Council roundup',
    publication={'precision': 'day', 'date': '2026-10-18', 'basis': 'publisher'},
    text='Council member Alex Doe and Alex Doe spoke.',
)
V3 = _version('v3', title='Who is Alex Doe?', publication={'precision': 'unknown'})
V5 = _version(
    'v5',
    title='Robin Roe resigns',
    publication={'precision': 'instant', 'at': '2026-10-19T18:30:00Z', 'basis': 'publisher'},
    text='Robin Roe resigned Monday.',
)
V6 = _version(
    'v6',
    title='Example Party announces platform',
    publication={'precision': 'day', 'date': '2026-10-18', 'basis': 'publisher'},
)

I1 = _item('v1', version_key='v1')
I2 = _item('v2', outlet=OUTLET_B, version_key='v2')
I3 = _item('v3', version_key='v3')
I4 = _item('v4')
I5 = _item('v5', version_key='v5')
I6 = _item('v6', version_key='v6')
I4['superseded_by'] = I5['id']

LINKED = [_id('version:' + key) for key in ('v1', 'v3', 'v5', 'v6')]
RUN_LINK_OLD = _run(
    'link1', processor='mentions', config='model-A', inputs=[_id('version:v1')], finished_at='2026-10-20T05:00:00Z'
)
RUN_LINK = _run(
    'link2', processor='mentions', config='model-B', inputs=LINKED, finished_at='2026-10-20T06:00:00Z'
)
RUN_CLUSTER = _run(
    'cluster1',
    processor='cluster',
    config='identical-text',
    inputs=[_id('version:' + key) for key in ('v1', 'v2', 'v5')],
    finished_at='2026-10-20T06:30:00Z',
)
STORY_SYNDICATION = _story('syndication', 'cluster1')
STORY_ROE = _story('roe', 'cluster1')

M_OLD = _mention(
    'old',
    version_key='v1',
    surface='Alex Doe',
    resolution='resolved',
    occurrences=[{'field': 'title', 'start': 0, 'end': 8}],
    entity_key='p1',
)
M_OLD['run_id'] = RUN_LINK_OLD['id']
M1 = _mention(
    'm1',
    version_key='v1',
    surface='Alex Doe',
    resolution='resolved',
    occurrences=[{'field': 'title', 'start': 0, 'end': 8}, {'field': 'text', 'start': 15, 'end': 23}],
    entity_key='p1',
)
M2 = _mention(
    'm2',
    version_key='v1',
    surface='Alex Doe',
    resolution='resolved',
    occurrences=[{'field': 'title', 'start': 0, 'end': 8}, {'field': 'text', 'start': 28, 'end': 36}],
    entity_key='p1b',
)
M_AMBIGUOUS = _mention(
    'amb',
    version_key='v3',
    surface='Alex Doe',
    resolution='ambiguous',
    occurrences=[{'field': 'title', 'start': 7, 'end': 15}],
    aboutness='unknown',
)
M_ROE = _mention(
    'roe',
    version_key='v5',
    surface='Robin Roe',
    resolution='resolved',
    occurrences=[{'field': 'title', 'start': 0, 'end': 9}, {'field': 'text', 'start': 0, 'end': 9}],
    entity_key='p2',
)
M_ORG = _mention(
    'org',
    version_key='v6',
    surface='Example Party',
    resolution='resolved',
    occurrences=[{'field': 'title', 'start': 0, 'end': 13}],
    entity_key='org',
)

SHELLS = []
for _k in ('v1', 'v2', 'v3', 'v5', 'v6'):
    SHELLS.extend([_capture(_k), _extract_run(_k, _id('capture:' + _k))])

CORPUS = [
    OUTLET_A, OUTLET_B, I1, I2, I3, I4, I5, I6, V1, V2, V3, V5, V6,
    P1, P1B, P2, ORG, MERGE_P1B_INTO_P1,
    RUN_LINK_OLD, RUN_LINK, RUN_CLUSTER,
    STORY_SYNDICATION, STORY_ROE,
    _member('syndication', 'v1', 'cluster1'), _member('syndication', 'v2', 'cluster1'),
    _member('roe', 'v5', 'cluster1'),
    M_OLD, M1, M2, M_AMBIGUOUS, M_ROE, M_ORG,
    *SHELLS,
]

SELECTIONS = [
    {'processor': 'mentions', 'processor_version': 'fixture-1', 'config_hash': RUN_LINK['config_hash']},
    {'processor': 'cluster', 'processor_version': 'fixture-1', 'config_hash': RUN_CLUSTER['config_hash']},
]


def release_read_of(records, selections):
    tables = {}
    for record in records:
        tables.setdefault(KIND_TABLES[record['kind']], []).append(record)
    release = {
        'kind': 'release',
        'id': _id('release:views'),
        'recorded_at': AT,
        'contract_version': '0.1.0',
        'snapshots': [{'table': table, 'table_uuid': _id('uuid:' + table)} for table in CONTENT_TABLES],
        'selections': list(selections),
        'checkpoints': [],
    }
    validate_shape(release)
    return {'release': release, 'tables': tables}


def _decade_slice(tag, instant, pub_date, *, outlet_id, entity_id, outlet_domain, feed_url, extra_alias=None):
    """Build a valid slice of records for a single decade timestamp."""
    cap_id = _uid(f'capture:{tag}')
    disc_id = _uid(f'discovery:{tag}')
    item_id = _uid(f'item:{tag}')
    ver_id = _uid(f'version:{tag}')
    run_ext_id = _uid(f'run-extract:{tag}')
    run_men_id = _uid(f'run-mentions:{tag}')
    run_cls_id = _uid(f'run-cluster:{tag}')
    men_id = _uid(f'mention:{tag}')
    cls_id = _uid(f'classification:{tag}')
    story_id = _uid(f'story:{tag}')
    member_id = _uid(f'member:{tag}')
    text = f'Sen. Alex Doe addressed the floor on {pub_date}.'
    title = f'Alex Doe speech {pub_date}'

    aliases = [{'value': extra_alias, 'language': 'en'}] if extra_alias else []

    return [
        {
            'kind': 'outlet',
            'id': outlet_id,
            'recorded_at': instant,
            'name': f'Archive News ({tag})',
            'domains': [outlet_domain],
            'feed_urls': [feed_url],
        },
        {
            'kind': 'capture',
            'id': cap_id,
            'recorded_at': instant,
            'provider': 'rss',
            'request_url': f'https://{outlet_domain}/articles/{tag}',
            'observed_at': instant,
            'http_status': 200,
            'access': 'redistributable',
            'payload_uri': f's3://archive-news/captures/{tag}.html',
            'payload_hash': _hash(f'payload:{tag}'),
            'media_type': 'text/html',
            'rights_basis': 'Public archive.',
            'status': 'succeeded',
        },
        {
            'kind': 'discovery',
            'id': disc_id,
            'recorded_at': instant,
            'capture_id': cap_id,
            'item_id': item_id,
            'provider': 'rss',
            'external_id': f'ext-{tag}',
            'feed_url': feed_url,
            'url': f'https://{outlet_domain}/articles/{tag}',
            'observed_at': instant,
            'mode': 'backfill' if tag != '2026' else 'live',
            'reported_title': title,
            'reported_publication': {'precision': 'day', 'date': pub_date, 'basis': 'publisher'},
        },
        {
            'kind': 'item',
            'id': item_id,
            'recorded_at': instant,
            'outlet_id': outlet_id,
            'canonical_url': f'https://{outlet_domain}/articles/{tag}',
            'url_aliases': [f'https://{outlet_domain}/{tag}'],
            'content_type': 'news_article',
            'first_seen_at': instant,
            'current_version_id': ver_id,
        },
        {
            'kind': 'version',
            'id': ver_id,
            'recorded_at': instant,
            'item_id': item_id,
            'capture_id': cap_id,
            'run_id': run_ext_id,
            'title': title,
            'publication': {'precision': 'day', 'date': pub_date, 'basis': 'publisher'},
            'text': text,
            'text_hash': _hash(text),
            'access': 'redistributable',
            'rights_basis': 'Public archive.',
        },
        {
            'kind': 'entity',
            'id': entity_id,
            'recorded_at': instant,
            'entity_type': 'person',
            'name': 'Alex Doe',
            'aliases': aliases,
            'identifiers': [{'scheme': 'bioguide', 'value': 'D000001'}],
        },
        {
            'kind': 'run',
            'id': run_ext_id,
            'recorded_at': instant,
            'processor': 'extract',
            'processor_version': 'v1',
            'config_hash': _hash('extract-v1'),
            'input_hash': _hash(f'extract-in:{tag}'),
            'inputs': [{'kind': 'capture', 'id': cap_id}],
            'mode': 'backfill' if tag != '2026' else 'live',
            'status': 'succeeded',
            'started_at': instant,
            'finished_at': instant,
        },
        {
            'kind': 'run',
            'id': run_men_id,
            'recorded_at': instant,
            'processor': 'mentions',
            'processor_version': 'v1',
            'config_hash': _hash('mentions-v1'),
            'input_hash': _hash(f'mentions-in:{tag}'),
            'inputs': [{'kind': 'version', 'id': ver_id}],
            'mode': 'backfill' if tag != '2026' else 'live',
            'status': 'succeeded',
            'started_at': instant,
            'finished_at': instant,
        },
        {
            'kind': 'mention',
            'id': men_id,
            'recorded_at': instant,
            'version_id': ver_id,
            'run_id': run_men_id,
            'surface': 'Alex Doe',
            'resolution': 'resolved',
            'entity_id': entity_id,
            'aboutness': 'primary',
            'occurrences': [
                {'field': 'title', 'start': 0, 'end': 8},
                {'field': 'text', 'start': 5, 'end': 13},
            ],
        },
        {
            'kind': 'classification',
            'id': cls_id,
            'recorded_at': instant,
            'version_id': ver_id,
            'run_id': run_men_id,
            'dimension': 'topic',
            'taxonomy_version': 'v1',
            'value_strings': ['floor-speech'],
        },
        {
            'kind': 'run',
            'id': run_cls_id,
            'recorded_at': instant,
            'processor': 'cluster',
            'processor_version': 'v1',
            'config_hash': _hash('cluster-v1'),
            'input_hash': _hash(f'cluster-in:{tag}'),
            'inputs': [{'kind': 'version', 'id': ver_id}],
            'mode': 'backfill' if tag != '2026' else 'live',
            'status': 'succeeded',
            'started_at': instant,
            'finished_at': instant,
        },
        {
            'kind': 'story',
            'id': story_id,
            'recorded_at': instant,
            'run_id': run_cls_id,
            'label': f'Story {tag}',
        },
        {
            'kind': 'story_member',
            'id': member_id,
            'recorded_at': instant,
            'story_id': story_id,
            'version_id': ver_id,
            'run_id': run_cls_id,
            'score': 1.0,
        },
    ]


# -- Part 1: I5 Partition Specs & 26-Year Partitioned Lake ----------------------------


def test_partition_spec_for_every_kind_and_granularity():
    observed_at_kinds = {'capture', 'discovery'}
    unpartitioned_kinds = {'outlet', 'item', 'entity'}
    recorded_at_kinds = {
        'version',
        'mention',
        'classification',
        'run',
        'story',
        'story_member',
        'identity_decision',
        'release',
    }
    assert observed_at_kinds | unpartitioned_kinds | recorded_at_kinds == set(KIND_ORDER)

    for kind in KIND_ORDER:
        schema = iceberg_schema(kind)
        month_spec = partition_spec_for(kind, schema, granularity='month')
        day_spec = partition_spec_for(kind, schema, granularity='day')
        none_spec = partition_spec_for(kind, schema, granularity=None)
        assert len(none_spec.fields) == 0

        if kind in unpartitioned_kinds:
            assert KIND_TABLES[kind] in UPSERT_TABLES
            assert len(month_spec.fields) == 0
            assert len(day_spec.fields) == 0
        else:
            expected_col = 'observed_at' if kind in observed_at_kinds else 'recorded_at'
            expected_source_id = schema.find_field(expected_col).field_id
            assert len(month_spec.fields) == 1
            mf = month_spec.fields[0]
            assert mf.source_id == expected_source_id
            assert isinstance(mf.transform, MonthTransform)
            assert mf.name == f'{expected_col}_month'

            assert len(day_spec.fields) == 1
            df = day_spec.fields[0]
            assert df.source_id == expected_source_id
            assert isinstance(df.transform, DayTransform)
            assert df.name == f'{expected_col}_day'


def test_partition_spec_rejects_unknown_kind_or_granularity():
    with pytest.raises(ValueError, match='unknown record kind'):
        partition_spec_for('not_a_kind')
    with pytest.raises(ValueError, match='unsupported partition granularity'):
        partition_spec_for('capture', granularity='hour')


def test_26_year_partitioned_lake_commits_upserts_releases_and_abandon_cycle(tmp_path):
    lake = create_partitioned_tables(Lake(tmp_path / 'lake_26yr'), granularity='month')
    # Calling create_partitioned_tables again is idempotent.
    assert create_partitioned_tables(lake, granularity='month') is lake
    control = ControlStore(tmp_path / 'lake_26yr' / 'control.db')
    coordinator = Coordinator(lake, control)

    # Verify table metadata specs on the created catalog tables.
    for kind in KIND_ORDER:
        table_name = KIND_TABLES[kind]
        table = lake.table(table_name)
        assert table.metadata.format_version == 2
        col = PARTITION_COLUMNS[kind]
        if col is None:
            assert len(table.spec().fields) == 0, table_name
        else:
            assert len(table.spec().fields) == 1, table_name
            field = table.spec().fields[0]
            assert field.source_id == table.schema().find_field(col).field_id
            assert isinstance(field.transform, MonthTransform)

    shared_outlet_id = _uid('outlet:shared')
    shared_entity_id = _uid('entity:doe')
    alias_entity_id = _uid('entity:doe-alias')

    slice_2000 = _decade_slice(
        '2000',
        '2000-05-12T14:00:00Z',
        '2000-05-12',
        outlet_id=shared_outlet_id,
        entity_id=shared_entity_id,
        outlet_domain='archive.example',
        feed_url='https://archive.example/rss-2000.xml',
        extra_alias='Rep. Alex Doe',
    )
    slice_2012 = _decade_slice(
        '2012',
        '2012-11-06T20:00:00Z',
        '2012-11-06',
        outlet_id=shared_outlet_id,
        entity_id=shared_entity_id,
        outlet_domain='archive.example',
        feed_url='https://archive.example/rss-2012.xml',
        extra_alias='Sen. Alex Doe',
    )
    slice_2026 = _decade_slice(
        '2026',
        '2026-10-20T06:00:00Z',
        '2026-10-20',
        outlet_id=shared_outlet_id,
        entity_id=shared_entity_id,
        outlet_domain='archive.example',
        feed_url='https://archive.example/rss-2026.xml',
        extra_alias='Chair Alex Doe',
    )
    # Upsert the 2000 item in 2026: first_seen_at stays 2000-05-12 while
    # recorded_at advances to 2026-10-20 and url_aliases unions across decades.
    item_2000_update = copy.deepcopy(next(r for r in slice_2000 if r['kind'] == 'item'))
    item_2000_update['recorded_at'] = '2026-10-20T06:00:00Z'
    item_2000_update['first_seen_at'] = '2026-10-20T06:00:00Z'
    item_2000_update['url_aliases'] = ['https://archive.example/legacy-2000']
    slice_2026.append(item_2000_update)
    slice_2026.extend([
        {
            'kind': 'entity',
            'id': alias_entity_id,
            'recorded_at': '2026-10-20T06:00:00Z',
            'entity_type': 'person',
            'name': 'A. Doe',
            'aliases': [],
            'identifiers': [{'scheme': 'wikidata', 'value': 'Q12345'}],
        },
        {
            'kind': 'identity_decision',
            'id': _uid('decision:2026'),
            'recorded_at': '2026-10-20T06:00:00Z',
            'action': 'same_as',
            'left_id': alias_entity_id,
            'right_id': shared_entity_id,
            'decided_by': 'curator',
            'reason': 'Same legislator across 26-year span.',
        },
    ])

    selections = [
        {'processor': 'extract', 'processor_version': 'v1', 'config_hash': _hash('extract-v1')},
        {'processor': 'mentions', 'processor_version': 'v1', 'config_hash': _hash('mentions-v1')},
        {'processor': 'cluster', 'processor_version': 'v1', 'config_hash': _hash('cluster-v1')},
    ]

    rel_2000 = publish_release(
        coordinator,
        slice_2000,
        release_id=_uid('release:2000'),
        recorded_at='2000-05-12T15:00:00Z',
        selections=selections,
        checkpoints=[{
            'connector_key': 'rss:archive',
            'checkpoint_ref': 's3://archive-news/cp/2000.json',
            'completed_until': '2000-05-12T14:00:00Z',
        }],
    )
    rel_2012 = publish_release(
        coordinator,
        slice_2012,
        release_id=_uid('release:2012'),
        recorded_at='2012-11-06T21:00:00Z',
        selections=selections,
        checkpoints=[{
            'connector_key': 'rss:archive',
            'checkpoint_ref': 's3://archive-news/cp/2012.json',
            'completed_until': '2012-11-06T20:00:00Z',
        }],
    )
    rel_2026 = publish_release(
        coordinator,
        slice_2026,
        release_id=_uid('release:2026'),
        recorded_at='2026-10-20T07:00:00Z',
        selections=selections,
        checkpoints=[{
            'connector_key': 'rss:archive',
            'checkpoint_ref': 's3://archive-news/cp/2026.json',
            'completed_until': '2026-10-20T06:00:00Z',
        }],
    )

    # Upsert tables merged evidence across 26 years without duplicating the ID.
    outlets = lake.read_all('news.outlets')
    assert len(outlets) == 1
    assert outlets[0]['id'] == shared_outlet_id
    assert outlets[0]['name'] == 'Archive News (2026)'
    assert outlets[0]['feed_urls'] == [
        'https://archive.example/rss-2000.xml',
        'https://archive.example/rss-2012.xml',
        'https://archive.example/rss-2026.xml',
    ]

    entities = {e['id']: e for e in lake.read_all('news.entities')}
    assert set(entities) == {shared_entity_id, alias_entity_id}
    assert [a['value'] for a in entities[shared_entity_id]['aliases']] == [
        'Rep. Alex Doe',
        'Sen. Alex Doe',
        'Chair Alex Doe',
    ]

    # Cross-decade item upsert kept the 2000 first_seen_at, advanced recorded_at
    # to 2026, and unioned url_aliases without duplicating the item row.
    items_by_id = {it['id']: it for it in lake.read_all('news.items')}
    assert len(items_by_id) == 3
    assert items_by_id[item_2000_update['id']]['first_seen_at'] == '2000-05-12T14:00:00Z'
    assert items_by_id[item_2000_update['id']]['recorded_at'] == '2026-10-20T06:00:00Z'
    assert items_by_id[item_2000_update['id']]['url_aliases'] == [
        'https://archive.example/2000',
        'https://archive.example/legacy-2000',
    ]

    # Pinned release reads across all three decades return the exact historical snapshots.
    read_2000 = read_release(lake, control, rel_2000['id'])
    read_2012 = read_release(lake, control, rel_2012['id'])
    read_2026 = read_release(lake, control, rel_2026['id'])
    assert len(read_2000['tables']['news.versions']) == 1
    assert len(read_2012['tables']['news.versions']) == 2
    assert len(read_2026['tables']['news.versions']) == 3

    # Test abandon_cycle on the partitioned lake after a failed cycle mutates an
    # upsert table and appends a partitioned row.
    bad_cycle_id = _uid('release:failed-2026')
    mutated_outlet = copy.deepcopy(outlets[0])
    mutated_outlet['recorded_at'] = '2026-10-21T00:00:00Z'
    mutated_outlet['name'] = 'Corrupted Outlet Name'
    bad_mention = copy.deepcopy(next(r for r in slice_2026 if r['kind'] == 'mention'))
    bad_mention['id'] = _uid('mention:bad-2026')
    bad_mention['recorded_at'] = '2026-10-21T00:00:00Z'
    bad_mention['entity_id'] = _uid('entity:missing')
    with pytest.raises(ContractError) as exc_info:
        publish_release(
            coordinator,
            [mutated_outlet, bad_mention],
            release_id=bad_cycle_id,
            recorded_at='2026-10-21T00:00:00Z',
            selections=selections,
            checkpoints=[],
        )
    assert exc_info.value.rule == 'missing_reference'

    coordinator.abandon_cycle(bad_cycle_id)
    assert control.cycle_state(bad_cycle_id) == 'abandoned'
    assert lake.read_all('news.outlets')[0]['name'] == 'Archive News (2026)'
    assert len(lake.read_all('news.mentions')) == 3

    # Views on the 2026 release see all 3 decades of coverage, and bridge tables agree.
    cov = coverage_daily(read_2026)
    assert [row['date'] for row in cov] == ['2000-05-12', '2012-11-06', '2026-10-20']
    pa_rows = politician_articles(read_2026)
    assert len(pa_rows) == 3
    assert all(row['person_root_id'] == shared_entity_id for row in pa_rows)
    assert _relational_politician_articles(read_2026) == pa_rows
    assert _relational_coverage_daily(read_2026) == cov


def test_day_granularity_partitioned_tables_round_trip(tmp_path):
    lake = create_partitioned_tables(Lake(tmp_path / 'lake_day'), granularity='day')
    control = ControlStore(tmp_path / 'lake_day' / 'control.db')
    coordinator = Coordinator(lake, control)

    assert isinstance(lake.table('news.captures').spec().fields[0].transform, DayTransform)
    assert isinstance(lake.table('news.versions').spec().fields[0].transform, DayTransform)
    assert len(lake.table('news.items').spec().fields) == 0

    records = _decade_slice(
        'day-2026',
        '2026-10-20T06:00:00Z',
        '2026-10-20',
        outlet_id=_uid('outlet:day'),
        entity_id=_uid('entity:day'),
        outlet_domain='day.example',
        feed_url='https://day.example/feed.xml',
    )
    coordinator.commit(records)
    assert len(lake.read_all('news.captures')) == 1
    assert len(lake.read_all('news.items')) == 1


# -- Part 2: Relational Bridge Tables (Arrow & Row Dicts) -----------------------------


def _relational_politician_articles(release_read, decision_result=None):
    """Compute politician_articles purely from the 3 Arrow bridge tables."""
    selections = release_read['release']['selections']
    roots_tbl = entity_roots_arrow(release_read, decision_result=decision_result)
    items_tbl = survivor_items_arrow(release_read, selections=selections)
    mentions_tbl = selected_mentions_arrow(release_read, selections=selections)

    roots_by_entity = {
        row['entity_id']: row
        for row in roots_tbl.to_pylist()
        if row['entity_type'] == 'person'
    }
    survivor_by_version = {
        row['current_version_id']: row
        for row in items_tbl.to_pylist()
        if row['current_version_id'] is not None
    }
    versions_by_id = {
        rec['id']: rec
        for rec in release_read['tables'].get('news.versions', ())
    }

    grouped = {}
    for m in mentions_tbl.to_pylist():
        item_row = survivor_by_version.get(m['version_id'])
        root_row = roots_by_entity.get(m['entity_id'])
        if item_row is None or root_row is None:
            continue
        key = (root_row['person_root_id'], item_row['item_id'])
        bucket = grouped.setdefault(key, {
            'release_id': release_read['release']['id'],
            'person_root_id': root_row['person_root_id'],
            'entity_ids': set(),
            'item_id': item_row['item_id'],
            'version_id': m['version_id'],
            'run_ids': set(),
            'aboutness': set(),
            'surfaces': set(),
            '_spans': [],
        })
        bucket['entity_ids'].add(m['entity_id'])
        bucket['run_ids'].add(m['run_id'])
        bucket['aboutness'].add(m['aboutness'])
        bucket['surfaces'].add(m['surface'])
        bucket['_spans'].extend(
            {'field': span['field'], 'surface': m['surface'], 'start': span['start'], 'end': span['end']}
            for span in m['occurrences']
        )

    result = []
    for bucket in grouped.values():
        version = versions_by_id.get(bucket['version_id'])
        result.append({
            'release_id': bucket['release_id'],
            'person_root_id': bucket['person_root_id'],
            'entity_ids': sorted(bucket['entity_ids']),
            'item_id': bucket['item_id'],
            'version_id': bucket['version_id'],
            'run_ids': sorted(bucket['run_ids']),
            'aboutness': sorted(bucket['aboutness']),
            'surfaces': sorted(bucket['surfaces']),
            'spans': _merge_spans(bucket['_spans'], version=version),
        })
    return sorted(result, key=lambda r: (r['person_root_id'], r['item_id']))


def _relational_coverage_daily(release_read):
    """Compute coverage_daily purely from survivor_items_arrow."""
    items_tbl = survivor_items_arrow(release_read, selections=release_read['release']['selections'])
    item_rows = items_tbl.to_pylist()

    text_group_counts = {}
    for row in item_rows:
        tg = row['text_group_id']
        if tg is not None:
            text_group_counts.setdefault(tg, set()).add(row['item_id'])

    buckets = {}
    for row in item_rows:
        pub_date = row['effective_pub_date']
        date_str = pub_date.isoformat() if pub_date is not None else None
        bucket = buckets.setdefault(date_str, {
            'items': set(),
            'outlets': set(),
            'stories': set(),
            'text_groups': set(),
        })
        bucket['items'].add(row['item_id'])
        if row['outlet_id'] is not None:
            bucket['outlets'].add(row['outlet_id'])
        if row['story_id'] is not None:
            bucket['stories'].add(row['story_id'])
        if row['text_group_id'] is not None:
            bucket['text_groups'].add(row['text_group_id'])

    out = []
    for date_str in sorted(buckets, key=lambda d: (d is None, d or '')):
        b = buckets[date_str]
        out.append({
            'release_id': release_read['release']['id'],
            'date': date_str,
            'undated': date_str is None,
            'items': len(b['items']),
            'outlets': len(b['outlets']),
            'stories': len(b['stories']),
            'identical_text_group_ids': sorted(
                tg for tg in b['text_groups'] if len(text_group_counts[tg]) > 1
            ),
        })
    return out


def test_entity_roots_arrow_schema_and_resolution():
    tbl = entity_roots_arrow(CORPUS)
    assert tbl.schema == ENTITY_ROOTS_SCHEMA
    by_id = {row['entity_id']: row for row in tbl.to_pylist()}
    assert set(by_id) == {P1['id'], P1B['id'], P2['id'], ORG['id']}
    # P1B was merged into P1 via MERGE_P1B_INTO_P1
    assert by_id[P1['id']]['person_root_id'] == P1['id']
    assert by_id[P1B['id']]['person_root_id'] == P1['id']
    assert by_id[P2['id']]['person_root_id'] == P2['id']
    assert by_id[ORG['id']]['entity_type'] == 'organization'


def test_survivor_items_arrow_schema_supersede_and_date32():
    tbl = survivor_items_arrow(CORPUS, selections=SELECTIONS)
    assert tbl.schema == SURVIVOR_ITEMS_SCHEMA
    assert tbl.schema.field('effective_pub_date').type == pa.date32()

    rows = {row['item_id']: row for row in tbl.to_pylist()}
    # I4 is superseded by I5 and must not appear as a survivor row.
    assert I4['id'] not in rows
    assert set(rows) == {I1['id'], I2['id'], I3['id'], I5['id'], I6['id']}

    assert rows[I1['id']]['effective_pub_date'] == date(2026, 10, 18)
    assert rows[I2['id']]['effective_pub_date'] == date(2026, 10, 18)
    assert rows[I3['id']]['effective_pub_date'] is None  # unknown precision, no discovery fallback
    assert rows[I5['id']]['effective_pub_date'] == date(2026, 10, 19)
    # I1 and I2 have identical normalized text and share a text_group_id and story_id.
    assert rows[I1['id']]['text_group_id'] is not None
    assert rows[I1['id']]['text_group_id'] == rows[I2['id']]['text_group_id']
    assert rows[I1['id']]['story_id'] == rows[I2['id']]['story_id']
    assert rows[I3['id']]['text_group_id'] is None


def test_survivor_items_discovery_date_fallback_and_conflict():
    # 1. Versionless item falls back to unambiguous discovery reported_publication date.
    item_mc = _item('mc-bridge')
    corpus_ok = [
        OUTLET_A,
        item_mc,
        _capture('mc-bridge'),
        _discovery('mc-bridge', reported_publication={'precision': 'day', 'date': '2026-10-17', 'basis': 'provider'}),
    ]
    rows_ok = survivor_items_rows(corpus_ok)
    assert len(rows_ok) == 1
    assert rows_ok[0]['effective_pub_date'] == date(2026, 10, 17)
    assert survivor_items_arrow(corpus_ok)['effective_pub_date'].to_pylist() == [date(2026, 10, 17)]

    # 2. Unknown version precision falls back to discovery instant date.
    item_unk = _item('unk-bridge', version_key='unk-bridge')
    ver_unk = _version('unk-bridge', title='Unknown', publication={'precision': 'unknown'})
    corpus_unk = [
        OUTLET_A,
        item_unk,
        _capture('unk-bridge'),
        _extract_run('unk-bridge', _id('capture:unk-bridge')),
        ver_unk,
        _discovery(
            'unk-bridge',
            reported_publication={'precision': 'instant', 'at': '2026-10-16T22:00:00Z', 'basis': 'provider'},
        ),
    ]
    assert survivor_items_rows(corpus_unk)[0]['effective_pub_date'] == date(2026, 10, 16)

    # 3. Conflicting discovery dates remain None (undated).
    corpus_conflict = [
        OUTLET_A,
        item_mc,
        _capture('mc-bridge'),
        _discovery('mc-1', item_key='mc-bridge', reported_publication={'precision': 'day', 'date': '2026-10-17', 'basis': 'provider'}),
        _discovery('mc-2', item_key='mc-bridge', reported_publication={'precision': 'day', 'date': '2026-10-15', 'basis': 'provider'}),
    ]
    assert survivor_items_rows(corpus_conflict)[0]['effective_pub_date'] is None


def test_selected_mentions_arrow_filters_to_selected_resolved_mentions():
    tbl = selected_mentions_arrow(CORPUS, selections=SELECTIONS)
    assert tbl.schema == SELECTED_MENTIONS_SCHEMA
    rows = tbl.to_pylist()
    # M_OLD (unselected run) and M_AMBIGUOUS (ambiguous, no entity_id) are excluded;
    # M1, M2, M_ROE, M_ORG are included.
    assert len(rows) == 4
    assert all(r['entity_id'] is not None for r in rows)


def test_bridges_reproduce_politician_articles_and_coverage_daily():
    rel_read = release_read_of(CORPUS, SELECTIONS)
    decisions = apply_decisions(CORPUS)

    assert _relational_politician_articles(rel_read, decisions) == politician_articles(rel_read, decisions)
    assert _relational_politician_articles(rel_read) == politician_articles(rel_read)
    assert _relational_coverage_daily(rel_read) == coverage_daily(rel_read, decisions)
