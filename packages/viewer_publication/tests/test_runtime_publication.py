"""The approved runtime identity must hold before a private object can be written."""
import io
import json

import pytest

from viewer_publication import publish_docspec_runtime as runtime


class Exists(Exception):
    response = {'Error': {'Code': 'PreconditionFailed'}}


class Store:
    def __init__(self, corrupt=False):
        self.objects = {}; self.puts = []; self.gets = []; self.corrupt = corrupt

    def put_object(self, **request):
        assert request['IfNoneMatch'] == '*'
        identity = request['Bucket'], request['Key']
        self.puts.append(identity)
        if identity in self.objects:
            raise Exists()
        data = request['Body'].read()
        assert len(data) == request['ContentLength']
        self.objects[identity] = data

    def get_object(self, **request):
        identity = request['Bucket'], request['Key']; self.gets.append(identity)
        data = self.objects[identity]
        if self.corrupt:
            data = bytes([data[0] ^ 1]) + data[1:]
        return {'Body': io.BytesIO(data), 'ContentLength': len(data)}


@pytest.fixture
def artifact(tmp_path):
    binary = tmp_path / 'docspec'; binary.write_bytes(b'local compiled runtime fixture\x00')
    expected = runtime.build_runtime_descriptor(binary, bucket='congressional-tech-runtime')
    approved = tmp_path / 'approved.json'; approved.write_text(json.dumps(expected))
    output = tmp_path / 'published.json'
    args = ['--binary',str(binary),'--bucket','congressional-tech-runtime','--upload',
            '--expected-descriptor',str(approved),'--output',str(output)]
    return binary, expected, approved, output, args


def test_approved_cli_upload_is_create_only_verified_and_idempotent(artifact):
    binary, expected, _, output, args = artifact
    store = Store()
    assert runtime.main(args, client=store) == 0
    assert json.loads(output.read_text()) == expected
    assert runtime.main(args, client=store) == 0
    assert len(store.objects) == 1 and len(store.puts) == len(store.gets) == 2
    assert next(iter(store.objects.values())) == binary.read_bytes()


@pytest.mark.parametrize('field,value', [
    ('source_revision','a'*40),('platform','darwin-arm64'),('bucket','wrong-runtime-bucket'),
    ('key','unexpected/object'),('bytes',1),('sha256','b'*64),('version',True),('version',1.0),
    ('build_features',['remote','test-util']),('required_capabilities',[]),('unexpected','extra'),
])
def test_changed_approval_refuses_before_any_client_or_put(artifact, monkeypatch, field, value):
    _, expected, approved, output, args = artifact
    expected[field] = value; approved.write_text(json.dumps(expected))
    monkeypatch.setattr(runtime, 'make_client', lambda **_: pytest.fail('approval mismatch reached storage'))
    with pytest.raises(ValueError, match='[Dd]escriptor|[Aa]pprov'):
        runtime.main(args)
    assert not output.exists()


def test_changed_binary_refuses_before_storage_even_at_the_same_size(artifact, monkeypatch):
    binary, _, _, output, args = artifact
    data = binary.read_bytes(); binary.write_bytes(bytes([data[0] ^ 1]) + data[1:])
    monkeypatch.setattr(runtime, 'make_client', lambda **_: pytest.fail('changed binary reached storage'))
    with pytest.raises(ValueError, match='[Dd]escriptor|[Aa]pprov'):
        runtime.main(args)
    assert not output.exists()


@pytest.mark.parametrize('data', [b'{', b'null', b'[]', b' '*(1024**2 + 1)],
                         ids=['invalid-json','null','array','oversized'])
def test_invalid_or_oversized_approval_refuses_before_storage(artifact, monkeypatch, data):
    _, _, approved, output, args = artifact; approved.write_bytes(data)
    monkeypatch.setattr(runtime, 'make_client', lambda **_: pytest.fail('invalid approval reached storage'))
    with pytest.raises(ValueError):
        runtime.main(args)
    assert not output.exists()


def test_readback_failure_never_publishes_a_descriptor(artifact):
    _, _, _, output, args = artifact
    with pytest.raises(ValueError, match='SHA-256'):
        runtime.main(args, client=Store(corrupt=True))
    assert not output.exists()


def test_existing_descriptor_only_mode_still_never_connects(artifact, monkeypatch):
    binary, expected, _, output, _ = artifact
    monkeypatch.setattr(runtime, 'make_client', lambda **_: pytest.fail('preview reached storage'))
    assert runtime.main(['--binary',str(binary),'--bucket','congressional-tech-runtime',
                         '--output',str(output)]) == 0
    assert json.loads(output.read_text()) == expected
