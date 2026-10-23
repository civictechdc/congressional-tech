"""Shared fixtures: docs fixtures, a fresh offline lake, and a second cycle.

The second batch (B) is deterministic (uuid5 ids) and touches all twelve
non-release tables so every table-commit fault point fires.
"""
import hashlib
import json
import os
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

_DEFAULT_DOCSPEC = Path(__file__).resolve().parents[4] / "spicy-stack/docspec-rs/target/release/docspec"
if not os.environ.get("DOCSPEC_BINARY") and _DEFAULT_DOCSPEC.is_file():
    os.environ["DOCSPEC_BINARY"] = str(_DEFAULT_DOCSPEC)

DOCS = Path(__file__).resolve().parents[1] / 'docs'
DOCS_SCHEMA = DOCS / 'schema' / 'news-lake.schema.json'
DOCS_FIXTURES = DOCS / 'examples' / 'records.jsonl'


@pytest.fixture(scope='session')
def fixture_records():
    return [json.loads(line) for line in DOCS_FIXTURES.read_text().splitlines() if line.strip()]


@pytest.fixture(scope='session')
def batch(fixture_records):
    return [record for record in fixture_records if record['kind'] != 'release']


def _uid(name):
    return str(uuid5(NAMESPACE_URL, 'news-lake-test:' + name))


@pytest.fixture(scope='session')
def ids():
    return {
        'outlet2': _uid('outlet2'),
        'capture2': _uid('capture2'),
        'discovery2': _uid('discovery2'),
        'item2': _uid('item2'),
        'version2': _uid('version2'),
        'entity3': _uid('entity3'),
        'decision2': _uid('decision2'),
        'run_extract2': _uid('run-extract2'),
        'run_mentions2': _uid('run-mentions2'),
        'mention2': _uid('mention2'),
        'classification2': _uid('classification2'),
        'run_cluster2': _uid('run-cluster2'),
        'story2': _uid('story2'),
        'story_member2': _uid('story-member2'),
        'release_a': _uid('release-a'),
        'release_b': _uid('release-b'),
    }


def _config_hash(name):
    return hashlib.sha256(name.encode()).hexdigest()


@pytest.fixture(scope='session')
def second_batch(fixture_records, ids):
    """A consistent follow-up corpus: second outlet/article/entities/story."""
    first = {record['kind']: record for record in fixture_records}
    text = 'Robin Roe speaks.'
    entity1 = first['entity']['id']
    at = '2026-10-20T06:00:00Z'
    return [
        {'kind': 'outlet', 'id': ids['outlet2'], 'recorded_at': at, 'name': 'Second Example News',
         'domains': ['second.example'], 'feed_urls': ['https://second.example/feed.xml']},
        {'kind': 'capture', 'id': ids['capture2'], 'recorded_at': at, 'provider': 'rss',
         'request_url': 'https://second.example/news/2', 'observed_at': at, 'http_status': 200,
         'access': 'restricted', 'payload_uri': 's3://example-news/captures/second.html',
         'payload_hash': hashlib.sha256(b'second fixture bytes').hexdigest(), 'media_type': 'text/html',
         'rights_basis': 'Synthetic fixture.', 'status': 'succeeded'},
        {'kind': 'discovery', 'id': ids['discovery2'], 'recorded_at': at, 'capture_id': ids['capture2'],
         'item_id': ids['item2'], 'provider': 'rss', 'external_id': 'article-2',
         'feed_url': 'https://second.example/feed.xml', 'url': 'https://second.example/news/2',
         'observed_at': at, 'mode': 'live', 'reported_title': 'Robin Roe speaks.'},
        {'kind': 'item', 'id': ids['item2'], 'recorded_at': at, 'outlet_id': ids['outlet2'],
         'canonical_url': 'https://second.example/news/2', 'url_aliases': ['https://second.example/2'],
         'content_type': 'news_article', 'first_seen_at': at, 'current_version_id': ids['version2']},
        {'kind': 'version', 'id': ids['version2'], 'recorded_at': at, 'item_id': ids['item2'],
         'capture_id': ids['capture2'], 'run_id': ids['run_extract2'], 'title': text,
         'publication': {'precision': 'day', 'date': '2026-10-20', 'basis': 'publisher'},
         'text': text, 'text_hash': hashlib.sha256(text.encode('utf-8')).hexdigest(),
         'access': 'restricted', 'rights_basis': 'Synthetic fixture.'},
        {'kind': 'entity', 'id': ids['entity3'], 'recorded_at': at, 'entity_type': 'person',
         'name': 'Robin Roe', 'aliases': [], 'identifiers': [{'scheme': 'fixture', 'value': 'person-3'}]},
        {'kind': 'identity_decision', 'id': ids['decision2'], 'recorded_at': at, 'action': 'different_from',
         'left_id': entity1, 'right_id': ids['entity3'], 'decided_by': 'fixture:reviewer',
         'reason': 'Distinct fixture people.'},
        {'kind': 'run', 'id': ids['run_extract2'], 'recorded_at': at, 'processor': 'extract',
         'processor_version': 'fixture-1', 'config_hash': _config_hash('extract-2'),
         'input_hash': _config_hash('extract-inputs-2'),
         'inputs': [{'kind': 'capture', 'id': ids['capture2']}], 'mode': 'live', 'status': 'succeeded',
         'started_at': at, 'finished_at': at},
        {'kind': 'run', 'id': ids['run_mentions2'], 'recorded_at': at, 'processor': 'mentions',
         'processor_version': 'fixture-1', 'config_hash': _config_hash('mentions-2'),
         'input_hash': _config_hash('mentions-inputs-2'),
         'inputs': [{'kind': 'version', 'id': ids['version2']}], 'mode': 'live', 'status': 'succeeded',
         'started_at': at, 'finished_at': at},
        {'kind': 'mention', 'id': ids['mention2'], 'recorded_at': at, 'version_id': ids['version2'],
         'run_id': ids['run_mentions2'], 'surface': 'Robin Roe', 'resolution': 'resolved',
         'entity_id': ids['entity3'], 'aboutness': 'primary',
         'occurrences': [{'field': 'title', 'start': 0, 'end': 9}, {'field': 'text', 'start': 0, 'end': 9}]},
        {'kind': 'classification', 'id': ids['classification2'], 'recorded_at': at,
         'version_id': ids['version2'], 'run_id': ids['run_mentions2'], 'dimension': 'genre',
         'taxonomy_version': 'fixture-1', 'value_strings': ['opinion']},
        {'kind': 'run', 'id': ids['run_cluster2'], 'recorded_at': at, 'processor': 'cluster',
         'processor_version': 'fixture-1', 'config_hash': _config_hash('cluster-2'),
         'input_hash': _config_hash('cluster-inputs-2'),
         'inputs': [{'kind': 'version', 'id': ids['version2']}], 'mode': 'live', 'status': 'succeeded',
         'started_at': at, 'finished_at': at},
        {'kind': 'story', 'id': ids['story2'], 'recorded_at': at, 'run_id': ids['run_cluster2'],
         'label': 'Second story'},
        {'kind': 'story_member', 'id': ids['story_member2'], 'recorded_at': at, 'story_id': ids['story2'],
         'version_id': ids['version2'], 'run_id': ids['run_cluster2'], 'score': 0.9},
    ]


@pytest.fixture(scope='session')
def selections_a():
    return [{'processor': 'extract', 'processor_version': 'fixture-1', 'config_hash': _config_hash('extract-a')}]


@pytest.fixture(scope='session')
def selections_b():
    return [{'processor': 'extract', 'processor_version': 'fixture-1', 'config_hash': _config_hash('extract-2')}]


@pytest.fixture(scope='session')
def checkpoints_a():
    return [{'connector_key': 'rss:example', 'checkpoint_ref': 's3://example-news/checkpoints/a.json',
             'completed_until': '2026-10-20T04:00:00Z'}]


@pytest.fixture(scope='session')
def checkpoints_b():
    return [{'connector_key': 'rss:second', 'checkpoint_ref': 's3://example-news/checkpoints/b.json',
             'completed_until': '2026-10-20T06:00:00Z'}]


@pytest.fixture
def lake(tmp_path):
    from news_lake.storage.catalog import Lake

    return Lake(tmp_path / 'lake').create_tables()


@pytest.fixture
def control(tmp_path):
    from news_lake.storage.control import ControlStore

    return ControlStore(tmp_path / 'lake' / 'control.db')


@pytest.fixture
def coordinator(lake, control):
    from news_lake.storage.coordinator import Coordinator

    return Coordinator(lake, control)


def logical_state(lake, control, release_ids):
    """Content-level final state: records per table, releases (ignoring volatile
    snapshot ids but keeping table uuids), cursor, availability."""
    from news_lake.contract.records import CONTENT_TABLES

    state = {}
    for table in CONTENT_TABLES:
        state[table] = sorted((json.dumps(r, sort_keys=True) for r in lake.read_all(table)))
    releases = []
    for record in lake.read_all('news.releases'):
        if record['id'] in release_ids:
            # Snapshot ids and table UUIDs are warehouse-scoped; convergence is
            # about content, which read_release verifies within the warehouse.
            releases.append(json.dumps(
                {k: v for k, v in record.items() if k != 'snapshots'}, sort_keys=True
            ))
    state['news.releases'] = sorted(releases)
    state['cursor'] = control.active_cursor()
    state['availability'] = {rid: control.availability(rid) for rid in release_ids}
    return state
