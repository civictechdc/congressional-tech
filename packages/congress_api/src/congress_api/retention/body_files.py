"""Shared bounded file compression, immutable upload and collision verification."""
import gzip
import hashlib
from pathlib import Path

CHUNK = 1024**2


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
