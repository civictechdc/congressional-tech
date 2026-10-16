"""Guard the maintained catalog/viewer publishers at their S3 write boundary.

The caller supplies ownership, cloud, input and pin checks. SDK write retries
must be disabled. Only derived catalog and viewer objects may be written.
"""
from dataclasses import dataclass
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


class GuardedPublicationClient:
    def __init__(self, client, *, guard, journal, after_write):
        self.client = client
        self.guard = guard
        self.journal = journal
        self.after_write = after_write
        self.lock = threading.RLock()
        self._key_locks = {}
        self._receipts = {}

    @staticmethod
    def immutable_write(kwargs):
        return (kwargs.get('IfNoneMatch') == '*' and
                kwargs['Key'].startswith(('catalog-generations/', 'catalog-history/sha256/',
                    'indexes/processing/body-results/', 'viewer-publications/releases/',
                    'viewer-publications/catalogs/')))

    def write_lock(self, kwargs):
        if not self.immutable_write(kwargs):
            return self.lock
        with self.lock:
            return self._key_locks.setdefault((kwargs['Bucket'], kwargs['Key']), threading.RLock())

    def check_guard(self, kwargs):
        method = 'check' if self.immutable_write(kwargs) else 'shared_commit'
        return getattr(self.guard, method, self.guard)()

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
        key = kwargs['Key']
        if not (key.startswith(('catalog-generations/', 'catalog-history/sha256/',
                                'indexes/processing/', 'viewer-publications/'))
                or key == 'indexes/catalog.json'):
            raise ValueError('Publication cannot write raw/source object: ' + key)
        if not kwargs.get('IfMatch') and kwargs.get('IfNoneMatch') != '*':
            raise ValueError('Publication write requires an explicit condition')
        body = kwargs['Body']
        if isinstance(body, bytes):
            size, digest = len(body), hashlib.sha256(body).hexdigest()
        else:
            start = body.tell()
            digestor = hashlib.sha256()
            size = 0
            while chunk := body.read(1024 * 1024):
                size += len(chunk)
                digestor.update(chunk)
            body.seek(start)
            digest = digestor.hexdigest()

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
            try:
                result = self.client.put_object(**kwargs)
            except Exception:
                # Verify the possible commit once; never resend this request.
                uncertain, result = True, {}
            version = verify()
            if uncertain:
                result = {'ETag': version}
                self.journal('publication_acknowledgment_reconciled', dict(key=key))
            self.after_write(key, version)
            self.journal('publication_write_verified', dict(key=key, etag=version,
                                                           sha256=digest, bytes=size))
            return self.verified_result(result, bucket=kwargs['Bucket'], key=key,
                                        size=size, sha256=digest, etag=version)

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        # Replace managed multipart writes with one conditional, streamed PUT.
        # Return the exact verified result so callers can avoid a second full GET.
        path = Path(filename)
        if path.stat().st_size >= 5 * 1024**3:
            raise ValueError('Publication file exceeds single-PUT limit')
        options = dict(ExtraArgs or {})
        with path.open('rb') as stream:
            result = self.put_object(Bucket=bucket, Key=key, Body=stream,
                            ContentLength=path.stat().st_size, IfNoneMatch='*', **options)
        return result.get('_verified_transfer')
