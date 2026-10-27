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
    assert store.put(KEY, Path('/no/read/for/repeat'), 'text/html').outcome == 'unchanged'
    assert len(adapter.calls) == 2
    adapter = Adapter(old={'size': 99, 'etag': 'old'})
    result = BodyStore(adapter).put(KEY, Path('/no/read/for/legacy'), 'text/html')
    assert (result.outcome, result.suffix) == ('unchanged', '.gz')
    assert adapter.calls == [('head', KEY + '.gz')]


def test_body_collision_no_followup_read(tmp_path):
    path = tmp_path / 'body'
    path.write_bytes(DATA)
    adapter = Adapter(collision=True)
    result = BodyStore(adapter).put(KEY, path, 'application/pdf')
    assert (result.outcome, result.suffix, result.md5, result.size) == ('unchanged', '', None, None)
    assert [c[0] for c in adapter.calls] == ['head', 'create']


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
    source.write_bytes(b'changed')
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
