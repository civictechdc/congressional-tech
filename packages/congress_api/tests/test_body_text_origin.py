"""Body-text reads from the archive origin: one pinned ranged GET per body, checked by its SHA-256.

The fake origin answers as the raw bucket's public custom domain does (measured 2026-11-08): a
strong MD5 ETag, If-Match refused with 412, Range answered 206 with Content-Range over the stored
bytes, and a gzip-stored object returned as stored with Content-Encoding gzip when the client
accepts gzip. The live test reads the edge configuration's integrity-probe body and skips offline.
"""
import hashlib
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from body_text_fixtures import HTML, PAGE_ONE, PAGE_TWO, XML, committed, lake, two_page_pdf
from congress_api.lake import body_text


class Origin:
    """A local origin over a raw root; records each request's path and headers.

    ``quirks`` names paths it answers unlike the bucket: `weak` (a weak ETag) or `no_range` (200, the whole object).
    """

    def __init__(self, root):
        self.root, self.requests, self.quirks = root, [], {}
        origin = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                origin.requests.append((self.path, dict(self.headers)))
                path = origin.root / self.path.lstrip('/')
                if not path.is_file():
                    return self.reply(404, b'')
                data = path.read_bytes()
                quirk = origin.quirks.get(self.path)
                etag = ('W/' if quirk == 'weak' else '') + '"' + hashlib.md5(data).hexdigest() + '"'
                if self.headers.get('If-Match') not in (None, etag):
                    return self.reply(412, b'precondition failed')
                headers = {'ETag': etag, 'Accept-Ranges': 'bytes'}
                if data[:2] == b'\x1f\x8b' and 'gzip' in self.headers.get('Accept-Encoding', ''):
                    headers['Content-Encoding'] = 'gzip'
                match = re.fullmatch(r'bytes=(\d+)-(\d+)', self.headers.get('Range', ''))
                if match is None or quirk == 'no_range':
                    return self.reply(200, data, headers)
                start, end = map(int, match.groups())
                headers['Content-Range'] = f'bytes {start}-{end}/{len(data)}'
                return self.reply(206, data[start:end + 1], headers)

            def reply(self, status, body, headers=()):
                self.send_response(status)
                for name, value in dict(headers).items():
                    self.send_header(name, value)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


def set_capture(captures, digest, **values):
    """Overwrite one body's captured pins in the captures file."""
    table = pq.read_table(captures)
    rows = table.to_pylist()
    for row in rows:
        if row['sha256'] == digest:
            row.update(values)
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), captures)


@pytest.mark.loopback
def test_origin_reads_are_pinned_ranged_gets_checked_by_the_body_hash(tmp_path):
    bodies = dict(pdf=(two_page_pdf(), 'pdf'), html=(HTML, 'html'), forged=(XML, 'xml'),
                  replaced=(XML.replace(b'Oversight', b'Hearing'), 'xml'), unpinned=(b'<a>unpinned</a>', 'xml'),
                  sizeless=(b'<a>sizeless</a>', 'xml'), huge=(XML.replace(b'met', b'adjourned'), 'xml'))
    args, names = lake(tmp_path, bodies, gzip_stored={'html'})
    digests = {name: digest for digest, name in names.items()}
    raw, captures = args.pop('local_root'), args['captures']
    key = lambda name: next(raw.glob(f'bodies/sha256/*/{digests[name].hex()}*'))
    # Same size and MD5 pins as the bytes served, but not the body the key names: only its hash can tell.
    forged = b'<?xml version="1.0"?><hearing><para>Not this body.</para></hearing>'
    key('forged').write_bytes(forged)
    set_capture(captures, digests['forged'], stored_bytes=len(forged), stored_md5=hashlib.md5(forged).digest())
    key('replaced').write_bytes(b'<x>changed after capture</x>')  # its captured MD5 no longer matches: 412
    set_capture(captures, digests['unpinned'], stored_md5=None)  # most real captures: pinned to the served ETag
    set_capture(captures, digests['sizeless'], stored_bytes=None, stored_md5=None)
    set_capture(captures, digests['huge'], stored_bytes=body_text.MAX_STORED_BYTES + 1)
    with Origin(raw) as origin:
        report = body_text.run(**args, origin=origin.url, work=tmp_path / 'run', execute=True)
    [batch] = report['batches']
    assert report['status'] == 'pending' and (batch['pending_reads'], batch['missing_pins']) == (2, 1)
    # The forged body fails its hash; the replaced one's If-Match is refused (412).
    assert batch['pending_read_reasons'] == report['pending_read_reasons'] == dict(
        decoded_sha_mismatch=1, raw_range_ClientError=1)
    text = {names[bytes.fromhex(r['body'])]: r['text'] for r in committed(args, tmp_path / 't', 'body_text', 'text')}
    assert text.pop('unpinned').strip() == 'unpinned'
    assert text == dict(pdf=PAGE_ONE + '\n' + PAGE_TWO, html='STATEMENT OF THE WITNESS\n\n    Mr. Chairman, thank you.\n')
    rows = {names[bytes.fromhex(r['body'])]: (r['status'], r['error_type'])
            for r in committed(args, tmp_path / 'r', 'readings', 'status,error_type')}
    assert rows == dict(pdf=('completed', None), html=('completed', None), unpinned=('completed', None),
                        huge=('size_limit', 'stored_size_limit'))
    fetched = {}
    for path, headers in origin.requests:
        fetched.setdefault(path, []).append((headers.get('If-Match'), headers['Range']))
        assert headers['User-Agent'] == 'ct-body-text/1' and headers['Accept-Encoding'] == 'gzip'
    # One GET per MD5-pinned body under the bound, If-Match on the captured MD5; the unpinned body's
    # read is If-Match on the ETag its one-byte GET answered; none for the oversize or sizeless body.
    md5 = lambda name: '"' + hashlib.md5(key(name).read_bytes()).hexdigest() + '"'
    captured = {r['sha256']: r for r in pq.read_table(captures).to_pylist()}
    assert fetched == {'/' + str(key(n).relative_to(raw)): [('"' + captured[digests[n]]['stored_md5'].hex() + '"',
                                                             f'bytes=0-{captured[digests[n]]["stored_bytes"] - 1}')]
                       for n in ('pdf', 'html', 'forged', 'replaced')} | {
        '/' + str(key('unpinned').relative_to(raw)): [(None, 'bytes=0-0'),
            (md5('unpinned'), f'bytes=0-{len(key("unpinned").read_bytes()) - 1}')]}
    assert not list((tmp_path / 'run').glob('batch-*/stage/bodies'))  # range caches leave with the stage
    assert not list((tmp_path / 'run').glob('batch-*/stage/body-text.parquet'))  # and the committed text copy


@pytest.mark.loopback
def test_an_md5_less_read_refuses_an_origin_answer_it_cannot_pin(tmp_path):
    bodies = {name: (b'<a>' + name.encode() + b'</a>', 'xml') for name in ('weak', 'whole', 'resized')}
    args, names = lake(tmp_path, bodies | dict(gzipped=(HTML, 'html')), gzip_stored={'gzipped'})
    digests = {name: digest for digest, name in names.items()}
    raw, captures = args.pop('local_root'), args['captures']
    path = lambda name: '/' + str(next(raw.glob(f'bodies/sha256/*/{digests[name].hex()}*')).relative_to(raw))
    for name in digests:
        set_capture(captures, digests[name], stored_md5=None)
    set_capture(captures, digests['resized'], stored_bytes=len(bodies['resized'][0]) + 1)
    with Origin(raw) as origin:
        origin.quirks = {path('weak'): 'weak', path('whole'): 'no_range'}
        report = body_text.run(**args, origin=origin.url, work=tmp_path / 'run', execute=True)
    # A weak ETag, a 200 to the ranged probe and a total unlike the captured size each stop at the
    # one-byte GET; the gzip-stored body reads once more under the ETag of its stored bytes.
    assert report['status'] == 'pending' and report['pending_read_reasons'] == dict(changed_input=3)
    stored = (raw / path('gzipped')[1:]).read_bytes()
    assert stored[:2] == b'\x1f\x8b'
    fetched = {}
    for requested, headers in origin.requests:
        fetched.setdefault(requested, []).append((headers.get('If-Match'), headers['Range']))
    assert fetched == {path(name): [(None, 'bytes=0-0')] for name in bodies} | {path('gzipped'): [
        (None, 'bytes=0-0'), ('"' + hashlib.md5(stored).hexdigest() + '"', f'bytes=0-{len(stored) - 1}')]}
    text = {names[bytes.fromhex(r['body'])]: r['text'] for r in committed(args, tmp_path / 't', 'body_text', 'text')}
    assert text == dict(gzipped='STATEMENT OF THE WITNESS\n\n    Mr. Chairman, thank you.\n')


@pytest.mark.network
def test_a_real_small_body_reads_from_the_public_origin(tmp_path, monkeypatch):
    """The edge's integrity-probe body (19,492 bytes, gzip-stored as 5,597): its decoded SHA-256 is
    the key the probe names, so the check does not trust the origin's own MD5 or length."""
    from congress_api.retention.r2_edge_rules import body_integrity_configuration
    probe = body_integrity_configuration()['integrity_probe']
    digest = probe['decoded_sha256']
    monkeypatch.setenv('DOCSPEC_PARSER_IO_MARKER', str(tmp_path / 'io-marker'))
    (tmp_path / 'texts').mkdir()
    request = dict(body_sha=digest, parser='html_text', stored_bytes=5597, texts=str(tmp_path / 'texts'),
                   strategy='congress_api.parsers.body_text:native_only',
                   page_deadline_seconds=60, cache=str(tmp_path / 'cache'),
                   remote=dict(origin=body_text.ORIGIN, bucket='congressional-tech-raw', key=probe['path'][1:],
                               md5='e51a3b5300e3f74fefdff6f9058f2a88'))
    try:
        data = body_text._read_decoded(request)
    except (OSError, RuntimeError) as error:  # no route or DNS; the offline lanes' tripwire is a RuntimeError
        if isinstance(error, RuntimeError) and 'Network access is disabled' not in str(error):
            raise
        pytest.skip(f'archive origin unreachable: {error}')
        return
    assert hashlib.sha256(data).hexdigest() == digest and len(data) == probe['decoded_bytes']
    value = body_text.parse_payload(json.dumps(request))
    assert value['row']['status'] == 'completed' and value['text']['bytes'] > 0
