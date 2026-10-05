"""Conditional storage writes must preserve a competing writer's index."""

import base64
import hashlib
import io

import pytest

from congress_api.retention.r2 import R2Store

boto3 = pytest.importorskip("boto3")
StreamingBody = pytest.importorskip("botocore.response").StreamingBody
Stubber = pytest.importorskip("botocore.stub").Stubber


def client():
    return boto3.client(
        "s3",
        endpoint_url="https://r2.example.test",
        region_name="auto",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


@pytest.mark.parametrize('value,minimum,maximum', [
    ('', 1, 2), ('invalid', 1, 2), ('NaN', 1, 2), ('-1', 1, 2),
    ('0', 1, 2), ('2', 2, 2), ('60', 60, 60),
    ('Thu, 01 Jan 1970 00:00:05 GMT', 5, 5),
    ('Wed, 31 Dec 1969 23:59:59 GMT', 1, 2),
])
def test_r2_retry_after_respects_server_wait_and_backoff(value, minimum, maximum):
    from congress_api.retention.r2 import _throttle_delay
    assert minimum <= _throttle_delay({'retry-after': value}, 1, 0) <= maximum


@pytest.mark.parametrize('value', ['61', 'Thu, 01 Jan 1970 00:01:01 GMT'])
def test_r2_refuses_retry_after_beyond_bounded_wait(value):
    from congress_api.retention.r2 import _throttle_delay
    assert _throttle_delay({'retry-after': value}, 1, 0) is False


def test_r2_backoff_grows_with_attempts_and_caps_at_twenty_seconds():
    from congress_api.retention.r2 import _throttle_delay
    for attempt, base in [(1, 1), (2, 2), (3, 4), (6, 20)]:
        assert base <= _throttle_delay({}, attempt, 0) < base + 1


@pytest.mark.parametrize('key', ['indexes/captures.parquet', 'indexes/document-filenames.parquet', 'indexes/documents.parquet'])
def test_index_update_uses_read_etag_and_keeps_conflict_visible(key):
    c = client()
    data = b"index"
    etag = '"' + hashlib.md5(data).hexdigest() + '"'
    with Stubber(c) as stub:
        stub.add_response(
            "get_object",
            {
                "Body": StreamingBody(io.BytesIO(data), len(data)),
                "ContentLength": len(data),
                "ETag": etag,
            },
            {"Bucket": "archive", "Key": key},
        )
        stub.add_client_error(
            "put_object",
            service_error_code="PreconditionFailed",
            http_status_code=412,
            expected_params={
                "Bucket": "archive",
                "Key": key,
                "Body": data,
                "ContentMD5": base64.b64encode(hashlib.md5(data).digest()).decode(),
                "ContentType": "application/octet-stream",
                "IfMatch": etag,
            },
        )
        store = R2Store(c, "archive")
        assert store.read(key) == data
        with pytest.raises(RuntimeError, match="Concurrent update"):
            store.put(key, data)
        stub.assert_no_pending_responses()


def test_existing_body_is_preserved_and_receipt_name_collision_fails():
    c = client()
    data = b"compressed"
    with Stubber(c) as stub:
        for key in ("bodies/sha256/a.gz", "receipts/documents/run.jsonl.gz"):
            stub.add_client_error(
                "put_object",
                service_error_code="PreconditionFailed",
                http_status_code=412,
                expected_params={
                    "Bucket": "archive",
                    "Key": key,
                    "Body": data,
                    "ContentMD5": base64.b64encode(hashlib.md5(data).digest()).decode(),
                    "ContentType": "application/gzip",
                    "IfNoneMatch": "*",
                },
            )
        store = R2Store(c, "archive")
        assert store.put("bodies/sha256/a.gz", data, immutable=True) is False
        with pytest.raises(RuntimeError, match="reused receipt"):
            store.put("receipts/documents/run.jsonl.gz", data, immutable=True)


@pytest.mark.parametrize('saved', [b'previous catalog', b'different bytes'])
@pytest.mark.parametrize('prefix', ['catalog-history/sha256/', 'indexes/processing/body-results/'])
def test_catalog_history_retry_requires_identical_bytes(saved, prefix):
    c = client()
    data = b'previous catalog'
    key = f'{prefix}{hashlib.sha256(data).hexdigest()}/document-filenames.parquet'
    with Stubber(c) as stub:
        stub.add_client_error('put_object', service_error_code='PreconditionFailed', http_status_code=412,
            expected_params={'Bucket': 'archive', 'Key': key, 'Body': data,
                'ContentMD5': base64.b64encode(hashlib.md5(data).digest()).decode(),
                'ContentType': 'application/octet-stream', 'IfNoneMatch': '*'})
        stub.add_response('get_object', {'Body': StreamingBody(io.BytesIO(saved), len(saved)),
            'ContentLength': len(saved), 'ETag': '"saved"'}, {'Bucket': 'archive', 'Key': key})
        store = R2Store(c, 'archive')
        if saved == data:
            assert store.put(key, data, immutable=True) is False
        else:
            with pytest.raises(RuntimeError, match='Concurrent update'):
                store.put(key, data, immutable=True)
        stub.assert_no_pending_responses()


def test_catalog_version_uses_head_without_downloading_the_table():
    c = client()
    key = 'indexes/document-filenames.parquet'
    with Stubber(c) as stub:
        stub.add_response('head_object', {'ETag': '"version"'}, {'Bucket': 'archive', 'Key': key})
        stub.add_client_error('head_object', service_error_code='404', http_status_code=404,
                              expected_params={'Bucket': 'archive', 'Key': key})
        store = R2Store(c, 'archive')
        assert store.version(key) == '"version"'
        assert store.version(key) == 'missing'
        # HEAD used for change detection must not authorize replacing that index.
        assert key not in store.index_etags
        stub.assert_no_pending_responses()


def test_catalog_selector_uses_snapshot_etag_even_after_another_read():
    from congress_api.retention.catalog_publication import MANIFEST_KEY
    c = client()
    data = b'new selection'
    with Stubber(c) as stub:
        stub.add_client_error(
            'put_object', service_error_code='PreconditionFailed', http_status_code=412,
            expected_params={'Bucket': 'archive', 'Key': MANIFEST_KEY, 'Body': data,
                             'ContentMD5': base64.b64encode(hashlib.md5(data).digest()).decode(),
                             'ContentType': 'application/octet-stream', 'IfMatch': 'old-etag'})
        store = R2Store(c, 'archive')
        store.index_etags[MANIFEST_KEY] = 'new-etag'
        with pytest.raises(RuntimeError, match='Concurrent'):
            store.put_catalog_manifest(data, expected_version='old-etag')
        stub.assert_no_pending_responses()


@pytest.mark.parametrize('outcome', ['created', 'existing', 'checksum', 'failure'])
def test_async_body_upload_preserves_storage_checks(outcome):
    import asyncio
    from aiobotocore.session import get_session
    from aiobotocore.stub import AioStubber
    from botocore.exceptions import ClientError
    from congress_api.retention.r2 import AsyncBodies, put_parameters

    async def check():
        async with get_session().create_client('s3', endpoint_url='https://r2.example.test',
            region_name='auto', aws_access_key_id='test', aws_secret_access_key='test') as c:
            data, key = b'compressed', 'bodies/sha256/ab/example.gz'
            with AioStubber(c) as stub:
                params = put_parameters('archive', key, data, IfNoneMatch='*')
                if outcome in {'created', 'checksum'}:
                    etag = hashlib.md5(data).hexdigest() if outcome == 'created' else 'wrong'
                    stub.add_response('put_object', {'ETag': '"' + etag + '"'}, params)
                else:
                    stub.add_client_error('put_object',
                        service_error_code='PreconditionFailed' if outcome == 'existing' else 'AccessDenied',
                        http_status_code=412 if outcome == 'existing' else 403, expected_params=params)
                store = AsyncBodies(c, 'archive')
                if outcome == 'checksum':
                    with pytest.raises(ValueError, match='checksum'):
                        await store.put(key, data)
                elif outcome == 'failure':
                    with pytest.raises(ClientError):
                        await store.put(key, data)
                else:
                    assert await store.put(key, data) is (outcome == 'created')
                stub.assert_no_pending_responses()

    asyncio.run(check())


@pytest.mark.parametrize('length', [4, 10])
def test_async_read_checks_length_and_closes_stream(length):
    import asyncio
    from aiobotocore.session import get_session
    from aiobotocore.stub import AioStubber
    from congress_api.retention.r2 import AsyncBodies

    class Stream:
        closed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            self.closed = True

        async def read(self):
            return b'body'

    async def check():
        async with get_session().create_client('s3', endpoint_url='https://r2.example.test',
            region_name='auto', aws_access_key_id='test', aws_secret_access_key='test') as c:
            stream = Stream()
            key = 'bodies/sha256/example.gz'
            with AioStubber(c) as stub:
                stub.add_response('get_object', {'Body': stream, 'ContentLength': length},
                                  {'Bucket': 'archive', 'Key': key})
                store = AsyncBodies(c, 'archive')
                if length == 4:
                    assert await store.read(key) == b'body'
                else:
                    with pytest.raises(ValueError, match='Incomplete stored object'):
                        await store.read(key)
                assert stream.closed
                stub.assert_no_pending_responses()

    asyncio.run(check())
