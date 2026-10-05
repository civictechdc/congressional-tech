"""Small object-store implementation for the raw mirror; no acquisition policy."""

import base64
import hashlib
import asyncio
import json
import logging
import random
import time
from contextlib import asynccontextmanager, closing
from datetime import timezone
from email.utils import parsedate_to_datetime


LOGGER = logging.getLogger(__name__)


def _throttle_delay(headers, attempt, now):
    """Back off at least a second; refuse a server wait beyond one minute."""
    value = headers.get('retry-after', '')
    try:
        if value.isdigit():
            requested = int(value)
        else:
            date = parsedate_to_datetime(value)
            requested = date.replace(tzinfo=date.tzinfo or timezone.utc).timestamp() - now
    except (TypeError, ValueError, OverflowError):
        requested = 0
    if requested > 60:
        return False  # Do not retry earlier than the server permits.
    return max(requested, min(20, 2 ** (attempt - 1)) + random.random())


def _configure_retries(client):
    """Extend SDK retries for R2's HTTP 429 without a second attempt budget."""
    # Do not invent a retry budget for clients using an implicit SDK default.
    maximum = client.meta.config.retries.get('total_max_attempts')

    def retry(*, response, attempts, operation, request_dict, **_):
        if response is None or response[0].status_code < 400:
            return None
        http, parsed = response
        status = http.status_code
        delay = None
        if status == 429 and maximum is not None:
            delay = (_throttle_delay(http.headers, attempts, time.time())
                     if attempts < maximum else False)
        if status not in (404, 412):
            metadata = parsed.get('ResponseMetadata', {})
            inputs = request_dict['context'].get('input_params', {})
            LOGGER.warning(json.dumps(dict(
                event='r2_request_error', operation=operation.name,
                key=inputs.get('Key'), http_status=status,
                code=parsed.get('Error', {}).get('Code'),
                request_id=metadata.get('RequestId') or http.headers.get('cf-ray'),
                attempt=attempts, max_attempts=maximum, retry_delay_seconds=delay,
            ), sort_keys=True))
        return delay

    # Public SDK extension point. The SDK owns request replay and sync/async
    # sleeping; returning False stops even a later SDK handler's retry decision.
    client.meta.events.register_first('needs-retry.s3', retry, unique_id='r2-http-429')


def put_parameters(bucket, key, body, **conditions):
    return dict(Bucket=bucket, Key=key, Body=body,
                ContentMD5=base64.b64encode(hashlib.md5(body).digest()).decode(),
                ContentType='application/gzip' if key.endswith('.gz') else 'application/octet-stream',
                **conditions)


def verify_upload(result, body):
    if result['ETag'].strip('"') != hashlib.md5(body).hexdigest():
        raise ValueError('Upload checksum mismatch')


@asynccontextmanager
async def threaded_bodies(store):
    """Adapt local stores and existing injected synchronous stores."""
    class Bodies:
        async def put(self, key, data):
            return await asyncio.to_thread(store.put, key, data, immutable=True)

        async def read(self, key):
            return await asyncio.to_thread(store.read, key)

    yield Bodies()


class AsyncBodies:
    """Async I/O for immutable bodies; index state remains with the collector."""
    def __init__(self, client, bucket):
        self.client, self.bucket = client, bucket
        _configure_retries(client)

    async def put(self, key, data):
        from botocore.exceptions import ClientError
        if not key.startswith('bodies/'):
            raise ValueError('Async body upload requires a body key')
        try:
            result = await self.client.put_object(**put_parameters(self.bucket, key, data, IfNoneMatch='*'))
        except ClientError as error:
            if error.response['Error']['Code'] in {'PreconditionFailed', '412'}:
                return False
            raise
        verify_upload(result, data)
        return True

    async def read(self, key):
        response = await self.client.get_object(Bucket=self.bucket, Key=key)
        async with response['Body'] as stream:
            data = await stream.read()
        if len(data) != response['ContentLength']:
            raise ValueError(f'Incomplete stored object: {key}')
        return data


class R2Store:
    def __init__(self, client, bucket, *, async_client=None):
        self.client, self.bucket = client, bucket
        _configure_retries(client)
        self.async_client = async_client
        self.index_etags = {}

    @asynccontextmanager
    async def async_bodies(self):
        if self.async_client is None:
            async with threaded_bodies(self) as bodies:
                yield bodies
        else:
            async with self.async_client() as client:
                yield AsyncBodies(client, self.bucket)

    def read(self, key):
        from botocore.exceptions import ClientError

        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as error:
            if error.response["Error"]["Code"] in {"NoSuchKey", "404"}:
                if key.startswith("indexes/"):
                    self.index_etags[key] = None
                return None
            raise
        if key.startswith("indexes/"):
            self.index_etags[key] = response["ETag"]
        with closing(response["Body"]) as stream:
            data = stream.read()
        if len(data) != response["ContentLength"]:
            raise ValueError(f"Incomplete stored object: {key}")
        return data

    def put(self, key, body, *, immutable=False):
        from botocore.exceptions import ClientError

        options = {}
        if immutable:
            options["IfNoneMatch"] = "*"
        elif key.startswith("indexes/"):
            if key not in self.index_etags:
                raise ValueError("Read an index before replacing it")
            etag = self.index_etags[key]
            options.update({"IfMatch": etag} if etag else {"IfNoneMatch": "*"})
        try:
            result = self.client.put_object(**put_parameters(self.bucket, key, body, **options))
        except ClientError as error:
            if error.response["Error"]["Code"] in {"PreconditionFailed", "412"}:
                if immutable and key.startswith("bodies/"):
                    return False
                if immutable and key.startswith(("catalog-history/sha256/", "indexes/processing/body-results/")) and self.read(key) == body:
                    return False  # A retry may preserve the same prior table again.
                raise RuntimeError(
                    f"Concurrent update or reused receipt name: {key}; published receipts remain recoverable."
                ) from error
            raise
        verify_upload(result, body)
        if key.startswith("indexes/"):
            self.index_etags[key] = result["ETag"]
        return True

    def put_catalog_manifest(self, data, *, expected_version):
        """Use the selector version captured before this catalog build."""
        from congress_api.retention.catalog_publication import MANIFEST_KEY
        self.index_etags[MANIFEST_KEY] = expected_version
        return self.put(MANIFEST_KEY, data)

    def version(self, key):
        """Read an object's version without downloading its contents."""
        from botocore.exceptions import ClientError
        try:
            return self.client.head_object(Bucket=self.bucket, Key=key)['ETag']
        except ClientError as error:
            if error.response['Error']['Code'] in {'NoSuchKey', '404'}:
                return 'missing'
            raise

    def keys(self, prefix):
        for page in self.client.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=prefix
        ):
            for item in page.get("Contents", []):
                yield item["Key"]
