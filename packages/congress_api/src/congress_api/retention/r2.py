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


def _stream_read_attempts(client):
    # SDK retries stop when GetObject returns its headers. Body consumption
    # needs its own bound: at most three complete reads, each with SDK retries.
    # Respect explicitly disabled retries and clients with no explicit budget.
    return min(3, client.meta.config.retries.get('total_max_attempts', 1))


def _stream_retry_delay(client, key, response, error, attempt):
    maximum = _stream_read_attempts(client)
    delay = 2 ** (attempt - 1) + random.random() if attempt < maximum else None
    metadata = response.get('ResponseMetadata', {})
    LOGGER.warning(json.dumps(dict(
        event='r2_stream_read_error', key=key, error_type=type(error).__name__,
        request_id=metadata.get('RequestId'), attempt=attempt,
        max_attempts=maximum, retry_delay_seconds=delay,
    ), sort_keys=True))
    return delay


def _read_stream(client, key, request, consume):
    """Retry body consumption only; callers own requests and content checks."""
    from botocore.exceptions import IncompleteReadError, ReadTimeoutError, ResponseStreamingError

    for attempt in range(1, _stream_read_attempts(client) + 1):
        response = request()  # SDK request failures do not enter body retries.
        if response is None:
            return None
        try:
            with closing(response['Body']) as stream:
                result = consume(response, stream)
        except (IncompleteReadError, ReadTimeoutError, ResponseStreamingError) as error:
            delay = _stream_retry_delay(client, key, response, error, attempt)
            if delay is None:
                raise
            time.sleep(delay)  # The failed body has already been closed.
            continue
        return result


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
        from aiohttp import ClientPayloadError
        from botocore.exceptions import IncompleteReadError, ReadTimeoutError, ResponseStreamingError

        for attempt in range(1, _stream_read_attempts(self.client) + 1):
            response = await self.client.get_object(Bucket=self.bucket, Key=key)
            try:
                async with response['Body'] as stream:
                    data = await stream.read()
            except (ReadTimeoutError, ResponseStreamingError, IncompleteReadError, ClientPayloadError) as error:
                delay = _stream_retry_delay(self.client, key, response, error, attempt)
                if delay is None:
                    raise
                await asyncio.sleep(delay)
                continue
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

        def request():
            try:
                return self.client.get_object(Bucket=self.bucket, Key=key)
            except ClientError as error:
                if error.response["Error"]["Code"] in {"NoSuchKey", "404"}:
                    if key.startswith("indexes/"):
                        self.index_etags[key] = None
                    return None
                raise

        def consume(response, stream):
            if key == 'indexes/catalog.json':
                if response['ContentLength'] > 1024**2:
                    raise ValueError('Catalog selector exceeds 1 MiB read budget')
                data = stream.read(1024**2 + 1)
                if len(data) > 1024**2:
                    raise ValueError('Catalog selector exceeds 1 MiB read budget')
            else:
                data = stream.read()
            return response, data

        result = _read_stream(self.client, key, request, consume)
        if result is None:
            return None
        response, data = result
        if len(data) != response["ContentLength"]:
            raise ValueError(f"Incomplete stored object: {key}")
        # Only a complete read can authorize a later conditional write.
        if key.startswith("indexes/"):
            self.index_etags[key] = response["ETag"]
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
                if immutable and key.startswith("indexes/processing/body-results/") and self.read(key) == body:
                    return False  # A retry may preserve the same processing result again.
                raise RuntimeError(
                    f"Concurrent update or reused receipt name: {key}; published receipts remain recoverable."
                ) from error
            raise
        verify_upload(result, body)
        if key.startswith("indexes/"):
            self.index_etags[key] = result["ETag"]
        return True

    def put_file(self, key, path):
        """Conditionally retain an immutable body without loading it in memory."""
        from pathlib import Path
        from botocore.exceptions import ClientError
        if not key.startswith('bodies/'):
            raise ValueError('File upload requires a body key')
        with Path(path).open('rb') as source:
            digest = hashlib.file_digest(source, 'md5')
            import os
            length = os.fstat(source.fileno()).st_size
            source.seek(0)
            try:
                result = self.client.put_object(
                    Bucket=self.bucket, Key=key, Body=source, ContentLength=length,
                    ContentMD5=base64.b64encode(digest.digest()).decode(),
                    ContentType='application/gzip', IfNoneMatch='*')
            except ClientError as error:
                if error.response['Error']['Code'] in {'PreconditionFailed', '412'}:
                    return False
                raise
        if result['ETag'].strip('"') != digest.hexdigest():
            raise ValueError('Upload checksum mismatch')
        return True

    def read_file(self, key, path, *, max_bytes):
        """Read a bounded immutable body to disk; pin its version across retries."""
        from pathlib import Path
        if not key.startswith('bodies/') or max_bytes < 0:
            raise ValueError('File read requires a body key and a nonnegative bound')
        etag = None

        def request():
            return self.client.get_object(Bucket=self.bucket, Key=key,
                                          **({'IfMatch': etag} if etag else {}))

        def consume(response, source):
            nonlocal etag
            if response['ContentLength'] > max_bytes:
                raise ValueError('Stored object exceeds file budget')
            if etag is not None and response['ETag'] != etag:
                raise ValueError('Stored object changed during file read')
            etag = response['ETag']
            count = 0
            with Path(path).open('wb') as destination:
                while chunk := source.read(1024**2):
                    count += len(chunk)
                    if count > max_bytes:
                        raise ValueError('Stored object exceeds file budget')
                    destination.write(chunk)
            if count != response['ContentLength']:
                raise ValueError('Incomplete stored object')
            return count

        return _read_stream(self.client, key, request, consume)

    def put_catalog_manifest(self, data, *, expected_version):
        """Use the selector version captured before this catalog build."""
        from congress_api.retention.catalog_publication import MANIFEST_KEY
        return self.put_index_selector(MANIFEST_KEY, data, expected_version=expected_version)

    def put_index_selector(self, key, data, *, expected_version):
        """Compare against the exact selector version captured before preparation."""
        from congress_api.retention.index_selector import require_selector_key
        require_selector_key(key)
        self.index_etags[key] = expected_version
        return self.put(key, data)

    def read_derived_file(self, key, path, *, expected=None):
        """Stream only catalog tables, pinning the object version across retries."""
        from botocore.exceptions import ClientError
        from congress_api.retention.derived_files import require_derived_key, copy_checked
        require_derived_key(key)
        etag = None

        def request():
            try:
                return self.client.get_object(Bucket=self.bucket, Key=key,
                    **({'IfMatch': etag} if etag else {}))
            except ClientError as error:
                if error.response['Error']['Code'] in {'NoSuchKey', '404'} and etag is None:
                    return None
                raise

        def consume(response, source):
            nonlocal etag
            if etag is not None and response['ETag'] != etag:
                raise ValueError('Stored catalog changed during file read')
            etag = response['ETag']
            size = response['ContentLength']
            if expected is not None and size != expected['bytes']:
                raise ValueError(f'Selected catalog size mismatch: {key}')
            result = copy_checked(source, path, size=size, expected=expected, key=key)
            result['version'] = etag
            return result

        return _read_stream(self.client, key, request, consume)

    def put_derived_file(self, key, path, *, expected):
        """Upload an immutable catalog file with streamed checksum verification."""
        import os
        from pathlib import Path
        import shutil
        import tempfile
        from botocore.exceptions import ClientError
        from congress_api.retention.derived_files import require_derived_key, check_identity, VerifiedFile
        require_derived_key(key)
        with Path(path).open('rb') as source:
            before = os.fstat(source.fileno())
            proven = isinstance(expected, VerifiedFile)
            if proven:
                expected.require(path)
            md5, digest, count = hashlib.md5(), None if proven else hashlib.sha256(), 0
            for chunk in iter(lambda: source.read(1024**2), b''):
                md5.update(chunk)
                if digest is not None:
                    digest.update(chunk)
                count += len(chunk)
            actual = {'bytes': count, 'sha256': expected['sha256'] if proven else digest.hexdigest()}
            check_identity(actual, expected, key)
            source.seek(0)
            try:
                result = self.client.put_object(Bucket=self.bucket, Key=key, Body=source,
                    ContentLength=count, ContentMD5=base64.b64encode(md5.digest()).decode(),
                    ContentType='application/vnd.apache.parquet', IfNoneMatch='*')
            except ClientError as error:
                if error.response['Error']['Code'] not in {'PreconditionFailed', '412'}:
                    raise
                if not key.startswith('catalog-history/sha256/'):
                    raise RuntimeError(f'Concurrent update or reused catalog generation: {key}') from error
                directory = Path(tempfile.mkdtemp(prefix='catalog-history-verify-'))
                try:
                    if self.read_derived_file(key, directory / 'existing.parquet', expected=expected) is None:
                        raise ValueError(f'Missing immutable catalog history: {key}')
                except BaseException as failure:
                    failure.add_note(f'Catalog verification evidence retained: {directory}')
                    raise
                shutil.rmtree(directory)
                return False
            after = os.fstat(source.fileno())
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ValueError(f'Catalog source changed during upload: {path}')
        if result['ETag'].strip('"') != md5.hexdigest():
            raise ValueError('Catalog upload checksum mismatch')
        return True

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
