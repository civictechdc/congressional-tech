"""Integration tests: news_lake records and C9 views on the docspec-rs backend.

Each test drives a fresh ``docspec`` workspace through
``news_lake.storage.docspec_backend`` and asserts parity with the Python
owners: ``Coordinator._merge_upsert`` for upsert merging (C1) and
``analysis.views.politician_articles`` / ``coverage_daily`` for the views.
Corpus fixtures mirror ``tests/test_analysis_views.py`` (deterministic uuid5
ids), and every admitted corpus passes ``check_corpus``.
"""
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pyarrow as pa
import pytest

from news_lake.analysis import bridges, coverage_daily
from news_lake.analysis.views import politician_articles as politician_articles_views
from news_lake.contract import check_corpus
from news_lake.contract.records import KIND_TABLES
from news_lake.storage.coordinator import _merge_upsert
from news_lake.storage.docspec_backend import (
    AppendCollisionError,
    DocSpecClient,
    DocSpecFailure,
    DocSpecLake,
    DocSpecNewsViews,
    _ArrowHttpStream,
    dataset_id_for,
    merge_upsert_batch,
    restore_application_schema,
    table_records,
    version_ref,
)

docspec = DocSpecClient.default_binary_path()
pytestmark = pytest.mark.skipif(
    not Path(docspec).exists(), reason=f'docspec binary is not available at {docspec}')

AT = '2026-10-20T04:00:00Z'
_id = lambda key: str(uuid5(NAMESPACE_URL, 'news-lake-views-test:' + key))


def _hash(name):
    import hashlib

    return hashlib.sha256(name.encode()).hexdigest()


def _entity(key, name, entity_type='person', aliases=(), identifiers=()):
    return {'kind': 'entity', 'id': _id('entity:' + key), 'recorded_at': AT,
            'entity_type': entity_type, 'name': name, 'aliases': list(aliases),
            'identifiers': list(identifiers)}


P1 = _entity('p1', 'Alex Doe', identifiers=[{'scheme': 'fixture', 'value': 'p1'}])
# A distinct scheme, so merging P1B into P1 corroborates identity instead of
# colliding authoritative ids (C6).
P1B = _entity('p1b', 'Alex Doe', aliases=[{'value': 'A. Doe', 'language': 'en'}],
              identifiers=[{'scheme': 'fixture-alias', 'value': 'p1b'}])
P2 = _entity('p2', 'Robin Roe', identifiers=[{'scheme': 'fixture', 'value': 'p2'}])
ORG = _entity('org', 'Example Party', entity_type='organization',
              identifiers=[{'scheme': 'fixture', 'value': 'org'}])
MERGE_P1B_INTO_P1 = {
    'kind': 'identity_decision', 'id': _id('decision:merge'), 'recorded_at': AT,
    'action': 'same_as', 'left_id': P1B['id'], 'right_id': P1['id'],
    'decided_by': 'fixture:reviewer', 'reason': 'Fixture merge of the alias entity.',
}

OUTLET_A = {'kind': 'outlet', 'id': _id('outlet:a'), 'recorded_at': AT, 'name': 'Example News',
            'domains': ['a.example']}
OUTLET_B = {'kind': 'outlet', 'id': _id('outlet:b'), 'recorded_at': AT, 'name': 'Other News',
            'domains': ['b.example']}


def _capture(key):
    return {'kind': 'capture', 'id': _id('capture:' + key), 'recorded_at': AT, 'provider': 'rss',
            'request_url': f'https://a.example/{key}', 'observed_at': AT, 'http_status': 200,
            'access': 'redistributable', 'payload_uri': f's3://fixture/{key}',
            'payload_hash': _hash('capture:' + key), 'media_type': 'text/html',
            'rights_basis': 'Synthetic fixture.', 'status': 'succeeded'}


def _discovery(key, *, item_key=None, reported_publication=None):
    item_key = item_key or key
    record = {'kind': 'discovery', 'id': _id('discovery:' + key), 'recorded_at': AT,
              'capture_id': _id('capture:' + item_key), 'item_id': _id('item:' + item_key),
              'provider': 'mediacloud', 'url': f'https://a.example/{key}', 'observed_at': AT,
              'mode': 'live'}
    if reported_publication is not None:
        record['reported_publication'] = reported_publication
    return record


def _extract_run(key, capture_id):
    return {'kind': 'run', 'id': _id('run-extract:' + key), 'recorded_at': AT, 'processor': 'extract',
            'processor_version': 'fixture-1', 'config_hash': _hash('extract:' + key),
            'input_hash': _hash('extract-inputs:' + key),
            'inputs': [{'kind': 'capture', 'id': capture_id}], 'mode': 'live', 'status': 'succeeded',
            'started_at': AT, 'finished_at': AT}


def _item(key, *, outlet=OUTLET_A, version_key=None, superseded_by=None):
    record = {'kind': 'item', 'id': _id('item:' + key), 'recorded_at': AT, 'outlet_id': outlet['id'],
              'canonical_url': f"https://{outlet['domains'][0]}/{key}", 'url_aliases': [],
              'content_type': 'news_article', 'first_seen_at': AT}
    if version_key is not None:
        record['current_version_id'] = _id('version:' + version_key)
    if superseded_by is not None:
        record['superseded_by'] = _id('item:' + superseded_by)
    return record


def _version(key, *, title, publication, text=None):
    record = {'kind': 'version', 'id': _id('version:' + key), 'recorded_at': AT,
              'item_id': _id('item:' + key), 'capture_id': _id('capture:' + key),
              'run_id': _id('run-extract:' + key), 'title': title, 'publication': publication,
              'access': 'metadata_only'}
    if text is not None:
        record['access'] = 'restricted'
        record['rights_basis'] = 'Synthetic fixture.'
        record['text'] = text
        record['text_hash'] = _hash(text)
    return record


def _run(key, *, processor, config, inputs, finished_at):
    return {'kind': 'run', 'id': _id('run:' + key), 'recorded_at': finished_at, 'processor': processor,
            'processor_version': 'fixture-1', 'config_hash': _hash(processor + ':' + config),
            'input_hash': _hash(processor + '-inputs:' + key),
            'inputs': [{'kind': 'version', 'id': identifier} for identifier in inputs],
            'mode': 'reprocess', 'status': 'succeeded', 'started_at': AT, 'finished_at': finished_at}


def _mention(key, *, version_key, surface, resolution, occurrences, entity_key=None, aboutness='primary'):
    record = {'kind': 'mention', 'id': _id('mention:' + key), 'recorded_at': AT,
              'version_id': _id('version:' + version_key), 'run_id': _id('run:link2'),
              'surface': surface, 'resolution': resolution, 'aboutness': aboutness,
              'occurrences': occurrences}
    if entity_key is not None:
        record['entity_id'] = _id('entity:' + entity_key)
    return record


def _story(key, run_key):
    return {'kind': 'story', 'id': _id('story:' + key), 'recorded_at': AT, 'run_id': _id('run:' + run_key)}


def _member(story_key, version_key, run_key):
    return {'kind': 'story_member', 'id': _id('member:' + story_key + ':' + version_key),
            'recorded_at': AT, 'story_id': _id('story:' + story_key),
            'version_id': _id('version:' + version_key), 'run_id': _id('run:' + run_key)}


# -- the scenario (mirrors tests/test_analysis_views.py) --------------------------------

V1 = _version('v1', title='Alex Doe speaks at the council',
              publication={'precision': 'day', 'date': '2026-10-18', 'basis': 'publisher'},
              text='Council member Alex Doe and Alex Doe spoke.')
V2 = _version('v2', title='Council roundup',
              publication={'precision': 'day', 'date': '2026-10-18', 'basis': 'publisher'},
              text='Council member Alex Doe and Alex Doe spoke.')  # identical text: syndication
V3 = _version('v3', title='Who is Alex Doe?', publication={'precision': 'unknown'})
V5 = _version('v5', title='Robin Roe resigns',
              publication={'precision': 'instant', 'at': '2026-10-19T18:30:00Z', 'basis': 'publisher'},
              text='Robin Roe resigned Monday.')
V6 = _version('v6', title='Example Party announces platform',
              publication={'precision': 'day', 'date': '2026-10-18', 'basis': 'publisher'})

I1 = _item('v1', version_key='v1')
I2 = _item('v2', outlet=OUTLET_B, version_key='v2')
I3 = _item('v3', version_key='v3')
I4 = _item('v4')  # superseded duplicate of the Robin Roe appearance
I5 = _item('v5', version_key='v5')
I6 = _item('v6', version_key='v6')
I4['superseded_by'] = I5['id']

LINKED = [_id('version:' + key) for key in ('v1', 'v3', 'v5', 'v6')]
RUN_LINK_OLD = _run('link1', processor='mentions', config='model-A', inputs=[_id('version:v1')],
                    finished_at='2026-10-20T05:00:00Z')
RUN_LINK = _run('link2', processor='mentions', config='model-B', inputs=LINKED,
                finished_at='2026-10-20T06:00:00Z')
RUN_CLUSTER = _run('cluster1', processor='cluster', config='identical-text',
                   inputs=[_id('version:' + key) for key in ('v1', 'v2', 'v5')],
                   finished_at='2026-10-20T06:30:00Z')
STORY_SYNDICATION = _story('syndication', 'cluster1')
STORY_ROE = _story('roe', 'cluster1')

M_OLD = _mention('old', version_key='v1', surface='Alex Doe', resolution='resolved',
                 occurrences=[{'field': 'title', 'start': 0, 'end': 8}], entity_key='p1')
M1 = _mention('m1', version_key='v1', surface='Alex Doe', resolution='resolved',
              occurrences=[{'field': 'title', 'start': 0, 'end': 8},
                           {'field': 'text', 'start': 15, 'end': 23}], entity_key='p1')
M2 = _mention('m2', version_key='v1', surface='Alex Doe', resolution='resolved',
              occurrences=[{'field': 'title', 'start': 0, 'end': 8},
                           {'field': 'text', 'start': 28, 'end': 36}], entity_key='p1b')
M_AMBIGUOUS = _mention('amb', version_key='v3', surface='Alex Doe', resolution='ambiguous',
                       occurrences=[{'field': 'title', 'start': 7, 'end': 15}], aboutness='unknown')
M_ROE = _mention('roe', version_key='v5', surface='Robin Roe', resolution='resolved',
                 occurrences=[{'field': 'title', 'start': 0, 'end': 9},
                              {'field': 'text', 'start': 0, 'end': 9}], entity_key='p2')
M_ORG = _mention('org', version_key='v6', surface='Example Party', resolution='resolved',
                 occurrences=[{'field': 'title', 'start': 0, 'end': 13}], entity_key='org')
M_OLD['run_id'] = RUN_LINK_OLD['id']  # the old run's mention carries its own run id

SHELLS = []
for _key in ('v1', 'v2', 'v3', 'v5', 'v6'):
    SHELLS.extend([_capture(_key), _extract_run(_key, _id('capture:' + _key))])

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

COVERAGE_CORPUS = [
    OUTLET_A,
    _capture('ca'), _extract_run('ca', _id('capture:ca')),
    _item('ca', version_key='ca'),  # 2002 backfill article
    _version('ca', title='Archive floor speech',
             publication={'precision': 'day', 'date': '2002-05-14', 'basis': 'publisher'}),
    _capture('cb'), _extract_run('cb', _id('capture:cb')),
    _item('cb', version_key='cb'),  # current article
    _version('cb', title='Live coverage',
             publication={'precision': 'day', 'date': '2026-10-18', 'basis': 'publisher'}),
    _capture('cc'), _extract_run('cc', _id('capture:cc')),
    _item('cc', version_key='cc'),  # unknown publication precision: undated
    _version('cc', title='Undated story', publication={'precision': 'unknown'}),
]

BACKFILL_RECORDS = [
    _capture('cd'), _extract_run('cd', _id('capture:cd')),
    _item('cd', version_key='cd'),  # a second 2002 article
    _version('cd', title='Second archive story',
             publication={'precision': 'day', 'date': '2002-05-14', 'basis': 'publisher'}),
]


def release_read_of(records, selections):
    """Build the read_release shape directly; storage tests cover its fidelity."""
    from news_lake.contract.records import CONTENT_TABLES, validate_shape

    tables = {}
    for record in records:
        tables.setdefault(KIND_TABLES[record['kind']], []).append(record)
    release = {'kind': 'release', 'id': _id('release:views'), 'recorded_at': AT,
               'contract_version': '0.1.0',
               'snapshots': [{'table': table, 'table_uuid': _id('uuid:' + table)}
                             for table in CONTENT_TABLES],
               'selections': list(selections), 'checkpoints': []}
    validate_shape(release)
    return {'release': release, 'tables': tables}


def _expected_datasets(records):
    return {dataset_id_for(KIND_TABLES[record['kind']]) for record in records}


def _records_of(lake, dataset):
    return sorted(table_records(lake.read_dataset(dataset)), key=lambda record: record['id'])


def _compact(rows):
    """Drop explicit None fields so recomputed bridge rows compare with stored rows
    (the native readback omits absent-optional nulls; bridge rows carry Nones)."""
    return [
        {key: value for key, value in row.items() if value is not None}
        for row in rows
    ]


# -- Test 1 -----------------------------------------------------------------------------


def test_admit_seal_and_read_arrow(tmp_path):
    """Admit a valid corpus, seal one generation, and read records back natively."""
    check_corpus(CORPUS)
    client = DocSpecClient(tmp_path / 'ws')
    lake = DocSpecLake(client)

    pins = lake.commit_records(CORPUS, generation='g1', family='news')
    expected = _expected_datasets(CORPUS)
    assert set(pins) == expected
    for pin in pins.values():
        assert pin['verified'] is True
        assert pin['dataset']['relationship'] == {
            'kind': 'coupled', 'family': 'news', 'generation': 'g1'}

    seal = lake.seal('g1', family='news')
    assert seal['family'] == 'news'
    assert seal['generation'] == 'g1'
    assert set(seal['members']) == expected
    for dataset, member in seal['members'].items():
        assert version_ref(client.latest(dataset)) == member  # latest pins are the sealed members

    # Native readback restores the exact submitted records (contract round trip).
    assert _records_of(lake, 'news_versions') == sorted(
        (record for record in CORPUS if record['kind'] == 'version'), key=lambda record: record['id'])
    assert _records_of(lake, 'news_mentions') == sorted(
        (record for record in CORPUS if record['kind'] == 'mention'), key=lambda record: record['id'])
    assert _records_of(lake, 'news_entities') == sorted(
        (record for record in CORPUS if record['kind'] == 'entity'), key=lambda record: record['id'])


# -- Test 2 -----------------------------------------------------------------------------


def test_c1_upsert_merge_across_polls(tmp_path):
    """Evidence unions survive later polls; older polls never regress scalars (C1)."""
    client = DocSpecClient(tmp_path / 'ws')
    lake = DocSpecLake(client)

    at_early = '2026-10-19T00:00:00Z'
    at_first = '2026-10-20T04:00:00Z'
    at_later = '2026-10-21T09:00:00Z'
    outlet_first = {'kind': 'outlet', 'id': _id('outlet:poll'), 'recorded_at': at_first,
                    'name': 'Example News', 'domains': ['a.example']}
    outlet_second = dict(outlet_first, recorded_at=at_later, name='Renamed News',
                         domains=['renamed.example'],
                         feed_urls=['https://renamed.example/rss.xml'])
    outlet_older = dict(outlet_first, recorded_at=at_early, name='Old Name',
                        domains=['old.example'], feed_urls=['https://old.example/feed'])

    lake.commit_records([outlet_first])
    lake.commit_records([outlet_second])
    stored = _records_of(lake, 'news_outlets')
    expected = merge_upsert_batch([outlet_first], [outlet_second])
    assert expected == [_merge_upsert(outlet_first, outlet_second)]  # batch helper == coordinator
    assert stored == expected
    assert stored[0]['name'] == 'Renamed News'  # newer poll wins scalars
    assert stored[0]['domains'] == ['a.example', 'renamed.example']  # evidence union

    # A third, OLDER poll: still unions its evidence, never regresses scalars.
    lake.commit_records([outlet_older])
    stored = _records_of(lake, 'news_outlets')
    expected = merge_upsert_batch(expected, [outlet_older])
    assert expected == [_merge_upsert(_merge_upsert(outlet_first, outlet_second), outlet_older)]
    assert stored == expected
    assert stored[0]['recorded_at'] == at_later
    assert stored[0]['name'] == 'Renamed News'
    assert stored[0]['domains'] == ['a.example', 'renamed.example', 'old.example']
    assert stored[0]['feed_urls'] == ['https://renamed.example/rss.xml',
                                      'https://old.example/feed']

    # Item polls exercise first_seen_at (items carry it): the newer poll
    # reports an earlier first seen and the merge keeps the minimum. A third,
    # OLDER poll cannot regress it: _merge_upsert restores prior scalars for
    # stale polls before the min, so its value is dropped (parity means
    # matching the coordinator's actual semantics).
    item_first = _item('poll')
    item_second = dict(item_first, recorded_at=at_later,
                       url_aliases=['https://a.example/redirect-1'],
                       first_seen_at=at_early)
    item_older = dict(item_first, recorded_at=at_early,
                      url_aliases=['https://a.example/legacy'], first_seen_at=at_first)
    lake.commit_records([item_first])
    lake.commit_records([item_second])
    lake.commit_records([item_older])
    stored_item = _records_of(lake, 'news_items')
    expected_item = merge_upsert_batch(merge_upsert_batch([item_first], [item_second]), [item_older])
    assert stored_item == expected_item
    assert stored_item[0]['first_seen_at'] == at_early  # chronologically earliest reported
    assert stored_item[0]['recorded_at'] == at_later  # latest poll instant
    assert stored_item[0]['url_aliases'] == ['https://a.example/redirect-1',
                                             'https://a.example/legacy']

    # Replayed identical polls are no-ops (same native version stays selected).
    version_before = client.latest('news_items')['dataset']['version']
    lake.commit_records([item_second])
    assert client.latest('news_items')['dataset']['version'] == version_before


# -- Test 3 -----------------------------------------------------------------------------


def test_incremental_join_politician_articles(tmp_path):
    """selected_mentions ⋈ entity_roots: full, then incremental after a same_as."""
    initial = [record for record in CORPUS if record['id'] != MERGE_P1B_INTO_P1['id']]
    before = release_read_of(initial, SELECTIONS)
    client = DocSpecClient(tmp_path / 'ws')
    lake = DocSpecLake(client)
    lake.commit_records(initial)

    views = DocSpecNewsViews(client)
    views.materialize(before)

    mentions_arrow = lake.read_dataset('selected_mentions')
    assert pa.types.is_list(mentions_arrow.schema.field('occurrences').type)
    assert pa.types.is_struct(mentions_arrow.schema.field('occurrences').type.value_type)

    got_full = views.politician_articles(before, mode='full')
    joined_arrow = lake.read_dataset('politician_articles')
    assert pa.types.is_list(joined_arrow.schema.field('occurrences').type)
    assert pa.types.is_struct(joined_arrow.schema.field('occurrences').type.value_type)
    assert got_full == politician_articles_views(before)  # parity with the Python view
    assert sorted((row['person_root_id'], row['item_id']) for row in got_full) == sorted(
        [(P1['id'], I1['id']), (P1B['id'], I1['id']), (P2['id'], I5['id'])])

    cov_full = views.coverage_daily(before, mode='full')
    cov_arrow = lake.read_dataset('coverage_daily')
    assert pa.types.is_list(cov_arrow.schema.field('identical_text_group_ids').type)
    assert cov_full == coverage_daily(before)
    cov_by_date = {row['date']: row for row in cov_full}
    assert len(cov_by_date['2026-10-18']['identical_text_group_ids']) == 1
    assert cov_by_date['2026-10-19']['identical_text_group_ids'] == []

    # Apply the same_as decision: admit it, rebuild the roots bridge with it,
    # and update the native entity_roots dataset by key.
    lake.commit_records([MERGE_P1B_INTO_P1])
    merged_corpus = initial + [MERGE_P1B_INTO_P1]
    new_roots = _compact(bridges.entity_roots_rows(merged_corpus))
    current = {row['entity_id']: row
               for row in table_records(lake.read_dataset('entity_roots'))}
    changed = [row for row in new_roots if current.get(row['entity_id']) != row]
    assert changed == [{'entity_id': P1B['id'], 'person_root_id': P1['id'],
                        'entity_type': 'person', 'name': 'Alex Doe'}]
    roots_pin = client.latest('entity_roots')
    client.update_table('entity_roots', 'entity-roots-same-as-1',
                        roots_pin['dataset']['version'], ['entity_id'],
                        pa.Table.from_pylist(changed, schema=bridges.ENTITY_ROOTS_SCHEMA))

    after = release_read_of(merged_corpus, SELECTIONS)
    got_incremental = views.politician_articles(after, mode='incremental')
    assert got_incremental == politician_articles_views(after)  # parity after the merge
    assert sorted((row['person_root_id'], row['item_id'])
                  for row in got_incremental) == sorted(
        [(P1['id'], I1['id']), (P2['id'], I5['id'])])
    doe = next(row for row in got_incremental if row['person_root_id'] == P1['id'])
    assert doe['entity_ids'] == sorted([P1['id'], P1B['id']])  # both aliases' mentions
    assert doe['surfaces'] == ['Alex Doe'] and doe['aboutness'] == ['primary']


# -- Test 4 -----------------------------------------------------------------------------


def test_incremental_coverage_daily_undated(tmp_path):
    """Date32 aggregation: dated and undated buckets, full then incremental."""
    corpus = COVERAGE_CORPUS
    check_corpus(corpus)
    read = release_read_of(corpus, [])
    client = DocSpecClient(tmp_path / 'ws')
    lake = DocSpecLake(client)
    lake.commit_records(corpus)

    views = DocSpecNewsViews(client)
    views.materialize(read)

    got = views.coverage_daily(read, mode='full')
    assert got == coverage_daily(read)  # parity with the Python view
    by_date = {row['date']: row for row in got}
    assert set(by_date) == {'2002-05-14', '2026-10-18', None}
    assert by_date['2002-05-14']['items'] == 1
    assert by_date['2026-10-18']['items'] == 1
    assert by_date[None]['undated'] is True and by_date[None]['items'] == 1
    assert got[-1]['undated'] is True  # the undated bucket sorts last, never a fake date

    # Add a second 2002 article through the append tables, then update the
    # native survivor_items dataset with its new bridge row.
    lake.commit_records(BACKFILL_RECORDS)
    merged = corpus + BACKFILL_RECORDS
    merged_read = release_read_of(merged, [])
    new_rows = _compact(bridges.survivor_items_rows(merged))
    current = {row['item_id']: row
               for row in table_records(lake.read_dataset('survivor_items'))}
    changed = [row for row in new_rows if current.get(row['item_id']) != row]
    assert len(changed) == 1
    assert changed[0]['item_id'] == _id('item:cd')
    assert changed[0]['effective_pub_date'].isoformat() == '2002-05-14'
    items_pin = client.latest('survivor_items')
    client.update_table('survivor_items', 'survivor-items-backfill-1',
                        items_pin['dataset']['version'], ['item_id'],
                        pa.Table.from_pylist(changed, schema=bridges.SURVIVOR_ITEMS_SCHEMA))

    got_incremental = views.coverage_daily(merged_read, mode='incremental')
    assert got_incremental == coverage_daily(merged_read)  # parity after the backfill
    incremental_by_date = {row['date']: row for row in got_incremental}
    assert incremental_by_date['2002-05-14']['items'] == 2
    assert incremental_by_date[None]['items'] == 1  # undated bucket untouched


# -- Test 5 -----------------------------------------------------------------------------


def test_serve_loopback_http(tmp_path):
    """The same admit/seal/read flow through the persistent loopback HTTP host."""
    check_corpus(CORPUS)
    client = DocSpecClient(tmp_path / 'ws')
    with client.serve():
        lake = DocSpecLake(client)
        pins = lake.commit_records(CORPUS, generation='g1', family='news')
        assert set(pins) == _expected_datasets(CORPUS)

        seal = lake.seal('g1', family='news')
        assert set(seal['members']) == set(pins)
        for dataset, member in seal['members'].items():
            assert version_ref(client.latest(dataset)) == member

        # Arrow reads stream over HTTP into the same record shapes.
        assert _records_of(lake, 'news_versions') == sorted(
            (record for record in CORPUS if record['kind'] == 'version'),
            key=lambda record: record['id'])
        version = client.latest('news_versions')['dataset']['version']
        historical = client.release('news_versions', version)
        assert historical['dataset']['version'] == version

    # After the host stops, the CLI transport serves the same workspace.
    assert _records_of(lake, 'news_versions') == sorted(
        (record for record in CORPUS if record['kind'] == 'version'),
        key=lambda record: record['id'])


# -- Test 6 (ct-qkvr): multi-batch append preservation, replay, and collision refusal ---


def test_multi_batch_append_preserves_prior_records_and_files(tmp_path):
    """Append commits across distinct polls preserve earlier rows and Parquet files."""
    client = DocSpecClient(tmp_path / 'ws')
    lake = DocSpecLake(client)

    batch1 = [
        _capture('b1'),
        _extract_run('b1', _id('capture:b1')),
        _version('b1', title='First batch article',
                 publication={'precision': 'day', 'date': '2026-10-18', 'basis': 'publisher'},
                 text='Alex Doe spoke first.'),
        _mention('b1', version_key='b1', surface='Alex Doe', resolution='resolved',
                 occurrences=[{'field': 'title', 'start': 0, 'end': 8}], entity_key='p1'),
    ]
    batch2 = [
        _capture('b2'),
        _extract_run('b2', _id('capture:b2')),
        _version('b2', title='Second batch article',
                 publication={'precision': 'day', 'date': '2026-10-19', 'basis': 'publisher'},
                 text='Robin Roe spoke second.'),
        _mention('b2', version_key='b2', surface='Robin Roe', resolution='resolved',
                 occurrences=[{'field': 'title', 'start': 0, 'end': 9}], entity_key='p2'),
    ]

    pins1 = lake.commit_records(batch1)
    pins2 = lake.commit_records(batch2)

    for dataset, kind in (
        ('news_captures', 'capture'),
        ('news_versions', 'version'),
        ('news_mentions', 'mention'),
    ):
        assert pins2[dataset]['dataset']['version'] != pins1[dataset]['dataset']['version']
        # Unchanged Parquet files from batch 1 are preserved in batch 2's manifest.
        files1 = {
            entry['path']
            for entry in pins1[dataset]['dataset']['groups']['source']['objects']
            if entry['path'].endswith('.parquet')
        }
        files2 = {
            entry['path']
            for entry in pins2[dataset]['dataset']['groups']['source']['objects']
            if entry['path'].endswith('.parquet')
        }
        assert files1 and files1.issubset(files2)
        expected = sorted(
            [r for r in batch1 + batch2 if r['kind'] == kind],
            key=lambda r: r['id'],
        )
        assert _records_of(lake, dataset) == expected

    # Replaying an already-committed append batch is an idempotent no-op.
    pins_replay = lake.commit_records(batch1)
    assert (pins_replay['news_captures']['dataset']['version']
            == pins2['news_captures']['dataset']['version'])

    # Reusing an existing append id with altered content raises AppendCollisionError.
    colliding_capture = dict(_capture('b1'), http_status=404)
    with pytest.raises(AppendCollisionError, match='append-only news_captures'):
        lake.commit_records([colliding_capture])


# -- Test 7 (ct-nloa): bounded upsert via update_table and key-filtered reads ----------


def test_bounded_upsert_updates_only_changed_rows_across_unrelated_records(tmp_path):
    """Upsert reads only incoming keys and updates only changed rows via update_table."""
    client = DocSpecClient(tmp_path / 'ws')
    lake = DocSpecLake(client)

    # Seed 50 unrelated outlets across two initial batches so the dataset has multiple files.
    initial_a = [
        {'kind': 'outlet', 'id': _id(f'outlet:bulk-{i}'), 'recorded_at': AT,
         'name': f'Outlet {i}', 'domains': [f'o{i}.example']}
        for i in range(25)
    ]
    initial_b = [
        {'kind': 'outlet', 'id': _id(f'outlet:bulk-{i}'), 'recorded_at': AT,
         'name': f'Outlet {i}', 'domains': [f'o{i}.example']}
        for i in range(25, 50)
    ]
    lake.commit_records(initial_a)
    pin_before = lake.commit_records(initial_b)['news_outlets']

    # Spy on update_table and _existing_by_ids to prove work is bounded to incoming IDs.
    observed_updates = []
    orig_update_table = client.update_table

    def spy_update_table(dataset, operation, base_version, keys, table, **kwargs):
        observed_updates.append((dataset, len(table), keys))
        return orig_update_table(dataset, operation, base_version, keys, table, **kwargs)

    client.update_table = spy_update_table

    target_id = _id('outlet:bulk-7')
    existing_subset = lake._existing_by_ids(pin_before, 'outlet', {target_id})
    assert list(existing_subset.keys()) == [target_id]

    updated_outlet = {
        'kind': 'outlet', 'id': target_id, 'recorded_at': '2026-10-21T09:00:00Z',
        'name': 'Outlet 7 Renamed', 'domains': ['o7-new.example'],
    }
    pin_after = lake.commit_records([updated_outlet])['news_outlets']

    assert observed_updates == [('news_outlets', 1, ['id'])]
    # Unchanged Parquet file from the second batch (indices 25..49) is reused without rewrite.
    files_before = {
        entry['path']
        for entry in pin_before['dataset']['groups']['source']['objects']
    }
    files_after = {
        entry['path']
        for entry in pin_after['dataset']['groups']['source']['objects']
    }
    assert len(files_before & files_after) >= 1

    all_outlets = _records_of(lake, 'news_outlets')
    assert len(all_outlets) == 50
    by_id = {row['id']: row for row in all_outlets}
    assert by_id[target_id]['name'] == 'Outlet 7 Renamed'
    assert by_id[target_id]['domains'] == ['o7.example', 'o7-new.example']


# -- Test 8 (ct-egpe): schema restoration, retained producer inputs, IPC EOS check -----


def test_boundary_hardening_schema_retention_and_ipc_framing(tmp_path):
    """Explicit schema restoration, retained inputs on indeterminate error, and IPC EOS."""
    import io

    # 1. restore_application_schema restores UInt64 only when declared, preserving Decimal128.
    declared = pa.schema([
        pa.field('u64_col', pa.uint64()),
        pa.field('dec_col', pa.decimal128(20, 0)),
    ])
    stored = pa.Table.from_pylist(
        [{'u64_col': 42, 'dec_col': 99}],
        schema=pa.schema([
            pa.field('u64_col', pa.decimal128(20, 0)),
            pa.field('dec_col', pa.decimal128(20, 0)),
        ]),
    )
    restored = restore_application_schema(stored, declared)
    assert restored.schema.field('u64_col').type == pa.uint64()
    assert restored.schema.field('dec_col').type == pa.decimal128(20, 0)

    # 2. _ArrowHttpStream rejects truncated IPC streams missing the 8-byte EOS marker.
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, pa.schema([pa.field('x', pa.int64())])) as writer:
        writer.write_table(pa.Table.from_pylist([{'x': 1}]))
    valid_bytes = sink.getvalue().to_pybytes()
    assert valid_bytes.endswith(b'\xff\xff\xff\xff\x00\x00\x00\x00')

    stream_ok = _ArrowHttpStream(io.BytesIO(valid_bytes))
    assert pa.ipc.open_stream(stream_ok).read_all().to_pylist() == [{'x': 1}]
    stream_ok.verify_eos()

    truncated_bytes = valid_bytes[:-8]
    stream_bad = _ArrowHttpStream(io.BytesIO(truncated_bytes))
    assert pa.ipc.open_stream(stream_bad).read_all().to_pylist() == [{'x': 1}]
    with pytest.raises(OSError, match='lacks a complete stream terminator'):
        stream_bad.verify_eos()

    # 3. Producer input staging retains files on indeterminate ('worker') errors
    # and cleans them up on deterministic ('validation') refusals.
    client = DocSpecClient(tmp_path / 'ws')
    table = pa.Table.from_pylist([{'id': '1'}])
    orig_call = client._call

    def fake_worker_call(*args, dispatch=None):
        if args and args[0] == 'hash':
            return orig_call(*args, dispatch=dispatch)
        if dispatch is not None:
            dispatch['submitted'] = True
        raise DocSpecFailure(
            args, 500, 'worker: simulated crash', status_code=500, code='worker'
        )

    client._call = fake_worker_call
    with pytest.raises(DocSpecFailure):
        client.run_table(table, 'news_outlets', 'op-crash')
    retained = client.retained_producer_inputs()
    assert len(retained) == 1
    assert Path(retained[0]['input']).exists()
    assert Path(retained[0]['request']).exists()

    def fake_validation_call(*args, dispatch=None):
        if args and args[0] == 'hash':
            return orig_call(*args, dispatch=dispatch)
        if dispatch is not None:
            dispatch['submitted'] = True
        raise DocSpecFailure(
            args, 422, 'validation: bad schema', status_code=422, code='validation'
        )

    client._call = fake_validation_call
    with pytest.raises(DocSpecFailure):
        client.run_table(table, 'news_outlets', 'op-invalid')
    # The deterministic validation refusal cleans up its staging dir; only op-crash remains.
    assert client.retained_producer_inputs() == retained


# -- Test 9 (ct-jo8n, ct-gf8i): update_bridges, pin isolation, cross-day syndication ---


def test_update_bridges_pin_isolation_and_cross_day_syndication(tmp_path):
    """views.update_bridges diffs bridges, pins exact versions, and tracks cross-day stories."""
    from news_lake.analysis.cluster import text_group_key

    # Make V2 publish on 2026-10-19 while sharing identical text with V1 (2026-10-18).
    v2_next_day = _version(
        'v2', title='Council roundup next day',
        publication={'precision': 'day', 'date': '2026-10-19', 'basis': 'publisher'},
        text='Council member Alex Doe and Alex Doe spoke.',
    )
    corpus_initial = [
        (v2_next_day if r['id'] == V2['id'] else r)
        for r in CORPUS
        if r['id'] != MERGE_P1B_INTO_P1['id']
    ]
    check_corpus(corpus_initial)
    before = release_read_of(corpus_initial, SELECTIONS)

    client = DocSpecClient(tmp_path / 'ws')
    lake = DocSpecLake(client)
    lake.commit_records(corpus_initial)

    views = DocSpecNewsViews(client)
    views.materialize(before)

    pa_before = views.politician_articles(before, mode='full')
    assert pa_before == politician_articles_views(before)
    cov_before = views.coverage_daily(before, mode='full')
    assert cov_before == coverage_daily(before)
    cov_by_date = {row['date']: row for row in cov_before}
    # Cross-day syndication: identical text group spans 2026-10-18 (V1) and 2026-10-19 (V2),
    # so both days carry the shared text_group_key in identical_text_group_ids.
    expected_group = text_group_key(V1['text'])
    assert cov_by_date['2026-10-18']['identical_text_group_ids'] == [expected_group]
    assert cov_by_date['2026-10-19']['identical_text_group_ids'] == [expected_group]

    # Now apply MERGE_P1B_INTO_P1 via views.update_bridges(...) instead of manual update_table.
    lake.commit_records([MERGE_P1B_INTO_P1])
    after_corpus = corpus_initial + [MERGE_P1B_INTO_P1]
    after = release_read_of(after_corpus, SELECTIONS)

    roots_v_before = views.pins['entity_roots']['dataset']['version']
    mentions_v_before = views.pins['selected_mentions']['dataset']['version']
    items_v_before = views.pins['survivor_items']['dataset']['version']

    views.update_bridges(after)
    assert views.pins['entity_roots']['dataset']['version'] != roots_v_before
    # Unchanged bridges are not rewritten.
    assert views.pins['selected_mentions']['dataset']['version'] == mentions_v_before
    assert views.pins['survivor_items']['dataset']['version'] == items_v_before

    # Simulate an unpinned concurrent advance on entity_roots AFTER views.update_bridges
    # pinned the release: views.politician_articles(mode='incremental') must use views.pins,
    # not unpinned client.latest.
    rogue_root = [{'entity_id': P1['id'], 'person_root_id': P2['id'],
                   'entity_type': 'person', 'name': 'Rogue Override'}]
    client.update_table(
        'entity_roots', 'rogue-advance',
        views.pins['entity_roots']['dataset']['version'], ['entity_id'],
        pa.Table.from_pylist(rogue_root, schema=bridges.ENTITY_ROOTS_SCHEMA),
    )
    assert (client.latest('entity_roots')['dataset']['version']
            != views.pins['entity_roots']['dataset']['version'])

    got_inc = views.politician_articles(after, mode='incremental')
    assert got_inc == politician_articles_views(after)


# -- Test 10 (ct-4nyy): C5 rights and capture expiry enforcement on native export ------


def test_export_authorized_enforces_c5_rights_and_capture_expiry(tmp_path):
    """views.export_authorized scrubs restricted/expired payloads before native export."""
    cap_pub_ok = dict(
        _capture('pub-ok'),
        access='redistributable',
        retain_until='2026-10-25T00:00:00Z',
    )
    cap_pub_expired = dict(
        _capture('pub-exp'),
        access='redistributable',
        retain_until='2026-10-19T00:00:00Z',
    )
    cap_restricted = dict(
        _capture('rest'),
        access='restricted',
        retain_until='2026-10-25T00:00:00Z',
    )

    ver_pub_ok = dict(
        _version('pub-ok', title='Public OK',
                 publication={'precision': 'day', 'date': '2026-10-18', 'basis': 'publisher'},
                 text='Redistributable body text.'),
        access='redistributable',
    )
    ver_pub_expired = dict(
        _version('pub-exp', title='Public Expired Capture',
                 publication={'precision': 'day', 'date': '2026-10-18', 'basis': 'publisher'},
                 text='Body text whose capture expired.'),
        access='redistributable',
    )
    ver_restricted = _version(
        'rest', title='Restricted Article',
        publication={'precision': 'day', 'date': '2026-10-18', 'basis': 'publisher'},
        text='Restricted body text.',
    )

    export_corpus = [
        OUTLET_A,
        cap_pub_ok, _extract_run('pub-ok', cap_pub_ok['id']),
        _item('pub-ok', version_key='pub-ok'), ver_pub_ok,
        cap_pub_expired, _extract_run('pub-exp', cap_pub_expired['id']),
        _item('pub-exp', version_key='pub-exp'), ver_pub_expired,
        cap_restricted, _extract_run('rest', cap_restricted['id']),
        _item('rest', version_key='rest'), ver_restricted,
    ]
    check_corpus(export_corpus)
    read = release_read_of(export_corpus, [])

    client = DocSpecClient(tmp_path / 'ws')
    lake = DocSpecLake(client)
    lake.commit_records(export_corpus)
    views = DocSpecNewsViews(client)

    as_of = '2026-10-20T12:00:00Z'
    public_dir = tmp_path / 'export-public'
    receipts_pub = views.export_authorized(
        read, public_dir, as_of=as_of, authorized=False,
    )
    assert 'news_captures' in receipts_pub
    assert 'news_versions' in receipts_pub
    assert (public_dir / 'news_captures.parquet').exists()
    assert (public_dir / 'news_versions.parquet').exists()

    exported_captures = {
        r['id']: r
        for r in table_records(pa.parquet.read_table(public_dir / 'news_captures.parquet'))
    }
    exported_versions = {
        r['id']: r
        for r in table_records(pa.parquet.read_table(public_dir / 'news_versions.parquet'))
    }

    # Public export: only non-expired redistributable keeps payload/text.
    assert exported_captures[cap_pub_ok['id']]['access'] == 'redistributable'
    assert 'payload_uri' in exported_captures[cap_pub_ok['id']]
    assert exported_captures[cap_pub_expired['id']]['access'] == 'metadata_only'
    assert 'payload_uri' not in exported_captures[cap_pub_expired['id']]
    assert exported_captures[cap_restricted['id']]['access'] == 'metadata_only'
    assert 'payload_uri' not in exported_captures[cap_restricted['id']]

    assert exported_versions[ver_pub_ok['id']]['access'] == 'redistributable'
    assert exported_versions[ver_pub_ok['id']]['text'] == 'Redistributable body text.'
    # Version referencing an expired capture is scrubbed to metadata_only even if redistributable!
    assert exported_versions[ver_pub_expired['id']]['access'] == 'metadata_only'
    assert 'text' not in exported_versions[ver_pub_expired['id']]
    assert exported_versions[ver_restricted['id']]['access'] == 'metadata_only'
    assert 'text' not in exported_versions[ver_restricted['id']]

    # Re-exporting the same release/channel reuses the admitted export dataset version.
    receipts_pub_again = views.export_authorized(
        read, tmp_path / 'export-public-2', as_of=as_of, authorized=False,
    )
    assert (receipts_pub_again['news_versions']['source']['version']
            == receipts_pub['news_versions']['source']['version'])

    # Authorized export: preserves restricted payload/text for privileged consumers.
    auth_dir = tmp_path / 'export-auth'
    views.export_authorized(read, auth_dir, as_of=as_of, authorized=True, channel='authorized')
    auth_versions = {
        r['id']: r
        for r in table_records(pa.parquet.read_table(auth_dir / 'news_versions.parquet'))
    }
    assert auth_versions[ver_restricted['id']]['access'] == 'restricted'
    assert auth_versions[ver_restricted['id']]['text'] == 'Restricted body text.'

