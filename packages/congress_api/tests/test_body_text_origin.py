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


class PagedListClient:
    """Minimal S3 client answering paged list_objects_v2 over in-memory metadata."""

    def __init__(self, entries, *, page_size=2):
        self.entries = sorted(entries, key=lambda item: item['Key'])
        self.page_size = page_size
        self.list_calls = []

    def get_paginator(self, operation):
        assert operation == 'list_objects_v2'
        client = self

        class Paginator:
            def paginate(self, *, Bucket, Prefix):
                matched = [e for e in client.entries if e['Key'].startswith(Prefix)]
                for start in range(0, max(1, len(matched)), client.page_size):
                    client.list_calls.append((Bucket, Prefix, start))
                    yield {'Contents': matched[start:start + client.page_size]}

        return Paginator()


def test_write_body_listing_pages_list_objects_v2_and_validates_keys(tmp_path):
    entries = [
        {'Key': f'bodies/sha256/{i:02x}/' + (f'{i:02x}' * 32) + '.gz', 'Size': 100 + i, 'ETag': f'"{i:032x}"'}
        for i in range(5)
    ]
    client = PagedListClient(entries, page_size=2)
    out = tmp_path / 'body-listing.parquet'
    written = body_text.write_body_listing(client, bucket='congressional-tech-raw', out=out)
    assert written == {'path': out.resolve(), 'rows': 5}
    assert len(client.list_calls) == 3  # ceil(5 / 2) LIST calls, zero GET/HEAD calls
    rows = pq.read_table(out).to_pylist()
    assert rows == [{'key': e['Key'], 'size': e['Size'], 'etag': e['ETag']} for e in entries]


@pytest.mark.loopback
def test_body_listing_pins_md5_less_reads_with_zero_probe_gets_and_preserves_refusals(tmp_path, monkeypatch, capsys):
    from congress_api.cli import body_text as command

    bodies = dict(
        md5_pinned=(two_page_pdf(), 'pdf'),
        unpinned_plain=(b'<doc>plain listed</doc>', 'xml'),
        unpinned_gzip=(HTML, 'html'),
        weak=(b'<doc>weak</doc>', 'xml'),
        resized=(b'<doc>resized</doc>', 'xml'),
        unlisted=(b'<doc>unlisted</doc>', 'xml'),
        md5_conflict=(b'<doc>md5_conflict</doc>', 'xml'),
        whole=(b'<doc>whole</doc>', 'xml'),
        replaced_after_list=(b'<doc>before</doc>', 'xml'),
    )
    args, names = lake(tmp_path, bodies, gzip_stored={'unpinned_gzip'})
    digests = {name: digest for digest, name in names.items()}
    raw, captures = args.pop('local_root'), args['captures']
    file_of = lambda name: next(raw.glob(f'bodies/sha256/*/{digests[name].hex()}*'))
    rel_key = lambda name: file_of(name).relative_to(raw).as_posix()

    for name in ('unpinned_plain', 'unpinned_gzip', 'weak', 'resized', 'unlisted', 'whole', 'replaced_after_list'):
        set_capture(captures, digests[name], stored_md5=None)

    listing_rows = []
    for name in bodies:
        if name == 'unlisted':
            continue
        stored = file_of(name).read_bytes()
        etag = '"' + hashlib.md5(stored).hexdigest() + '"'
        size = len(stored)
        if name == 'weak':
            etag = 'W/' + etag
        elif name == 'resized':
            size += 1
        elif name == 'md5_conflict':
            etag = '"' + ('0' * 32) + '"'
        listing_rows.append({'key': rel_key(name), 'size': size, 'etag': etag})

    listing_path = tmp_path / 'body-listing.parquet'
    listing_schema = pa.schema([('key', pa.string()), ('size', pa.int64()), ('etag', pa.string())])
    pq.write_table(pa.Table.from_pylist(listing_rows, schema=listing_schema), listing_path)

    # Mutate replaced_after_list on origin AFTER listing was captured so If-Match fails with 412.
    file_of('replaced_after_list').write_bytes(b'<doc>changed after listing</doc>')

    def forbid_probe(*_args, **_kwargs):
        raise AssertionError('_observed_etag must not run when body_listing pins remote reads')

    monkeypatch.setattr(body_text, '_observed_etag', forbid_probe)

    with Origin(raw) as origin:
        origin.quirks = {'/' + rel_key('whole'): 'no_range'}
        report = body_text.run(**args, origin=origin.url, body_listing=listing_path, work=tmp_path / 'run', execute=True)

    assert report['status'] == 'pending'
    # 4 refused before any GET (weak, resized, md5_conflict as changed_input; unlisted as missing_remote) + 1 no_range + 1 412.
    assert report['pending_read_reasons'] == dict(
        changed_input=3,
        missing_remote=1,
        raw_range_ClientError=1,
        raw_range_ValueError=1,
    )

    fetched = {}
    for requested, headers in origin.requests:
        fetched.setdefault(requested, []).append((headers.get('If-Match'), headers['Range']))
    # Zero 'bytes=0-0' probes anywhere; weak/resized/unlisted/md5_conflict made zero GETs;
    # every fetched body made exactly 1 ranged GET with If-Match!
    assert all(rng != 'bytes=0-0' for calls in fetched.values() for _, rng in calls)
    assert set(fetched) == {'/' + rel_key(n) for n in ('md5_pinned', 'unpinned_plain', 'unpinned_gzip', 'whole', 'replaced_after_list')}
    assert all(len(calls) == 1 and calls[0][0] is not None for calls in fetched.values())

    text = {names[bytes.fromhex(r['body'])]: r['text'] for r in committed(args, tmp_path / 't', 'body_text', 'text')}
    assert text == dict(
        md5_pinned=PAGE_ONE + '\n' + PAGE_TWO,
        unpinned_plain='plain listed',
        unpinned_gzip='STATEMENT OF THE WITNESS\n\n    Mr. Chairman, thank you.\n',
    )

    # Duplicate keys in body_listing or combining local_root + body_listing must refuse cleanly.
    dup_listing = tmp_path / 'dup-listing.parquet'
    pq.write_table(pa.Table.from_pylist([listing_rows[0], listing_rows[0]], schema=listing_schema), dup_listing)
    with pytest.raises(ValueError, match='body_listing'):
        body_text.plan(captures=captures, engine=args['engine'], work=tmp_path / 'dup-plan',
                       decided_at=args['decided_at'], body_listing=dup_listing)
    with pytest.raises(ValueError, match='body_listing'):
        body_text.run(**args, local_root=raw, body_listing=listing_path, work=tmp_path / 'bad-local', execute=False)

    # CLI spec accepts body_listing with origin and rejects body_listing with local_root.
    spec_path = tmp_path / 'cli-spec.json'
    spec_path.write_text(json.dumps(dict(
        captures=str(captures), work=str(tmp_path / 'cli-plan'), decided_at=args['decided_at'],
        catalog_root=str(args['catalog_root']), tables=args['tables'],
        origin=body_text.ORIGIN, body_listing=str(listing_path),
    )))
    assert command.main(['--spec', str(spec_path), '--plan']) == 0
    capsys.readouterr()
    spec_path.write_text(json.dumps(dict(
        captures=str(captures), work=str(tmp_path / 'cli-bad'), decided_at=args['decided_at'],
        catalog_root=str(args['catalog_root']), tables=args['tables'],
        local_root=str(raw), body_listing=str(listing_path),
    )))
    with pytest.raises(SystemExit):
        command.main(['--spec', str(spec_path), '--plan'])


def test_cli_write_body_listing_streams_atomically_and_shares_listing_schema(tmp_path, capsys):
    """[WARNING-1] CLI --write-body-listing streams pages via LISTING_SCHEMA and leaves no partial file on failure."""
    from pathlib import Path
    from congress_api.cli import body_text as command

    assert isinstance(body_text.LISTING_SCHEMA, pa.Schema)
    entries = [
        {'Key': f'bodies/sha256/{i:02x}/' + (f'{i:02x}' * 32) + '.gz', 'Size': 200 + i, 'ETag': f'"{i:032x}"'}
        for i in range(4)
    ]
    client = PagedListClient(entries, page_size=2)
    out = tmp_path / 'cli-listing.parquet'
    assert command.main(['--write-body-listing', str(out)], r2_client=client) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['rows'] == 4 and Path(payload['path']) == out.resolve()
    assert pq.read_schema(out).equals(body_text.LISTING_SCHEMA)

    bad_entries = [*entries, {'Key': 'bodies/sha256/../bad-key', 'Size': 10, 'ETag': '"00"'}]
    bad_out = tmp_path / 'bad-listing.parquet'
    with pytest.raises(ValueError):
        body_text.write_body_listing(PagedListClient(bad_entries, page_size=2), out=bad_out)
    assert not bad_out.exists()
    assert list(tmp_path.glob('*.tmp')) == [] and list(tmp_path.glob('.*.tmp')) == []


@pytest.mark.loopback
def test_body_listing_prefers_listed_fallback_copy_refuses_sizeless_and_cleans_conflict_work_list(tmp_path, monkeypatch):
    """[WARNING-1] Multi-copy prefers listed .gz over unlisted '', sizeless stays missing_pins, conflict leaves no work-list."""
    import gzip

    bodies = dict(
        multicopy=(HTML, 'html'),
        sizeless=(b'<doc>sizeless</doc>', 'xml'),
    )
    args, names = lake(tmp_path, bodies, gzip_stored={'multicopy'})
    digests = {name: digest for digest, name in names.items()}
    raw, captures = args.pop('local_root'), args['captures']
    file_of = lambda name: next(raw.glob(f'bodies/sha256/*/{digests[name].hex()}*'))
    rel_key = lambda name: file_of(name).relative_to(raw).as_posix()

    # Add a higher-priority '' capture row for multicopy that is NOT in the bucket listing,
    # while keeping the .gz capture row that IS in the bucket listing (both MD5-less).
    cap_table = pq.read_table(captures)
    cap_rows = cap_table.to_pylist()
    for row in cap_rows:
        row['stored_md5'] = None
        if row['sha256'] == digests['sizeless']:
            row['stored_bytes'] = None
    gz_row = next(r for r in cap_rows if r['sha256'] == digests['multicopy'])
    plain_missing_row = dict(
        gz_row,
        receipt_key='receipts/unlisted-plain.jsonl',
        stored_suffix='',
        stored_bytes=len(HTML),
    )
    pq.write_table(pa.Table.from_pylist([*cap_rows, plain_missing_row], schema=cap_table.schema), captures)

    # Listing contains multicopy's .gz object AND sizeless's object (even though captures had stored_bytes=None).
    gz_bytes = file_of('multicopy').read_bytes()
    sz_bytes = file_of('sizeless').read_bytes()
    listing_rows = [
        {'key': rel_key('multicopy'), 'size': len(gz_bytes), 'etag': '"' + hashlib.md5(gz_bytes).hexdigest() + '"'},
        {'key': rel_key('sizeless'), 'size': len(sz_bytes), 'etag': '"' + hashlib.md5(sz_bytes).hexdigest() + '"'},
    ]
    listing_path = tmp_path / 'listing.parquet'
    pq.write_table(pa.Table.from_pylist(listing_rows, schema=body_text.LISTING_SCHEMA), listing_path)

    monkeypatch.setattr(body_text, '_observed_etag', lambda *_a, **_k: (_ for _ in ()).throw(AssertionError('probed')))

    with Origin(raw) as origin:
        report = body_text.run(**args, origin=origin.url, body_listing=listing_path, work=tmp_path / 'run', execute=True)

    assert report['status'] == 'pending'
    [batch] = report['batches']
    # multicopy succeeded via .gz fallback; sizeless refused as missing_pins (not fetched!)
    assert batch['body_text_rows'] == 1
    assert batch['missing_pins'] == 1
    assert batch['pending_reads'] == 0
    assert [req for req, _ in origin.requests] == ['/' + rel_key('multicopy')]

    # Conflict in body_listing must NOT leave work-list.parquet behind!
    dup_path = tmp_path / 'dup.parquet'
    pq.write_table(pa.Table.from_pylist([listing_rows[0], listing_rows[0]], schema=body_text.LISTING_SCHEMA), dup_path)
    conflict_work = tmp_path / 'conflict-plan'
    with pytest.raises(ValueError, match='body_listing'):
        body_text.plan(captures=captures, engine=args['engine'], work=conflict_work,
                       decided_at=args['decided_at'], body_listing=dup_path)
    assert not (conflict_work / 'work-list.parquet').exists()


