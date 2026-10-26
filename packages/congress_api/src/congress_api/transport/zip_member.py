"""Read one ZIP member through bounded, version-pinned publisher byte ranges."""

from dataclasses import dataclass
from io import RawIOBase
import hashlib
import re
import struct
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile
import zlib

import requests

from congress_api.retention.archive_members import ArchiveReadError, ZipLimits, validate_zip_directory
from congress_api.transport.http import get_with_retry, HttpRequestError, response_metadata


TAIL_BYTES = 22 + 65535
MEMBER_LIMITS = ZipLimits(max_archive_bytes=2**32 - 1, max_member_bytes=1024**2,
                         max_total_bytes=1024**2)


@dataclass(frozen=True)
class ZipMemberResponse:
    data: bytes
    source: dict


class ZipMemberReadError(ValueError):
    """Retain the last received source bytes and request receipts on refusal."""

    def __init__(self, message, *, data=b'', source=None, media_type='application/zip'):
        super().__init__(message)
        self.data, self.source, self.media_type = data, source or {}, media_type


class _RangeFile(RawIOBase):
    def __init__(self, session, url, limits):
        self.session, self.url, self.limits = session, url, limits
        self.position, self.size = 0, 0
        self.source = {'url': url, 'requests': []}
        self.cache = []
        self.last_data, self.media_type = b'', 'application/zip'
        self.transferred = 0
        self.validator = {}
        tail, start, end, size, headers = self._fetch(f'bytes=-{TAIL_BYTES}', TAIL_BYTES)
        if (start, end) != (max(0, size - TAIL_BYTES), size - 1):
            self.fail('Publisher returned a different ZIP tail range')
        if size > limits.max_archive_bytes:
            self.fail('ZIP archive exceeds the source size limit')
        etag, modified = headers.get('ETag'), headers.get('Last-Modified')
        if etag and not etag.startswith('W/'):
            self.validator = {'If-Match': etag}
        elif modified:
            self.validator = {'If-Unmodified-Since': modified}
        else:
            self.fail('ZIP source has no version validator')
        self.source.update(bytes=size, etag=etag, last_modified=modified)
        self.size, self.cache = size, [(start, tail)]
        self._preflight(tail, start)

    def fail(self, message):
        raise ZipMemberReadError(message, data=self.last_data, source=self.source,
                                 media_type=self.media_type)

    def _fetch(self, byte_range, budget):
        if len(self.source['requests']) >= 16 or self.transferred + budget > 3 * 1024**2:
            self.fail('ZIP range request or transfer budget exceeded')
        try:
            with get_with_retry(self.session, self.url, allowed=(200, 206), stream=True,
                                headers={'Accept-Encoding': 'identity', 'Range': byte_range,
                                         **self.validator}) as response:
                receipt = {**response_metadata(response), 'range': byte_range}
                self.source['requests'].append(receipt)
                self.last_data = b''
                self.media_type = response.headers.get('Content-Type', 'application/zip')
                if response.headers.get('Content-Encoding', 'identity') != 'identity':
                    self.fail('ZIP ranges must use identity content encoding')
                data = bytearray()
                for chunk in response.iter_content(8192):
                    remaining = budget - len(data)
                    data.extend(chunk[:max(0, remaining)])
                    self.last_data = bytes(data)
                    if len(chunk) > remaining:
                        receipt['truncated'] = True
                        self.fail('Publisher exceeded the ZIP range byte limit')
                body = bytes(data)
                self.transferred += len(body)
                receipt.update(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
                if response.status_code != 206 or response.url != self.url:
                    self.fail('Publisher did not return the requested ZIP range URL with HTTP 206')
                if self.media_type.split(';')[0].lower() in ('text/html', 'application/xhtml+xml'):
                    self.fail('Publisher returned HTML instead of a ZIP range')
                match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
                if not match:
                    self.fail('ZIP range lacks an exact Content-Range')
                start, end, size = map(int, match.groups())
                if not 0 <= start <= end < size or len(body) != end - start + 1:
                    self.fail('ZIP range length does not match Content-Range')
                if self.size:
                    if size != self.size:
                        self.fail('ZIP source size changed between requests')
                    if ('If-Match' in self.validator
                            and response.headers.get('ETag') != self.validator['If-Match']):
                        self.fail('ZIP source ETag changed between requests')
                    if ('If-Unmodified-Since' in self.validator and response.headers.get('Last-Modified')
                            != self.validator['If-Unmodified-Since']):
                        self.fail('ZIP source Last-Modified changed between requests')
                return body, start, end, size, response.headers
        except (requests.RequestException, HttpRequestError) as error:
            if isinstance(error, HttpRequestError):
                self.source['request_failure'] = {'http_status': error.status, **error.details}
            raise ZipMemberReadError('ZIP range transfer failed: ' + type(error).__name__,
                data=self.last_data, source=self.source, media_type=self.media_type) from error

    def _preflight(self, tail, start):
        # Bound allocations before ZipFile reads its central directory. The
        # stdlib subsequently validates the directory and each selected member.
        stop = len(tail)
        while True:
            offset = tail.rfind(b'PK\x05\x06', 0, stop)
            if offset < 0:
                self.fail('ZIP end record is missing')
            if offset + 22 <= len(tail) and offset + 22 + struct.unpack_from('<H', tail, offset + 20)[0] == len(tail):
                break
            stop = offset
        disk, directory_disk, disk_count, count, size, directory = struct.unpack_from('<4H2I', tail, offset + 4)
        if disk or directory_disk or disk_count != count:
            self.fail('Split ZIP archives are unsupported')
        if count == 65535 or size == 0xffffffff or directory == 0xffffffff:
            self.fail('ZIP64 archives are unsupported')
        if count > self.limits.max_members or size > self.limits.max_directory_bytes:
            self.fail('ZIP directory exceeds entry or byte limits')
        if directory + size != start + offset:
            self.fail('ZIP directory location disagrees with its end record')
        self.directory_count = count
        # Like the retained archive reader, hide comments from ZipFile's end
        # scan so signatures inside a comment cannot masquerade as end records.
        self.length = start + offset + 22
        self.seek(directory)
        try:
            validate_zip_directory(self.read(size), expected_count=count, limits=self.limits)
        except ArchiveReadError as error:
            self.fail(str(error))

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        if whence not in (0, 1, 2):
            raise ValueError('Invalid ZIP seek')
        position = offset + (0 if whence == 0 else self.position if whence == 1 else self.length)
        if position < 0:
            raise ValueError('Negative ZIP seek')
        self.position = position
        return position

    def read(self, size=-1):
        end = self.length if size < 0 else min(self.length, self.position + size)
        if self.position >= end:
            return b''
        start = self.position
        for cached_start, data in self.cache:
            if cached_start <= start and end <= cached_start + len(data):
                self.position = end
                return data[start - cached_start:end - cached_start]
        if end - start > max(self.limits.max_directory_bytes, self.limits.max_member_bytes):
            self.fail('ZIP read exceeds the directory/member byte limit')
        data, actual_start, actual_end, _, _ = self._fetch(f'bytes={start}-{end - 1}', end - start)
        if (actual_start, actual_end) != (start, end - 1):
            self.fail('Publisher returned a different ZIP member range')
        self.cache.append((start, data))
        self.position = end
        return data


def read_zip_member(session, url, member_name, *, limits=MEMBER_LIMITS):
    """Return complete CRC-checked member bytes and archive/range provenance.

    No filesystem extraction, first-member assumption or full-download fallback.
    Publishers that refuse pinned ranges leave the caller's work retryable.
    """
    source = _RangeFile(session, url, limits)
    try:
        with source, ZipFile(source) as archive:
            entries = archive.infolist()
            if len(entries) != source.directory_count:
                source.fail('ZIP directory entry count disagrees with its end record')
            matches = [(i, entry) for i, entry in enumerate(entries) if entry.orig_filename == member_name]
            if len(matches) != 1:
                source.fail('ZIP must contain exactly one requested member')
            index, entry = matches[0]
            if entry.flag_bits & 1 or entry.compress_type not in (ZIP_STORED, ZIP_DEFLATED):
                source.fail('Encrypted or unsupported ZIP member')
            if (entry.file_size > min(limits.max_member_bytes, limits.max_total_bytes)
                    or entry.compress_size > limits.max_member_bytes):
                source.fail('ZIP member exceeds compressed or expanded byte limits')
            with archive.open(entry) as member:
                data = member.read(min(limits.max_member_bytes, limits.max_total_bytes) + 1)
            if len(data) != entry.file_size:
                source.fail('ZIP member expanded size differs from its directory')
            source.source.update(member=member_name, entry_index=index, member_bytes=len(data),
                                 compressed_bytes=entry.compress_size, crc32=f'{entry.CRC:08x}')
            return ZipMemberResponse(data=data, source=source.source)
    except (BadZipFile, EOFError, NotImplementedError, zlib.error) as error:
        raise ZipMemberReadError('Invalid ZIP member: ' + str(error),
            data=source.last_data, source=source.source, media_type=source.media_type) from error
