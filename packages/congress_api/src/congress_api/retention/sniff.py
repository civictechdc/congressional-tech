"""One byte-only sniffer for raw intake and retained-body readings.

Ordinary bodies need one bounded prefix, bare PDFs a tail and sometimes one
bounded whole read. ZIP package metadata currently uses the bounded retained
archive reader. No URL, media type, capture decision or borrowed PDF check enters
this parser. The caller supplies immutable exact byte ranges.
"""

from functools import lru_cache
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import re
import zlib
from zipfile import BadZipFile

from lxml.html.defs import tags as HTML_TAGS

from congress_api.parsers.document_links import response_kind
from congress_api.retention.archive_members import ArchiveReadError, ZipLimits, inspect_office_zip
from congress_api.retention.image_tools import image_kind
from congress_api.retention.pdf_tools import BODY_LIMIT, PdfToolError, check_pdf, reader_versions

PREFIX_BYTES = 8192


@lru_cache(maxsize=1)
def sniff_version():
    """Pin the implementation and reused format/reader helpers, once per run."""
    root = Path(__file__).parents[1]
    digest = hashlib.sha256()
    for name in ('retention/sniff.py', 'retention/archive_members.py',
                 'retention/pdf_tools.py', 'retention/image_tools.py',
                 'parsers/document_links.py'):
        digest.update(name.encode() + b'\0' + (root / name).read_bytes())
    digest.update(json.dumps({'readers': reader_versions(), 'lxml': version('lxml')},
                             sort_keys=True, separators=(',', ':')).encode())
    digest.update((Path(__file__).parents[5] / 'uv.lock').read_bytes())
    return digest.hexdigest()


class SniffRefusal(ValueError):
    def __init__(self, error_type):
        self.error_type = error_type
        super().__init__(error_type)


class SniffReadError(OSError):
    """No reading can be written; the raw input remains on the work list."""


class SniffResourceError(RuntimeError):
    """The producer must retry or settle the input, rather than write a verdict."""

    def __init__(self, error_type):
        self.error_type = error_type
        super().__init__(error_type)


def _prefix(data):
    if data.startswith(b'\x1f\x8b'):
        try:
            decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
            result = decoder.decompress(data, PREFIX_BYTES)
            if not result and not decoder.eof:
                raise SniffRefusal('invalid_gzip')
            return result
        except zlib.error as exc:
            raise SniffRefusal('invalid_gzip') from exc
    return data


def _format(prefix):
    kind = response_kind(prefix, '')
    if kind in ('pdf', 'zip', 'html'):
        return kind
    if kind in ('legacy_office', 'rtf', 'file_wrapper'):
        return 'doc'
    if image_kind(prefix) or prefix.startswith((b'GIF87a', b'GIF89a', b'II\x2a\0', b'MM\0\x2a', b'BM')):
        return 'image'
    if prefix.startswith(b'RIFF') and prefix[8:12] == b'WEBP':
        return 'image'
    try:
        encoding = 'utf-16' if prefix.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
        # A range may end inside a character. Ignore only that final partial
        # sequence; malformed bytes elsewhere remain binary.
        import codecs
        text = codecs.getincrementaldecoder(encoding)().decode(prefix, final=False).lstrip()
    except UnicodeError:
        return 'other'
    if not prefix:
        return 'empty'
    if text.startswith('WARC/') or re.match(r'filedesc://\S+\s+\S+\s+\d{14}\s+', text):
        return 'warc'
    if text.startswith('WEBVTT') and (len(text) == 6 or text[6].isspace()):
        return 'vtt'
    if text.startswith('#EXTM3U'):
        return 'm3u8'
    if text.startswith(('{', '[')):
        return 'json'
    if text.startswith('<'):
        match = re.search(r'<([\w:.-]+)(?:\s|/?>)', text)
        if match and (match[1].split(':')[-1].lower() in HTML_TAGS):
            return 'html'
        if text.startswith('<?xml') or match:
            return 'xml'
    if any(ord(c) < 32 and c not in '\r\n\t\f' for c in text):
        return 'other'
    return 'text'


def read_sniff(read_range, *, stored_size, stored_gzip=False, pdf_reader=check_pdf,
               zip_limits=ZipLimits()):
    """Return facts or an input rejection; raise read/resource failures for retry.

    read_range(start, length) returns exactly the requested immutable bytes.
    Memory is O(prefix), O(reader limit) for a PDF needing the reader, and
    O(archive limit) for ZIP package metadata. No work grows per capture URL.
    """
    row = dict(parser='sniff', parser_version=sniff_version(), status='completed',
               error_type=None, format=None, intact=None, fields={})
    def read(start, length):
        try:
            data = read_range(start, length)
        except OSError as exc:
            raise SniffReadError(type(exc).__name__) from None
        if not isinstance(data, bytes) or len(data) != length:
            raise SniffReadError('short_range')
        return data
    try:
        if not isinstance(stored_size, int) or stored_size < 0:
            raise SniffRefusal('invalid_size')
        head = read(0, min(stored_size, PREFIX_BYTES)) if stored_size else b''
        if stored_gzip and not head.startswith(b'\x1f\x8b'):
            raise SniffRefusal('invalid_gzip')
        prefix = _prefix(head) if stored_gzip else head
        # Gzip originals (not just the archive's storage compression) may hold
        # WARC/ARC. Decompress their start only; PDFs still have no tail check.
        nested_gzip = prefix.startswith(b'\x1f\x8b')
        if nested_gzip:
            prefix = _prefix(prefix)
        row['format'] = _format(prefix)
        if row['format'] == 'pdf' and not stored_gzip and not nested_gzip:
            start = max(0, stored_size - PREFIX_BYTES)
            tail = head if start == 0 else read(start, stored_size - start)
            if b'%%EOF' in tail:
                row['intact'] = True
            elif stored_size > BODY_LIMIT:
                row.update(intact=False, error_type='pdf_reader_size_limit')
            else:
                data = head
                if start > len(head):
                    data += read(len(head), start - len(head))
                if stored_size > len(head):
                    data += tail[max(0, len(head) - start):]
                row['intact'] = pdf_reader(data)
                if type(row['intact']) is not bool:
                    raise SniffRefusal('invalid_reader_result')
        elif row['format'] == 'zip':
            if stored_size > zip_limits.max_archive_bytes:
                raise SniffRefusal('archive_size_limit')
            data = head + (read(len(head), stored_size - len(head))
                           if stored_size > len(head) else b'')
            if stored_gzip:
                decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
                data = decoder.decompress(data, zip_limits.max_archive_bytes + 1)
                if len(data) > zip_limits.max_archive_bytes:
                    raise SniffRefusal('archive_size_limit')
                if not decoder.eof:
                    raise SniffRefusal('invalid_gzip')
            if inspect_office_zip(data, limits=zip_limits):
                row['format'] = 'docx'
    except PdfToolError as exc:
        raise SniffResourceError(type(exc).__name__) from None
    except (ValueError, BadZipFile, zlib.error) as exc:
        code = getattr(exc, 'error_type', getattr(exc, 'status', type(exc).__name__))
        row.update(status='size_limit' if code.endswith('_limit') else 'error',
                   intact=None, error_type=code)
    return row
