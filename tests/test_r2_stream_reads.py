"""Shared body retries preserve each reader's state and partial-file rules."""
import hashlib
import io
import json

import pytest
from botocore import exceptions

from congress_api.retention.r2 import R2Store
from test_r2_body_files import Client as BodyClient


DATA = b'complete'
DERIVED_KEY = 'catalog-generations/' + 'a' * 32 + '/documents.parquet'
KEYS = {'bytes': 'indexes/test', 'body': 'bodies/test.gz', 'derived': DERIVED_KEY}


class Client(BodyClient):
    def get_object(self, **args):
        response = super().get_object(**args)
        if isinstance(response, BaseException):
            raise response
        return response


def read(store, kind, path):
    if kind == 'bytes':
        return store.read(KEYS[kind])
    if kind == 'body':
        return store.read_file(KEYS[kind], path, max_bytes=len(DATA))
    return store.read_derived_file(KEYS[kind], path, expected={
        'bytes': len(DATA), 'sha256': hashlib.sha256(DATA).hexdigest()})


def failure(name):
    return {
        'ReadTimeoutError': lambda: exceptions.ReadTimeoutError(endpoint_url='fixture'),
        'ResponseStreamingError': lambda: exceptions.ResponseStreamingError(error='reset'),
        'IncompleteReadError': lambda: exceptions.IncompleteReadError(actual_bytes=4, expected_bytes=8),
    }[name]()


class Interrupted(io.BytesIO):
    def __init__(self, error):
        super().__init__(DATA)
        self.error = error

    def read(self, size=-1):
        if size == -1:
            super().read(4)
            raise self.error
        if self.tell():
            raise self.error
        return super().read(4)


@pytest.mark.parametrize('kind', KEYS)
@pytest.mark.parametrize('error_name', ['ReadTimeoutError', 'ResponseStreamingError', 'IncompleteReadError'])
@pytest.mark.parametrize('recover', [True, False])
def test_interruption_closes_before_backoff_and_preserves_reader_state(
    tmp_path, monkeypatch, caplog, kind, error_name, recover,
):
    path = tmp_path / 'output'
    streams = [Interrupted(failure(error_name)) for _ in range(2)]
    streams.append(io.BytesIO(DATA) if recover else Interrupted(failure(error_name)))
    client = Client()
    client.responses = [dict(Body=stream, ContentLength=len(DATA), ETag=f'version-{i}',
                             ResponseMetadata={'RequestId': f'request-{i}'})
                        for i, stream in enumerate(streams)]
    if kind != 'bytes':
        for response in client.responses:
            response['ETag'] = 'pinned'
    store = R2Store(client, 'bucket')
    store.index_etags[KEYS[kind]] = 'previous-complete'
    sleeps = []

    def sleep(delay):
        assert streams[len(sleeps)].closed
        assert store.index_etags[KEYS[kind]] == 'previous-complete'
        if kind == 'body':
            assert path.read_bytes() == DATA[:4]
        elif kind == 'derived':
            assert not path.exists()
            assert all(p.read_bytes() == DATA[:4] for p in tmp_path.glob('*.partial'))
        sleeps.append(delay)

    monkeypatch.setattr('congress_api.retention.r2.time.sleep', sleep)
    monkeypatch.setattr('congress_api.retention.r2.random.random', lambda: 0.25)
    if recover:
        result = read(store, kind, path)
        if kind == 'bytes':
            assert result == DATA and store.index_etags[KEYS[kind]] == 'version-2'
        else:
            assert path.read_bytes() == DATA
            if kind == 'body':
                assert result == len(DATA)
            else:
                assert result['version'] == 'pinned'
    else:
        with pytest.raises(getattr(exceptions, error_name)):
            read(store, kind, path)
        assert store.index_etags[KEYS[kind]] == 'previous-complete'
        if kind == 'derived':
            assert not path.exists()
    assert all(stream.closed for stream in streams)
    assert sleeps == [1.25, 2.25]
    assert len(client.reads) == 3
    assert ['IfMatch' in request for request in client.reads] == (
        [False, False, False] if kind == 'bytes' else [False, True, True])
    if kind == 'derived':
        assert len(list(tmp_path.glob('*.partial'))) == (2 if recover else 3)
    logs = [json.loads(record.message) for record in caplog.records
            if record.name == 'congress_api.retention.r2']
    assert logs == [dict(event='r2_stream_read_error', key=KEYS[kind], error_type=error_name,
                         request_id=f'request-{i}', attempt=i + 1, max_attempts=3,
                         retry_delay_seconds=[1.25, 2.25, None][i])
                    for i in range(2 if recover else 3)]


@pytest.mark.parametrize('kind', KEYS)
def test_request_timeout_stays_outside_body_retry_budget(tmp_path, monkeypatch, kind):
    client = Client()
    error = failure('ReadTimeoutError')
    client.responses = [error]
    monkeypatch.setattr('congress_api.retention.r2.time.sleep',
                        lambda _: pytest.fail('SDK request failures cannot enter body retries'))
    with pytest.raises(exceptions.ReadTimeoutError) as caught:
        read(R2Store(client, 'bucket'), kind, tmp_path / 'output')
    assert caught.value is error and len(client.reads) == 1


@pytest.mark.parametrize('kind', KEYS)
@pytest.mark.parametrize('retries', [{}, {'total_max_attempts': 1}])
def test_no_explicit_body_retry_budget_stops_after_one_read(tmp_path, monkeypatch, kind, retries):
    client = Client()
    client.meta.config.retries = retries
    stream = Interrupted(failure('ReadTimeoutError'))
    client.responses = [dict(Body=stream, ContentLength=len(DATA), ETag='pinned')]
    monkeypatch.setattr('congress_api.retention.r2.time.sleep',
                        lambda _: pytest.fail('A disabled retry budget cannot sleep'))
    with pytest.raises(exceptions.ReadTimeoutError):
        read(R2Store(client, 'bucket'), kind, tmp_path / 'output')
    assert stream.closed and len(client.reads) == 1


@pytest.mark.parametrize('kind', KEYS)
def test_missing_initial_object_keeps_reader_absence_policy(tmp_path, kind):
    client = Client()
    client.responses = [exceptions.ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject')]
    store = R2Store(client, 'bucket')
    store.index_etags[KEYS[kind]] = 'previous'
    if kind == 'body':
        with pytest.raises(exceptions.ClientError):
            read(store, kind, tmp_path / 'output')
    else:
        assert read(store, kind, tmp_path / 'output') is None
    assert store.index_etags[KEYS[kind]] == (None if kind == 'bytes' else 'previous')
    assert len(client.reads) == 1


@pytest.mark.parametrize('kind', ['body', 'derived'])
def test_missing_object_after_pinned_partial_is_a_failure(tmp_path, monkeypatch, kind):
    client = Client()
    stream = Interrupted(failure('ReadTimeoutError'))
    missing = exceptions.ClientError({'Error': {'Code': '404'}}, 'GetObject')
    client.responses = [dict(Body=stream, ContentLength=len(DATA), ETag='pinned'), missing]
    sleeps = []
    monkeypatch.setattr('congress_api.retention.r2.time.sleep', sleeps.append)
    path = tmp_path / 'output'
    with pytest.raises(exceptions.ClientError) as caught:
        read(R2Store(client, 'bucket'), kind, path)
    assert caught.value is missing and stream.closed
    assert len(sleeps) == 1 and client.reads[1]['IfMatch'] == 'pinned'
    if kind == 'derived':
        assert not path.exists() and len(list(tmp_path.glob('*.partial'))) == 1
    else:
        assert path.read_bytes() == DATA[:4]


def test_index_write_authority_waits_for_body_close(tmp_path):
    class BadClose(io.BytesIO):
        def close(self):
            super().close()
            raise OSError('close failed')

    client = Client()
    stream = BadClose(DATA)
    client.responses = [dict(Body=stream, ContentLength=len(DATA), ETag='new')]
    store = R2Store(client, 'bucket')
    store.index_etags[KEYS['bytes']] = 'previous'
    with pytest.raises(OSError, match='close failed'):
        read(store, 'bytes', tmp_path / 'output')
    assert stream.closed and store.index_etags[KEYS['bytes']] == 'previous'
