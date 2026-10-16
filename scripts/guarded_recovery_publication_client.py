"""Guard the maintained catalog/viewer publishers at their S3 write boundary.

The caller supplies ownership, cloud, input and pin checks. SDK write retries
must be disabled. Only derived catalog and viewer objects may be written.
"""
import hashlib
from pathlib import Path
import threading


class GuardedPublicationClient:
    def __init__(self, client, *, guard, journal, after_write):
        self.client = client
        self.guard = guard
        self.journal = journal
        self.after_write = after_write
        self.lock = threading.RLock()

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

        with self.lock:
            self.guard()
            self.journal('publication_write_intent', dict(key=key, bytes=size,
                sha256=digest, expected_etag=kwargs.get('IfMatch'),
                if_none_match=kwargs.get('IfNoneMatch')))
            try:
                result = self.client.put_object(**kwargs)
            except Exception:
                # The request may have committed. Never repeat it automatically.
                version = verify()
                result = {'ETag': version}
                self.journal('publication_acknowledgment_reconciled', dict(key=key))
            version = verify()
            self.after_write(key, version)
            self.journal('publication_write_verified', dict(key=key, etag=version,
                                                           sha256=digest, bytes=size))
            return result

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        # Replace managed multipart writes with one conditional, streamed PUT.
        # The maintained publisher independently downloads and hashes it too.
        path = Path(filename)
        if path.stat().st_size >= 5 * 1024**3:
            raise ValueError('Publication file exceeds single-PUT limit')
        options = dict(ExtraArgs or {})
        with path.open('rb') as stream:
            self.put_object(Bucket=bucket, Key=key, Body=stream,
                            ContentLength=path.stat().st_size, IfNoneMatch='*', **options)
