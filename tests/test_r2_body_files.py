"""File-backed R2 bodies preserve checksum, immutability and bounded reads."""

import base64
import hashlib
import io
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError, ReadTimeoutError
from congress_api.retention.r2 import R2Store


class Client:
    def __init__(self):
        self.meta = SimpleNamespace(
            config=SimpleNamespace(retries={"total_max_attempts": 3}),
            events=SimpleNamespace(register_first=lambda *a, **k: None),
        )
        self.reads = []
        self.puts = []
        self.responses = []

    def put_object(self, **args):
        self.puts.append(args)
        assert args["IfNoneMatch"] == "*"
        assert not isinstance(args["Body"], bytes)
        self.data = args["Body"].read()
        assert args["ContentLength"] == len(self.data)
        assert (
            args["ContentMD5"]
            == base64.b64encode(hashlib.md5(self.data).digest()).decode()
        )
        return {"ETag": hashlib.md5(self.data).hexdigest()}

    def get_object(self, **args):
        self.reads.append(args)
        return self.responses.pop(0)


def test_file_upload_streams_and_retains_checksum(tmp_path):
    path = tmp_path / "body"
    path.write_bytes(b"bytes")
    client = Client()
    store = R2Store(client, "bucket")
    assert store.put_file("bodies/x.gz", path)
    assert client.data == b"bytes" and store.index_etags == {}
    assert client.puts[0]["Body"].closed


def test_file_upload_checksum_failure_and_existing_body(tmp_path):
    path = tmp_path / "body"
    path.write_bytes(b"bytes")
    client = Client()
    store = R2Store(client, "bucket")
    client.put_object = lambda **kwargs: {"ETag": "bad"}
    with pytest.raises(ValueError, match="checksum"):
        store.put_file("bodies/x.gz", path)

    def collision(**kwargs):
        raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")

    client.put_object = collision
    assert store.put_file("bodies/x.gz", path) is False


@pytest.mark.parametrize(
    "key", ["indexes/test", "receipts/test", "catalog-history/test"]
)
def test_body_file_operations_cannot_replace_indexes_or_receipts(tmp_path, key):
    store = R2Store(Client(), "bucket")
    with pytest.raises(ValueError):
        store.put_file(key, tmp_path / "body")
    with pytest.raises(ValueError):
        store.read_file(key, tmp_path / "body", max_bytes=10)


def test_read_file_restarts_interrupted_stream_and_pins_etag(tmp_path, monkeypatch):
    class Broken(io.BytesIO):
        def read(self, size=-1):
            assert 0 < size <= 1024**2
            raise ReadTimeoutError(endpoint_url="test")

    monkeypatch.setattr("congress_api.retention.r2.time.sleep", lambda _: None)
    broken = Broken()
    good = io.BytesIO(b"complete")
    client = Client()
    client.responses = [
        dict(Body=broken, ContentLength=8, ETag="version"),
        dict(Body=good, ContentLength=8, ETag="version"),
    ]
    store = R2Store(client, "bucket")
    path = tmp_path / "body"
    assert store.read_file("bodies/x", path, max_bytes=8) == 8
    assert path.read_bytes() == b"complete" and broken.closed and good.closed
    assert "IfMatch" not in client.reads[0] and client.reads[1]["IfMatch"] == "version"
    assert not store.index_etags


@pytest.mark.parametrize(
    "length,data,bound", [(20, b"x", 10), (4, b"abc", 4), (1, b"abc", 2)]
)
def test_read_file_refuses_wrong_or_excessive_size_and_closes(
    tmp_path, length, data, bound
):
    body = io.BytesIO(data)
    client = Client()
    client.responses = [dict(Body=body, ContentLength=length, ETag="v")]
    with pytest.raises(ValueError):
        R2Store(client, "bucket").read_file(
            "bodies/x", tmp_path / "body", max_bytes=bound
        )
    assert body.closed


def test_read_file_refuses_changed_object_on_retry(tmp_path, monkeypatch):
    class Broken(io.BytesIO):
        def read(self, size=-1):
            raise ReadTimeoutError(endpoint_url="test")

    monkeypatch.setattr("congress_api.retention.r2.time.sleep", lambda _: None)
    broken, changed = Broken(), io.BytesIO(b"changed")
    client = Client()
    client.responses = [
        dict(Body=broken, ContentLength=7, ETag="original"),
        dict(Body=changed, ContentLength=7, ETag="changed"),
    ]
    with pytest.raises(ValueError, match="changed"):
        R2Store(client, "bucket").read_file("bodies/x", tmp_path / "body", max_bytes=7)
    assert broken.closed and changed.closed
    assert client.reads[1]["IfMatch"] == "original"


def test_file_stream_does_not_retry_when_sdk_retries_disabled(tmp_path):
    class Broken(io.BytesIO):
        def read(self, size=-1):
            raise ReadTimeoutError(endpoint_url="test")

    client = Client()
    client.meta.config.retries = {"total_max_attempts": 1}
    broken = Broken()
    client.responses = [dict(Body=broken, ContentLength=7, ETag="original")]
    with pytest.raises(ReadTimeoutError):
        R2Store(client, "bucket").read_file("bodies/x", tmp_path / "body", max_bytes=7)
    assert broken.closed and len(client.reads) == 1
