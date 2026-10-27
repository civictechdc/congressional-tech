"""S1 byte fixtures, committed before the shared sniffer implementation."""

import gzip
from io import BytesIO
from zipfile import ZipFile

import pytest


def office(entries):
    out = BytesIO()
    with ZipFile(out, 'w') as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return out.getvalue()


class Ranges:
    def __init__(self, data):
        self.data, self.calls = data, []

    def __call__(self, start, length):
        assert start >= 0 and length > 0
        self.calls.append((start, length))
        return self.data[start:start + length]


@pytest.mark.parametrize(('body', 'expected'), [
    (b'%PDF-1.7\n%%EOF', 'pdf'),
    (office([('a.xml', b'<a/>')]), 'zip'),
    (b'<?xml version="1.0"?><meeting/>', 'xml'),
    ('<?xml version="1.0"?><meeting/>'.encode('utf-16'), 'xml'),
    (b'<meeting><name>Committee</name></meeting>', 'xml'),
    (b'<!DOCTYPE html><html><body>Hi</body></html>', 'html'),
    (b'<div><a href="file.pdf">File</a></div>', 'html'),
    (b'{"a":1}', 'json'), (b'[1,2]', 'json'),
    (b'WEBVTT\n\n00:00.000 --> 00:01.000\nHello', 'vtt'),
    (b'#EXTM3U\n#EXT-X-VERSION:3', 'm3u8'),
    (office([('document.xml', b'<x/>'), ('[Content_Types].xml', b'<Types/>')]), 'docx'),
    (office([('mimetype', b'application/vnd.oasis.opendocument.text'), ('content.xml', b'<x/>')]), 'docx'),
    (b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1more', 'doc'),
    (b'{\\rtf1 example}', 'doc'),
    (b'Plain substantive UTF-8 text.', 'text'),
    ('The committee met in Montréal.'.encode(), 'text'),
    (b'\x89PNG\r\n\x1a\nrest', 'image'),
    (b'GIF89arest', 'image'), (b'II\x2a\x00rest', 'image'),
    (b'WARC/1.0\r\nWARC-Type: response\r\n', 'warc'),
    (b'filedesc://archive.arc 0.0.0.0 20260101000000 text/plain 100\n', 'warc'),
    (b'\x00\x01\xffbinary', 'other'), (b'', 'empty'),
])
def test_format_depends_on_bytes_not_a_filename_or_media_type(body, expected):
    from congress_api.retention.sniff import read_sniff

    source = Ranges(body)
    row = read_sniff(source, stored_size=len(body))
    assert row['status'] == 'completed'
    assert row['format'] == expected
    assert row['intact'] == (True if expected == 'pdf' else None)
    assert len(row['parser_version']) == 64


def test_office_names_must_be_exact_and_odf_mimetype_must_name_the_type():
    from congress_api.retention.sniff import read_sniff

    for data in (office([('nested/[Content_Types].xml', b'<Types/>')]),
                 office([('mimetype', b'text/plain')])):
        assert read_sniff(Ranges(data), stored_size=len(data))['format'] == 'zip'


def test_pdf_tail_and_bounded_reader_are_separate_from_borrowed_checks():
    from congress_api.retention.sniff import read_sniff
    from congress_api.retention.pdf_tools import BODY_LIMIT

    def forbidden(data):
        pytest.fail('An end marker or an over-limit PDF must not open the reader')
    body = b'%PDF-1.7\n' + b'x' * 20000 + b'%%EOF' + b'trailing bytes'
    source = Ranges(body)
    row = read_sniff(source, stored_size=len(body), pdf_reader=forbidden)
    assert row['intact'] is True
    assert source.calls == [(0, 8192), (len(body) - 8192, 8192)]
    body = b'%PDF-1.7\n' + b'x' * BODY_LIMIT
    row = read_sniff(Ranges(body), stored_size=len(body), pdf_reader=forbidden)
    assert row['intact'] is False and row['error_type'] == 'pdf_reader_size_limit'
    for accepted in (False, True):
        seen = []
        def reader(data):
            seen.append(data)
            return accepted
        body = b'%PDF-1.7\nno end marker'
        row = read_sniff(Ranges(body), stored_size=len(body), pdf_reader=reader)
        assert row['intact'] is accepted and seen == [body]


def test_gzip_prefixes_do_not_turn_an_unchecked_pdf_into_a_damaged_one():
    from congress_api.retention.sniff import read_sniff

    def forbidden(data):
        pytest.fail('Older gzip PDFs defer whole reads to B13')
    for plain in (b'%PDF-1.7\ncut off', b'%PDF-1.7\n%%EOF'):
        body = gzip.compress(plain)
        source = Ranges(body)
        row = read_sniff(source, stored_size=len(body), stored_gzip=True, pdf_reader=forbidden)
        assert row['format'] == 'pdf' and row['intact'] is None
        assert len(source.calls) == 1
    for prefix in (b'WARC/1.0\r\n', b'filedesc://archive.arc 0.0.0.0 20260101000000 text/plain 100\n'):
        body = gzip.compress(gzip.compress(prefix + b'x' * 100000))
        row = read_sniff(Ranges(body), stored_size=len(body), stored_gzip=True)
        assert row['format'] == 'warc' and row['intact'] is None


def test_reader_or_storage_failure_is_not_a_completed_damage_verdict():
    from congress_api.retention.sniff import read_sniff
    from congress_api.retention.pdf_tools import PdfToolError

    def unavailable(data):
        raise PdfToolError('private input must never appear in a reading')
    body = b'%PDF-1.7\nno end'
    row = read_sniff(Ranges(body), stored_size=len(body), pdf_reader=unavailable)
    assert row['status'] == 'failed' and row['intact'] is None
    assert row['error_type'] == 'PdfToolError'
    assert 'private' not in str(row)
    row = read_sniff(lambda start, length: b'', stored_size=100)
    assert row['status'] == 'failed' and row['error_type'] == 'short_range'


def test_corrupt_or_oversized_zip_is_a_reported_refusal_not_generic_zip_success():
    from congress_api.retention.sniff import read_sniff
    from congress_api.retention.archive_members import ZipLimits

    for body, limits, expected in (
        (b'PK\x03\x04broken', ZipLimits(), 'corrupt_archive'),
        (office([('a', b'x' * 100)]), ZipLimits(max_archive_bytes=80), 'archive_size_limit'),
    ):
        row = read_sniff(Ranges(body), stored_size=len(body), zip_limits=limits)
        assert row['status'] == 'failed' and row['error_type'] == expected


def test_compressed_office_is_bounded_and_content_identified():
    from congress_api.retention.sniff import read_sniff

    plain = office([('[Content_Types].xml', b'<Types/>')])
    body = gzip.compress(plain)
    row = read_sniff(Ranges(body), stored_size=len(body), stored_gzip=True)
    assert row['status'] == 'completed' and row['format'] == 'docx'


def test_real_bounded_pdf_reader_opens_structure_without_an_end_marker():
    from pypdf import PdfWriter
    from congress_api.retention.sniff import read_sniff

    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(output)
    data = output.getvalue().replace(b'%%EOF', b'')
    for body in (data, b'\x00\xff' + data):
        row = read_sniff(Ranges(body), stored_size=len(body))
        assert row['status'] == 'completed' and row['intact'] is True
    row = read_sniff(Ranges(data[:100]), stored_size=100)
    assert row['status'] == 'completed' and row['intact'] is False
