"""Owned, checked files for the exact derived catalog namespaces."""
from hashlib import sha256
import os
from pathlib import Path
import re
import tempfile
import weakref

_issued = weakref.WeakValueDictionary()


def custody_identity(path):
    value = Path(path).stat()
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


class VerifiedFile(dict):
    """A JSON-compatible digest with process-local, exact-file custody.

    Serialization retains only public hash/size facts. It cannot manufacture
    the issued object needed to avoid a new integrity pass after restoration.
    """
    def require(self, path):
        if (_issued.get(id(self)) is not self or self.process != os.getpid() or Path(path).resolve() != self.path
                or custody_identity(path) != self.custody
                or (self.get('bytes'), self.get('sha256')) != self.facts):
            raise ValueError('Verified catalog file custody changed')
        return self


def _verified(path, facts):
    result = VerifiedFile(facts)
    result.path = Path(path).resolve()
    result.process = os.getpid()
    result.custody = custody_identity(path)
    result.facts = result['bytes'], result['sha256']
    _issued[id(result)] = result
    return result


def require_derived_key(key):
    if not isinstance(key, str) or re.fullmatch(
        r'(?:indexes|catalog-generations/[0-9a-f]{32}|catalog-history/sha256/[0-9a-f]{64})/'
        r'(?:document-filenames|documents)\.parquet', key) is None:
        raise ValueError('Derived file operation requires an exact catalog table key')


def file_identity(path):
    before = custody_identity(path)
    digest, count = sha256(), 0
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024**2), b''):
            digest.update(chunk)
            count += len(chunk)
    if custody_identity(path) != before:
        raise ValueError(f'Catalog changed during hashing: {path}')
    return _verified(path, {'sha256': digest.hexdigest(), 'bytes': count})


def retain_verified_file(path, destination, *, expected, key):
    """Retain an immutable hard link under the caller's directory ownership.

    Both names own a link until their stage cleans it up. This avoids a copy
    and hash pass; cross-filesystem inputs retain the checked-copy route.
    """
    path, destination = Path(path), Path(destination)
    actual = expected.require(path) if isinstance(expected, VerifiedFile) else file_identity(path)
    check_identity(actual, expected, key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, partial_name = tempfile.mkstemp(prefix=destination.name+'.', suffix='.partial', dir=destination.parent)
    os.close(fd)
    partial = Path(partial_name)
    partial.unlink()
    try:
        os.link(path, partial)
    except OSError as error:
        import errno
        if error.errno != errno.EXDEV:
            raise
        with path.open('rb') as source:
            return copy_checked(source, destination, size=actual['bytes'], expected=actual, key=key, exclusive=True)
    try:
        try:
            os.link(partial, destination)
        except FileExistsError:
            check_identity(file_identity(destination), actual, key)
        directory = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        partial.unlink()
        # Adding/removing owned links changes ctime. Rebind only after proving
        # the exact inode, size and modification time across that operation.
        now = custody_identity(path)
        if now[:4] != actual.custody[:4]:
            raise ValueError('Catalog changed while retaining verified file')
        actual.custody = now
        return _verified(destination, actual)
    except BaseException as error:
        error.add_note(f'Owned catalog partial retained for diagnosis: {partial}')
        raise


def check_identity(actual, expected, key):
    if expected is not None and any(actual[name] != expected[name] for name in ('bytes', 'sha256')):
        raise ValueError(f'Selected catalog checksum mismatch: {key}')
    if key.startswith('catalog-history/sha256/') and actual['sha256'] != key.split('/')[2]:
        raise ValueError(f'Catalog history digest does not match its key: {key}')


def copy_checked(source, destination, *, size, expected=None, key='catalog', exclusive=False):
    """Publish an owned partial only after exact size/hash checks and fsync.

    On any failure the partial remains named in the exception for diagnosis.
    Exclusive publication uses a hard link, so concurrent immutable writers
    cannot replace one another between an existence check and a rename.
    """
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, partial_name = tempfile.mkstemp(prefix=destination.name + '.', suffix='.partial', dir=destination.parent)
    partial = Path(partial_name)
    digest, count = sha256(), 0
    try:
        with os.fdopen(fd, 'wb') as target:
            for chunk in iter(lambda: source.read(1024**2), b''):
                count += len(chunk)
                if count > size:
                    raise ValueError(f'Stored catalog exceeds declared size: {key}')
                digest.update(chunk)
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
        if count != size:
            raise ValueError(f'Incomplete stored catalog: {key}')
        actual = {'sha256': digest.hexdigest(), 'bytes': count}
        check_identity(actual, expected, key)
        try:
            os.link(partial, destination)
        except FileExistsError:
            if not exclusive:
                raise  # Read destinations are newly owned snapshot paths.
            check_identity(file_identity(destination), actual, key)
        directory = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        partial.unlink()
        return _verified(destination, actual)
    except BaseException as error:
        error.add_note(f'Owned catalog partial retained for diagnosis: {partial}')
        raise
