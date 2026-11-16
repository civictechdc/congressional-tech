"""Tests for single-record WARC/ARC HTTP response unwrapping and FileWrapper integrity."""
import base64
import gzip
import hashlib
import io
from pathlib import Path
import zlib

import pytest
from warcio.statusandheaders import StatusAndHeaders
from warcio.warcwriter import WARCWriter

from congress_api.parsers.file_wrapper import (
    ArchivedHttpPayload,
    regular_file,
    sniff_archive_envelope,
    sniff_payload_magic,
    unwrap_archived_http_response,
    unwrap_warc_or_arc_response,
)


def _make_warc_bytes(
    payload: bytes,
    *,
    uri: str = 'https://www.finance.senate.gov/imo/media/doc/report.pdf',
    status: str = '200 OK',
    headers: list[tuple[str, str]] | None = None,
    compress_envelope: bool = True,
    include_warcinfo: bool = False,
) -> bytes:
    buf = io.BytesIO()
    writer = WARCWriter(buf, gzip=compress_envelope)
    if include_warcinfo:
        info = writer.create_warcinfo_record('test-crawl.warc.gz', {'software': 'test'})
        writer.write_record(info)
    http_headers = StatusAndHeaders(
        status,
        headers or [('Content-Type', 'application/pdf; charset=binary')],
        protocol='HTTP/1.1',
    )
    record = writer.create_warc_record(
        uri,
        'response',
        payload=io.BytesIO(payload),
        http_headers=http_headers,
    )
    writer.write_record(record)
    return buf.getvalue()


def _make_arc_bytes(
    payload: bytes,
    *,
    uri: str = 'http://finance.senate.gov:80/hearings/statement.pdf',
    mime: str = 'application/pdf',
    status_line: bytes = b'HTTP/1.1 200 OK',
    extra_headers: bytes = b'Content-Type: application/pdf\r\n',
    include_filedesc: bool = True,
    gzip_mode: str = 'single',
) -> bytes:
    http_block = status_line + b'\r\n' + extra_headers + b'\r\n' + payload
    rec = (
        f'{uri} 198.51.100.4 20140612153045 {mime} {len(http_block)}\n'.encode('ascii')
        + http_block
        + b'\n'
    )
    preamble = b''
    if include_filedesc:
        desc_body = b'1 0 InternetArchive\nURL IP-address Archive-date Content-type Archive-length\n'
        preamble = (
            f'filedesc://IA-20140612.arc 0.0.0.0 20140612153000 text/plain {len(desc_body)}\n'.encode('ascii')
            + desc_body
            + b'\n'
        )
    if gzip_mode == 'none':
        return preamble + rec
    if gzip_mode == 'multi' and preamble:
        return gzip.compress(preamble) + gzip.compress(rec)
    return gzip.compress(preamble + rec)


def test_warc_and_warc_gzip_pdf_and_html_unwrapping():
    pdf_bytes = b'%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n'
    warc_gz = _make_warc_bytes(pdf_bytes, compress_envelope=True, include_warcinfo=True)
    assert sniff_archive_envelope(warc_gz) == 'warc+gzip'

    unwrapped = unwrap_archived_http_response(warc_gz)
    assert isinstance(unwrapped, ArchivedHttpPayload)
    assert unwrapped.record_format == 'warc+gzip'
    assert unwrapped.http_status == 200
    assert unwrapped.media_type == 'application/pdf'
    assert unwrapped.magic_format == 'pdf'
    assert unwrapped.payload == pdf_bytes
    assert unwrapped.target_uri == 'https://www.finance.senate.gov/imo/media/doc/report.pdf'
    expected_b32 = base64.b32encode(hashlib.sha1(pdf_bytes).digest()).decode('ascii')
    assert unwrapped.payload_digest == f'sha1:{expected_b32}'

    html_bytes = b'<!DOCTYPE html><html><head><title>Hearing</title></head><body><p>Testimony</p></body></html>'
    gz_inner = gzip.compress(html_bytes)
    warc_plain = _make_warc_bytes(
        gz_inner,
        uri='https://www.banking.senate.gov/hearings/uuid-page',
        headers=[('Content-Type', 'text/html; charset=UTF-8'), ('Content-Encoding', 'gzip')],
        compress_envelope=False,
    )
    assert sniff_archive_envelope(warc_plain) == 'warc'
    html_res = unwrap_warc_or_arc_response(warc_plain)
    assert html_res is not None
    assert html_res.record_format == 'warc'
    assert html_res.http_status == 200
    assert html_res.media_type == 'text/html'
    assert html_res.magic_format == 'html'
    assert html_res.payload == html_bytes


@pytest.mark.parametrize('gzip_mode,expected_fmt', [
    ('single', 'arc+gzip'),
    ('multi', 'arc+gzip'),
    ('none', 'arc'),
])
def test_arc_and_arc_gzip_unwrapping_with_filedesc_preamble(gzip_mode, expected_fmt):
    pdf_bytes = b'%PDF-1.5\n%legacy wayback capture\n%%EOF\n'
    arc_blob = _make_arc_bytes(pdf_bytes, include_filedesc=True, gzip_mode=gzip_mode)
    assert sniff_archive_envelope(arc_blob) == expected_fmt
    res = unwrap_archived_http_response(arc_blob)
    assert res is not None
    assert res.record_format == expected_fmt
    assert res.http_status == 200
    assert res.media_type == 'application/pdf'
    assert res.magic_format == 'pdf'
    assert res.payload == pdf_bytes
    assert res.archive_date == '20140612153045'


def test_deflate_and_chunked_inner_http_decoding():
    xml_bytes = b'<?xml version="1.0" encoding="UTF-8"?><committee-meeting/>'
    deflated = zlib.compress(xml_bytes)
    chunk = f'{len(deflated):x}\r\n'.encode('ascii') + deflated + b'\r\n0\r\n\r\n'
    warc_gz = _make_warc_bytes(
        chunk,
        uri='https://docs.house.gov/meetings/JU/JU00/20230510/115538/HHRG.xml',
        headers=[
            ('Content-Type', 'application/xml'),
            ('Transfer-Encoding', 'chunked'),
            ('Content-Encoding', 'deflate'),
        ],
    )
    res = unwrap_archived_http_response(warc_gz)
    assert res is not None
    assert res.magic_format == 'xml'
    assert res.payload == xml_bytes


def test_warc_digest_mismatch_truncation_and_size_bounds_refuse():
    pdf_bytes = b'%PDF-1.7\nvalid payload bytes\n%%EOF\n'
    plain_warc = _make_warc_bytes(pdf_bytes, compress_envelope=False)
    tampered = plain_warc.replace(b'valid payload bytes', b'tampered payload!! ')
    with pytest.raises(ValueError, match='WARC-Payload-Digest'):
        unwrap_archived_http_response(tampered)

    truncated = plain_warc.replace(
        b'WARC-Type: response\r\n',
        b'WARC-Type: response\r\nWARC-Truncated: length\r\n',
    )
    with pytest.raises(ValueError, match='truncated'):
        unwrap_archived_http_response(truncated)

    with pytest.raises(ValueError, match='max_bytes'):
        unwrap_archived_http_response(plain_warc, max_bytes=10)

    # Multi-response WARC must be refused by the single-record reader
    two_records = plain_warc + plain_warc
    with pytest.raises(ValueError, match='multiple HTTP response records'):
        unwrap_archived_http_response(two_records)


def test_non_envelopes_return_none_and_apple_rtfd_stays_intact():
    pdf = b'%PDF-1.7\nplain pdf\n%%EOF\n'
    assert sniff_archive_envelope(pdf) is None
    assert unwrap_archived_http_response(pdf) is None
    assert unwrap_archived_http_response(gzip.compress(pdf)) is None
    assert sniff_payload_magic(b'  \xef\xbb\xbf<!-- comment --><!doctype html><html>') == 'html'

    fixture = Path(__file__).parent / 'fixtures/capture-failures/wrapped-letter.rtfd.gz'
    raw_rtfd = gzip.decompress(fixture.read_bytes())
    assert unwrap_archived_http_response(raw_rtfd) is None
    wrapped = regular_file(raw_rtfd)
    assert wrapped.name and bytes(wrapped.data).startswith(b'%PDF-')
