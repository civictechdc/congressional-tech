"""Small object-store implementation for the raw mirror; no acquisition policy."""

import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import asyncio
import json
import logging
import os
from pathlib import Path
import random
import threading
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


PDF_CACHE_CONTROL = 'public, max-age=31536000, immutable'


def put_parameters(bucket, key, body, **conditions):
    md5_b64 = base64.b64encode(hashlib.md5(body).digest()).decode()
    if key.endswith('.pdf'):
        headers = dict(
            ContentType='application/pdf',
            ContentDisposition='inline',
            CacheControl=PDF_CACHE_CONTROL,
        )
        headers.update(conditions)
        return dict(Bucket=bucket, Key=key, Body=body, ContentMD5=md5_b64, **headers)
    return dict(Bucket=bucket, Key=key, Body=body,
                ContentMD5=md5_b64,
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
    def __init__(self, client, bucket, *, async_client=None, excluded_body_hashes=None, store_uncompressed_pdfs=False, cache_dir=None):
        self.client, self.bucket = client, bucket
        _configure_retries(client)
        self.async_client = async_client
        self.excluded_body_hashes = excluded_body_hashes
        self.store_uncompressed_pdfs = store_uncompressed_pdfs
        self.index_etags = {}
        from congress_api.retention.body_store import BodyStore, R2Adapter
        self.raw = BodyStore(R2Adapter(client, bucket))
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self._manifest_cache_dir = self.cache_dir / 'r2-native-manifests' if self.cache_dir is not None else None
        self._immutable_cache_dir = self.cache_dir / 'r2-immutable' if self.cache_dir is not None else None
        self._manifest_lock = threading.Lock()
        self._manifest_mem = {}
        self._manifest_pool = None
        self._manifest_futures = []

    def _write_manifest_disk_cache(self, disk_path, body):
        try:
            disk_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = disk_path.with_name(f'.{disk_path.name}.{threading.get_ident()}.tmp')
            tmp_path.write_bytes(body)
            os.replace(tmp_path, disk_path)
        except OSError:
            pass

    def _upload_manifest(self, key, body, disk_path):
        from botocore.exceptions import ClientError

        if disk_path.is_file():
            try:
                if disk_path.stat().st_size == len(body):
                    return False
            except OSError:
                pass
        try:
            result = self.client.put_object(**put_parameters(self.bucket, key, body, IfNoneMatch='*'))
        except ClientError as error:
            if error.response['Error']['Code'] in {'PreconditionFailed', '412'}:
                self._write_manifest_disk_cache(disk_path, body)
                return False
            raise
        verify_upload(result, body)
        self._write_manifest_disk_cache(disk_path, body)
        return True

    def _flush_manifests(self):
        if not self._manifest_futures:
            return
        with self._manifest_lock:
            pending = list(self._manifest_futures)
            self._manifest_futures.clear()
        for future in pending:
            future.result()

    @asynccontextmanager
    async def async_bodies(self):
        if self.async_client is None:
            async with threaded_bodies(self) as bodies:
                yield bodies
        else:
            async with self.async_client() as client:
                yield AsyncBodies(client, self.bucket)

    def _immutable_cache_path(self, key):
        if (
            self._immutable_cache_dir is None
            or not isinstance(key, str)
            or key.endswith('.pdf')
            or not key.startswith(('receipts/', 'bodies/sha256/'))
        ):
            return None
        return self._immutable_cache_dir / key

    def prefetch_immutable(self, keys, *, max_workers=64):
        if self._immutable_cache_dir is None:
            return
        missing = []
        for k in dict.fromkeys(keys):
            cache_path = self._immutable_cache_path(k)
            if cache_path is not None and not cache_path.is_file():
                missing.append(k)
        if not missing:
            return
        with ThreadPoolExecutor(max_workers=min(max_workers, len(missing))) as pool:
            list(pool.map(self.read, missing))

    def read(self, key):
        from botocore.exceptions import ClientError

        immutable_path = self._immutable_cache_path(key)
        if immutable_path is not None and immutable_path.is_file():
            try:
                return immutable_path.read_bytes()
            except OSError:
                pass

        if self._manifest_cache_dir is not None and key.startswith('indexes/native-manifests/'):
            with self._manifest_lock:
                cached = self._manifest_mem.get(key)
            if cached is not None:
                return cached
            disk_path = self._manifest_cache_dir / key.removeprefix('indexes/native-manifests/')
            if disk_path.is_file():
                try:
                    data = disk_path.read_bytes()
                    with self._manifest_lock:
                        if len(self._manifest_mem) < 16384:
                            self._manifest_mem[key] = data
                    return data
                except OSError:
                    pass

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
        if self._manifest_cache_dir is not None and key.startswith('indexes/native-manifests/'):
            with self._manifest_lock:
                if len(self._manifest_mem) < 16384:
                    self._manifest_mem[key] = data
            self._write_manifest_disk_cache(
                self._manifest_cache_dir / key.removeprefix('indexes/native-manifests/'),
                data,
            )
        elif immutable_path is not None:
            self._write_manifest_disk_cache(immutable_path, data)
        return data

    def put(self, key, body, *, immutable=None):
        from botocore.exceptions import ClientError
        from io import BytesIO
        from congress_api.retention.body_store import RAW_PREFIXES, R2Adapter, create_stored
        if key.startswith(RAW_PREFIXES):
            media = ('application/pdf' if key.endswith('.pdf') else
                     'application/gzip' if key.endswith('.gz') else 'application/octet-stream')
            return create_stored(R2Adapter(self.client, self.bucket), key, BytesIO(body), media,
                operation='replace' if immutable is False else 'create').outcome == 'stored'

        if self._manifest_cache_dir is not None and immutable and key.startswith('indexes/native-manifests/'):
            disk_path = self._manifest_cache_dir / key.removeprefix('indexes/native-manifests/')
            with self._manifest_lock:
                if len(self._manifest_mem) >= 16384:
                    self._manifest_mem.clear()
                self._manifest_mem[key] = body
            if disk_path.is_file():
                try:
                    if disk_path.stat().st_size == len(body):
                        return False
                except OSError:
                    pass
            with self._manifest_lock:
                if self._manifest_pool is None:
                    self._manifest_pool = ThreadPoolExecutor(max_workers=128)
                if len(self._manifest_futures) >= 512:
                    done = [f for f in self._manifest_futures if f.done()]
                    self._manifest_futures = [f for f in self._manifest_futures if not f.done()]
                else:
                    done = []
                self._manifest_futures.append(
                    self._manifest_pool.submit(self._upload_manifest, key, body, disk_path)
                )
            for f in done:
                f.result()
            return True

        self._flush_manifests()

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
                if immutable and key.startswith("indexes/native-manifests/") and self.read(key) == body:
                    return False
                raise RuntimeError(
                    f"Concurrent update or reused receipt name: {key}; published receipts remain recoverable."
                ) from error
            raise
        verify_upload(result, body)
        if key.startswith("indexes/"):
            self.index_etags[key] = result["ETag"]
        return True

    def put_pdf_body(self, key_or_sha256, data):
        """Conditionally retain an uncompressed PDF body with public inline and immutable headers."""
        from congress_api.retention.body_keys import physical_body_object_key
        pdf_key = physical_body_object_key(key_or_sha256, is_pdf=True)
        return self.put(pdf_key, data, immutable=True)

    def put_file(self, key, path):
        """Conditionally retain an immutable body without loading it in memory."""
        from pathlib import Path
        from botocore.exceptions import ClientError
        if not key.startswith('bodies/'):
            raise ValueError('File upload requires a body key')
        if self.excluded_body_hashes:
            from congress_api.retention.raw_storage import enforce_body_ingest_gate
            enforce_body_ingest_gate(
                self, key, Path(path).read_bytes(), excluded_hashes=self.excluded_body_hashes
            )
        with Path(path).open('rb') as source:
            digest = hashlib.file_digest(source, 'md5')
            import os
            length = os.fstat(source.fileno()).st_size
            source.seek(0)
            extra = (
                dict(
                    ContentType='application/pdf',
                    ContentDisposition='inline',
                    CacheControl=PDF_CACHE_CONTROL,
                    IfNoneMatch='*',
                )
                if key.endswith('.pdf')
                else dict(ContentType='application/gzip', IfNoneMatch='*')
            )
            try:
                result = self.client.put_object(
                    Bucket=self.bucket, Key=key, Body=source, ContentLength=length,
                    ContentMD5=base64.b64encode(digest.digest()).decode(),
                    **extra)
            except ClientError as error:
                if error.response['Error']['Code'] in {'PreconditionFailed', '412'}:
                    return False
                raise
        if result['ETag'].strip('"') != digest.hexdigest():
            raise ValueError('Upload checksum mismatch')
        return True

    def put_pdf_file(self, key_or_sha256, path):
        """Stream an uncompressed PDF file to bodies/sha256/<xx>/<sha256>.pdf."""
        from congress_api.retention.body_keys import physical_body_object_key
        pdf_key = physical_body_object_key(key_or_sha256, is_pdf=True)
        return self.put_file(pdf_key, path)

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
        from congress_api.retention.derived_files import require_derived_key
        require_derived_key(key)
        return self._read_checked_file(key, path, expected=expected)

    def read_body_cache_file(self, path, *, expected_version):
        """Retain the exact existing reader cache for explicit native adoption."""
        if not expected_version or expected_version == 'missing':
            raise ValueError('Reader cache download requires its selected source version')
        return self._read_checked_file('indexes/processing/bodies.parquet', path, etag=expected_version, exclusive=True)

    def _read_checked_file(self, key, path, *, expected=None, etag=None, exclusive=False):
        from botocore.exceptions import ClientError
        from congress_api.retention.derived_files import copy_checked

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
            result = copy_checked(source, path, size=size, expected=expected, key=key, exclusive=exclusive)
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
                # The following transport scan verifies content without a second read.
                expected._require_custody(path)
            md5, digest, count = hashlib.md5(), hashlib.sha256(), 0
            for chunk in iter(lambda: source.read(1024**2), b''):
                md5.update(chunk)
                digest.update(chunk)
                count += len(chunk)
            actual = {'bytes': count, 'sha256': digest.hexdigest()}
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
