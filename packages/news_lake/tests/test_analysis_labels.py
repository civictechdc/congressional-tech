"""Slice 6 (C6): deterministic keyword baseline topic/tone labels."""
import hashlib
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from news_lake.analysis import classify
from news_lake.context import AdapterContext
from news_lake.contract import check_corpus
from news_lake.contract.records import validate_shape

AT = '2026-10-20T04:00:00Z'
_id = lambda key: str(uuid5(NAMESPACE_URL, 'news-lake-labels-test:' + key))
TYPED_VALUE_FIELDS = ('value_string', 'value_number', 'value_boolean', 'value_strings')


def _capture(key, *, retained=False):
    record = {'kind': 'capture', 'id': _id('capture:' + key), 'recorded_at': AT,
              'provider': 'rss', 'request_url': f'https://example.com/{key}',
              'observed_at': AT, 'access': 'metadata_only', 'status': 'succeeded'}
    if retained:
        record.update({
            'access': 'restricted',
            'payload_uri': f's3://example-news/{key}.html',
            'payload_hash': hashlib.sha256(key.encode()).hexdigest(),
            'media_type': 'text/html',
            'rights_basis': 'Synthetic fixture.',
        })
    return record


def _item(key):
    return {'kind': 'item', 'id': _id('item:' + key), 'recorded_at': AT,
            'canonical_url': f'https://example.com/{key}', 'url_aliases': [],
            'content_type': 'news_article', 'first_seen_at': AT}


def _extract_run(key):
    return {'kind': 'run', 'id': _id('run-extract:' + key), 'recorded_at': AT,
            'processor': 'extract', 'processor_version': 'fixture-1',
            'config_hash': hashlib.sha256(f'extract-config:{key}'.encode()).hexdigest(),
            'input_hash': hashlib.sha256(f'extract-inputs:{key}'.encode()).hexdigest(),
            'inputs': [{'kind': 'capture', 'id': _id('capture:' + key)}],
            'mode': 'live', 'status': 'succeeded', 'started_at': AT, 'finished_at': AT}


def _version(key, *, text=None):
    record = {'kind': 'version', 'id': _id('version:' + key), 'recorded_at': AT,
              'item_id': _id('item:' + key), 'capture_id': _id('capture:' + key),
              'run_id': _id('run-extract:' + key), 'title': f'Title {key}',
              'publication': {'precision': 'day', 'date': '2026-10-19', 'basis': 'publisher'},
              'access': 'metadata_only'}
    if text is not None:
        record['access'] = 'restricted'
        record['rights_basis'] = 'Synthetic fixture.'
        record['text'] = text
        record['text_hash'] = hashlib.sha256(text.encode('utf-8')).hexdigest()
    return record


def _record_set(key, *, text=None):
    return [_capture(key, retained=text is not None), _item(key), _extract_run(key),
            _version(key, text=text)]


CASES = [
    _record_set('budget', text='The council will approve the budget.'),
    _record_set('election', text='The election scandal dominated the campaign.'),
    _record_set('quiet', text='A quiet afternoon downtown.'),
    _record_set('metadata'),  # no text: cannot be classified by this method
]
CORPUS = [record for case in CASES for record in case]
VERSIONS = [case[-1] for case in CASES]
METADATA_VERSION = VERSIONS[-1]


def test_fixture_corpus_is_valid():
    check_corpus(CORPUS)


def test_classifications_are_shape_and_corpus_valid():
    result = classify(VERSIONS)
    for classification in result['classifications']:
        assert validate_shape(classification) is classification
        assert sum(field in classification for field in TYPED_VALUE_FIELDS) == 1
        assert classification['dimension'] in ('topic', 'tone')
        assert classification['taxonomy_version'] == 'keyword-taxonomy-1'
    check_corpus(CORPUS + [result['run'], *result['classifications']])


def test_one_run_names_every_version_in_id_order():
    result = classify(VERSIONS)
    run = result['run']
    assert run['processor'] == 'classify-keywords'
    assert run['processor_version'] == 'keyword-baseline-1'
    assert run['status'] == 'succeeded'
    assert run['inputs'] == [
        {'kind': 'version', 'id': version['id']}
        for version in sorted(VERSIONS, key=lambda version: version['id'])
    ]


def test_replay_with_the_same_clock_is_identical():
    frozen = AdapterContext(clock=lambda: datetime(2026, 10, 20, 4, 0, 0, tzinfo=timezone.utc))
    first = classify(VERSIONS, context=frozen)
    replay = classify(list(reversed(VERSIONS)), context=frozen)
    assert first == replay


def test_metadata_only_versions_produce_no_classifications():
    result = classify(VERSIONS)
    labelled = {classification['version_id'] for classification in result['classifications']}
    assert labelled == {version['id'] for version in VERSIONS if 'text' in version}
    assert METADATA_VERSION['id'] not in labelled


def test_documented_keywords_produce_topic_and_tone_values():
    result = classify(VERSIONS)
    values = {}
    for classification in result['classifications']:
        values.setdefault(classification['version_id'], {})[
            classification['dimension']
        ] = classification['value_string']
    assert values[_id('version:budget')] == {'topic': 'budget', 'tone': 'positive'}
    assert values[_id('version:election')] == {'topic': 'election', 'tone': 'negative'}
    assert values[_id('version:quiet')] == {'topic': 'other', 'tone': 'neutral'}
