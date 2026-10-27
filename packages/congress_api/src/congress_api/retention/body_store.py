"""One create-only raw boundary. Adapters provide HEAD and atomic single-object create."""
from dataclasses import dataclass, replace
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import parse_qsl, urlsplit

from congress_api.retention.receipt_privacy import URL, credential_parameters

RAW_PREFIXES = ('bodies/', 'receipts/', 'provenance/')
BODY = re.compile(r'bodies/sha256/([a-f0-9]{2})/([a-f0-9]{64})(\.gz|\.pdf)?')


@dataclass(frozen=True)
class WriteResult:
    outcome: str
    suffix: str
    md5: str | None = None
    size: int | None = None


def validate_key(key, operation='create', *, body_identity=True):
    if operation != 'create':
        raise ValueError('Raw storage is create-only')
    if (not isinstance(key, str) or not key.startswith(RAW_PREFIXES) or '\\' in key
            or any(p in {'', '.', '..'} for p in key.split('/'))):
        raise ValueError('Invalid raw key')
    if body_identity and key.startswith('bodies/'):
        match = BODY.fullmatch(key)
        if not match or match[1] != match[2][:2]:
            raise ValueError('Invalid body shard or SHA-256')


def validate_record(value):
    """Check every recorded URL, including nested observations and recovery evidence."""
    names = {row['parameter'].casefold() for row in credential_parameters()}

    def walk(node):
        if isinstance(node, str):
            for match in URL.finditer(node):
                parts = urlsplit(match[0])
                if parts.username is not None or parts.password is not None or any(
                        name.casefold() in names for name, _ in parse_qsl(parts.query, keep_blank_values=True)):
                    raise ValueError('Credential in recorded URL')
        elif isinstance(node, dict):
            for key, child in node.items():
                walk(key)
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)
    walk(value)


def create_stored(adapter, key, source, media, *, encoding=None, operation='create', body_identity=True):
    """Create already prepared bytes; receipt validation finishes before adapter I/O."""
    validate_key(key, operation, body_identity=body_identity)
    if key.startswith(('receipts/', 'provenance/')):
        source.seek(0)
        reader = gzip.GzipFile(fileobj=source) if key.endswith('.gz') else source
        try:
            for line in reader:
                validate_record(json.loads(line))
        finally:
            if reader is not source:
                reader.close()
        source.seek(0)
    digest = hashlib.file_digest(source, 'md5')
    size = source.seek(0, os.SEEK_END)
    source.seek(0)
    if size > 5 * 1024**3:
        raise ValueError('Single-PUT size limit exceeded')
    created = adapter.create(key, source, media=media, encoding=encoding,
                             md5=digest.hexdigest(), size=size)
    suffix = '.gz' if key.endswith('.gz') else '.pdf' if key.endswith('.pdf') else ''
    if not created and not key.startswith('bodies/'):
        raise RuntimeError(f'Concurrent update or reused receipt name: {key}')
    return WriteResult('stored' if created else 'unchanged', suffix,
                       digest.hexdigest() if created else None, size if created else None)


def compressible(media):
    media = (media or '').split(';', 1)[0].strip().lower()
    return media.startswith('text/') or media.endswith(('+xml', '+json')) or media in {
        'application/xml', 'application/json', 'application/x-ndjson', 'application/javascript'}


class BodyStore:
    def __init__(self, adapter):
        self.adapter, self.known = adapter, {}

    def put(self, key, file, media, *, operation='create'):
        validate_key(key, operation)
        if not key.startswith('bodies/'):
            with Path(file).open('rb') as source:
                return create_stored(self.adapter, key, source, media)
        if key.endswith(('.gz', '.pdf')):
            raise ValueError('New body writes require a suffix-free identity')
        if key in self.known:
            return replace(self.known[key], outcome='unchanged', md5=None, size=None)
        older = self.adapter.head(key + '.gz')
        if older is not None:
            result = WriteResult('unchanged', '.gz')
        else:
            with Path(file).open('rb') as source, tempfile.TemporaryFile() as prepared:
                if compressible(media):
                    with gzip.GzipFile(filename='', fileobj=prepared, mode='wb', mtime=0) as zipped:
                        shutil.copyfileobj(source, zipped, 1024**2)
                    prepared.seek(0)
                    result = create_stored(self.adapter, key, prepared, media, encoding='gzip')
                else:
                    result = create_stored(self.adapter, key, source, media)
        self.known[key] = result
        return result


class R2Adapter:
    def __init__(self, client, bucket):
        self.client, self.bucket = client, bucket

    def head(self, key):
        from botocore.exceptions import ClientError
        try:
            value = self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as error:
            if error.response['Error']['Code'] in {'404', 'NoSuchKey', 'NotFound'}:
                return None
            raise
        return dict(size=value['ContentLength'], etag=value['ETag'].strip('"'))

    def create(self, key, source, *, media, encoding, md5, size):
        from botocore.exceptions import ClientError
        options = dict(ContentEncoding=encoding) if encoding else {}
        try:
            result = self.client.put_object(Bucket=self.bucket, Key=key, Body=source,
                ContentLength=size, ContentType=media, IfNoneMatch='*',
                ContentMD5=base64.b64encode(bytes.fromhex(md5)).decode(), **options)
        except ClientError as error:
            if error.response['Error']['Code'] in {'412', 'PreconditionFailed'}:
                return False
            raise
        if result['ETag'].strip('"') != md5:
            raise ValueError('Upload checksum mismatch')
        return True


class LocalAdapter:
    def __init__(self, root):
        self.root = Path(root)

    def head(self, key):
        path = self.root / key
        try:
            return dict(size=path.stat().st_size, etag=None)
        except FileNotFoundError:
            return None

    def create(self, key, source, *, media, encoding, md5, size):
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as destination:
                shutil.copyfileobj(source, destination, 1024**2)
                destination.flush()
                os.fsync(destination.fileno())
            with open(temporary, 'rb') as check:
                if hashlib.file_digest(check, 'md5').hexdigest() != md5 or check.tell() != size:
                    raise ValueError('Local upload checksum mismatch')
            try:
                os.link(temporary, path)
            except FileExistsError:
                return False
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            return True
        finally:
            Path(temporary).unlink(missing_ok=True)
