"""One create-only raw boundary. Adapters provide HEAD and atomic single-object create."""
from dataclasses import dataclass, replace
import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import parse_qsl, urlsplit

from congress_api.retention.receipt_privacy import credential_parameters

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
            urls = ([node] if node.lower().startswith(('http://', 'https://')) else
                    re.findall(r'https?://[^\s<>]+',node,re.I))
            for url in urls:
                parts = urlsplit(url)
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


def prepare_stored(key, source, *, operation='create', body_identity=True):
    """Validate and hash already prepared bytes before storage I/O."""
    validate_key(key, operation, body_identity=body_identity)
    if key.startswith(('receipts/', 'provenance/')):
        source.seek(0)
        encoded = source.read(2) == b'\x1f\x8b'
        source.seek(0)
        reader = gzip.GzipFile(fileobj=source) if encoded else source
        try:
            for line in reader:
                # This boundary checks public URLs. The receipt writer owns JSON
                # schema; opaque historical payloads remain valid storage inputs.
                text = line.decode('utf-8')
                validate_record(json.loads(text) if text.lstrip().startswith(('{', '[', '"')) else text)
        finally:
            if reader is not source:
                reader.close()
        source.seek(0)
    digest = hashlib.file_digest(source, 'md5')
    size = source.seek(0, os.SEEK_END)
    source.seek(0)
    if size > 5 * 1024**3:
        raise ValueError('Single-PUT size limit exceeded')
    return dict(md5=digest.hexdigest(), size=size)


def write_result(key, created, *, md5, size):
    suffix = '.gz' if key.endswith('.gz') else '.pdf' if key.endswith('.pdf') else ''
    if not created and not key.startswith('bodies/'):
        raise RuntimeError(f'Concurrent update or reused receipt name: {key}')
    return WriteResult('stored' if created else 'unchanged', suffix,
                       md5 if created else None, size if created else None)


def create_stored(adapter, key, source, media, *, encoding=None, operation='create', body_identity=True,
                  expected_md5=None, expected_size=None):
    facts = prepare_stored(key, source, operation=operation, body_identity=body_identity)
    if ((expected_md5 is not None and facts['md5'] != expected_md5)
            or (expected_size is not None and facts['size'] != expected_size)):
        raise ValueError('Prepared bytes differ from their qualified checksum or size')
    created = adapter.create(key, source, media=media, encoding=encoding, **facts)
    return write_result(key, created, **facts)


async def create_stored_async(adapter, key, source, media):
    facts = prepare_stored(key, source, body_identity=False)
    created = await adapter.create(key, source, media=media, encoding=None, **facts)
    return write_result(key, created, **facts)


def compressible(media):
    media = (media or '').split(';', 1)[0].strip().lower()
    return media.startswith('text/') or media.endswith(('+xml', '+json')) or media in {
        'application/xml', 'application/json', 'application/x-ndjson', 'application/javascript'}


class BodyStore:
    def __init__(self, adapter):
        self.adapter, self.known = adapter, {}

    def reference(self, key, *, stored_suffix):
        """Verify an existing raw reference; recovery imports need no whole reread."""
        validate_key(key)
        if not key.startswith('bodies/') or key.endswith(('.gz','.pdf')) or stored_suffix not in {'','.gz'}:
            raise ValueError('Invalid retained body reference')
        if key in self.known and self.known[key].suffix==stored_suffix:
            return replace(self.known[key],outcome='unchanged',md5=None,size=None)
        if self.adapter.head(key+stored_suffix) is None:
            raise ValueError('Missing retained body reference')
        result=WriteResult('unchanged',stored_suffix)
        self.known[key]=result
        return result

    def existing(self, key):
        """The run set and one legacy-key HEAD, without reading body bytes."""
        if key in self.known:
            return replace(self.known[key], outcome='unchanged', md5=None, size=None)
        if self.adapter.head(key + '.gz') is not None:
            result = WriteResult('unchanged', '.gz')
            self.known[key] = result
            return result
        return None

    def put_prepared(self, key, file, media, *, encoding=None, expected_md5=None, expected_size=None):
        """Use a caller's streaming compression without another compression pass."""
        validate_key(key)
        if not key.startswith('bodies/') or key.endswith(('.gz', '.pdf')):
            raise ValueError('Prepared body requires a suffix-free identity')
        result = self.existing(key)
        if result is None:
            with Path(file).open('rb') as source:
                result = create_stored(self.adapter, key, source, media, encoding=encoding,
                                       expected_md5=expected_md5, expected_size=expected_size)
            self.known[key] = result
        return result

    def put(self, key, file, media, *, operation='create'):
        validate_key(key, operation)
        if not key.startswith('bodies/'):
            with Path(file).open('rb') as source:
                return create_stored(self.adapter, key, source, media)
        if key.endswith(('.gz', '.pdf')):
            raise ValueError('New body writes require a suffix-free identity')
        result = self.existing(key)
        if result is None:
            with Path(file).open('rb') as source, tempfile.TemporaryFile() as prepared:
                identity = hashlib.sha256()
                def copy(destination):
                    while chunk := source.read(1024**2):
                        identity.update(chunk)
                        destination.write(chunk)
                if compressible(media):
                    with gzip.GzipFile(filename='', fileobj=prepared, mode='wb', mtime=0) as zipped:
                        copy(zipped)
                else:
                    copy(prepared)
                if identity.hexdigest() != key.rsplit('/',1)[1]:
                    raise ValueError('Original body identity differs from its key')
                prepared.seek(0)
                result = create_stored(self.adapter, key, prepared, media,
                                       encoding='gzip' if compressible(media) else None)
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

    def parameters(self, key, source, *, media, encoding, md5, size):
        options = dict(ContentEncoding=encoding) if encoding else {}
        if key.endswith('.pdf'):
            options.update(ContentDisposition='inline', CacheControl='public, max-age=31536000, immutable')
        if isinstance(source, io.BytesIO):
            body = source.getvalue()
        else:
            body = source
            options['ContentLength'] = size
        return dict(Bucket=self.bucket, Key=key, Body=body, ContentType=media,
                    IfNoneMatch='*', ContentMD5=base64.b64encode(bytes.fromhex(md5)).decode(), **options)

    @staticmethod
    def verify(result, md5):
        if result['ETag'].strip('"') != md5:
            raise ValueError('Upload checksum mismatch')
        return True

    def create(self, key, source, **facts):
        from botocore.exceptions import ClientError
        try:
            result = self.client.put_object(**self.parameters(key, source, **facts))
        except ClientError as error:
            if error.response['Error']['Code'] in {'412', 'PreconditionFailed'}:
                return False
            raise
        return self.verify(result, facts['md5'])


class AsyncR2Adapter(R2Adapter):
    async def create(self, key, source, **facts):
        from botocore.exceptions import ClientError
        try:
            result = await self.client.put_object(**self.parameters(key, source, **facts))
        except ClientError as error:
            if error.response['Error']['Code'] in {'412', 'PreconditionFailed'}:
                return False
            raise
        return self.verify(result, facts['md5'])


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
