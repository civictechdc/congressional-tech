"""Owned capture files, bounded compression, immutable upload and collision checks.

Interpretation receives bytes; acquired files are read and released here.
"""
import codecs
from dataclasses import dataclass, field
import gzip
import hashlib
from pathlib import Path

from congress_api.models.content import CapturedBody, RawContent

CHUNK = 1024**2


@dataclass(frozen=True)
class CapturedFile:
    """Owned native response file; never construct this from serialized input."""
    path: Path
    media_type: str
    sha256: str = field(init=False)
    body_encoding: str = field(init=False)
    size: int = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, 'path', Path(self.path))
        digest, size = hashlib.sha256(), 0
        decoder = codecs.getincrementaldecoder('utf-8')()
        with self.path.open('rb') as source:
            while chunk := source.read(1024**2):
                digest.update(chunk)
                size += len(chunk)
                if decoder is not None:
                    try:
                        decoder.decode(chunk)
                    except UnicodeDecodeError:
                        decoder = None
        if decoder is not None:
            try:
                decoder.decode(b'', final=True)
            except UnicodeDecodeError:
                decoder = None
        object.__setattr__(self, 'size', size)
        object.__setattr__(self, 'sha256', digest.hexdigest())
        object.__setattr__(self, 'body_encoding', 'utf-8' if decoder is not None else 'base64')

    def __len__(self):
        return self.size

    def prefix(self, limit=8192):
        with self.path.open('rb') as source:
            return source.read(limit)

    def read_bytes(self):
        return self.path.read_bytes()

    def close(self):
        self.path.unlink(missing_ok=True)

    def source_dict(self):
        return dict(media_type=self.media_type, body=self,
                    body_encoding=self.body_encoding, sha256=self.sha256)


def content_body(content):
    """Validate metadata while preserving an acquired file or byte payload."""
    body = content.get('body')
    if isinstance(body, (CapturedBody, CapturedFile)):
        if any(content.get(key) != getattr(body, key)
               for key in ('media_type', 'body_encoding', 'sha256')):
            raise ValueError('Captured body metadata mismatch')
        return body if isinstance(body, CapturedFile) else body.data
    return RawContent.model_validate(content).body_bytes()


def content_bytes(content):
    """Materialize only for consumers that require a bounded byte payload."""
    body = content_body(content)
    return body.read_bytes() if isinstance(body, CapturedFile) else body


def capture_files(value):
    """Find owned files without retaining their surrounding provider payloads."""
    if isinstance(value, CapturedFile):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from capture_files(child)
    elif isinstance(value, list):
        for child in value:
            yield from capture_files(child)


def close_capture_files(value):
    """Release owned files, including prior attempts, after all readers finish."""
    for body in capture_files(value):
        body.close()


def file_digest(path, algorithm='sha256'):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, algorithm).hexdigest()


def retain_body_file(store, path, scratch, *, expected_sha256=None):
    """Publish only verified original bytes; scratch belongs to this operation."""
    path, scratch = Path(path), Path(scratch)
    size = path.stat().st_size
    digest = hashlib.sha256()
    owned = False
    try:
        with path.open('rb') as source, scratch.open('xb') as destination:
            owned = True
            with gzip.GzipFile(filename='', fileobj=destination, mode='wb',
                               compresslevel=1, mtime=0) as zipped:
                while chunk := source.read(CHUNK):
                    digest.update(chunk)
                    zipped.write(chunk)
        digest = digest.hexdigest()
        if path.stat().st_size != size or (expected_sha256 and digest != expected_sha256):
            raise ValueError('Acquired file changed before retention')
        key = f'bodies/sha256/{digest[:2]}/{digest}.gz'
        created = store.put_file(key, scratch)
        if created is False:
            # An earlier orphan may have a different gzip representation.
            store.read_file(key, scratch, max_bytes=size + size // 100 + CHUNK)
            actual, raw_size = hashlib.sha256(), 0
            with gzip.open(scratch, 'rb') as source:
                while chunk := source.read(CHUNK):
                    raw_size += len(chunk)
                    if raw_size > size:
                        raise ValueError('Stored body length mismatch')
                    actual.update(chunk)
            if actual.hexdigest() != digest or raw_size != size:
                raise ValueError('Stored body checksum mismatch')
        return dict(body_key=key, sha256=digest, bytes=size,
                    stored_sha256=file_digest(scratch), stored_bytes=scratch.stat().st_size)
    finally:
        if owned:
            scratch.unlink(missing_ok=True)
