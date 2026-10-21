"""Integration tests: news_lake records and C9 views on the docspec-rs backend.

Each test drives a fresh ``docspec`` workspace through
``news_lake.storage.docspec_backend`` and asserts parity with the Python
owners: ``Coordinator._merge_upsert`` for upsert merging (C1) and
``analysis.views.politician_articles`` / ``coverage_daily`` for the views.
Corpus fixtures mirror ``tests/test_analysis_views.py`` (deterministic uuid5
ids), and every admitted corpus passes ``check_corpus``.
"""
from pathlib import Path
import io
import time
import subprocess
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
    dataset_id_for,
    merge_upsert_batch,
    restore_application_schema,
    table_records,
    version_ref,
)

_ARROW_STREAM_EOS = b'\xff\xff\xff\xff\x00\x00\x00\x00'


class _ArrowHttpStream(io.RawIOBase):
    """Bounded blocking Arrow IPC framing check retained next to its only user."""

    def __init__(self, response, *, deadline=None):
        super().__init__()
        self._response = response
        self._deadline = deadline
        self._tail = b''

    def _check_deadline(self):
        if self._deadline is not None and time.monotonic() >= self._deadline:
            raise TimeoutError('DocSpec response exceeded its wall-time limit')

    def readable(self):
        return True

    def readinto(self, target):
        view = memoryview(target)
        count = 0
        while count < len(view):
            self._check_deadline()
            chunk = self._response.read(min(1 << 20, len(view) - count))
            self._check_deadline()
            if not chunk:
                break
            length = len(chunk)
            view[count:count + length] = chunk
            self._tail = (self._tail + chunk)[-8:]
            count += length
        return count

    def verify_eos(self):
        """Require both Arrow's stream terminator and complete HTTP framing."""
        if self.read(1) or self._tail != _ARROW_STREAM_EOS:
            raise OSError('DocSpec Arrow response lacks a complete stream terminator')


docspec = DocSpecClient.default_binary_path()
pytestmark = pytest.mark.skipif(
    not docspec or not Path(docspec).exists(),
    reason='set DOCSPEC_BINARY to the qualified maintained CLI')

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
    assert lake.last_lookup_stats['news_outlets']['rows_transferred'] == 1
    assert lake.last_lookup_stats['news_outlets']['total_rows'] == 50

    updated_outlet = {
        'kind': 'outlet', 'id': target_id, 'recorded_at': '2026-10-21T09:00:00Z',
        'name': 'Outlet 7 Renamed', 'domains': ['o7-new.example'],
    }
    pin_after = lake.commit_records([updated_outlet])['news_outlets']
    assert lake.last_lookup_stats['news_outlets']['rows_transferred'] == 1
    assert lake.last_lookup_stats['news_outlets']['total_rows'] == 50

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
    orig_request = client._native._request

    def fake_worker_request(path, request, *, dispatch=None):
        if dispatch is not None:
            dispatch['submitted'] = True
        raise DocSpecFailure(
            [path], subprocess.CompletedProcess(
                [path], 500, stderr='{"code":"worker","message":"simulated crash"}'))

    client._native._request = fake_worker_request
    with pytest.raises(DocSpecFailure):
        client.run_table(table, 'news_outlets', 'op-crash')
    retained = client.retained_producer_inputs()
    assert len(retained) == 1
    assert Path(retained[0]['input']).exists()
    assert Path(retained[0]['request']).exists()

    def fake_validation_request(path, request, *, dispatch=None):
        if dispatch is not None:
            dispatch['submitted'] = True
        error = DocSpecFailure(
            [path], subprocess.CompletedProcess(
                [path], 422, stderr='{"code":"validation","message":"bad schema"}'))
        error.status_code = 422
        raise error

    client._native._request = fake_validation_request
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



# -- ct-f11a: strict release identity and direct pinned export --------------------------


def test_export_authorized_requires_a_published_release_identity(tmp_path):
    """Raw record lists cannot fabricate a release identity for authorized export."""
    client = DocSpecClient(tmp_path / 'ws')
    views = DocSpecNewsViews(client)
    with pytest.raises(ValueError, match='requires an exact published release read'):
        views.export_authorized([_capture('raw')], tmp_path / 'export')


def test_export_authorized_uses_an_unchanged_release_pin_directly(tmp_path):
    """When C5 filtering changes nothing, the pinned dataset is exported, not re-admitted."""
    corpus = [OUTLET_A]
    read = release_read_of(corpus, [])
    client = DocSpecClient(tmp_path / 'ws')
    lake = DocSpecLake(client)
    lake.commit_records(corpus)
    pin = client.latest('news_outlets')
    views = DocSpecNewsViews(client)
    result = views.export_authorized(
        read, tmp_path / 'export-pinned', authorized=True,
        dataset_pins={'news.outlets': pin})
    assert result['pins']['news.outlets']['source']['version'] == pin['dataset']['version']
    # No duplicate export_news_outlets staging dataset was created.
    with pytest.raises(DocSpecFailure):
        client.latest('export_news_outlets')


# -- ct-5fkx: multi-poll coupled generation sealing with partial table updates ----------


def test_multi_poll_coupled_generation_sealing_with_partial_tables(tmp_path, monkeypatch):
    """Poll 1 (g1) and Poll 2 (g2 with untouched tables) both seal and preserve pins."""
    client = DocSpecClient(tmp_path / 'ws')
    lake = DocSpecLake(client)

    # Poll 1 commits outlet (upsert), capture (append), run (append), and version (append).
    poll1 = [
        OUTLET_A,
        _capture('p1'),
        _extract_run('p1', _id('capture:p1')),
        _version('p1', title='Poll 1 article',
                 publication={'precision': 'day', 'date': '2026-10-18', 'basis': 'publisher'},
                 text='Alex Doe spoke in poll 1.'),
    ]
    pins_g1 = lake.commit_records(poll1, generation='g1', family='news')
    seal_g1 = lake.seal('g1', family='news')
    assert set(seal_g1['members']) == {'news_outlets', 'news_captures', 'news_runs', 'news_versions'}

    # Poll 2 touches ONLY outlet (upsert) and capture (append), leaving news_runs and
    # news_versions completely untouched in the incoming batch.
    outlet_updated = dict(
        OUTLET_A,
        recorded_at='2026-10-21T10:00:00Z',
        domains=['example.com', 'news.example.com'],
    )
    poll2 = [
        outlet_updated,
        _capture('p2'),
    ]
    pins_g2 = lake.commit_records(poll2, generation='g2', family='news')
    seal_g2 = lake.seal('g2', family='news')
    assert set(seal_g2['members']) == set(seal_g1['members'])
    for ds, member in seal_g2['members'].items():
        assert pins_g2[ds]['dataset']['relationship'] == {
            'kind': 'coupled', 'family': 'news', 'generation': 'g2'
        }
        assert version_ref(pins_g2[ds]) == member

    # Untouched news_versions preserved 100% of its data files without rewrite.
    v_files_g1 = {
        obj['path'] for obj in pins_g1['news_versions']['dataset']['groups']['source']['objects']
    }
    v_files_g2 = {
        obj['path'] for obj in pins_g2['news_versions']['dataset']['groups']['source']['objects']
    }
    assert v_files_g1 == v_files_g2

    # Missing binary raises DocSpecFailure rather than TypeError.
    monkeypatch.delenv('DOCSPEC_BINARY', raising=False)
    monkeypatch.setattr('shutil.which', lambda _: None)
    with pytest.raises(DocSpecFailure, match='no DocSpec runtime configured'):
        DocSpecClient(tmp_path / 'ws-missing', binary=None)


# -- ct-jo8n, ct-n6lj, ct-gf8i, ct-4nyy: published release lifecycle & fresh resume -----


def test_published_release_lifecycle_fresh_process_resume_and_retire(tmp_path):
    """publish_release / read_release / views / export_release work across fresh processes."""
    from news_lake.analysis.export import export_release as export_release_fn
    from news_lake.storage import ControlStore, Coordinator, ReleaseError, publish_release, read_release, retire_release

    ws = tmp_path / 'ws'
    control = ControlStore(tmp_path / 'control.sqlite')
    client1 = DocSpecClient(ws)
    lake1 = DocSpecLake(client1)
    coord1 = Coordinator(lake1, control)

    initial_corpus = [r for r in CORPUS if r['id'] != MERGE_P1B_INTO_P1['id']]
    rel1_id = _id('release:pub-1')
    rel1 = publish_release(
        coord1,
        initial_corpus,
        release_id=rel1_id,
        recorded_at=AT,
        selections=SELECTIONS,
        checkpoints=[{'connector_key': 'rss:example', 'checkpoint_ref': 'urn:fixture:cp:1', 'completed_until': AT}],
    )
    assert rel1['id'] == rel1_id

    views1 = DocSpecNewsViews(client1)
    read1 = read_release(lake1, control, rel1_id)
    # Explicit empty tables are preserved as []
    assert read1['tables']['news.classifications'] == []
    views1.materialize(read1)
    pa1 = politician_articles_views(read1, docspec_views=views1, mode='full')
    cov1 = coverage_daily(read1, docspec_views=views1, mode='full')
    assert pa1 == politician_articles_views(read1)
    assert cov1 == coverage_daily(read1)
    client1.close()

    # Fresh process resumes durable lake & bridge state without calling client.latest()
    client2 = DocSpecClient(ws)
    lake2 = DocSpecLake(client2)
    coord2 = Coordinator(lake2, control)
    rel2_id = _id('release:pub-2')
    publish_release(
        coord2,
        [MERGE_P1B_INTO_P1],
        release_id=rel2_id,
        recorded_at='2026-10-20T05:00:00Z',
        selections=SELECTIONS,
        checkpoints=[{'connector_key': 'rss:example', 'checkpoint_ref': 'urn:fixture:cp:2', 'completed_until': '2026-10-20T05:00:00Z'}],
    )
    read2 = read_release(lake2, control, rel2_id)
    views2 = DocSpecNewsViews(client2)
    views2.update_bridges(read2)
    # Cached bridge state avoids full-table read_arrow on prior bridge pins!
    for bridge_ds, stats in views2.last_bridge_diff.items():
        assert stats['full_table_reads'] == 0, bridge_ds
    pa2 = politician_articles_views(read2, docspec_views=views2, mode='incremental')
    assert pa2 == politician_articles_views(read2)

    # Export through analysis.export.export_release using the release's dataset_pins
    exp_dir = tmp_path / 'exported-rel2'
    exp_result = export_release_fn(
        read2,
        authorized=True,
        now='2026-10-20T12:00:00Z',
        docspec_views=views2,
        destination_dir=exp_dir,
        channel='authorized',
    )
    assert (exp_dir / 'news_outlets.parquet').is_file()
    assert (
        exp_result['pins']['news.outlets']['source']['version']
        == read2['dataset_pins']['news.outlets']['dataset']['version']
    )

    # Retiring release 1 blocks read_release on release 1 while release 2 stays readable
    retire_release(control, rel1_id, epoch=coord2.epoch)
    with pytest.raises(ReleaseError) as exc_info:
        read_release(lake2, control, rel1_id)
    assert exc_info.value.rule == 'retired_release'
    assert read_release(lake2, control, rel2_id)['release']['id'] == rel2_id
    client2.close()


# -- ct-ur2y: RFC 9562 UUIDv7 time-ordered record IDs prune disjoint poll files ---------


def test_uuidv7_context_ids_prune_disjoint_historical_files_across_polls(tmp_path):
    """Chronological polls using AdapterContext default UUIDv7 IDs prune prior files on Update."""
    from datetime import datetime, timedelta, timezone
    import uuid
    from news_lake.context import AdapterContext

    base_time = datetime(2026, 10, 20, 0, 0, 0, tzinfo=timezone.utc)
    current_time = [base_time]
    ctx = AdapterContext(clock=lambda: current_time[0])

    client = DocSpecClient(tmp_path / 'ws-uuid7')
    lake = DocSpecLake(client)

    poll_ids = []
    for poll_idx in range(4):
        current_time[0] = base_time + timedelta(hours=poll_idx)
        batch = []
        for item_idx in range(4):
            cid = ctx.new_id()
            parsed = uuid.UUID(cid)
            assert parsed.version == 7
            batch.append(
                dict(
                    _capture(f'p{poll_idx}-{item_idx}'),
                    id=cid,
                    recorded_at=ctx.now_string(),
                    observed_at=ctx.now_string(),
                )
            )
        # Within and across polls, UUIDv7 IDs are strictly monotonically increasing
        assert batch[0]['id'] < batch[1]['id'] < batch[2]['id'] < batch[3]['id']
        if poll_ids:
            assert poll_ids[-1][-1] < batch[0]['id']
        poll_ids.append([r['id'] for r in batch])
        lake.commit_records(batch)

    # Touch the first ID of poll 3 in an update; polls 0, 1, 2 have disjoint [min, max] bounds
    # and must be reused without scanning!
    pin_before = lake.committed['news_captures']
    inspect_all = client._native.inspect('news_captures')
    latest_op = pin_before['id']
    processing_phases = [
        v for v in inspect_all.values()
        if isinstance(v, dict) and v.get('operation') == latest_op and v.get('phase') == 'processing'
    ]
    assert len(processing_phases) == 1
    metrics = processing_phases[0]['metrics']
    # On the 4th poll (3 existing files + 1 new replacement batch), none of the 3 prior files
    # overlap the new poll's UUIDv7 keys, so all 3 prior files are reused without decoding
    # (`files_reused == 3` and `files_scanned == 0`)!
    assert metrics['files_reused'] == 3, metrics
    assert metrics['files_scanned'] == 0, metrics
    client.close()


# -- ct-r60e: threshold-based automatic compact_lifecycle maintenance -------------------


def test_threshold_lifecycle_compaction_triggers_after_multi_poll_updates(tmp_path):
    """DocSpecLake and DocSpecNewsViews compact lifecycle revisions automatically at threshold."""
    client = DocSpecClient(tmp_path / 'ws-compact')
    lake = DocSpecLake(client, lifecycle_compact_interval=4)
    views = DocSpecNewsViews(client, lifecycle_compact_interval=4)

    for i in range(4):
        cap = dict(_capture(f'c{i}'), id=f'0192a000-{i:04x}-7000-8000-000000000001')
        lake.commit_records([OUTLET_A, cap])

    assert len(lake.lifecycle_compactions) == 1
    assert lake.lifecycle_compactions[0]['dataset'] == 'news_captures'
    assert lake.lifecycle_compactions[0]['revisions_after'] == 1
    assert lake._mutation_counts['news_captures'] == 0

    # Verify views also compact at threshold
    views.materialize(CORPUS, SELECTIONS)
    for i in range(4):
        views.coverage_daily(CORPUS, mode='full', selections=SELECTIONS)
    assert any(c['dataset'] == 'coverage_daily' and c['revisions_after'] == 1 for c in views.lifecycle_compactions)
    client.close()


# -- ct-ur7v: news-lake CLI defaults to DocSpecLake and DocSpecNewsViews ----------------


def test_news_lake_cli_publish_views_export_and_compact_lifecycle(tmp_path, capsys):
    """news_lake.cli drives publish, views (--verify-oracle), export, and compact-lifecycle."""
    import json
    from news_lake.cli import main as cli_main

    ws = tmp_path / 'cli-ws'
    jsonl_path = tmp_path / 'corpus.jsonl'
    jsonl_path.write_text(
        '\n'.join(json.dumps(r, sort_keys=True) for r in CORPUS) + '\n',
        encoding='utf-8',
    )
    selections_path = tmp_path / 'selections.json'
    selections_path.write_text(json.dumps(SELECTIONS), encoding='utf-8')
    rel_id = _id('release:cli-1')

    assert cli_main([
        'publish',
        '--workspace', str(ws),
        '--input', str(jsonl_path),
        '--release-id', rel_id,
        '--recorded-at', AT,
        '--selections', str(selections_path),
        '--binary', str(docspec),
    ]) == 0
    pub_out = json.loads(capsys.readouterr().out)
    assert pub_out['backend'] == 'docspec'
    assert pub_out['release']['id'] == rel_id

    assert cli_main([
        'views',
        '--workspace', str(ws),
        '--release-id', rel_id,
        '--mode', 'full',
        '--verify-oracle',
        '--binary', str(docspec),
    ]) == 0
    views_out = json.loads(capsys.readouterr().out)
    assert views_out['backend'] == 'docspec'
    assert views_out['oracle_verified'] is True
    assert len(views_out['politician_articles']) == 2
    assert len(views_out['coverage_daily']) == 3

    export_dir = tmp_path / 'cli-export'
    assert cli_main([
        'export',
        '--workspace', str(ws),
        '--release-id', rel_id,
        '--destination', str(export_dir),
        '--as-of', '2026-10-20T12:00:00Z',
        '--binary', str(docspec),
    ]) == 0
    exp_out = json.loads(capsys.readouterr().out)
    assert exp_out['backend'] == 'docspec'
    assert (export_dir / 'news_versions.parquet').is_file()

    assert cli_main([
        'compact-lifecycle',
        '--workspace', str(ws),
        '--binary', str(docspec),
    ]) == 0
    comp_out = json.loads(capsys.readouterr().out)
    assert comp_out['backend'] == 'docspec'
    assert 'news_versions' in comp_out['lake_datasets']
    assert 'politician_articles' in comp_out['view_datasets']


# -- ct-xu1o: input-derived time-keyed append updates prune historical poll files -------


def test_append_time_keyed_pruning_replay_and_collision_refusal(tmp_path):
    """ct-xu1o: uuid5 append tables key Updates by [<time_col>, 'id'] so polls skip old files."""
    from news_lake.contract.records import CONTENT_TABLES, TABLE_KINDS, TABLE_MUTATIONS
    from news_lake.storage.docspec_backend import APPEND_UPDATE_KEYS, kind_arrow_schema

    append_kinds = {
        TABLE_KINDS[table]
        for table in CONTENT_TABLES
        if TABLE_MUTATIONS[table] == 'append'
    }
    assert set(APPEND_UPDATE_KEYS) == append_kinds
    assert APPEND_UPDATE_KEYS['capture'] == ('id',)
    assert APPEND_UPDATE_KEYS['discovery'] == ('observed_at', 'id')
    assert APPEND_UPDATE_KEYS['run'] == ('started_at', 'id')
    for kind in ('version', 'mention', 'classification', 'identity_decision', 'story', 'story_member'):
        assert APPEND_UPDATE_KEYS[kind] == ('recorded_at', 'id')
    for kind, keys in APPEND_UPDATE_KEYS.items():
        schema = kind_arrow_schema(kind)
        for col in keys:
            assert col in schema.names, (kind, col)

    ws = tmp_path / 'ws-xu1o'
    client = DocSpecClient(ws)
    lake = DocSpecLake(client)

    observed_update_keys = {}
    orig_update_table = client.update_table

    def spy_update_table(dataset, operation, base_version, keys, table, **kwargs):
        observed_update_keys.setdefault(dataset, []).append(list(keys))
        return orig_update_table(dataset, operation, base_version, keys, table, **kwargs)

    client.update_table = spy_update_table

    polls = []
    for poll_idx in range(4):
        ts = f'2026-10-20T{poll_idx:02d}:00:00Z'
        batch = []
        for item_idx in range(4):
            key = f'xu1o-p{poll_idx}-i{item_idx}'
            cap_id = _id('capture:' + key)
            item_id = _id('item:' + key)
            ver_id = _id('version:' + key)
            run_id = _id('run:' + key)
            story_id = _id('story:' + key)
            batch.extend([
                dict(_discovery(key), observed_at=ts, recorded_at=ts),
                dict(_extract_run(key, cap_id), id=run_id, recorded_at=ts, started_at=ts, finished_at=ts),
                dict(
                    _version(
                        key,
                        title=f'Poll {poll_idx} item {item_idx}',
                        publication={'precision': 'unknown'},
                    ),
                    id=ver_id,
                    item_id=item_id,
                    capture_id=cap_id,
                    run_id=run_id,
                    recorded_at=ts,
                ),
                dict(
                    _mention(
                        key,
                        version_key=key,
                        surface='Alex Doe',
                        resolution='resolved',
                        occurrences=[{'field': 'title', 'start': 0, 'end': 8}],
                        entity_key='p1',
                    ),
                    version_id=ver_id,
                    run_id=run_id,
                    recorded_at=ts,
                ),
                {
                    'kind': 'classification',
                    'id': _id('classification:' + key),
                    'recorded_at': ts,
                    'version_id': ver_id,
                    'run_id': run_id,
                    'dimension': 'topic',
                    'taxonomy_version': 'fixture-1',
                    'value_string': 'election',
                },
                {
                    'kind': 'identity_decision',
                    'id': _id('decision:' + key),
                    'recorded_at': ts,
                    'action': 'same_as',
                    'left_id': _id('entity:left-' + key),
                    'right_id': _id('entity:right-' + key),
                    'decided_by': 'fixture:reviewer',
                    'reason': 'Synthetic decision.',
                },
                {
                    'kind': 'story',
                    'id': story_id,
                    'recorded_at': ts,
                    'run_id': run_id,
                },
                {
                    'kind': 'story_member',
                    'id': _id('member:' + key),
                    'recorded_at': ts,
                    'story_id': story_id,
                    'version_id': ver_id,
                    'run_id': run_id,
                },
            ])
        polls.append(batch)
        pins = lake.commit_records(batch)

        if poll_idx >= 1:
            for kind, expected_keys in APPEND_UPDATE_KEYS.items():
                if kind == 'capture':
                    continue
                ds = dataset_id_for(KIND_TABLES[kind])
                assert observed_update_keys[ds][-1] == list(expected_keys)
                assert lake.last_lookup_stats[ds]['matched_rows'] == 0, (ds, poll_idx, lake.last_lookup_stats[ds])
                assert lake.last_lookup_stats[ds]['rows_transferred'] == 0, (ds, poll_idx, lake.last_lookup_stats[ds])
                latest_op = pins[ds]['id']
                inspect_all = client._native.inspect(ds)
                phases = [
                    v for v in inspect_all.values()
                    if isinstance(v, dict)
                    and v.get('operation') == latest_op
                    and v.get('phase') == 'processing'
                ]
                assert len(phases) == 1, (ds, poll_idx)
                metrics = phases[0]['metrics']
                assert metrics['files_scanned'] == 0, (ds, poll_idx, metrics)
                assert metrics['files_reused'] == poll_idx, (ds, poll_idx, metrics)

    # Stored IDs and records match input exactly across all converted append tables.
    all_records = [r for p in polls for r in p]
    for kind in ('discovery', 'run', 'version', 'mention', 'classification', 'identity_decision', 'story', 'story_member'):
        ds = dataset_id_for(KIND_TABLES[kind])
        expected = sorted([r for r in all_records if r['kind'] == kind], key=lambda r: r['id'])
        assert _records_of(lake, ds) == expected

    # Re-running the same poll in-process and from a fresh process is an idempotent no-op.
    versions_before = {
        ds: pin['dataset']['version'] for ds, pin in lake.committed.items()
    }
    pins_replay_inproc = lake.commit_records(polls[1])
    assert {ds: p['dataset']['version'] for ds, p in pins_replay_inproc.items()} == versions_before
    client.close()

    client2 = DocSpecClient(ws)
    lake2 = DocSpecLake(client2)
    pins_replay_fresh = lake2.commit_records(polls[2])
    assert {ds: p['dataset']['version'] for ds, p in pins_replay_fresh.items()} == versions_before
    for kind, expected_keys in APPEND_UPDATE_KEYS.items():
        if kind == 'capture':
            continue
        ds = dataset_id_for(KIND_TABLES[kind])
        assert lake2.last_lookup_stats[ds]['matched_rows'] == 4, (ds, lake2.last_lookup_stats[ds])
        assert lake2.last_lookup_stats[ds]['rows_transferred'] == 4, (ds, lake2.last_lookup_stats[ds])
        assert lake2.last_lookup_stats[ds]['total_rows'] == 16, (ds, lake2.last_lookup_stats[ds])

    # Reusing an existing id with different content (same timestamp OR different timestamp) is refused.
    orig_version = next(r for r in polls[1] if r['kind'] == 'version')
    bad_same_ts = dict(orig_version, title='Tampered Title With Same Timestamp')
    with pytest.raises(AppendCollisionError, match='append-only news_versions'):
        lake2.commit_records([bad_same_ts])
    bad_diff_ts = dict(orig_version, recorded_at='2026-10-20T09:00:00Z', title='Tampered Title With New Timestamp')
    with pytest.raises(AppendCollisionError, match='append-only news_versions'):
        lake2.commit_records([bad_diff_ts])
    assert lake2.committed['news_versions']['dataset']['version'] == versions_before['news_versions']
    client2.close()


# -- ct-dzyf: Coordinator.abandon_cycle on DocSpecLake-backed publication ---------------


def test_docspec_abandon_cycle_rollback_idempotency_and_refusals(tmp_path):
    """ct-dzyf: Coordinator.abandon_cycle restores DocSpecLake pins, discards checkpoints, and enforces baseline/release guards."""
    import copy
    import json
    from news_lake.contract import ContractError
    from news_lake.storage import (
        CommitError,
        ControlStore,
        Coordinator,
        CrashInjection,
        Faults,
        ReleaseError,
        publish_release,
        read_release,
        retire_release,
    )
    from news_lake.storage.releases import find_release

    # 1. Abandoning on a warehouse with no prior published release when a dataset was dirtied refuses.
    ws_unpinned = tmp_path / 'ws-unpinned'
    ctrl_unpinned = ControlStore(tmp_path / 'ctrl-unpinned.sqlite')
    client_unpinned = DocSpecClient(ws_unpinned)
    lake_unpinned = DocSpecLake(client_unpinned)
    coord_unpinned = Coordinator(lake_unpinned, ctrl_unpinned)
    bad_first_id = _id('release:bad-first')
    bad_first_corpus = [
        OUTLET_A,
        dict(M1, entity_id='00000000-0000-0000-0000-00000000000f'),
    ]
    with pytest.raises(ContractError):
        publish_release(coord_unpinned, bad_first_corpus, release_id=bad_first_id, recorded_at=AT)
    with pytest.raises(CommitError) as no_base_err:
        coord_unpinned.abandon_cycle(bad_first_id)
    assert no_base_err.value.rule == 'no_available_baseline'
    client_unpinned.close()

    # 2. Publish a valid baseline release (rel_a) on DocSpecLake.
    ws = tmp_path / 'ws-dzyf'
    control = ControlStore(tmp_path / 'ctrl-dzyf.sqlite')
    client = DocSpecClient(ws)
    lake = DocSpecLake(client)
    coord = Coordinator(lake, control)

    initial_corpus = [r for r in CORPUS if r['id'] != MERGE_P1B_INTO_P1['id']]
    rel_a_id = _id('release:dzyf-a')
    cp_a = [{'connector_key': 'rss:a', 'checkpoint_ref': 'urn:cp:a', 'completed_until': AT}]
    rel_a = publish_release(
        coord,
        initial_corpus,
        release_id=rel_a_id,
        recorded_at=AT,
        selections=SELECTIONS,
        checkpoints=cp_a,
    )
    assert rel_a['id'] == rel_a_id
    baseline_outlets = _records_of(lake, 'news_outlets')
    baseline_mentions = _records_of(lake, 'news_mentions')
    baseline_captures = _records_of(lake, 'news_captures')

    # 3. Candidate cycle (rel_b) mutates an existing upsert row (OUTLET_A), adds a new outlet,
    # replays an existing capture, and adds an invalid C7 mention -> fails mid-cycle after table_commit.
    mutated_outlet = dict(
        copy.deepcopy(OUTLET_A),
        recorded_at='2026-10-20T05:00:00Z',
        name='Mutated By Failed Cycle B',
        domains=['a.example', 'dirty.example'],
    )
    added_dirty_outlet = {
        'kind': 'outlet',
        'id': _id('outlet:dirty-b'),
        'recorded_at': '2026-10-20T05:00:00Z',
        'name': 'Added Dirty Outlet',
        'domains': ['added-dirty.example'],
    }
    replayed_capture = copy.deepcopy(_capture('v1'))
    invalid_mention = dict(
        copy.deepcopy(M1),
        id=_id('mention:dirty-invalid-b'),
        recorded_at='2026-10-20T05:00:00Z',
        entity_id='00000000-0000-0000-0000-00000000000f',
    )
    rel_b_id = _id('release:dzyf-b')
    with pytest.raises(ContractError) as c7_err:
        publish_release(
            coord,
            [mutated_outlet, added_dirty_outlet, replayed_capture, invalid_mention],
            release_id=rel_b_id,
            recorded_at='2026-10-20T05:00:00Z',
            selections=SELECTIONS,
        )
    assert c7_err.value.rule == 'missing_reference'
    # Dirty candidate records landed in DocSpecLake before C7 validation failed.
    assert len(_records_of(lake, 'news_outlets')) == len(baseline_outlets) + 1
    assert len(_records_of(lake, 'news_mentions')) == len(baseline_mentions) + 1

    # Stage a checkpoint on rel_b to verify abandon_cycle discards staged checkpoints.
    control.stage_checkpoint(
        rel_b_id,
        {
            'connector_key': 'rss:dirty',
            'checkpoint_ref': 'urn:cp:dirty',
            'completed_until': '2026-10-20T05:00:00Z',
        },
        epoch=coord.epoch,
    )

    # 4. If all releases are retired, abandon_cycle refuses to wipe and preserves staged state.
    retire_release(control, rel_a_id, epoch=coord.epoch)
    with pytest.raises(CommitError) as retired_base_err:
        coord.abandon_cycle(rel_b_id)
    assert retired_base_err.value.rule == 'no_available_baseline'
    control.mark_available(rel_a_id, epoch=coord.epoch)

    # 5. If a dirtied dataset is missing from the release manifest's dataset_pins, abandon_cycle refuses.
    manifest_path = lake._release_manifest_path(rel_a_id)
    orig_manifest_text = manifest_path.read_text()
    tampered_manifest = json.loads(orig_manifest_text)
    tampered_manifest['dataset_pins'].pop('news_outlets', None)
    manifest_path.write_text(json.dumps(tampered_manifest))
    with pytest.raises(CommitError) as missing_pin_err:
        coord.abandon_cycle(rel_b_id)
    assert missing_pin_err.value.rule == 'no_available_baseline'
    assert 'news_outlets' in str(missing_pin_err.value)
    manifest_path.write_text(orig_manifest_text)

    # 6. Abandoning rel_b from a fresh process restores all content datasets (including relationship)
    # to rel_a's pinned baseline and discards staged checkpoints.
    client.close()
    client = DocSpecClient(ws)
    lake = DocSpecLake(client)
    coord = Coordinator(lake, control)
    coord.abandon_cycle(rel_b_id)
    assert control.cycle_state(rel_b_id) == 'abandoned'
    assert control.connection.execute(
        'SELECT * FROM staged_checkpoints WHERE cycle_id = ?', (rel_b_id,)
    ).fetchall() == []
    assert _records_of(lake, 'news_outlets') == baseline_outlets
    assert _records_of(lake, 'news_mentions') == baseline_mentions
    assert _records_of(lake, 'news_captures') == baseline_captures
    assert read_release(lake, control, rel_a_id)['release']['id'] == rel_a_id
    rel_a_manifest = json.loads(orig_manifest_text)
    for ds, pin in lake.committed.items():
        assert pin['dataset']['relationship'] == rel_a_manifest['dataset_pins'][ds]['dataset']['relationship'], ds

    # 7. Abandoning is idempotent (second call is a no-op) and terminal for recover().
    versions_after_abandon = {
        ds: pin['dataset']['version'] for ds, pin in lake.committed.items()
    }
    coord.abandon_cycle(rel_b_id)
    assert {
        ds: pin['dataset']['version'] for ds, pin in lake.committed.items()
    } == versions_after_abandon
    assert coord.recover() == []

    # Retrying an abandoned cycle_id, abandoning an unknown cycle, or abandoning a released cycle fail cleanly.
    with pytest.raises(ReleaseError) as retry_err:
        publish_release(coord, [MERGE_P1B_INTO_P1], release_id=rel_b_id, recorded_at='2026-10-20T05:00:00Z')
    assert retry_err.value.rule == 'cycle_abandoned'
    with pytest.raises(CommitError) as unknown_err:
        coord.abandon_cycle(_id('release:unknown'))
    assert unknown_err.value.rule == 'unknown_cycle'
    with pytest.raises(CommitError) as released_err:
        coord.abandon_cycle(rel_a_id)
    assert released_err.value.rule == 'cycle_released'

    # 8. Subsequent valid cycle (rel_c) publishes cleanly on top of the restored baseline.
    rel_c_id = _id('release:dzyf-c')
    rel_c = publish_release(
        coord,
        [MERGE_P1B_INTO_P1],
        release_id=rel_c_id,
        recorded_at='2026-10-20T06:00:00Z',
        selections=SELECTIONS,
    )
    assert rel_c['id'] == rel_c_id
    read_c = read_release(lake, control, rel_c_id)
    assert sorted(read_c['tables']['news.outlets'], key=lambda r: r['id']) == baseline_outlets
    assert read_c['tables']['news.identity_decisions'] == [MERGE_P1B_INTO_P1]

    # 9. If the release record was already appended (crash after release_append), abandon_cycle refuses.
    rel_d_id = _id('release:dzyf-d')
    crashing_coord = Coordinator(
        lake, control, writer_id='crashing-writer', faults=Faults(crash_after={'release_append'})
    )
    new_outlet_d = {
        'kind': 'outlet',
        'id': _id('outlet:dzyf-d'),
        'recorded_at': '2026-10-20T07:00:00Z',
        'name': 'Cycle D Outlet',
        'domains': ['d.example'],
    }
    with pytest.raises(CrashInjection):
        publish_release(
            crashing_coord,
            [new_outlet_d],
            release_id=rel_d_id,
            recorded_at='2026-10-20T07:00:00Z',
            selections=SELECTIONS,
        )
    assert find_release(lake, rel_d_id) is not None
    with pytest.raises(CommitError) as appended_err:
        crashing_coord.abandon_cycle(rel_d_id)
    assert appended_err.value.rule == 'cycle_release_appended'
    assert find_release(lake, rel_d_id) is not None
    assert Coordinator(lake, control, writer_id='recovery-writer').recover() == [rel_d_id]
    assert read_release(lake, control, rel_d_id)['release']['id'] == rel_d_id
    client.close()

