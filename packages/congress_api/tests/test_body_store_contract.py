"""B3: raw writes are create-only; collisions never read existing body bytes."""
import base64
import gzip
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

from botocore.exceptions import ClientError
import pytest

from congress_api.retention.body_store import BodyStore, LocalAdapter, R2Adapter

DATA = b'<html>retained source</html>'
SHA = hashlib.sha256(DATA).hexdigest()
KEY = f'bodies/sha256/{SHA[:2]}/{SHA}'
RECEIPT = 'receipts/test/2026-10-27/run-000001.jsonl.gz'
PROVENANCE = 'provenance/reviews/20261027T000000Z.jsonl'


class Adapter:
    def __init__(self, *, old=None, collision=False):
        self.calls, self.old, self.collision = [], old, collision

    def head(self, key):
        self.calls.append(('head', key))
        return self.old

    def create(self, key, source, *, media, encoding, md5, size):
        self.calls.append(('create', key, source.read(), media, encoding, md5, size))
        return not self.collision


@pytest.mark.parametrize('key', [KEY, RECEIPT, PROVENANCE])
@pytest.mark.parametrize('operation', ['replace', 'delete', 'multipart'])
def test_refusal_matrix_before_any_io(key, operation):
    adapter = Adapter()
    store = BodyStore(adapter)
    with pytest.raises(ValueError, match='create-only'):
        store.put(key, Path('/does/not/exist'), 'text/plain', operation=operation)
    assert adapter.calls == []


@pytest.mark.parametrize('key', ['indexes/raw.json', '/bodies/x', 'bodies/../x',
                                  'receipts/x/../../outside', 'bodies/sha256/ff/' + SHA])
def test_unsafe_keys_refused_before_source_read(key):
    adapter = Adapter()
    with pytest.raises(ValueError):
        BodyStore(adapter).put(key, Path('/does/not/exist'), 'text/plain')
    assert adapter.calls == []


@pytest.mark.parametrize('field', ['requested_url', 'url', 'redirects', 'prior_attempts',
                                  'source_context', 'recovery_evidence'])
@pytest.mark.parametrize('url', ['https://docs.house.gov/a?API_KEY=secret',
                                'https://docs.house.gov/a?%74oken=secret',
                                'https://user:secret@docs.house.gov/a'])
def test_credential_urls_refused_in_every_receipt_location(tmp_path, field, url):
    adapter = Adapter()
    value = url if field in {'requested_url', 'url'} else [{'url': url}]
    path = tmp_path / 'receipt'
    path.write_bytes(gzip.compress((json.dumps({field: value}) + '\n').encode()))
    with pytest.raises(ValueError, match='[Cc]redential'):
        BodyStore(adapter).put(RECEIPT, path, 'application/x-ndjson')
    assert adapter.calls == []


def test_body_create_legacy_hit_and_run_dedup(tmp_path):
    path = tmp_path / 'body'
    path.write_bytes(DATA)
    adapter = Adapter()
    store = BodyStore(adapter)
    first = store.put(KEY, path, 'text/html')
    assert (first.outcome, first.suffix, first.size) == ('stored', '', len(gzip.compress(DATA, mtime=0)))
    assert [c[0] for c in adapter.calls] == ['head', 'create']
    _, key, payload, media, encoding, md5, size = adapter.calls[1]
    assert (key, media, encoding, size) == (KEY, 'text/html', 'gzip', len(payload))
    assert gzip.decompress(payload) == DATA and hashlib.md5(payload).hexdigest() == md5
    assert first.md5 == md5
    again = store.put(KEY, Path('/no/read/for/repeat'), 'text/html')
    assert (again.outcome, again.suffix, again.md5, again.size) == ('unchanged', '', md5, size)
    assert len(adapter.calls) == 2
    adapter = Adapter(old={'size': 99, 'etag': '"' + 'A'*32 + '"'})
    result = BodyStore(adapter).put(KEY, Path('/no/read/for/legacy'), 'text/html')
    assert (result.outcome, result.suffix, result.md5, result.size) == ('unchanged', '.gz', 'a'*32, 99)
    assert adapter.calls == [('head', KEY + '.gz')]


def test_prepared_snapshot_collision_needs_no_followup_head(tmp_path):
    path = tmp_path / 'body'
    path.write_bytes(DATA)
    adapter = Adapter(collision=True)
    store = BodyStore(adapter)
    result = store.put_prepared(KEY, path, 'application/pdf')
    assert (result.outcome, result.suffix, result.md5, result.size) == ('unchanged', '', None, None)
    assert [c[0] for c in adapter.calls] == ['head', 'create']

    # A capture sharing this store needs the exact object's metadata.
    adapter.old = dict(size=32, etag='a'*32)
    result = store.put(KEY, Path('/no/read/for/cached-key'), 'application/pdf')
    assert (result.outcome, result.suffix, result.md5, result.size) == ('unchanged', '', 'a'*32, 32)
    assert adapter.calls[2:] == [('head', KEY)]


@pytest.mark.parametrize(('metadata', 'error', 'message'), [
    (None, ValueError, 'Missing stored body'),
    ({'ETag': 'a'*32}, ValueError, 'Missing HEAD metadata'),
    ({'ContentLength': -1, 'ETag': 'a'*32}, ValueError, 'Invalid stored body size'),
    ({'ContentLength': True, 'ETag': 'a'*32}, ValueError, 'Invalid stored body size'),
    ({'ContentLength': 9}, ValueError, 'Missing HEAD metadata'),
    ({'ContentLength': 9, 'ETag': None}, ValueError, 'Invalid HEAD ETag'),
    ({'ContentLength': 9, 'ETag': '"'+'a'*32}, ValueError, 'Invalid stored body MD5'),
    ({'ContentLength': 9, 'ETag': '""'+'a'*32+'""'}, ValueError, 'Invalid stored body MD5'),
    ({'ContentLength': 9, 'ETag': 'a'*32+'-2'}, ValueError, 'Invalid stored body MD5'),
    (OSError('HEAD unavailable'), OSError, 'HEAD unavailable'),
])
def test_body_collision_distinguishes_missing_invalid_and_unavailable_metadata(tmp_path, metadata, error, message):
    from unittest.mock import Mock

    path = tmp_path / 'body'
    path.write_bytes(DATA)
    missing = ClientError({'Error': {'Code': '404'}}, 'HeadObject')
    client = Mock()
    client.head_object.side_effect = [missing, missing if metadata is None else metadata]
    client.put_object.side_effect = ClientError({'Error': {'Code': '412'}}, 'PutObject')
    store = BodyStore(R2Adapter(client, 'raw'))
    with pytest.raises(error, match=message):
        store.put(KEY, path, 'application/pdf')
    assert [(call[0], call.kwargs['Key']) for call in client.mock_calls] == [
        ('head_object', KEY+'.gz'), ('put_object', KEY), ('head_object', KEY)]
    assert KEY not in store.known


@pytest.mark.parametrize('key', [RECEIPT, PROVENANCE])
def test_receipt_and_provenance_collision_fails(tmp_path, key):
    path = tmp_path / 'record'
    path.write_bytes(gzip.compress(b'{}\n') if key == RECEIPT else b'{}\n')
    with pytest.raises(RuntimeError, match='reused'):
        BodyStore(Adapter(collision=True)).put(key, path, 'application/x-ndjson')


def test_local_create_is_atomic_and_preserves_collision(tmp_path):
    root, source = tmp_path / 'raw', tmp_path / 'input'
    source.write_bytes(DATA)
    store = BodyStore(LocalAdapter(root))
    result = store.put(KEY, source, 'application/pdf')
    assert result.outcome == 'stored' and (root / KEY).read_bytes() == DATA
    source.write_bytes(DATA)
    assert BodyStore(LocalAdapter(root)).put(KEY, source, 'application/pdf').outcome == 'unchanged'
    assert (root / KEY).read_bytes() == DATA
    assert list((root / KEY).parent.iterdir()) == [root / KEY]


def test_r2_single_put_checks_md5_and_condition(tmp_path):
    class Client:
        def head_object(self, **args):
            raise ClientError({'Error': {'Code': '404'}}, 'HeadObject')

        def put_object(self, **args):
            payload = args.pop('Body').read()
            assert args == dict(Bucket='raw', Key=KEY, ContentLength=len(DATA),
                                ContentMD5=base64.b64encode(hashlib.md5(DATA).digest()).decode(),
                                ContentType='application/pdf', IfNoneMatch='*')
            return {'ETag': '"' + hashlib.md5(DATA).hexdigest() + '"'}

    source = tmp_path / 'body'
    source.write_bytes(DATA)
    assert BodyStore(R2Adapter(Client(), 'raw')).put(KEY, source, 'application/pdf').outcome == 'stored'


def test_checksum_failure_is_not_success(tmp_path):
    class Client:
        def head_object(self, **args):
            raise ClientError({'Error': {'Code': '404'}}, 'HeadObject')

        def put_object(self, **args):
            return {'ETag': '"bad"'}

    source = tmp_path / 'body'
    source.write_bytes(DATA)
    with pytest.raises(ValueError, match='checksum'):
        BodyStore(R2Adapter(Client(), 'raw')).put(KEY, source, 'application/pdf')


def test_credential_after_apostrophe_in_recorded_url_is_refused(tmp_path):
    path = tmp_path / 'receipt'
    path.write_bytes(gzip.compress(json.dumps({'url': "https://docs.house.gov/a'/?api_key=secret"}).encode()))
    adapter = Adapter()
    with pytest.raises(ValueError, match='Credential'):
        BodyStore(adapter).put(RECEIPT, path, 'application/x-ndjson')
    assert adapter.calls == []


def test_recorded_suffix_resolves_the_physical_body_key():
    from congress_api.retention.body_keys import physical_body_object_key
    assert physical_body_object_key(KEY, 'application/pdf', stored_suffix='') == KEY
    assert physical_body_object_key(KEY + '.gz', 'application/pdf', stored_suffix='.gz') == KEY + '.gz'


def test_local_interrupted_copy_does_not_publish_partial_body(tmp_path):
    class Interrupted(io.BytesIO):
        def read(self, size=-1):
            raise OSError('interrupted source')

    root = tmp_path / 'raw'
    with pytest.raises(OSError, match='interrupted'):
        LocalAdapter(root).create(KEY, Interrupted(DATA), media='application/pdf', encoding=None,
                                  md5=hashlib.md5(DATA).hexdigest(), size=len(DATA))
    assert not (root / KEY).exists()
    assert list((root / KEY).parent.iterdir()) == []


def test_prepared_input_preserves_the_callers_qualified_checksum(tmp_path):
    source=tmp_path/'body'
    source.write_bytes(b'changed after qualification')
    adapter=Adapter()
    with pytest.raises(ValueError,match='qualified'):
        BodyStore(adapter).put_prepared(KEY,source,'application/pdf',
            expected_md5=hashlib.md5(DATA).hexdigest(),expected_size=len(DATA))
    assert [c[0] for c in adapter.calls] == ['head']


def test_original_input_must_match_the_content_address_before_create(tmp_path):
    source=tmp_path/'body'
    source.write_bytes(b'wrong original bytes')
    adapter=Adapter()
    with pytest.raises(ValueError,match='identity'):
        BodyStore(adapter).put(KEY,source,'text/html')
    assert [c[0] for c in adapter.calls] == ['head']


def test_retained_references_keep_both_qualified_copies_in_the_run_cache():
    class PhysicalCopies(Adapter):
        def head(self, key):
            super().head(key)
            if key == KEY:
                return dict(size=123, etag='b'*32)
            return dict(size=99, etag='a'*32)

    adapter = PhysicalCopies()
    store = BodyStore(adapter)
    bare = store.reference(KEY, stored_suffix='')
    legacy = store.reference(KEY, stored_suffix='.gz')
    assert (bare.outcome, bare.suffix, bare.md5, bare.size) == ('unchanged', '', 'b'*32, 123)
    assert (legacy.outcome, legacy.suffix, legacy.md5, legacy.size) == ('unchanged', '.gz', 'a'*32, 99)
    assert store.reference(KEY, stored_suffix='') == bare
    assert store.reference(KEY, stored_suffix='.gz') == legacy
    assert store.put(KEY, Path('/no/read/for/cached-key'), 'text/html') == legacy
    assert adapter.calls == [('head', KEY), ('head', KEY+'.gz')]


def test_missing_retained_reference_never_fabricates_a_body():
    adapter=Adapter()
    with pytest.raises(ValueError,match='Missing retained'):
        BodyStore(adapter).reference(KEY,stored_suffix='.gz')
    assert adapter.calls==[('head',KEY+'.gz')]


def test_embedded_recorded_url_keeps_apostrophes_during_credential_check(tmp_path):
    path=tmp_path/'receipt'
    path.write_bytes(gzip.compress(json.dumps({'error':"request 'https://docs.house.gov/a'/?api_key=secret' failed"}).encode()))
    adapter=Adapter()
    with pytest.raises(ValueError,match='Credential'):
        BodyStore(adapter).put(RECEIPT,path,'application/x-ndjson')
    assert adapter.calls==[]


def _gzip_body(data):
    buffer = io.BytesIO()
    with gzip.GzipFile(filename='', fileobj=buffer, mode='wb', compresslevel=6, mtime=0) as zipped:
        zipped.write(data)
    return buffer.getvalue()


def _service_error(code, status, operation='PutObject', message='Reduce your concurrent request rate for the same object'):
    return ClientError(
        {'Error': {'Code': code, 'Message': message}, 'ResponseMetadata': {'HTTPStatusCode': status}},
        operation,
    )


@pytest.mark.parametrize('transient_error', [
    _service_error('ServiceUnavailable', 503),
    _service_error('SlowDown', 503),
    _service_error('InternalError', 500),
    pytest.param('read_timeout', id='ReadTimeoutError'),
])
def test_r2_create_polls_head_and_confirms_settled_compressed_body(tmp_path, monkeypatch, transient_error):
    import time
    from botocore.exceptions import ReadTimeoutError

    if transient_error == 'read_timeout':
        transient_error = ReadTimeoutError(endpoint_url='https://r2.example.test')
    compressed = _gzip_body(DATA)
    waits, puts, heads, stored = [], [], [], {}
    settled_looks = 0

    class Client:
        def head_object(self, *, Bucket, Key):
            nonlocal settled_looks
            assert Bucket == 'raw'
            heads.append(Key)
            if Key == KEY and KEY in stored:
                settled_looks += 1
                if settled_looks == 1:
                    raise _service_error('404', 404, 'HeadObject', 'Not Found')
                payload = stored[Key]
                return {'ContentLength': len(payload), 'ETag': '"' + hashlib.md5(payload).hexdigest() + '"'}
            raise _service_error('404', 404, 'HeadObject', 'Not Found')

        def put_object(self, **args):
            payload = args['Body'].read()
            puts.append((args['Key'], args.get('ContentEncoding'), args.get('IfNoneMatch'), payload))
            stored[args['Key']] = payload
            raise transient_error

    monkeypatch.setattr(time, 'sleep', waits.append)
    source = tmp_path / 'body.html'
    source.write_bytes(DATA)
    result = BodyStore(R2Adapter(Client(), 'raw')).put(KEY, source, 'text/html')
    assert (result.outcome, result.suffix, result.size, result.md5) == (
        'stored', '', len(compressed), hashlib.md5(compressed).hexdigest())
    assert len(puts) == 1 and puts[0] == (KEY, 'gzip', '*', compressed)
    assert heads == [KEY + '.gz', KEY, KEY]
    assert waits == [0, 2] and sum(waits) <= 22
    assert gzip.decompress(stored[KEY]) == DATA

    # Ordinary 412 and non-transient 403 must not enter the settle poll.
    class NonSettlingClient:
        mode = '412'

        def head_object(self, *, Bucket, Key):
            if self.mode == '412' and Key == KEY:
                return {'ContentLength': len(compressed), 'ETag': '"' + hashlib.md5(compressed).hexdigest() + '"'}
            raise _service_error('404', 404, 'HeadObject', 'Not Found')

        def put_object(self, **args):
            if self.mode == '412':
                raise _service_error('PreconditionFailed', 412)
            raise _service_error('AccessDenied', 403)

    waits.clear()
    client = NonSettlingClient()
    unchanged = BodyStore(R2Adapter(client, 'raw')).put(KEY, source, 'text/html')
    assert (unchanged.outcome, unchanged.md5, unchanged.size) == (
        'unchanged', hashlib.md5(compressed).hexdigest(), len(compressed))
    assert waits == []
    client.mode = '403'
    with pytest.raises(ClientError, match='AccessDenied'):
        BodyStore(R2Adapter(client, 'raw')).put(KEY, source, 'text/html')
    assert waits == []


@pytest.mark.parametrize('replay_mode', ['succeeds', 'settles_after_503', 'fails'])
def test_r2_create_persistent_absence_replays_once_within_bounded_wait(tmp_path, monkeypatch, replay_mode):
    import time

    compressed = _gzip_body(DATA)
    waits, puts, stored = [], [], {}

    class Client:
        def head_object(self, *, Bucket, Key):
            if Key in stored:
                payload = stored[Key]
                return {'ContentLength': len(payload), 'ETag': '"' + hashlib.md5(payload).hexdigest() + '"'}
            raise _service_error('404', 404, 'HeadObject', 'Not Found')

        def put_object(self, **args):
            payload = args['Body'].read()
            puts.append((args['Key'], args.get('IfNoneMatch'), len(payload)))
            if len(puts) == 1:
                raise _service_error('ServiceUnavailable', 503)
            if replay_mode == 'succeeds':
                stored[args['Key']] = payload
                return {'ETag': '"' + hashlib.md5(payload).hexdigest() + '"'}
            if replay_mode == 'settles_after_503':
                stored[args['Key']] = payload
                raise _service_error('ServiceUnavailable', 503, message='Replay response lost')
            raise _service_error('ServiceUnavailable', 503, message='Still unavailable')

    monkeypatch.setattr(time, 'sleep', waits.append)
    source = tmp_path / 'body.html'
    source.write_bytes(DATA)
    store = BodyStore(R2Adapter(Client(), 'raw'))
    if replay_mode == 'fails':
        with pytest.raises(ClientError, match='Reduce your concurrent request rate'):
            store.put(KEY, source, 'text/html')
        assert KEY not in stored and KEY not in store.known
    else:
        result = store.put(KEY, source, 'text/html')
        assert (result.outcome, result.size, result.md5) == (
            'stored', len(compressed), hashlib.md5(compressed).hexdigest())
        assert gzip.decompress(stored[KEY]) == DATA
    assert puts == [(KEY, '*', len(compressed)), (KEY, '*', len(compressed))]
    assert waits == [0, 2, 5, 15] and sum(waits) == 22


@pytest.mark.parametrize('mismatch', ['wrong_md5', 'uncompressed_length', 'replay_collision_wrong_bytes'])
def test_r2_create_refuses_stored_object_with_different_bytes(tmp_path, monkeypatch, mismatch):
    import time

    compressed = _gzip_body(DATA)
    waits, puts = [], []

    class Client:
        def head_object(self, *, Bucket, Key):
            if Key == KEY + '.gz':
                raise _service_error('404', 404, 'HeadObject', 'Not Found')
            if mismatch == 'wrong_md5':
                return {'ContentLength': len(compressed), 'ETag': '"' + hashlib.md5(b'different').hexdigest() + '"'}
            if mismatch == 'uncompressed_length':
                return {'ContentLength': len(DATA), 'ETag': '"' + hashlib.md5(DATA).hexdigest() + '"'}
            if len(puts) < 2:
                raise _service_error('404', 404, 'HeadObject', 'Not Found')
            other = b'competing bytes'
            return {'ContentLength': len(other), 'ETag': '"' + hashlib.md5(other).hexdigest() + '"'}

        def put_object(self, **args):
            args['Body'].read()
            puts.append(args['Key'])
            if len(puts) == 1:
                raise _service_error('ServiceUnavailable', 503)
            raise _service_error('PreconditionFailed', 412)

    monkeypatch.setattr(time, 'sleep', waits.append)
    source = tmp_path / 'body.html'
    source.write_bytes(DATA)
    store = BodyStore(R2Adapter(Client(), 'raw'))
    with pytest.raises(ValueError, match='differs from expected bytes'):
        store.put(KEY, source, 'text/html')
    assert KEY not in store.known
    if mismatch == 'replay_collision_wrong_bytes':
        assert len(puts) == 2 and waits == [0, 2, 5, 15]
    else:
        assert len(puts) == 1 and waits == [0]


@pytest.mark.parametrize(('media', 'encoding'), [('text/html', 'gzip'), ('application/pdf', None)])
def test_r2_create_replay_rewinds_stream_and_resends_full_bytes(tmp_path, monkeypatch, media, encoding):
    import time

    expected = _gzip_body(DATA) if encoding == 'gzip' else DATA
    waits, sent, stored = [], [], {}

    class Client:
        def head_object(self, *, Bucket, Key):
            raise _service_error('404', 404, 'HeadObject', 'Not Found')

        def put_object(self, **args):
            stream = args['Body']
            payload = stream.read()
            assert stream.read() == b''  # stream is at EOF after the attempt consumes it
            sent.append(payload)
            assert len(payload) == args['ContentLength'] == len(expected) > 0
            assert args['ContentMD5'] == base64.b64encode(hashlib.md5(payload).digest()).decode()
            if len(sent) == 1:
                raise _service_error('ServiceUnavailable', 503)
            stored[args['Key']] = payload
            return {'ETag': '"' + hashlib.md5(payload).hexdigest() + '"'}

    monkeypatch.setattr(time, 'sleep', waits.append)
    source = tmp_path / 'body'
    source.write_bytes(DATA)
    result = BodyStore(R2Adapter(Client(), 'raw')).put(KEY, source, media)
    assert result.outcome == 'stored'
    assert sent == [expected, expected]
    assert stored[KEY] == expected
    assert waits == [0, 2, 5, 15]


@pytest.mark.parametrize('key', [RECEIPT, PROVENANCE])
@pytest.mark.parametrize('mode', ['matching_head_after_503', 'replay_412_after_503'])
def test_r2_create_does_not_reconcile_ordinary_receipt_or_provenance_keys(tmp_path, monkeypatch, key, mode):
    import time
    from congress_api.retention.body_store import RawNameCollision

    raw_line = b'{"url":"https://docs.house.gov/a"}\n'
    payload = gzip.compress(raw_line, mtime=0) if key == RECEIPT else raw_line
    waits, puts, heads = [], [], []
    stored = {key: payload} if mode == 'matching_head_after_503' else {}

    class Client:
        def head_object(self, *, Bucket, Key):
            heads.append(Key)
            if Key in stored:
                data = stored[Key]
                return {'ContentLength': len(data), 'ETag': '"' + hashlib.md5(data).hexdigest() + '"'}
            raise _service_error('404', 404, 'HeadObject', 'Not Found')

        def put_object(self, **args):
            args['Body'].read()
            puts.append(args['Key'])
            if len(puts) == 1:
                raise _service_error('ServiceUnavailable', 503)
            stored[args['Key']] = payload
            raise _service_error('PreconditionFailed', 412)

    monkeypatch.setattr(time, 'sleep', waits.append)
    source = tmp_path / 'record'
    source.write_bytes(payload)
    store = BodyStore(R2Adapter(Client(), 'raw'))
    with pytest.raises(ClientError, match='Reduce your concurrent request rate'):
        store.put(key, source, 'application/x-ndjson')
    assert puts == [key]
    assert heads == []
    assert waits == []
    assert key not in store._provenance_acks

    with pytest.raises(RawNameCollision):
        store.put(key, source, 'application/x-ndjson')
    assert puts == [key, key]
    assert heads == []
    assert waits == []


@pytest.mark.parametrize('head_mode', [
    '404',
    'NoSuchKey',
    'NotFound',
    'head_503',
    'head_timeout',
    '404_then_head_503',
])
def test_r2_create_only_treats_404_or_nosuchkey_as_absent_and_raises_original_error_when_head_fails(
    tmp_path, monkeypatch, head_mode,
):
    import time
    from botocore.exceptions import ReadTimeoutError

    waits, puts, poll_heads, stored = [], [], [], {}

    class Client:
        def head_object(self, *, Bucket, Key):
            if Key == KEY + '.gz':
                raise _service_error('404', 404, 'HeadObject', 'Not Found')
            if Key in stored:
                data = stored[Key]
                return {'ContentLength': len(data), 'ETag': '"' + hashlib.md5(data).hexdigest() + '"'}
            poll_heads.append(Key)
            if head_mode in {'404', 'NoSuchKey', 'NotFound'}:
                raise _service_error(head_mode, 404, 'HeadObject', head_mode)
            if head_mode == '404_then_head_503' and len(poll_heads) == 1:
                raise _service_error('404', 404, 'HeadObject', 'Not Found')
            if head_mode == 'head_timeout':
                raise ReadTimeoutError(endpoint_url='https://r2.example.test')
            raise _service_error('ServiceUnavailable', 503, 'HeadObject', 'HEAD throttled')

        def put_object(self, **args):
            payload = args['Body'].read()
            puts.append(args['Key'])
            if len(puts) == 1:
                raise _service_error('ServiceUnavailable', 503, 'PutObject', 'Original PutObject 503')
            stored[args['Key']] = payload
            return {'ETag': '"' + hashlib.md5(payload).hexdigest() + '"'}

    monkeypatch.setattr(time, 'sleep', waits.append)
    source = tmp_path / 'body.pdf'
    source.write_bytes(DATA)
    store = BodyStore(R2Adapter(Client(), 'raw'))
    if head_mode in {'404', 'NoSuchKey'}:
        result = store.put(KEY, source, 'application/pdf')
        assert result.outcome == 'stored'
        assert len(puts) == 2
        assert waits == [0, 2, 5, 15]
    elif head_mode == 'NotFound':
        with pytest.raises(ClientError, match='NotFound'):
            store.put(KEY, source, 'application/pdf')
        assert len(puts) == 1
        assert waits == [0]
    else:
        with pytest.raises(ClientError, match='Original PutObject 503'):
            store.put(KEY, source, 'application/pdf')
        assert len(puts) == 1
        assert waits == [0, 2, 5, 15]
        assert KEY not in stored and KEY not in store.known


def test_r2_create_per_writer_reconciliation_budget_stops_further_waits(tmp_path, monkeypatch):
    import time

    waits, puts, poll_heads, stored = [], {}, {}, {}

    class Client:
        def head_object(self, *, Bucket, Key):
            if Key.endswith('.gz'):
                raise _service_error('404', 404, 'HeadObject', 'Not Found')
            if Key in stored:
                data = stored[Key]
                return {'ContentLength': len(data), 'ETag': '"' + hashlib.md5(data).hexdigest() + '"'}
            poll_heads[Key] = poll_heads.get(Key, 0) + 1
            raise _service_error('404', 404, 'HeadObject', 'Not Found')

        def put_object(self, **args):
            payload = args['Body'].read()
            key = args['Key']
            puts[key] = puts.get(key, 0) + 1
            if puts[key] == 1:
                raise _service_error('ServiceUnavailable', 503, 'PutObject', 'Ambiguous write')
            stored[key] = payload
            return {'ETag': '"' + hashlib.md5(payload).hexdigest() + '"'}

    monkeypatch.setattr(time, 'sleep', waits.append)
    store = BodyStore(R2Adapter(Client(), 'raw'))
    items = []
    for index in range(5):
        body = DATA + f'-{index}'.encode()
        sha = hashlib.sha256(body).hexdigest()
        key = f'bodies/sha256/{sha[:2]}/{sha}'
        path = tmp_path / f'body-{index}.pdf'
        path.write_bytes(body)
        items.append((key, path))

    for key, path in items[:3]:
        assert store.put(key, path, 'application/pdf').outcome == 'stored'
        assert puts[key] == 2 and poll_heads[key] == 4
    assert waits == [0, 2, 5, 15] * 3 and sum(waits) == 66

    for key, path in items[3:]:
        with pytest.raises(ClientError, match='Ambiguous write'):
            store.put(key, path, 'application/pdf')
        assert puts[key] == 1 and key not in poll_heads and key not in stored
    assert waits == [0, 2, 5, 15] * 3 and sum(waits) == 66
