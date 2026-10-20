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
    DocSpecClient,
    DocSpecLake,
    DocSpecNewsViews,
    dataset_id_for,
    merge_upsert_batch,
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

    got_full = views.politician_articles(before, mode='full')
    assert got_full == politician_articles_views(before)  # parity with the Python view
    assert sorted((row['person_root_id'], row['item_id']) for row in got_full) == sorted(
        [(P1['id'], I1['id']), (P1B['id'], I1['id']), (P2['id'], I5['id'])])

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
