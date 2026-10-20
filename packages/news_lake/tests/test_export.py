"""C5: restricted-export enforcement on release-scoped reads.

Unauthorized exports omit restricted and expired bodies while preserving
redistributable and metadata-only fields; authorized exports preserve
everything; the caller's release read is never mutated.
"""
import copy
import hashlib
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from news_lake.analysis import export_release
from news_lake.contract.records import CONTENT_TABLES, validate_shape

AT = '2026-10-20T04:00:00Z'
PAST = '2026-01-01T00:00:00Z'
FUTURE = '2027-01-01T00:00:00Z'
NOW = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
_id = lambda key: str(uuid5(NAMESPACE_URL, 'news-lake-export-test:' + key))


def _capture(key, *, access, retain_until=None):
    record = {'kind': 'capture', 'id': _id('capture:' + key), 'recorded_at': AT,
              'provider': 'rss', 'request_url': f'https://example.com/{key}',
              'observed_at': AT, 'access': access, 'status': 'succeeded'}
    if access in ('restricted', 'redistributable'):
        record.update({
            'payload_uri': f's3://example-news/{key}.html',
            'payload_hash': hashlib.sha256(key.encode()).hexdigest(),
            'media_type': 'text/html',
            'rights_basis': 'Synthetic fixture.',
        })
    if retain_until is not None:
        record['retain_until'] = retain_until
    return record


def _version(key, *, access, capture_key, text=None):
    record = {'kind': 'version', 'id': _id('version:' + key), 'recorded_at': AT,
              'item_id': _id('item:' + key), 'capture_id': _id('capture:' + capture_key),
              'run_id': _id('run-extract:' + key), 'title': f'Title {key}',
              'publication': {'precision': 'day', 'date': '2026-10-19', 'basis': 'publisher'},
              'access': access}
    if access in ('restricted', 'redistributable'):
        record.update({
            'text': text,
            'text_hash': hashlib.sha256(text.encode('utf-8')).hexdigest(),
            'rights_basis': 'Synthetic fixture.',
        })
    return record


def _release_read():
    captures = [
        _capture('restricted', access='restricted', retain_until=FUTURE),
        _capture('redistributable', access='redistributable', retain_until=FUTURE),
        _capture('expired-restricted', access='restricted', retain_until=PAST),
        _capture('expired-redistributable', access='redistributable', retain_until=PAST),
        _capture('metadata', access='metadata_only'),
    ]
    versions = [
        _version('restricted', access='restricted', capture_key='restricted',
                 text='Restricted body remains local.'),
        _version('redistributable', access='redistributable', capture_key='redistributable',
                 text='Redistributable body.'),
        _version('expired-restricted', access='restricted', capture_key='expired-restricted',
                 text='Expired restricted body.'),
        _version('expired-redistributable', access='redistributable',
                 capture_key='expired-redistributable', text='Expired redistributable body.'),
        _version('metadata', access='metadata_only', capture_key='metadata'),
    ]
    release = {
        'kind': 'release', 'id': _id('release:export'), 'recorded_at': AT,
        'contract_version': '0.1.0',
        'snapshots': [{'table': table, 'table_uuid': _id('uuid:' + table)}
                      for table in CONTENT_TABLES],
        'selections': [], 'checkpoints': [],
    }
    tables = {table: [] for table in CONTENT_TABLES}
    tables['news.captures'] = captures
    tables['news.versions'] = versions
    return {'release': release, 'tables': tables}


def _records(exported, kind):
    return {
        record['id']: record
        for rows in exported['tables'].values()
        for record in rows
        if record['kind'] == kind
    }


def test_fixture_records_are_shape_valid():
    read = _release_read()
    validate_shape(read['release'])
    for rows in read['tables'].values():
        for record in rows:
            validate_shape(record)


def test_unauthorized_export_omits_restricted_capture_payloads():
    exported = export_release(_release_read(), now=NOW)
    capture = _records(exported, 'capture')[_id('capture:restricted')]
    assert capture['access'] == 'metadata_only'
    assert capture['request_url'] == 'https://example.com/restricted'
    assert capture['retain_until'] == FUTURE  # metadata evidence survives
    for field in ('payload_uri', 'payload_hash', 'media_type', 'rights_basis'):
        assert field not in capture


def test_unauthorized_export_omits_restricted_version_bodies():
    exported = export_release(_release_read(), now=NOW)
    version = _records(exported, 'version')[_id('version:restricted')]
    assert version['access'] == 'metadata_only'
    assert version['title'] == 'Title restricted'
    assert version['publication'] == {'precision': 'day', 'date': '2026-10-19',
                                      'basis': 'publisher'}
    for field in ('text', 'text_hash', 'rights_basis'):
        assert field not in version


def test_unauthorized_export_expires_payloads_and_derived_text():
    exported = export_release(_release_read(), now=NOW)
    captures = _records(exported, 'capture')
    versions = _records(exported, 'version')
    for key in ('expired-restricted', 'expired-redistributable'):
        capture = captures[_id('capture:' + key)]
        assert capture['access'] == 'metadata_only'
        assert capture['retain_until'] == PAST  # retained as expiry evidence
        for field in ('payload_uri', 'payload_hash', 'media_type', 'rights_basis'):
            assert field not in capture
        version = versions[_id('version:' + key)]
        assert version['access'] == 'metadata_only'
        for field in ('text', 'text_hash', 'rights_basis'):
            assert field not in version


def test_unauthorized_export_preserves_redistributable_and_metadata_records():
    exported = export_release(_release_read(), now=NOW)
    capture = _records(exported, 'capture')[_id('capture:redistributable')]
    assert capture['access'] == 'redistributable'
    assert capture['payload_uri'] == 's3://example-news/redistributable.html'
    assert capture['rights_basis'] == 'Synthetic fixture.'
    version = _records(exported, 'version')[_id('version:redistributable')]
    assert version['access'] == 'redistributable'
    assert version['text'] == 'Redistributable body.'
    assert version['rights_basis'] == 'Synthetic fixture.'
    metadata = _records(exported, 'version')[_id('version:metadata')]
    assert metadata['access'] == 'metadata_only'
    assert 'text' not in metadata


def test_authorized_export_preserves_everything_as_a_deep_copy():
    read = _release_read()
    exported = export_release(read, authorized=True, now=NOW)
    assert exported['release'] == read['release']
    assert exported['tables'] == read['tables']
    assert exported is not read
    assert exported['tables'] is not read['tables']
    expired = _records(exported, 'capture')[_id('capture:expired-restricted')]
    assert expired['payload_uri'] == 's3://example-news/expired-restricted.html'
    # Mutating the export cannot reach the caller's read.
    expired['access'] = 'metadata_only'
    assert _records(read, 'capture')[_id('capture:expired-restricted')]['access'] == 'restricted'


def test_export_never_mutates_the_input():
    read = _release_read()
    pristine = copy.deepcopy(read)
    export_release(read, now=NOW)
    assert read == pristine


def test_export_rejects_unredacted_credentials():
    import pytest
    from news_lake.contract import ContractError

    for authorized in (False, True):
        read = _release_read()
        read['tables']['news.captures'][0]['request_url'] = 'https://user:secret@example.com/restricted'
        with pytest.raises(ContractError) as raised:
            export_release(read, authorized=authorized, now=NOW)
        assert raised.value.rule == 'unredacted_credentials'
