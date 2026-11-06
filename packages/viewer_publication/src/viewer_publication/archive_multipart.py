"""Bounded create-only release uploads through the existing publication SDK.

The manifest keeps whole-file SHA-256/MD5. A separate, custody-bound transport
plan records R2's multipart ETag. No SDK mutation is automatically retried.
"""
from base64 import b64encode
from hashlib import md5, sha256
import os
from pathlib import Path
import re

from congress_shared.custody import custody_identity

THRESHOLD = 64 << 20
PART_BYTES = 8 << 20
MAX_PARTS = 10_000


def _identity(stat):
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns,
            stat.st_ctime_ns, stat.st_nlink)


def _require_source(source, stream, custody):
    if custody_identity(source) != custody or _identity(os.fstat(stream.fileno())) != custody:
        raise ValueError('Local publication asset changed during multipart transfer')


def _etag(parts):
    return md5(b''.join(bytes.fromhex(value) for value in parts)).hexdigest() + '-' + str(len(parts))


def _observed_etag(value):
    if isinstance(value, str) and value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return value


def require_plan(plan, size):
    count = (size + PART_BYTES - 1) // PART_BYTES
    if (not isinstance(plan, dict) or set(plan) != {'kind', 'part_bytes', 'part_md5', 'etag'}
            or plan['kind'] != 'multipart' or plan['part_bytes'] != PART_BYTES
            or not 1 <= count <= MAX_PARTS or not isinstance(plan['part_md5'], list)
            or len(plan['part_md5']) != count
            or any(not isinstance(value, str) or re.fullmatch('[a-f0-9]{32}', value) is None
                   for value in plan['part_md5']) or plan['etag'] != _etag(plan['part_md5'])):
        raise ValueError('Invalid publication multipart transport identity')
    return plan


def plan_file(source, facts, *, custody=None):
    """Verify known full-file facts before any remote request; retain bounded part facts."""
    if not 1 <= (facts['size'] + PART_BYTES - 1) // PART_BYTES <= MAX_PARTS:
        raise ValueError('Publication asset exceeds bounded multipart inventory')
    source = Path(source)
    custody = custody_identity(source) if custody is None else custody
    if custody[2] != facts['size']:
        raise ValueError('Local publication asset size changed')
    digest, checksum, parts, size = sha256(), md5(), [], 0
    with source.open('rb') as stream:
        _require_source(source, stream, custody)
        while block := stream.read(PART_BYTES):
            size += len(block)
            if size > facts['size']:
                raise ValueError('Local publication asset exceeds declared size')
            digest.update(block); checksum.update(block); parts.append(md5(block).hexdigest())
        _require_source(source, stream, custody)
    if (size != facts['size'] or digest.hexdigest() != facts['sha256']
            or checksum.hexdigest() != facts['md5']):
        raise ValueError('Local publication multipart bytes differ from expected identity')
    return require_plan(dict(kind='multipart', part_bytes=PART_BYTES, part_md5=parts, etag=_etag(parts)), size)


def _status(error):
    return getattr(error, 'response', {}).get('ResponseMetadata', {}).get('HTTPStatusCode')


def abort_attempt(client, bucket, key, attempt):
    """Abort only an exact retained upload ID, never a published object."""
    if attempt is None or attempt['stage'] in ('aborted', 'completed', 'closed'):
        return
    try:
        client.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=attempt['id'])
    except Exception as error:
        if _status(error) != 404:
            raise


def transfer(client, *, bucket, key, source, facts, plan, content_type, cache_control, record, custody=None):
    """One part at a time; persist completion intent before its conditional request.

    ``record`` atomically journals the owned upload ID and stage. An uncertain
    completion remains journaled for HEAD reconciliation on the next invocation.
    """
    require_plan(plan, facts['size'])
    source = Path(source)
    custody = custody_identity(source) if custody is None else custody
    if custody[2] != facts['size']:
        raise ValueError('Local publication asset size changed')
    arguments = dict(Bucket=bucket, Key=key)
    attempt = None
    completing = False
    with source.open('rb') as stream:
        _require_source(source, stream, custody)
        response = client.create_multipart_upload(**arguments, ContentType=content_type, CacheControl=cache_control)
        upload_id = response.get('UploadId')
        if not isinstance(upload_id, str) or not upload_id or len(upload_id) > 4096:
            raise ValueError('Publication SDK returned no multipart upload identity')
        attempt = dict(id=upload_id, stage='uploading')
        try:
            record(attempt)
            digest, checksum, size, parts = sha256(), md5(), 0, []
            for number, expected in enumerate(plan['part_md5'], 1):
                block = stream.read(PART_BYTES)
                size += len(block)
                if md5(block).hexdigest() != expected or not block or size > facts['size']:
                    raise ValueError('Local publication multipart part changed')
                digest.update(block); checksum.update(block)
                result = client.upload_part(**arguments, UploadId=upload_id, PartNumber=number,
                    Body=block, ContentLength=len(block), ContentMD5=b64encode(bytes.fromhex(expected)).decode())
                etag = result.get('ETag')
                if _observed_etag(etag) != expected:
                    raise ValueError('Publication multipart part ETag differs from consumed bytes')
                parts.append(dict(PartNumber=number, ETag=etag))
            if (stream.read(1) or size != facts['size'] or digest.hexdigest() != facts['sha256']
                    or checksum.hexdigest() != facts['md5']):
                raise ValueError('Local publication multipart bytes differ from expected identity')
            _require_source(source, stream, custody)
            record(dict(id=upload_id, stage='completing'))
            completing = True
            try:
                result = client.complete_multipart_upload(**arguments, UploadId=upload_id,
                    MultipartUpload={'Parts': parts}, IfNoneMatch='*')
            except Exception as error:
                if _status(error) == 412:
                    abort_attempt(client, bucket, key, attempt)
                    record(dict(id=upload_id, stage='aborted'))
                    return 'already_exists'  # Caller must still verify the exact remote identity.
                raise
            etag = result.get('ETag')
            if _observed_etag(etag) != plan['etag']:
                raise ValueError('Publication multipart completion ETag differs from expected identity')
            record(dict(id=upload_id, stage='completed'))
            return 'created'
        except BaseException as error:
            if not completing:
                try:
                    abort_attempt(client, bucket, key, attempt)
                    record(dict(id=upload_id, stage='aborted'))
                except BaseException:
                    error.add_note('Owned multipart cleanup is unconfirmed; retained upload ID: ' + upload_id)
            raise
