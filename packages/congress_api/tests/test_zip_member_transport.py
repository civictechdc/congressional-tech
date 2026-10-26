"""Selected ZIP reads must not fetch neighboring PDFs or mix source versions."""

from io import BytesIO
import re
import struct
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest
import requests

from congress_api.retention.archive_members import ZipLimits
from congress_api.transport import http
from congress_api.transport.zip_member import read_zip_member, ZipMemberReadError


URL = 'https://www.govinfo.gov/content/pkg/CHRG-119shrg64090.zip'
MEMBER = 'CHRG-119shrg64090/dip.xml'
XML = b'<mets xmlns="http://www.loc.gov/METS/" OBJID="CHRG-119shrg64090"/>'


def make_zip(*, names=(MEMBER,), comment=b''):
    output = BytesIO()
    with ZipFile(output, 'w') as archive:
        archive.writestr('unrelated.txt', b'not the manifest', compress_type=ZIP_STORED)
        for name in names:
            archive.writestr(name, XML, compress_type=ZIP_DEFLATED)
        archive.writestr('large.pdf', b'pdf bytes' * 40000, compress_type=ZIP_STORED)
        archive.comment = comment
    return output.getvalue()


class RangeSession:
    def __init__(self, body=None, mutate=None):
        self.body = make_zip() if body is None else body
        self.mutate = mutate
        self.calls = []
        self.responses = []

    def request(self, method, url, *, headers, stream, **kwargs):
        assert method == 'GET' and url == URL and stream is True
        assert headers['Accept-Encoding'] == 'identity'
        if self.calls:
            assert headers.get('If-Match') == '"source-1"' or headers.get('If-Unmodified-Since') == 'Fri, 23 Oct 2026 21:58:30 GMT'
        self.calls.append(headers)
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', headers['Range'])
        first, last = match.groups()
        start = int(first) if first else max(0, len(self.body) - int(last))
        end = int(last) if first else len(self.body) - 1
        response = requests.Response()
        response.status_code, response.url = 206, URL
        response.headers.update({
            'Content-Range': f'bytes {start}-{end}/{len(self.body)}',
            'Content-Type': 'application/zip', 'ETag': '"source-1"',
            'Last-Modified': 'Fri, 23 Oct 2026 21:58:30 GMT',
        })
        body = self.body[start:end + 1]
        if self.mutate:
            body = self.mutate(response, len(self.calls), body)
        class ResponseBody(BytesIO):
            def release_conn(self):
                self.close()

        response.raw = ResponseBody(body)
        self.responses.append(response)
        return response


@pytest.fixture(autouse=True)
def no_waits(monkeypatch):
    monkeypatch.setattr(http, 'pace_request', lambda *args, **kwargs: None)


def test_selects_nonfirst_member_with_bounded_pinned_reads_and_provenance():
    session = RangeSession()
    result = read_zip_member(session, URL, MEMBER)
    assert result.data == XML
    assert result.source['member'] == MEMBER and result.source['entry_index'] == 1
    assert result.source['etag'] == '"source-1"'
    assert result.source['bytes'] == len(session.body)
    assert sum(r['bytes'] for r in result.source['requests']) < 70000 < len(session.body)
    assert all(r['http_status'] == 206 and r['sha256'] and r['final_url'] == URL
               for r in result.source['requests'])
    assert all(response.raw.closed for response in session.responses)


def test_comment_end_signatures_cannot_hide_the_real_directory():
    session = RangeSession(make_zip(comment=b'comment PK\x05\x06' + b'\x00' * 30))
    assert read_zip_member(session, URL, MEMBER).data == XML


@pytest.mark.parametrize('condition', [
    'html-200', 'ignored-range', 'redirect', 'encoding', 'truncated',
    'wrong-range', 'missing-range', 'etag-change', 'size-change', 'unversioned',
])
def test_refuses_invalid_http_or_changed_source_and_closes_responses(condition):
    html = b'<html><head><link rel="icon" href="/icon"></head><body>Page Not Found</body></html>'

    def mutate(response, call, body):
        if condition == 'html-200':
            response.status_code, response.url = 200, 'https://www.govinfo.gov/error'
            response.headers['Content-Type'] = 'text/html'
            return html
        if condition == 'ignored-range':
            response.status_code = 200
            return b'x' * 100000
        if condition == 'redirect':
            response.url = 'https://www.govinfo.gov/error'
        if condition == 'encoding':
            response.headers['Content-Encoding'] = 'gzip'
        if condition == 'truncated':
            return body[:-1]
        if condition == 'wrong-range':
            response.headers['Content-Range'] = f'bytes 0-{len(body) - 1}/{len(session.body)}'
        if condition == 'missing-range':
            del response.headers['Content-Range']
        if condition == 'etag-change' and call > 1:
            response.headers['ETag'] = '"changed-source"'
        if condition == 'size-change' and call > 1:
            response.headers['Content-Range'] = response.headers['Content-Range'].replace(
                '/' + str(len(session.body)), '/' + str(len(session.body) + 1))
        if condition == 'unversioned':
            del response.headers['ETag'], response.headers['Last-Modified']
        return body

    session = RangeSession(mutate=mutate)
    with pytest.raises(ZipMemberReadError) as failure:
        read_zip_member(session, URL, MEMBER)
    assert failure.value.source['requests']
    if condition == 'html-200':
        assert failure.value.data == html and failure.value.media_type == 'text/html'
    if condition == 'ignored-range':
        assert len(failure.value.data) == 65557
        assert failure.value.source['requests'][-1]['truncated']
    assert all(response.raw.closed for response in session.responses)


def test_last_modified_pins_sources_without_strong_etags():
    def mutate(response, call, body):
        response.headers['ETag'] = 'W/"weak"'
        return body

    session = RangeSession(mutate=mutate)
    assert read_zip_member(session, URL, MEMBER).data == XML
    assert all('If-Unmodified-Since' in headers for headers in session.calls[1:])


def test_changed_last_modified_is_rejected():
    def mutate(response, call, body):
        del response.headers['ETag']
        if call > 1:
            response.headers['Last-Modified'] = 'Sat, 24 Oct 2026 21:58:30 GMT'
        return body

    session = RangeSession(mutate=mutate)
    with pytest.raises(ZipMemberReadError, match='Last-Modified changed'):
        read_zip_member(session, URL, MEMBER)


@pytest.mark.parametrize('names', [(), (MEMBER, MEMBER)])
@pytest.mark.filterwarnings('ignore:Duplicate name:UserWarning')
def test_missing_or_duplicate_members_are_rejected(names):
    with pytest.raises(ZipMemberReadError, match='exactly one'):
        read_zip_member(RangeSession(make_zip(names=names)), URL, MEMBER)


def test_member_crc_is_checked():
    raw = bytearray(make_zip())
    with ZipFile(BytesIO(raw)) as archive:
        entry = archive.getinfo(MEMBER)
        offset = entry.header_offset
        names, extra = struct.unpack_from('<HH', raw, offset + 26)
        raw[offset + 30 + names + extra + entry.compress_size // 2] ^= 1
    with pytest.raises(ZipMemberReadError, match='Invalid ZIP member'):
        read_zip_member(RangeSession(bytes(raw)), URL, MEMBER)


@pytest.mark.parametrize(('limits', 'message'), [
    (ZipLimits(max_member_bytes=10), 'member exceeds'),
    (ZipLimits(max_directory_bytes=10), 'directory exceeds'),
    (ZipLimits(max_members=1), 'directory exceeds'),
    (ZipLimits(max_archive_bytes=100), 'source size limit'),
])
def test_limits_reject_before_unbounded_member_reads(limits, message):
    with pytest.raises(ZipMemberReadError, match=message):
        read_zip_member(RangeSession(), URL, MEMBER, limits=limits)


@pytest.mark.parametrize('defect', ['zip64', 'split', 'entry-count', 'directory-offset'])
def test_bad_directory_is_rejected_before_zipfile_allocations(monkeypatch, defect):
    from congress_api.transport import zip_member

    raw = bytearray(make_zip())
    end = raw.rfind(b'PK\x05\x06')
    if defect == 'zip64':
        struct.pack_into('<HH', raw, end + 8, 65535, 65535)
    elif defect == 'split':
        struct.pack_into('<H', raw, end + 4, 1)
    elif defect == 'entry-count':
        struct.pack_into('<HH', raw, end + 8, 1, 1)
    else:
        struct.pack_into('<I', raw, end + 16, 0)

    def unexpected_allocation(*args, **kwargs):
        pytest.fail('Invalid directory reached ZipFile allocation')

    monkeypatch.setattr(zip_member, 'ZipFile', unexpected_allocation)
    with pytest.raises(ZipMemberReadError):
        read_zip_member(RangeSession(bytes(raw)), URL, MEMBER)


def test_retrying_streamed_http_closes_rejected_attempt():
    def mutate(response, call, body):
        if call == 1:
            response.status_code = 503
        return body

    session = RangeSession(mutate=mutate)
    # This retry is still the first range and therefore has no source validator.
    original = session.request

    def request(*args, **kwargs):
        if len(session.calls) == 1:
            session.calls.clear()
            session.mutate = None
        return original(*args, **kwargs)

    session.request = request
    assert read_zip_member(session, URL, MEMBER).data == XML
    assert all(response.raw.closed for response in session.responses)
