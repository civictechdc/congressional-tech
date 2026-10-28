"""Owned, checked files for the exact derived catalog namespaces."""
from hashlib import sha256
import os
from pathlib import Path
import re
import tempfile

from congress_shared.custody import (
    VerifiedFile,
    custody_identity,
    issue_verified_file as _verified,
    verify_local_file,
)


def require_derived_key(key):
    if not isinstance(key, str) or re.fullmatch(
        r'(?:indexes|catalog-generations/[0-9a-f]{32}|catalog-history/sha256/[0-9a-f]{64})/'
        r'(?:document-filenames|documents)\.parquet', key) is None:
        raise ValueError('Derived file operation requires an exact catalog table key')


def file_identity(path, *, additional_hashes=None):
    return verify_local_file(path, sha256_factory=sha256, identity_fn=custody_identity,
                             additional_hashes=additional_hashes)


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
        # Adding/removing owned links changes link count and may change ctime.
        # Rebind only after proving
        # the exact inode, size and modification time across that operation.
        now = custody_identity(path)
        if now[:4] != actual.custody[:4]:
            raise ValueError('Catalog changed while retaining verified file')
        actual._rebind_custody(now)
        return _verified(destination, actual)
    except BaseException as error:
        error.add_note(f'Owned catalog partial retained for diagnosis: {partial}')
        raise


def check_identity(actual, expected, key):
    if expected is not None and any(actual[name] != expected[name] for name in ('bytes', 'sha256')):
        raise ValueError(f'Selected catalog checksum mismatch: {key}')
    if key.startswith('catalog-history/sha256/') and actual['sha256'] != key.split('/')[2]:
        raise ValueError(f'Catalog history digest does not match its key: {key}')


def copy_checked(source, destination, *, size, expected=None, key='catalog', exclusive=False, partial_directory=None):
    """Publish an owned partial only after exact size/hash checks and fsync.

    On any failure the partial remains named in the exception for diagnosis.
    Callers may retain partials in a private directory on the same filesystem.
    Exclusive publication uses a hard link, so concurrent immutable writers
    cannot replace one another between an existence check and a rename.
    """
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, partial_name = tempfile.mkstemp(prefix=destination.name + '.', suffix='.partial',
                                         dir=partial_directory if partial_directory is not None else destination.parent)
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
