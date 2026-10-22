"""Guard the maintained catalog/viewer publishers at their S3 write boundary.

The caller supplies ownership, cloud, input and pin checks. SDK write retries
must be disabled. Only derived catalog and viewer objects may be written.
"""
from dataclasses import dataclass
from contextlib import contextmanager
import weakref
import hashlib
from pathlib import Path
import threading


@dataclass(frozen=True)
class VerifiedTransfer:
    bucket: str
    key: str
    bytes: int
    sha256: str
    etag: str


class CallbackPublicationGuard:
    """Adapter for a caller that deliberately runs one complete check per write."""
    def __init__(self, callback):
        self.callback = callback
    def check(self):
        return self.callback()
    shared_commit = check


def require_publication_client(client):
    if not all(callable(getattr(client, name, None)) for name in ('get_object', 'put_object')):
        raise TypeError('Publication client requires complete reads and conditional put_object')
    metadata = getattr(client, 'meta', None)
    if metadata is not None:
        retries = getattr(getattr(metadata, 'config', None), 'retries', {})
        if retries.get('total_max_attempts') != 1:
            raise ValueError('Publication SDK mutation retries must be disabled (total_max_attempts=1)')
    return client


class GuardedPublicationClient:
    def __init__(self, client, *, guard, journal, after_write, strict_conditions=False):
        require_publication_client(client)
        if callable(guard) and not all(callable(getattr(guard, name, None)) for name in ('check','shared_commit')):
            guard = CallbackPublicationGuard(guard)
        if not all(callable(getattr(guard, name, None)) for name in ('check','shared_commit')):
            raise TypeError('Publication guard requires explicit check and shared_commit methods')
        self.client = client
        self.guard = guard
        self.journal = journal
        self.after_write = after_write
        self.strict_conditions = strict_conditions
        self.lock = threading.RLock()
        self._key_locks = {}
        self._receipts = weakref.WeakValueDictionary()

    @staticmethod
    def immutable_write(kwargs):
        return (kwargs.get('IfNoneMatch') == '*' and
                kwargs['Key'].startswith(('catalog-generations/', 'catalog-history/sha256/',
                    'indexes/processing/body-results/', 'indexes/native-manifests/', 'viewer-publications/releases/',
                    'viewer-publications/catalogs/', 'viewer-publications/attempts/')))

    @contextmanager
    def write_lock(self, kwargs):
        if not self.immutable_write(kwargs):
            with self.lock:
                yield
            return
        key = (kwargs['Bucket'], kwargs['Key'])
        with self.lock:
            entry = self._key_locks.setdefault(key, [threading.RLock(), 0])
            entry[1] += 1  # Include waiters, so cleanup cannot split same-key exclusion.
        try:
            with entry[0]:
                yield
        finally:
            with self.lock:
                entry[1] -= 1
                if entry[1] == 0:
                    del self._key_locks[key]

    def check_guard(self, kwargs):
        method = 'check' if self.immutable_write(kwargs) else 'shared_commit'
        return getattr(self.guard, method)()

    def verified_result(self, result, *, bucket, key, size, sha256, etag):
        receipt = VerifiedTransfer(bucket, key, size, sha256, etag)
        with self.lock:
            self._receipts[id(receipt)] = receipt
        return dict(result, _verified_transfer=receipt)

    def confirm_transfer(self, receipt, *, bucket, key, size, sha256):
        # A result applies only to this client, exact request and current version.
        with self.lock:
            issued = self._receipts.pop(id(receipt), None)
        if issued is not receipt or receipt is None:
            return False
        if (receipt.bucket, receipt.key, receipt.bytes, receipt.sha256) != (bucket, key, size, sha256):
            return False
        response = self.client.head_object(Bucket=bucket, Key=key)
        return response['ETag'] == receipt.etag and response.get('ContentLength') == size

    def get_object(self, **kwargs):
        return self.client.get_object(**kwargs)

    def head_object(self, **kwargs):
        return self.client.head_object(**kwargs)

    @property
    def meta(self):
        return self.client.meta

    def get_paginator(self, name):
        if name != 'list_objects_v2':
            raise ValueError('Unsupported publication paginator')
        return self.client.get_paginator(name)

    def download_file(self, bucket, key, filename):
        return self.client.download_file(bucket, key, filename)

    def put_object(self, **kwargs):
        local_validation = kwargs.pop('_local_validation', None)
        key = kwargs['Key']
        native_metadata = key.startswith('indexes/native-manifests/')
        if not (key.startswith(('catalog-generations/', 'catalog-history/sha256/',
                                'indexes/processing/', 'viewer-publications/')) or native_metadata
                or key == 'indexes/catalog.json'):
            raise ValueError('Publication cannot write raw/source object: ' + key)
        if native_metadata and (kwargs.get('IfNoneMatch') != '*' or kwargs.get('IfMatch')):
            raise ValueError('Native catalog metadata is immutable')
        if not kwargs.get('IfMatch') and kwargs.get('IfNoneMatch') != '*':
            raise ValueError('Publication write requires an explicit condition')
        body = kwargs['Body']
        if isinstance(body, bytes):
            size, digest = len(body), hashlib.sha256(body).hexdigest()
        else:
            start = body.tell()
            if local_validation is not None:
                from congress_api.retention.derived_files import VerifiedFile
                if not isinstance(local_validation, VerifiedFile) or start != 0:
                    raise ValueError('Invalid local publication file proof')
                local_validation.require(body.name)
                size, digest = local_validation['bytes'], local_validation['sha256']
            else:
                digestor = hashlib.sha256()
                size = 0
                while chunk := body.read(1024 * 1024):
                    size += len(chunk)
                    digestor.update(chunk)
                body.seek(start)
                digest = digestor.hexdigest()
        if native_metadata:
            parts = key.split('/')
            if (len(parts) != 4 or not parts[2]
                    or any(char not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for char in parts[2])
                    or parts[3] != digest + '.json'):
                raise ValueError('Native catalog metadata identity differs from its key')

        def verify():
            response = self.client.get_object(Bucket=kwargs['Bucket'], Key=key)
            actual, count = hashlib.sha256(), 0
            with response['Body'] as stream:
                while chunk := stream.read(1024 * 1024):
                    count += len(chunk)
                    if count > size:
                        raise ValueError('Publication readback exceeds expected size')
                    actual.update(chunk)
            if count != size or count != response['ContentLength'] or actual.hexdigest() != digest:
                raise ValueError('Publication readback differs: ' + key)
            return response['ETag']

        with self.write_lock(kwargs):
            self.check_guard(kwargs)
            self.journal('publication_write_intent', dict(key=key, bytes=size,
                sha256=digest, expected_etag=kwargs.get('IfMatch'),
                if_none_match=kwargs.get('IfNoneMatch')))
            uncertain = False
            request_error = None
            try:
                result = self.client.put_object(**kwargs)
            except Exception as error:
                request_error = error
                if self.strict_conditions:
                    from botocore.exceptions import ClientError
                    if isinstance(error, ClientError) and error.response['Error']['Code'] in {'PreconditionFailed', '412'}:
                        raise
                # Verify the possible commit once; never resend this request.
                uncertain, result = True, {}
            try:
                version = verify()
            except Exception as reconciliation_error:
                # Preserve a definite condition refusal for maintained callers
                # that deliberately keep an existing immutable catalog locator.
                from botocore.exceptions import ClientError
                if (isinstance(request_error, ClientError)
                        and request_error.response['Error']['Code'] in {'PreconditionFailed', '412'}):
                    self.journal('publication_write_refused', dict(key=key, reason='condition_failed'))
                    raise request_error
                if request_error is not None:
                    failure = RuntimeError('Publication write and reconciliation failed for ' + key
                        + '; upload outcome is uncertain; no request was resent')
                    failure.add_note('Original request failure type: ' + type(request_error).__name__)
                    failure.add_note('Reconciliation failure type: ' + type(reconciliation_error).__name__)
                    # Keep exact exceptions available to operators without formatting
                    # transport messages that might contain signed URLs or credentials.
                    failure.request_error = request_error
                    failure.reconciliation_error = reconciliation_error
                    raise failure from request_error
                raise
            if uncertain:
                result = {'ETag': version}
                self.journal('publication_acknowledgment_reconciled', dict(key=key))
            self.after_write(key, version)
            self.journal('publication_write_verified', dict(key=key, etag=version,
                                                           sha256=digest, bytes=size))
            return self.verified_result(result, bucket=kwargs['Bucket'], key=key,
                                        size=size, sha256=digest, etag=version)

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        return self._upload_file(filename, bucket, key, ExtraArgs)

    def upload_verified_file(self, filename, bucket, key, ExtraArgs=None, *, validation):
        return self._upload_file(filename, bucket, key, ExtraArgs, validation=validation)

    def _upload_file(self, filename, bucket, key, ExtraArgs=None, *, validation=None):
        # Replace managed multipart writes with one conditional, streamed PUT.
        # Return the exact verified result so callers can avoid a second full GET.
        path = Path(filename)
        if path.stat().st_size >= 5 * 1024**3:
            raise ValueError('Publication file exceeds single-PUT limit')
        options = dict(ExtraArgs or {})
        if validation is not None:
            validation.require(path)
            options['_local_validation'] = validation
        with path.open('rb') as stream:
            result = self.put_object(Bucket=bucket, Key=key, Body=stream,
                            ContentLength=path.stat().st_size, IfNoneMatch='*', **options)
        return result.get('_verified_transfer')


class ContinuedPublicationClient(GuardedPublicationClient):
    """One original-condition replay boundary for cloud and local acceptance."""
    def __init__(self, client, *, continuation, **kwargs):
        self.continuation = continuation
        super().__init__(client, **kwargs)

    def put_object(self, **kwargs):
        with self.write_lock(kwargs):
            saved = self.continuation.value['writes'].get(kwargs['Key'])
            if saved:
                if (saved.get('expected_etag'), saved.get('if_none_match')) != (kwargs.get('IfMatch'), kwargs.get('IfNoneMatch')):
                    raise ValueError('Continued publication write conditions differ')
                if saved['verified']:
                    self.check_guard(kwargs)
                reused = self.continuation.replay(self.client, kwargs['Bucket'], kwargs['Key'], kwargs['Body'],
                                                  validation=kwargs.get('_local_validation'))
                if reused is not None:
                    return self.verified_result(reused, bucket=kwargs['Bucket'], key=kwargs['Key'],
                        size=saved['bytes'], sha256=saved['sha256'], etag=saved['etag'])
            return super().put_object(**kwargs)


def publish_manifest_pointer(
    client,
    *,
    bucket,
    pointer,
    key='viewer-publications/manifest.json',
    expected_etag=None,
    content_type='application/json',
    cache_control='no-store',
):
    """Commit the viewer manifest pointer via a single conditional PUT (Ruling A.2).

    Uses ``IfMatch=expected_etag`` when advancing an existing pointer or
    ``IfNoneMatch='*'`` when creating the initial pointer, without performing
    2x ``get_object`` readback or WAL journaling.
    """
    import json

    if isinstance(pointer, (bytes, bytearray)):
        raw = bytes(pointer)
    elif isinstance(pointer, dict):
        raw = json.dumps(pointer, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    else:
        raise TypeError('Manifest pointer payload must be a dict or bytes')

    if expected_etag is not None and (not isinstance(expected_etag, str) or not expected_etag.strip()):
        raise ValueError('expected_etag must be a non-empty ETag string or None')

    condition = {'IfMatch': expected_etag} if expected_etag is not None else {'IfNoneMatch': '*'}
    size = len(raw)
    digest = hashlib.sha256(raw).hexdigest()
    response = client.put_object(
        Bucket=bucket,
        Key=key,
        Body=raw,
        ContentLength=size,
        ContentType=content_type,
        CacheControl=cache_control,
        **condition,
    )
    etag = (response or {}).get('ETag') or ''
    return VerifiedTransfer(bucket=bucket, key=key, bytes=size, sha256=digest, etag=etag)


class ConditionalManifestPublisher:
    """Thin conditional-PUT publisher for content-addressed viewer assets and manifest pointers (Ruling A.2)."""

    def __init__(self, client, *, bucket):
        if not callable(getattr(client, 'put_object', None)):
            raise TypeError('ConditionalManifestPublisher requires a client with put_object')
        self.client = client
        self.bucket = bucket

    def put_immutable_asset(self, key, body, *, content_type='application/octet-stream', validation=None):
        if not key.startswith('viewer-publications/releases/'):
            raise ValueError(f'Immutable viewer asset key must live under viewer-publications/releases/: {key}')
        if isinstance(body, Path) or (isinstance(body, str) and Path(body).exists()):
            path = Path(body)
            if path.stat().st_size >= 5 * 1024**3:
                raise ValueError('Immutable viewer asset exceeds single-PUT limit')
            if validation is not None:
                validation.require(path)
                size, digest = int(validation['bytes']), str(validation['sha256'])
            else:
                size = path.stat().st_size
                with path.open('rb') as digest_stream:
                    digest = hashlib.file_digest(digest_stream, 'sha256').hexdigest()
            try:
                with path.open('rb') as stream:
                    response = self.client.put_object(
                        Bucket=self.bucket,
                        Key=key,
                        Body=stream,
                        ContentLength=size,
                        ContentType=content_type,
                        IfNoneMatch='*',
                    )
                etag = (response or {}).get('ETag') or ''
            except Exception as error:
                code = getattr(error, 'response', {}).get('Error', {}).get('Code')
                if code not in {'PreconditionFailed', '412'}:
                    raise
                etag = 'existing-immutable'
            return VerifiedTransfer(bucket=self.bucket, key=key, bytes=size, sha256=digest, etag=etag)

        if hasattr(body, 'read') and hasattr(body, 'seek') and hasattr(body, 'tell'):
            start = body.tell()
            digestor = hashlib.sha256()
            size = 0
            while chunk := body.read(1024 * 1024):
                size += len(chunk)
                digestor.update(chunk)
            body.seek(start)
            digest = digestor.hexdigest()
            payload = body
        else:
            raw = bytes(body) if isinstance(body, (bytes, bytearray)) else body.read()
            size = len(raw)
            digest = hashlib.sha256(raw).hexdigest()
            payload = raw
        try:
            response = self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=payload,
                ContentLength=size,
                ContentType=content_type,
                IfNoneMatch='*',
            )
            etag = (response or {}).get('ETag') or ''
        except Exception as error:
            code = getattr(error, 'response', {}).get('Error', {}).get('Code')
            if code not in {'PreconditionFailed', '412'}:
                raise
            etag = 'existing-immutable'
        return VerifiedTransfer(bucket=self.bucket, key=key, bytes=size, sha256=digest, etag=etag)

    def publish_pointer(self, pointer, *, key='viewer-publications/manifest.json', expected_etag=None):
        return publish_manifest_pointer(
            self.client,
            bucket=self.bucket,
            pointer=pointer,
            key=key,
            expected_etag=expected_etag,
        )

