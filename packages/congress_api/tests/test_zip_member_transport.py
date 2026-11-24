"""Selected ZIP reads must not fetch neighboring PDFs or mix source versions."""

from collections import defaultdict
from io import BytesIO
import re
import struct
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest
import requests

from congress_api.retention.archive_members import ZipLimits
from congress_api.transport import http
from congress_api.transport.zip_member import read_zip_member, ZipMemberReadError

_REAL_PACE_REQUEST = http.pace_request


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
        if self.calls and headers['Range'] != f'bytes=-{22 + 65535}':
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


def test_cold_zip_redirect_to_error_206_html_retries_with_retry_after_and_succeeds(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(http, 'pace_request', _REAL_PACE_REQUEST)
    monkeypatch.setattr(http.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(http.time, 'sleep', lambda delay: now.__setitem__(0, now[0] + delay))
    monkeypatch.setattr(http, '_next', defaultdict(float))

    error_html = b'<html><body>The ZIP file you have requested is being generated</body></html>'
    starts = []

    def mutate(response, call, body):
        starts.append(now[0])
        if call in (1, 3):  # Fail on tail attempt AND mid-read small range attempt!
            redirect = requests.Response()
            redirect.status_code = 302
            redirect.url = URL
            redirect.headers['Retry-After'] = '15'
            response.status_code = 206
            response.url = 'https://www.govinfo.gov/error'
            response.headers['Content-Type'] = 'text/html; charset=utf-8'
            response.history = [redirect]
            return error_html * 60  # Larger than small local-header/member range budgets!
        return body

    session = RangeSession(mutate=mutate)
    result = read_zip_member(session, URL, MEMBER)
    assert result.data == XML
    # Both 302->/error bounces waited 15s via Retry-After before next range request.
    assert starts[1] - starts[0] == pytest.approx(15.0)
    assert starts[3] - starts[2] == pytest.approx(15.0)
    assert [r['final_url'] for r in result.source['requests'][:2]] == [
        'https://www.govinfo.gov/error', URL,
    ]
    assert 'https://www.govinfo.gov/error' in [r['final_url'] for r in result.source['requests']]
    assert all(response.raw.closed for response in session.responses)


def test_cold_zip_redirect_to_error_206_html_fails_with_last_bytes_when_exhausted():
    error_html = b'<html><body>Cold ZIP temporarily unavailable</body></html>'

    def mutate(response, call, body):
        response.status_code = 206
        response.url = 'https://www.govinfo.gov/error'
        response.headers['Content-Type'] = 'text/html'
        return error_html

    session = RangeSession(mutate=mutate)
    with pytest.raises(ZipMemberReadError, match='requested ZIP range URL with HTTP 206') as failure:
        read_zip_member(session, URL, MEMBER)
    assert failure.value.data == error_html
    assert failure.value.media_type == 'text/html'
    assert len(failure.value.source['requests']) == 4
    assert all(r['final_url'] == 'https://www.govinfo.gov/error' for r in failure.value.source['requests'])
    assert all(response.raw.closed for response in session.responses)


def test_mid_read_412_restarts_once_from_scratch_with_new_validator_and_retains_evidence():
    xml_v2 = b'<mets xmlns="http://www.loc.gov/METS/" OBJID="CHRG-119shrg64090" REV="2"/>'
    body_v1 = make_zip()
    # Build v2 archive with larger leading file so member offsets shift completely.
    buf_v2 = BytesIO()
    with ZipFile(buf_v2, 'w') as archive:
        archive.writestr('unrelated.txt', b'shifted payload' * 500, compress_type=ZIP_STORED)
        archive.writestr(MEMBER, xml_v2, compress_type=ZIP_DEFLATED)
        archive.writestr('large.pdf', b'pdf bytes' * 40000, compress_type=ZIP_STORED)
    body_v2 = buf_v2.getvalue()

    class VersionedSession:
        def __init__(self, *, persistent_412=False, fail_on_call=2):
            self.persistent_412 = persistent_412
            self.fail_on_call = fail_on_call
            self.calls = []
            self.responses = []
            self.restarted = False

        def request(self, method, url, *, headers, stream, **kwargs):
            self.calls.append(dict(headers))
            is_tail = headers['Range'] == f'bytes=-{22 + 65535}'
            if not self.restarted and not is_tail and len(self.calls) >= self.fail_on_call:
                # Subsequent range request after tail hits 412 with updated ETag.
                assert headers.get('If-Match') == '"source-v1"'
                self.restarted = True
                resp = requests.Response()
                resp.status_code, resp.url = 412, URL
                resp.headers.update({'Content-Type': 'text/plain', 'ETag': '"source-v2"'})
                body = b'Precondition Failed'
            elif self.persistent_412 and self.restarted and not is_tail:
                assert headers.get('If-Match') == '"source-v2"'
                resp = requests.Response()
                resp.status_code, resp.url = 412, URL
                resp.headers.update({'Content-Type': 'text/plain', 'ETag': '"source-v3"'})
                body = b'Still Precondition Failed'
            else:
                active_body, active_etag = (body_v2, '"source-v2"') if self.restarted else (body_v1, '"source-v1"')
                if self.restarted and not is_tail:
                    assert headers.get('If-Match') == '"source-v2"'
                match = re.fullmatch(r'bytes=(\d*)-(\d*)', headers['Range'])
                first, last = match.groups()
                start = int(first) if first else max(0, len(active_body) - int(last))
                end = int(last) if first else len(active_body) - 1
                resp = requests.Response()
                resp.status_code, resp.url = 206, URL
                resp.headers.update({
                    'Content-Range': f'bytes {start}-{end}/{len(active_body)}',
                    'Content-Type': 'application/zip', 'ETag': active_etag,
                    'Last-Modified': 'Fri, 23 Oct 2026 21:58:30 GMT',
                })
                body = active_body[start:end + 1]

            class ResponseBody(BytesIO):
                def release_conn(self):
                    self.close()

            resp.raw = ResponseBody(body)
            self.responses.append(resp)
            return resp

    for fail_on_call in (2, 4):  # Both early and mid-member 412s trigger a single full restart.
        session = VersionedSession(fail_on_call=fail_on_call)
        result = read_zip_member(session, URL, MEMBER)
        assert result.data == xml_v2
        assert result.source['etag'] == '"source-v2"'
        assert result.source['bytes'] == len(body_v2)
        assert all(r['http_status'] == 206 for r in result.source['requests'])
        assert len(result.source['prior_attempts']) == 1
        prior = result.source['prior_attempts'][0]
        assert prior['etag'] == '"source-v1"'
        assert prior['request_failure']['http_status'] == 412
        assert [r['http_status'] for r in prior['requests']] == [206] * (fail_on_call - 1) + [412]
        assert 'If-Match' not in session.calls[fail_on_call]  # Restarted tail did not send stale If-Match.
        assert all(response.raw.closed for response in session.responses)

    failing = VersionedSession(persistent_412=True)
    with pytest.raises(ZipMemberReadError, match='412') as failure:
        read_zip_member(failing, URL, MEMBER)
    assert failure.value.source['request_failure']['http_status'] == 412
    assert len(failure.value.source['prior_attempts']) == 1
    assert [r['http_status'] for r in failure.value.source['prior_attempts'][0]['requests']] == [206, 412]
    assert [r['http_status'] for r in failure.value.source['requests']] == [206, 412]
    assert all(response.raw.closed for response in failing.responses)
