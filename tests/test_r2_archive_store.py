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
