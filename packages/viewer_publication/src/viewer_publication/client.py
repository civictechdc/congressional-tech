"""Guard the maintained catalog/viewer publishers at their S3 write boundary.

The caller supplies ownership, cloud, input and pin checks. SDK write retries
must be disabled. Only derived catalog and viewer objects may be written.
"""
from dataclasses import dataclass
import hashlib
from pathlib import Path


@dataclass(frozen=True)
class VerifiedTransfer:
    """Receipt for an acknowledged PUT or a reconciled uncertain request."""
    bucket: str
    key: str
    bytes: int
    sha256: str
    etag: str


class _HashingUpload:
    """Hash the final sequential pass consumed by a seekable PUT body."""
    def __init__(self, stream):
        self.stream = stream
        self.start = stream.tell()
        self._reset()

    def _reset(self):
        self.count, self.digest, self.sequential = 0, hashlib.sha256(), True

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def _record(self, chunk):
        self.count += len(chunk)
        self.digest.update(chunk)
        return chunk

    def read(self, size=-1):
        return self._record(self.stream.read(size))

    def readinto(self, buffer):
        chunk = self.read(len(buffer))
        buffer[:len(chunk)] = chunk
        return len(chunk)

    def readline(self, size=-1):
        return self._record(self.stream.readline(size))

    def __iter__(self):
        while chunk := self.readline():
            yield chunk

    def seek(self, offset, whence=0):
        position = self.stream.seek(offset, whence)
        if position == self.start:
            self._reset()  # SDK checksum/signing probes may rewind before sending.
        elif position != self.start + self.count:
            self.sequential = False
        return position

    def require(self, size, digest):
        if (not self.sequential or self.count != size
                or self.stream.tell() != self.start + self.count
                or self.digest.hexdigest() != digest):
            raise ValueError('Publication upload bytes differ from expected identity')


def require_publication_client(client):
    if not all(callable(getattr(client, name, None)) for name in ('get_object', 'put_object')):
        raise TypeError('Publication client requires complete reads and conditional put_object')
    metadata = getattr(client, 'meta', None)
    if metadata is not None:
        retries = getattr(getattr(metadata, 'config', None), 'retries', {})
        if retries.get('total_max_attempts') != 1:
            raise ValueError('Publication SDK mutation retries must be disabled (total_max_attempts=1)')
    return client


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
                from congress_api.retention.derived_files import VerifiedFile
                if not isinstance(validation, VerifiedFile):
                    raise ValueError('Invalid local publication file proof')
                validation._require_custody(path)
                size, digest = int(validation['bytes']), str(validation['sha256'])
            else:
                size = path.stat().st_size
                with path.open('rb') as digest_stream:
                    digest = hashlib.file_digest(digest_stream, 'sha256').hexdigest()
            try:
                with path.open('rb') as stream:
                    consumed = _HashingUpload(stream)
                    response = self.client.put_object(
                        Bucket=self.bucket,
                        Key=key,
                        Body=consumed,
                        ContentLength=size,
                        ContentType=content_type,
                        IfNoneMatch='*',
                    )
                    consumed.require(size, digest)
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
            payload = _HashingUpload(body)
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
            if isinstance(payload, _HashingUpload):
                payload.require(size, digest)
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

