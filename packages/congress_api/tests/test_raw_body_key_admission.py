"""Every raw-write delegate refuses malformed body names before adapter calls."""
import asyncio
from contextlib import contextmanager
import gzip
from hashlib import md5, sha256
import io
import sys
from types import SimpleNamespace

import pytest

from congress_api.retention.body_store import LocalAdapter, create_stored, create_stored_async
from congress_api.retention.r2 import AsyncBodies, R2Store


DATA = b'%PDF-1.7\nbody-key-admission fixture\n%%EOF\n'
SHA = sha256(DATA).hexdigest()
KEY = f'bodies/sha256/{SHA[:2]}/{SHA}'
BAD_KEYS = ['bodies/x', 'bodies/x.gz', 'bodies/../escape',
    'bodies/sha256/aa/'+'a'*63, 'bodies/sha256/aa/'+'a'*65,
    'bodies/sha256/aa/'+'g'*64, 'bodies/sha256/aa/'+'A'*64,
    'bodies/sha256/bb/'+'a'*64, KEY+'.zip', KEY+'\n',
    'bodies//sha256/aa/'+'a'*64, 'bodies/sha256\\aa\\'+'a'*64]


class Client:
    def __init__(self):
        self.calls = []
        self.meta = SimpleNamespace(config=SimpleNamespace(retries={}),
                                    events=SimpleNamespace(register_first=lambda *a, **k: None))

    def put_object(self, **options):
        self.calls.append(('put', options['Key']))
        body = options['Body']
        data = body if isinstance(body, bytes) else body.read()
        return dict(ETag=md5(data).hexdigest())

    def head_object(self, **options):
        self.calls.append(('head', options['Key']))
        raise AssertionError('Admission must not HEAD a malformed name')

    def get_object(self, **options):
        self.calls.append(('get', options['Key']))
        raise AssertionError('Admission must not GET a malformed name')


class AsyncClient(Client):
    async def put_object(self, **options):
        return super().put_object(**options)


@contextmanager
def local_adapter_calls():
    """Observe the production adapter without replacing it or adding a test seam."""
    calls = []
    methods = {LocalAdapter.head.__code__, LocalAdapter.create.__code__}
    previous = sys.getprofile()
    def record(frame, event, arg):
        if event == 'call' and frame.f_code in methods:
            calls.append(frame.f_code.co_name)
    sys.setprofile(record)
    try:
        yield calls
    finally:
        sys.setprofile(previous)


def put(kind, key, data, tmp_path, client):
    if kind == 'async':
        return asyncio.run(AsyncBodies(client, 'fixture').put(key, data))
    source = tmp_path/'input'
    source.write_bytes(data)
    return R2Store(client, 'fixture').put_file(key, source, content_type='application/pdf')


@pytest.mark.parametrize('kind', ['async', 'file'])
@pytest.mark.parametrize('key', BAD_KEYS)
def test_malformed_body_name_refuses_before_adapter_calls(tmp_path, kind, key):
    client = AsyncClient() if kind == 'async' else Client()
    with local_adapter_calls() as local_calls:
        with pytest.raises(ValueError):
            put(kind, key, DATA, tmp_path, client)
    assert client.calls == [] and local_calls == []
    assert not (tmp_path/'raw').exists()


@pytest.mark.parametrize('key', BAD_KEYS)
def test_file_delegate_validates_before_opening_source(tmp_path, key):
    client = Client()
    with pytest.raises(ValueError):
        R2Store(client, 'fixture').put_file(key, tmp_path/'missing-source')
    assert client.calls == []


@pytest.mark.parametrize('kind', ['async', 'file'])
@pytest.mark.parametrize('suffix', ['', '.gz', '.pdf'])
def test_valid_original_content_address_keeps_delegate_behavior(tmp_path, kind, suffix):
    client = AsyncClient() if kind == 'async' else Client()
    data = gzip.compress(DATA, mtime=0) if suffix == '.gz' else DATA
    assert put(kind, KEY+suffix, data, tmp_path, client) is True
    assert client.calls == [('put', KEY+suffix)]


@pytest.mark.parametrize('asynchronous', [False, True])
@pytest.mark.parametrize('key', BAD_KEYS)
def test_shared_preparation_refuses_before_source_reads(key, asynchronous):
    class UnreadSource(io.BytesIO):
        def readinto(self, *args):
            raise AssertionError('Invalid key reached source read')
        def seek(self, *args):
            raise AssertionError('Invalid key reached source seek')
    class Adapter:
        calls = []
        def create(self, *args, **kwargs):
            self.calls.append('create')
            raise AssertionError('Invalid key reached adapter')
    adapter = Adapter()
    source = UnreadSource(DATA)
    with pytest.raises(ValueError):
        if asynchronous:
            asyncio.run(create_stored_async(adapter, key, source, 'application/pdf'))
        else:
            create_stored(adapter, key, source, 'application/pdf')
    assert adapter.calls == []
