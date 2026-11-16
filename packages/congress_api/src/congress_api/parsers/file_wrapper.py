"""Read Apple's serialized FileWrapper and single-record WARC/ARC HTTP envelopes.

The Apple FileWrapper reader covers only the observed v3 regular-file subset:
exact field names, block boundaries, and types must agree; unfamiliar layouts
are refused.

The web-archive envelope helpers unwrap single-record ``warc``, ``warc+gzip``,
``arc``, and ``arc+gzip`` HTTP response captures (Wayback, Common Crawl,
WebHarvest, Library of Congress), verifying ``WARC-Payload-Digest`` when
present, decoding inner HTTP ``Content-Encoding`` within explicit byte bounds,
and exposing the inner HTTP status, headers, MIME type, magic format, and raw
document bytes (``%PDF-`` / HTML / XML).
"""
import base64
from contextlib import ExitStack
from dataclasses import dataclass
import gzip
import hashlib
import io
import re
import struct
import zlib

DEFAULT_MAX_ARCHIVE_PAYLOAD_BYTES = 64 * 1024 * 1024

_GZIP_MAGIC = b'\x1f\x8b\x08'
_WARC_PREFIX_RE = re.compile(rb'^\s*WARC/(?:0\.\d+|1\.\d+)\r?\n')
_ARC_FILEDESC_RE = re.compile(rb'^filedesc://\S+\s+\S+\s+\d{14}\s+\S+\s+\d+\r?\n')
_ARC_RECORD_RE = re.compile(rb'^[a-zA-Z][a-zA-Z0-9+.-]*://\S+\s+\S+\s+\d{14}\s+\S+\s+\d+\r?\n')
_SHA1_BASE32_RE = re.compile(r'^(?:sha1:)?([A-Z2-7]{32})$', re.I)
_SHA1_HEX_RE = re.compile(r'^(?:sha1:)?([0-9a-fA-F]{40})$')
_HTML_LEAD_RE = re.compile(
    rb'^(?:\s|\xef\xbb\xbf|<!--[\s\S]{0,1024}?-->)*<(?:!doctype\s+html\b|html[\s>/])',
    re.I,
)
_XML_LEAD_RE = re.compile(rb'^(?:\s|\xef\xbb\xbf)*<\?xml[\s?]', re.I)


@dataclass(frozen=True)
class WrappedFile:
    name: str
    offset: int
    data: memoryview


@dataclass(frozen=True, slots=True)
class ArchivedHttpPayload:
    """Unwrapped HTTP response from a single-record WARC or ARC envelope."""

    record_format: str
    target_uri: str
    archive_date: str
    http_status: int
    headers: tuple[tuple[str, str], ...]
    media_type: str | None
    magic_format: str | None
    payload: bytes
    payload_digest: str | None = None
    record_id: str | None = None


def regular_file(data: bytes) -> WrappedFile:
    """Return a zero-copy, length-delimited payload; never search for PDF magic."""
    if data[:16] != b'rtfd' + struct.pack('<3I', 0, 3, 4):
        raise ValueError('Unsupported serialized file wrapper')
    cursor = 16

    def word():
        nonlocal cursor
        if cursor + 4 > len(data):
            raise ValueError('Truncated file wrapper')
        result = struct.unpack_from('<I', data, cursor)[0]
        cursor += 4
        return result

    for expected in (b'..', b'__@PreferredName@__', b'__@UTF8PreferredName@__', b'.'):
        size = word()
        if size != len(expected) or data[cursor:cursor + size] != expected:
            raise ValueError('Unsupported file wrapper fields')
        cursor += size
    sizes = [word() for _ in range(4)]
    if cursor + sum(sizes) != len(data):
        raise ValueError('File wrapper block lengths disagree')
    with ExitStack() as views:
        payloads = []
        for index, size in enumerate(sizes):
            end = cursor + size
            if size < 8 or word() != 1:
                raise ValueError('Unsupported file wrapper block')
            length = word()
            if length == 0x80000000:
                if index != 0 or size < 16:
                    raise ValueError('Unsupported padded file wrapper block')
                length, padding = word(), word()
                if cursor + padding + length != end or any(memoryview(data)[cursor:cursor + padding]):
                    raise ValueError('File wrapper padding disagrees')
                cursor += padding
            if cursor + length != end:
                raise ValueError('File wrapper payload length disagrees')
            payloads.append((cursor, views.enter_context(memoryview(data)[cursor:end])))
            cursor = end
        # The observed regular-file metadata describes exactly one '..' entry,
        # with a 16-byte attribute record. Only its permissions value varies.
        attributes = payloads[3][1]
        if (len(attributes) != 30
                or attributes[:18] != struct.pack('<2I', 1, 2) + b'..' + struct.pack('<2I', 16, 0)
                or attributes[22:] != struct.pack('<2I', 2, 1)):
            raise ValueError('Unsupported file wrapper attributes')
        if len(payloads[2][1]) > 16384:
            raise ValueError('File wrapper name exceeds limit')
        name = payloads[2][1].tobytes().decode('utf-8')
        if not name or len(name) > 4096 or '\x00' in name:
            raise ValueError('Invalid file wrapper name')
        return WrappedFile(name, payloads[0][0], payloads[0][1][:])


def _plain_archive_kind(prefix: bytes) -> str | None:
    if _WARC_PREFIX_RE.match(prefix):
        return 'warc'
    if _ARC_FILEDESC_RE.match(prefix) or _ARC_RECORD_RE.match(prefix):
        return 'arc'
    return None


def sniff_archive_envelope(data: bytes) -> str | None:
    """Identify ``'warc'``, ``'warc+gzip'``, ``'arc'``, ``'arc+gzip'``, or ``None``."""
    if not data:
        return None
    if data[:3] == _GZIP_MAGIC:
        try:
            dec = zlib.decompressobj(16 + zlib.MAX_WBITS)
            head = dec.decompress(data[:8192], 1024)
        except zlib.error:
            return None
        plain = _plain_archive_kind(head)
        return f'{plain}+gzip' if plain else None
    return _plain_archive_kind(data[:1024])


def sniff_payload_magic(payload: bytes) -> str | None:
    """Sniff inner HTTP payload magic (``'pdf'``, ``'html'``, ``'xml'``, ``'rtf'``, ``'zip'``, ``'gzip'``)."""
    if not payload:
        return None
    head = payload[:2048]
    stripped = head.lstrip(b'\xef\xbb\xbf \t\r\n')
    if stripped.startswith(b'%PDF-'):
        return 'pdf'
    if _HTML_LEAD_RE.match(head):
        return 'html'
    if _XML_LEAD_RE.match(head):
        return 'xml'
    if stripped.startswith(b'{\\rtf'):
        return 'rtf'
    if payload[:4] in (b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08'):
        return 'zip'
    if payload[:3] == _GZIP_MAGIC:
        return 'gzip'
    return None


def _gunzip_multi_member(data: bytes, max_bytes: int | None) -> bytes:
    """Decompress single- or multi-member gzip bytes within ``max_bytes``."""
    chunks: list[bytes] = []
    total = 0
    view = memoryview(data)
    pos = 0
    limit = None if max_bytes is None else max_bytes + 1
    while pos < len(view):
        if view[pos:pos + 3].tobytes() != _GZIP_MAGIC:
            raise ValueError('Corrupt gzip member header in archive envelope')
        dec = zlib.decompressobj(16 + zlib.MAX_WBITS)
        budget = 0 if limit is None else max(1, limit - total)
        piece = dec.decompress(view[pos:], budget)
        total += len(piece)
        if max_bytes is not None and total > max_bytes:
            raise ValueError('Archive envelope exceeds max_bytes')
        chunks.append(piece)
        if not dec.eof:
            tail = dec.flush()
            total += len(tail)
            if max_bytes is not None and total > max_bytes:
                raise ValueError('Archive envelope exceeds max_bytes')
            if tail:
                chunks.append(tail)
        if not dec.eof:
            raise ValueError('Truncated gzip member in archive envelope')
        consumed = len(view) - pos - len(dec.unused_data)
        if consumed <= 0:
            raise ValueError('Stalled gzip member in archive envelope')
        pos += consumed
        while pos < len(view) and view[pos] in (0x0D, 0x0A):
            pos += 1
    return b''.join(chunks)


def _read_bounded_stream(stream, max_bytes: int | None) -> bytes:
    if max_bytes is None:
        return stream.read()
    data = stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError('Archived HTTP payload exceeds max_bytes')
    return data


def _verify_warc_digest(payload: bytes, declared: str | None) -> str | None:
    if not declared:
        return None
    raw = declared.strip()
    m_b32 = _SHA1_BASE32_RE.match(raw)
    if m_b32:
        expected = m_b32.group(1).upper()
        actual = base64.b32encode(hashlib.sha1(payload).digest()).decode('ascii')
        if actual != expected:
            raise ValueError('WARC payload SHA-1 differs from WARC-Payload-Digest')
        return f'sha1:{expected}'
    m_hex = _SHA1_HEX_RE.match(raw)
    if m_hex:
        expected_hex = m_hex.group(1).lower()
        actual_hex = hashlib.sha1(payload).hexdigest()
        if actual_hex != expected_hex:
            raise ValueError('WARC payload SHA-1 differs from WARC-Payload-Digest')
        return f'sha1:{expected_hex}'
    raise ValueError(f'Unsupported WARC-Payload-Digest format: {raw}')


def _decode_http_content_encoding(payload: bytes, encoding: str, max_bytes: int | None) -> bytes:
    enc = encoding.strip().lower()
    if not enc or enc == 'identity':
        return payload
    if enc in ('gzip', 'x-gzip'):
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(payload)) as gz_stream:
                data = _read_bounded_stream(gz_stream, max_bytes)
        except (OSError, EOFError, zlib.error) as exc:
            raise ValueError('Invalid gzip HTTP Content-Encoding in archived response') from exc
        return data
    if enc == 'deflate':
        try:
            dec = zlib.decompressobj()
            data = dec.decompress(payload, 0 if max_bytes is None else max_bytes + 1)
            if not dec.eof:
                data += dec.flush()
        except zlib.error:
            try:
                dec_raw = zlib.decompressobj(-zlib.MAX_WBITS)
                data = dec_raw.decompress(payload, 0 if max_bytes is None else max_bytes + 1)
                if not dec_raw.eof:
                    data += dec_raw.flush()
            except zlib.error as exc:
                raise ValueError('Invalid deflate HTTP Content-Encoding in archived response') from exc
        if max_bytes is not None and len(data) > max_bytes:
            raise ValueError('Decoded HTTP payload exceeds max_bytes')
        return data
    raise ValueError(f'Unsupported HTTP Content-Encoding in archived response: {encoding}')


def _decode_http_chunked(payload: bytes, max_bytes: int | None) -> bytes:
    """Decode HTTP/1.1 chunked transfer-coding if present; reject malformed chunks."""
    out: list[bytes] = []
    total = 0
    pos = 0
    n = len(payload)
    while pos < n:
        line_end = payload.find(b'\r\n', pos)
        if line_end == -1:
            raise ValueError('Malformed HTTP chunked transfer-encoding')
        size_token = payload[pos:line_end].split(b';', 1)[0].strip()
        try:
            chunk_len = int(size_token, 16)
        except ValueError as exc:
            raise ValueError('Invalid HTTP chunk size in archived response') from exc
        pos = line_end + 2
        if chunk_len == 0:
            return b''.join(out)
        if pos + chunk_len + 2 > n or payload[pos + chunk_len:pos + chunk_len + 2] != b'\r\n':
            raise ValueError('Truncated HTTP chunk in archived response')
        total += chunk_len
        if max_bytes is not None and total > max_bytes:
            raise ValueError('Dechunked HTTP payload exceeds max_bytes')
        out.append(payload[pos:pos + chunk_len])
        pos += chunk_len + 2
    raise ValueError('Unterminated HTTP chunked body in archived response')


def _normalize_media_type(headers: tuple[tuple[str, str], ...], fallback: str | None = None) -> str | None:
    raw = next((v for k, v in headers if k.lower() == 'content-type'), None) or fallback
    if not raw:
        return None
    media = raw.split(';', 1)[0].strip().lower()
    return media or None


def unwrap_archived_http_response(
    data: bytes,
    *,
    max_bytes: int | None = DEFAULT_MAX_ARCHIVE_PAYLOAD_BYTES,
) -> ArchivedHttpPayload | None:
    """Unwrap a single-record ``warc``, ``warc+gzip``, ``arc``, or ``arc+gzip`` HTTP response.

    Returns ``None`` if ``data`` is not a WARC or ARC envelope. Raises ``ValueError`` if
    the envelope is malformed, truncated, fails ``WARC-Payload-Digest`` verification,
    contains zero or multiple HTTP ``response`` records, or decodes past ``max_bytes``.
    """
    envelope_kind = sniff_archive_envelope(data)
    if envelope_kind is None:
        return None
    if max_bytes is not None and max_bytes <= 0:
        raise ValueError('max_bytes must be positive')

    raw_archive = (
        _gunzip_multi_member(data, None if max_bytes is None else max_bytes + (4 * 1024 * 1024))
        if envelope_kind.endswith('+gzip')
        else data
    )

    from warcio.archiveiterator import ArchiveIterator

    responses: list[ArchivedHttpPayload] = []
    try:
        iterator = ArchiveIterator(io.BytesIO(raw_archive), arc2warc=False, check_digests=False)
        for record in iterator:
            rec_type = record.rec_type
            if rec_type in ('warcinfo', 'arc_header', 'request', 'metadata'):
                continue
            if rec_type != 'response':
                raise ValueError(f'Unsupported archive record type: {rec_type}')
            if record.rec_headers.get_header('WARC-Truncated'):
                raise ValueError('WARC record payload is truncated')
            http_headers = record.http_headers
            if http_headers is None or http_headers.get_statuscode() is None:
                raise ValueError('Archived response record has no HTTP status line')

            status_code = int(http_headers.get_statuscode())
            header_pairs = tuple((str(k), str(v)) for k, v in http_headers.headers)
            raw_entity = _read_bounded_stream(record.raw_stream, max_bytes)

            if record.format == 'warc':
                declared_digest = record.rec_headers.get_header('WARC-Payload-Digest')
                verified_digest = _verify_warc_digest(raw_entity, declared_digest)
                target_uri = record.rec_headers.get_header('WARC-Target-URI') or ''
                archive_date = record.rec_headers.get_header('WARC-Date') or ''
                record_id = record.rec_headers.get_header('WARC-Record-ID')
                arc_mime = None
            else:
                verified_digest = None
                target_uri = record.rec_headers.get_header('uri') or ''
                archive_date = record.rec_headers.get_header('archive-date') or ''
                record_id = None
                arc_mime = record.rec_headers.get_header('content-type')

            # If Transfer-Encoding: chunked was stored in raw_stream without warcio dechunking,
            # use warcio's content_stream when Transfer-Encoding is chunked and Content-Encoding is absent.
            transfer_enc = next(
                (v.strip().lower() for k, v in header_pairs if k.lower() == 'transfer-encoding'),
                '',
            )
            content_enc = next(
                (v.strip().lower() for k, v in header_pairs if k.lower() == 'content-encoding'),
                '',
            )
            entity_bytes = (
                _decode_http_chunked(raw_entity, max_bytes)
                if 'chunked' in transfer_enc
                else raw_entity
            )
            decoded_payload = _decode_http_content_encoding(entity_bytes, content_enc, max_bytes)

            media_type = _normalize_media_type(header_pairs, fallback=arc_mime)
            magic_format = sniff_payload_magic(decoded_payload)
            responses.append(
                ArchivedHttpPayload(
                    record_format=envelope_kind,
                    target_uri=target_uri,
                    archive_date=archive_date,
                    http_status=status_code,
                    headers=header_pairs,
                    media_type=media_type,
                    magic_format=magic_format,
                    payload=decoded_payload,
                    payload_digest=verified_digest,
                    record_id=record_id,
                )
            )
            if len(responses) > 1:
                raise ValueError('Archive envelope holds multiple HTTP response records, expected one')
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f'Unreadable {envelope_kind} archive envelope') from exc

    if len(responses) != 1:
        raise ValueError(f'Archive envelope holds {len(responses)} HTTP response records, expected one')
    return responses[0]


unwrap_warc_or_arc_response = unwrap_archived_http_response
