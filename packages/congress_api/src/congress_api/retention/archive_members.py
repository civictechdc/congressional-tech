"""Read bounded ZIP member bytes and provenance without filesystem extraction.

Consume the iterator sequentially to retain at most one expanded member at a
time. Member names are source text, never destination paths. Nested ZIPs are
ordinary member bytes; a second extraction depth is refused by default.
"""

from dataclasses import dataclass
from io import RawIOBase
from pathlib import PureWindowsPath
import struct
import zlib
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile
from congress_api.parsers.file_wrapper import regular_file


@dataclass(frozen=True)
class ZipLimits:
    max_archive_bytes: int = 64 * 1024**2
    max_member_bytes: int = 64 * 1024**2
    max_total_bytes: int = 128 * 1024**2
    max_members: int = 1024
    max_directory_bytes: int = 1024**2
    max_depth: int = 1

    def __post_init__(self):
        if any(value <= 0 for value in vars(self).values()):
            raise ValueError('ZIP limits must be positive')


class ArchiveReadError(ValueError):
    """Archive-level refusal with a stable status for acquisition receipts."""

    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


@dataclass(frozen=True)
class ArchiveMember:
    archive_path: str
    entry_index: int
    original_name: str
    declared_bytes: int
    compressed_bytes: int
    status: str
    data: bytes | None = None
    error_type: str | None = None
    unsafe_name: bool = False
    nested_archive: bool = False
    source_offset: int | None = None


def iter_archive_members(body, *, archive_path, limits):
    """Share retention limits for ZIP entries and supported regular-file wrappers."""
    if not body.startswith(b'rtfd'):
        yield from iter_zip_members(body, archive_path=archive_path, limits=limits)
        return
    if len(body) > limits.max_archive_bytes:
        raise ArchiveReadError('archive_size_limit', 'File wrapper exceeds its limit')
    try:
        file = regular_file(body)
    except ValueError as exc:
        raise ArchiveReadError('unsupported_format', 'Unsupported file wrapper') from exc
    size = len(file.data)
    status = ('member_size_limit' if size > limits.max_member_bytes else
              'aggregate_size_limit' if size > limits.max_total_bytes else 'completed')
    yield ArchiveMember(archive_path, 0, file.name, size, size, status,
        data=file.data.tobytes() if status == 'completed' else None,
        unsafe_name=_unsafe_name(file.name), source_offset=file.offset,
        nested_archive=file.data[:4] in (b'rtfd', b'PK\x03\x04', b'PK\x05\x06'))


class _ArchiveView(RawIOBase):
    """Seekable read-only bytes view that avoids a second archive-sized buffer."""

    def __init__(self, body, end):
        self.body, self.end, self.position = memoryview(body), end, 0

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        position = offset + (0 if whence == 0 else self.position if whence == 1 else self.end)
        if whence not in (0, 1, 2) or (whence == 0 and position < 0):
            raise ValueError('Invalid archive seek')
        # Match BytesIO: relative backward seeks clamp to the start. ZipFile
        # probes before the start of small archives when looking for comments.
        self.position = max(0, position)
        return self.position

    def read(self, size=-1):
        end = self.end if size < 0 else min(self.end, self.position + size)
        value = self.body[self.position:end].tobytes()
        self.position = max(self.position, end)
        return value


def _directory_preflight(body, limits):
    """Bound the central directory before ZipFile allocates its entry objects."""
    start = max(0, len(body) - 22 - 65535)
    end = len(body)
    while True:
        offset = body.rfind(b'PK\x05\x06', start, end)
        if offset < 0:
            raise ArchiveReadError('corrupt_archive', 'ZIP end record is missing')
        if offset + 22 <= len(body):
            comment_size = struct.unpack_from('<H', body, offset + 20)[0]
            if offset + 22 + comment_size == len(body):
                break
        end = offset
    disk, directory_disk, disk_count, count, size, directory_offset = struct.unpack_from(
        '<4H2I', body, offset + 4)
    if count == 65535 or size == 0xffffffff or directory_offset == 0xffffffff:
        raise ArchiveReadError('unsupported_zip64', 'ZIP64 end records are unsupported')
    if disk or directory_disk or disk_count != count:
        raise ArchiveReadError('unsupported_multidisk', 'Split ZIP archives are unsupported')
    if count > limits.max_members:
        raise ArchiveReadError('member_count_limit', 'ZIP entry count exceeds its limit')
    if size > limits.max_directory_bytes:
        raise ArchiveReadError('directory_size_limit', 'ZIP central directory exceeds its limit')
    cursor = offset - size
    if cursor < 0:
        raise ArchiveReadError('corrupt_archive', 'ZIP central directory exceeds the archive')
    actual_count = 0
    while cursor < offset:
        if cursor + 46 > offset or body[cursor:cursor + 4] != b'PK\x01\x02':
            raise ArchiveReadError('corrupt_archive', 'Invalid ZIP central directory entry')
        name, extra, comment = struct.unpack_from('<3H', body, cursor + 28)
        cursor += 46 + name + extra + comment
        actual_count += 1
        if actual_count > limits.max_members:
            raise ArchiveReadError('member_count_limit', 'ZIP entry count exceeds its limit')
    if cursor != offset or actual_count != count:
        raise ArchiveReadError('corrupt_archive', 'ZIP directory sizes or counts disagree')
    return offset + 22


def _unsafe_name(name):
    parts = name.replace('\\', '/').split('/')
    return (not name or '\x00' in name or name.startswith(('/', '\\'))
            or bool(PureWindowsPath(name).drive) or '..' in parts)


def is_office_zip(body: bytes, *, limits: ZipLimits = ZipLimits()):
    """Identify an Open XML package by its exact root directory member name.

    This bounded directory-only check does not read compressed member bytes.
    A generic archive containing a stored Office document remains generic.
    Malformed or refused archives return False for the normal reader to report.
    """
    if len(body) > limits.max_archive_bytes:
        return False
    try:
        end = _directory_preflight(body, limits)
        with ZipFile(_ArchiveView(body, end)) as archive:
            return any(info.orig_filename == '[Content_Types].xml'
                       for info in archive.infolist())
    except (ArchiveReadError, BadZipFile, UnicodeError, ValueError, NotImplementedError):
        return False


def iter_zip_members(body: bytes, *, archive_path: str,
                     limits: ZipLimits = ZipLimits(), depth: int = 0):
    """Yield complete bytes or an explicit failure for each non-directory entry.

    Positions include directory entries, so duplicate source names stay distinct.
    Only stored and DEFLATE compression are admitted: their readers bound output
    during decompression. ZIP64 and split archives are explicitly unsupported.
    Archive-level errors raise ArchiveReadError; corrupt members yield failures
    and allow subsequent independent members to be inspected. Once the aggregate
    limit is reached, remaining entries yield refusals without decompression.
    """
    if depth < 0:
        raise ValueError('ZIP depth must be nonnegative')
    if depth >= limits.max_depth:
        raise ArchiveReadError('nesting_limit', 'ZIP extraction depth exceeds its limit')
    if len(body) > limits.max_archive_bytes:
        raise ArchiveReadError('archive_size_limit', 'ZIP archive bytes exceed their limit')
    end = _directory_preflight(body, limits)
    try:
        # Comments do not describe members. Omit them from the view so ZIP end
        # signatures inside comments cannot confuse the stdlib end-record scan.
        archive = ZipFile(_ArchiveView(body, end))
    except (BadZipFile, UnicodeError, ValueError, NotImplementedError) as exc:
        raise ArchiveReadError('corrupt_archive', type(exc).__name__) from exc
    total = 0
    exhausted = False
    with archive:
        for position, info in enumerate(archive.infolist()):
            if info.is_dir():
                continue
            context = dict(archive_path=archive_path, entry_index=position,
                           original_name=info.orig_filename,
                           declared_bytes=info.file_size,
                           compressed_bytes=info.compress_size,
                           unsafe_name=_unsafe_name(info.orig_filename))
            if exhausted:
                yield ArchiveMember(**context, status='aggregate_size_limit')
                continue
            if info.flag_bits & 1:
                yield ArchiveMember(**context, status='encrypted_member')
                continue
            if info.compress_type not in (ZIP_STORED, ZIP_DEFLATED):
                yield ArchiveMember(**context, status='unsupported_compression')
                continue
            if info.file_size > limits.max_member_bytes:
                yield ArchiveMember(**context, status='member_size_limit')
                continue
            if info.file_size > limits.max_total_bytes - total:
                exhausted = True
                yield ArchiveMember(**context, status='aggregate_size_limit')
                continue
            data = bytearray()
            status, error_type = 'completed', None
            try:
                with archive.open(info) as source:
                    while True:
                        budget = min(limits.max_member_bytes - len(data),
                                     limits.max_total_bytes - total)
                        chunk = source.read(min(64 * 1024, budget + 1))
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > limits.max_total_bytes:
                            status, exhausted = 'aggregate_size_limit', True
                            break
                        if len(data) + len(chunk) > limits.max_member_bytes:
                            status = 'member_size_limit'
                            break
                        data.extend(chunk)
            except (BadZipFile, EOFError, OSError, ValueError, RuntimeError,
                    NotImplementedError, zlib.error) as exc:
                status, error_type = 'corrupt_member', type(exc).__name__
            payload = bytes(data) if status == 'completed' else None
            del data
            yield ArchiveMember(**context, status=status, error_type=error_type,
                            data=payload, nested_archive=bool(payload and payload.startswith(
                                (b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08'))))
            # Do not retain the previous payload while buffering the next member.
            del payload
