"""Red/Green tests for bounded, verified document body reading and snippet search (ct-o7t4)."""
import asyncio
from collections.abc import Callable
from contextlib import contextmanager
import gzip
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import shutil
from threading import Thread
import time

from fastmcp import Client
import pyarrow.parquet as pq
import pytest

from congressional_explorer_mcp.models import DocumentQuery, ExplorerError, MAX_BYTES
from congressional_explorer_mcp.reader import Reader
from congressional_explorer_mcp.release import encoded, prepare
from congressional_explorer_mcp.server import create_server
from conftest import CURRENT, manifest, replace_rows


def make_pdf_bytes(pages: list[str]) -> bytes:
    """Build a valid multi-page PDF using standard PDF objects and xref table."""
    def esc(text: str) -> bytes:
        return text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)').encode('latin-1')

    objects: list[bytes] = []
    # 1: Catalog, 2: Pages, 3: Font
    objects.append(b'<< /Type /Catalog /Pages 2 0 R >>')
    kids = ' '.join(f'{4 + 2 * i} 0 R' for i in range(len(pages)))
    objects.append(f'<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>'.encode('ascii'))
    objects.append(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')

    for i, page_text in enumerate(pages):
        page_obj_num = 4 + 2 * i
        content_obj_num = page_obj_num + 1
        lines = page_text.split('\n')
        ops = [b'BT /F1 12 Tf 72 720 Td']
        for idx, line in enumerate(lines):
            if idx > 0:
                ops.append(b'0 -16 Td')
            ops.append(b'(' + esc(line) + b') Tj')
        ops.append(b'ET')
        stream = b'\n'.join(ops)
        page_dict = (
            f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] '
            f'/Resources << /Font << /F1 3 0 R >> >> /Contents {content_obj_num} 0 R >>'
        ).encode('ascii')
        content_dict = f'<< /Length {len(stream)} >>\nstream\n'.encode('ascii') + stream + b'\nendstream'
        objects.append(page_dict)
        objects.append(content_dict)

    buf = io.BytesIO()
    buf.write(b'%PDF-1.4\n')
    offsets = [0]
    for idx, obj in enumerate(objects, start=1):
        offsets.append(buf.tell())
        buf.write(f'{idx} 0 obj\n'.encode('ascii'))
        buf.write(obj)
        buf.write(b'\nendobj\n')
    xref_pos = buf.tell()
    buf.write(f'xref\n0 {len(objects) + 1}\n'.encode('ascii'))
    buf.write(b'0000000000 65535 f \n')
    for off in offsets[1:]:
        buf.write(f'{off:010d} 00000 n \n'.encode('ascii'))
    buf.write(
        f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n'.encode('ascii')
    )
    return buf.getvalue()


@contextmanager
def local_archive_server(routes: dict[str, bytes | Callable]):
    requests: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            entry = routes.get(self.path)
            if callable(entry):
                entry(self)
                return
            if entry is None:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header('Content-Length', str(len(entry)))
            self.end_headers()
            self.wfile.write(entry)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', requests
    finally:
        server.shutdown()
        server.server_close()


def _prepare_body_fixture(tmp_path: Path, specs: list[dict], archive_origin: str | None):
    """Build a release fixture where the first N document rows have custom formats, digests, and suffixes."""
    root = tmp_path / 'release'
    shutil.copytree(CURRENT, root)

    def update_list(rows):
        for i, spec in enumerate(specs):
            rows[i].update(
                filename=spec.get('filename', rows[i]['filename']),
                title=spec.get('title', rows[i]['title']),
                format=spec.get('format', rows[i]['format']),
                hidden=False,
            )

    def update_detail(rows):
        for i, spec in enumerate(specs):
            rows[i].update(
                saved_body=spec.get('saved_body', rows[i]['saved_body']),
                saved_suffix=spec.get('saved_suffix', rows[i]['saved_suffix']),
                saved_media_type=spec.get('saved_media_type', rows[i]['saved_media_type']),
                saved_bytes=spec.get('saved_bytes', rows[i]['saved_bytes']),
            )

    replace_rows(root, 'list', update_list)
    replace_rows(root, 'detail', update_detail)
    links = pq.read_table(root / 'links.parquet').to_pylist()
    by_row = {}
    for item in links:
        by_row.setdefault(item['list_row'], item['link_key'].hex())
    selected_dir = tmp_path / 'selected'
    selected = prepare(selected_dir, manifest(root), archive_origin=archive_origin)
    return selected_dir, selected, by_row


def test_server_instructions_and_document_query_schema(tmp_path, phase2):
    selected = prepare(tmp_path, phase2, archive_origin='https://archive.example')
    q = DocumentQuery(
        release_id=selected['release_id'],
        link_key='11' * 8,
        section='text',
        query='burn pits',
        page=2,
        offset=10,
        max_chars=4000,
    )
    assert q.section == 'text'
    assert q.query == 'burn pits'
    assert q.page == 2
    assert q.offset == 10
    assert q.max_chars == 4000

    mcp = create_server(selected, data_dir=tmp_path)
    assert "get_document(section='text')" in mcp.instructions
    assert 'does not read document bodies' not in mcp.instructions

    async def run():
        async with Client(mcp) as client:
            tools = {t.name: t for t in await client.list_tools()}
            assert 'text' in tools['get_document'].description

    asyncio.run(run())


def test_get_document_text_reads_pdf_gzip_html_xml_and_plain_text_and_caches(tmp_path):
    pdf_raw = make_pdf_bytes([
        'Page One: Witness Statement of John Ray III on FTX corporate controls.',
        'Page Two: Detailed balance sheet findings and commingled customer assets.',
    ])
    pdf_sha = sha256(pdf_raw).digest()

    pdf_gz_inner = make_pdf_bytes([
        'Compressed PDF Page 1: VA burn pit airborne hazards posture.',
        'Compressed PDF Page 2: Scientific threshold and presumption analysis.',
    ])
    pdf_gz_raw = gzip.compress(pdf_gz_inner, mtime=0)
    pdf_gz_sha = sha256(pdf_gz_raw).digest()

    html_inner = (
        b'<html><head><title>Ignored Head</title><style>body{color:red}</style>'
        b'<script>alert(1)</script></head>'
        b'<body><h1>Committee Hearing Transcript</h1>'
        b'<p>Opening statement by Chair on whistleblowers &amp; safety.</p>'
        b'<p>Second paragraph with Boeing quality assurance details.</p></body></html>'
    )
    html_gz_raw = gzip.compress(html_inner, mtime=0)
    html_sha = sha256(html_gz_raw).digest()

    xml_inner = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<hearing><title>Legislative Markup</title>'
        b'<statement>Roll call vote on Amendment 4 passed unanimously.</statement></hearing>'
    )
    xml_gz_raw = gzip.compress(xml_inner, mtime=0)
    xml_sha = sha256(xml_gz_raw).digest()

    txt_raw = b'Plain text memorandum regarding inspector general subpoena compliance.\nLine two of memo.'
    txt_sha = sha256(txt_raw).digest()

    r2_inner = b'<html><body><p>R2 content-addressed gzip transcript where saved_body is uncompressed SHA-256.</p></body></html>'
    r2_uncompressed_sha = sha256(r2_inner).digest()
    r2_gz_wire = gzip.compress(r2_inner, mtime=0)

    routes = {
        f'/bodies/sha256/{pdf_sha.hex()[:2]}/{pdf_sha.hex()}.pdf': pdf_raw,
        f'/bodies/sha256/{pdf_gz_sha.hex()[:2]}/{pdf_gz_sha.hex()}.gz': pdf_gz_raw,
        f'/bodies/sha256/{html_sha.hex()[:2]}/{html_sha.hex()}.gz': html_gz_raw,
        f'/bodies/sha256/{xml_sha.hex()[:2]}/{xml_sha.hex()}.gz': xml_gz_raw,
        f'/bodies/sha256/{txt_sha.hex()[:2]}/{txt_sha.hex()}': txt_raw,
        f'/bodies/sha256/{r2_uncompressed_sha.hex()[:2]}/{r2_uncompressed_sha.hex()}.gz': r2_gz_wire,
    }

    with local_archive_server(routes) as (origin, requests):
        selected_dir, selected, by_row = _prepare_body_fixture(
            tmp_path,
            [
                dict(filename='Ray-Testimony.pdf', title='John Ray Statement', format='pdf',
                     saved_body=pdf_sha, saved_suffix='.pdf', saved_media_type='application/pdf', saved_bytes=len(pdf_raw)),
                dict(filename='VA-Burn-Pits.pdf', title='VA Testimony', format='pdf',
                     saved_body=pdf_gz_sha, saved_suffix='.gz', saved_media_type='application/pdf', saved_bytes=len(pdf_gz_raw)),
                dict(filename='CHRG-118shrg1.htm', title='Boeing Hearing HTML', format='html',
                     saved_body=html_sha, saved_suffix='.gz', saved_media_type='text/html', saved_bytes=len(html_gz_raw)),
                dict(filename='Markup.xml', title='Committee XML', format='xml',
                     saved_body=xml_sha, saved_suffix='.gz', saved_media_type='application/xml', saved_bytes=len(xml_gz_raw)),
                dict(filename='Memo.txt', title='Staff Memo', format='text',
                     saved_body=txt_sha, saved_suffix='', saved_media_type='text/plain', saved_bytes=len(txt_raw)),
                dict(filename='R2-Transcript.htm', title='R2 Gzip HTML', format='html',
                     saved_body=r2_uncompressed_sha, saved_suffix='.gz', saved_media_type='text/html', saved_bytes=len(r2_inner)),
            ],
            archive_origin=origin,
        )

        async def run():
            async with Client(create_server(selected, data_dir=selected_dir)) as client:
                async def get_doc(**kwargs):
                    return (await client.call_tool('get_document', {'query': kwargs})).data

                # 0. Verify DuckDB worker remains air-gapped for arbitrary SQL while parent fetches bodies
                sql_err = await client.call_tool(
                    'query_sql',
                    {'query': {'sql': f"SELECT * FROM read_csv_auto('{origin}/bodies/sha256/{txt_sha.hex()[:2]}/{txt_sha.hex()}')"}},
                    raise_on_error=False,
                )
                assert sql_err.is_error

                # 1. Uncompressed PDF full text, single page, offset/max_chars, and snippet search
                full_pdf = await get_doc(release_id=selected['release_id'], link_key=by_row[0], section='text')
                assert full_pdf['page_count'] == 2
                assert 'John Ray III' in full_pdf['text']
                assert 'commingled customer assets' in full_pdf['text']

                page2 = await get_doc(release_id=selected['release_id'], link_key=by_row[0], section='text', page=2)
                assert page2['page'] == 2
                assert 'commingled customer assets' in page2['text']
                assert 'John Ray III' not in page2['text']

                sliced = await get_doc(release_id=selected['release_id'], link_key=by_row[0], section='text', page=1, offset=10, max_chars=25)
                assert len(sliced['text']) == 25
                assert sliced['has_more'] is True
                assert sliced['next_offset'] == 35

                search_hit = await get_doc(release_id=selected['release_id'], link_key=by_row[0], section='text', query='commingled')
                assert search_hit['match_count'] == 1
                assert search_hit['matches'][0]['page'] == 2
                assert 'commingled customer assets' in search_hit['matches'][0]['snippet']

                # Cache verification: 4 calls to row 0 only made 1 HTTP request and wrote <data_dir>/bodies/<sha>.json
                cache_file = selected_dir / 'bodies' / f'{pdf_sha.hex()}.json'
                assert cache_file.is_file()
                assert requests.count(f'/bodies/sha256/{pdf_sha.hex()[:2]}/{pdf_sha.hex()}.pdf') == 1

                # 2. Gzip-compressed PDF (.pdf.gz)
                gz_pdf = await get_doc(release_id=selected['release_id'], link_key=by_row[1], section='text', query='burn pit')
                assert gz_pdf['page_count'] == 2
                assert gz_pdf['match_count'] == 1
                assert gz_pdf['matches'][0]['page'] == 1
                assert 'airborne hazards' in gz_pdf['text']

                # 3. HTML (.gz) strips script/style and unescapes entities
                html_doc = await get_doc(release_id=selected['release_id'], link_key=by_row[2], section='text')
                assert 'whistleblowers & safety' in html_doc['text']
                assert 'Boeing quality assurance' in html_doc['text']
                assert 'alert(1)' not in html_doc['text']
                assert 'color:red' not in html_doc['text']

                # 4. XML (.gz)
                xml_doc = await get_doc(release_id=selected['release_id'], link_key=by_row[3], section='text')
                assert 'Amendment 4 passed unanimously' in xml_doc['text']

                # 5. Plain text
                txt_doc = await get_doc(release_id=selected['release_id'], link_key=by_row[4], section='text')
                assert 'inspector general subpoena compliance' in txt_doc['text']

                # 6. R2 content-addressed gzip where saved_body is uncompressed SHA-256
                r2_doc = await get_doc(release_id=selected['release_id'], link_key=by_row[5], section='text')
                assert 'R2 content-addressed gzip transcript' in r2_doc['text']

        asyncio.run(run())


def test_get_document_text_fails_closed_on_security_and_integrity_faults(tmp_path):
    valid_pdf = make_pdf_bytes(['Verified page text'])
    expected_sha = sha256(valid_pdf).digest()
    wrong_bytes = make_pdf_bytes(['Tampered body text'])

    # Small gzip bomb that decompresses to 20 MiB of zeros
    bomb_raw = gzip.compress(b'A' * (20 << 20), mtime=0)
    bomb_sha = sha256(bomb_raw).digest()

    binary_raw = b'\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom'
    binary_sha = sha256(binary_raw).digest()

    routes = {
        # Tampered content at expected_sha path
        f'/bodies/sha256/{expected_sha.hex()[:2]}/{expected_sha.hex()}.pdf': wrong_bytes,
        # Decompression bomb at bomb_sha path
        f'/bodies/sha256/{bomb_sha.hex()[:2]}/{bomb_sha.hex()}.gz': bomb_raw,
        # Binary mp4 payload
        f'/bodies/sha256/{binary_sha.hex()[:2]}/{binary_sha.hex()}': binary_raw,
    }

    with local_archive_server(routes) as (origin, _):
        selected_dir, selected, by_row = _prepare_body_fixture(
            tmp_path,
            [
                # Row 0: SHA-256 mismatch
                dict(filename='Tampered.pdf', format='pdf', saved_body=expected_sha, saved_suffix='.pdf',
                     saved_media_type='application/pdf', saved_bytes=len(valid_pdf)),
                # Row 1: Decompression bomb
                dict(filename='Bomb.txt', format='text', saved_body=bomb_sha, saved_suffix='.gz',
                     saved_media_type='text/plain', saved_bytes=len(bomb_raw)),
                # Row 2: Unsupported binary format
                dict(filename='Video.mp4', format='mp4', saved_body=binary_sha, saved_suffix='',
                     saved_media_type='video/mp4', saved_bytes=len(binary_raw)),
                # Row 3: Missing saved_body
                dict(filename='MissingBody.pdf', format='pdf', saved_body=None, saved_suffix='',
                     saved_media_type='application/pdf', saved_bytes=0),
            ],
            archive_origin=origin,
        )

        reader = Reader(selected)
        try:
            from congressional_explorer_mcp import body_reader
            # 1. SHA-256 mismatch fails closed without caching AND without calling parser
            with pytest.MonkeyPatch.context() as mp:
                def forbid_extract(*args, **kwargs):
                    raise AssertionError('extract_pages must not be invoked when SHA-256 verification fails')
                mp.setattr(body_reader, 'extract_pages', forbid_extract)
                with pytest.raises(ExplorerError, match='SHA-256|checksum|digest|mismatch'):
                    reader.get_document(dict(release_id=selected['release_id'], link_key=by_row[0], section='text'))
            assert not (selected_dir / 'bodies' / f'{expected_sha.hex()}.json').exists()

            # 2. Decompression bomb exceeding cap fails closed without caching
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(body_reader, 'MAX_BODY_BYTES', 1 << 20)
                with pytest.raises(ExplorerError, match='exceeds|size|limit'):
                    reader.get_document(dict(release_id=selected['release_id'], link_key=by_row[1], section='text'))
            assert not (selected_dir / 'bodies' / f'{bomb_sha.hex()}.json').exists()

            # 3. Unsupported binary format fails closed
            with pytest.raises(ExplorerError, match='Unsupported|format|binary'):
                reader.get_document(dict(release_id=selected['release_id'], link_key=by_row[2], section='text'))

            # 4. Missing saved_body / saved_url fails closed
            with pytest.raises(ExplorerError, match='no verified archived body|missing|absent'):
                reader.get_document(dict(release_id=selected['release_id'], link_key=by_row[3], section='text'))

            # 5. SSRF attempt outside archive_origin fails closed
            from congressional_explorer_mcp.body_reader import read_document_body
            target = reader.document_body_target(dict(release_id=selected['release_id'], link_key=by_row[0], section='text'))
            ssrf_target = dict(target, saved_url=f'http://evil.example/bodies/sha256/{expected_sha.hex()[:2]}/{expected_sha.hex()}.pdf')
            with pytest.raises(ExplorerError, match='archive_origin|origin'):
                read_document_body(ssrf_target, DocumentQuery(release_id=selected['release_id'], link_key=by_row[0], section='text'))
        finally:
            reader.close()


def test_get_document_text_respects_max_bytes_and_timeout(tmp_path):
    huge_text = ('Paragraph of congressional testimony with detailed analysis. ' * 3000).encode('utf-8')
    huge_gz = gzip.compress(huge_text, mtime=0)
    huge_sha = sha256(huge_gz).digest()

    slow_sha = sha256(b'slow body').digest()

    def slow_handler(handler):
        time.sleep(0.5)
        handler.send_response(200)
        handler.end_headers()
        handler.wfile.write(b'slow body')

    routes = {
        f'/bodies/sha256/{huge_sha.hex()[:2]}/{huge_sha.hex()}.gz': huge_gz,
        f'/bodies/sha256/{slow_sha.hex()[:2]}/{slow_sha.hex()}': slow_handler,
    }

    with local_archive_server(routes) as (origin, _):
        selected_dir, selected, by_row = _prepare_body_fixture(
            tmp_path,
            [
                dict(filename='Huge.txt', format='text', saved_body=huge_sha, saved_suffix='.gz',
                     saved_media_type='text/plain', saved_bytes=len(huge_gz)),
                dict(filename='Slow.txt', format='text', saved_body=slow_sha, saved_suffix='',
                     saved_media_type='text/plain', saved_bytes=9),
            ],
            archive_origin=origin,
        )

        reader = Reader(selected)
        try:
            res = reader.get_document(dict(
                release_id=selected['release_id'],
                link_key=by_row[0],
                section='text',
                max_chars=65536,
            ))
            assert len(encoded(res)) <= MAX_BYTES
            assert res['has_more'] is True
        finally:
            reader.close()

        async def run_timeout():
            async with Client(create_server(selected, data_dir=selected_dir, timeout=0.1)) as client:
                err = await client.call_tool(
                    'get_document',
                    {'query': dict(release_id=selected['release_id'], link_key=by_row[1], section='text')},
                    raise_on_error=False,
                )
                assert err.is_error
                assert 'timed out' in err.content[0].text.lower() or 'deadline' in err.content[0].text.lower() or 'timeout' in err.content[0].text.lower()

        asyncio.run(run_timeout())
