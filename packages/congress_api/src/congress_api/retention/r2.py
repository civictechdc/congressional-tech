"""Small object-store implementation for the raw mirror; no acquisition policy."""

import base64
from concurrent.futures import ThreadPoolExecutor,CancelledError
import hashlib
import asyncio
import json
import logging
import os
from pathlib import Path
import random
import re
import threading
import time
from queue import Queue,Full
from contextlib import asynccontextmanager, closing
from datetime import timezone
from email.utils import parsedate_to_datetime
from weakref import WeakValueDictionary
from congress_api.retention.concurrency import completed_map


LOGGER = logging.getLogger(__name__)
_read_locks = WeakValueDictionary()
_read_locks_guard = threading.Lock()


class R2GetTransportExhausted(RuntimeError):
    """An explicitly bounded GET failed; never turn it into a pending body read."""


class _ReadyPrefetch:
    """Bound ready keys; cancellation releases producer callbacks before joining."""
    _END=object()

    def __init__(self,store,keys,*,max_workers,expected,timings,max_ready):
        if type(max_ready) is not int or max_ready<=0:
            raise ValueError('Ready prefetch requires a positive queue bound')
        if expected is None:raise ValueError('Ready prefetch requires exact body pins')
        self.store,self.keys=store,list(keys)
        if any(store._immutable_cache_path(key) is None for key in self.keys):
            raise ValueError('Ready prefetch requires cacheable immutable keys')
        self.options=dict(max_workers=max_workers,expected=expected,timings=timings)
        self.queue=Queue(maxsize=max_ready);self.stop=threading.Event()
        self.executor=self.future=None;self.error=None;self.exhausted=False

    def _notify(self,key):
        while not self.stop.is_set():
            try:self.queue.put(key,timeout=.1);return
            except Full:pass
        raise CancelledError('Ready prefetch cancelled')

    def _run(self):
        try:self.store.prefetch_immutable(self.keys,on_ready=self._notify,**self.options)
        except BaseException as error:self.error=error
        finally:
            if not self.stop.is_set():
                try:self._notify(self._END)
                except CancelledError:pass

    def __enter__(self):
        if self.future is not None:raise RuntimeError('Ready prefetch is single use')
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='prefetch')
        try:self.future=self.executor.submit(self._run)
        except BaseException:
            self.executor.shutdown(wait=True,cancel_futures=True);self.executor=None
            raise
        return self

    def get(self,*,block):
        if self.future is None:raise RuntimeError('Ready prefetch requires an open context')
        if self.exhausted:raise StopIteration
        if self.stop.is_set():raise CancelledError('Ready prefetch cancelled')
        value=self.queue.get(block=block)
        if value is self._END:
            self.exhausted=True;self.future.result()
            if self.error is not None:raise self.error
            raise StopIteration
        return value

    def cancel(self):
        self.stop.set()
        try:self.queue.put_nowait(self._END)
        except Full:pass

    def __exit__(self,kind,*error):
        self.cancel()
        if self.executor is not None:
            self.executor.shutdown(wait=True,cancel_futures=True);self.executor=None
        if kind is None and self.error is not None and not isinstance(self.error,CancelledError):
            raise self.error


def _raw_pin(key,expected):
    from congress_api.retention.body_store import validate_key
    from congress_shared.storage import single_put_md5
    validate_key(key)
    if (not key.startswith('bodies/') or not isinstance(expected,dict) or set(expected) not in ({'md5','bytes'},{'etag','md5','bytes'})
            or type(expected['bytes']) is not int or expected['bytes']<0):
        raise ValueError('Pinned raw read requires a body key, conditional version and total bytes')
    md5=single_put_md5(expected['md5']) if expected.get('md5') is not None else None
    etag=expected.get('etag',('"'+md5+'"') if md5 is not None else None)
    if not isinstance(etag,str) or not etag or any(ord(c)<32 or ord(c)==127 for c in etag):
        raise ValueError('Pinned raw read requires a nonempty conditional ETag or stored MD5')
    return dict(etag=etag,md5=md5,bytes=expected['bytes'])


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


def _read_stream(client, key, request, consume, *, bucket):
    """Retry body consumption only; callers own requests and content checks."""
    from botocore.exceptions import IncompleteReadError, ReadTimeoutError, ResponseStreamingError

    # Hold one process-wide lock through response consumption, close and retry
    # backoff, across store instances and read methods. Weak values retain only
    # active/waiting keys, O(concurrent readers), rather than a corpus-size map.
    with _read_locks_guard:
        lock = _read_locks.get((bucket, key))
        if lock is None:
            lock = threading.Lock()
            _read_locks[bucket, key] = lock
    with lock:
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


def _configure_retries(client, *, read_throttle_attempts=None, asynchronous=False):
    """Use one SDK replay loop for bounded throttling and GET transport failures."""
    from botocore.exceptions import ConnectionClosedError,EndpointConnectionError,HTTPClientError,ReadTimeoutError
    if read_throttle_attempts is not None and (
            type(read_throttle_attempts) is not int or not 1 <= read_throttle_attempts <= 5):
        raise ValueError('Read throttle attempts must be between one and five')
    # Do not invent a retry budget for clients using an implicit SDK default.
    sdk_maximum = client.meta.config.retries.get('total_max_attempts')

    def transport(error):
        return isinstance(error,(ConnectionClosedError,ReadTimeoutError,EndpointConnectionError,ConnectionResetError)) or (
            isinstance(error,HTTPClientError) and isinstance(error.kwargs.get('error'),ConnectionResetError))

    def retry(*, response, attempts, operation, request_dict, caught_exception=None, **_):
        maximum = (read_throttle_attempts if operation.name == 'GetObject' and read_throttle_attempts is not None
                   else sdk_maximum)
        if response is None:
            if operation.name!='GetObject' or maximum is None or not transport(caught_exception):
                return None
            delay=_throttle_delay({},attempts,time.time()) if attempts<maximum else False
            LOGGER.warning(json.dumps(dict(event='r2_request_error',operation=operation.name,
                key=request_dict['context'].get('input_params',{}).get('Key'),
                error_type=type(caught_exception).__name__,http_status=None,attempt=attempts,
                max_attempts=maximum,retry_delay_seconds=delay),sort_keys=True))
            if delay is False and read_throttle_attempts is not None:
                key=request_dict['context'].get('input_params',{}).get('Key')
                raise R2GetTransportExhausted(f'GetObject transport failed after {attempts} attempts: {key}') from caught_exception
            return delay
        if response[0].status_code < 400:
            return None
        http, parsed = response
        status = http.status_code
        delay = None
        if (status == 429 or status == 503 and parsed.get('Error', {}).get('Code') in
                {'ServiceUnavailable', 'SlowDown'}) and maximum is not None:
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

    if client.meta.config.retries.get('mode')=='legacy' and sdk_maximum is not None:
        # Legacy dispatch raises at its own bound, or for a raw reset it does
        # not recognize, even when our earlier hook requests another replay.
        # Delegate its installed SDK policy unchanged for every other decision.
        # Only this owner's GET transport decision bypasses that second vote;
        # no request/replay loop is added here.
        from botocore.loaders import Loader
        if asynchronous:
            from aiobotocore.retryhandler import create_retry_handler
        else:
            from botocore.retryhandler import create_retry_handler
        from botocore.translate import build_retry_config
        model=Loader(extra_search_paths=[Loader.BUILTIN_DATA_PATH],
            include_default_search_paths=False).load_data('_retry')
        policy=build_retry_config('s3',model['retry'],model['definitions'],
            dict(max_attempts=sdk_maximum-1))
        sdk_retry=create_retry_handler(policy,'s3')
        def legacy_retry(*,operation,caught_exception=None,**kwargs):
            if operation.name=='GetObject' and transport(caught_exception):return None
            return sdk_retry(operation=operation,caught_exception=caught_exception,**kwargs)
        client.meta.events.unregister('needs-retry.s3',unique_id='retry-config-s3')
        client.meta.events.register('needs-retry.s3',legacy_retry,unique_id='retry-config-s3')

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


class AsyncBodies:
    """Async I/O for immutable bodies; index state remains with the collector."""
    def __init__(self, client, bucket):
        self.client, self.bucket = client, bucket
        _configure_retries(client,asynchronous=True)

    async def put(self, key, data):
        from io import BytesIO
        from congress_api.retention.body_store import AsyncR2Adapter, create_stored_async
        if not key.startswith('bodies/'):
            raise ValueError('Async body upload requires a body key')
        media = ('application/pdf' if key.endswith('.pdf') else
                 'application/gzip' if key.endswith('.gz') else 'application/octet-stream')
        result = await create_stored_async(AsyncR2Adapter(self.client, self.bucket), key, BytesIO(data), media)
        return result.outcome == 'stored'

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
    def __init__(self, client, bucket, *, async_client=None, excluded_body_hashes=None, store_uncompressed_pdfs=False, cache_dir=None, read_throttle_attempts=None):
        self.client, self.bucket = client, bucket
        _configure_retries(client, read_throttle_attempts=read_throttle_attempts)
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

    def _immutable_cache_path(self, key):
        if (
            self._immutable_cache_dir is None
            or not isinstance(key, str)
            or key.endswith('.pdf')
            or not key.startswith(('receipts/', 'bodies/sha256/'))
        ):
            return None
        return self._immutable_cache_dir / key

    def prefetch_immutable_ready(self,keys,*,max_workers=64,expected=None,timings=None,max_ready=128):
        return _ReadyPrefetch(self,keys,max_workers=max_workers,expected=expected,timings=timings,max_ready=max_ready)

    def prefetch_immutable(self, keys, *, max_workers=64,expected=None,timings=None,on_ready=None):
        if type(max_workers) is not int or max_workers<=0:raise ValueError('Prefetch worker bound must be positive')
        if on_ready is not None and (not callable(on_ready) or expected is None):
            raise ValueError('Ready notification requires a callable and exact body pins')
        if timings is not None and (not isinstance(timings,list) or expected is None):
            raise ValueError('Read timings require a list and exact body pins')
        if self._immutable_cache_dir is None:
            if expected is not None:raise ValueError('Pinned prefetch requires a local cache')
            return
        keys=list(dict.fromkeys(keys))
        pins=None
        if expected is not None:
            if not isinstance(expected,dict) or set(expected)!=set(keys):
                raise ValueError('Pinned prefetch needs exactly every selected body pin')
            pins={key:_raw_pin(key,expected[key]) for key in keys}
        missing = []
        for k in keys:
            cache_path = self._immutable_cache_path(k)
            if cache_path is not None and (pins is not None or not cache_path.is_file()):
                missing.append(k)
        if not missing:
            return
        def fetch(key):
            if pins is None:self.read(key)
            elif timings is None:self.read(key,expected=pins[key])
            else:
                timing={}
                try:self.read(key,expected=pins[key],timing=timing)
                finally:timings.append(dict(key=key,**timing))
            if on_ready is not None:on_ready(key)
            # Cache the bytes, not a second batch-sized collection of results.
        with ThreadPoolExecutor(max_workers=min(max_workers, len(missing))) as pool:
            for _ in completed_map(pool,fetch,missing,max_pending=4*min(max_workers,len(missing))):pass

    def read(self, key, *, start=None,length=None,expected=None,metadata=None,timing=None):
        if timing is not None and (not isinstance(timing,dict) or expected is None):
            raise ValueError('Read timing requires a mapping and an exact body pin')
        started=time.monotonic() if timing is not None else None
        if timing is not None:timing.update(requests=0,bytes=0,cache_hit=False,error_type=None,
            sdk_retries=0,sdk_retry_metadata_complete=True)
        try:
            value=self._read(key,start=start,length=length,expected=expected,metadata=metadata,timing=timing)
            if timing is not None:timing['bytes']=len(value)
            return value
        except BaseException as error:
            if timing is not None:timing['error_type']=type(error).__name__
            raise
        finally:
            if timing is not None:timing['seconds']=time.monotonic()-started

    def _read(self, key, *, start=None,length=None,expected=None,metadata=None,timing=None):
        from botocore.exceptions import ClientError, BotoCoreError
        from congress_shared.storage import single_put_md5
        ranged=start is not None or length is not None
        pin=_raw_pin(key,expected) if expected is not None else None
        if metadata is not None and (not isinstance(metadata,dict) or pin is None):
            raise ValueError('Response metadata requires a pinned raw read and an output mapping')
        if ranged:
            if (pin is None or type(start) is not int or type(length) is not int or start<0 or length<0
                    or start+length>pin['bytes']):
                raise ValueError('Raw range requires an exact captured pin and valid bounds')
            if length==0:return b''

        immutable_path = None if ranged else self._immutable_cache_path(key)
        if immutable_path is not None and immutable_path.is_file() and (pin is None or pin['md5'] is not None):
            try:
                data=immutable_path.read_bytes()
                if pin is not None and (len(data)!=pin['bytes'] or
                        pin['md5'] is not None and hashlib.md5(data).hexdigest()!=pin['md5']):
                    raise ValueError('Pinned immutable cache changed')
                if timing is not None:timing['cache_hit']=True
                return data
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

        def retries(response):
            if timing is not None:
                count=response.get('ResponseMetadata',{}).get('RetryAttempts')
                if type(count) is int and count>=0:timing['sdk_retries']+=count
                else:timing['sdk_retry_metadata_complete']=False

        def request():
            try:
                if timing is not None:timing['requests']+=1
                options={} if pin is None else dict(IfMatch=pin['etag'])
                if ranged:options['Range']=f'bytes={start}-{start+length-1}'
                return self.client.get_object(Bucket=self.bucket, Key=key,**options)
            except ClientError as error:
                retries(error.response)
                if error.response["Error"]["Code"] in {"NoSuchKey", "404"}:
                    if key.startswith("indexes/"):
                        self.index_etags[key] = None
                    if pin is None:return None
                raise
            except (BotoCoreError,ConnectionResetError,R2GetTransportExhausted):
                # A transport error may follow SDK replays but carries no
                # response RetryAttempts. Preserve the failure and report the gap.
                if timing is not None:timing['sdk_retry_metadata_complete']=False
                raise

        def consume(response, stream):
            retries(response)
            if pin is not None:
                wanted=length if ranged else pin['bytes']
                # LIST versions are opaque. A canonical captured-MD5 condition
                # retains shared quote normalization through prefetch as well.
                version_matches=(single_put_md5(response.get('ETag'))==pin['md5']
                    if pin['md5'] is not None and pin['etag']=='"'+pin['md5']+'"' else
                    response.get('ETag')==pin['etag'])
                if (type(response.get('ContentLength')) is not int or response['ContentLength']!=wanted
                        or not version_matches):
                    raise ValueError('Pinned raw response changed')
                if ranged:
                    match=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',response.get('ContentRange',''))
                    if (match is None or tuple(map(int,match.groups()))!=(start,start+length-1,pin['bytes'])
                            or response.get('ResponseMetadata',{}).get('HTTPStatusCode')!=206):
                        raise ValueError('Pinned raw range or total size changed')
                if metadata is not None:
                    metadata.update(content_encoding=response.get('ContentEncoding'),bytes=pin['bytes'],
                                    etag=response['ETag'])
                data=stream.read(wanted+1)
                if len(data)!=wanted:raise ValueError('Incomplete pinned raw response')
                if not ranged and pin['md5'] is not None and hashlib.md5(data).hexdigest()!=pin['md5']:
                    raise ValueError('Pinned raw MD5 mismatch')
            elif key == 'indexes/catalog.json':
                if response['ContentLength'] > 1024**2:
                    raise ValueError('Catalog selector exceeds 1 MiB read budget')
                data = stream.read(1024**2 + 1)
                if len(data) > 1024**2:
                    raise ValueError('Catalog selector exceeds 1 MiB read budget')
            else:
                data = stream.read()
            return response, data

        result = _read_stream(self.client, key, request, consume, bucket=self.bucket)
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
            if pin is not None and not immutable_path.is_file():raise OSError('Pinned raw cache write failed')
        return data

    def put_pdf_body(self, key_or_sha256, data):
        """Conditionally retain an uncompressed PDF body with public inline and immutable headers."""
        from io import BytesIO
        from congress_api.retention.body_keys import physical_body_object_key
        from congress_api.retention.body_store import R2Adapter, create_stored
        pdf_key = physical_body_object_key(key_or_sha256, is_pdf=True)
        return create_stored(R2Adapter(self.client, self.bucket), pdf_key, BytesIO(data), 'application/pdf').outcome == 'stored'

    def put_file(self, key, path, *, content_type='application/gzip', content_encoding=None, md5=None):
        """Conditionally retain an immutable body without loading it in memory.

        New-shape bodies (no key suffix) name their original media type and a
        gzip ``content_encoding``; ``md5`` skips re-hashing a file the caller
        just wrote. R2 still checks the sent ``Content-MD5`` against the bytes.
        """
        from congress_api.retention.body_store import R2Adapter, create_stored, validate_key
        validate_key(key)
        if not key.startswith('bodies/'):
            raise ValueError('File upload requires a body key')
        with Path(path).open('rb') as source:
            return create_stored(R2Adapter(self.client, self.bucket), key, source,
                'application/pdf' if key.endswith('.pdf') else content_type,
                encoding=content_encoding).outcome == 'stored'

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

        return _read_stream(self.client, key, request, consume, bucket=self.bucket)

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

        return _read_stream(self.client, key, request, consume, bucket=self.bucket)

    def keys(self, prefix):
        for page in self.client.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=prefix
        ):
            for item in page.get("Contents", []):
                yield item["Key"]
